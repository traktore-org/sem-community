"""(#1369, step 1) One goal object for a hot water tank — built in the shadow.

Nothing decides by the goal yet. The controller builds it beside today's code
each cycle and counts where the two differ. These tests pin that the goal
agrees with today's decisions everywhere EXCEPT the two documented spots, and
that the shadow changes and publishes nothing. C1 is FIXED (#1369):
the live code now does what the goal says.

The documented differences (the goal picks ONE side):
  C1  start reads the band's sensor, a switched tank's stop reads the tank's
      sensor -> the goal reads ONE: the band's when the band is in use.
  C2  away with the dump on: today a too-cold tank whose limit is above the
      minimum temperature is stopped at the minimum -> the goal lets it heat
      back above its limit (too cold wins).
Not judged in step 1: C3 (Legionella's natural 60 °C) and C4 (Legionella state
runs after the engine).
"""
from __future__ import annotations

import copy
import itertools
from dataclasses import fields, replace
from datetime import timedelta
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.devices import hot_water_controller as hwc
from custom_components.solar_energy_management.devices import tank_goal as tg
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.devices.tank_goal import (
    TankInputs, build_tank_goal, differences,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management.tests import test_1102_use_cases as uc1102
from custom_components.solar_energy_management.tests import test_1344_heater_matrix as hm
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)
from custom_components.solar_energy_management.tests.test_1369_band_decides_top import (
    SENSOR, SWITCH, _tank,
)

COUNTERS = ("tank_goal_diffs", "tank_goal_last", "tank_goal_errors")


def inp(**kw) -> TankInputs:
    """Keep at 52, Extra 4, Run now past 36, Solar Heating Target 50,
    Legionella 60, minimum 40; one thermometer at 45 °C."""
    base = dict(tank_c=45.0, band_c=45.0, keep_c=52.0, extra_c=4.0,
                too_cold_c=36.0, fallback_top_c=50.0, min_temperature_c=40.0,
                legionella_target_c=60.0)
    base.update(kw)
    if "tank_c" in kw and "band_c" not in kw:
        base["band_c"] = kw["tank_c"]
    return TankInputs(**base)


def goal(**kw):
    return build_tank_goal(inp(**kw))


# ── the goal, alone ────────────────────────────────────────────────────────

