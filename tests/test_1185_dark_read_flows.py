"""#1185 — the daily flows and the solar savings keep a dark input's share.

PROD (Huawei over modbus): the inverter reads dark about 25 % of a sunny
hour. Since #1177 the daily rows book a dark input's last live read for
``SENSOR_DARK_READ_GRACE_S``, the window its own entity shows it. The flows
were still built from the reader's 0 W (#818), so the daily flows (solar to
home, to the battery, …), the solar savings built on them, the car's daily
split, the battery's charge origin, an own-tariff device's grid share and the
EV and battery session splits all lost that share (bug class 58).

The books now split by flows built from the same held watts
(``EnergyCalculator.book_flows``). Steering and the health check keep the
cycle's own flows.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.consts.core import (
    SENSOR_DARK_READ_GRACE_S,
)
from custom_components.solar_energy_management.coordinator.device_tariff import (
    DeviceCycle,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    DEVICE_TARIFF_KWH,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)
from custom_components.solar_energy_management.tests.test_1177_dark_read_integral import (  # noqa: E501
    DAY,
    STEP_S,
    _calc,
    _kwh,
    _row,
    clock,  # noqa: F401 — the frozen-noon fixture
)

GRACE = SENSOR_DARK_READ_GRACE_S
RATE = 0.30


def _turn(calc, **power):
    """One cycle the coordinator's way: the flows from the reader's watts
    (steering's), then the books."""
    calc._last_update = None
    shown = power.pop("home_shown_w", None)
    p = PowerReadings(**power)
    p.calculate_derived()
    p.home_shown_w = shown
    flows = FlowCalculator().calculate_power_flows(p)
    calc.calculate_energy(p, flows)
    return p, flows


def _savings(calc) -> float:
    return calc._daily_cost_accumulators.get(f"cost_savings_{DAY}", 0.0)


# Solar 3 kW, export 2 kW, the house 1 kW — then the inverter goes dark and
# the house is shown from its last value (#1047).
LIVE = dict(solar_power=3000.0, grid_power=2000.0)
DARK = dict(solar_power=0.0, solar_power_unavailable=True, grid_power=2000.0,
            home_shown_w=1000.0)


@pytest.mark.unit
@pytest.mark.usefixtures("clock")
class TestTheBooksSplitTheHeldWatts:
    def test_a_dark_inverter_keeps_its_savings(self):
        calc, _ = _calc()
        calc._import_rate = RATE
        _turn(calc, **LIVE)
        _turn(calc, **DARK)
        assert _savings(calc) == pytest.approx(_kwh(1000.0, 2) * RATE)

    def test_the_daily_flows_keep_its_share(self):
        calc, _ = _calc()
        fc = FlowCalculator()
        for power in (LIVE, DARK, DARK):
            _turn(calc, **power)
            fc.integrate_energy_flows(calc.book_flows, STEP_S)
        acc = fc._flow_accumulators
        assert acc["solar_to_home"] == pytest.approx(_kwh(1000.0, 3))
        assert acc["solar_to_grid"] == pytest.approx(_kwh(2000.0, 3))
        assert acc["solar_to_home"] + acc["solar_to_grid"] == pytest.approx(
            _row(calc, "solar")), "the flows add up to the solar row"

    def test_every_input_dark_on_one_link(self):
        """The PROD shape: one modbus link, so solar, grid and battery go
        dark together; raw, every input is 0 W and the cycle is idle."""
        calc, _ = _calc()
        calc._import_rate = RATE
        _turn(calc, solar_power=4000.0, battery_power=3000.0)   # house 1 kW
        _, flows = _turn(calc, solar_power_unavailable=True,
                         grid_power_unavailable=True,
                         battery_power_all_unavailable=True,
                         home_shown_w=1000.0)
        assert flows.solar_to_home == 0.0, "the case never reached the 0 W"
        assert calc.book_flows.solar_to_home == pytest.approx(1000.0)
        assert calc.book_flows.solar_to_battery == pytest.approx(3000.0)
        assert _savings(calc) == pytest.approx(_kwh(1000.0, 2) * RATE)

    def test_one_dark_unit_of_two(self):
        """(#1186) A held unit of a live total is held in the books' flows."""
        calc, _ = _calc()
        calc._import_rate = RATE
        _turn(calc, **LIVE)
        calc._last_update = None
        p = PowerReadings(solar_power=2000.0, grid_power=2000.0)
        p.calculate_derived()
        p.held_w = {"solar": 1000.0}
        p.home_shown_w = 1000.0
        calc.calculate_energy(p, FlowCalculator().calculate_power_flows(p))
        assert calc.book_flows.solar_to_home == pytest.approx(1000.0)
        assert _savings(calc) == pytest.approx(_kwh(1000.0, 2) * RATE)

    def test_past_the_grace_the_books_take_what_was_read(self):
        calc, _ = _calc()
        calc._import_rate = RATE
        _turn(calc, **LIVE)
        self.clock.tick(timedelta(seconds=GRACE))
        _turn(calc, **DARK)
        assert _savings(calc) == pytest.approx(_kwh(1000.0, 2) * RATE), "edge"
        self.clock.tick(timedelta(seconds=1))
        _turn(calc, **DARK)
        assert calc.book_flows.solar_to_home == 0.0
        assert _savings(calc) == pytest.approx(_kwh(1000.0, 2) * RATE)

    def test_nothing_held_keeps_the_cycles_own_flows(self):
        calc, _ = _calc()
        p, flows = _turn(calc, **LIVE)
        assert calc.book_flows is flows
        assert calc.book_power is p

    def test_a_shown_house_alone_keeps_the_cycles_own_flows(self):
        """(#1185 review) The #1105 battery stop shows the house held while
        every input reads live: a held house beside them left 1564 W of
        live import in no flow."""
        calc, _ = _calc()
        _turn(calc, grid_power=-50.0, battery_power=-1450.0)
        p, flows = _turn(calc, grid_power=-1614.0, battery_power=-1450.0,
                         home_shown_w=1500.0)
        assert calc.book_flows is flows and calc.book_power is p
        assert flows.grid_to_home == pytest.approx(1614.0)

    def test_the_copy_holds_no_unit_of_its_own(self):
        """(#1186) The held unit is in the copy's total; ``shown_w`` on it
        must not add the unit a second time."""
        from custom_components.solar_energy_management.coordinator.types import (
            shown_w,
        )
        calc, _ = _calc()
        _turn(calc, **LIVE)
        calc._last_update = None
        p = PowerReadings(solar_power=2000.0, grid_power=2000.0)
        p.calculate_derived()
        p.held_w = {"solar": 1000.0}
        p.home_shown_w = 1000.0
        calc.calculate_energy(p, FlowCalculator().calculate_power_flows(p))
        assert shown_w(calc.book_power, "solar_power") == pytest.approx(3000.0)
        assert p.held_w == {"solar": 1000.0}, "the read is left as it was"

    def test_steering_keeps_the_zero(self):
        calc, _ = _calc()
        _turn(calc, **LIVE)
        p, flows = _turn(calc, **DARK)
        assert p.solar_power == 0.0 and flows.solar_to_home == 0.0
        assert calc.book_power is not p and calc.book_flows is not flows
        assert calc.book_power.solar_power == pytest.approx(3000.0)
        assert calc.book_power.home_consumption_power == pytest.approx(1000.0)

    def test_the_car_day_split_keeps_its_share(self):
        """(#1046) The car's flow rows, on its own day key."""
        calc, _ = _calc()
        car = dict(ev_power=2000.0, grid_power=2000.0)
        _turn(calc, solar_power=5000.0, **car)                  # house 1 kW
        _turn(calc, solar_power_unavailable=True, home_shown_w=1000.0, **car)
        day = calc._daily_ev_day
        assert calc._daily_accumulators[f"ev_flow_solar_{day}"] == (
            pytest.approx(_kwh(2000.0, 2)))

    def test_a_live_battery_keeps_its_solar_origin(self):
        """(#770) A charge whose source reads dark was split by nothing."""
        calc, _ = _calc()
        _turn(calc, solar_power=3000.0, battery_power=2500.0)   # house 500 W
        _turn(calc, solar_power_unavailable=True, battery_power=2500.0,
              home_shown_w=500.0)
        assert _row(calc, "battery_charge_solar") == pytest.approx(
            _kwh(2500.0, 2))
        assert _row(calc, "battery_charge") == pytest.approx(_kwh(2500.0, 2))

    def test_an_own_tariff_device_takes_the_held_grid_share(self):
        """(#812) The grid's share of the house: held import over the held
        house — 2000 of 2500 W. The 0 W read gave 0; the held import over
        the raw house (500 W) gave all of it."""
        calc, _ = _calc()
        calc._import_rate = RATE
        _turn(calc, solar_power=500.0, grid_power=-2000.0)
        calc.set_device_tariff_cycle([DeviceCycle("boiler", power_w=1000.0,
                                                  price=0.10)])
        _turn(calc, solar_power=500.0, grid_power_unavailable=True,
              home_shown_w=2500.0)
        assert _row(calc, f"{DEVICE_TARIFF_KWH}boiler") == pytest.approx(
            _kwh(1000.0) * 0.8)


# ── the coordinator hands the books' flows over ────────────────────────────

def _cycle_tree():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    return ast.parse(textwrap.dedent(
        inspect.getsource(SEMCoordinator._async_update_data)))


def _uses(tree, name):
    """Where each read of ``name`` goes: the call it is an argument of (its
    method name, or ``kw=`` for a keyword), or ``=target`` for an assign."""
    parent = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and node.id == name
                and isinstance(node.ctx, ast.Load)):
            continue
        child, up = node, parent.get(id(node))
        while up is not None and not isinstance(up, (ast.Call, ast.Assign)):
            child, up = up, parent.get(id(up))
        if isinstance(up, ast.Assign):
            out.append("=" + ",".join(
                t.id for t in up.targets if isinstance(t, ast.Name)))
        elif isinstance(up, ast.Call):
            func = up.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(
                func, "id", "?")
            kw = next((k.arg for k in up.keywords if k is child), None)
            out.append(f"{fname}({kw}=)" if kw else fname)
    return out


