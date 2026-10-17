"""The EV mode table, as behaviour tests (#1112).

``docs/EV_CHARGING_LOGIC.md`` was written from the code, and each test below
quotes one sentence of it and drives the REAL decision path to check it:
``build_charger_view`` (the coordinator's own seam, permissions and config
resolution included) → ``decide`` for the charger, and ``decide_battery`` for
the pack's side of the same cycle. No source strings, no global state.

A row the owner may want to change is still a test of today's behaviour;
its docstring says "edge case — open for discussion" and names the issue.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.consts.ev_charge_modes import (
    mode_allows_night_charging,
)
from custom_components.solar_energy_management.coordinator.build_view import (
    build_charger_view,
)
from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    Action,
    ActionKind,
    ChargerReconciler,
    ObservedState,
    desired_from_decision,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    ChargerIntent,
    FleetCycleState,
)
from custom_components.solar_energy_management.coordinator.decide import decide
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    REDIRECT_VETO_STRIKES,
)
from custom_components.solar_energy_management.coordinator.per_charger_context import (
    PerChargerState,
    note_redirect_outcome,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    NO_OPINION,
    PlanVerdict,
)

DOC = "docs/EV_CHARGING_LOGIC.md"
CID = "keba"
PHASES, VOLTS = 3, 230
WPA = PHASES * VOLTS                 # 690 W per amp, 6 A ≈ 4140 W
BUFFER, AUTO_START, PRIORITY = 70.0, 90.0, 30.0
GATE_W, ASSIST_MAX_W = 1200.0, 4500.0

SOLAR_ONLY = "solar_only"
SOLAR_BATT = "solar_plus_battery"
SOLAR_CHEAP = "solar_plus_cheap"
MIN_SOLAR = "min_plus_solar"
ALWAYS_MAX = "always_max"
OFF = "off"


def _config(**extra) -> dict:
    """The install-wide config, as a fresh install carries it."""
    cfg = {
        "ev_min_current": 6, "ev_phases": PHASES, "ev_voltage": VOLTS,
        "ev_max_current": 32,
        "minimum_solar_power": 1000,
        "battery_buffer_soc": BUFFER,
        "battery_auto_start_soc": AUTO_START,
        "battery_priority_soc": PRIORITY,
        "battery_assist_max_power": ASSIST_MAX_W,
        "battery_assist_min_surplus": GATE_W,
        "battery_capacity_kwh": 15,
    }
    cfg.update(extra)
    return cfg


def _view(mode, *, solar=0.0, home=500.0, charge=0.0, soc=50.0,
          night=False, tariff=None, target_kwh=None, connected=True,
          charging=False, power_w=0.0, config=None, charger_cfg=None,
          plan=NO_OPINION, deadline_amps=0, spendable=0.0, dyn_floor=None,
          battery_commanded=False, forecast_kwh=0.0, redirect_allowed=True):
    """One charger's view, built through the coordinator's own seam."""
    grid = solar - home - charge - power_w
    power = SimpleNamespace(
        solar_power=solar, home_consumption_power=home,
        battery_charge_power=charge, battery_discharge_power=0.0,
        battery_soc=soc, battery_soc_known=True,
        grid_import_power=max(0.0, -grid), grid_export_power=max(0.0, grid),
        ev_power=power_w, ev_connected=connected, ev_charging=charging,
    )
    fleet_state = FleetCycleState(
        power=power, config=config if config is not None else _config(),
        is_night=night, tariff_level=tariff,
        battery_spendable_kwh=spendable, dynamic_floor_pct=dyn_floor,
        forecast_remaining_kwh=forecast_kwh,
        battery_commanded=battery_commanded,
    )
    return build_charger_view(
        fleet_state, charger_id=CID, charger_cfg=charger_cfg or {},
        mode=mode, daily_ev_kwh=0.0, target_kwh=target_kwh, plan=plan,
        deadline_amps=deadline_amps, redirect_allowed=redirect_allowed,
    )


def _commanded_w(d) -> float:
    if d.intent is ChargerIntent.CHARGE_MAX:
        return float("inf")
    if d.intent is ChargerIntent.CHARGE_AT_AMPS:
        return float(d.commanded_amps) * WPA
    return 0.0


def _pack_side(*, solar, home, soc, spending=False, spendable=0.0,
               ev_wants_pack=False):
    """The battery's decision in the same cycle, a car plugged in."""
    from custom_components.solar_energy_management.coordinator.charger_types import (
        FleetContext,
    )
    fleet = FleetContext(solar_w=solar, home_w=home, battery_soc=soc,
                         buffer_soc=BUFFER, auto_start_soc=AUTO_START,
                         priority_soc=PRIORITY,
                         battery_assist_min_surplus_w=GATE_W)
    return decide_battery(BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config={"battery_max_discharge_power": 5000,
                "battery_max_charge_power_w": 5000,
                "battery_mode": "auto", "battery_reserve_soc": 20},
        fleet=fleet, charging_state="night_charging_active",
        ev_charging=True, ev_connected=True, home_consumption_w=home,
        forecast_spending_enabled=spending, battery_spendable_kwh=spendable,
        ev_wants_pack=ev_wants_pack,
    ))


