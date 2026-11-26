"""#1417 — a cascade meter (Messkonzept 12) with its own tariff for the heat
pump AND the car chargers.

What exists (#812): a LOAD may name its own rate, price entity and meter.
What #1417 adds, generalising that one feature rather than adding a second:

* a charger carries the same three fields (its own config row), and the
  plan, the live cheap-hour gate and the cost read them as for a load;
* a meter named by more than one device is read ONCE and its step split by
  what each draws; what none drew stays on the meter, never the house's;
* the house's grid kWh at the house rate = import − everything booked to
  own tariffs (never below 0).

Nothing configured = nothing changes.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.device_tariff import (
    DeviceTariffs, PlanTariff, apply_tariff, tariff_of,
)

from .test_812_device_tariff import T_NOON

METER = "sensor.cascade_meter"


def _dev(did, watts, *, rate=0.20, meter=METER, rated=11000.0):
    d = SimpleNamespace(device_id=did, name=did, rated_power=rated,
                        tariff_rate=0.0, tariff_entity="", tariff_meter="",
                        _tariff_level=None, tariff_inputs=None)
    d.get_current_consumption = lambda: watts
    apply_tariff(d, {"tariff_rate": rate, "tariff_meter": meter})
    return d


def _hass(value):
    hass = MagicMock()
    states = {METER: SimpleNamespace(state=str(value), attributes={})}
    hass.states.get = lambda eid: states.get(eid)
    return hass


@pytest.mark.unit
class TestASharedMeterIsOneOwnMeter:
    def test_it_is_one_entry_with_its_members(self):
        pump, car = _dev("heat_pump", 2000.0), _dev("ev_charger", 1000.0)
        out = DeviceTariffs(_hass(100.0)).cycle([pump, car], {}, T_NOON)
        assert len(out) == 1
        e = out[0]
        assert e.device_id == f"meter:{METER}" and e.meter
        assert dict(e.members) == {"heat_pump": 2000.0, "ev_charger": 1000.0}
        assert e.price == pytest.approx(0.20)

    def test_a_meter_named_by_one_device_is_unchanged(self):
        pump = _dev("heat_pump", 2000.0)
        out = DeviceTariffs(_hass(100.0)).cycle([pump], {}, T_NOON)
        assert len(out) == 1 and out[0].meter and not out[0].members

    def test_two_prices_on_one_meter_are_found(self):
        pump, car = _dev("heat_pump", 0.0, rate=0.20), _dev("ev_charger", 0.0, rate=0.25)
        t = DeviceTariffs(_hass(1.0))
        groups = t.shared_groups([pump, car])
        assert list(groups) == [METER] and t.mixed_prices(groups[METER])
        assert not t.mixed_prices([pump, _dev("x", 0.0, rate=0.20)])


# ── the real booking: one own-meter path (#1228 hold, #1230 spread) ──────

from .test_1230_coarse_meter_steps import Meter  # noqa: E402
from .test_1228_own_meter_outage import DAY, HOUSE, PUMP  # noqa: E402
from .test_812_device_tariff import _load  # noqa: E402

M = "sensor.hp_meter"


class Shared(Meter):
    """The #1230 night house with a heat pump AND a car behind ONE meter
    (a Messkonzept 12 cascade). The meter counts what both draw."""

    def __init__(self, *, pump_w=2000.0, car_w=1000.0, car_rate=PUMP, **kw):
        super().__init__(**kw)
        self.pump_w, self.car_w = pump_w, car_w
        pump = self.pumps[0]
        car = _load("ev_charger", rate=car_rate, meter=M)
        car.rated_power = 11000.0
        self.pumps = [pump, car]
        self._draw()

    def _draw(self):
        self.pumps[0].get_current_consumption.return_value = self.pump_w
        self.pumps[1].get_current_consumption.return_value = self.car_w

    def run(self, seconds, *, house_w=3300.0, step=10, **_kw):
        for _ in range(int(seconds // step)):
            self.now += timedelta(seconds=step)
            self.imp += house_w * self.grid(self.now) * step / 3.6e6
            self.meters[M] += (self.pump_w + self.car_w) * step / 3.6e6
            self._draw()
            self.cycle(house_w=house_w)

    def kwh(self, did):
        return self.calc._daily_accumulators.get(f"device_tariff_kwh:{did}_{DAY}", 0.0)


def _night(**kw):
    h = Shared(**kw)
    h.cycle(house_w=3300.0)
    h.run(3600)
    return h


@pytest.mark.unit
class TestTheSharedBooks:
    def test_a_coarse_tick_is_spread_not_clipped(self):
        """0.1 kWh ticks: each one holds ~2 min of use and must not be
        clipped to one 10 s cycle's import (the house kept the rest)."""
        h = _night(tick=0.1)
        total = h.kwh("heat_pump") + h.kwh("ev_charger") + h.kwh(f"meter:{M}")
        assert total == pytest.approx(3.0, abs=0.11)
        assert h.kwh("heat_pump") == pytest.approx(2.0, abs=0.08)
        assert h.kwh("ev_charger") == pytest.approx(1.0, abs=0.05)
        assert h.kwh(f"meter:{M}") == pytest.approx(0.0, abs=1e-9)

    def test_the_house_pays_only_what_no_own_tariff_took(self):
        h = _night(tick=0.1)
        own = h.kwh("heat_pump") + h.kwh("ev_charger")
        assert h.import_cost() == pytest.approx(
            (h.grid_kwh() - own) * HOUSE + own * PUMP, abs=1e-6)

    def test_a_late_meter_every_five_minutes(self):
        h = _night(tick=0.01, every=300)
        total = h.kwh("heat_pump") + h.kwh("ev_charger")
        assert total == pytest.approx(3.0, abs=0.3)   # the last 5 min not shown yet
        assert h.kwh("heat_pump") / h.kwh("ev_charger") == pytest.approx(2.0, rel=0.02)

    def test_a_step_in_a_sun_cycle_still_books_its_grid_part(self):
        """Ticks may land in a cycle with no grid share: the step is spread
        over its span, which had grid — never 0 with the baseline moved on."""
        h = _night(tick=0.1, grid=lambda now: 0.0 if (now.minute % 2) else 1.0)
        total = h.kwh("heat_pump") + h.kwh("ev_charger")
        assert total == pytest.approx(1.5, abs=0.2)

    def test_what_no_member_used_stays_on_the_meter(self):
        h = Shared(pump_w=0.0, car_w=0.0, tick=0.01)
        h.cycle(house_w=3300.0)
        for _ in range(60):     # something behind the meter draws 1 kW
            h.now += timedelta(seconds=10)
            h.imp += 3300.0 * 10 / 3.6e6
            h.meters[M] += 1000.0 * 10 / 3.6e6
            h.cycle(house_w=3300.0)
        assert h.kwh("heat_pump") == 0.0 and h.kwh("ev_charger") == 0.0
        assert h.kwh(f"meter:{M}") == pytest.approx(1000.0 * 600 / 3.6e6, abs=0.011)

    def test_a_restart_mid_span_keeps_the_split(self):
        h = Shared(tick=0.1)
        h.cycle(house_w=3300.0)
        h.run(1800)
        h.restart()
        h.cycle(house_w=3300.0)
        h.run(1800)
        assert h.kwh("heat_pump") / max(h.kwh("ev_charger"), 1e-9) == pytest.approx(2.0, rel=0.06)
        assert h.kwh("heat_pump") + h.kwh("ev_charger") == pytest.approx(3.0, abs=0.12)

    def test_an_outage_is_held_and_split(self):
        """#1228: an hour down; the step over it is held, settled against
        the rows over that span and split by what each used then."""
        h = Shared(tick=0.01)
        h.cycle(house_w=3300.0)
        h.run(60)
        before = h.kwh("heat_pump") + h.kwh("ev_charger")
        h.restart()
        h.down(3600, import_kwh=3.3, pump_kwh=0.0)
        h.meters[M] += 3.0
        h.cycle(house_w=3300.0)
        h.run(20)
        after = h.kwh("heat_pump") + h.kwh("ev_charger") + h.kwh(f"meter:{M}")
        assert after - before == pytest.approx(3.0, abs=0.1)
        assert h.calc.device_meter_gaps == {}

    def test_midnight_books_as_one_own_meter_does(self):
        """Across midnight a shared meter books exactly what ONE own meter
        with the same use books (the same path, #1228/#1230), split 2:1."""
        tomorrow = DAY.fromordinal(DAY.toordinal() + 1)

        def days(h, ids):
            return sum(h.calc._daily_accumulators.get(f"device_tariff_kwh:{d}_{day}", 0.0)
                       for d in ids for day in (DAY, tomorrow))

        h = Shared(tick=0.1)
        h.now = h.now.replace(hour=23, minute=40)
        h.cycle(house_w=3300.0)
        h.run(2400)
        one = Meter(tick=0.1)
        one.now = one.now.replace(hour=23, minute=40)
        one.cycle(house_w=3300.0)
        one.run(2400, house_w=3300.0, pump_w=3000.0)
        shared = days(h, ("heat_pump", "ev_charger", f"meter:{M}"))
        assert shared == pytest.approx(days(one, ("heat_pump",)), abs=0.11)
        assert days(h, ("heat_pump",)) == pytest.approx(2 * days(h, ("ev_charger",)), abs=0.08)


