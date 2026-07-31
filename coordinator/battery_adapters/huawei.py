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

from ..charger_types import BatteryIntent
from ..power_control import async_write_power_setpoint, prepare_power_setpoint
from .base import BatteryControlAdapter

_LOGGER = logging.getLogger(__name__)


class HuaweiBatteryAdapter(BatteryControlAdapter):
    """Huawei battery control. Delegates forced charge to the
    existing :class:`HuaweiChargeAdapter` for backward compat."""

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
        await super()._write_force_discharge(0.0)
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
            self._last_intent = BatteryIntent.STOP_FORCE_CHARGE
            return
        if await self._stop_forcible():
            self._forcible_charging = False
            self._last_intent = BatteryIntent.STOP_FORCE_CHARGE
            return
        await self._charge_adapter.stop_forced_charge()
        self._forcible_charging = False
        self._last_intent = BatteryIntent.STOP_FORCE_CHARGE

    # ─── Helpers ───────────────────────────────────────────────

    async def _apply_discharge_limit(self, watts: float) -> None:
        if not self._discharge_control_entity:
            _LOGGER.debug(
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
        prepared = prepare_power_setpoint(
            self._hass, self._discharge_control_entity, watts
        )
        if prepared is None:
            return
        tolerance = 1.0 / prepared.scale_to_watts
        if abs(prepared.current_value - prepared.value) < tolerance:
            self._last_discharge_limit_w = watts
            return
        if await async_write_power_setpoint(
            self._hass,
            self._discharge_control_entity,
            watts,
            context="Huawei battery discharge limit",
        ):
            self._last_discharge_limit_w = watts
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
