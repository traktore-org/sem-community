"""#1282: publishing a complete plan must not create a charging shortage."""
import json
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator import ev_night_targets
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    ev_overlay,
    plan_gate,
)

from .test_638_shadow_mode import (  # noqa: F401 — include the fixed-clock fixture
    _fake_self, _idle_load, _power, _scheduler, _freeze_now,
)


@pytest.mark.parametrize("charger_id", ["ev_charger", "second_car"])
@pytest.mark.parametrize("need_kwh", [5.2834, 10.5668])
def test_published_plan_keeps_a_fitting_ev_waiting(monkeypatch, charger_id, need_kwh):
    """Packing -> published blocks -> gate must not invent a sub-Wh shortage.

    A measured 5283.4 W became 5283 W in the control stash. A complete
    one-hour allocation then appeared 0.4 Wh short, released the wait,
    and let the reactive layer start a minimum-on charging burst.
    """
    from datetime import datetime

    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {charger_id: need_kwh})
    fake = _fake_self(devices=[_idle_load()])
    fake.config["ev_chargers"][0].update(
        id=charger_id, ev_phases=1, ev_min_current=6, ev_max_current=28)
    fake._ev_watts_for_amps = lambda cid, cfg, amps: float(amps) * 5283.4 / 28
    assert SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(deficit=0), energy=MagicMock(), power=_power())

    # Exercise the actual serialized producer output, not a hand-written
    # plan that silently omits the coordinator's lossy projection.
    plan = json.loads(json.dumps(fake._energy_plan_shadow))
    demand_id = f"ev:{charger_id}"
    row = next(r for r in plan["demands"] if r["id"] == demand_id)
    assert row["status"] == "fits"
    gate = plan_gate(plan, demand_id, datetime.fromisoformat(plan["computed_at"]))
    assert gate.covered and not gate.in_block
    assert gate.remaining_kwh == pytest.approx(need_kwh, abs=1e-6)
    kwargs = dict(reachable=True, deadline_active=False, watts_per_amp=5283.4 / 28,
                  min_amps=6, max_amps=28)
    assert ev_overlay(gate, remaining_kwh=need_kwh, **kwargs) == (True, 0)

    # Keep the existing guarantee: a real shortage or an urgent deadline
    # must still release the wait; this fix adds no energy deadband.
    assert ev_overlay(gate, remaining_kwh=need_kwh + 0.1, **kwargs) == (False, 0)
    assert ev_overlay(gate, remaining_kwh=need_kwh,
                      **{**kwargs, "deadline_active": True}) == (False, 0)
    assert ev_overlay(gate, remaining_kwh=need_kwh,
                      **{**kwargs, "reachable": False}) == (False, 0)