class TestTheGoalAlone:
    def test_a_band_in_use_sets_the_top_keep_at_plus_extra(self):
        g = goal(tank_c=45.0)
        assert (g.top, g.top_source, g.stop_at) == (56.0, "band", 56.0)
        assert (g.keep_at, g.too_cold_below, g.band_state) == (52.0, 36.0, "willing")
        assert g.reading_source == "band"

    def test_the_top_is_capped_at_the_legionella_target(self):
        assert goal(extra_c=10.0).top == 60.0
        assert goal(extra_c=10.0, legionella_target_c=58.0).top == 58.0

    @pytest.mark.parametrize("kw", [
        dict(band_c=None),                              # its thermometer is silent
        dict(too_cold_c=52.0),                          # limit not below Keep at
        dict(too_cold_c=55.0),
        dict(keep_c=None, extra_c=None, too_cold_c=None),   # no band
    ])
    def test_a_band_that_cannot_be_used_falls_back_to_the_solar_target(self, kw):
        g = goal(**kw)
        assert (g.top, g.top_source) == (50.0, "fallback")
        assert g.band_state == "disengaged"

    def test_a_user_stop_below_the_top_is_the_top(self):
        g = goal(user_stop_c=54.0)
        assert (g.top, g.top_source) == (54.0, "user_stop")
        assert g.legionella_blocked is True        # 54 < 60: no run can reach it

    def test_a_user_stop_at_the_legionella_target_blocks_nothing(self):
        assert goal(user_stop_c=60.0).legionella_blocked is False
        assert goal(user_stop_c=61.0).legionella_blocked is False
        assert goal(user_stop_c=None).legionella_blocked is False

    def test_too_cold_may_start_whatever_the_margin_says(self):
        # a stop at 35.5 puts the start line at 34.5: 35 is inside the margin
        assert goal(tank_c=35.0, user_stop_c=35.5, band_c=40.0).may_start is False
        g = goal(tank_c=35.0, user_stop_c=35.5)
        assert (g.band_state, g.may_start) == ("forced", True)
        assert g.needs_heat_now is True and g.reason == "too_cold"

    def test_the_start_margin_is_one_kelvin(self):
        assert goal(tank_c=55.0).may_start is True
        assert goal(tank_c=55.1).may_start is False
        assert goal(tank_c=55.0).start_below == 55.0

    def test_a_refused_start_waits_a_little_more(self):
        assert goal(tank_c=54.9, margin_refused=True).may_start is False
        assert goal(tank_c=54.8, margin_refused=True).may_start is True

    def test_at_the_top_it_must_stop(self):
        g = goal(tank_c=56.0)
        assert (g.must_stop, g.band_state, g.reason) == (True, "banked", "at_stop")
        assert goal(tank_c=55.9).must_stop is False

    def test_a_tank_without_a_band_stops_at_the_solar_target(self):
        g = goal(keep_c=None, extra_c=None, too_cold_c=None, tank_c=50.0, band_c=None)
        assert g.must_stop is True
        assert goal(keep_c=None, extra_c=None, too_cold_c=None, tank_c=49.9,
                    band_c=None).must_stop is False

    def test_a_setpoint_tank_ends_its_own_run_at_the_setpoint(self):
        g = goal(keep_c=None, extra_c=None, too_cold_c=None, tank_c=50.0,
                 band_c=None, switched=False)
        assert g.must_stop is False          # its thermostat stops it
        assert goal(switched=False, user_stop_c=44.0).must_stop is True
        assert goal(switched=False, tank_c=56.0).must_stop is True   # banked

    def test_away_without_the_dump_keeps_the_old_target(self):
        g = goal(vacation=True)
        assert (g.band_state, g.top, g.top_source) == ("disengaged", 50.0, "fallback")

    def test_away_with_the_dump_tops_at_the_minimum(self):
        g = goal(vacation=True, vacation_dump=True, tank_c=41.0)
        assert (g.top, g.top_source, g.must_stop) == (40.0, "away", True)
        assert goal(vacation=True, vacation_dump=True, tank_c=39.0).must_stop is False

    def test_away_too_cold_still_heats(self):
        g = goal(vacation=True, vacation_dump=True, tank_c=35.0)
        assert (g.may_start, g.must_stop, g.needs_heat_now) == (True, False, True)

    def test_c2_away_too_cold_wins_above_the_minimum(self):
        """Limit 45 above the minimum 40: heats on to the limit, not to 40."""
        g = goal(vacation=True, vacation_dump=True, too_cold_c=45.0, tank_c=44.0)
        assert (g.must_stop, g.may_start, g.top) == (False, True, 45.0)
        assert goal(vacation=True, vacation_dump=True, too_cold_c=45.0,
                    tank_c=45.1).must_stop is True

    def test_a_legionella_run_heats_to_its_own_target(self):
        g = goal(legionella_active=True, tank_c=55.0)
        assert (g.stop_at, g.top_source) == (60.0, "legionella")
        assert (g.needs_heat_now, g.must_stop, g.may_start) == (True, False, True)
        assert g.reason == "legionella_run"

    def test_a_legionella_hold_needs_no_heat_near_its_target(self):
        base = dict(legionella_active=True, legionella_hold=True)
        assert goal(tank_c=59.8, **base).needs_heat_now is False       # 60 - 0.3 = 59.7
        assert goal(tank_c=59.6, **base).needs_heat_now is True
        assert goal(tank_c=60.5, **base).must_stop is True              # off above +0.5
        assert goal(tank_c=60.4, **base).must_stop is False
        # once off it stays off until the dip
        assert goal(tank_c=59.8, hold_stopped=True, **base).must_stop is True
        assert goal(tank_c=59.6, hold_stopped=True, **base).must_stop is False

    def test_a_legionella_run_without_a_reading_needs_heat(self):
        g = goal(legionella_active=True, tank_c=None, band_c=None)
        assert g.needs_heat_now is True and g.may_start is True

    def test_silent_sensor_is_not_heated_blind(self):
        g = goal(tank_c=None, band_c=None, keep_c=None, extra_c=None,
                 too_cold_c=None, sensor_expected=True)
        assert (g.may_start, g.reason) == (False, "no_reading")
        assert goal(tank_c=None, band_c=None, sensor_expected=False).may_start is True

    def test_c1_one_reading_the_bands_when_the_band_is_in_use(self):
        g = goal(tank_c=40.0, band_c=57.0)
        assert (g.reading_c, g.reading_source, g.must_stop) == (57.0, "band", True)
        g = goal(tank_c=57.0, band_c=None)
        assert (g.reading_c, g.reading_source) == (57.0, "tank")

    def test_the_goal_is_in_celsius_and_has_no_unit_input(self):
        assert not [f.name for f in fields(TankInputs) if "unit" in f.name or f.name.endswith("_f")]
        assert goal().top == 56.0

    def test_the_inputs_are_frozen_and_the_rules_have_no_price(self):
        with pytest.raises(Exception):
            inp().tank_c = 1.0            # type: ignore[misc]
        assert not [f.name for f in fields(TankInputs) if "price" in f.name or "tariff" in f.name]
        assert replace(inp(), may_buy=True).may_buy is True

    def test_the_constants_are_the_controllers(self):
        # (#1369) one definition: the controller imports tank_goal's numbers
        for name in ("START_MARGIN_K", "START_MARGIN_STICKY_K",
                     "LEGIONELLA_HOLD_BAND_K", "LEGIONELLA_HOLD_DIP_K"):
            assert getattr(hwc, name) is getattr(tg, name)
        src = open(hwc.__file__).read()
        assert "edge -= 0." not in src and "0.2" not in src.split("def start_refusal")[1][:2000]


# ── the controller's inputs ────────────────────────────────────────────────

