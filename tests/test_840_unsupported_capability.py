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
        a, calls = _adapter()
        for _ in range(10):
            await a._write_force_discharge(2000.0)
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
        await a._write_force_discharge(2100.0)
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
        for _ in range(a.FORCE_DISCHARGE_FAILURE_LIMIT):
            await a._write_force_discharge(2000.0)
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
        for _ in range(20):
            await a._write_force_discharge(2000.0)
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
        for _ in range(a.FORCE_DISCHARGE_FAILURE_LIMIT):
            await a._write_force_discharge(2000.0)
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "number.growatt_power_setpoint" in text


class TestItNeverZeroesASetpointItNeverSet:
    """The actual mechanism behind the 2,364 lines.

    ``command_normal`` / ``command_limit_discharge`` / ``command_off`` each
    write 0 W as #523 mutual exclusion, and command_normal runs on EVERY
    ordinary cycle. On @RienduPre's Growatt the export feature is dormant —
    every one of those failures came from this defensive zero, not from
    arbitrage.

    It is unbounded by construction: ``_last_force_discharge_w`` is only
    assigned after a SUCCESSFUL call, so a failing write never records itself
    and the de-dup guard below it never engages.
    """

    async def test_a_zero_write_is_skipped_when_nothing_was_ever_set(self):
        a, calls = _adapter()
        for _ in range(10):
            await a._write_force_discharge(0.0)
        assert calls == [], (
            f"{len(calls)} writes to clear a setpoint SEM never set — this is "
            "the every-cycle failure the reporter saw (#840)"
        )

    async def test_it_does_not_burn_the_failure_budget(self):
        """A device that never gets asked cannot be judged unsupported."""
        a, _ = _adapter()
        for _ in range(10):
            await a._write_force_discharge(0.0)
        assert a._force_discharge_failures == 0
        assert a.supports_forced_discharge is True, (
            "the capability was withdrawn on the strength of writes that "
            "never happened"
        )

    async def test_a_real_setpoint_still_gets_cleared(self):
        """The mutual exclusion must still work once there IS something to
        undo — skipping the clear would leave a battery exporting."""
        a, calls = _adapter(fails=False)
        await a._write_force_discharge(2000.0)
        await a._write_force_discharge(0.0)
        assert len(calls) == 2, calls
        assert calls[-1]["value"] == 0.0