# ── Solar only ──────────────────────────────────────────────────────────


class TestSolarOnly:
    @pytest.mark.parametrize("solar", [1500.0, 3000.0, 4500.0, 6000.0, 9000.0])
    def test_never_grids_by_day(self, solar):
        """"| **Solar only** | Never by day. […] | Charges on spare sun
        only." — docs/EV_CHARGING_LOGIC.md — The five charge
        modes. No floor set: whatever the sun, the offer never exceeds the
        surplus, so the grid pays nothing."""
        d = decide(_view(SOLAR_ONLY, solar=solar, home=500.0, soc=50.0))
        assert _commanded_w(d) <= solar - 500.0, d.reason
        if solar - 500.0 < 6 * WPA:
            assert d.intent is ChargerIntent.IDLE, d.reason
        else:
            assert d.intent is ChargerIntent.CHARGE_AT_AMPS, d.reason

    def test_never_discharges_the_pack_for_the_car(self):
        """"| **Solar only** | … | Never discharges for the car, with one
        exception: forecast spending […] |" and
        "*not* Solar only, which never discharges the pack for the car" —
        docs/EV_CHARGING_LOGIC.md — The five charge modes / Battery-assist.
        A full pack and 2.5 kW of sun: Solar only waits; Solar + battery,
        same cycle, takes the pack (so the situation can use it)."""
        d = decide(_view(SOLAR_ONLY, solar=3000.0, home=500.0, soc=100.0))
        assert d.intent is ChargerIntent.IDLE, d.reason
        assert d.assist_w == 0.0
        other = decide(_view(SOLAR_BATT, solar=3000.0, home=500.0, soc=100.0))
        assert other.intent is ChargerIntent.CHARGE_AT_AMPS, other.reason
        assert other.assist_w > 0.0

    def test_idles_at_night_with_the_pack_full(self):
        """"| **Solar only** | … | Charges on spare sun only. Idles at night
        unless you set a floor. |"
        — docs/EV_CHARGING_LOGIC.md — The five charge modes. Night, pack at
        100 %, no floor set on the charger: no night lane, no charge."""
        assert not mode_allows_night_charging(
            _config(daily_ev_target=10), {"id": CID, "charge_mode": SOLAR_ONLY})
        d = decide(_view(SOLAR_ONLY, night=True, soc=100.0))
        assert d.intent is ChargerIntent.IDLE, d.reason
        assert _commanded_w(d) == 0.0

    def test_a_floor_tops_up_from_grid_not_the_pack(self):
        """"| **Solar only** | Never by day. At night only if *you* set a
        floor on this charger | Never discharges for the car […] |" — docs/EV_CHARGING_LOGIC.md — The five
        charge modes. With a floor the night top-up runs; the pack, full,
        is held back so the grid pays, not the battery."""
        d = decide(_view(SOLAR_ONLY, night=True, soc=100.0, target_kwh=5.0,
                         charger_cfg={"daily_ev_target": 5}))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS, d.reason
        pack = _pack_side(solar=0.0, home=500.0, soc=100.0)
        assert pack.intent is BatteryIntent.LIMIT_DISCHARGE, pack.reason
        assert pack.discharge_limit_w <= 500.0

    def test_forecast_spending_lets_the_pack_cover_a_solar_only_car(self):
        """"With forecast spending on and a positive budget for tonight, SEM
        no longer holds the home battery back while a Solar-only car charges
        on its floor." — docs/EV_CHARGING_LOGIC.md — Solar only and forecast
        spending (#1115).

        Edge case — open for discussion, see #1115.

        Night, pack full, 3 kWh budget, no Solar + battery charger plugged
        in: the car charges on its floor and the pack is not held back."""
        d = decide(_view(SOLAR_ONLY, night=True, soc=100.0, target_kwh=5.0,
                         spendable=3.0,
                         config=_config(forecast_spending_enabled=True),
                         charger_cfg={"daily_ev_target": 5}))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS, d.reason
        pack = _pack_side(solar=0.0, home=500.0, soc=100.0, spending=True,
                          spendable=3.0, ev_wants_pack=False)
        assert pack.intent is BatteryIntent.NORMAL, pack.reason
        held = _pack_side(solar=0.0, home=500.0, soc=100.0, spending=False,
                          spendable=3.0, ev_wants_pack=False)
        assert held.intent is BatteryIntent.LIMIT_DISCHARGE, held.reason

    def test_the_spending_still_stops_at_the_buffer(self):
        """"The battery may then cover the car, down to the Buffer SoC or
        tonight's floor, whichever is higher." — docs/EV_CHARGING_LOGIC.md —
        Solar only and forecast spending (#1115)."""
        pack = _pack_side(solar=0.0, home=500.0, soc=BUFFER - 5,
                          spending=True, spendable=3.0)
        assert pack.intent is BatteryIntent.LIMIT_DISCHARGE, pack.reason

    def test_a_global_default_floor_does_not_opt_it_in(self):
        """"A global default value in Setup does **not** opt a Solar-only
        charger in … The other night-capable modes do follow the global" —
        docs/EV_CHARGING_LOGIC.md — Solar only and the overnight floor
        (#679)."""
        seeded = _config(daily_ev_target=10, ev_target_soc=80)
        assert not mode_allows_night_charging(
            seeded, {"id": CID, "charge_mode": SOLAR_ONLY})
        assert mode_allows_night_charging(
            seeded, {"id": CID, "charge_mode": SOLAR_ONLY, "daily_ev_target": 5})
        assert mode_allows_night_charging(
            seeded, {"id": CID, "charge_mode": MIN_SOLAR})