class TestTheControllersInputs:
    def test_a_fahrenheit_install_reads_in_celsius(self):
        hass = _Hass(unit="°F")
        hass.set(SWITCH, "off")
        hass.set(SENSOR, "113.0", unit_of_measurement="°F")
        dev = HotWaterController(hass=hass, entity_id=SWITCH, temperature_entity_id=SENSOR)
        assert dev.tank_goal_inputs().tank_c == pytest.approx(45.0)

    def test_a_missing_sensor_reads_as_blind_only_when_none_is_set_up(self):
        hass = _Hass()
        hass.set(SWITCH, "off")
        blind = HotWaterController(hass=hass, entity_id=SWITCH)
        assert blind.tank_goal_inputs().sensor_expected is False
        hass.set(SENSOR, "unavailable")
        broken = HotWaterController(hass=hass, entity_id=SWITCH, temperature_entity_id=SENSOR)
        assert broken.tank_goal_inputs().sensor_expected is True

    def test_a_stop_on_another_sensor_is_carried_as_met(self):
        hass = _Hass()
        dev = _tank(hass, 45.0)
        hass.set("sensor.car", "80")
        dev.stop_entity, dev.stop_at = "sensor.car", 80.0
        i = dev.tank_goal_inputs()
        assert i.user_stop_c is None and i.other_stop_met is True
        assert dev.stop_condition_met is True and dev.tank_goal().must_stop is True


# ── the goal beside today's decisions ──────────────────────────────────────

def _agree(dev, *, allow=()):
    """Every compared field, plus may_start and needs_heat_now, must match
    what the controller says. Returns the differences (may_start included)."""
    g = dev.tank_goal()
    seen = dev._goal_seen()
    diffs = differences(g, seen)
    assert set(diffs) <= set(allow), (diffs, dev.__dict__.get("vacation"), g)
    dev._margin_refused = bool(dev.tank_goal_inputs().margin_refused)
    today_may_start = dev.start_refusal is None
    if g.may_start is not today_may_start:
        assert "may_start" in allow, (g, dev.start_refusal)
        diffs["may_start"] = (g.may_start, today_may_start)
    if dev._legionella_cycle_active:
        assert g.needs_heat_now is dev.own_run_needs_heat, g
    return diffs


class TestTheShadowAgreesOnTheTestFixtures:
    @pytest.mark.parametrize("temp", [30.0, 36.0, 40.0, 49.9, 50.0, 51.0, 55.0, 55.5, 56.0, 62.0])
    @pytest.mark.parametrize("band", [True, False])
    @pytest.mark.parametrize("entity", [SWITCH, "water_heater.dhw"])
    def test_1369_tanks(self, temp, band, entity):
        dev = _tank(_Hass(), temp, band=band, entity_id=entity)
        assert _agree(dev) == {}
        dev.vacation = True
        assert _agree(dev) == {}
        dev.vacation_dhw_surplus = True
        # C2 needs a limit above the minimum; this fixture's 36 is below it
        assert _agree(dev) == {}

    def test_1369_legionella_and_stop(self):
        dev = _tank(_Hass(), 58.0)
        dev._legionella_cycle_active = True
        assert _agree(dev) == {}
        dev._legionella_hold_start = hwc.dt_util.now()
        for t in (59.6, 59.8, 60.2, 60.6, 59.8, 59.6):
            dev.hass.set(SENSOR, str(t), unit_of_measurement="°C")
            assert _agree(dev) == {}, t

    @pytest.mark.parametrize("tank", list(hm.TANKS))
    @pytest.mark.parametrize("away", hm.AWAY)
    @pytest.mark.asyncio
    async def test_1344_matrix_tanks_through_the_engine(self, tank, away):
        hass, sc, dev = hm._build(HotWaterController, "cheap_hours", tank, "night_block", away)
        assert _agree(dev) == {}
        kw = hm._inputs("night_block")
        power = kw.pop("available_power_w")
        for _ in range(8):
            await sc.update(power, **kw)
        assert dev.tank_goal_diffs == {} and dev.tank_goal_errors == 0, (
            tank, away, dev.tank_goal_diffs)
        assert _agree(dev) == {}

    @pytest.mark.parametrize("stop", [None, 53.0, 50.0])
    @pytest.mark.asyncio
    async def test_1102_boiler_through_the_engine(self, stop):
        hass, dev, sc = uc1102._boiler(47.6, stop=stop)
        for temp in (47.6, 50.0, 53.5, 55.0, 56.0, 36.0, 34.0, 52.0):
            hass.set(uc1102.SENSOR, str(temp), unit_of_measurement="°C")
            await uc1102._cycle(sc, night=False, solar=5000.0, surplus=3000.0)
            assert _agree(dev) == {}, temp
        assert dev.tank_goal_diffs == {} and dev.tank_goal_errors == 0

    @pytest.mark.asyncio
    async def test_1102_legionella_run_through_the_engine(self):
        hass, dev, sc = uc1102._boiler(50.0)
        dev._last_legionella_time = hwc.dt_util.now() - timedelta(hours=80)
        t0 = hwc.dt_util.now()
        for minute, temp in ((0, 50.0), (60, 60.2), (80, 60.1), (90, 60.0)):
            hass.set(uc1102.SENSOR, str(temp), unit_of_measurement="°C")
            with patch.object(hwc.dt_util, "now", return_value=t0 + timedelta(minutes=minute)):
                await dev.check_legionella_cycle(good_hour=False)
                await uc1102._cycle(sc)
            assert _agree(dev) == {}, (minute, temp)
        assert dev.tank_goal_diffs == {} and dev.tank_goal_errors == 0


