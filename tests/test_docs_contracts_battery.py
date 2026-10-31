"""#1112 — the battery mode table and the two battery permissions, as tests.

The user guide was written from the code. Each test is one of its sentences,
driven through the real ``decide_battery`` (and, for the car permission, the
real charger ``decide``). The docstring quotes the sentence and names where
it lives. A row the owner may want to change still tests today's behaviour;
its docstring says "edge case — open for discussion" and names the issue.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    ChargerEnergy,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import decide
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
    manual_mode_done,
)

USER_GUIDE = "docs/USER_GUIDE.md"
MODES = "Per-Battery Modes (Multi-Battery Systems, v1.7.3)"
SPEND = "Forecast-Led Spending — What the budget may be spent on"

MAX_DISCHARGE_W = 4000.0
MAX_CHARGE_W = 5000.0
SELL = (True, MAX_DISCHARGE_W)   # the plan's sell block is open


def _view(*, mode="auto", soc=80.0, reserve=None, sched=None, perms=None,
          sell=None, forecast_sell=None, forecast_spending=False,
          spendable_kwh=0.0, arbitrage_on=True, ev_connected=False,
          fleet=None, available=True):
    cfg = {
        "battery_mode": mode,
        "battery_max_discharge_power": MAX_DISCHARGE_W,
        "battery_max_charge_power_w": MAX_CHARGE_W,
        "battery_grid_arbitrage_enabled": arbitrage_on,
    }
    if reserve is not None:
        cfg["battery_reserve_soc"] = reserve
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc,
                               available=available),
        config=cfg,
        fleet=fleet or FleetContext(),
        charging_state="idle",
        ev_charging=False,
        ev_connected=ev_connected,
        home_consumption_w=500.0,
        scheduler_decision=sched,
        arbitrage_sell=sell,
        forecast_sell=forecast_sell,
        forecast_spending_enabled=forecast_spending,
        battery_spendable_kwh=spendable_kwh,
        battery_permissions=perms,
    )


def _sell_verdict(*, spend=False, floor=10.0):
    """The scheduler's 'sell now' verdict — arbitrage, or the forecast spend."""
    return SimpleNamespace(
        state=SimpleNamespace(value="discharging_arbitrage"),
        discharge_power_w=MAX_DISCHARGE_W, floor_soc=floor,
        reason="sell", should_charge=False,
        from_forecast_spend=spend, from_arbitrage=not spend,
    )


def _sells(d) -> bool:
    return d.intent is BatteryIntent.FORCE_DISCHARGE


# ── the mode table ──────────────────────────────────────────────────────


