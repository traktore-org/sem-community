"""Internal force-charge actuation per brand (#624).

Moved from ``coordinator/battery_charge_adapter.py``: these classes are
NOT a public adapter surface any more — they are the brand-specific
force-charge implementation composed by the ``BatteryControlAdapter``
subclasses in this package (see huawei.py / goodwe.py / generic.py).
No **production** module outside ``battery_adapters/`` may import them — that
is what the arch test in test_battery_charge_scheduler.py enforces, and it
scans production packages only. Tests import them directly on purpose.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from homeassistant.core import HomeAssistant

from ...utils.log_gate import log_on_change
from .charge_record import ForcedChargeRecord
from .charge_select import (
    AWAY_FOR_S, SHOW_WITHIN_S, charge_option, permit_switch, read_select,
    select_setup)
from ...utils.select_option import listed_option
from .charge_target import ChargeTargetHold
from ..units import finite_float

_LOGGER = logging.getLogger(__name__)


class ChargeCommandStatus(Enum):
    """Status of a forced charge command."""

    IDLE = "idle"
    CHARGING = "charging"
    TARGET_REACHED = "target_reached"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


@dataclass
class ChargeCommand:
    """Parameters for a forced grid-to-battery charge command."""

    target_soc: float  # 0-100%
    max_power_w: float  # Max charge power in watts
    duration_minutes: int = 480  # Safety timeout (default 8h)


@dataclass
class ChargeStatus:
    """Current status of the battery charge adapter."""

    status: ChargeCommandStatus
    current_soc: float = 0.0
    target_soc: float = 0.0
    charge_power_w: float = 0.0
    message: str = ""


def _nothing_to_stop(why: str) -> ChargeStatus:
    """A stop with nothing to stop is DONE, not FAILED (#1005).

    Every ``stop_forced_charge`` below needs the actuator that its own
    ``start_forced_charge`` refuses to run without. When that actuator is not
    configured, no forced charge can be running, so the stop has nothing to
    send and is already complete.

    Reporting FAILED instead is what @RienduPre hit on 2× Sessy: the caller
    (``command_stop_force_charge``) treats FAILED as "transient — retry next
    cycle" and deliberately does NOT record the intent, which is the very
    thing the #757 flood guard reads. A fault that can never clear then turns
    honest retry into an endless one: the whole stop path ran on every cycle
    for 28 h — the #523 zero-write to the battery setpoint (refused by the
    device, so it spent the #840 strikes that withdraw battery-to-grid) and
    the strategy write back to self-consumption. A retry policy written for a
    dropped Modbus write was answering a config gap.

    So: a permanent, knowable "there is nothing to do" is IDLE and sends
    nothing. Only a real refusal by real hardware is FAILED.
    """
    return ChargeStatus(
        status=ChargeCommandStatus.IDLE,
        message=f"Nothing to stop — {why}",
    )


def _say_nothing_to_stop(adapter, why: str) -> ChargeStatus:
    """:func:`_nothing_to_stop`, said once per adapter.

    ``ChargeStatus.message`` is only ever surfaced on the FAILED branch, so
    without this the fix trades a false diagnostic line for no line at all
    and a battery with no force-charge actuator looks like a healthy one
    (found in review). Once, at INFO: it is a standing config fact, not an
    event (#762).
    """
    if not getattr(adapter, "_nothing_to_stop_said", False):
        adapter._nothing_to_stop_said = True
        _LOGGER.info(
            "Battery: asked to stop a forced charge, but %s — nothing can be "
            "forcing, so nothing is sent (#1005)", why,
        )
    return _nothing_to_stop(why)


class BatteryChargeAdapter(ABC):
    """Abstract base class for inverter-specific forced charge control."""

    #: (#1281) the record, read whole, does not name this battery
    not_started_by_sem: bool = False

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.config = config
        self._active = False
        self._target_soc: float = 0.0
        #: (#1180) the charge-target number as SEM found it. The coordinator
        #: hands every battery the entry's one hold; a stand-in gets its own.
        hold = config.get("charge_target_hold")
        self.target_hold = (
            hold if isinstance(hold, ChargeTargetHold)
            else ChargeTargetHold(
                hass, configured=(config.get("battery_target_soc_entity", ""),)))
        #: (#1181) the forced charges SEM started, across a restart. The
        #: coordinator hands every battery the entry's one record.
        record = config.get("forced_charge_record")
        self.charge_record = (record if isinstance(record, ForcedChargeRecord)
                              else ForcedChargeRecord())

    @property
    def is_active(self) -> bool:
        """Whether a forced charge session is currently active."""
        return self._active

    def charge_actuator(self) -> str:
        """(#1181) The entity this brand's start turns on and only its stop
        turns back, kept in the record — ``""`` when it has none."""
        return ""

    def _charging_state(self, state: str) -> bool:
        """(#1181) Does the actuator's state say a forced charge runs?"""
        return False

    def actuator_charging(self) -> "bool | None":
        """(#1181) True: the actuator reads a forced charge. False: it reads
        one of its other states. None: it cannot be read yet."""
        actuator = self.charge_actuator()
        try:
            st = self.hass.states.get(actuator) if actuator else None
        except Exception:  # noqa: BLE001
            st = None
        state = getattr(st, "state", None) if st is not None else None
        if not isinstance(state, str) or state in ("", "unknown", "unavailable"):
            return None
        return self._charging_state(state)

    def _battery(self) -> str:
        return str(self.config.get("battery_id", "") or "")

    async def adopt_running(self) -> bool:
        """(#1181) True when a charge SEM started for this battery is found
        still on, now: the record names this battery for the actuator, and
        the actuator still reads a charge. Such a charge is active from now on,
        so Off, the unload hand-back and the next decision stop it.

        Until the actuator can be read nothing is adopted, and this is asked
        again on the next cycle: a stop sent to an entity HA has not loaded
        yet is dropped without a word, and the name with it. An actuator
        that reads no charge drops the name: the charge has ended. Reads
        only, except that drop. Never raises."""
        if self._active or getattr(self, "_adoption_settled", False):
            return False                        # True only when adopted now
        actuator = self.charge_actuator()
        if not actuator:
            self._adoption_settled = True
            return False
        try:
            if not await self.charge_record.running(actuator, self._battery()):
                self._adoption_settled = True
                # (#1281) a record read whole that does not name this
                # battery: no charge on its actuator is SEM's to stop.
                self.not_started_by_sem = bool(
                    getattr(self.charge_record, "trusted", False))
                return False
            charging = self.actuator_charging()
            if charging is None:
                return False                    # not readable yet: next cycle
            if not charging and not await self._may_drop_stopped(actuator):
                return False                    # (#1377) the restore's first
            self._adoption_settled = True
            if not charging:
                await self.charge_record.stopped(actuator)
                return False
        except Exception:  # noqa: BLE001 — a record never costs a cycle
            _LOGGER.debug("forced charge record not read", exc_info=True)
            return False
        self._active = True
        _LOGGER.info("Battery: %s is still on from a forced charge SEM "
                     "started — SEM stops it unless the plan still wants it "
                     "(#1181)", actuator)
        return True

    async def _may_drop_stopped(self, actuator: str) -> bool:
        """(#1377) May adoption drop the name of an actuator that reads no
        charge? A brand that sends something first says no."""
        return True

    async def _note_stopped(self, readable: bool = True) -> None:
        """(#1181) The actuator is back: it leaves the record. Not when it
        could not be read before the stop: HA drops a call to an entity it
        has not loaded without a word. The name then stays, and adoption
        asks again until the actuator reads (review)."""
        if not readable:
            self._adoption_settled = False
            return
        try:
            await self.charge_record.stopped(self.charge_actuator())
        except Exception:  # noqa: BLE001 — the stop has landed regardless
            _LOGGER.warning("Battery: SEM could not drop %s from its record "
                            "of forced charges (#1181)",
                            self.charge_actuator(), exc_info=True)

    async def _note_failed_start(self) -> None:
        """(#1181) A start that raised: the name stays only while the
        actuator reads a charge — the write may have landed anyway. One
        that reads no charge is not SEM's to stop later."""
        if self.actuator_charging() is False:
            await self._note_stopped()

    async def _note_started(self, prior: "str | None" = None,
                            option: "str | None" = None
                            ) -> "ChargeStatus | None":
        """(#1181) Before the start's write: the actuator goes in the
        record. A FAILED status when it could not: no start goes out.
        ``prior`` (#1346): the option a select shows before SEM's start."""
        try:
            saved = await self.charge_record.started(
                self.charge_actuator(), self._battery(), prior=prior,
                option=option)
        except Exception:  # noqa: BLE001
            saved = False
        if saved:
            return None
        return ChargeStatus(
            status=ChargeCommandStatus.FAILED,
            message="SEM could not save its record of the charge (#1181)",
        )

    async def _put_target_back(self) -> None:
        """(#1180) The stop's last step: the charge-target number back to
        the value SEM found. One that has not landed is checked and sent
        again on later cycles — the stop itself has landed, so it is not
        sent again for it. Never raises."""
        try:
            await self.target_hold.put_back(
                self.config.get("battery_target_soc_entity", ""))
        except Exception:  # noqa: BLE001 — the stop has landed regardless
            _LOGGER.warning("Battery: putting the charge target back failed "
                            "(#1180)", exc_info=True)

    async def _release_target(self) -> None:
        """(#1180) A start that failed after the target went out: nothing
        stops a charge that never started, so the value goes back on the
        next cycle without a forced charge. Never raises."""
        try:
            await self.target_hold.release(
                self.config.get("battery_target_soc_entity", ""))
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Battery: releasing the charge target failed "
                            "(#1180)", exc_info=True)

    @abstractmethod
    async def start_forced_charge(self, command: ChargeCommand) -> ChargeStatus:
        """Start forced grid-to-battery charging.

        Returns status indicating success or failure.
        """

    @abstractmethod
    async def stop_forced_charge(self) -> ChargeStatus:
        """Stop forced charging and restore normal operation."""

    @abstractmethod
    async def get_status(self) -> ChargeStatus:
        """Get current charge status (SOC, power, active state)."""

    # ``should_stop(current_soc)`` lived here until #659. Nothing called it.
    # The live target-reached decision is the scheduler's, made against the
    # coordinator's SOC reading (``battery_charge_scheduler.py``, "Already at
    # target SOC"). This was a second statement of the same rule, on an object
    # the scheduler doesn't consult, kept alive only by its own unit tests.
    #
    # NOTE for the next sweep: ``get_status()`` below is in the same position
    # — abstract, implemented three times, zero production callers, and it
    # computes TARGET_REACHED that nobody reads. It is out of #659's scope
    # (still UNTRIAGED in tests/test_653_orphan_methods.py) but it is the same
    # finding, not a live consumer of these fields.


class HuaweiChargeAdapter(BatteryChargeAdapter):
    """Huawei SUN2000 + LUNA2000 forced charge via huawei_solar integration.

    Uses the `huawei_solar.forcible_charge_soc` service which sets:
    - Target SOC
    - Charge power (limited by AC coupling, typically 2.5-5 kW)
    - Duration (max 1440 min)
    """

    async def start_forced_charge(self, command: ChargeCommand) -> ChargeStatus:
        """Start forced charge via huawei_solar.forcible_charge_soc."""
        device_id = self.config.get("inverter_device_id", "")
        if not device_id:
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message="No inverter_device_id configured",
            )

        try:
            await self.hass.services.async_call(
                "huawei_solar",
                "forcible_charge_soc",
                {
                    "device_id": device_id,
                    "target_soc": int(command.target_soc),
                    "power": int(command.max_power_w),
                    "duration": command.duration_minutes,
                },
            )
            self._active = True
            self._target_soc = command.target_soc
            _LOGGER.info(
                "Huawei forced charge started: target=%d%%, power=%dW, duration=%dmin",
                command.target_soc,
                command.max_power_w,
                command.duration_minutes,
            )
            return ChargeStatus(
                status=ChargeCommandStatus.CHARGING,
                target_soc=command.target_soc,
                charge_power_w=command.max_power_w,
                message="Forced charge active",
            )
        except Exception as exc:
            _LOGGER.error("Failed to start Huawei forced charge: %s", exc)
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Service call failed: {exc}",
            )

    async def stop_forced_charge(self) -> ChargeStatus:
        """Stop forced charge via huawei_solar.stop_forcible_charge.

        Deliberately unconditional (no ``_active`` short-circuit): after a
        restart the in-memory ``_active`` is False while the inverter may still
        be force-charging (an orphan from the prior lifetime), so the first
        stop MUST reach the hardware. The #757 per-cycle flood is closed one
        layer up, at ``command_stop_force_charge``'s ``_last_intent`` guard —
        which only ever calls this once, on the transition.

        (#1005) ``start_forced_charge`` needs the device id and refuses
        without it, so with no device id this adapter never started a charge
        and has nothing to stop. A forcible DISCHARGE is stopped one layer up,
        by ``_stop_forcible`` / ``_issue_stop``'s number-entity path. FAILED
        here was retried every cycle for the life of the install and left
        "stop_forced_charge failed" standing in diagnostics as the last word.

        Read the review note on the START side before touching this: nothing
        in production ever writes ``inverter_device_id`` into the config this
        object holds — ``HuaweiBatteryAdapter`` autodetects it into its OWN
        ``_inverter_device_id`` and does not pass it down — so on Huawei this
        branch is the only branch, and ``start_forced_charge`` above answers
        the same permanent gap with FAILED. That is this very class on the
        paired command, and closing it would switch grid charging ON for
        every Huawei install at once, so it needs a decision, not a sweep.
        """
        device_id = self.config.get("inverter_device_id", "")
        if not device_id:
            self._active = False
            self._target_soc = 0.0
            return _say_nothing_to_stop(
                self, "no inverter_device_id configured")

        try:
            await self.hass.services.async_call(
                "huawei_solar",
                "stop_forcible_charge",
                {"device_id": device_id},
            )
            self._active = False
            self._target_soc = 0.0
            _LOGGER.info("Huawei forced charge stopped")
            return ChargeStatus(
                status=ChargeCommandStatus.IDLE,
                message="Forced charge stopped",
            )
        except Exception as exc:
            _LOGGER.error("Failed to stop Huawei forced charge: %s", exc)
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Stop failed: {exc}",
            )

    async def get_status(self) -> ChargeStatus:
        """Read current SOC from battery entity."""
        soc_entity = self.config.get("battery_soc_entity", "")
        if not soc_entity:
            return ChargeStatus(
                status=ChargeCommandStatus.CHARGING if self._active else ChargeCommandStatus.IDLE,
                message="No SOC entity configured",
            )

        state = self.hass.states.get(soc_entity)
        current_soc = 0.0
        if state and state.state not in ("unknown", "unavailable"):
            try:
                current_soc = finite_float(state.state)
            except (ValueError, TypeError):
                pass

        if self._active and current_soc >= self._target_soc:
            return ChargeStatus(
                status=ChargeCommandStatus.TARGET_REACHED,
                current_soc=current_soc,
                target_soc=self._target_soc,
                message=f"Target SOC {self._target_soc}% reached",
            )

        return ChargeStatus(
            status=ChargeCommandStatus.CHARGING if self._active else ChargeCommandStatus.IDLE,
            current_soc=current_soc,
            target_soc=self._target_soc,
        )