# ── the grid sweep: only C1 and C2 may differ ───────────────────────────────

def _sweep_dev(hass):
    hass.set(SWITCH, "off")
    hass.set(SENSOR, "45", unit_of_measurement="°C")
    dev = HotWaterController(
        hass=hass, entity_id=SWITCH, temperature_entity_id=SENSOR,
        solar_target_temp=50.0, legionella_target_temp=60.0)
    dev.comfort_entity = SENSOR
    return dev


def _expected_c2(temp, limit, stop, away_dump, leg):
    """The goal and today's code differ here, and only here, on (top, must_stop)."""
    if not away_dump or leg or temp > limit:
        return set()
    cap = lambda v: v if stop is None else min(v, stop)  # noqa: E731
    out = set()
    # today the start is also refused at the Solar Heating Target (50) while
    # the goal lets a too-cold tank start; the margin to a stop still applies
    if temp >= 50.0 and (stop is None or temp <= stop - 1.0):
        out.add("may_start")
    if cap(max(40.0, limit)) != cap(40.0):
        out.add("top")
    if temp >= 40.0 and not (stop is not None and temp >= stop):
        out.add("must_stop")
    return out


def test_the_grid_sweep_differs_only_where_c2_says():
    hass = _Hass()
    dev = _sweep_dev(hass)
    c2_seen = {"top": 0, "must_stop": 0, "may_start": 0}
    points = 0
    combos = itertools.product(
        range(30, 71, 2), (45.0, 52.0), (0.0, 4.0, 9.0), (36.0, 44.0, 50.0),
        (None, 44.0, 50.0, 58.0, 65.0), ("home", "dump", "nodump"),
        ("off", "run", "hold"))
    for temp, keep, extra, limit, stop, away, leg in combos:
        hass.set(SENSOR, str(float(temp)), unit_of_measurement="°C")
        dev.comfort_target, dev.comfort_offset, dev.comfort_limit = keep, extra, limit
        dev.stop_entity, dev.stop_at = (SENSOR, stop) if stop is not None else ("", 0.0)
        dev.vacation = away != "home"
        dev.vacation_dhw_surplus = away == "dump"
        dev._legionella_cycle_active = leg != "off"
        dev._legionella_hold_start = hwc.dt_util.now() if leg == "hold" else None
        dev._margin_refused = dev._hold_stopped = False
        usable = limit < keep
        want = _expected_c2(float(temp), limit, stop, away == "dump", leg != "off") if usable else set()
        got = _agree(dev, allow=("top", "must_stop", "may_start"))
        assert set(got) == want, (temp, keep, extra, limit, stop, away, leg, got, want)
        for name in got:
            c2_seen[name] += 1
        points += 1
    # the sweep is not vacuous, and C2 really shows up in it
    assert points > 15000
    assert all(n > 0 for n in c2_seen.values()), c2_seen


def test_the_registry_publishes_the_goals_top():
    """The line the cards read (max_c) is the goal's top at home, no run."""
    hass = _Hass()
    dev = _sweep_dev(hass)
    for temp, extra, stop in itertools.product((40.0, 52.0), (0.0, 4.0, 9.0), (None, 50.0, 58.0)):
        hass.set(SENSOR, str(temp), unit_of_measurement="°C")
        dev.comfort_target, dev.comfort_offset, dev.comfort_limit = 52.0, extra, 36.0
        dev.stop_entity, dev.stop_at = (SENSOR, stop) if stop is not None else ("", 0.0)
        shown = UnifiedDeviceRegistry._band_lines(dev)["max_c"]
        assert dev.tank_goal().top == pytest.approx(shown), (temp, extra, stop)


# ── C1: the two sensors ─────────────────────────────────────────────────────