class TestBatteryModeTable:
    def test_auto_leaves_the_battery_to_the_inverter(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Auto | The inverter runs the
        battery as usual. SEM steps in only to: […]".

        Nothing to step in for: SEM's command is NORMAL — no forced charge,
        no sale, no hold."""
        d = decide_battery(_view(mode="auto"))
        assert d.intent is BatteryIntent.NORMAL

    def test_auto_holds_the_battery_for_a_car_without_spare_sun(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Auto | … hold it to the house
        while a car is plugged in and the spare sun is under the Solar Gate
        or the battery is under the Buffer SoC".

        A car plugged in, no sun, pack at 95 %: held to the house."""
        fleet = FleetContext(solar_w=0.0, home_w=500.0, battery_soc=95.0)
        d = decide_battery(_view(mode="auto", soc=95.0, ev_connected=True,
                                 fleet=fleet))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w <= 500.0

    def test_auto_sells_in_the_sell_hours_when_selling_is_on(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Auto | … sell in the plan's
        sell hours when selling is on"."""
        assert _sells(decide_battery(_view(
            mode="auto", sched=_sell_verdict(), sell=SELL)))
        assert not _sells(decide_battery(_view(
            mode="auto", sched=_sell_verdict(), sell=SELL,
            arbitrage_on=False)))

    def test_self_consumption_never_sells_arbitrage(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Self-Consumption | As Auto, but it
        never sells to the grid, unless you turn on *Battery may sell to the
        grid*".

        Arbitrage is on, the plan's sell block is open, the price verdict
        says sell — a Self-Consumption battery still does not."""
        sells_in_auto = decide_battery(_view(
            mode="auto", sched=_sell_verdict(), sell=SELL))
        assert _sells(sells_in_auto)   # the same cycle sells in Auto
        d = decide_battery(_view(
            mode="self_consumption", sched=_sell_verdict(), sell=SELL))
        assert not _sells(d)

    def test_self_consumption_never_sells_the_forecast_budget(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Self-Consumption | … never
        sells to the grid" — the forecast spend is the second road to the grid,
        and it is closed too."""
        kw = dict(sched=_sell_verdict(spend=True), forecast_sell=SELL,
                  forecast_spending=True, spendable_kwh=5.0)
        assert _sells(decide_battery(_view(mode="auto", **kw)))
        d = decide_battery(_view(mode="self_consumption", **kw))
        assert not _sells(d)

    def test_force_charge_charges_to_full(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Force Charge | Charges to 100 %
        now, at the maximum charge power, from the sun and the grid".\""""
        d = decide_battery(_view(mode="force_charge", soc=40.0))
        assert d.intent is BatteryIntent.FORCE_CHARGE
        assert d.target_soc == 100.0
        assert d.charge_power_w == MAX_CHARGE_W

    def test_force_charge_goes_back_to_auto_at_100(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Force Charge | … At 100 % the
        mode goes back to Auto." (#1131)

        The coordinator writes Auto when ``manual_mode_done`` says so; the
        write itself is pinned in ``test_1131_manual_mode_finishes.py``."""
        assert not manual_mode_done("force_charge", 99.0, soc_read=True, reserve=20)
        assert manual_mode_done("force_charge", 100.0, soc_read=True, reserve=20)

    def test_force_charge_goes_back_to_auto_when_the_pack_takes_no_more(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Force Charge | … Some inverters
        stop the charge below 100 %: at 90 % or more, a battery that takes no
        more charge for 15 minutes also goes back to Auto." (#1164)

        The window and the write are pinned in
        ``test_1164_force_charge_stall.py``."""
        from custom_components.solar_energy_management.coordinator.decide_battery import (
            MANUAL_CHARGE_STALL_S, MANUAL_CHARGE_STALL_SOC, charge_stall_read,
            charge_stall_step,
        )
        assert MANUAL_CHARGE_STALL_SOC == 90.0
        assert MANUAL_CHARGE_STALL_S == 15 * 60
        read = dict(soc_read=True, power_read=True, asked_w=5000.0,
                    sem_charging=True)
        assert charge_stall_read(90.0, 0.0, **read)
        assert not charge_stall_read(89.0, 0.0, **read)
        window, stalled = None, False
        for t in range(0, 15 * 60 + 1, 30):      # one check every 30 s
            assert not stalled
            window, stalled = charge_stall_step(window, float(t), 95.0, True)
        assert stalled
        assert manual_mode_done("force_charge", 95.0, soc_read=True, reserve=20,
                                charge_stalled=stalled)

    def test_force_charge_buys_at_any_price(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Force Charge | … **at any
        price**" and "It does not wait for a cheap hour: at night in an
        expensive hour it buys from the grid."

        Deliberate override, settled per #1116: charge now, whatever the
        price. Night, no sun, the tariff is EXPENSIVE: it force-charges
        anyway."""
        fleet = FleetContext(solar_w=0.0, home_w=500.0, is_night=True,
                             tariff_level="expensive")
        d = decide_battery(_view(mode="force_charge", soc=40.0, fleet=fleet))
        assert d.intent is BatteryIntent.FORCE_CHARGE
        assert d.charge_power_w == MAX_CHARGE_W

    def test_self_consumption_sells_when_you_allow_it(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Self-Consumption | … unless
        you turn on *Battery may sell to the grid*"."""
        d = decide_battery(_view(mode="self_consumption", sched=_sell_verdict(),
                                 sell=SELL, perms={"may_export": True}))
        assert _sells(d)

    def test_force_discharge_runs_at_maximum_rate(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Force Discharge | Sells at the
        maximum discharge power down to this battery's reserve".\""""
        d = decide_battery(_view(mode="force_discharge", soc=80.0, reserve=30))
        assert d.intent is BatteryIntent.FORCE_DISCHARGE
        assert d.discharge_power_w == MAX_DISCHARGE_W

    def test_force_discharge_stops_at_the_reserve(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Force Discharge | Sells … down
        to this battery's reserve, then the mode goes back to Auto".\" (#1131)"""
        above = decide_battery(_view(mode="force_discharge", soc=31.0, reserve=30))
        assert above.intent is BatteryIntent.FORCE_DISCHARGE
        assert above.floor_soc == 30
        assert not manual_mode_done("force_discharge", 31.0, soc_read=True, reserve=30)
        at = decide_battery(_view(mode="force_discharge", soc=30.0, reserve=30))
        assert at.intent is not BatteryIntent.FORCE_DISCHARGE
        assert manual_mode_done("force_discharge", 30.0, soc_read=True, reserve=30)

    def test_force_discharge_goes_back_to_auto_when_the_pack_sends_no_more(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Force Discharge | … Some
        inverters stop the sale above the reserve: a battery that sends
        nothing for 15 minutes while the home buys from the grid and there is
        no sun also goes back to Auto." (#1165)

        The window and the write are pinned in ``test_1165_sale_stall.py``."""
        from custom_components.solar_energy_management.coordinator.decide_battery import (
            MANUAL_CHARGE_STALL_S, sale_stall_read, sale_stall_step,
        )
        assert MANUAL_CHARGE_STALL_S == 15 * 60
        read = dict(soc_read=True, power_read=True, asked_w=5000.0,
                    sem_selling=True)
        assert sale_stall_read(30.0, 0.0, site=(400.0, 0.0), **read)
        assert not sale_stall_read(30.0, 0.0, site=(0.0, 3000.0), **read), (
            "the sun feeds the home: an export limit may hold the pack")
        assert not sale_stall_read(30.0, 0.0, site=(900.0, 1500.0), **read), (
            "the home buys, but there is sun")
        window, stalled = None, False
        for t in range(0, 15 * 60 + 1, 30):      # one check every 30 s
            assert not stalled
            window, stalled = sale_stall_step(window, float(t), 30.0, True)
        assert stalled
        assert manual_mode_done("force_discharge", 30.0, soc_read=True,
                                reserve=20, sale_stalled=stalled)

    def test_a_reserve_never_set_is_20_percent(self):
        """USER_GUIDE.md, "Per-Battery Modes": "A reserve you never set is
        20 %."  A forced sale stops at 20 % when no reserve was chosen."""
        above = decide_battery(_view(mode="force_discharge", soc=21.0))
        assert above.intent is BatteryIntent.FORCE_DISCHARGE
        assert above.floor_soc == 20.0
        at = decide_battery(_view(mode="force_discharge", soc=20.0))
        assert at.intent is not BatteryIntent.FORCE_DISCHARGE

    def test_force_discharge_never_sells_blind(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Force Discharge | … It does
        not sell while the battery level cannot be read.\""""
        d = decide_battery(_view(mode="force_discharge", soc=80.0, reserve=30,
                                 available=False))
        assert d.intent is not BatteryIntent.FORCE_DISCHARGE

    def test_off_beats_every_other_branch(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Off | One clean hand-over to the
        inverter, then SEM sends nothing to this battery".

        A sell verdict, an open sell block and a plugged car — none of them
        moves an Off battery out of hands-off."""
        d = decide_battery(_view(mode="off", sched=_sell_verdict(), sell=SELL,
                                 ev_connected=True, soc=95.0))
        assert d.intent is BatteryIntent.OFF

    @pytest.mark.asyncio
    async def test_off_hands_over_once_then_sends_nothing(self):
        """USER_GUIDE.md, "Per-Battery Modes": "Off | One clean hand-over to the
        inverter, then SEM sends nothing to this battery".

        A battery SEM was selling from is switched to Off: one handoff, then
        ten cycles with nothing on the wire."""
        hass = MagicMock()
        state = Mock()
        state.state = "4000"
        state.attributes = {"min": 0, "max": 10000}
        hass.states.get = Mock(return_value=state)
        hass.services.async_call = AsyncMock(return_value=None)
        adapter = GenericBatteryAdapter(hass, {
            "battery_discharge_control_entity": "number.batt_limit",
            "battery_max_discharge_power": MAX_DISCHARGE_W,
        })
        adapter._last_intent = BatteryIntent.FORCE_DISCHARGE

        view = _view(mode="off", sched=_sell_verdict(), sell=SELL,
                     ev_connected=True)
        await actuate_battery(decide_battery(view), adapter)
        assert adapter.last_intent is BatteryIntent.OFF
        handoff_calls = hass.services.async_call.await_count

        for _ in range(10):
            await actuate_battery(decide_battery(view), adapter)
        assert hass.services.async_call.await_count == handoff_calls


# ── the two permissions ─────────────────────────────────────────────────


class TestBatteryPermissions:
    def test_may_not_sell_never_sells(self):
        """USER_GUIDE.md, "What the budget may be spent on": "Battery may sell
        to the grid — off: SEM does not sell on a high price or from the
        forecast budget."

        Turned off, in Auto with arbitrage on: no sale on either road."""
        no = {"may_export": False}
        arb = decide_battery(_view(mode="auto", sched=_sell_verdict(),
                                   sell=SELL, perms=no))
        spend = decide_battery(_view(
            mode="auto", sched=_sell_verdict(spend=True), forecast_sell=SELL,
            forecast_spending=True, spendable_kwh=5.0, perms=no))
        assert not _sells(arb)
        assert not _sells(spend)

    def test_may_not_sell_still_obeys_force_discharge(self):
        """USER_GUIDE.md, "What the budget may be spent on": "*Force
        Discharge* still sells; it is a manual order.\""""
        d = decide_battery(_view(mode="force_discharge", soc=80.0, reserve=30,
                                 perms={"may_export": False}))
        assert _sells(d)

    def test_unset_permissions_keep_the_old_behaviour(self):
        """USER_GUIDE.md, "What the budget may be spent on": "Both default to
        your current behaviour, so turning forecast spending on does not
        silently grant a permission you never gave."

        Unset sells exactly where the mode alone sold before: Auto follows the
        arbitrage switch, Self-Consumption never sells."""
        def sells(mode, arbitrage_on):
            return _sells(decide_battery(_view(
                mode=mode, sched=_sell_verdict(), sell=SELL, perms=None,
                arbitrage_on=arbitrage_on)))
        assert sells("auto", True) is True
        assert sells("auto", False) is False
        assert sells("self_consumption", True) is False

    def test_may_not_charge_the_car_gives_the_charger_no_assist(self):
        """USER_GUIDE.md, "What the budget may be spent on": "Battery may charge
        the car — off: no charger is offered battery power".

        Off, the charger is offered no battery watts, in the one mode built to
        spend the pack on the car."""
        def charger(may):
            return decide(ChargerView(
                power=ChargerPower(charger_id="keba", connected=True),
                energy=ChargerEnergy(charger_id="keba"),
                mode="solar_plus_battery",
                config={"ev_min_current": 6, "ev_phases": 3,
                        "ev_voltage": 230, "ev_max_current": 32},
                fleet=FleetContext(
                    solar_w=3500.0, home_w=500.0, battery_soc=95.0,
                    battery_assist_max_power_w=4500.0,
                    battery_assist_min_surplus_w=1200.0,
                    battery_may_assist_ev=may),
            ))
        allowed = charger(True)
        assert allowed.assist_w > 0          # the pack is offered when allowed
        denied = charger(False)
        assert denied.assist_w == 0
        assert denied.budget_w < allowed.budget_w

    def test_may_not_charge_the_car_clamps_the_pack(self):
        """USER_GUIDE.md, "What the budget may be spent on": "Battery may charge
        the car — off: … while a car is plugged in the battery is held to the
        house, even when full and in the sun.\""""
        fleet = FleetContext(solar_w=5000.0, home_w=500.0, battery_soc=95.0)
        allowed = decide_battery(_view(mode="auto", soc=95.0, ev_connected=True,
                                       fleet=fleet))
        assert allowed.intent is BatteryIntent.NORMAL
        denied = decide_battery(_view(mode="auto", soc=95.0, ev_connected=True,
                                      fleet=fleet,
                                      perms={"may_assist_ev": False}))
        assert denied.intent is BatteryIntent.LIMIT_DISCHARGE