# ── #680: floor 0 means no overnight charge ────────────────────────────


@pytest.mark.parametrize("mode", [SOLAR_ONLY, SOLAR_BATT, MIN_SOLAR, SOLAR_CHEAP])
def test_floor_zero_means_no_overnight_charge(mode):
    """"**a floor of 0 means no overnight charge** in every mode except
    **Always (max)**" — docs/EV_CHARGING_LOGIC.md — Turning overnight
    charging off (#680). Night, a full pack, nothing owed: idle."""
    d = decide(_view(mode, night=True, soc=100.0, target_kwh=0.0,
                     tariff="very_cheap"))
    assert d.intent is ChargerIntent.IDLE, d.reason


# ── Solar + battery ────────────────────────────────────────────────────


class TestSolarPlusBattery:
    def test_assists_above_the_buffer(self):
        """"| **Solar + battery** | … | Assists down to **max(Buffer SoC,
        tonight's computed floor)** — above the Solar Gate always" —
        docs/EV_CHARGING_LOGIC.md — The five charge modes."""
        d = decide(_view(SOLAR_BATT, solar=3000.0, home=500.0, soc=85.0))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS, d.reason
        assert d.assist_w > 0.0

    def test_stops_at_the_buffer(self):
        """"Assists down to **max(Buffer SoC, tonight's computed floor)**"
        — docs/EV_CHARGING_LOGIC.md — The five charge modes. Below the
        buffer the pack gives the car nothing."""
        d = decide(_view(SOLAR_BATT, solar=3000.0, home=500.0, soc=BUFFER - 5))
        assert d.assist_w == 0.0
        assert d.intent is ChargerIntent.IDLE, d.reason

    def test_stops_at_tonights_floor_above_the_buffer(self):
        """"Assists down to **max(Buffer SoC, tonight's computed floor)**"
        — docs/EV_CHARGING_LOGIC.md — The five charge modes. SOC 78 % sits
        above the 70 % buffer but below tonight's 82 % floor."""
        held = decide(_view(SOLAR_BATT, solar=3000.0, home=500.0, soc=78.0,
                            dyn_floor=82.0, spendable=2.0))
        assert held.assist_w == 0.0, held.reason
        free = decide(_view(SOLAR_BATT, solar=3000.0, home=500.0, soc=78.0))
        assert free.assist_w > 0.0, free.reason

    def test_below_the_gate_only_with_a_budget_tonight(self):
        """"above the Solar Gate always, and below it when tonight's
        forecast budget is positive" — docs/EV_CHARGING_LOGIC.md — The five
        charge modes. 1 kW surplus is under the 1.2 kW gate."""
        none = decide(_view(SOLAR_BATT, solar=1500.0, home=500.0, soc=85.0))
        assert none.assist_w == 0.0, none.reason
        some = decide(_view(SOLAR_BATT, solar=1500.0, home=500.0, soc=85.0,
                            spendable=3.0))
        assert some.assist_w > 0.0, some.reason

    @pytest.mark.parametrize("solar,soc", [(3000.0, 85.0), (1500.0, 85.0),
                                           (3000.0, 60.0), (8000.0, 95.0)])
    def test_never_grids_by_day(self, solar, soc):
        """"| **Solar + battery** | Never by day. […] |" —
        docs/EV_CHARGING_LOGIC.md — The five charge modes. The offer never
        exceeds the sun's surplus plus the pack's allowance."""
        d = decide(_view(SOLAR_BATT, solar=solar, home=500.0, soc=soc))
        assert _commanded_w(d) <= (solar - 500.0) + ASSIST_MAX_W, d.reason
        assert _commanded_w(d) <= d.budget_w or d.intent is ChargerIntent.IDLE

    def test_idles_at_night(self):
        """"Spare sun plus the pack […] Idles at night unless you set a
        floor." —
        docs/EV_CHARGING_LOGIC.md — The five charge modes. A full pack and
        no floor: nothing at night."""
        assert not mode_allows_night_charging(
            _config(daily_ev_target=10), {"id": CID, "charge_mode": SOLAR_BATT})
        d = decide(_view(SOLAR_BATT, night=True, soc=100.0, spendable=5.0))
        assert d.intent is ChargerIntent.IDLE, d.reason