class TestC1TheTwoThermometers:
    def _two(self, tank, band):
        hass = _Hass()
        dev = _tank(hass, tank)
        hass.set("sensor.band", str(band), unit_of_measurement="°C")
        dev.comfort_entity = "sensor.band"
        # Keep at 52 + Extra 10 = 62, capped at the Legionella 60: the band's
        # own "banked" line (62) sits above the top, so only the reading
        # decides — the tank sensor today, the band's in the goal
        dev.comfort_offset = 10.0
        return dev

    def test_a_switched_tank_stops_by_the_band_sensor_like_the_goal(self):
        # (#1369, C1) start and stop read the band's sensor now
        dev = self._two(tank=45.0, band=61.0)    # band says hot, tank says cool
        assert dev.stop_condition_met is True
        assert differences(dev.tank_goal(), dev._goal_seen()) == {}
        dev = self._two(tank=61.0, band=45.0)
        assert dev.stop_condition_met is False
        assert differences(dev.tank_goal(), dev._goal_seen()) == {}

    def test_start_and_stop_read_the_same_sensor(self):
        # the band's top is 60 (Keep 52 + Extra 10, capped by Legionella 60)
        for tank, band in ((45.0, 59.0), (59.0, 45.0), (45.0, 61.0)):
            dev = self._two(tank=tank, band=band)
            starts = dev.start_refusal is None
            stops = dev.stop_condition_met
            assert starts == (band <= 60.0 - 1.0), (tank, band)
            assert stops == (band >= 60.0), (tank, band)

    def test_no_band_sensor_reads_the_tank_sensor(self):
        dev = _tank(_Hass(), 61.0, band=False)
        assert dev.stop_condition_met is True
        assert differences(dev.tank_goal(), dev._goal_seen()) == {}

    @pytest.mark.asyncio
    async def test_the_engine_counts_no_difference_any_more(self):
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            SurplusController,
        )
        dev = self._two(tank=45.0, band=61.0)
        sc = SurplusController(dev.hass)
        sc.register_device(dev)
        kw = dict(price_level="normal", is_night=False, battery_soc=50.0,
                  battery_reserve_soc=10.0, daylight_remaining_s=3600.0, solar_w=5000.0)
        for _ in range(3):
            await sc.update(4000.0, **kw)
        assert dev.tank_goal_diffs == {} and dev.tank_goal_errors == 0


def _shadow_diff(dev):
    """A made-up difference: the plumbing tests need one, and no known
    difference is left (C1 and C2 are fixed)."""
    return patch.object(dev, "_goal_seen", return_value={"must_stop": True})


# ── the shadow itself ───────────────────────────────────────────────────────

def _state(dev):
    return {k: v for k, v in dev.__dict__.items() if k not in COUNTERS}


class TestTheShadowChangesNothing:
    def _warm(self, dev):
        """What the engine has called this cycle before the shadow runs."""
        dev.comfort_state, dev.stop_condition_met, dev.start_refusal  # noqa: B018
        dev._active_target_temp()
        dev.legionella_blocked_by_stop  # noqa: B018

    @pytest.mark.parametrize("setup", ["plain", "legionella_hold", "away_dump",
                                       "misconfigured", "silent"])
    def test_no_state_changes(self, setup):
        hass = _Hass()
        dev = _tank(hass, 59.8 if setup == "legionella_hold" else 45.0)
        if setup == "legionella_hold":
            dev._legionella_cycle_active = True
            dev._legionella_hold_start = hwc.dt_util.now()
            dev._hold_stopped = True
        elif setup == "away_dump":
            dev.vacation = dev.vacation_dhw_surplus = True
        elif setup == "misconfigured":
            dev.comfort_limit = 60.0
        elif setup == "silent":
            hass.set(SENSOR, "unavailable")
        before = copy.copy(_state(dev))
        dev.tank_goal()                        # cold: not even the warm-up flags
        assert _state(dev) == before
        self._warm(dev)
        before = copy.copy(_state(dev))
        dev.tank_goal()
        dev.compare_tank_goal()
        dev.compare_tank_goal()
        assert _state(dev) == before

    def test_a_broken_input_never_raises_and_is_counted(self):
        dev = _tank(_Hass(), 45.0)
        dev.solar_target_temp = "broken"
        dev.compare_tank_goal()
        assert dev.tank_goal_errors == 1 and dev.tank_goal_diffs == {}
        with patch.object(dev, "tank_goal", side_effect=RuntimeError("x")):
            dev.compare_tank_goal()
        assert dev.tank_goal_errors == 2

    def test_a_new_kind_of_difference_logs_once(self, caplog):
        from custom_components.solar_energy_management.utils.log_gate import reset_log_gate
        reset_log_gate()
        hass = _Hass()
        dev = _tank(hass, 45.0)
        with caplog.at_level("INFO"), _shadow_diff(dev):
            for _ in range(5):
                dev.compare_tank_goal()
        lines = [r for r in caplog.records if "tank goal differs" in r.getMessage()]
        assert len(lines) == 1 and dev.tank_goal_diffs == {"must_stop": 5}
        del hass

    def test_nothing_is_published_without_a_difference(self):
        dev = _tank(_Hass(), 45.0)
        dev.compare_tank_goal()
        assert UnifiedDeviceRegistry._goal_shadow(dev) == {}
        assert "goal_shadow" not in UnifiedDeviceRegistry._comfort_payload(dev)

    def test_the_counts_are_published_when_there_are_some(self):
        dev = _tank(_Hass(), 45.0)
        with _shadow_diff(dev):
            dev.compare_tank_goal()
        out = UnifiedDeviceRegistry._comfort_payload(dev)
        assert out["goal_shadow"] == {"diffs": {"must_stop": 1}, "errors": 0}
        dev.tank_goal_diffs, dev.tank_goal_errors = {}, 2
        assert UnifiedDeviceRegistry._goal_shadow(dev) == {"goal_shadow": {"diffs": {}, "errors": 2}}

    def test_a_stand_in_without_the_counters_publishes_nothing(self):
        from unittest.mock import MagicMock
        assert UnifiedDeviceRegistry._goal_shadow(MagicMock()) == {}


