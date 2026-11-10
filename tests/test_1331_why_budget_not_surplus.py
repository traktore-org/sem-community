"""#1331 — the Why card showed the car's budget as Surplus at night.

``_stamp_decision_inputs`` wrote the charging context's ``available_power``
(the grid room left for a car) as ``surplus_w`` on every row. At 05:12, with
0 W of sun and no car charger, a boiler row read "Surplus 4.1 kW".

Now a charger row carries the car's budget as ``budget_w``; load, battery
and export rows carry ``surplus_w`` = spare sun, the solar-bounded figure the
load controller uses. At night with 0 W of sun no row shows a positive
surplus.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.decision_log import (
    KIND_BATTERY, KIND_CHARGER, KIND_EXPORT, KIND_LOAD, DecisionLog,
)


def _stamped_log(*, solar_w, budget_w, spare_sun_w):
    log = DecisionLog(MagicMock())
    fake = SimpleNamespace(
        _surplus_controller=SimpleNamespace(decision_log=log),
        _energy_calculator=None, _tariff_provider=None,
        _loads_true_surplus_w=spare_sun_w,
        _battery_display_names=lambda power: {},
    )
    power = SimpleNamespace(solar_power=solar_w, battery_soc=60.0)
    ctx = SimpleNamespace(available_power=budget_w, night_target_kwh=None)
    SEMCoordinator._stamp_decision_inputs(fake, power, ctx)
    return log


def _rows(log):
    for i, kind in enumerate((KIND_CHARGER, KIND_BATTERY, KIND_LOAD,
                              KIND_EXPORT)):
        log.record(device_id=f"d{i}", kind=kind, verb="on", value=10 + i)
    return {r["device_kind"]: r["inputs"] for r in log.records()}


def test_at_night_no_row_shows_a_positive_surplus():
    rows = _rows(_stamped_log(solar_w=0.0, budget_w=4100.0, spare_sun_w=0.0))
    for kind, inputs in rows.items():
        assert not inputs.get("surplus_w"), (kind, inputs)
    assert rows[KIND_CHARGER]["budget_w"] == 4100.0


def test_a_charger_row_keeps_the_budget_and_the_others_the_sun():
    rows = _rows(_stamped_log(solar_w=5200.0, budget_w=3000.0,
                              spare_sun_w=1400.0))
    assert rows[KIND_CHARGER]["budget_w"] == 3000.0
    assert "surplus_w" not in rows[KIND_CHARGER]
    for kind in (KIND_LOAD, KIND_BATTERY, KIND_EXPORT):
        assert rows[kind]["surplus_w"] == 1400.0
        assert "budget_w" not in rows[kind]


def test_a_fresh_sun_figure_reaches_the_rows_after_it():
    log = _stamped_log(solar_w=5200.0, budget_w=3000.0, spare_sun_w=1400.0)
    log.set_input("surplus_w", 900.0)
    rows = _rows(log)
    assert rows[KIND_LOAD]["surplus_w"] == 900.0


def test_a_row_stays_small():
    rows = _rows(_stamped_log(solar_w=0.0, budget_w=4100.0, spare_sun_w=0.0))
    assert len(json.dumps(rows[KIND_CHARGER])) < 300