# ── Solar + cheapest hours ─────────────────────────────────────────────


class TestSolarPlusCheapestHours:
    @pytest.mark.parametrize("level,charges", [
        ("negative", True), ("very_cheap", True), ("cheap", True),
        ("normal", False), ("expensive", False), ("very_expensive", False),
        (None, False), ("flat", False), ("no_prices", False),
    ])
    def test_grids_only_in_a_cheap_hour(self, level, charges):
        """"| **Solar + cheapest hours** | Only in cheap-price hours, up to
        the floor |" and
        "A static tariff (no live price level) never triggers it." —
        docs/EV_CHARGING_LOGIC.md — The five charge modes / Cheapest hours.
        Day, no sun, 8 kWh still owed."""
        d = decide(_view(SOLAR_CHEAP, solar=0.0, tariff=level, target_kwh=8.0))
        if charges:
            assert d.intent is ChargerIntent.CHARGE_AT_AMPS, d.reason
        else:
            assert d.intent is ChargerIntent.IDLE, d.reason

    def test_waits_for_the_plans_block_at_night(self):
        """"| Night | tariff-aware modes | Waits for the energy plan's charge
        block" — docs/EV_CHARGING_LOGIC.md — Cheapest hours."""
        hold = PlanVerdict(hold=True, reason="cheaper block at 02:00")
        d = decide(_view(SOLAR_CHEAP, night=True, target_kwh=8.0, plan=hold))
        assert d.intent is ChargerIntent.IDLE, d.reason
        go = decide(_view(SOLAR_CHEAP, night=True, target_kwh=8.0))
        assert go.intent is ChargerIntent.CHARGE_AT_AMPS, go.reason

    @pytest.mark.parametrize("level", ["normal", "cheap"])
    def test_never_uses_the_pack(self, level):
        """"| **Solar + cheapest hours** | Only in cheap-price hours, up to
        the floor | Never |" — docs/EV_CHARGING_LOGIC.md — The five charge modes. A full
        pack and 2.5 kW of sun: no battery share in any offer."""
        d = decide(_view(SOLAR_CHEAP, solar=3000.0, home=500.0, soc=100.0,
                         tariff=level, target_kwh=8.0))
        assert d.assist_w == 0.0, d.reason
        if level == "normal":
            assert d.intent is ChargerIntent.IDLE, d.reason