# ── the shadow writes nothing (#1369) ───────────────────────────────────────
# A review ran the engine with the shadow on and patched out and found a
# changed decision: the shadow read the stop rule (which stores the Legionella
# hold's off/on) in cycles where the engine returns before it ever does.

import asyncio  # noqa: E402
from contextlib import ExitStack  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from freezegun import freeze_time  # noqa: E402

from custom_components.solar_energy_management.consts.states import (  # noqa: E402
    LoadManagementState,
)
from custom_components.solar_energy_management.coordinator import (  # noqa: E402
    reason_codes as RC,
    surplus_controller as sc_mod,
)

_APART = ("hass", "_controller")     # per-run objects; every other field must match
_NOW = "2026-11-10 22:00:00"
_SUN = dict(surplus=4000.0, night=False, solar=5000.0)


def _hold(dev, *, hold_stopped=False):
    """A switched tank in its Legionella hold (the run reached its target)."""
    dev._legionella_cycle_active = True
    dev._legionella_hold_start = hwc.dt_util.now()
    dev._hold_stopped = hold_stopped


def _reading(hass, value):
    hass.set(uc1102.SENSOR, str(value), unit_of_measurement="°C")


async def _cyc(sc, *, peak=None, **kw):
    kw.setdefault("price", "normal")
    price = kw.pop("price")
    block = kw.pop("block", False)
    surplus = kw.pop("surplus", -400.0)
    night = kw.pop("night", True)
    solar = kw.pop("solar", 0.0)
    await sc.update(
        surplus, price_level=price, import_price=uc1102.PRICES[price],
        is_night=night, battery_soc=None, battery_reserve_soc=10.0,
        daylight_remaining_s=0.0 if night else 7200.0, solar_w=solar,
        peak_state=peak,
        plan_windows=({uc1102.DID: uc1102.BLOCK} if block is True
                      else {uc1102.DID: uc1102.CLOSED} if block == "closed" else {}))


def _lock(on):
    def go(hass, dev, sc):
        dev.behind_operator_relay = True
        sc.shed_signal = SimpleNamespace(active=on)
    return go


def _set(value, *more):
    def go(hass, dev, sc):
        _reading(hass, value)
        for fn in more:
            fn(hass, dev, sc)
    return go


def _do(fn):
    return lambda hass, dev, sc: fn(dev)


def _steps(*pairs):
    return list(pairs)


def _seq_lock():
    """The review's sequence: the hold at 60.6, an early return (operator
    lock), then 59.9 — the hold's hysteresis decides whether it stops."""
    return dict(temp=45.0, steps=_steps(
        (None, _SUN),
        (_set(60.6, _do(_hold), _lock(True)), {}),
        (_set(60.6), {}),
        (_set(59.9, _lock(False)), {}),
        (_set(59.9), {}),
        (_set(60.6), {})))


def _seq_shed():
    return dict(temp=45.0, steps=_steps(
        (None, _SUN),
        (_set(60.6, _do(_hold)), dict(peak=LoadManagementState.EMERGENCY)),
        (_set(59.9), {}),
        (_set(59.9), dict(peak=LoadManagementState.EMERGENCY)),
        (_set(59.9), {}),
        (_set(60.7), {})))


def _seq_plan_hold():
    return dict(temp=45.0, steps=_steps(
        (None, dict(price="cheap", block=True)),
        (_set(60.6, _do(_hold), _do(lambda d: setattr(d, "_offpeak_forced", True))),
         dict(price="cheap", block="closed")),
        (_set(59.9), dict(price="cheap", block=False)),
        (_set(60.6), dict(price="cheap", block="closed")),
        (_set(59.9), dict(price="cheap", block=False))))


def _seq_unread():
    return dict(temp=45.0, steps=_steps(
        (None, _SUN),
        (lambda h, d, s: h.set(uc1102.SENSOR, "unavailable"), _SUN),
        (lambda h, d, s: h.set(uc1102.SENSOR, "unknown"), _SUN),
        (_set(50.0), _SUN),
        (_set(56.0), _SUN)))


def _seq_top_in_min_run():
    return dict(temp=47.6, steps=_steps(
        (None, dict(price="cheap", block=True)),
        (_set(52.0), dict(price="cheap")),         # at Keep at, inside the minimum run
        (_set(56.0), dict(price="cheap")),
        (_set(57.0, _do(lambda d: setattr(d, "stop_entity", uc1102.SENSOR)),
              _do(lambda d: setattr(d, "stop_at", 56.5))), dict(price="cheap"))))