@pytest.mark.unit
class TestTheCycleHandsTheBooksOver:
    def test_the_raw_flows_go_only_where_the_reads_are_raw(self):
        """The cycle's own flows go to the books (which build theirs), the
        health check and the night recorder (each checks them against the
        raw power) — and stand in when the books have none."""
        assert sorted(_uses(_cycle_tree(), "power_flows")) == sorted([
            "calculate_energy", "=book_flows", "run_all_checks(flows=)",
            "_record_battery_night",
        ])

    def test_the_books_flows_reach_every_integral(self):
        uses = _uses(_cycle_tree(), "book_flows")
        for target in ("integrate_energy_flows", "_update_session_tracking",
                       "_update_battery_session_tracking",
                       "_record_demand_outcomes", "SEMData(power_flows=)"):
            assert target in uses, f"{target} gets no book flows: {uses}"

    def test_the_night_audit_and_battery_session_get_the_held_watts(self):
        uses = _uses(_cycle_tree(), "book_power")
        assert "_record_demand_outcomes(book_power=)" in uses
        assert "_update_battery_session_tracking" in uses

    def test_the_walker_sees_a_use(self):
        """The pins above would pass on a walker that sees nothing."""
        tree = ast.parse("def f(a, b):\n    g(a, k=b)\n    c = a\n")
        assert sorted(_uses(tree, "a")) == ["=c", "g"]
        assert _uses(tree, "b") == ["g(k=)"]