# ── Min + Solar ─────────────────────────────────────────────────────────


class TestMinPlusSolar:
    def test_grids_up_to_the_min_and_no_further(self):
        """"| **Min + Solar** *(default)* | Up to the floor (*At least X*) |
        … Nothing owed → no grid." —
        docs/EV_CHARGING_LOGIC.md — The five charge modes. Night: 4 kWh
        owed → the minimum current; nothing owed → idle."""
        owed = decide(_view(MIN_SOLAR, night=True, target_kwh=4.0))
        assert owed.intent is ChargerIntent.CHARGE_AT_AMPS, owed.reason
        assert owed.commanded_amps == 6
        met = decide(_view(MIN_SOLAR, night=True, target_kwh=0.0))
        assert met.intent is ChargerIntent.IDLE, met.reason
        day = decide(_view(MIN_SOLAR, solar=2000.0, home=500.0, soc=50.0,
                           target_kwh=0.0))
        assert day.intent is ChargerIntent.IDLE, day.reason

    def test_meets_the_charge_by_deadline(self):
        """"Tops up to *At least X kWh* by the *Charge by* deadline" —
        docs/EV_CHARGING_LOGIC.md — The five charge modes. The planner says
        16 A are needed to make it: the decision gives at least that."""
        d = decide(_view(MIN_SOLAR, night=True, target_kwh=20.0,
                         deadline_amps=16))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS, d.reason
        assert d.commanded_amps >= 16

    def test_assists_above_the_buffer_only(self):
        """"| **Min + Solar** | … | Assists above the Buffer SoC |" —
        docs/EV_CHARGING_LOGIC.md — The five charge modes."""
        above = decide(_view(MIN_SOLAR, solar=3000.0, home=500.0, soc=85.0))
        assert above.assist_w > 0.0, above.reason
        below = decide(_view(MIN_SOLAR, solar=3000.0, home=500.0, soc=BUFFER - 5))
        assert below.assist_w == 0.0, below.reason


# ── Always (max) and Off ───────────────────────────────────────────────


