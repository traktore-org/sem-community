"""#1186 — one dark unit of a total is not 0 W.

With two inverters, two batteries, or a grid meter split into import and
export sensors, SEM kept the last reading only when EVERY unit dropped out at
once: the ``*_unavailable`` flags (#818) blank the total, its entity holds the
last value, the daily rows hold it (#1177) and so does home (#1047). When just
one unit dropped out, its part was 0 W in the total SEM shows and in the daily
rows — while that unit's own entity (a battery, a string) held its value
(#1170, #1196), so for the grace the two did not add up.

Each unit now keeps its own last live read for ``SENSOR_DARK_READ_GRACE_S``,
in the reader (``SensorReader._hold_dark_units``). ``PowerReadings.held_w``
says what the held units add, in SEM's sign; the published total, the daily
rows and the shown home take it; steering keeps the reader's 0 W (#988,
#1047). #1203 — a dark string's daily energy — is the same rule per string.

Links, each driven for real: the reader on every shape of a total read from
several sensors (both read paths); the grace, renewal, never-read and live-0
edges; the sign each held unit takes after a flip; ``to_dict``; the
``EnergyCalculator`` rows; the shown-home hold; the string integral; and
structural pins over the reader.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.consts.core import (
    SENSOR_DARK_READ_GRACE_S,
)
from custom_components.solar_energy_management.coordinator import (
    sensor_reader as sr,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    SHOWN_FIELDS,
    PowerReadings,
    SEMData,
    shown_w,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (  # noqa: E501
    _reader,
    _state,
)
from custom_components.solar_energy_management.tests.test_1177_dark_read_integral import (  # noqa: E501
    STEP_S,
    _calc,
    _cycle,
    _kwh,
    _row,
    clock,  # noqa: F401 — the frozen-noon fixture
)

GRACE = SENSOR_DARK_READ_GRACE_S


def _built(states, *, ed=None, config=None):
    """The real reader; ``ed`` None reads the config path. Its clock is
    ``clock[0]`` (monotonic seconds)."""
    r = _reader(states, dict(config or {}))
    r.hass.states.async_all = MagicMock(return_value=[])
    r._sign_vote_warmup = 0
    if ed is not None:
        r.set_energy_dashboard_config(ed)
    else:
        r._energy_dashboard_config = None
    clock = [1000.0]
    r._now_monotonic = lambda: clock[0]
    return r, clock


def _read(r, clock, states, step=STEP_S, **changes):
    for eid, value in changes.items():
        states[eid] = _state(value, "W")
    clock[0] += step
    return r.read_power()


def _published(p) -> dict:
    data = SEMData()
    data.power = p
    return data.to_dict()


# Every shape of a total read from several sensors: (id, how it is wired,
# live states, the unit that goes dark, field, steering when dark, shown).
SHAPES = [
    ("two-inverters",
     dict(ed=EnergyDashboardConfig(
         solar_power="sensor.inv_a",
         solar_power_list=["sensor.inv_a", "sensor.inv_b"], has_solar=True)),
     {"sensor.inv_a": 2000, "sensor.inv_b": 1500}, "sensor.inv_b",
     "solar_power", 2000.0, 3500.0),
    ("two-batteries",
     dict(ed=EnergyDashboardConfig(
         battery_power="sensor.b1",
         battery_power_list=["sensor.b1", "sensor.b2"], has_battery=True)),
     {"sensor.b1": 1000, "sensor.b2": -400}, "sensor.b2",
     "battery_power", 1000.0, 600.0),
    ("fleet-pair-unit",
     dict(ed=EnergyDashboardConfig(
         battery_power="sensor.b1", battery_power_list=["sensor.b1"],
         battery_power_pairs=[("sensor.p_from", "sensor.p_to")],
         has_battery=True)),
     {"sensor.b1": 500, "sensor.p_to": 0, "sensor.p_from": 800},
     "sensor.p_from", "battery_power", 500.0, -300.0),
    ("one-battery-two-sensors",
     dict(ed=EnergyDashboardConfig(
         battery_power_from="sensor.p_from", battery_power_to="sensor.p_to",
         has_battery=True)),
     {"sensor.p_to": 0, "sensor.p_from": 900}, "sensor.p_from",
     "battery_power", 0.0, -900.0),
    ("declared-grid-pair",
     dict(ed=EnergyDashboardConfig(
         grid_power_from="sensor.imp", grid_power_to="sensor.exp",
         has_grid=True)),
     {"sensor.imp": 1500, "sensor.exp": 0}, "sensor.imp",
     "grid_power", 0.0, -1500.0),
    ("manual-grid-pair-dashboard",
     dict(ed=EnergyDashboardConfig(has_grid=True),
          config={"grid_import_power_entity": "sensor.imp",
                  "grid_export_power_entity": "sensor.exp"}),
     {"sensor.imp": 0, "sensor.exp": 2200}, "sensor.exp",
     "grid_power", 0.0, 2200.0),
    ("manual-grid-pair-no-dashboard",
     dict(config={"grid_import_power_entity": "sensor.imp",
                  "grid_export_power_entity": "sensor.exp"}),
     {"sensor.imp": 700, "sensor.exp": 0}, "sensor.imp",
     "grid_power", 0.0, -700.0),
    ("two-grid-meters",
     dict(ed=EnergyDashboardConfig(
         grid_import_power="sensor.g1",
         grid_power_list=["sensor.g1", "sensor.g2"], has_grid=True)),
     {"sensor.g1": 300, "sensor.g2": 700}, "sensor.g2",
     "grid_power", 300.0, 1000.0),
]
SHAPE_IDS = [s[0] for s in SHAPES]


def _shape(shape):
    _, wiring, live, dark, field, steering, shown = shape
    states = {eid: _state(v, "W") for eid, v in live.items()}
    r, clock = _built(states, **wiring)
    return r, clock, states, dark, field, steering, shown


# ── 1. The reader: each unit is held on its own ────────────────────────────

class TestEveryShapeHoldsItsDarkUnit:
    @pytest.mark.parametrize("shape", SHAPES, ids=SHAPE_IDS)
    def test_the_shown_total_keeps_the_dark_units_last_read(self, shape):
        r, clock, states, dark, field, steering, shown = _shape(shape)
        live = r.read_power()
        assert shown_w(live, field) == pytest.approx(shown), "live baseline"
        assert live.held_w == {}
        p = _read(r, clock, states, **{dark: "unavailable"})
        # steering keeps the reader's 0 W for the dark unit
        assert getattr(p, field) == pytest.approx(steering)
        assert p.inputs_degraded is True
        # …and the figure SEM shows keeps the unit's last read
        assert shown_w(p, field) == pytest.approx(shown)

    @pytest.mark.parametrize("shape", SHAPES, ids=SHAPE_IDS)
    def test_past_the_grace_the_unit_is_0_w_again(self, shape):
        r, clock, states, dark, field, steering, _ = _shape(shape)
        r.read_power()
        _read(r, clock, states, **{dark: "unavailable"})
        p = _read(r, clock, states, step=GRACE - STEP_S)      # age == GRACE
        assert p.held_w, "the edge is <=, as the entity's"
        p = _read(r, clock, states, step=1)
        assert p.held_w == {}, "a dark cycle never renews the read"
        assert shown_w(p, field) == pytest.approx(steering)

    @pytest.mark.parametrize("shape", SHAPES, ids=SHAPE_IDS)
    def test_a_unit_never_read_holds_nothing(self, shape):
        _, wiring, live, dark, field, steering, _ = shape
        states = {eid: _state(v, "W") for eid, v in live.items()}
        states[dark] = _state("unavailable", "W")
        r, _clock = _built(states, **wiring)
        p = r.read_power()
        assert p.held_w == {}
        assert shown_w(p, field) == pytest.approx(steering)

    @pytest.mark.parametrize("shape", SHAPES, ids=SHAPE_IDS)
    def test_every_unit_dark_is_left_to_the_flag(self, shape):
        r, clock, states, _, field, _, _ = _shape(shape)
        r.read_power()
        p = _read(r, clock, states, **{e: "unavailable" for e in list(states)})
        assert p.held_w == {}, "the *_unavailable hold owns it (#1177)"

    def test_a_live_0_w_is_a_reading_and_is_held_as_0(self):
        states = {"sensor.inv_a": _state(2000, "W"),
                  "sensor.inv_b": _state(0, "W")}
        r, clock = _built(states, ed=SHAPES[0][1]["ed"])
        r.read_power()
        p = _read(r, clock, states, **{"sensor.inv_b": "unavailable"})
        assert shown_w(p, "solar_power") == pytest.approx(2000.0)

    def test_a_state_that_is_no_number_is_held_too(self):
        r, clock, states, dark, field, _, shown = _shape(SHAPES[0])
        r.read_power()
        p = _read(r, clock, states, **{dark: "none"})
        assert shown_w(p, field) == pytest.approx(shown)

    def test_the_unit_returns_and_the_hold_ends(self):
        r, clock, states, dark, field, _, _ = _shape(SHAPES[0])
        r.read_power()
        _read(r, clock, states, **{dark: "unavailable"})
        p = _read(r, clock, states, **{dark: 900})
        assert p.held_w == {}
        assert shown_w(p, field) == pytest.approx(2900.0)

    def test_a_half_dark_pair_in_a_fleet_is_not_counted_twice(self):
        """The unit's live half is already in the sum: the hold puts back
        its last net in place of what the sum took, not on top of it."""
        states = {"sensor.b1": _state(500, "W"),
                  "sensor.p_to": _state(1200, "W"),
                  "sensor.p_from": _state(0, "W")}
        r, clock = _built(states, ed=SHAPES[2][1]["ed"])
        assert shown_w(r.read_power(), "battery_power") == pytest.approx(1700.0)
        p = _read(r, clock, states, **{"sensor.p_from": "unavailable"})
        assert p.battery_power == pytest.approx(1700.0), "live half in the sum"
        assert shown_w(p, "battery_power") == pytest.approx(1700.0)

    def test_an_unproven_grid_guess_holds_nothing(self):
        """(#947) A name-only pick steers nothing while unproven; its sides
        are no units of a grid SEM did not read."""
        states = {"sensor.imp": _state(1500, "W"),
                  "sensor.exp": _state(0, "W")}
        r, clock = _built(states, ed=EnergyDashboardConfig(
            grid_import_energy="sensor.imp_kwh", has_grid=True))
        r._split_grid_discovery.update(
            {"import": "sensor.imp", "export": "sensor.exp",
             "confidence": "any-device"})
        r._split_grid_scan_due = lambda disc: False
        r.read_power()
        p = _read(r, clock, states, **{"sensor.imp": "unavailable"})
        assert "grid" not in p.held_w

    def test_a_proven_discovered_pair_holds_its_dark_side(self):
        states = {"sensor.imp": _state(1500, "W"),
                  "sensor.exp": _state(0, "W")}
        r, clock = _built(states, ed=EnergyDashboardConfig(
            grid_import_energy="sensor.imp_kwh", has_grid=True))
        r._split_grid_discovery.update(
            {"import": "sensor.imp", "export": "sensor.exp",
             "confidence": "same-device"})
        assert r.read_power().grid_power == pytest.approx(-1500.0)
        p = _read(r, clock, states, **{"sensor.imp": "unavailable"})
        assert p.grid_power == 0.0
        assert shown_w(p, "grid_power") == pytest.approx(-1500.0)


class TestTheHeldUnitTakesTheFinalSign:
    def test_a_grid_turned_over_turns_its_held_side_with_it(self):
        states = {"sensor.g1": _state(300, "W"), "sensor.g2": _state(700, "W")}
        r, clock = _built(states, ed=SHAPES[7][1]["ed"],
                          config={"grid_sign_invert": True})
        assert r.read_power().grid_power == pytest.approx(-1000.0)
        p = _read(r, clock, states, **{"sensor.g2": "unavailable"})
        assert p.grid_power == pytest.approx(-300.0)
        assert shown_w(p, "grid_power") == pytest.approx(-1000.0)
        assert shown_w(p, "grid_import_power") == pytest.approx(1000.0)

    def test_a_battery_flipped_by_the_user_holds_its_flipped_read(self):
        states = {"sensor.b1": _state(1000, "W"), "sensor.b2": _state(-400, "W")}
        r, clock = _built(states, ed=SHAPES[1][1]["ed"],
                          config={"battery_sign_user_flip": True})
        assert r.read_power().battery_power == pytest.approx(-600.0)
        p = _read(r, clock, states, **{"sensor.b2": "unavailable"})
        assert p.battery_power == pytest.approx(-1000.0)
        assert shown_w(p, "battery_power") == pytest.approx(-600.0)

    def test_a_one_battery_pair_flipped_by_the_user(self):
        states = {"sensor.p_to": _state(0, "W"), "sensor.p_from": _state(900, "W")}
        r, clock = _built(states, ed=SHAPES[3][1]["ed"],
                          config={"battery_sign_user_flip": True})
        assert r.read_power().battery_power == pytest.approx(900.0)
        p = _read(r, clock, states, **{"sensor.p_from": "unavailable"})
        assert shown_w(p, "battery_power") == pytest.approx(900.0)


class TestAGateThatRefutesTheTotalUnreadsEveryUnit:
    """The #988 solar gate and the #902 battery gate refute a TOTAL. Taking
    one read away left the other unit's read, so a home with two inverters
    or a two-sensor battery published the refuted 0 W as a reading."""

    def _solar(self, inverters):
        states = {e: _state(2000, "W") for e in inverters}
        states["sensor.bat"] = _state(0, "W")
        r, clock = _built(states, ed=EnergyDashboardConfig(
            solar_power=inverters[0],
            solar_power_list=inverters if len(inverters) > 1 else [],
            battery_power="sensor.bat", has_solar=True, has_battery=True))
        r.read_power()
        changes = {e: 0 for e in inverters}
        changes["sensor.bat"] = 1267             # charging from nothing
        return _read(r, clock, states, **changes)

    @pytest.mark.parametrize("inverters", [
        ["sensor.inv_a"], ["sensor.inv_a", "sensor.inv_b"]], ids=["one", "two"])
    def test_a_refuted_solar_zero_is_no_reading(self, inverters):
        p = self._solar(inverters)
        assert "solar" in p.dark_inputs
        assert p.solar_power_unavailable is True
        assert _published(p)["solar_power"] is None

    def test_an_impossible_two_sensor_battery_is_no_reading(self):
        states = {"sensor.p_to": _state(0, "W"), "sensor.p_from": _state(0, "W")}
        r, clock = _built(states, ed=SHAPES[3][1]["ed"])
        r.read_power()
        p = _read(r, clock, states, **{"sensor.p_from": 22_806_824})
        assert p.battery_power_all_unavailable is True
        assert _published(p)["battery_power"] is None

    def test_a_fleet_keeps_the_unit_it_still_reads(self):
        """The twin: one impossible unit of two leaves a battery read."""
        states = {"sensor.b1": _state(1000, "W"), "sensor.b2": _state(-400, "W")}
        r, clock = _built(states, ed=SHAPES[1][1]["ed"])
        r.read_power()
        p = _read(r, clock, states, **{"sensor.b2": 22_806_824})
        assert p.battery_power_all_unavailable is False
        assert p.battery_power == pytest.approx(1000.0)
        assert shown_w(p, "battery_power") == pytest.approx(600.0)


# ── 2. What SEM publishes ──────────────────────────────────────────────────

class TestThePublishedTotal:
    def test_each_power_key_shows_the_held_figure(self):
        p = PowerReadings(solar_power=2000.0, grid_power=0.0,
                          battery_power=1000.0)
        p.calculate_derived()
        p.held_w = {"solar": 1500.0, "grid": -1500.0, "battery": -400.0}
        out = _published(p)
        assert out["solar_power"] == 3500
        assert out["grid_power"] == -1500
        assert out["grid_active_power"] == 1500
        assert out["grid_import_power"] == 1500
        assert out["grid_export_power"] == 0
        assert out["battery_power"] == 600
        assert out["battery_charge_power"] == 600
        assert out["battery_discharge_power"] == 0

    def test_every_shown_field_is_a_published_key(self):
        """A new power key with a held part would need ``shown_w``."""
        out = _published(PowerReadings())
        assert set(SHOWN_FIELDS) <= set(out)

    def test_nothing_held_publishes_as_before(self):
        p = PowerReadings(solar_power=2000.0, grid_power=-300.0,
                          battery_power=-500.0)
        p.calculate_derived()
        out = _published(p)
        assert (out["solar_power"], out["grid_power"], out["battery_power"],
                out["grid_import_power"], out["battery_discharge_power"]) == (
            2000, -300, -500, 300, 500)

    def test_every_read_dark_still_publishes_none(self):
        p = PowerReadings(solar_power_unavailable=True)
        p.held_w = {"solar": 1500.0}       # never set together; None wins
        assert _published(p)["solar_power"] is None

    def test_through_the_real_reader(self):
        r, clock, states, dark, _, _, _ = _shape(SHAPES[0])
        r.read_power()
        out = _published(_read(r, clock, states, **{dark: "unavailable"}))
        assert out["solar_power"] == 3500, "not the 2000 W of one inverter"


# ── 3. The daily rows ──────────────────────────────────────────────────────

@pytest.mark.usefixtures("clock")
class TestTheDailyRowsBookTheShownFigure:
    def test_a_held_inverter_is_booked(self):
        calc, _ = _calc()
        _cycle(calc, solar_power=3500.0)
        _cycle(calc, solar_power=2000.0, held_w={"solar": 1500.0})
        assert _row(calc, "solar") == pytest.approx(_kwh(3500.0, 2))
        assert "solar" in calc._integral_held

    def test_a_held_import_side_is_booked(self):
        calc, _ = _calc()
        _cycle(calc, grid_power=-1500.0)
        _cycle(calc, grid_power=0.0, held_w={"grid": -1500.0})
        assert _row(calc, "grid_import") == pytest.approx(_kwh(1500.0, 2))

    def test_a_held_battery_unit_is_booked_with_its_live_shares(self):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerFlows,
        )
        calc, _ = _calc()
        live = PowerFlows(solar_to_battery=600.0)
        r = PowerReadings(battery_power=600.0)
        r.calculate_derived()
        calc._last_update = None
        calc.calculate_energy(r, live)
        dark = PowerReadings(battery_power=1000.0)
        dark.calculate_derived()
        dark.held_w = {"battery": -400.0}
        calc._last_update = None
        calc.calculate_energy(dark, PowerFlows(grid_to_battery=1000.0))
        assert _row(calc, "battery_charge") == pytest.approx(_kwh(600.0, 2))
        assert calc._battery_flows(None) is calc._battery_live_flows
        assert calc._battery_live_flows.solar_to_battery == 600.0

    def test_the_held_read_is_what_every_unit_dark_then_holds(self):
        """A partly held cycle is the input's read, as the entity's last
        value is: every unit dark next books that figure."""
        calc, _ = _calc()
        _cycle(calc, solar_power=2000.0, held_w={"solar": 1500.0})
        _cycle(calc, solar_power=0.0, solar_power_unavailable=True)
        assert _row(calc, "solar") == pytest.approx(_kwh(3500.0, 2))

    def test_the_real_reader_coordinator_and_rows(self):
        """Two inverters through the real reader, the shown-home hold and
        the calculator: solar keeps inverter B, home stays the house."""
        from custom_components.solar_energy_management.coordinator import (
            SEMCoordinator,
        )
        states = {"sensor.inv_a": _state(2000, "W"),
                  "sensor.inv_b": _state(1500, "W"),
                  "sensor.grid": _state(2900, "W")}
        r, mono = _built(states, ed=EnergyDashboardConfig(
            solar_power="sensor.inv_a",
            solar_power_list=["sensor.inv_a", "sensor.inv_b"],
            grid_import_power="sensor.grid", has_solar=True, has_grid=True))
        r._grid_sign_detected = True          # SEM's sign: + is export
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord._shown_home_clock = lambda: mono[0]
        calc, _ = _calc()

        def cycle(**v):
            p = _read(r, mono, states, **v)
            self.clock.tick(timedelta(seconds=STEP_S))
            coord._smooth_home_consumption(p)
            coord._hold_shown_home(p)
            calc._last_update = None
            calc.calculate_energy(p)
            return p

        first = cycle()
        assert first.home_consumption_power == pytest.approx(600.0)
        for n in range(2, 6):
            p = cycle(**{"sensor.inv_b": "unavailable"})
            assert p.solar_power == pytest.approx(2000.0), "steering: 0 W"
            assert p.home_shown_w == pytest.approx(600.0), "the house"
            assert _row(calc, "solar") == pytest.approx(_kwh(3500.0, n))
            assert _row(calc, "home") == pytest.approx(_kwh(600.0, n), abs=1e-6)


# ── 4. The shown home ──────────────────────────────────────────────────────

class TestTheShownHomeHoldsWhileAUnitIs:
    def _coord(self, clock):
        from custom_components.solar_energy_management.coordinator import (
            SEMCoordinator,
        )
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord._shown_home_clock = lambda: clock[0]
        return coord

    def test_held_unit_holds_the_house_then_lets_go(self):
        clock = [1000.0]
        coord = self._coord(clock)

        def cycle(solar, held=None):
            p = PowerReadings(solar_power=solar, grid_power=-500.0)
            p.calculate_derived()
            if held:
                p.held_w = held
            clock[0] += STEP_S
            coord._hold_shown_home(p)
            return p

        cycle(3500.0)
        cycle(3500.0)
        p = cycle(2000.0, {"solar": 1500.0})
        assert p.home_consumption_power == pytest.approx(2500.0), "raw"
        assert p.home_shown_w == pytest.approx(4000.0), "the house"
        p = cycle(2000.0)                  # the reader let the unit go
        assert p.home_shown_w is None


# ── 5. A dark string's daily energy (#1203) ────────────────────────────────

class TestADarkStringBooksItsLastRead:
    def _strings(self):
        states = {"sensor.pv1": _state(1200, "W"), "sensor.pv2": _state(800, "W"),
                  "sensor.inv": _state(2000, "W")}
        r, clock = _built(states, config={"solar_production_sensor": "sensor.inv"})
        r.set_pv_strings({"pv1_power": "sensor.pv1", "pv2_power": "sensor.pv2"})
        return r, clock, states

    def _integrate(self, fc, p):
        return fc.integrate_energy_flows(fc.calculate_power_flows(p), STEP_S)

    def test_the_string_row_keeps_its_last_read_for_the_grace(self):
        r, clock, states = self._strings()
        fc = FlowCalculator()
        self._integrate(fc, r.read_power())
        p = _read(r, clock, states, **{"sensor.pv2": "unavailable"})
        assert p.solar_power_per_string["pv2"] == 0.0, "the sum keeps 0 W"
        assert p.solar_power_per_string_held == {"pv2": 800.0}
        assert _published(p)["pv_string_pv2_power"] is None, "#1196 kept"
        flows = self._integrate(fc, p)
        assert flows.per_string["pv2"].energy_kwh == pytest.approx(
            round(_kwh(800.0, 2), 3))

    def test_past_the_grace_the_string_books_0_w(self):
        r, clock, states = self._strings()
        r.read_power()
        _read(r, clock, states, **{"sensor.pv2": "unavailable"})
        p = _read(r, clock, states, step=GRACE)
        assert p.solar_power_per_string_held == {}

    def test_a_string_never_read_holds_nothing(self):
        r, clock, states = self._strings()
        states["sensor.pv2"] = _state("unavailable", "W")
        assert r.read_power().solar_power_per_string_held == {}

    def test_half_a_dark_v_i_pair_holds_its_last_product(self):
        states = {"sensor.v1": _state(400, "V"), "sensor.i1": _state(3, "A"),
                  "sensor.v2": _state(350, "V"), "sensor.i2": _state(2, "A"),
                  "sensor.inv": _state(1900, "W")}
        r, clock = _built(states, config={"solar_production_sensor": "sensor.inv"})
        r.set_pv_strings({}, {"pv1": ("sensor.v1", "sensor.i1"),
                              "pv2": ("sensor.v2", "sensor.i2")})
        r.read_power()
        states["sensor.i2"] = _state("unavailable", "A")
        clock[0] += STEP_S
        p = r.read_power()
        assert p.solar_power_per_string["pv2"] == 0.0
        assert p.solar_power_per_string_held == {"pv2": 700.0}

    def test_the_string_returns_and_its_hold_ends(self):
        r, clock, states = self._strings()
        r.read_power()
        _read(r, clock, states, **{"sensor.pv2": "unavailable"})
        p = _read(r, clock, states, **{"sensor.pv2": 300})
        assert p.solar_power_per_string == {"pv1": 1200.0, "pv2": 300.0}
        assert p.solar_power_per_string_held == {}


@pytest.mark.usefixtures("clock")
class TestStringsThatAreTheSolarSourcesAddUp:
    """(#1203) Two inverters on the dashboard ARE the strings (#378): the
    string rows and the solar row hold the same dark unit for the same
    grace, so they still add up — the reason #1203 waited for #1186."""

    def test_the_string_rows_add_up_to_the_solar_row(self):
        states = {"sensor.inv_a": _state(2000, "W"),
                  "sensor.inv_b": _state(1500, "W")}
        r, mono = _built(states, ed=EnergyDashboardConfig(
            solar_power="sensor.inv_a",
            solar_power_list=["sensor.inv_a", "sensor.inv_b"], has_solar=True))
        r.set_pv_strings({"pv1_power": "sensor.inv_a",
                          "pv2_power": "sensor.inv_b"})
        fc = FlowCalculator()
        calc, _ = _calc()
        booked = [0.0]

        def cycle(watts, step=STEP_S, **changes):
            p = _read(r, mono, states, step=step, **changes)
            self.clock.tick(timedelta(seconds=step))
            calc._last_update = None
            flows = fc.calculate_power_flows(p)
            calc.calculate_energy(p, flows)
            e = fc.integrate_energy_flows(flows, STEP_S)
            booked[0] += _kwh(watts)
            strings = sum(s.energy_kwh for s in e.per_string.values())
            assert _row(calc, "solar") == pytest.approx(booked[0])
            assert strings == pytest.approx(booked[0], abs=1e-3)
            return p

        cycle(3500.0)
        for _ in range(3):                      # inverter B dark, held
            p = cycle(3500.0, **{"sensor.inv_b": "unavailable"})
            assert p.solar_power == pytest.approx(2000.0), "steering: 0 W"
        cycle(2000.0, step=GRACE)               # past B's grace: 0 W again
        cycle(3500.0, **{"sensor.inv_b": 1500})
        for _ in range(3):                      # every unit dark, held
            p = cycle(3500.0, **{"sensor.inv_a": "unavailable",
                                 "sensor.inv_b": "unavailable"})
            assert p.solar_power_unavailable is True
        cycle(0.0, step=GRACE)                  # past the grace: 0 W


# ── 6. Structural pins ─────────────────────────────────────────────────────

def _tree(obj):
    return ast.parse(textwrap.dedent(inspect.getsource(obj)))


def _negations(tree):
    """``x.grid_power = -…`` / ``x.battery_power = -…`` outside the helper."""
    return [
        node.targets[0].attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Attribute)
        and node.targets[0].attr in ("grid_power", "battery_power")
        and isinstance(node.value, ast.UnaryOp)
        and isinstance(node.value.op, ast.USub)
    ]


def _side_read(node) -> bool:
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_read_sensor"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in ("grid_import", "grid_export"))


def _unheld_side_reads(tree):
    """Each ``_read_sensor(x, "grid_import" | "grid_export")`` that is not
    a unit: neither inside a ``_unit(…)`` call nor read into a name that a
    ``_unit(…)`` call takes."""
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        held, unit_names = set(), set()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_unit"):
                for sub in ast.walk(node):
                    held.add(id(sub))
                    if isinstance(sub, ast.Name):
                        unit_names.add(sub.id)
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and all(
                    isinstance(t, ast.Name) and t.id in unit_names
                    for t in node.targets):
                held.update(id(sub) for sub in ast.walk(node.value))
        out += [f"{fn.name}:{node.lineno}" for node in ast.walk(fn)
                if _side_read(node) and id(node) not in held]
    return out


class TestTheReaderHasNoUnheldUnit:
    def test_every_total_is_turned_over_by_the_helper(self):
        assert _negations(_tree(sr.SensorReader)) == [], (
            "turn a total over with _negate_total, so its held units turn too")

    def test_the_negation_walker_sees_one(self):
        probe = ast.parse("def f(readings):\n    readings.grid_power = -readings.grid_power\n")
        assert _negations(probe) == ["grid_power"]

    def test_every_grid_side_read_is_a_unit(self):
        """A grid side is half a meter: it is always a unit of the grid."""
        assert _unheld_side_reads(_tree(sr.SensorReader)) == []

    def test_the_side_walker_sees_a_bare_read(self):
        probe = ast.parse(textwrap.dedent('''
            def f(self):
                a = self._read_sensor(x, "grid_import")
                b = self._unit("grid", x, self._read_sensor(x, "grid_export"))
                raw = self._read_sensor(y, "grid_export")
                self._unit("grid", y, raw)
        '''))
        assert _unheld_side_reads(probe) == ["f:3"]

    def test_the_unit_inputs_are_the_flagged_inputs(self):
        assert set(sr._UNIT_INPUT.values()) == {"solar", "grid", "battery"}
        assert set(sr._UNIT_INPUT) == set(sr._DEGRADABLE_POWER_INPUTS)
        assert set(SHOWN_FIELDS.values()) == {"solar", "grid", "battery"}


# ── 7. Review edges (#1203) ────────────────────────────────────────────────

class TestNoFalseLastRead:
    def test_a_value_the_battery_gate_threw_out_is_never_held(self):
        """#902 blanks an impossible side; when that side then goes dark
        its last read is the one before, not 22.8 MW."""
        r, clock, states, *_ = _shape(SHAPES[3])
        r.read_power()
        _read(r, clock, states, **{"sensor.p_from": 22_806_824})
        p = _read(r, clock, states, **{"sensor.p_from": "unavailable"})
        assert shown_w(p, "battery_power") == pytest.approx(-900.0)
        assert _published(p)["battery_discharge_power"] == 900

    def test_a_zero_the_solar_gate_threw_out_is_never_held(self):
        """#988 refutes a 0 W total; inverter B's last read stays 1500 W."""
        states = {"sensor.inv_a": _state(2000, "W"),
                  "sensor.inv_b": _state(1500, "W"),
                  "sensor.bat": _state(0, "W")}
        r, clock = _built(states, ed=EnergyDashboardConfig(
            solar_power="sensor.inv_a",
            solar_power_list=["sensor.inv_a", "sensor.inv_b"],
            battery_power="sensor.bat", has_solar=True, has_battery=True))
        r.read_power()
        refuted = _read(r, clock, states, **{"sensor.inv_a": 0,
                                             "sensor.inv_b": 0,
                                             "sensor.bat": 1267})
        assert refuted.solar_power_unavailable is True
        p = _read(r, clock, states, **{"sensor.inv_a": 2000,
                                       "sensor.inv_b": "unavailable",
                                       "sensor.bat": 0})
        assert p.held_w == {"solar": 1500.0}

    @pytest.mark.parametrize("word", ["nan", "inf"])
    def test_a_state_that_is_no_finite_number_is_no_last_read(self, word):
        r, clock, states, dark, *_ = _shape(SHAPES[0])
        r.read_power()
        _read(r, clock, states, **{dark: word})
        p = _read(r, clock, states, **{dark: "unavailable"})
        assert p.held_w == {"solar": 1500.0}, "the read before it"

    def test_a_dark_unit_that_read_0_w_holds_nothing(self):
        """An idle battery of two drops out: nothing to put back, so the
        input is not held and the shown home does not freeze."""
        states = {"sensor.b1": _state(1000, "W"), "sensor.b2": _state(0, "W")}
        r, clock = _built(states, ed=SHAPES[1][1]["ed"])
        r.read_power()
        p = _read(r, clock, states, **{"sensor.b2": "unavailable"})
        assert p.held_w == {}
        assert shown_w(p, "battery_power") == pytest.approx(1000.0)


@pytest.mark.usefixtures("clock")
class TestAHeldBatteryKeepsItsChargeShare:
    def test_the_dark_unit_keeps_its_share_of_the_charge(self):
        """The charge booked holds battery 2; its share of the split comes
        from the last live read, not from the live battery alone."""
        from custom_components.solar_energy_management.coordinator.charger_types import (  # noqa: E501
            BatteryPower,
        )
        from custom_components.solar_energy_management.coordinator.types import (
            PowerFlows,
        )
        calc, _ = _calc()

        def cycle(b2, held=None):
            p = PowerReadings(battery_power=500.0 + (b2 or 0.0),
                              battery_soc_unavailable=True)
            p.batteries = {
                "b1": BatteryPower("b1", power_w=500.0, power_read=True),
                "b2": BatteryPower("b2", power_w=b2 or 0.0,
                                   power_read=b2 is not None)}
            p.calculate_derived()
            if held:
                p.held_w = held
            calc._last_update = None
            calc.calculate_energy(p, PowerFlows(solar_to_battery=p.battery_power))

        cycle(1100.0)
        cycle(None, {"battery": 1100.0})
        pools = calc._battery_provenance._pools
        assert pools["b2"].solar_kwh == pytest.approx(_kwh(1100.0, 2))
        assert pools["b1"].solar_kwh == pytest.approx(_kwh(500.0, 2))