@pytest.mark.unit
class TestTheNightAuditTakesTheHeldWatts:
    """(#755) The night's solar and export, integrated over the plan's window
    from the same held watts the rows book."""

    def test_a_dark_inverter_is_not_a_night_without_sun(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.tests.test_1191_battery_sale_self_consumption import (  # noqa: E501
            TestTheNightAudit,
        )
        me, record = TestTheNightAudit()._me()
        raw = PowerReadings(solar_power=0.0, solar_power_unavailable=True,
                            grid_power=2000.0)
        raw.calculate_derived()
        raw.ev_power_per_charger = {}
        held = PowerReadings(solar_power=3000.0, grid_power=2000.0)
        held.calculate_derived()
        flows = FlowCalculator().calculate_power_flows(held)
        t0 = datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc)
        record(me, t0, raw, flows, book_power=held)
        record(me, t0 + timedelta(hours=1), raw, flows, book_power=held)
        summary = me._demand_outcomes._summary
        assert summary.solar_kwh == pytest.approx(3.0, abs=0.01)
        assert summary.exported_kwh == pytest.approx(2.0, abs=0.01)
        assert record is SEMCoordinator._record_demand_outcomes


@pytest.mark.unit
@pytest.mark.usefixtures("clock")
class TestThroughTheRealReader:
    """The flags are the reader's own: a dark inverter, then the whole
    modbus link, through ``SensorReader.read_power``, the coordinator's home
    steps, the flows, the books and the flow rows."""

    def test_the_flow_rows_add_up_to_the_solar_row(self):
        from unittest.mock import Mock

        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        from custom_components.solar_energy_management.tests.test_1177_dark_read_integral import (  # noqa: E501
            _w_state,
        )
        values = {"sensor.pv": "4600", "sensor.grid": "50", "sensor.bat": "3900"}
        hass = Mock()
        hass.states.get = lambda eid: (
            _w_state(values[eid]) if eid in values else None)
        reader = SensorReader(hass, {
            "solar_production_sensor": "sensor.pv",
            "grid_power_sensor": "sensor.grid",
            "battery_power_sensor": "sensor.bat",
        })
        reader._energy_dashboard_config = None
        coord = SEMCoordinator.__new__(SEMCoordinator)
        mono = [1000.0]
        coord._shown_home_clock = lambda: mono[0]
        calc, _ = _calc()
        calc._import_rate = RATE
        fc = FlowCalculator()

        def cycle(**v):
            values.update(v)
            mono[0] += STEP_S
            self.clock.tick(timedelta(seconds=STEP_S))
            p = reader.read_power()
            coord._smooth_home_consumption(p)
            coord._hold_shown_home(p)
            calc._last_update = None
            calc.calculate_energy(p, fc.calculate_power_flows(p))
            fc.integrate_energy_flows(calc.book_flows, STEP_S)
            return p

        cycle()
        cycle()
        dark = cycle(**{"sensor.pv": "unavailable"})
        assert dark.solar_power_unavailable and dark.solar_power == 0.0
        for _ in range(3):                      # the whole link dark
            dark = cycle(**{"sensor.pv": "unavailable", "sensor.bat": "unavailable",
                            "sensor.grid": "unavailable"})
            assert dark.battery_power_all_unavailable and dark.grid_power_unavailable
        acc = fc._flow_accumulators
        solar = sum(acc[f] for f in ("solar_to_home", "solar_to_battery",
                                     "solar_to_grid", "solar_to_ev"))
        assert solar == pytest.approx(_row(calc, "solar"))
        assert _row(calc, "solar") == pytest.approx(_kwh(4600.0, 6))
        assert acc["solar_to_home"] == pytest.approx(_kwh(650.0, 6))
        assert _savings(calc) == pytest.approx(_kwh(650.0, 6) * RATE)