def test_always_max_ignores_solar_tariff_and_night():
    """"| **Always (max)** | … | Charges at the charger's maximum whenever a
    car is plugged in, day or night, at any price." —
    docs/EV_CHARGING_LOGIC.md — The five charge modes."""
    d = decide(_view(ALWAYS_MAX, night=True, solar=0.0, soc=20.0,
                     tariff="very_expensive", target_kwh=4.0))
    assert d.intent is ChargerIntent.CHARGE_MAX, d.reason


def test_always_max_ignores_a_zero_floor():
    """"The floor does not matter here: a floor of 0 does **not** stop it."
    — docs/EV_CHARGING_LOGIC.md — The five charge modes.

    Edge case — open for discussion, see #1113: the #680 note says a 0 floor
    means no overnight charge, and Always (max) is the one mode it does not
    reach."""
    d = decide(_view(ALWAYS_MAX, night=True, soc=100.0, target_kwh=0.0))
    assert d.intent is ChargerIntent.CHARGE_MAX, d.reason


def test_always_max_stops_at_the_ceiling():
    """"It stops at the *Up to* ceiling" — docs/EV_CHARGING_LOGIC.md — The
    five charge modes."""
    fleet = FleetCycleState(
        power=SimpleNamespace(
            solar_power=0.0, home_consumption_power=500.0,
            battery_charge_power=0.0, battery_discharge_power=0.0,
            battery_soc=50.0, battery_soc_known=True,
            grid_import_power=500.0, grid_export_power=0.0, ev_power=0.0,
            ev_connected=True, ev_charging=False),
        config=_config(), is_night=True, tariff_level=None)
    view = build_charger_view(
        fleet, charger_id=CID, charger_cfg={}, mode=ALWAYS_MAX,
        daily_ev_kwh=0.0, target_kwh=None, plan=NO_OPINION,
        soc_ceiling_reached=True)
    assert decide(view).intent is ChargerIntent.IDLE


def test_always_max_holds_the_pack_without_spare_sun():
    """"| **Always (max)** | … | Held to the house unless the pack is above
    the Buffer SoC and the spare sun passes the Solar Gate |" —
    docs/EV_CHARGING_LOGIC.md — The five charge modes. Night, pack full,
    a car plugged in: the pack is held to the house, the grid pays."""
    pack = _pack_side(solar=0.0, home=500.0, soc=100.0)
    assert pack.intent is BatteryIntent.LIMIT_DISCHARGE, pack.reason
    assert pack.discharge_limit_w <= 500.0


def _off_reconciler():
    return ChargerReconciler(charger_id=CID, heartbeat_s=5.0,
                             idle_disable_threshold=4)


def test_off_sends_nothing_to_the_charger():
    """"After that SEM sends nothing: no start, no stop, no current." and
    "A charge you start elsewhere in Home Assistant afterwards runs
    untouched, also after a restart" — docs/EV_CHARGING_LOGIC.md — The five
    charge modes / Charge mode Off is hands-off (#898). SEM starts up in
    Off with a car someone else started and a big sun: nothing, cycle after
    cycle."""
    d = decide(_view(OFF, solar=8000.0, connected=True, charging=True,
                     power_w=4000.0))
    assert d.intent is ChargerIntent.RELEASE, d.reason
    assert d.commanded_amps == 0
    desired, amps = desired_from_decision(d)
    rec = _off_reconciler()
    seen = ObservedState(charging=True, setpoint_a=0, self_charging=False,
                         power_w=4000.0, connected=True)
    for cycle in range(60):
        assert rec.reconcile(desired, amps, seen, now=cycle * 10.0) == [
            Action(ActionKind.NONE)], f"cycle {cycle}"


