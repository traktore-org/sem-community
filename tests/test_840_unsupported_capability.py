"""#840 — a capability the device refuses must be asked for once, not forever.

@RienduPre, back from holiday on a Growatt + Wallbox Pulsar, 25.08:

    battery_adapters/base.py:321
    Battery: failed to set forcible discharge:
      Setting value for Power Setpoint failed: Not supported by device
    First occurred: 24 August 15:58:17 (2364 events)  Last logged: 11:45:41

**2,364 events.** His inverter exposes the setpoint entity but its firmware
does not implement the write, so every attempt is rejected — and SEM tried
again on the next cycle, and the next, for nineteen hours.

Two separate faults, and only fixing the loud one would be a mistake:

* **The log spam** is the symptom. A permanent failure written every cycle is
  the #762 lesson — it trains people to ignore their logs, and it buried
  whatever else was in his.
* **The retry is the fault.** "Not supported by device" is not a transient
  modbus timeout; that register will not appear tomorrow. SEM had no memory of
  having been told, so it kept planning around a capability it could not use
  and kept issuing writes that could not land.

The fix does not parse the vendor's error string — those differ per
integration and change without notice. It counts evidence, the way the charger
side already does (``raise_charger_actuation_failed``, 3 consecutive failures
→ Repair, cleared on success). After three consecutive refusals the capability
is marked unsupported: SEM stops attempting, says so once, and raises a Repair
so it is visible somewhere other than a log — #799's lesson, that a log line
is not a surface.

It re-arms on restart rather than latching forever, so a firmware update or a
corrected entity gets another chance without the user having to know that SEM
had given up.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


from custom_components.solar_energy_management.coordinator.battery_adapters.base import (  # noqa: E501
    BatteryControlAdapter,
)


class _Adapter(BatteryControlAdapter):
    """Concrete shell — the base class is abstract."""

    async def command_normal(self): return True
    async def command_force_charge(self, watts): return True
    async def command_limit_discharge(self, watts): return True
    async def command_stop(self): return True
    async def command_stop_force_charge(self): return True

    @property
    def supports_forced_charge(self): return True

    @property
    def max_charge_power_w(self): return 5000.0

    @property
    def max_discharge_power_w(self): return 5000.0


def _adapter(*, fails=True):
    hass = MagicMock()
    hass.states.get.return_value = MagicMock(attributes={})
    calls = []

    async def _call(domain, service, data, **kw):
        calls.append(data)
        if fails:
            raise Exception("Setting value for Power Setpoint failed: "
                            "Not supported by device")
        return True

    hass.services.async_call = AsyncMock(side_effect=_call)
    a = _Adapter(hass, {"battery_force_discharge_control_entity":
                        "number.growatt_power_setpoint"})
    return a, calls


class TestItStopsAsking:
    async def test_it_gives_up_after_the_failure_limit(self):
        """Distinct values, because identical ones are de-duped before they
        ever reach the device — the strike counter only advances on writes
        that were genuinely attempted."""
        a, calls = _adapter()
        for i in range(10):
            await a._write_force_discharge(1000.0 + i * 500.0)
        limit = a.FORCE_DISCHARGE_FAILURE_LIMIT
        assert len(calls) == limit, (
            f"issued {len(calls)} writes for a capability the device refused "
            f"{limit} times — RienduPre's install made 2,364 (#840)"
        )

    async def test_the_first_attempts_still_happen(self):
        """A transient failure must not be mistaken for a permanent one."""
        a, calls = _adapter()
        await a._write_force_discharge(2000.0)
        assert len(calls) == 1

    async def test_a_success_resets_the_count(self):
        a, calls = _adapter(fails=True)
        await a._write_force_discharge(2000.0)
        await a._write_force_discharge(3000.0)
        a._hass.services.async_call = AsyncMock(return_value=True)
        await a._write_force_discharge(2200.0)          # succeeds
        assert a._force_discharge_failures == 0
        assert a.supports_forced_discharge is True


class TestItStopsPlanningForIt:
    """Muting the log while still planning battery→grid export would leave the
    user with a feature that silently never fires."""

    async def test_the_capability_is_withdrawn_once_refused(self):
        a, _ = _adapter()
        assert a.supports_forced_discharge is True
        for i in range(a.FORCE_DISCHARGE_FAILURE_LIMIT):
            await a._write_force_discharge(1000.0 + i * 500.0)
        assert a.supports_forced_discharge is False, (
            "SEM still advertises forced discharge after the device refused "
            "it — the actuator will keep issuing FORCE_DISCHARGE (#840)"
        )

    async def test_an_unconfigured_entity_is_still_simply_unsupported(self):
        hass = MagicMock()
        a = _Adapter(hass, {})
        assert a.supports_forced_discharge is False


class TestItSaysSoOnce:
    async def test_the_warning_is_not_written_every_cycle(self, caplog):
        import logging
        from custom_components.solar_energy_management.coordinator.battery_adapters import (  # noqa: E501
            base as _base,
        )
        caplog.set_level(logging.DEBUG, logger=_base.__name__)
        a, _ = _adapter()
        for i in range(20):
            await a._write_force_discharge(1000.0 + i * 500.0)
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) <= a.FORCE_DISCHARGE_FAILURE_LIMIT, (
            f"{len(warnings)} warnings for one permanent condition — this is "
            "the 2,364-line log the reporter sent (#840)"
        )

    async def test_it_names_the_entity_so_the_line_is_actionable(self, caplog):
        import logging
        from custom_components.solar_energy_management.coordinator.battery_adapters import (  # noqa: E501
            base as _base,
        )
        caplog.set_level(logging.DEBUG, logger=_base.__name__)
        a, _ = _adapter()
        for i in range(a.FORCE_DISCHARGE_FAILURE_LIMIT):
            await a._write_force_discharge(1000.0 + i * 500.0)
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "number.growatt_power_setpoint" in text


class TestItDoesNotRepeatARefusedWrite:
    """The actual mechanism behind the 2,364 lines.

    ``command_normal`` / ``command_limit_discharge`` / ``command_off`` each
    write 0 W as #523 mutual exclusion, and command_normal runs on EVERY
    ordinary cycle. On @RienduPre's Growatt the export feature is dormant —
    every one of those failures came from that routine zero.

    It repeats unbounded BY CONSTRUCTION: ``_last_force_discharge_w`` is only
    assigned after a SUCCESSFUL call, so a failing write never records itself
    and the de-dup guard never engages.

    An earlier draft of this fix skipped the zero write entirely when SEM had
    never set a setpoint — "nothing to clear". That was WRONG and the suite
    caught it: `test_off_mode_idles_sessy_strategy` (#523, same reporter)
    requires OFF to write 0 to idle a Sessy. The setpoint is SHARED hardware
    state, not SEM's private value, so establishing a known value on first
    contact is the whole point. What must not repeat is a write that was
    already REFUSED.
    """

    async def test_the_first_write_still_happens(self):
        """Skipping it would leave a Sessy self-consuming on OFF (#523)."""
        a, calls = _adapter()
        await a._write_force_discharge(0.0)
        assert len(calls) == 1

    async def test_the_same_refused_value_is_not_re_issued(self):
        a, calls = _adapter()
        for _ in range(20):
            await a._write_force_discharge(0.0)
        assert len(calls) == 1, (
            f"{len(calls)} writes of a value the device had already refused — "
            "this is the every-cycle failure the reporter saw (#840)"
        )

    async def test_a_refused_write_is_not_recorded_as_applied(self):
        """It never reached the device; calling it 'applied' would skip a
        later genuine request while the hardware sat somewhere else."""
        a, _ = _adapter()
        await a._write_force_discharge(2000.0)
        assert a._last_force_discharge_w is None

    async def test_a_different_value_is_still_attempted(self):
        a, calls = _adapter()
        await a._write_force_discharge(0.0)
        await a._write_force_discharge(2000.0)
        assert len(calls) == 2

    async def test_success_clears_the_refusal_memory(self):
        a, _ = _adapter(fails=True)
        await a._write_force_discharge(0.0)
        a._hass.services.async_call = AsyncMock(return_value=True)
        await a._write_force_discharge(2000.0)
        assert a._last_force_discharge_attempt_w is None
        assert a._last_force_discharge_w == 2000.0
