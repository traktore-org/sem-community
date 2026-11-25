"""#1425 — the phase switch could still go out while the charger draws.

1. A car starts by itself. The power median needs two reads to follow it, so
   the first cycle reads 0 W. With no status sensor the tick took the box as
   at rest and the switch went out under load. The tick now also asks the
   RAW read of the same sensor: at rest only if both say nothing flows.
2. The power sensor is unavailable and the charger's start/stop switch reads
   off. ``charger_draws`` takes that as "cannot draw", and a box whose switch
   does not open its contactor was switched under load. For the PHASE
   SWITCH a dark power sensor is now no answer: it waits for a reading. Only
   a car known gone is at rest. The phase guard's stop is unchanged: stopping
   without a reading is safe (``charger_draws`` keeps its answer).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    charger_draws,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent, ChargerPower,
)
from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
    MIN_SWITCH_GAP_S, SETTLE_S,
)
from custom_components.solar_energy_management.coordinator.ev_availability import (
    charger_power_raw_w,
)

from .test_1423_blind_phase_switch import (
    DARK, NO_STATUS, SWITCH, T0, _adapter, _calls, _cp, _host, _max, _rig,
    _switches, _tick, _values,
)


def _cp_raw(median_w, raw_w):
    return ChargerPower(charger_id="c1", power_w=median_w, connected=True,
                        charging=False, power_known=True, power_raw_w=raw_w)


# ── case 1: a car that starts by itself ─────────────────────────────────


class TestSelfStart:

    def test_the_first_cycle_of_a_self_start_is_not_at_rest(self):
        """The median still reads 0 W, the raw read shows 11 kW."""
        h = _host()
        d = _tick(h, _max(), _cp_raw(0.0, 11040.0), 0.0)
        assert _calls(h) == 0, "switched under load"
        assert d.intent is ChargerIntent.DISABLE, "stop first"

    def test_the_twin_both_at_rest_switches(self):
        h = _host()
        _tick(h, _max(), _cp_raw(0.0, 0.0), 0.0)
        assert _calls(h) == 1

    def test_no_raw_read_keeps_deciding_on_the_median(self):
        h = _host()
        _tick(h, _max(), _cp_raw(0.0, None), 0.0)
        assert _calls(h) == 1

    def test_the_raw_read_reaches_the_view(self):
        """One producer: the reader's raw read, the view's ``power_raw_w``."""
        power = SimpleNamespace(ev_power_per_charger={"c1": 0.0},
                                ev_power_per_charger_raw={"c1": 11040.0})
        assert charger_power_raw_w("c1", power) == 11040.0
        dark = SimpleNamespace(ev_power_per_charger={"c1": 0.0},
                               ev_power_per_charger_raw={"c1": None})
        assert charger_power_raw_w("c1", dark) is None
        fleet = SimpleNamespace(ev_power_per_charger={},
                                ev_power_fleet_raw=5000.0)
        assert charger_power_raw_w("c1", fleet) == 5000.0


async def _run(rig, freezer, steps):
    """``steps``: (box power, phase_mode) per cycle, 10 s apart."""
    await _run_from(rig, freezer, T0, steps)


async def _run_from(rig, freezer, t, steps):
    for p, mode in steps:
        rig.coord.config["ev_chargers"][0]["phase_mode"] = mode
        freezer.move_to(datetime.fromtimestamp(t, tz=timezone.utc))
        for eid, val in _values(p).items():
            rig.hass.states.set(eid, val)
        await rig.coord._async_update_data()
        t += 10


@pytest.mark.asyncio
async def test_pipeline_a_self_start_in_the_real_cycle(freezer):
    """Three phases wanted while idle (no switch), then a car starts by
    itself in the same cycle one phase is chosen: the median still reads
    0 W, and no switch may go out under load."""
    rig = _rig()
    # idle long enough that any switch from the idle part has settled and
    # its minimum gap has passed
    idle = int(max(SETTLE_S, MIN_SWITCH_GAP_S) / 10) + 3
    await _run(rig, freezer, [(0.0, "3")] * idle)
    before = len(_switches(rig))
    # the car starts by itself: the median has two 0 W reads to outvote it
    await _run_from(rig, freezer, T0 + 10 * idle, [(11040.0, "1")] * 3)
    assert len(_switches(rig)) == before, _switches(rig)[before:]


# ── case 2: dark power, switch reads off ────────────────────────────────


OFF_SWITCH = _adapter(enabled=False)


class TestDarkWithSwitchOff:

    def test_the_issue_a_dark_box_with_its_switch_off_is_not_switched(self):
        h = _host()
        for i in range(10):
            _tick(h, _max(), DARK, 10.0 * i, adapter=OFF_SWITCH)
        assert _calls(h) == 0

    def test_without_an_adapter_a_dark_box_waits_too(self):
        h = _host()
        _tick(h, _max(), DARK, 0.0, adapter=None)
        assert _calls(h) == 0

    def test_a_status_that_says_not_charging_waits_for_the_power(self):
        h = _host()
        _tick(h, _max(), DARK, 0.0, adapter=_adapter(status=False))
        assert _calls(h) == 0

    def test_a_car_known_gone_is_at_rest(self):
        h = _host(states={"binary_sensor.box_plug": "off"},
                  ev_connected_sensor="binary_sensor.box_plug")
        cp = _cp(0.0, charging=False, known=False, connected=False)
        _tick(h, _max(), cp, 0.0)
        assert _calls(h) == 1

    def test_the_power_back_at_0_w_switches(self):
        h = _host()
        _tick(h, _max(), DARK, 0.0, adapter=OFF_SWITCH)
        _tick(h, _max(), _cp(0.0, charging=False), 400.0, adapter=OFF_SWITCH)
        assert _calls(h) == 1

    def test_the_guard_stop_rule_is_unchanged(self):
        """``charger_draws`` — what the phase guard's stop asks — still
        says a dark box whose switch reads off cannot draw."""
        assert charger_draws(OFF_SWITCH, DARK) is False
        assert charger_draws(NO_STATUS, DARK) is None


@pytest.mark.asyncio
async def test_pipeline_dark_power_switch_off(freezer):
    rig = _rig()
    t = T0
    for _ in range(6):
        freezer.move_to(datetime.fromtimestamp(t, tz=timezone.utc))
        vals = _values("unavailable")
        vals["switch.box_enable"] = "off"
        for eid, val in vals.items():
            rig.hass.states.set(eid, val)
        await rig.coord._async_update_data()
        t += 10
    assert _switches(rig) == [], _switches(rig)
