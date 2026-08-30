"""#778 — the spend TRIGGER: the budget finally has a WHEN and a WHETHER.

The arc shipped a measured budget, floors and permissions — and a sell
path that only the arbitrage engine could open. On a fixed export price
(the maintainer's install, the reporter's install) arbitrage never fires:
the issue's own goal — "sell today's unnecessary stored battery energy" —
had no trigger. These tests pin the new one end to end:

* the PLAN writes one just-in-time block ending exactly at the night
  window's start (latest-possible selling: after the solar tail by
  construction, done the minute the night takes over);
* the GATE reads it under the same trust discipline as arbitrage's;
* the LIVE verdict fires only inside the block, in arbitrage's verdict
  shape, so every downstream discipline — mode/permission gate, three
  floors, budget cap, fleet split, #758 kill switch — applies unchanged;
* every default keeps it SHUT (`forecast_spending_enabled` off).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    SchedulerState,
)
from custom_components.solar_energy_management.coordinator.forecast_sell import (
    MIN_BLOCK_MIN,
    MIN_SPEND_KWH,
    evaluate_forecast_sell,
    forecast_sell_blocks,
)

TZ = timezone.utc
NOW = datetime(2026, 8, 27, 17, 0, tzinfo=TZ)
NIGHT = datetime(2026, 8, 27, 20, 30, tzinfo=TZ)


class TestThePlanBlocks:
    def test_one_jit_block_ending_at_night_start(self):
        b = forecast_sell_blocks(NOW, NIGHT, 2.2, 5000.0)
        assert len(b) == 1
        blk = b[0]
        assert blk["end"] == NIGHT
        # 2.2 kWh at 5 kW = 26.4 min before the night
        span_min = (NIGHT - blk["start"]).total_seconds() / 60
        assert span_min == pytest.approx(26.4, abs=0.5)
        assert blk["kwh"] == pytest.approx(2.2, abs=0.01)

    def test_a_big_budget_never_implies_a_rate_above_the_cap(self):
        """A budget too big for the time left sells at the cap, not faster.

        This used to be spelled as a TRIM — ``start`` pinned to ``now`` and
        ``kwh`` cut to what the remaining window carried. That spelling is
        what made the window shrink with the clock and vanish inside the
        last MIN_BLOCK_MIN minutes, stopping the sell exactly when
        "just in time" means to act (live on .175, 30.08.2026 — see
        tests/test_778_block_survives_to_night.py).

        The block is now anchored to the night, and the property the trim
        was protecting holds by construction instead: the gate derives
        ``kwh / hours``, which for an over-sized budget is exactly the cap.
        """
        late = NIGHT - timedelta(minutes=30)
        b = forecast_sell_blocks(late, NIGHT, 9.9, 5000.0)
        assert len(b) == 1
        blk = b[0]
        assert blk["start"] <= late < blk["end"] == NIGHT
        hours = (blk["end"] - blk["start"]).total_seconds() / 3600.0
        assert blk["kwh"] / hours * 1000.0 == pytest.approx(5000.0), (
            "an over-stuffed block would imply a discharge above the "
            "inverter's own limit"
        )
        # …and the half hour that is actually left still carries 2.5 kWh.
        assert blk["kwh"] / hours * 0.5 == pytest.approx(2.5)

    def test_nothing_spendable_means_no_block(self):
        assert forecast_sell_blocks(NOW, NIGHT, MIN_SPEND_KWH - 0.05, 5000.0) == []
        assert forecast_sell_blocks(NOW, NIGHT, 0.0, 5000.0) == []

    def test_the_night_owns_the_battery_from_its_first_minute(self):
        assert forecast_sell_blocks(NIGHT, NIGHT, 5.0, 5000.0) == []
        assert forecast_sell_blocks(NIGHT + timedelta(minutes=1), NIGHT, 5.0, 5000.0) == []

    def test_degenerate_inputs_say_nothing(self):
        assert forecast_sell_blocks(NOW, None, 5.0, 5000.0) == []
        assert forecast_sell_blocks(NOW, NIGHT, 5.0, 0.0) == []
        assert forecast_sell_blocks(NOW, NIGHT, "broken", 5000.0) == []

    def test_a_tiny_budget_still_gets_a_civilised_block(self):
        b = forecast_sell_blocks(NOW, NIGHT, 0.25, 5000.0)
        assert len(b) == 1
        span_min = (b[0]["end"] - b[0]["start"]).total_seconds() / 60
        assert span_min >= MIN_BLOCK_MIN                 # no 3-minute contactor stunts


class TestTheLiveVerdict:
    def _fire(self, **over):
        kw = dict(enabled=True, in_block=True, block_w=4400.0,
                  spendable_kwh=2.2, max_discharge_w=5000.0,
                  dynamic_floor_pct=61.0, reserve_pct=20.0)
        kw.update(over)
        return evaluate_forecast_sell(NOW, **kw)

    def test_it_fires_in_arbitrages_shape(self):
        v = self._fire()
        assert v.state is SchedulerState.DISCHARGING_ARBITRAGE
        assert v.from_arbitrage and v.from_forecast_spend
        assert v.discharge_power_w == pytest.approx(4400.0)

    def test_the_strongest_known_floor_rides_the_verdict(self):
        assert self._fire().floor_soc == pytest.approx(61.0)
        assert self._fire(dynamic_floor_pct=None).floor_soc == pytest.approx(20.0)
        assert self._fire(dynamic_floor_pct=5.0).floor_soc == pytest.approx(20.0)

    def test_off_means_off(self):
        v = self._fire(enabled=False)
        assert v.state is SchedulerState.IDLE and v.from_forecast_spend

    def test_outside_the_block_it_holds(self):
        assert self._fire(in_block=False).state is SchedulerState.IDLE

    def test_an_empty_budget_never_fires(self):
        assert self._fire(spendable_kwh=0.0).state is SchedulerState.NOT_NEEDED

    def test_block_rate_falls_back_to_the_configured_cap(self):
        assert self._fire(block_w=0.0).discharge_power_w == pytest.approx(5000.0)


class TestTheGate:
    def _plan(self, *, start=NOW, end=NIGHT, kwh=2.2, age_min=5):
        return {
            "computed_at": (NOW - timedelta(minutes=age_min)).isoformat(),
            "forecast_sell": {"enabled": True, "blocks": [
                {"start": start.isoformat(), "end": end.isoformat(), "kwh": kwh},
            ]},
        }

    def test_inside_the_block_the_gate_opens_with_the_block_rate(self):
        from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
            forecast_sell_gate,
        )
        open_, w = forecast_sell_gate(self._plan(), NOW + timedelta(minutes=10))
        assert open_ is True
        hours = (NIGHT - NOW).total_seconds() / 3600
        assert w == pytest.approx(2.2 / hours * 1000.0)

    def test_outside_or_stale_or_malformed_declines(self):
        from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
            forecast_sell_gate,
        )
        assert forecast_sell_gate(self._plan(), NIGHT + timedelta(minutes=1)) == (False, 0.0)
        from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
            _MAX_PLAN_AGE,
        )
        stale_min = int(_MAX_PLAN_AGE.total_seconds() / 60) + 30
        assert forecast_sell_gate(self._plan(age_min=stale_min), NOW) == (False, 0.0)
        assert forecast_sell_gate({}, NOW) == (False, 0.0)
        assert forecast_sell_gate(None, NOW) == (False, 0.0)
        bad = self._plan(); bad["forecast_sell"]["blocks"][0]["kwh"] = "broken"
        assert forecast_sell_gate(bad, NOW) == (False, 0.0)


class TestDecideBatteryActsOnTheSpendVerdict:
    """The same discharging_arbitrage branch, but gated by the SPEND plan
    block and the SPEND switch — not arbitrage's toggle."""

    def _view(self, *, spend_open=True, spend_w=4400.0, enabled=True,
              soc=78.0, budget=2.2, dyn_floor=61.0):
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            SchedulerDecision, SchedulerState,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryRuntime, BatteryView, FleetContext,
        )
        sched = SchedulerDecision(
            state=SchedulerState.DISCHARGING_ARBITRAGE,
            discharge_power_w=5000.0, floor_soc=61.0,
            from_arbitrage=True, from_forecast_spend=True,
            reason="forecast spend: test")
        return BatteryView(
            runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
            config={"battery_max_discharge_power": 5000,
                    "battery_mode": "auto",
                    "battery_reserve_soc": 20.0,
                    "battery_grid_arbitrage_enabled": False},   # arbitrage OFF
            fleet=FleetContext(),
            charging_state="idle",
            ev_charging=False,
            home_consumption_w=500.0,
            scheduler_decision=sched,
            arbitrage_sell=(False, 0.0),                        # arbitrage gate shut
            forecast_sell=(spend_open, spend_w),
            forecast_spending_enabled=enabled,
            battery_spendable_kwh=budget,
            dynamic_floor_pct=dyn_floor,
        )

    def _decide(self, view):
        from custom_components.solar_energy_management.coordinator.decide_battery import (
            decide_battery,
        )
        return decide_battery(view)

    def test_it_sells_through_the_spend_gate_with_arbitrage_fully_off(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        d = self._decide(self._view())
        assert d.intent is BatteryIntent.FORCE_DISCHARGE
        assert d.discharge_power_w == pytest.approx(4400.0)
        assert d.floor_soc == pytest.approx(61.0)          # dynamic floor binds

    def test_the_spend_gate_shut_means_no_sale(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        d = self._decide(self._view(spend_open=False))
        assert d.intent is not BatteryIntent.FORCE_DISCHARGE

    def test_the_master_switch_off_means_no_sale(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        d = self._decide(self._view(enabled=False))
        assert d.intent is not BatteryIntent.FORCE_DISCHARGE

    def test_an_empty_budget_holds_even_inside_the_block(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        d = self._decide(self._view(budget=0.0))
        assert d.intent is not BatteryIntent.FORCE_DISCHARGE

    def test_soc_at_the_dynamic_floor_holds(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        d = self._decide(self._view(soc=61.0))
        assert d.intent is not BatteryIntent.FORCE_DISCHARGE

    def test_unavailable_soc_never_sells_blind(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        d = self._decide(self._view(soc=None))
        assert d.intent is not BatteryIntent.FORCE_DISCHARGE


class TestTheCoordinatorWiring:
    def test_the_kill_switch_guards_the_spend_gate_too(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        src = inspect.getsource(cm)
        assert "forecast_sell_gate(" in src
        i = src.index("forecast_sell_gate(")
        guard = src[max(0, i - 600):i]
        assert "_energy_plan_actuation" in guard, "#758: a kill switch some callers ask is not a kill switch"

    def test_the_plan_carries_the_spend_blocks_besides_arbitrages(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        src = inspect.getsource(cm)
        assert src.count('"forecast_sell":') >= 2, "both the packed and the quiet plan must carry it"

    def test_the_view_hands_decide_the_spend_gate(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        src = inspect.getsource(cm)
        assert "forecast_sell=_fsell" in src
