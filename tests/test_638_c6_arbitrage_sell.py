"""#638 one-gate C6 — the arbitrage SELL path, wired with the valve closed.

The advisor's ``discharge_blocks`` had no actuation path at all. Now they
gate a FORCE_DISCHARGE through the same trust discipline as every consumer:
the PLAN says WHEN (the sell gate reads the stamped plan's arbitrage
blocks), the LIVE economics say WHETHER (``evaluate_arbitrage``'s
DISCHARGING_ARBITRAGE verdict stops being a window authority and becomes
the in-block validity check), and the user's mode gates say MAY (per-
battery ``allow_arbitrage`` / global toggle — every default keeps this
DORMANT; #533 stands).

Power discipline: the sell is AVOIDED IMPORT, not export-at-max — the
advisor bounds delivery by the home's own grid draw, so the block-implied
watts (kwh/hours) are the cap, split across the fleet
(``effective_battery_count``, the #531/#691 treatment).
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.overnight_actuation import (
    arbitrage_sell_gate,
)

NOW = datetime(2026, 8, 12, 19, 30, tzinfo=timezone.utc)


def _plan(*, blocks=None, computed_at="2026-08-12T14:00:00+00:00"):
    return {
        "computed_at": computed_at,
        "arbitrage": {
            "opportunity": True,
            "discharge_blocks": blocks if blocks is not None else [
                {"start": "2026-08-12T19:00:00+00:00",
                 "end": "2026-08-12T21:00:00+00:00",
                 "kwh": 3.0, "price": 0.40},
            ],
        },
    }


@pytest.mark.unit
class TestTheSellGate:
    def test_inside_the_block_yields_the_implied_power(self):
        in_block, power = arbitrage_sell_gate(_plan(), NOW)
        assert in_block is True
        assert power == pytest.approx(1500.0)  # 3 kWh over 2 h

    def test_outside_the_block_is_closed(self):
        early = datetime(2026, 8, 12, 17, 0, tzinfo=timezone.utc)
        in_block, power = arbitrage_sell_gate(_plan(), early)
        assert in_block is False and power == 0.0

    def test_no_arbitrage_on_the_plan_is_closed(self):
        in_block, power = arbitrage_sell_gate(
            {"computed_at": "2026-08-12T14:00:00+00:00"}, NOW)
        assert in_block is False and power == 0.0
        assert arbitrage_sell_gate(None, NOW) == (False, 0.0)

    def test_a_stale_stamp_is_closed(self):
        stale = _plan(computed_at="2026-08-10T14:00:00+00:00")
        assert arbitrage_sell_gate(stale, NOW) == (False, 0.0)

    def test_a_malformed_block_is_closed(self):
        bad = _plan(blocks=[{"start": "garbage", "end": None, "kwh": "x"}])
        assert arbitrage_sell_gate(bad, NOW) == (False, 0.0)


def _sell_sched(*, power=5000.0):
    return SimpleNamespace(
        state=SimpleNamespace(value="discharging_arbitrage"),
        discharge_power_w=power, floor_soc=50.0,
        from_arbitrage=True, reason="export arbitrage",
    )


def _view(*, sched=None, sell=None, mode="allow_arbitrage", soc=80.0,
          reserve=55.0, global_arb=False):
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config={"battery_max_discharge_power": 5000,
                "battery_mode": mode,
                "battery_reserve_soc": reserve,
                "battery_grid_arbitrage_enabled": global_arb},
        fleet=FleetContext(),
        charging_state="idle",
        ev_charging=False,
        home_consumption_w=500.0,
        scheduler_decision=sched,
        arbitrage_sell=sell,
    )


@pytest.mark.unit
class TestTheSellFiresOnlyInTheBlock:
    def test_live_verdict_plus_open_block_sells_at_the_capped_power(self):
        d = decide_battery(_view(sched=_sell_sched(power=5000.0),
                                 sell=(True, 1500.0)))
        assert d.intent == BatteryIntent.FORCE_DISCHARGE
        assert d.discharge_power_w == 1500.0  # block-implied, not max

    def test_live_verdict_without_a_block_does_not_sell(self):
        """The plan says WHEN — a live economics verdict alone no longer
        opens the valve."""
        d = decide_battery(_view(sched=_sell_sched(), sell=(False, 0.0)))
        assert d.intent != BatteryIntent.FORCE_DISCHARGE
        d2 = decide_battery(_view(sched=_sell_sched(), sell=None))
        assert d2.intent != BatteryIntent.FORCE_DISCHARGE

    def test_an_open_block_without_the_live_verdict_does_not_sell(self):
        d = decide_battery(_view(sched=None, sell=(True, 1500.0)))
        assert d.intent != BatteryIntent.FORCE_DISCHARGE

    def test_self_consumption_never_sells(self):
        d = decide_battery(_view(sched=_sell_sched(), sell=(True, 1500.0),
                                 mode="self_consumption"))
        assert d.intent != BatteryIntent.FORCE_DISCHARGE

    def test_default_config_stays_dormant(self):
        """auto mode + global toggle off (every default) → no sell, block
        or no block. #533 stands: the path is wired, the valve is closed."""
        d = decide_battery(_view(sched=_sell_sched(), sell=(True, 1500.0),
                                 mode="auto", global_arb=False))
        assert d.intent != BatteryIntent.FORCE_DISCHARGE

    def test_the_reserve_floor_still_binds(self):
        d = decide_battery(_view(sched=_sell_sched(), sell=(True, 1500.0),
                                 soc=54.0, reserve=55.0))
        assert d.intent != BatteryIntent.FORCE_DISCHARGE


@pytest.mark.unit
class TestThePipelineWiresTheSplit:
    def test_the_pipeline_computes_the_gate_and_splits_the_fleet(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._run_battery_pipeline)
        assert "arbitrage_sell_gate(" in src
        assert "effective_battery_count(" in src

    def test_the_v173_hardcode_is_gone(self):
        """_any_allow_arb = False was the #533 freeze; on the one-gate
        branch the per-battery opt-in scan is real again (defaults still
        dormant — no battery ships in allow_arbitrage mode)."""
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._run_battery_pipeline)
        assert "_any_allow_arb = False" not in src