def _seq_away_dump():
    return dict(temp=40.0, steps=_steps(
        (_do(lambda d: (setattr(d, "vacation", True),
                        setattr(d, "vacation_dhw_surplus", True))), _SUN),
        (_set(30.0), _SUN),
        (_set(36.5), _SUN),
        (_set(40.0), _SUN),
        (_set(47.0), _SUN),
        (_do(lambda d: setattr(d, "vacation", False)), _SUN)))


def _seq_1102_night():
    """tests/test_1102_use_cases.py test_2: a cheap block, 50.1, the plan's
    hold, Keep at reached."""
    return dict(temp=47.6, steps=_steps(
        (None, dict(price="cheap", block=True)),
        (_set(50.1, _do(uc1102._past_minimums)), dict(price="cheap", block=False)),
        (None, dict(price="cheap", block="closed")),
        (_set(52.0), dict(price="cheap", block="closed")),
        (None, dict(price="cheap", block="closed")),
        (_set(35.5), dict(price="expensive", night=False))))


_SEQUENCES = {
    "legionella_hold_then_lock": _seq_lock, "peak_shed": _seq_shed,
    "plan_hold": _seq_plan_hold, "unread_sensor": _seq_unread,
    "top_inside_min_run": _seq_top_in_min_run, "away_dump": _seq_away_dump,
    "boiler_night": _seq_1102_night}


def _canon(v, seen=None):
    """A value as plain data, so two runs compare by CONTENT (an object with
    no ``__eq__`` — the held-power tracker — would else differ by identity)."""
    if isinstance(v, (str, int, float, bool, bytes, type(None))) or hasattr(v, "isoformat"):
        return v
    seen = set() if seen is None else seen
    if id(v) in seen:                  # a shared or circular reference
        return "<again>"
    seen.add(id(v))
    if isinstance(v, dict):
        return {str(k): _canon(x, seen) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)) or hasattr(v, "maxlen"):
        return [_canon(x, seen) for x in v]
    if type(v).__module__.startswith("unittest.mock") or callable(v):
        return f"<{type(v).__name__}>"
    if hasattr(v, "__dict__"):
        return (type(v).__name__, _canon(vars(v), seen))
    return repr(v)


def _public(dev):
    block = UnifiedDeviceRegistry._comfort_payload(dev)
    block = {k: v for k, v in block.items() if k != "goal_shadow"}
    return {"comfort": block,
            "path": getattr(dev, "_last_temperature_reading_path", None),
            "reading": getattr(dev, "_last_temperature_reading", None)}


def _run(build, shadow):
    """One pass of a sequence through the REAL engine and tank. Time stands
    still (one tick per cycle), so every timer is comparable."""
    seq = build()
    trace, codes = [], []
    real = sc_mod.compute_load_intent

    def spy(device, **kw):
        out = real(device, **kw)
        codes.append((out.on, out.source, out.code, out.reason))
        return out

    async def go():
        hass, dev, sc = uc1102._boiler(seq["temp"])
        with ExitStack() as stack:
            stack.enter_context(patch.object(sc_mod, "compute_load_intent", spy))
            if not shadow:
                stack.enter_context(patch.object(
                    HotWaterController, "compare_tank_goal", lambda *a, **k: None))
            for setup, cycle in seq["steps"]:
                if setup is not None:
                    setup(hass, dev, sc)
                n = len(codes)
                await _cyc(sc, **cycle)
                clock.tick(60)
                state = {k: v for k, v in dev.__dict__.items()
                         if k not in COUNTERS + ("tank_goal_skipped",) + _APART}
                trace.append((codes[n:], _canon(state), _canon(_public(dev))))
        return trace

    with freeze_time(_NOW, real_asyncio=True) as clock:
        return asyncio.run(go())


@pytest.mark.parametrize("name", sorted(_SEQUENCES))
def test_the_engine_decides_the_same_with_the_shadow_on_or_off(name):
    with_shadow = _run(_SEQUENCES[name], True)
    without = _run(_SEQUENCES[name], False)
    assert len(with_shadow) == len(without) > 3
    for i, (a, b) in enumerate(zip(with_shadow, without, strict=True)):
        assert a[0] == b[0], f"{name} cycle {i}: the decision changed"
        assert a[1].keys() == b[1].keys()
        moved = {k for k in a[1] if a[1][k] != b[1][k]}
        assert not moved, f"{name} cycle {i}: the shadow wrote {sorted(moved)}"
        assert a[2] == b[2], f"{name} cycle {i}: a published value changed"


def test_the_sequences_really_reach_the_early_returns():
    """Not vacuous: the lock, the shed and the plan hold each return early
    (an empty engine verdict list would pass the test above for nothing)."""
    def seen(name):
        codes = []
        real = sc_mod.compute_load_intent

        def spy(device, **kw):
            out = real(device, **kw)
            codes.append(out.code)
            return out

        async def go():
            seq = _SEQUENCES[name]()
            hass, dev, sc = uc1102._boiler(seq["temp"])
            with patch.object(sc_mod, "compute_load_intent", spy):
                for setup, cycle in seq["steps"]:
                    if setup is not None:
                        setup(hass, dev, sc)
                    await _cyc(sc, **cycle)
            return dev
        with freeze_time(_NOW, real_asyncio=True):
            return asyncio.run(go()), codes
    dev, codes = seen("peak_shed")
    assert RC.LOAD_PEAK_SHED in codes
    dev, codes = seen("plan_hold")
    assert RC.LOAD_PLAN_CLOSED in codes
    dev, codes = seen("legionella_hold_then_lock")
    assert dev.locked_by_operator is False and dev._legionella_cycle_active