@pytest.mark.unit
class TestTheBooksSplitOnlyByTheirOwnFlows:
    """Structural: in ``calculate_energy`` the first read of ``power_flows``
    builds the books' flows; every split below reads those. A new split
    read before it would bring the 0 W back."""

    @staticmethod
    def _first_read(src):
        """The method the first read of ``power_flows`` goes to, and
        whether that statement binds ``power_flows`` again."""
        tree = ast.parse(textwrap.dedent(src))
        parent = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        first = min(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.Name) and n.id == "power_flows"
             and isinstance(n.ctx, ast.Load)),
            key=lambda n: (n.lineno, n.col_offset))
        call, stmt = parent[id(first)], first
        while not isinstance(stmt, ast.stmt):
            stmt = parent[id(stmt)]
        bound = isinstance(stmt, ast.Assign) and any(
            isinstance(n, ast.Name) and n.id == "power_flows"
            for t in stmt.targets for n in ast.walk(t))
        name = getattr(call.func, "attr", None) if isinstance(call, ast.Call) else None
        return name, bound

    def test_the_first_read_builds_the_books_flows(self):
        from custom_components.solar_energy_management.coordinator.energy_calculator import (
            EnergyCalculator,
        )
        assert self._first_read(inspect.getsource(
            EnergyCalculator.calculate_energy)) == ("_book_flows", True)

    def test_the_pin_sees_an_earlier_read(self):
        probe = ("def f(self, power, power_flows):\n"
                 "    x = self._battery_flows(power_flows)\n"
                 "    power_flows = self._book_flows(power, power_flows, {})\n")
        assert self._first_read(probe) == ("_battery_flows", False)

    def test_the_pin_sees_flows_not_bound_back(self):
        probe = ("def f(self, power, power_flows):\n"
                 "    p, f = self._book_flows(power, power_flows, {})\n")
        assert self._first_read(probe) == ("_book_flows", False)