def test_switching_to_off_stops_once():
    """"Switching to Off stops a running charge **once**, whoever started
    it. After that SEM sends nothing" — docs/EV_CHARGING_LOGIC.md — The five
    charge modes. A charge is running; the mode moves to Off: one stop,
    then silence while the car keeps drawing."""
    rec = _off_reconciler()
    seen = ObservedState(charging=True, setpoint_a=0, self_charging=True,
                         power_w=4000.0, connected=True)
    idle, idle_a = desired_from_decision(decide(_view(
        SOLAR_ONLY, solar=0.0, connected=True, charging=True)))
    rec.reconcile(idle, idle_a, seen, now=0.0)
    off, off_a = desired_from_decision(decide(_view(
        OFF, connected=True, charging=True, power_w=4000.0)))
    first = rec.reconcile(off, off_a, seen, now=10.0)
    assert Action(ActionKind.DISABLE) in first
    for cycle in range(2, 60):
        acts = rec.reconcile(off, off_a, seen, now=cycle * 10.0)
        assert all(a.kind is not ActionKind.DISABLE for a in acts), cycle
        assert all(a.kind is not ActionKind.ENABLE for a in acts), cycle


# ── #899: the battery redirect ─────────────────────────────────────────


class TestTheRedirect:
    """koen71's afternoon: 3.8 kW sun, 1.1 kW house, the pack taking 2.7 kW,
    a one-phase car. The redirect is the only thing that can start it."""

    def _v(self, **kw):
        return _view(SOLAR_ONLY, solar=3800.0, home=1100.0, charge=2700.0,
                     soc=60.0, forecast_kwh=30.0,
                     charger_cfg={"ev_phases": 1, "ev_max_current": 16}, **kw)

    def test_a_commanded_pack_is_never_credited(self):
        """"A commanded pack (forced / scheduled charge) is never credited"
        — docs/EV_CHARGING_LOGIC.md — `solar_only` and the battery
        "redirect" (#899)."""
        d = decide(self._v(battery_commanded=True))
        assert d.intent is ChargerIntent.IDLE, d.reason
        assert d.redirect_w == 0.0
        free = decide(self._v())
        assert free.intent is ChargerIntent.CHARGE_AT_AMPS, free.reason

    def test_three_cycles_of_import_veto_it_for_the_plug_in(self):
        """"three cycles of sustained grid import with a redirect in the
        budget veto it for the rest of the plug-in" —
        docs/EV_CHARGING_LOGIC.md — `solar_only` and the battery "redirect"
        (#899)."""
        st = PerChargerState()
        for _ in range(REDIRECT_VETO_STRIKES):
            note_redirect_outcome(st, redirect_w=1500.0, grid_import_w=2000.0,
                                  charging=True)
        assert st.redirect_vetoed
        d = decide(self._v(redirect_allowed=not st.redirect_vetoed))
        assert d.intent is ChargerIntent.IDLE, d.reason


# ── Battery may assist this charger ────────────────────────────────────


class TestBatteryMayAssistThisCharger:
    """"| **Battery may assist this charger** | … Defaults on, inherits the
    install-wide battery permission, and can only *restrict* — it never
    overrides a battery you have declared off-limits to cars." —
    docs/EV_CHARGING_LOGIC.md — Battery-assist."""

    def _assist(self, *, config=None, charger_cfg=None):
        d = decide(_view(MIN_SOLAR, solar=3000.0, home=500.0, soc=85.0,
                         config=config, charger_cfg=charger_cfg))
        return d.assist_w

    def test_defaults_on(self):
        """"Defaults on" — docs/EV_CHARGING_LOGIC.md — Battery-assist."""
        assert self._assist() > 0.0

    def test_off_on_this_charger_restricts(self):
        """"Excludes a single charger from the pack." —
        docs/EV_CHARGING_LOGIC.md — Battery-assist."""
        assert self._assist(charger_cfg={"ev_battery_may_assist": False}) == 0.0

    def test_on_never_overrides_an_install_that_said_no(self):
        """"it never overrides a battery you have declared off-limits to
        cars" — docs/EV_CHARGING_LOGIC.md — Battery-assist."""
        cfg = _config(battery_permissions={"may_assist_ev": False})
        assert self._assist(config=cfg,
                            charger_cfg={"ev_battery_may_assist": True}) == 0.0