class GoodWeChargeAdapter(BatteryChargeAdapter):
    """GoodWe inverter forced charge via work mode entity.

    GoodWe uses a select entity to switch between work modes.
    Forced charge = "Eco Charge" or "General" mode with SOC target.
    """

    def charge_actuator(self) -> str:
        return str(self.config.get("inverter_work_mode_entity", "") or "")

    def _charging_state(self, state: str) -> bool:
        return state == "Eco Charge"

    async def start_forced_charge(self, command: ChargeCommand) -> ChargeStatus:
        """Start forced charge by setting work mode and SOC target."""
        work_mode_entity = self.config.get("inverter_work_mode_entity", "")
        soc_target_entity = self.config.get("battery_target_soc_entity", "")

        if not work_mode_entity:
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message="No inverter_work_mode_entity configured",
            )
        unsaved = await self._note_started()     # (#1181)
        if unsaved is not None:
            return unsaved

        try:
            if soc_target_entity:
                # (#1180) saved first, put back on the stop
                await self.target_hold.write(
                    soc_target_entity, int(command.target_soc))

            await self.hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": work_mode_entity, "option": "Eco Charge"},
            )

            self._active = True
            self._target_soc = command.target_soc
            _LOGGER.info("GoodWe forced charge started: target=%d%%", command.target_soc)
            return ChargeStatus(
                status=ChargeCommandStatus.CHARGING,
                target_soc=command.target_soc,
                message="Eco Charge mode active",
            )
        except Exception as exc:
            _LOGGER.error("Failed to start GoodWe forced charge: %s", exc)
            await self._release_target()
            await self._note_failed_start()      # (#1181)
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Service call failed: {exc}",
            )

    async def stop_forced_charge(self) -> ChargeStatus:
        """Restore normal work mode.

        Unconditional by design — this restore is GoodWe's only boot-orphan
        clear (no persistent snapshot, no status-sensor reconcile), so after a
        restart it must fire even though the in-memory ``_active`` is False.
        The #757 per-cycle flood is closed by the ``_last_intent`` guard in
        ``command_stop_force_charge``, which calls this only on the transition.

        Unconditional in ``_active``, NOT in the work-mode entity (#1005):
        without it ``start_forced_charge`` refuses, so no Eco Charge was ever
        set and there is no mode to restore. ``select_option`` with an empty
        ``entity_id`` is rejected by Home Assistant, and the FAILED that came
        back was retried on every cycle forever.
        """
        work_mode_entity = self.config.get("inverter_work_mode_entity", "")
        normal_mode = self.config.get("inverter_normal_work_mode", "General")
        if not work_mode_entity:
            self._active = False
            self._target_soc = 0.0
            return _say_nothing_to_stop(
                self, "no inverter_work_mode_entity configured")

        readable = self.actuator_charging() is not None   # (#1181)
        try:
            await self.hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": work_mode_entity, "option": normal_mode},
            )
            self._active = False
            self._target_soc = 0.0
            await self._note_stopped(readable)   # (#1181)
            log_on_change(_LOGGER, f"goodwe_stop:{work_mode_entity}",
                          logging.INFO, "GoodWe forced charge stopped (%s)",
                          normal_mode)
            # (#1180) the mode first: a higher target under Eco Charge would
            # charge on from the grid
            await self._put_target_back()
            return ChargeStatus(
                status=ChargeCommandStatus.IDLE,
                message=f"Restored {normal_mode} mode",
            )
        except Exception as exc:
            # (#1181) Off retries a failed stop every cycle: say it once
            log_on_change(_LOGGER, f"goodwe_stop:{work_mode_entity}",
                          logging.ERROR,
                          "Failed to stop GoodWe forced charge: %s", exc)
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Stop failed: {exc}",
            )

    async def get_status(self) -> ChargeStatus:
        """Read SOC from battery entity."""
        soc_entity = self.config.get("battery_soc_entity", "")
        current_soc = 0.0

        if soc_entity:
            state = self.hass.states.get(soc_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    current_soc = finite_float(state.state)
                except (ValueError, TypeError):
                    pass

        if self._active and current_soc >= self._target_soc:
            return ChargeStatus(
                status=ChargeCommandStatus.TARGET_REACHED,
                current_soc=current_soc,
                target_soc=self._target_soc,
            )

        return ChargeStatus(
            status=ChargeCommandStatus.CHARGING if self._active else ChargeCommandStatus.IDLE,
            current_soc=current_soc,
            target_soc=self._target_soc,
        )


class GenericChargeAdapter(BatteryChargeAdapter):
    """Generic adapter for inverters with a simple charge switch + SOC target.

    Works with any inverter that exposes:
    - A switch entity to enable/disable forced charging
    - A number entity for target SOC
    """

    def charge_actuator(self) -> str:
        chosen = select_setup(self.config)
        if chosen:                                        # (#1346)
            return chosen[0]
        return str(self.config.get("battery_force_charge_switch", "") or "")

    def _charging_state(self, state: str) -> bool:
        chosen = select_setup(self.config)
        if chosen:                                        # (#1346)
            return state == charge_option(self.hass, *chosen)
        return state == "on"

    async def start_forced_charge(self, command: ChargeCommand) -> ChargeStatus:
        """Enable forced charge switch and set SOC target."""
        if select_setup(self.config):                     # (#1346)
            return await self._start_by_select(command)
        charge_switch = self.config.get("battery_force_charge_switch", "")
        soc_target_entity = self.config.get("battery_target_soc_entity", "")

        if not charge_switch:
            return ChargeStatus(
                status=ChargeCommandStatus.UNSUPPORTED,
                message="No battery_force_charge_switch configured",
            )
        unsaved = await self._note_started()     # (#1181)
        if unsaved is not None:
            return unsaved

        try:
            if soc_target_entity:
                # (#1180) saved first, put back on the stop
                await self.target_hold.write(
                    soc_target_entity, int(command.target_soc))

            await self.hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": charge_switch},
            )

            self._active = True
            self._target_soc = command.target_soc
            return ChargeStatus(
                status=ChargeCommandStatus.CHARGING,
                target_soc=command.target_soc,
                message="Force charge switch enabled",
            )
        except Exception as exc:
            await self._release_target()
            await self._note_failed_start()      # (#1181)
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Failed: {exc}",
            )

    async def stop_forced_charge(self) -> ChargeStatus:
        """Disable forced charge switch.

        Unconditional by design — this ``turn_off`` is the generic adapter's
        only boot-orphan clear (no persistent snapshot, no status reconcile),
        so after a restart it must fire even though the in-memory ``_active``
        is False. The #757 per-cycle flood is closed by the ``_last_intent``
        guard in ``command_stop_force_charge`` (called only on the transition).

        Unconditional in ``_active``, NOT in the switch (#1005): with no
        switch there is nothing this adapter could ever have turned on —
        ``start_forced_charge`` refuses — so there is no orphan to clear and
        nothing to stop. Sending ``turn_off`` with an empty ``entity_id`` is
        rejected by Home Assistant, and a FAILED stop is retried every cycle
        for the life of the install (see the class note below).
        """
        if select_setup(self.config):                     # (#1346)
            return await self._stop_by_select()
        charge_switch = self.config.get("battery_force_charge_switch", "")
        if not charge_switch:
            self._active = False
            self._target_soc = 0.0
            return _say_nothing_to_stop(
                self, "no battery_force_charge_switch configured")

        readable = self.actuator_charging() is not None   # (#1181)
        try:
            await self.hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": charge_switch},
            )
            self._active = False
            self._target_soc = 0.0
            await self._note_stopped(readable)   # (#1181)
            # (#1180) the switch first: a higher target with the switch on
            # would charge on from the grid
            await self._put_target_back()
            return ChargeStatus(
                status=ChargeCommandStatus.IDLE,
                message="Force charge switch disabled",
            )
        except Exception as exc:
            return ChargeStatus(
                status=ChargeCommandStatus.FAILED,
                message=f"Stop failed: {exc}",
            )

    # ── (#1346) the select path ──────────────────────────────────────
    #: writes one charge attempt may make: the start and ONE retry
    SELECT_WRITES_PER_ATTEMPT = 2
    #: failed stops, in a row on one options list, before the Repair
    SELECT_STOP_STRIKES = 3
    #: a record older than this is not acted on after a restart: the select
    #: may long since serve another purpose
    ORPHAN_MAX_AGE_H = 48.0
    #: how long a refusal is remembered for the plan (the plan must not
    #: promise a charge the inverter just refused)
    REFUSAL_MEMORY_S = 24 * 3600.0
    _sel_refused_at: "float | None" = None

    @property
    def charge_refused(self) -> bool:
        """(#1346) The inverter did not take the charge option lately."""
        at = self._sel_refused_at
        return at is not None and (time.monotonic() - at) < self.REFUSAL_MEMORY_S

    #: (#1413) when SEM last gave up a charge because the hold would not
    #: write the charge target (``_target_not_set``)
    _sel_unset_at: "float | None" = None

    @property
    def charge_target_unset(self) -> bool:
        """(#1413) SEM gave up a charge lately because it could not set the
        charge target (the reserve on a Powerwall). The plan leaves this
        pack's charge out for as long as it remembers a refusal, and says
        why. A target the hold writes again clears it."""
        at = self._sel_unset_at
        return at is not None and (time.monotonic() - at) < self.REFUSAL_MEMORY_S
    #: this attempt's writes, whether the option was ever read back, why it
    #: ended (a message), and the stop's (failed cycles, options listed)
    _sel_writes: int = 0
    _permit_writes: int = 0     # (#1377) turn_on writes of this attempt
    #: (#1377) cycles the permit has read OFF since SEM turned it on. A
    #: cloud-backed switch may take 20–40 s to show the new state: re-send
    #: "on" once at the 3rd off read, give up at the 6th (~60 s at 10 s)
    _permit_off_reads: int = 0
    PERMIT_RESEND_AT = 3
    PERMIT_GIVE_UP_AT = 6
    _sel_seen: bool = False
    _sel_spent: "str | None" = None
    _sel_stop_miss: tuple = (0, ())
    #: (#1377) a cloud read can lag a write by minutes (``AWAY_FOR_S``,
    #: ``SHOW_WITHIN_S``): when SEM last wrote the option, since when the
    #: select (and the permit) read their old value after showing SEM's, and
    #: whether the permit showed on at all and the old option went out again
    AWAY_FOR_S = AWAY_FOR_S
    SHOW_WITHIN_S = SHOW_WITHIN_S
    _sel_wrote_at: "float | None" = None
    _sel_away_since: "float | None" = None
    _permit_away_since: "float | None" = None
    _permit_seen_on: bool = False
    _permit_wrote_at: "float | None" = None
    _sel_prior_sent: bool = False
    #: (#1377) this pack joined a charge SEM started for another pack, or
    #: in the last lifetime: SEM's "on" may stand on the permit
    _sel_joined: bool = False

    def _select_failed(self, why: str) -> ChargeStatus:
        log_on_change(_LOGGER, f"select_charge:{self.charge_actuator()}",
                      logging.WARNING, "Battery: grid charge by select: %s "
                      "(#1346)", why)
        return ChargeStatus(status=ChargeCommandStatus.FAILED, message=why)

    def _forget_attempt(self) -> None:
        """(#1346) A stop ends the attempt: the next start may try again."""
        self._sel_writes, self._sel_seen = 0, False
        self._permit_writes = self._permit_off_reads = 0
        self._sel_spent = None
        self._sel_stop_miss = (0, ())
        self._sel_wrote_at = self._sel_away_since = None     # (#1377)
        self._permit_away_since = self._permit_wrote_at = None
        self._permit_seen_on = self._sel_prior_sent = False
        self._sel_joined = False

    async def _select_over(self, entity: str, why: str) -> ChargeStatus:
        """(#1346) The charge did not start or is gone: nothing counts it,
        the record forgets this pack, and no write follows in this attempt
        (a select the inverter flips back is its own logic, not a fight)."""
        self._active, self._target_soc = False, 0.0
        self._sel_spent = why
        self._sel_refused_at = time.monotonic()
        await self._release_target()
        await self._send_prior_once(entity)         # (#1377)
        await self._put_permit_back()               # (#1377) best effort
        await self.charge_record.left(entity, self._battery())
        return self._select_failed(why)

    async def _send_prior_once(self, entity: str) -> None:
        """(#1377) A select SEM wrote, that reads its old option when the
        charge ends: the old option goes out ONCE more. On a cloud select
        SEM's own write may still be on its way and land later (a Tesla
        Powerwall showed the old mode, then SEM's again 11 minutes on); the
        old option sent after it puts the battery back. A select that shows
        it already is not changed by it. A value set since (neither SEM's
        nor the old one) is the user's and is never written over, nor is a
        select another pack still charges through. Never raises."""
        if self._sel_prior_sent or not self._sel_writes:
            return
        try:
            prior = await self.charge_record.prior_of(entity)
            option = (select_setup(self.config) or ("", ""))[1]
            if prior is None or prior == charge_option(self.hass, entity, option):
                return                      # SEM never wrote this select
            state, options = read_select(self.hass, entity)
            if state != prior or prior not in options:
                return
            if await self.charge_record.others(entity, self._battery()):
                return
            self._sel_prior_sent = True
            await self._put_select_back(entity, option, prior, options)
        except Exception:  # noqa: BLE001 — the end has happened regardless
            _LOGGER.debug("old option not sent again", exc_info=True)

    async def _start_by_select(self, command: ChargeCommand) -> ChargeStatus:
        """Set the select to the charge option. Nothing goes out when the
        select cannot be read or does not list the option; a select that
        already shows it is not written again. A select that keeps its old
        option gets ONE retry, then no more writes in this attempt."""
        entity, option = select_setup(self.config)
        state, options = read_select(self.hass, entity)
        if state is None:
            return self._select_failed(f"{entity} is unavailable — SEM cannot "
                                       "ask it, so no charge is started")
        wanted = listed_option(self.hass, entity, option)   # (#1039)
        if wanted not in options:
            return self._select_failed(f"{entity} does not list '{option}'")
        if state == wanted:
            # (#1377) a cloud select shows a write at once, before any poll
            # says the device took it: it counts as seen only once it still
            # shows the option ``SHOW_WITHIN_S`` after the write. Until then
            # an old option read back is a write not taken (the re-send and
            # the give-up below), not a charge that went back.
            if self._sel_writes and self._since_write() >= self.SHOW_WITHIN_S:
                self._sel_seen = True
            if not self._sel_spent or not self._join_needs_writes():
                # it took the option. (#1377) Not after a give-up where the
                # option alone is a mode (a permit or a target beside it):
                # a mode that was the user's before the charge still shows
                # it, and the plan must still hear that this attempt ended
                self._sel_refused_at = None
            self._sel_away_since = None            # (#1377) back, or never away
            return await self._join_select_charge(entity, command)
        if self._sel_spent:
            return self._select_failed(self._sel_spent)
        went_back = (f"{entity} went back to '{state}' by itself — the "
                     "charge is over and SEM does not write it again")
        if self._sel_writes:
            # (#1377) a value that is neither SEM's nor the one it had before
            # was set since — by hand or by the inverter — and a cloud read
            # can only lag to the old one: over at once, seen or not
            prior = await self.charge_record.prior_of(entity)
            if prior is not None and state != prior:
                return await self._select_over(entity, went_back)
        if self._sel_writes and self._sel_seen:
            waiting = await self._wait_while_away(entity, state, wanted, command)
            if waiting is not None:
                return waiting
            return await self._select_over(entity, went_back)
        if self._sel_writes and self._since_write() < self.SHOW_WITHIN_S:
            # (#1377) a cloud select shows a write on its next poll: the
            # re-send, and the give-up after it, wait for that
            return ChargeStatus(status=ChargeCommandStatus.CHARGING,
                                target_soc=command.target_soc,
                                message=f"Charge option set — {entity} does "
                                "not show it yet")
        if self._sel_writes >= self.SELECT_WRITES_PER_ATTEMPT:
            return await self._select_over(
                entity, f"{entity} did not take '{wanted}' — could not start "
                "the charge, no more writes for it")
        return await self._write_charge_option(entity, wanted, state, command)

    def _since_write(self) -> float:
        at = self._sel_wrote_at
        return float("inf") if at is None else time.monotonic() - at

    async def _wait_while_away(self, entity: str, state: str, wanted: str,
                               command: ChargeCommand) -> "ChargeStatus | None":
        """(#1377) The select showed SEM's option and now reads the option
        it had before SEM's write. A cloud read may show that for minutes
        after a write that landed: the charge is kept, unwritten, until the
        old option has read for ``AWAY_FOR_S``. None: it is over now — the
        wait ran out, or the select reads a value set since."""
        prior = await self.charge_record.prior_of(entity)
        if prior is None or state != prior or prior == wanted:
            return None
        now = time.monotonic()
        if self._sel_away_since is None:
            self._sel_away_since = now
        if now - self._sel_away_since >= self.AWAY_FOR_S:
            return None
        minutes = int(self.AWAY_FOR_S // 60)
        log_on_change(_LOGGER, f"select_charge_away:{entity}", logging.INFO,
                      "Battery: %s reads '%s' again — SEM waits up to %d min "
                      "for '%s' before it ends the charge: a cloud read can "
                      "show the old value for minutes (#1377)",
                      entity, state, minutes, wanted)
        return ChargeStatus(
            status=ChargeCommandStatus.CHARGING, target_soc=command.target_soc,
            message=(f"{entity} reads '{state}' again — SEM waits up to "
                     f"{minutes} min for '{wanted}' before it ends the charge"))

    # ── (#1377) the reserve that starts the charge ───────────────────
    def _unreadable_part(self) -> "ChargeStatus | None":
        """Before any record or write: each entity a select charge sets up
        must give a value, or nothing starts. The select and the permit
        already followed this rule; the charge target joins them. On a
        Powerwall the reserve is what starts the charge (the mode alone is
        a mode), and the hold writes no value it cannot read — so a target
        that reads nothing would leave the mode and the permit set and the
        battery idle. One rule for every select setup with a target: SEM
        cannot tell a reserve from an upper limit. Not given up: the next
        cycle asks again, and nothing is saved meanwhile."""
        target = str(self.config.get("battery_target_soc_entity", "") or "")
        if target and not self.target_hold.readable(target):
            return self._select_failed(f"{target} is unavailable — SEM cannot "
                                       "ask it, so no charge is started")
        permit = permit_switch(self.config)
        if permit and self._permit_state(permit) is None:
            return self._select_failed(f"{permit} is unavailable — SEM cannot "
                                       "ask it, so no charge is started")
        return None

    async def _target_not_set(self, entity: str) -> ChargeStatus:
        """The hold wrote no reserve (its record could not be read or saved,
        or the old value is lost): without it no charge runs. Nothing was
        sent yet — the reserve goes first — so only the records go, and
        the attempt is given up until the block ends."""
        target = self.config.get("battery_target_soc_entity", "")
        await self._put_permit_back()       # off and SEM's: only the record
        await self.charge_record.left(entity, self._battery())
        self._active, self._target_soc = False, 0.0
        why = (f"{target} was not set — SEM could not keep its old value "
               "to put back, so no charge is started")
        self._sel_spent = why
        self._sel_unset_at = time.monotonic()     # (#1413) for the plan
        return self._select_failed(why)

    async def _write_charge_option(self, entity: str, wanted: str, state: str,
                                   command: ChargeCommand) -> ChargeStatus:
        retry = self._sel_writes > 0
        if not retry:
            unreadable = self._unreadable_part()            # (#1377)
            if unreadable is not None:
                return unreadable
        if not retry:
            # a name left from a charge that has ended (the select no longer
            # shows the option) must not hand its old prior to this one
            await self.charge_record.stopped(entity)
            unsaved = await self._note_started(prior=state, option=wanted)
            if unsaved is not None:                    # before the write
                return unsaved
            unsaved = await self._note_permit_started()
            if unsaved is not None:
                await self._note_failed_start()
                return unsaved
        try:
            if not retry and self.config.get("battery_target_soc_entity", ""):
                wrote = await self.target_hold.write(
                    self.config["battery_target_soc_entity"],
                    int(command.target_soc))
                if not wrote:                          # (#1377) its "no"
                    return await self._target_not_set(entity)
                self._sel_unset_at = None              # (#1413) it wrote
            if not retry:
                await self._permit_on()                # (#1377)
            await self.hass.services.async_call(
                "select", "select_option",
                # (#1039) the option as the select lists it (mapped again
                # here: it is the same value, and the write is then safe
                # whoever calls this)
                {"entity_id": entity,
                 "option": listed_option(self.hass, entity, wanted)})
        except Exception as exc:  # noqa: BLE001
            await self._release_target()
            await self._put_permit_back()              # (#1377) best effort
            await self._note_failed_start()
            return self._select_failed(f"start failed: {exc}")
        self._sel_writes += 1
        self._sel_wrote_at = time.monotonic()          # (#1377)
        self._active, self._target_soc = True, command.target_soc
        return ChargeStatus(status=ChargeCommandStatus.CHARGING,
                            target_soc=command.target_soc,
                            message="Charge option set")

    async def _join_select_charge(self, entity: str,
                                  command: ChargeCommand) -> ChargeStatus:
        """The select already shows the charge option: nothing to write. A
        charge SEM's record names (another pack's start) gains this pack as
        an owner; any other is the user's or the inverter's, left alone."""
        if await self.charge_record.prior_of(entity) is not None:
            if not await self.charge_record.started(entity, self._battery()):
                return self._select_failed("SEM could not save its record")
            if not self._sel_writes:
                # (#1377) a pack joining SEM's own charge (another pack's
                # start, or the last lifetime's) writes nothing of its own:
                # its writes count as spent. It sees the option like the
                # starter, from a read ``SHOW_WITHIN_S`` after it joined;
                # an old option later waits, sooner it ends its part.
                self._sel_writes = self.SELECT_WRITES_PER_ATTEMPT
                self._sel_wrote_at = time.monotonic()
                self._sel_joined = True
            # (#1377) a pack joining a charge another pack started owns the
            # permit too: the first pack's stop must not turn it off
            permit = permit_switch(self.config)
            if permit and await self.charge_record.prior_of(permit) is not None:
                await self.charge_record.started(permit, self._battery())
            self._active, self._target_soc = True, command.target_soc
            refused = await self._check_permit(entity)
            if refused is not None:
                return refused
        elif self._join_needs_writes():
            # (#1377) The option was set by someone else, but where a permit
            # switch or a charge target is set up, the option alone is a
            # mode, not a charge: a battery whose time-based mode is the
            # option charges from the grid only with the permit ON and the
            # reserve raised. SEM sets those two and puts back only them.
            return await self._join_with_permit_and_target(entity, command)
        return ChargeStatus(status=ChargeCommandStatus.CHARGING,
                            target_soc=command.target_soc,
                            message="Select already shows the charge option")

    def _join_needs_writes(self) -> bool:
        return bool(permit_switch(self.config)
                    or self.config.get("battery_target_soc_entity", ""))

    async def _join_with_permit_and_target(
            self, entity: str, command: ChargeCommand) -> ChargeStatus:
        """(#1377) The select goes in the record with the option it shows
        as its prior: a restart then adopts the charge and its stop puts the
        permit and the reserve back, while the select itself is never
        written (its prior is the option). Every later cycle takes the
        branch above, so this runs once per charge."""
        if self._sel_spent:              # given up in this attempt: no rewrite
            return self._select_failed(self._sel_spent)
        unreadable = self._unreadable_part()                # (#1377)
        if unreadable is not None:
            return unreadable
        state, _options = read_select(self.hass, entity)
        unsaved = await self._note_started(prior=state, option=state)
        if unsaved is not None:                        # before any write
            return unsaved
        unsaved = await self._note_permit_started()
        if unsaved is not None:
            await self.charge_record.stopped(entity)
            return unsaved
        wrote = []
        try:
            target = self.config.get("battery_target_soc_entity", "")
            if target:
                # (#1377) its answer is read: the option alone is a mode, so
                # with no reserve raised no charge runs (class 192)
                if not await self.target_hold.write(
                        target, int(command.target_soc)):
                    return await self._target_not_set(entity)
                self._sel_unset_at = None              # (#1413) it wrote
                wrote.append("reserve")
            if permit_switch(self.config):
                before = self._permit_writes
                await self._permit_on()
                if self._permit_writes > before:
                    wrote.append("permit")
        except Exception as exc:  # noqa: BLE001
            await self._release_target()
            await self._put_permit_back()
            await self.charge_record.stopped(entity)
            return self._select_failed(f"start failed: {exc}")
        self._active, self._target_soc = True, command.target_soc
        # the option counts as seen: a mode changed by hand since ends the
        # charge (the "went back by itself" rule), SEM does not force it back
        self._sel_writes, self._sel_seen = max(self._sel_writes, 1), True
        return ChargeStatus(
            status=ChargeCommandStatus.CHARGING, target_soc=command.target_soc,
            message=("Select already showed the charge option; set: "
                     + (", ".join(wrote) or "nothing, both already set")))

    async def _check_permit(self, entity: str) -> "ChargeStatus | None":
        """(#1377) SEM turned the permit on and it reads OFF. Never shown on:
        a switch that ignores the write — one more try, then the charge is
        given up, the mode and the reserve go back and the plan says it was
        refused. Shown on, now off: a cloud read may show the old value for
        minutes, so the charge ends only once it has read off for
        ``AWAY_FOR_S`` (a read of "on" starts the wait again), and nothing
        is sent meanwhile."""
        permit = permit_switch(self.config)
        if not permit or await self.charge_record.prior_of(permit) is None:
            return None
        state = self._permit_state(permit)
        if state == "on":                   # SEM's "on" (its record)
            # it took, once a read ``SHOW_WITHIN_S`` after SEM's last write
            # still says so (a cloud switch shows "on" at once); an "on"
            # from the last lifetime has long been read back
            at = self._permit_wrote_at
            if at is None or time.monotonic() - at >= self.SHOW_WITHIN_S:
                self._permit_seen_on = True
            self._permit_away_since = None
            return None
        if state != "off":
            return None                     # unreadable: no count either way
        if self._permit_seen_on:
            now = time.monotonic()
            if self._permit_away_since is None:
                self._permit_away_since = now
            if now - self._permit_away_since < self.AWAY_FOR_S:
                log_on_change(
                    _LOGGER, f"select_charge_away:{permit}", logging.INFO,
                    "Battery: %s reads off again — SEM waits up to %d min "
                    "before it ends the charge: a cloud read can show the "
                    "old value for minutes (#1377)",
                    permit, int(self.AWAY_FOR_S // 60))
                return None
            why = (f"{permit} went back to off by itself — the charge is "
                   "over and SEM does not turn it on again")
        else:
            self._permit_off_reads += 1
            if self._permit_off_reads < self.PERMIT_GIVE_UP_AT:
                if (self._permit_off_reads == self.PERMIT_RESEND_AT
                        and self._permit_writes < self.SELECT_WRITES_PER_ATTEMPT):
                    await self._permit_on()
                return None
            why = (f"{permit} did not turn on — could not start the charge, "
                   "no more writes for it")
        await self._stop_by_select()
        self._sel_spent, self._sel_refused_at = why, time.monotonic()
        return self._select_failed(why)

    async def _stop_by_select(self) -> ChargeStatus:
        """Put the select back to what it showed before SEM's start, but
        only while it still shows the charge option: a choice made by hand
        since is the user's and is never written over. A select that other
        packs still charge through goes back with the last of them."""
        entity, option = select_setup(self.config)
        prior = await self.charge_record.prior_of(entity)
        # (#1377) the reserve goes back FIRST and each restore is tried on
        # its own: a mode or permit that cannot be read must never hold the
        # reserve high (it blocks the battery's discharge to the house)
        await self._put_target_back()
        if prior is None:
            self._active, self._target_soc = False, 0.0
            self._forget_attempt()
            failed = await self._put_permit_back()
            if failed is not None:
                return failed
            return _say_nothing_to_stop(self, f"SEM changed no option of {entity}")
        shared = await self.charge_record.others(entity, self._battery())
        failed = await self._put_mode_back(entity, option, prior, shared)
        failed = await self._put_permit_back() or failed
        if failed is not None:
            return failed
        self._active, self._target_soc = False, 0.0
        self._forget_attempt()
        self._clear_stuck_repair(entity)
        if shared:      # another pack still charges: its name keeps the prior
            await self.charge_record.left(entity, self._battery())
        else:
            await self._note_stopped(True)
        return ChargeStatus(status=ChargeCommandStatus.IDLE,
                            message="Select put back")

    async def _put_mode_back(self, entity: str, option: str, prior: str,
                             shared: bool) -> "ChargeStatus | None":
        state, options = read_select(self.hass, entity)
        if state is None:
            return self._select_failed(f"{entity} is unavailable — the charge "
                                       "option is put back when it answers")
        if not shared and state == charge_option(self.hass, entity, option):
            if prior == state:           # (#1377) it showed the option before
                return None
            return await self._put_select_back(entity, option, prior, options)
        if not shared and state == prior:
            # (#1377) it reads the old option: SEM's write may still land
            await self._send_prior_once(entity)
        return None

    # ── (#1377) the permit switch beside the select ──────────────────
    def _permit_state(self, entity: str) -> "str | None":
        """"on" / "off", or None when the switch cannot be read."""
        try:
            state = getattr(self.hass.states.get(entity), "state", None)
        except Exception:  # noqa: BLE001
            return None
        return state if state in ("on", "off") else None

    async def _note_permit_started(self) -> "ChargeStatus | None":
        """Before any write: a permit that is OFF goes in the record with
        its prior. One already ON is the user's and is left alone. A permit
        that cannot be read or recorded means no start."""
        entity = permit_switch(self.config)
        if not entity:
            return None
        state = self._permit_state(entity)
        if state is None:
            return self._select_failed(f"{entity} is unavailable — SEM cannot "
                                       "ask it, so no charge is started")
        if state == "on":
            return None
        try:
            saved = await self.charge_record.started(
                entity, self._battery(), prior="off", option="on")
        except Exception:  # noqa: BLE001
            saved = False
        if saved:
            return None
        return self._select_failed("SEM could not save its record")

    async def _permit_on(self) -> None:
        entity = permit_switch(self.config)
        if (entity and self._permit_state(entity) == "off"
                and await self.charge_record.prior_of(entity) is not None):
            self._permit_writes += 1
            self._permit_wrote_at = time.monotonic()       # (#1377)
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": entity})

    async def _put_permit_back(self, resend_off: bool = False
                               ) -> "ChargeStatus | None":
        """The permit goes back OFF, with the last pack's stop: when it
        reads ON, and (#1377) when it reads OFF but SEM turned it on — in
        this lifetime, or ``resend_off`` (the record of the last one says
        so): a cloud read can show "off" while SEM's "on" is on its way.
        A hand change to ON is never made here. None: done or nothing to
        do. A status: the switch cannot be read, the record stays and the
        next stop asks again."""
        entity = permit_switch(self.config)
        prior = await self.charge_record.prior_of(entity) if entity else None
        if prior is None:
            return None
        if await self.charge_record.others(entity, self._battery()):
            await self.charge_record.left(entity, self._battery())
            return None
        state = self._permit_state(entity)
        if state is None:
            return self._select_failed(f"{entity} is unavailable — it is put "
                                       "back when it answers")
        # (#1377) one SEM turned on this lifetime goes off even when it
        # reads off: a cloud read can show the old value while SEM's "on"
        # is still on its way, and lands later. Off is never the user's on.
        if prior == "off" and (state == "on" or self._permit_writes > 0
                               or resend_off or self._sel_joined):
            try:
                await self.hass.services.async_call(
                    "switch", "turn_off", {"entity_id": entity})
            except Exception as exc:  # noqa: BLE001
                if state == "on":
                    return self._select_failed(f"stop failed: {exc}")
                # it reads off: the "off" was sent once, in case; a cloud
                # that keeps failing is not asked again every cycle
                _LOGGER.debug("permit off not sent again", exc_info=True)
        await self.charge_record.stopped(entity)
        return None

    async def _put_select_back(self, entity: str, option: str, prior: str,
                               options: list) -> "ChargeStatus | None":
        """The write of ``prior``. None: it went out. A status: it did not;
        a ``prior`` the select no longer lists is counted, and the third
        failed cycle on one list files a Repair (#1346)."""
        if prior not in options:
            count, seen = self._sel_stop_miss
            count = count + 1 if seen == tuple(options) else 1
            self._sel_stop_miss = (count, tuple(options))
            if count >= self.SELECT_STOP_STRIKES:
                self._raise_stuck_repair(entity, option)
            return self._select_failed(f"{entity} no longer lists '{prior}'")
        try:
            await self.hass.services.async_call(
                "select", "select_option",
                {"entity_id": entity,
                 "option": listed_option(self.hass, entity, prior)})
        except Exception as exc:  # noqa: BLE001
            return self._select_failed(f"stop failed: {exc}")
        return None

    def _raise_stuck_repair(self, entity: str, option: str) -> None:
        try:
            from .. import repair_issues as _ri
            _ri.raise_charge_select_stuck(self.hass, entity=entity,
                                          option=option)
        except Exception:  # noqa: BLE001 — a repair never costs a cycle
            _LOGGER.debug("select repair not raised", exc_info=True)

    def _clear_stuck_repair(self, entity: str) -> None:
        try:
            from .. import repair_issues as _ri
            _ri.clear_charge_select_stuck(self.hass, entity)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("select repair not cleared", exc_info=True)

    async def restore_orphan_select(self, observer: bool = False) -> None:
        """(#1346) A restart with the select settings cleared: the record
        still names the select this pack turned to the charge option. Put it
        back once if it still shows that option, then drop the name. Through
        the observer gate like every write: in observer mode nothing is sent
        and the record stays. Never raises."""
        if getattr(self, "_orphans_settled", False):
            return
        try:
            # (#1377) the permit is live beside the select: not an orphan
            live = {(select_setup(self.config) or ("",))[0],
                    permit_switch(self.config)}
            for entity, prior, option in await self.charge_record.select_records(
                    self._battery()):
                if entity not in live and not await self._restore_one(
                        entity, prior, option, observer):
                    return                      # asked again next cycle
            if not await self._restore_stale_select(observer):
                return
            if not await self._restore_stale_permit(observer):
                return
            self._orphans_settled = True
        except Exception:  # noqa: BLE001 — a record never costs a cycle
            _LOGGER.debug("orphan select not restored", exc_info=True)

    async def _may_drop_stopped(self, actuator: str) -> bool:
        """(#1377) A select that reads its old option after a restart is
        left to ``_restore_stale_select``, which sends it once (not in
        watch-only mode) before the name goes."""
        chosen = select_setup(self.config)
        if not chosen or actuator != chosen[0]:
            return True
        prior = await self.charge_record.prior_of(actuator)
        state, options = read_select(self.hass, actuator)
        return not (prior is not None and state == prior and prior in options
                    and prior != charge_option(self.hass, *chosen))

    def _touched_this_lifetime(self) -> bool:
        """(#1377) A charge of this lifetime: its own rules end it, never
        the restart's."""
        return bool(self._active or self._sel_writes or self._permit_writes)

    async def _restore_stale_select(self, observer: bool) -> bool:
        """(#1377) After a restart SEM's record names the live select with
        an old option, and the select reads that old option: the charge
        ended, or a cloud read still shows the old value while SEM's write
        is on its way. The old option goes out once, so that write cannot
        land later with no owner, and this pack's name goes. A select that
        shows the option is adoption's; any other value was set since and
        is left. True: settled; False: asked again (unreadable, observer)."""
        chosen = select_setup(self.config)
        if not chosen or self._touched_this_lifetime():
            return True
        entity, option = chosen
        if not await self.charge_record.running(entity, self._battery()):
            return True
        prior = await self.charge_record.prior_of(entity)
        state, options = read_select(self.hass, entity)
        if state is None or observer:
            return False
        if (prior is None or state != prior or prior not in options
                or prior == charge_option(self.hass, entity, option)):
            return True
        # no charge runs (the select reads its old option): the reserve SEM
        # raised goes back too — once the name goes, no stop comes for it
        await self._put_target_back()
        age = await self.charge_record.age_h(entity)
        if (not await self.charge_record.others(entity, self._battery())
                and (age is None or age <= self.ORPHAN_MAX_AGE_H)):
            await self._put_select_back(entity, option, prior, options)
            _LOGGER.info("Battery: %s reads '%s' after a restart — sent once "
                         "more, in case SEM's charge option still lands "
                         "(#1377)", entity, prior)
        await self.charge_record.left(entity, self._battery())
        return True

    async def _restore_stale_permit(self, observer: bool) -> bool:
        """(#1377) A crash between the permit and the select write leaves
        the permit on with the select at its old option: no charge runs, so
        the permit goes back. True: settled; False: asked again next cycle
        (unreadable, or observer mode, which sends nothing)."""
        permit = permit_switch(self.config)
        if (not permit or self._touched_this_lifetime()
                or await self.charge_record.prior_of(permit) is None):
            return True
        entity, option = select_setup(self.config)
        state, _ = read_select(self.hass, entity)
        if state is None or observer:
            return False
        if state == charge_option(self.hass, entity, option):
            return True                         # a charge runs: its stop
        # (#1377) the record says SEM turned it on: "off" goes out even
        # when it reads off, in case that "on" still lands
        return await self._put_permit_back(resend_off=True) is None

    async def _restore_one(self, entity: str, prior: str, option: str,
                           observer: bool) -> bool:
        """True: this record is settled (restored or nothing to do)."""
        state, options = read_select(self.hass, entity)
        if state is None or observer:
            return False
        age = await self.charge_record.age_h(entity)
        if age is not None and age > self.ORPHAN_MAX_AGE_H:
            # too old to trust: the select may serve another purpose now
            _LOGGER.warning("Battery: SEM's record for %s is %.0f h old — it "
                            "is dropped and the select is left as it is "
                            "(#1346)", entity, age)
            await self.charge_record.stopped(entity)
            return True
        if await self.charge_record.others(entity, self._battery()):
            await self.charge_record.left(entity, self._battery())
            return True
        if entity.startswith("switch."):                 # (#1377) the permit
            if state == "on" and prior == "off":
                await self.hass.services.async_call(
                    "switch", "turn_off", {"entity_id": entity})
        elif option and state == charge_option(self.hass, entity, option):
            if prior not in options:
                self._select_failed(f"{entity} no longer lists '{prior}'")
                return False
            await self.hass.services.async_call(
                "select", "select_option",
                {"entity_id": entity,
                 "option": listed_option(self.hass, entity, prior)})
            _LOGGER.info("Battery: %s put back to '%s' after a restart with "
                         "the charge select unset (#1346)", entity, prior)
        await self.charge_record.stopped(entity)
        return True

    async def get_status(self) -> ChargeStatus:
        """Read SOC from battery entity."""
        soc_entity = self.config.get("battery_soc_entity", "")
        current_soc = 0.0

        if soc_entity:
            state = self.hass.states.get(soc_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    current_soc = finite_float(state.state)
                except (ValueError, TypeError):
                    pass

        if self._active and current_soc >= self._target_soc:
            return ChargeStatus(
                status=ChargeCommandStatus.TARGET_REACHED,
                current_soc=current_soc,
                target_soc=self._target_soc,
            )

        return ChargeStatus(
            status=ChargeCommandStatus.CHARGING if self._active else ChargeCommandStatus.IDLE,
            current_soc=current_soc,
            target_soc=self._target_soc,
        )


# ``create_charge_adapter`` (and its ``_has_integration`` helper) lived here
# until #659. It was a second brand-selection factory — same platform key,
# same auto-detect order — running in parallel with the live one,
# ``battery_adapters.adapter_for`` (called from coordinator.py). Nothing in
# production ever called this copy; only its own unit tests did, which is
# what kept it looking healthy.
#
# The classes above are NOT dead: each brand adapter (huawei.py, goodwe.py,
# generic.py) constructs its matching *ChargeAdapter directly to implement
# ``command_force_charge``. It is only the selection of which one to build
# that had two implementations, and this was the invisible one — the #651
# shape. Brand selection belongs in ``adapter_for``; add new platforms there.