@pytest.mark.unit
@pytest.mark.usefixtures("clock")
class TestTheBatterySessionStaysInsideItsTotal:
    """(#1185 review) The session took its total from the raw read and its
    split from the books: with one battery of two dark (#1186) the solar
    part grew three times faster than the total."""

    def _session(self):
        from types import MethodType, SimpleNamespace

        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.types import (
            BatterySessionData,
        )
        me = SimpleNamespace(
            _battery_session=BatterySessionData(),
            _battery_session_idle_count=0, _battery_session_opposite_count=0,
            update_interval=timedelta(seconds=STEP_S),
            _energy_calculator=SimpleNamespace(_import_rate=RATE))
        track = MethodType(SEMCoordinator._update_battery_session_tracking, me)
        return me, track

    def _books(self, calc, **power):
        units = power.pop("held_w", None)
        shown = power.pop("home_shown_w", None)
        calc._last_update = None
        p = PowerReadings(**power)
        p.calculate_derived()
        if units:
            p.held_w = units
        p.home_shown_w = shown
        calc.calculate_energy(p, FlowCalculator().calculate_power_flows(p))
        return calc.book_power, calc.book_flows

    def test_one_dark_battery_of_two(self):
        calc, _ = _calc()
        me, track = self._session()
        track(*self._books(calc, solar_power=4000.0, battery_power=3000.0))
        for _ in range(3):
            track(*self._books(calc, solar_power=4000.0, battery_power=1000.0,
                               held_w={"battery": 2000.0}, home_shown_w=1000.0))
        s = me._battery_session
        assert s.energy_kwh == pytest.approx(_kwh(3000.0, 4))
        assert s.solar_energy_kwh == pytest.approx(s.energy_kwh)

    def test_a_dark_battery_is_no_idle_cycle(self):
        """Inside the grace the session books the held charge, as the
        daily row does; past it the battery reads 0 W, as before."""
        calc, _ = _calc()
        me, track = self._session()
        track(*self._books(calc, solar_power=4000.0, battery_power=3000.0))
        track(*self._books(calc, solar_power=4000.0, battery_power=0.0,
                           battery_power_all_unavailable=True,
                           home_shown_w=1000.0))
        assert me._battery_session.energy_kwh == pytest.approx(_kwh(3000.0, 2))
        assert me._battery_session_idle_count == 0
        self.clock.tick(timedelta(seconds=GRACE + 1))
        track(*self._books(calc, solar_power=4000.0, battery_power=0.0,
                           battery_power_all_unavailable=True,
                           home_shown_w=1000.0))
        assert me._battery_session.energy_kwh == pytest.approx(_kwh(3000.0, 2))
        assert me._battery_session_idle_count == 1
