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
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from homeassistant.core import HomeAssistant

from ...utils.log_gate import log_on_change
from .charge_record import ForcedChargeRecord
from .charge_target import ChargeTargetHold

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
                return False
            charging = self.actuator_charging()
            if charging is None:
                return False                    # not readable yet: next cycle
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

    async def _note_started(self) -> "ChargeStatus | None":
        """(#1181) Before the start's write: the actuator goes in the
        record. A FAILED status when it could not: no start goes out."""
        try:
            saved = await self.charge_record.started(
                self.charge_actuator(), self._battery())
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
                current_soc = float(state.state)
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
                    current_soc = float(state.state)
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
        return str(self.config.get("battery_force_charge_switch", "") or "")

    def _charging_state(self, state: str) -> bool:
        return state == "on"

    async def start_forced_charge(self, command: ChargeCommand) -> ChargeStatus:
        """Enable forced charge switch and set SOC target."""
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

    async def get_status(self) -> ChargeStatus:
        """Read SOC from battery entity."""
        soc_entity = self.config.get("battery_soc_entity", "")
        current_soc = 0.0

        if soc_entity:
            state = self.hass.states.get(soc_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    current_soc = float(state.state)
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