@pytest.mark.unit
class TestAChargerOnItsOwnTariff:
    def test_the_plan_reads_it(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _ev_plan_tariff,
        )
        car = _dev("ev_charger", 0.0, meter="")
        coord = SimpleNamespace(
            _ev_devices={"ev_charger": car},
            _surplus_controller=SimpleNamespace(device_tariffs=DeviceTariffs(MagicMock())))
        assert isinstance(_ev_plan_tariff(coord, "ev_charger"), PlanTariff)

    def test_no_tariff_is_the_house_plan(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _ev_plan_tariff,
        )
        car = _dev("ev_charger", 0.0, rate=0.0, meter="")
        coord = SimpleNamespace(
            _ev_devices={"ev_charger": car},
            _surplus_controller=SimpleNamespace(device_tariffs=DeviceTariffs(MagicMock())))
        assert _ev_plan_tariff(coord, "ev_charger") is None

    def test_its_live_gate_reads_its_own_level(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _charger_tariff_levels,
        )
        car = _dev("ev_charger", 0.0, meter="")
        car._tariff_level = "cheap"
        other = _dev("ev2", 0.0, rate=0.0, meter="")
        other._tariff_level = None
        coord = SimpleNamespace(_ev_devices={"ev_charger": car, "ev2": other})
        assert _charger_tariff_levels(coord) == {"ev_charger": "cheap"}

    def test_the_view_uses_it_and_the_house_level_otherwise(self):
        from custom_components.solar_energy_management.coordinator import build_view
        src = build_view.__file__
        text = open(src, encoding="utf-8").read()
        assert 'charger_tariff_levels' in text

    def test_its_row_carries_the_fields_from_its_own_config_only(self):
        """The setup reads the charger's OWN row — never the house's flat
        keys — the same three fields a load has."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        text = (root / "__init__.py").read_text(encoding="utf-8")
        assert "apply_tariff(ev_device, {k: charger_cfg.get(k) for k in TARIFF_KEYS" in text


@pytest.mark.unit
class TestNothingConfiguredChangesNothing:
    def test_no_tariff_no_cycle_entries(self):
        a = _dev("heat_pump", 2000.0, rate=0.0, meter="")
        b = _dev("ev_charger", 1000.0, rate=0.0, meter="")
        assert not tariff_of(a).configured
        assert DeviceTariffs(_hass(1.0)).cycle([a, b], {}, T_NOON) == []


@pytest.mark.unit
class TestOneMeterOnePrice:
    def test_two_prices_raise_a_repair_naming_them_and_clear_when_fixed(self):
        from unittest.mock import patch
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        pump, car = _dev("heat_pump", 0.0, rate=0.20), _dev("ev_charger", 0.0, rate=0.25)
        coord = SimpleNamespace(hass=MagicMock())
        base = "custom_components.solar_energy_management.coordinator.repair_issues."
        with patch(base + "raise_shared_meter_two_prices") as up, \
                patch(base + "clear_shared_meter_two_prices") as down:
            SEMCoordinator._check_shared_meter_prices(coord, DeviceTariffs(MagicMock()), [pump, car])
            assert up.call_count == 1
            kw = up.call_args.kwargs
            assert "heat_pump" in kw["devices"] and "ev_charger" in kw["devices"]
            assert kw["used"].startswith("heat_pump")
            # the same state again: no second Repair
            SEMCoordinator._check_shared_meter_prices(coord, DeviceTariffs(MagicMock()), [pump, car])
            assert up.call_count == 1
            apply_tariff(car, {"tariff_rate": 0.20})
            SEMCoordinator._check_shared_meter_prices(coord, DeviceTariffs(MagicMock()), [pump, car])
            assert down.call_count == 1

    def test_the_whole_meter_is_priced_at_the_first_device(self):
        pump, car = _dev("heat_pump", 1.0, rate=0.20), _dev("ev_charger", 1.0, rate=0.25)
        out = DeviceTariffs(_hass(1.0)).cycle([pump, car], {}, T_NOON)
        assert out[0].price == pytest.approx(0.20)
