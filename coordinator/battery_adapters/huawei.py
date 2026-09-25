"""HuaweiBatteryAdapter — Huawei SUN2000 + LUNA2000.

Wraps:
- Today's HuaweiChargeAdapter (forcible_charge_soc service) for
  command_force_charge / command_stop_force_charge
- The number.set_value path that BatteryProtectionMixin used for
  command_limit_discharge / command_normal

Brand quirks:
- LUNA2000 supports power-based forced charge (not just SOC ramp)
- Discharge limit entity is brand-specific (typically
  ``number.batteries_maximale_entladeleistung``)
- Force-charge service requires target_soc + power + duration
"""
from __future__ import annotations

import logging

from ..charger_types import BatteryIntent, ExportIntent
from ..power_control import async_write_power_setpoint_verbose
from .base import BatteryControlAdapter

from ...utils.log_gate import log_on_change

_LOGGER = logging.getLogger(__name__)


class HuaweiBatteryAdapter(BatteryControlAdapter):
    """Huawei battery control. Delegates forced charge to the
    existing :class:`HuaweiChargeAdapter` for backward compat."""

    # ── (#955) export control is SERVICE-shaped on huawei_solar ──────────
    _EXTERNAL_MODES = ("di active scheduling", "remote scheduling")

    def _export_readback_entity(self) -> str:
        """The huawei_solar ``*_active_power_control`` sensor — configured, or
        found in the entity registry (review of the first cut: the config key
        is never written by the flow, so a config-only read was dead code and
        the guard WOULD have written under DI Active Scheduling)."""
        ent = str(self._config.get("export_control_readback_entity", "") or "")
        if ent:
            return ent
        try:
            from homeassistant.helpers import entity_registry as er
            reg = er.async_get(self._hass)
            for e in reg.entities.values():
                if (str(getattr(e, "platform", "")) == "huawei_solar"
                        and "active_power_control" in str(e.entity_id)):
                    return str(e.entity_id)
        except Exception:  # noqa: BLE001 — no registry, no read-back
            pass
        return ""

    #: States that are the absence of an answer, not an answer.
    _UNREAD = ("", "unavailable", "unknown", "none")

    def _export_mode_read(self):
        """The inverter's active-power mode, or ``None`` for UNREAD.

        Three states, never two: a missing entity and an ``unavailable`` one
        are both "I could not ask", and the caller must not fold that into
        "no". `.175`'s readback sensor sat ``unavailable`` for two hours on
        17.09 while the inverter was under DI scheduling the whole time.
        """
        ent = self._export_readback_entity()
        st = self._hass.states.get(ent) if ent else None
        if st is None:
            return None
        mode = str(getattr(st, "state", "") or "").strip()
        return None if mode.lower() in self._UNREAD else mode

    def _external_scheduling(self):
        """Is the inverter under an operator's digital-input / remote schedule?

        ``True`` / ``False`` / ``None`` — a zero-export write REPLACES this
        mode rather than sitting beside it, so an unreadable mode is not
        permission. It used to be: ``unavailable`` matched none of
        ``_EXTERNAL_MODES`` and the guard cut as if the inverter were free.
        """
        mode = self._export_mode_read()
        if mode is None:
            return None
        return any(m in mode.lower() for m in self._EXTERNAL_MODES)

    def _export_device_id(self) -> str:
        """The INVERTER device — not the battery one every other call uses.

        `huawei_solar` splits its services by device TYPE: `forcible_charge`
        resolves a battery (`.../battery_1`), while the feed-in verbs go
        through `get_inverter_data`, which raises `wrong_device_type` for
        anything that is not the inverter itself. `_inverter_device_id` is,
        despite its name, the BATTERY device — `_autodetect_battery_device`
        looks for `connected_energy_storage` or `/battery` on purpose (#523).

        Handing that to `set_zero_power_grid_connection` refuses EVERY time, on
        every zero-config Huawei install — which is the common one. It never
        surfaced because the unit tests stub the id and the rig ran in observer
        mode, where the call is never made. Found on PROD by reading the
        device registry rather than by firing at it: `Inverter` is
        `('huawei_solar', 'BT2470369058')`, `Battery 1` is
        `('huawei_solar', 'BT2470369058/battery_1')` with `via_device_id`
        pointing at the inverter.
        """
        cached = getattr(self, "_export_device_id_cache", None)
        if cached is not None:
            return cached
        found = self._resolve_inverter_device() or ""
        self._export_device_id_cache = found
        return found

    def _resolve_inverter_device(self) -> str | None:
        """The huawei_solar device the feed-in verbs accept.

        An explicit ``export_device_id`` wins. Otherwise: the battery hangs off
        its inverter via ``via_device_id``, which is the authoritative link;
        failing that (a solar-only Huawei), a root device whose identifier
        carries no ``/`` sub-part — optimizers and batteries both have one.
        """
        explicit = str(self._config.get("export_device_id", "") or "")
        if explicit:
            return explicit
        try:
            from homeassistant.helpers import device_registry as dr
            reg = dr.async_get(self._hass)
        except Exception:  # noqa: BLE001 — resolution never breaks a cycle
            return None

        def _hw_ident(dev):
            for ident in getattr(dev, "identifiers", ()) or ():
                try:
                    domain, value = ident
                except (ValueError, TypeError):
                    continue
                if domain == "huawei_solar":
                    return str(value)
            return None

        batt_id = str(getattr(self, "_inverter_device_id", "") or "")
        if batt_id:
            batt = reg.devices.get(batt_id)
            via = getattr(batt, "via_device_id", None) if batt else None
            if via and _hw_ident(reg.devices.get(via)) is not None:
                return via
        for dev in reg.devices.values():
            ident = _hw_ident(dev)
            if ident is None or "/" in ident:
                continue
            if getattr(dev, "via_device_id", None) is None:
                return dev.id
        return None

    async def command_limit_export(self, watts: float) -> None:
        device_id = self._export_device_id()
        if not device_id:
            raise NotImplementedError("no Huawei battery/inverter device found (inverter_device_id)")
        w = max(0.0, float(watts))
        if self._last_export_limit_w is not None and abs(self._last_export_limit_w - w) < 1.0:
            return                       # #538 — a repeat is pure cost
        # The mode check comes AFTER the repeat check on purpose: a repeat of
        # what SEM already wrote replaces nothing, and SEM's own write is what
        # knocks the readback `unavailable` for ~60 s (live, 17.09 — every
        # write did it). Checked first, the cut would have refused itself.
        external = self._external_scheduling()          # True / False / None
        if external is not False and not bool(
                self._config.get("export_guard_override_external", False)):
            raise NotImplementedError(
                "inverter is under external scheduling — an operator's mode is "
                "not SEM's to replace"
                if external
                else "cannot read the inverter's active-power mode — refusing "
                     "to replace a mode SEM cannot see")
        # (#908) Capture what SEM is about to replace, BEFORE replacing it.
        self._capture_export_prior()
        if w <= 0.0:
            await self._hass.services.async_call(
                "huawei_solar", "set_zero_power_grid_connection", {"device_id": device_id})
        else:
            await self._hass.services.async_call(
                "huawei_solar", "set_maximum_feed_grid_power",
                {"device_id": device_id, "power": int(round(w))})
        self._last_export_limit_w = w
        self._last_export_intent = ExportIntent.LIMIT

    #: Mode string (the readback sensor's own words) -> how to put it back.
    #: ``reset_maximum_feed_grid_power`` is NOT a universal restore: the
    #: integration documents it as *"Set Active Power Control to 'Unlimited'"*,
    #: so using it on an inverter that was under DI scheduling or a percent cap
    #: silently moves it to a THIRD state (#908 — hand back what SEM found).
    _RESTORE = {
        "unlimited": ("reset_maximum_feed_grid_power", None),
        "di active scheduling": ("set_di_active_power_scheduling", None),
        "zero power": ("set_zero_power_grid_connection", None),
    }

    def _capture_export_prior(self) -> None:
        """(#908) Read the inverter's CURRENT active-power mode, once per cut.

        Found on PROD, whose SUN2000 has sat in ``DI Active Scheduling`` — the
        grid operator's ripple-control receiver driving the dry contacts — for
        as long as its history goes back. ``ACTIVE_POWER_CONTROL_MODE`` is ONE
        register with five mutually exclusive values, so SEM's zero-export does
        not sit beside the operator's mode, it REPLACES it; and the old release
        would then have left the inverter ``Unlimited``, out of the operator's
        scheme entirely, with nothing in SEM aware of it.
        """
        if getattr(self, "_export_prior_mode", None) is not None:
            return          # already known — see the note on the release
        self._export_prior_mode = self._read_export_prior()

    def _read_export_prior(self):
        """The inverter's mode as ``(mode, {watt, percent})`` — a pure read,
        shared by the capture (which stores it) and the dry-run (which never
        does). UNREAD is recorded as UNREAD — never as the literal word
        "unavailable", which would read like a fifth inverter mode."""
        ent = self._export_readback_entity()
        st = self._hass.states.get(ent) if ent else None
        if st is None:
            return ("", None)
        attrs = getattr(st, "attributes", None) or {}
        mode = self._export_mode_read()
        return (mode or "",
                {"watt": attrs.get("maximum_power_watt"),
                 "percent": attrs.get("maximum_power_percent")})

    def export_release_recipe(self):
        """How to put the inverter back exactly as SEM found it."""
        adopted = getattr(self, "_adopted_recipe", None)
        if adopted:
            # A previous lifetime's capture beats anything readable now: the
            # inverter currently reports SEM's own cut, so re-deriving here
            # would restore "Zero Power" or fall back to "Unlimited".
            return dict(adopted)
        device_id = self._export_device_id()
        if not device_id:
            return None
        mode, nums = getattr(self, "_export_prior_mode", None) or ("", None)
        return self._recipe_for_prior(device_id, mode, nums)

    def _recipe_for_prior(self, device_id: str, mode, nums) -> dict:
        """The service that puts the inverter back into ``mode``."""
        key = str(mode).strip().lower()
        if key in self._RESTORE:
            service, _ = self._RESTORE[key]
            return {"domain": "huawei_solar", "service": service,
                    "data": {"device_id": device_id}}
        if key.startswith("limited to") and nums:
            if key.endswith("%") and nums.get("percent") is not None:
                return {"domain": "huawei_solar",
                        "service": "set_maximum_feed_grid_power_percent",
                        "data": {"device_id": device_id,
                                 "power_percentage": float(nums["percent"])}}
            if nums.get("watt") is not None:
                return {"domain": "huawei_solar",
                        "service": "set_maximum_feed_grid_power",
                        "data": {"device_id": device_id,
                                 "power": int(nums["watt"])}}
        return self._uncapped_recipe(device_id)

    @staticmethod
    def _uncapped_recipe(device_id: str) -> dict:
        """Take the cap off, in a dialect the hardware accepts.

        Measured on the reference SUN2000 (17.09.2026, .175 against the same
        inverter PROD talks to): ``reset_maximum_feed_grid_power`` — mode 0,
        ``Unlimited`` — does not land. The service returns cleanly and the
        register then reads ``DI Active Scheduling``: a value that call never
        wrote, so the inverter is choosing its own fallback rather than
        accepting mode 0. Tried from two different starting modes, three
        times. The same register through the same code path took mode 7
        (``set_maximum_feed_grid_power_percent(100)``) and mode 1 without
        complaint, and mode 7 then held untouched for eight minutes. 100 % of
        nominal IS the inverter's maximum, so the intent is identical to
        ``Unlimited`` and only the dialect differs.

        (The write itself takes 17-40 s either way — that is ordinary modbus
        latency on this link, not a symptom. The refusal is the OUTCOME.)

        So the last resort — prior unknown or unreadable — asks for no cap,
        never for ``Unlimited``. A prior that was READ as ``Unlimited`` still
        gets the plain reset: that is what the inverter itself reported.
        """
        return {"domain": "huawei_solar",
                "service": "set_maximum_feed_grid_power_percent",
                "data": {"device_id": device_id, "power_percentage": 100.0}}

    async def command_release_export(self) -> None:
        device_id = self._export_device_id()
        if not device_id:
            raise NotImplementedError("no Huawei battery/inverter device found (inverter_device_id)")
        # Put back the mode SEM found — NOT always 'Unlimited'. One register,
        # five mutually exclusive values (#908).
        recipe = self.export_release_recipe() or self._uncapped_recipe(device_id)
        await self._hass.services.async_call(
            recipe["domain"], recipe["service"], dict(recipe["data"]))
        # The prior is KEPT, not cleared. `huawei_solar` polls the
        # configuration registers on its own slow schedule — PROD's view of
        # this mode lagged a real write by 7m55s and then 14m21s (measured
        # 17.09.2026). Clearing it here means the NEXT cut re-reads, and a
        # cut → release → cut inside that window reads back SEM's OWN
        # `Zero Power` as the inverter's baseline. The release would then
        # "restore" the meter shut, and keep restoring it: a latch that
        # never lets the house export again, with SEM believing it had let
        # go. The operator's mode is a standing configuration, not a
        # per-cycle value, so the FIRST honest read is the one to keep.
        # (`export_release_recipe` already refuses to re-derive for exactly
        # this reason after a restart, via `_adopted_recipe`.)
        self._adopted_recipe = None
        self._last_export_limit_w = None
        self._last_export_intent = ExportIntent.RELEASE

    def export_dry_run(self, intent, watts: float) -> dict:
        """(#955) The verb's answer without the write — see the base class.

        Walks the SAME checks as ``command_limit_export`` in the same order
        (device, mode — the repeat check is skipped: a dry-run always shows
        the recipe), and for a release derives the recipe the way the real
        release would: the adopted one, else the captured prior, else — an
        observer rig has never cut — from what the readback says right now.
        """
        device_id = self._export_device_id()
        if not device_id:
            return {"service": None, "data": None,
                    "why": "no Huawei battery/inverter device found (inverter_device_id)"}
        if intent is ExportIntent.LIMIT:
            external = self._external_scheduling()          # True / False / None
            if external is not False and not bool(
                    self._config.get("export_guard_override_external", False)):
                return {"service": None, "data": None, "why": (
                    "inverter is under external scheduling — an operator's mode is "
                    "not SEM's to replace" if external else
                    "cannot read the inverter's active-power mode — refusing "
                    "to replace a mode SEM cannot see")}
            w = max(0.0, float(watts))
            if w <= 0.0:
                return {"service": "huawei_solar.set_zero_power_grid_connection",
                        "data": {"device_id": device_id}, "why": None}
            return {"service": "huawei_solar.set_maximum_feed_grid_power",
                    "data": {"device_id": device_id, "power": int(round(w))}, "why": None}
        recipe = self.export_release_recipe()
        if recipe is None or getattr(self, "_export_prior_mode", None) is None \
                and not getattr(self, "_adopted_recipe", None):
            mode, nums = self._read_export_prior()
            recipe = self._recipe_for_prior(device_id, mode, nums)
        return {"service": f"{recipe['domain']}.{recipe['service']}",
                "data": dict(recipe["data"]), "why": None}

    @classmethod
    def expected_operating_modes(cls):
        """(#845) SEM's whole model assumes the LUNA sits in
        maximise_self_consumption — the mode where ``forcible_charge`` /
        ``forcible_discharge_soc`` are proven to override cleanly. The other
        selector states (fully_fed_to_grid, time_of_use_luna2000,
        fixed_charge_discharge, adaptive) run the inverter's OWN schedule
        underneath SEM; whether the force services still bite there is
        UNVERIFIED (the issue's item 4 — a guided live test, not a guess)."""
        return {"maximise_self_consumption"}

    def __init__(self, hass, config: dict) -> None:
        super().__init__(hass, config)
        # Lazy import the existing forced-charge adapter so this
        # module's imports stay lightweight + the legacy adapter
        # can be deleted later without breaking the structural
        # plan.
        from .force_charge import HuaweiChargeAdapter
        self._charge_adapter = HuaweiChargeAdapter(hass, config)
        # Config keys for discharge limit
        self._discharge_control_entity = config.get(
            "battery_discharge_control_entity", "",
        )
        self._max_discharge_w = float(
            config.get("battery_max_discharge_power", 5000),
        )
        # Forced battery→grid discharge (#523). Real Huawei LUNA2000 has NO
        # "forcible discharge power" NUMBER entity — it's driven by the
        # ``huawei_solar.forcible_discharge_soc`` SERVICE (device_id +
        # target_soc + power), the discharge mirror of the forced-charge
        # service this adapter already uses. We override the base number-
        # write path to call that service when an inverter device_id is
        # configured; if instead a number entity is wired
        # (``battery_force_discharge_control_entity``) the base path is used.
        self._inverter_device_id = config.get("inverter_device_id", "")
        # Auto-detect the Huawei battery device when it isn't configured, so
        # forcible charge/discharge works with ZERO manual config (#523). The
        # huawei_solar services target the BATTERY device (identifier
        # ``.../connected_energy_storage`` or ``.../battery_<n>``), not the
        # inverter device.
        if not self._inverter_device_id:
            self._inverter_device_id = self._autodetect_battery_device() or ""
        # Target SOC (reserve floor) for the in-flight forced discharge.
        self._fd_floor_soc = 0.0
        # Whether a forcible discharge is currently active. The LUNA2000
        # BLOCKS if it gets stop_forcible_charge + another Modbus write
        # (e.g. the discharge-limit register) back-to-back in one cycle, so
        # every transition issues exactly ONE command and defers the rest to
        # the next cycle. This flag is the state that makes that possible.
        self._forcible_discharging = False
        # Whether a forcible CHARGE is currently active (started by SEM this
        # lifetime). Guards the startup orphan-clear from wrongly stopping a
        # charge that SEM itself issued this run (#589 Part C).
        self._forcible_charging = False
        # Stop-retry budget. Huawei Modbus writes are queued and can be
        # dropped / reordered under a flaky connection — a single
        # stop_forcible_charge sometimes doesn't land, leaving the battery
        # discharging. After exiting forcible we re-issue the (idempotent)
        # stop for a few extra cycles so it self-heals. forcible_discharge_soc
        # also self-terminates at target_soc=reserve, so this is belt-and-
        # braces over an already-bounded action.
        self._stop_retries = 0
        # #532 (PROD incident 2026-06-19): forcible_discharge_soc runs
        # AUTONOMOUSLY on the inverter until target_soc. A SEM restart / config
        # reload mid-discharge gives a fresh adapter ``_forcible_discharging =
        # False``, so ``_stop_forcible()`` returns early and never cancels the
        # in-flight op — the inverter drains the battery to the reserve floor
        # unsupervised (drained a PROD LUNA2000 80%→20% to grid). On the first
        # non-force-discharge cycle after startup we detect and cancel any
        # forcible op THIS adapter didn't start. One-shot; only consumed once
        # huawei_solar is actually loaded (so the status sensor is readable).
        self._startup_orphan_checked = False
        # H2 (review): shared across a fleet's adapters by the coordinator so a
        # multi-battery setup behind ONE inverter issues exactly one orphan
        # stop per device per startup (back-to-back stops block the LUNA2000).
        # Defaults to a private dict so a standalone adapter / unit test works.
        self._orphan_guard: dict = {}

    # ─── Capability ────────────────────────────────────────────

    @property
    def max_charge_power_w(self) -> float:
        return float(self._config.get("battery_max_charge_power", 5000))

    @property
    def max_discharge_power_w(self) -> float:
        return self._max_discharge_w

    @property
    def supports_forced_charge(self) -> bool:
        return True

    @property
    def supports_forced_discharge(self) -> bool:
        # Service-based (inverter device_id) OR a wired number entity.
        return bool(self._inverter_device_id) or bool(self._force_discharge_entity)

    # ─── Forced discharge: huawei_solar service (no number entity) ──────

    async def command_force_discharge(
        self, power_w: float, floor_soc: float,
    ) -> None:
        """Sell to grid via ``huawei_solar.forcible_discharge_soc`` —
        discharge at ``power_w`` until SOC falls to ``floor_soc`` (the
        reserve). Issued ONCE; while already discharging at ~this power the
        call is a no-op (re-hammering the inverter blocks the LUNA2000)."""
        # #532: we are (re)asserting the forcible op ourselves — opt out of the
        # startup orphan-stop so a restart that resumes arbitrage continues
        # selling instead of stopping then restarting.
        self._startup_orphan_checked = True
        self._fd_floor_soc = floor_soc
        watts = max(0.0, min(float(power_w), self._max_discharge_w))
        if not self._inverter_device_id:
            # No service → number-entity fallback (a user who wired one).
            await super().command_force_discharge(power_w, floor_soc)
            self._forcible_discharging = bool(self._force_discharge_entity)
            return
        if self._forcible_discharging and abs(watts - self._last_force_discharge_w) < 100.0:
            self._last_intent = BatteryIntent.FORCE_DISCHARGE
            return
        try:
            await self._hass.services.async_call(
                "huawei_solar", "forcible_discharge_soc",
                {
                    "device_id": self._inverter_device_id,
                    "target_soc": int(floor_soc),
                    "power": int(watts),
                }, blocking=True,
            )
            self._forcible_discharging = True
            self._last_force_discharge_w = watts
            _LOGGER.info(
                "Huawei battery: forcible discharge %.0f W to SOC %d%% "
                "(manual sell / arbitrage)", watts, int(floor_soc),
            )
            self._last_error = None
            self._last_intent = BatteryIntent.FORCE_DISCHARGE
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Huawei battery: forcible_discharge_soc failed: %s", e,
            )
            self._last_error = f"forcible_discharge_soc failed: {e}"
            # _last_intent intentionally NOT updated — retry next cycle (#589)

    async def command_stop_force_discharge(self) -> None:
        # #532: also catch an orphan op from a prior instance (the flag-gated
        # _stop_forcible alone misses it on a fresh adapter).
        # #589: record STOP_FORCE_DISCHARGE only when the stop landed.
        cleared = await self._maybe_clear_startup_orphan()
        if not cleared:
            stopped = await self._stop_forcible()
            if not stopped and self._forcible_discharging:
                # Stop didn't land — leave _last_intent unchanged so the
                # next cycle re-issues. _stop_forcible already logged.
                self._last_error = "stop_forcible failed"
                return
        self._last_error = None
        self._last_intent = BatteryIntent.STOP_FORCE_DISCHARGE

    async def _stop_forcible(self) -> bool:
        """Stop an active forcible discharge — ONE Modbus command, nothing
        else. Returns True if it issued a stop, so the caller does NOTHING
        else this cycle (a second write right after stop_forcible_charge
        makes the LUNA2000 ignore the stop / block). No-op when not
        currently forcing, so it's safe to call from every command."""
        if not self._forcible_discharging:
            return False
        ok = await self._issue_stop()
        if not ok and self._inverter_device_id:
            return False  # service raised — keep forcing, retry next cycle
        self._forcible_discharging = False
        self._last_force_discharge_w = 0.0
        # Re-issue the stop on the next couple of NORMAL cycles — a single
        # Modbus stop can be dropped/reordered on a flaky link.
        self._stop_retries = 2
        return True

    async def _issue_stop(self) -> bool:
        """Raw stop (service or number-entity). True on success."""
        if self._inverter_device_id:
            try:
                await self._hass.services.async_call(
                    "huawei_solar", "stop_forcible_charge",
                    {"device_id": self._inverter_device_id}, blocking=True,
                )
                _LOGGER.info("Huawei battery: stopped forcible discharge")
                return True
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "Huawei battery: stop_forcible_charge failed: %s", e,
                )
                return False
        await super()._zero_setpoint()   # the one #523 door (#1005)
        return True

    def _forcible_status_reading(self) -> str:
        """Classify the ``huawei_solar`` "Forcible charge/discharge" status
        sensor (#532). Returns one of:

        * ``"active"``  — an op is running (charge or discharge).
        * ``"stopped"`` — a forcible sensor is readable and says stopped/idle.
        * ``"pending"`` — a forcible sensor exists but is still
          unknown/unavailable (just after the integration loads — don't act
          yet, the next cycle will have a real reading).
        * ``"absent"``  — no forcible sensor at all (e.g. a number-entity
          Huawei, or a non-storage inverter).

        Brand-agnostic on the entity id (installs name it
        ``sensor.batteries_forcible_charge`` / ``battery_<n>_forcible_*`` /
        …): scan the ``sensor`` domain for any ``forcible`` entity.
        """
        try:
            states = self._hass.states.async_all("sensor")
        except Exception:  # noqa: BLE001
            return "absent"
        found = False
        any_readable = False
        try:
            for st in states:
                eid = getattr(st, "entity_id", "") or ""
                if "forcible" not in eid:
                    continue
                found = True
                val = str(getattr(st, "state", "") or "").strip().lower()
                if val in ("", "unknown", "unavailable", "none"):
                    continue  # this one not ready — keep scanning
                any_readable = True
                if "stop" not in val and val != "idle":
                    return "active"
        except TypeError:
            # states wasn't iterable (MagicMock in a unit test) — can't tell.
            return "absent"
        if not found:
            return "absent"
        return "stopped" if any_readable else "pending"

    def _forcible_status_active(self) -> bool:
        """True iff a forcible op is actively running (#532)."""
        return self._forcible_status_reading() == "active"

    async def _maybe_clear_startup_orphan(self) -> bool:
        """Cancel a forcible op (charge OR discharge) left running by a prior
        SEM instance (#532, #589 Part C).

        One-shot, consumed only once ``huawei_solar`` is loaded so the status
        sensor is readable (the same startup race the adapter self-heal guards
        against). Issues exactly ONE ``stop_forcible_charge`` if an op is
        active that THIS adapter didn't start. Returns True when it issued the
        stop so the caller defers other Modbus writes this cycle (back-to-back
        writes after a stop block the LUNA2000).

        Conservative: if the status sensor is unreadable or absent, we do
        NOTHING (fail-safe). Only issues a stop command — never a new
        charge/discharge. Does NOT touch generic/Sessy setpoint boot-clear.
        # TODO(#589 3b): extend to generic adapter setpoint-based orphan-clear."""
        if self._startup_orphan_checked:
            return False
        from . import _integration_loaded
        if not _integration_loaded(self._hass, "huawei_solar"):
            # Integration still coming up — re-check next cycle, don't burn
            # the one-shot on an unreadable sensor.
            return False
        status = self._forcible_status_reading()
        if status == "pending":
            # Sensor exists but hasn't polled a real value yet — wait one more
            # cycle so we don't miss an in-flight op to sensor lag.
            return False
        if self._forcible_discharging or self._forcible_charging:
            # We started this op in the current lifetime — the normal path
            # owns it; nothing orphaned.
            self._startup_orphan_checked = True
            return False
        if status != "active":
            self._startup_orphan_checked = True
            return False
        # H2 (review): in a multi-battery fleet sharing ONE inverter, a sibling
        # adapter may have already issued the stop for this device THIS cycle.
        # Firing a second back-to-back stop_forcible_charge blocks the LUNA2000
        # (the very failure the fix guards against) — defer to the sibling.
        dev = self._inverter_device_id
        if dev and self._orphan_guard.get(dev):
            self._startup_orphan_checked = True
            return False
        _LOGGER.warning(
            "Huawei battery: a forcible charge/discharge is active that SEM "
            "did not start (restart/reload mid-op?) — issuing stop so the "
            "inverter doesn't drain the battery to the floor unsupervised "
            "(#532)",
        )
        ok = await self._issue_stop()
        if not ok:
            # H1 (review): the stop didn't land (flaky Modbus). Do NOT consume
            # the one-shot — re-detect and retry next cycle — but still defer
            # other writes this cycle (no back-to-back Modbus after a stop).
            self._stop_retries = 2
            return True
        if dev:
            self._orphan_guard[dev] = True
        self._startup_orphan_checked = True
        self._forcible_discharging = False
        self._last_force_discharge_w = 0.0
        # Belt-and-braces re-issue on the next couple of cycles (flaky Modbus).
        self._stop_retries = 2
        return True

    # ─── Commands ──────────────────────────────────────────────

    async def command_normal(self) -> None:
        """Restore discharge to max — undoes any LIMIT_DISCHARGE in effect.
        If exiting a forcible discharge, issue ONLY the stop this cycle (the
        discharge-limit write is deferred to the next cycle — back-to-back
        Modbus writes after stop_forcible_charge block the LUNA2000)."""
        if await self._maybe_clear_startup_orphan():
            self._last_intent = BatteryIntent.NORMAL
            return
        # #589 3b (review HIGH): command_normal is the teardown / return-to-
        # normal primitive, but a forcible CHARGE is stopped via the charge
        # adapter — NOT _stop_forcible (which only cancels a forcible DISCHARGE).
        # Without this, a reload mid-force-charge left the LUNA2000 charging
        # until the next boot's orphan-clear (~45s). Guarded on _forcible_charging
        # so it's a no-op in the common NORMAL cycle; defer other writes this
        # cycle (back-to-back Modbus writes after a stop block the LUNA2000).
        # Honest-retry: on failure leave the flag + intent so the next cycle
        # re-issues instead of falsely reporting NORMAL.
        if self._forcible_charging:
            try:
                await self._charge_adapter.stop_forced_charge()
            except Exception as e:  # noqa: BLE001
                self._last_error = f"stop_forced_charge failed: {e}"
                return
            self._forcible_charging = False
            self._last_intent = BatteryIntent.NORMAL
            return
        if await self._stop_forcible():
            self._last_intent = BatteryIntent.NORMAL
            return
        # Self-healing stop retries (flaky Modbus can drop a single stop).
        if self._stop_retries > 0:
            self._stop_retries -= 1
            await self._issue_stop()
            self._last_intent = BatteryIntent.NORMAL
            return
        await self._apply_discharge_limit(self._max_discharge_w)
        self._last_intent = BatteryIntent.NORMAL

    async def command_limit_discharge(self, watts: float) -> None:
        """Apply the 1:1 home-consumption protection limit.
        Honours 100 W hysteresis to avoid log spam."""
        # Cancel any orphan forcible op left by a prior instance first (#532).
        if await self._maybe_clear_startup_orphan():
            self._last_intent = BatteryIntent.LIMIT_DISCHARGE
            return
        # Forced discharge is mutually exclusive with limiting it (#523).
        # If forcing, stop cleanly this cycle and apply the limit next cycle.
        if await self._stop_forcible():
            self._last_intent = BatteryIntent.LIMIT_DISCHARGE
            return
        # Clamp to [0, max]
        watts = max(0.0, min(watts, self._max_discharge_w))
        # Hysteresis (matches battery_protection.py:106-109)
        if (self._last_discharge_limit_w >= 0
                and abs(watts - self._last_discharge_limit_w) < 100.0):
            self._last_intent = BatteryIntent.LIMIT_DISCHARGE
            return
        await self._apply_discharge_limit(watts)
        self._last_intent = BatteryIntent.LIMIT_DISCHARGE

    async def command_force_charge(
        self, target_soc: float, charge_power_w: float, duration_min: int,
    ) -> None:
        """Delegate to HuaweiChargeAdapter.start_forced_charge."""
        # Cancel an orphan forcible op from a prior instance first (#532) —
        # never start a charge on top of an in-flight discharge.
        if await self._maybe_clear_startup_orphan():
            self._last_intent = BatteryIntent.FORCE_CHARGE
            return
        # Can't force-charge and force-discharge at once (#523). If a forcible
        # discharge is active, STOP it this cycle and start the charge next
        # cycle — never discharge-stop + charge-start back-to-back.
        if await self._stop_forcible():
            self._last_intent = BatteryIntent.FORCE_CHARGE
            return
        from .force_charge import ChargeCommand, ChargeCommandStatus
        cmd = ChargeCommand(
            target_soc=target_soc,
            max_power_w=charge_power_w,
            duration_minutes=duration_min,
        )
        status = await self._charge_adapter.start_forced_charge(cmd)
        if status.status is ChargeCommandStatus.FAILED:
            self._last_error = f"start_forced_charge failed: {status.message}"
            # _last_intent intentionally NOT updated — retry next cycle (#589)
        else:
            self._forcible_charging = True  # guard orphan-clear from stopping us
            self._last_error = None
            self._last_intent = BatteryIntent.FORCE_CHARGE

    async def command_stop_force_charge(self) -> None:
        # STOP any forced op — also clears an arbitrage discharge (#523),
        # so the scheduler's idle/target-reached verdict can't leave the
        # battery silently selling to grid. Forcible discharge and forced
        # charge share the same huawei stop service, so one clean stop covers
        # both; only fall through to the charge adapter when not forcing.
        if await self._maybe_clear_startup_orphan():
            self._forcible_charging = False
            self._last_error = None
            self._last_intent = BatteryIntent.STOP_FORCE_CHARGE
            return
        if await self._stop_forcible():
            self._forcible_charging = False
            self._last_error = None
            self._last_intent = BatteryIntent.STOP_FORCE_CHARGE
            return
        # (#757) Everything above is a real edge — an orphan cleared, a
        # forcible discharge cancelled. Below is the steady state, and
        # the steady state is where the storm lived: hours of "stop" for
        # a battery that stopped at the first one. Ask the shared
        # predicate, then honour its contract — record the intent ONLY on
        # a stop that landed, so a dropped Modbus write is retried next
        # cycle instead of being remembered as a success.
        if self._force_charge_already_stopped():
            return
        from .force_charge import ChargeCommandStatus
        status = await self._charge_adapter.stop_forced_charge()
        if getattr(status, "status", None) is ChargeCommandStatus.FAILED:
            self._last_error = (
                f"stop_forced_charge failed: {getattr(status, 'message', '')}"
            )
            return
        self._forcible_charging = False
        self._last_error = None
        self._last_intent = BatteryIntent.STOP_FORCE_CHARGE

    # ─── Helpers ───────────────────────────────────────────────

    async def _apply_discharge_limit(self, watts: float) -> None:
        if not self._discharge_control_entity:
            log_on_change(   # (#762) a standing config gap is one line, not 806/day
                _LOGGER, "no_discharge_entity", logging.DEBUG,
                "HuaweiBatteryAdapter: no battery_discharge_control_entity "
                "configured — skipping limit %.0f W", watts,
            )
            self._last_discharge_limit_w = watts
            return
        # Idempotency (#538): skip the Modbus write when the control entity
        # is already at this value. ``command_normal`` re-issues max every
        # cycle, and a redundant write on the single serial Modbus
        # connection is not free — it collides with the huawei_solar read
        # coordinators (transaction-ID mismatches + read timeouts observed
        # on PROD). Compare to the LIVE entity state so an external change
        # is still re-asserted; if the state is unknown/unavailable, write.
        # Self-heal window: if the inverter silently reverts the register,
        # the HA entity reflects the stale commanded value until huawei_solar
        # next polls it (~30-60s / 1-2 SEM cycles); the next cycle sees the
        # divergence and re-asserts. Bounded, and acceptable vs the per-cycle
        # Modbus flooding this guard removes.
        # (#900) The compare-to-live-state skip now lives in
        # ``async_write_power_setpoint`` itself, for every adapter.
        ok, wrote = await async_write_power_setpoint_verbose(
            self._hass,
            self._discharge_control_entity,
            watts,
            context="Huawei battery discharge limit",
        )
        if ok:
            self._last_discharge_limit_w = watts
            if wrote:
                # (#915) judged on the next cycle: did the register keep it?
                # Only a write that went OUT — not the #538 same-value skip.
                self._note_pending_write(self._discharge_control_entity, watts)
            _LOGGER.debug(
                "Huawei battery: discharge limit %.0f W → %s",
                watts, self._discharge_control_entity,
            )

    def _autodetect_battery_device(self) -> str | None:
        """Find the huawei_solar BATTERY device id that the
        ``forcible_*_soc`` services target — the combined
        ``connected_energy_storage`` device (preferred), else a per-battery
        device. Lets forcible charge/discharge work with zero manual config."""
        try:
            from homeassistant.helpers import device_registry as dr
            reg = dr.async_get(self._hass)
            fallback = None
            for dev in reg.devices.values():
                for ident in getattr(dev, "identifiers", ()) or ():
                    try:
                        domain, value = ident
                    except (ValueError, TypeError):
                        continue
                    if domain != "huawei_solar":
                        continue
                    v = str(value).lower()
                    if "connected_energy_storage" in v:
                        _LOGGER.info(
                            "Huawei battery device auto-detected: %s (%s)",
                            dev.id, value,
                        )
                        return dev.id
                    if "/battery" in v:
                        fallback = fallback or dev.id
            if fallback:
                _LOGGER.info("Huawei battery device auto-detected: %s", fallback)
            return fallback
        except Exception:  # noqa: BLE001 — detection must never break setup
            return None
