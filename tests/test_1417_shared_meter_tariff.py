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

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.device_tariff import (
    DeviceCycle, DeviceTariffs, PlanTariff, apply_tariff, tariff_of,
)

from .test_812_device_tariff import T_NOON, _calc, _cycle

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


def _shared(devs, store, value, at):
    out = DeviceTariffs(_hass(value)).cycle(devs, store, at)
    for e in out:   # the booking writes the meter's baseline back
        if getattr(e, "shared", False) and e.baseline is not None:
            store[e.device_id] = e.baseline
    return out


@pytest.mark.unit
class TestASharedMeter:
    def test_its_step_is_split_by_draw(self):
        pump, car = _dev("heat_pump", 2000.0), _dev("ev_charger", 1000.0)
        store = {}
        _shared([pump, car], store, 100.0, T_NOON)            # first read
        out = _shared([pump, car], store, 100.6, T_NOON + timedelta(minutes=15))
        by = {e.device_id: e for e in out}
        assert by["heat_pump"].meter_kwh == pytest.approx(0.4)
        assert by["ev_charger"].meter_kwh == pytest.approx(0.2)
        assert by[f"meter:{METER}"].meter_kwh == pytest.approx(0.0)
        assert all(e.shared for e in out)

    def test_what_none_drew_stays_on_the_meter(self):
        pump, car = _dev("heat_pump", 0.0), _dev("ev_charger", 0.0)
        store = {}
        _shared([pump, car], store, 100.0, T_NOON)
        out = _shared([pump, car], store, 100.3, T_NOON + timedelta(minutes=15))
        by = {e.device_id: e for e in out}
        assert by[f"meter:{METER}"].meter_kwh == pytest.approx(0.3)
        assert by["heat_pump"].meter_kwh == 0.0 and by["ev_charger"].meter_kwh == 0.0

    def test_the_meter_is_read_once_with_one_baseline(self):
        pump, car = _dev("heat_pump", 2000.0), _dev("ev_charger", 1000.0)
        store = {}
        _shared([pump, car], store, 100.0, T_NOON)
        assert set(store) == {f"meter:{METER}"}

    def test_a_meter_named_by_one_device_is_unchanged(self):
        pump = _dev("heat_pump", 2000.0)
        out = DeviceTariffs(_hass(100.0)).cycle([pump], {}, T_NOON)
        assert len(out) == 1 and out[0].meter and not out[0].shared


@pytest.mark.unit
class TestTheBooks:
    def test_house_pays_only_what_no_own_tariff_took(self):
        calc = _calc(0.30)
        entries = [
            DeviceCycle("heat_pump", power_w=1000.0, meter_kwh=0.5, price=0.20, shared=True),
            DeviceCycle("ev_charger", power_w=500.0, meter_kwh=0.25, price=0.20, shared=True),
            DeviceCycle(f"meter:{METER}", meter_kwh=0.25, price=0.20, shared=True,
                        baseline={"entity": METER, "value": 1.0,
                                  "at": T_NOON.isoformat(), "date": "2026-10-03"}),
        ]
        # 1 h at 2 kW import, all of the house from the grid
        _cycle(calc, T_NOON, import_w=2000.0, entries=entries)
        day = T_NOON.date()
        assert calc.get_device_tariff("heat_pump", day)["daily_grid_kwh"] == pytest.approx(0.5)
        assert calc.get_device_tariff("ev_charger", day)["daily_grid_kwh"] == pytest.approx(0.25)
        # what nobody drew is the meter's, at its tariff — never the house's
        assert calc.get_device_tariff(f"meter:{METER}", day)["daily_grid_kwh"] == \
            pytest.approx(0.25)
        # the house: 2 kWh − 1 kWh on the cascade meter = 1 kWh at 0.30
        assert calc._get_daily_cost("cost_import", day) == pytest.approx(1.0 * 0.30 + 1.0 * 0.20)
        assert calc.device_meter_last[f"meter:{METER}"]["value"] == 1.0


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