def test_the_lock_then_59_9_sequence_keeps_the_tank_heating():
    """The review's exact case, pinned on its own: the shadow ran on the
    locked cycle and used to leave ``_hold_stopped`` True, so 59.9 stopped a
    tank that is not stopped when the shadow is off."""
    seq = _seq_lock()
    for shadow in (True, False):
        trace = _run(lambda: seq, shadow)
        last_locked = trace[2][1]
        assert last_locked["_hold_stopped"] is False, f"shadow={shadow}"
        after = trace[3][0]
        assert all(code != RC.LOAD_STOP_CONDITION for _on, _src, code, _r in after)


# ── E. the only attributes the comparison ever writes ──────────────────────

class _Tracer:
    """Records every attribute set on the controller while it is armed."""

    def __init__(self):
        self.written = set()
        self.armed = False


def _trace_writes(dev_cls, tracer):
    orig = dev_cls.__setattr__

    def spy(self, name, value):
        if tracer.armed:
            tracer.written.add(name)
        orig(self, name, value)
    return patch.object(dev_cls, "__setattr__", spy)


_OWN = {"tank_goal_diffs", "tank_goal_last", "tank_goal_errors", "tank_goal_skipped"}


def _grid_states():
    for temp, band, entity, vac, dump, leg, hold, hstop, cl, lim in itertools.product(
            (None, 30.0, 45.0, 52.0, 56.5, 59.9, 60.6),
            (True, False), (SWITCH, "water_heater.dhw"),
            (False, True), (False, True), (False, True), (False, True), (False, True),
            (52.0, 60.0), (36.0, 60.0)):
        if hold and not leg:
            continue
        yield temp, band, entity, vac, dump, leg, hold, hstop, cl, lim


def test_the_comparison_writes_nothing_but_its_own_counters():
    """A guard over a grid: misconfigured bands, a silent sensor, away with the
    dump, a Legionella hold with and without its flag, a switch and a setpoint
    tank — every attribute set while ``compare_tank_goal`` runs is a counter."""
    tracer, written, runs = _Tracer(), set(), 0
    with _trace_writes(HotWaterController, tracer):
        for i, (temp, band, entity, vac, dump, leg, hold, hstop, top, lim) in enumerate(_grid_states()):
            if i % 3:                   # a third of the grid is plenty and fast
                continue
            dev = _tank(_Hass(), temp if temp is not None else 45.0, band=band,
                        entity_id=entity)
            if temp is None:
                dev.hass.set(SENSOR, "unavailable")
            dev.comfort_target, dev.comfort_limit = (top, lim) if band else (0.0, 0.0)
            dev.vacation, dev.vacation_dhw_surplus = vac, dump
            if leg:
                dev._legionella_cycle_active = True
                dev._legionella_hold_start = hwc.dt_util.now() if hold else None
                dev._hold_stopped = hstop
            for verdict in (RECOMPUTE_, True, False, None):
                tracer.armed = True
                dev.compare_tank_goal(verdict)
                tracer.armed = False
                runs += 1
            written |= tracer.written
    assert runs > 100
    assert written <= _OWN, sorted(written - _OWN)
    assert "tank_goal_errors" not in written    # nothing broke on the way


RECOMPUTE_ = tg.RECOMPUTE


class TestTheOneStopRule:
    def test_the_pure_rule_writes_nothing_and_the_property_stores_it(self):
        dev = _tank(_Hass(), 60.6)
        _hold(dev)
        before = dict(dev.__dict__)
        met, hold = dev._stop_condition(
            False, read=lambda: 60.6, band_state=lambda: "willing",
            target=lambda: 60.0)
        assert (met, hold) == (True, True) and dev.__dict__ == before
        assert dev.stop_condition_met is True and dev._hold_stopped is True
        assert dev._last_temperature_reading_path          # the property still records it

    def test_the_hold_flag_is_left_alone_outside_the_hold(self):
        dev = _tank(_Hass(), 45.0)
        assert dev._stop_condition(
            True, read=lambda: 45.0, band_state=lambda: "willing",
            target=lambda: 56.0) == (False, None)

    def test_the_engines_own_answer_is_used_and_an_early_return_is_skipped(self):
        dev = _tank(_Hass(), 45.0)
        dev.compare_tank_goal(None)
        assert dev.tank_goal_skipped == 1 and dev.tank_goal_diffs == {}
        dev.compare_tank_goal(True)             # the engine stopped it; the goal does not
        assert dev.tank_goal_diffs == {"must_stop": 1}
        assert dev.tank_goal_skipped == 1
