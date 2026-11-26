"""(#1435) The sun a charger holds back for a load above it is the sun the
load pass gives that load.

Found while fixing #1434. The walk judged an idle senior load on
``solar − home``. Three parts of that figure never reach the load:

1. the pack's charge power, which the load pass hands only to a load ranked
   above a pack that yields it (#576). 5 kW sun, pack at 20 % charging 3 kW,
   a heat pump that needs 2.5 kW: SEM held 2.5 kW from the car, the heat
   pump saw 1.5 kW and stayed off, and 1.5 kW went to the grid;
2. the load pass's filter and regulation offset. The walk read each cycle's
   raw figure, so with the sun around the start bar the car's offer jumped
   between 2 kW and 0 each cycle while the load pass saw a steady figure;
3. what a charger ranked at or above the load took earlier in the loop.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    ev_reclaims_battery_charge, pack_yields_charge,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SeniorView, SurplusController, build_senior_view, compute_load_intent,
    surplus_reserved_w, tier1_battery_reserved_w,
)

CONFIG = {"battery_priority_soc": 30, "battery_buffer_soc": 50,
          "battery_assist_min_surplus": 500, "battery_assist_max_power": 3000}


def _senior(priority=1, *, rated=2500.0, name="hp", assist=False):
    return SimpleNamespace(
        device_id=name, name=name, priority=priority, is_active=False,
        battery_assist_enabled=assist, battery_eligible_overnight=False,
        rated_power=rated, min_power_threshold=0.0, _tier1_batt_w=0.0,
        control_mode="surplus", daily_max_runtime_reached=False,
        _external_off_until=None, _surplus_since=None,
        can_activate=lambda: (_ for _ in ()).throw(AssertionError("no")),
    )


def _view(soc, *, solar=5000.0, home=0.0, charge=3000.0, battery_priority=3,
          commanded=False, controller=None):
    return build_senior_view(
        CONFIG, solar_w=solar, home_w=home, charge_w=charge, soc=soc,
        battery_priority=battery_priority, battery_commanded=commanded,
        controller=controller)


def _held(devices, view, *, headroom=5000.0, below=8):
    return surplus_reserved_w(devices, below_priority=below,
                              available_w=headroom, senior=view)


# ---------------------------------------------------------------------------
# 1. The pack's charge power
# ---------------------------------------------------------------------------

def test_the_issue_case_holds_nothing():
    """Pack at 20 % (below its 30 % reserve floor) keeps its 3 kW charge.
    The heat pump gets 2 kW and cannot start: the car keeps the sun."""
    hp = _senior(priority=1, rated=2500.0)
    assert _held([hp], _view(20.0)) == 0.0
    # the old walk, on the bare headroom, held 2.5 kW
    assert surplus_reserved_w([hp], below_priority=8, available_w=5000.0) == 2500.0


def test_a_pack_that_yields_gives_its_charge_to_a_load_above_it():
    """Pack at 60 % yields its charge to a load above it (prio 1 < 3)."""
    assert _held([_senior(priority=1)], _view(60.0)) == 2500.0


def test_a_load_below_the_pack_never_gets_its_charge():
    """Same pack at 60 %, but the heat pump ranks below it (prio 4 > 3)."""
    assert _held([_senior(priority=4)], _view(60.0)) == 0.0


def test_a_commanded_or_unread_pack_keeps_its_charge():
    hp = _senior(priority=1)
    assert _held([hp], _view(60.0, commanded=True)) == 0.0
    assert _held([hp], _view(60.0, battery_priority=None)) == 0.0
    unread = build_senior_view(CONFIG, solar_w=5000.0, home_w=0.0,
                               charge_w=3000.0, soc=60.0, soc_known=False,
                               battery_priority=3)
    assert _held([hp], unread) == 0.0


def test_a_pack_charged_from_the_grid_gives_only_the_sun_part():
    """(#938) Pack at 60 % charges 3 kW, 1 kW of it from the grid (an
    inverter time window): solar 3 kW, house 1 kW. The load pass gives a
    load above the pack 2 kW, so a 2.5 kW heat pump holds nothing."""
    hp = _senior(priority=1, rated=2500.0)
    view = _view(60.0, solar=3000.0, home=1000.0, charge=3000.0)
    assert view.reclaim_w == 2000.0
    assert _held([hp], view, headroom=2000.0) == 0.0
    # all of it from the sun: 5 kW, and the heat pump holds its 2.5 kW
    assert _held([hp], _view(60.0)) == 2500.0


def test_no_charge_is_the_old_figure():
    """With the pack idle the view is the headroom, as before."""
    hp = _senior(priority=4)
    for headroom in (1000.0, 2400.0, 2500.0, 4000.0):
        view = _view(20.0, solar=headroom, charge=0.0)
        assert _held([hp], view, headroom=headroom) == surplus_reserved_w(
            [hp], below_priority=8, available_w=headroom)


def test_the_battery_axis_reads_the_same_sun():
    """A "Solar + battery" heat pump below the pack: 2 kW of sun (the 3 kW
    charge kept out) plus 400 W the pack may add cannot start 2.5 kW."""
    hp = _senior(priority=4, assist=True)
    view = SeniorView(sun_w=2000.0, reclaim_w=3000.0, battery_priority=3,
                      pack_w=400.0, pack_above_w=3000.0)
    held = tier1_battery_reserved_w([hp], below_priority=8, allowance_w=3000.0,
                                    sun_w=5000.0, pack_w=400.0, senior=view)
    assert held == 0.0
    # the old walk saw 5 kW of sun and held the pack
    assert tier1_battery_reserved_w([hp], below_priority=8, allowance_w=3000.0,
                                    sun_w=5000.0, pack_w=400.0) > 0.0


def test_pack_help_is_the_load_pass_budget_for_its_rank():
    """(#1114) Above the pack the gate counts the charge, below it does not:
    300 W of sun past a 500 W gate only with the 3 kW charge counted."""
    view = _view(60.0, solar=3300.0, charge=3000.0)
    assert view.pack_w == 0.0
    assert view.pack_above_w == 3000.0
    assert view.pack_for(_senior(priority=1)) == 3000.0
    assert view.pack_for(_senior(priority=4)) == 0.0


def test_the_pack_rule_is_the_chargers_rule():
    """One rule for the pack's side: a charger and a load ranked the same get
    the same answer."""
    for soc in (10.0, 29.9, 30.0, 80.0):
        for bp in (None, 1, 5):
            for commanded in (False, True):
                yields = pack_yields_charge(soc=soc, priority_soc=30.0,
                                            battery_priority=bp,
                                            battery_commanded=commanded)
                for rank in (0, 3, 9):
                    assert (yields and bp is not None and rank < bp) == \
                        ev_reclaims_battery_charge(
                            soc=soc, priority_soc=30.0, ev_priority=rank,
                            battery_priority=bp, battery_commanded=commanded)
    assert pack_yields_charge(soc=None, priority_soc=30.0, battery_priority=3,
                              battery_commanded=False) is False


def test_the_walk_and_the_load_pass_agree():
    """The oracle: an idle switch load is held for exactly when the load pass
    would start it on what it gets there (sun, plus the charge above a pack
    that yields it)."""
    from custom_components.solar_energy_management.devices.base import (
        DeviceControlMode, SwitchDevice,
    )
    checked = 0
    for prio in (1, 4):
        dev = SwitchDevice(MagicMock(), "hp", "Heat pump", rated_power=2500.0,
                           entity_id="switch.hp")
        dev.control_mode = DeviceControlMode.SURPLUS
        dev.priority = prio
        for soc in (20.0, 60.0):
            for solar in range(0, 6001, 250):
                view = _view(soc, solar=float(solar), charge=1500.0)
                pool = max(0.0, solar - 1500.0)
                if soc >= 30.0 and prio < 3:
                    pool += min(1500.0, solar)   # the load pass's reclaim
                starts = compute_load_intent(
                    dev, remaining_surplus_w=pool, tier1_headroom_w=0.0,
                    is_night=False).on
                held = _held([dev], view, headroom=float(solar))
                assert (held > 0.0) == starts, (prio, soc, solar, held)
                checked += starts
    assert checked > 0, "the sweep never reached a start"


# ---------------------------------------------------------------------------
# 2. The load pass's filter and offset
# ---------------------------------------------------------------------------

def test_noise_around_the_bar_does_not_flip_the_hold():
    """Sun alternates 2.5 kW / 2.7 kW each cycle around a 2.5 kW heat pump
    (with the 50 W offset). Raw, the hold flips every cycle; through the
    load pass's filter it settles and stays."""
    sc = SurplusController(MagicMock(), regulation_offset=50)
    hp = _senior(priority=1, rated=2500.0)
    raw, filtered = [], []
    for n in range(30):
        sun = 2500.0 if n % 2 == 0 else 2700.0
        raw.append(_held([hp], SeniorView(sun_w=sun - 50.0), headroom=sun) > 0)
        view = build_senior_view(CONFIG, solar_w=sun, home_w=0.0, charge_w=0.0,
                                 soc=None, controller=sc)
        filtered.append(_held([hp], view, headroom=sun) > 0)
    flips = sum(a != b for a, b in zip(raw[10:], raw[11:], strict=False))
    assert flips >= 15
    assert all(filtered[10:]), filtered


def test_one_bad_sample_does_not_move_the_hold():
    """The median of three: one cycle of 0 W does not let go."""
    sc = SurplusController(MagicMock(), regulation_offset=50)
    hp = _senior(priority=1, rated=2500.0)
    for n in range(20):
        sun = 0.0 if n == 12 else 4000.0
        view = build_senior_view(CONFIG, solar_w=sun, home_w=0.0, charge_w=0.0,
                                 soc=None, controller=sc)
        if n >= 3:
            assert _held([hp], view, headroom=4000.0) == 2500.0, n


def test_the_offset_is_the_load_pass_offset():
    """At the bar the load pass needs the bar past its 50 W offset; so does
    the walk. With the export sink closed there is no offset (#871)."""
    hp = _senior(priority=1, rated=2500.0)
    for closed, held in ((False, 0.0), (True, 2500.0)):
        sc = SurplusController(MagicMock(), regulation_offset=50)
        view = build_senior_view(CONFIG, solar_w=2520.0, home_w=0.0,
                                 charge_w=0.0, soc=None, grid_closed=closed,
                                 controller=sc)
        assert _held([hp], view, headroom=2520.0) == held


def test_a_load_switching_on_does_not_lag_the_hold():
    """Solar 5.5 kW. Heat pump 1 (prio 1, 2.5 kW) starts; heat pump 2
    (prio 2, 3.2 kW) is idle. The load pass gives heat pump 2
    5.5 − 0.05 − 2.5 = 2.95 kW from the first cycle on, so it holds nothing
    from the car. The filter reads the loads' draw added back, so the start
    does not move it."""
    sc = SurplusController(MagicMock(), regulation_offset=50)
    hp1 = _senior(priority=1, rated=2500.0, name="hp1")
    hp2 = _senior(priority=2, rated=3200.0, name="hp2")
    draw = {"w": 0.0}
    sc.active_surplus_draw_w = lambda: draw["w"]
    for n in range(20):
        if n == 10:                       # heat pump 1 starts
            draw["w"] = 2500.0
            hp1.is_active = True
            hp1.get_current_consumption = lambda: 2500.0
        view = build_senior_view(CONFIG, solar_w=5500.0, home_w=draw["w"],
                                 charge_w=0.0, soc=None, controller=sc)
        held = _held([hp1, hp2], view, headroom=5500.0 - draw["w"], below=5)
        if n >= 10:
            assert held == 0.0, (n, held)
    assert sc._senior_filter.value == 5500.0


def test_an_expensive_hour_damps_the_walk_as_it_damps_the_load_pass():
    """(#953) With price response on, an expensive hour takes 500 W off the
    load pass's pool: 2.8 kW of sun no longer starts a 2.5 kW heat pump."""
    hp = _senior(priority=1, rated=2500.0)
    for level, held in (("expensive", 0.0), ("normal", 2500.0)):
        sc = SurplusController(MagicMock(), regulation_offset=50)
        sc.price_responsive_mode = True
        view = build_senior_view(CONFIG, solar_w=2800.0, home_w=0.0,
                                 charge_w=0.0, soc=None, price_level=level,
                                 controller=sc)
        assert _held([hp], view, headroom=2800.0) == held, level


def test_the_load_pass_filter_is_unchanged():
    """``PoolFilter`` is the load pass's old median of three and average."""
    sc = SurplusController(MagicMock(), regulation_offset=0)
    samples = [1000.0, 3000.0, 0.0, 2000.0, 2500.0, 100.0, 4000.0]
    smoothed, kept = None, []
    for x in samples:
        kept = (kept + [x])[-3:]
        f = sorted(kept)[1] if len(kept) == 3 else x
        smoothed = f if smoothed is None else 0.3 * f + 0.7 * smoothed
        sc._surplus_filter.update(x)
        assert sc._smoothed_surplus == smoothed
    assert sc._surplus_samples == samples[-3:]


# ---------------------------------------------------------------------------
# 3. A charger ranked above the load already took it
# ---------------------------------------------------------------------------

def test_sun_a_senior_charger_took_is_not_the_loads():
    """Charger A (prio 2) took 3 kW of 5 kW. The heat pump (prio 5) gets
    2 kW and cannot start: charger B (prio 8) must not be held back."""
    hp = _senior(priority=5, rated=2500.0)
    view = SeniorView(sun_w=5000.0, taken=((2, 3000.0, 0.0),))
    assert _held([hp], view) == 0.0
    # a charger ranked below the heat pump held its share: not subtracted
    view = SeniorView(sun_w=5000.0, taken=((6, 3000.0, 0.0),))
    assert _held([hp], view) == 2500.0


def test_pack_a_senior_charger_took_is_not_the_loads():
    hp = _senior(priority=5, rated=2500.0, assist=True)
    view = SeniorView(sun_w=1000.0, pack_w=2000.0, taken=((2, 0.0, 1500.0),))
    assert view.pack_for(hp) == 500.0
    assert tier1_battery_reserved_w([hp], below_priority=8, allowance_w=3000.0,
                                    senior=view) == 0.0
    view = SeniorView(sun_w=1000.0, pack_w=2000.0)
    assert tier1_battery_reserved_w([hp], below_priority=8, allowance_w=3000.0,
                                    senior=view) > 0.0


def test_the_loop_hands_both_walks_the_view_and_records_each_take():
    """Both walks get ``senior`` with this cycle's takes, and each charger's
    take is recorded by its rank (AST, not text)."""
    import ast
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    from .ast_contracts import _tree_of, call_kwargs
    loop = SEMCoordinator._async_update_data
    tree = _tree_of(loop)
    for name in ("_surplus_reserved_w", "_tier1_reserved_w"):
        calls = call_kwargs(loop, name)
        assert calls and all("senior" in kw for kw in calls), name
        # …with this cycle's takes in it
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call)
                    and getattr(n.func, "id", getattr(n.func, "attr", None)) == name):
                senior = next(k.value for k in n.keywords if k.arg == "senior")
                assert isinstance(senior, ast.Call) and "taken" in {
                    k.arg for k in senior.keywords}, name
    # one view and one reset per cycle: both before the charger loop
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and isinstance(n.iter, ast.Name) and n.iter.id == "sorted_chargers"]
    assert loops
    for for_node in loops:
        inside = list(ast.walk(for_node))
        assert not any(
            isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", None)) == "build_senior_view"
            for n in inside), "the view is built per charger: one filter sample each"
        assert not any(
            isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == "_charger_takes_per_cycle"
                for t in n.targets)
            for n in inside), "the takes are reset inside the loop"
    appends = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "append"
        and isinstance(n.func.value, ast.Attribute)
        and n.func.value.attr == "_charger_takes_per_cycle"
    ]
    assert appends, "no charger take is recorded"
    builds = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", getattr(n.func, "attr", None)) == "build_senior_view"
    ]
    assert builds and all(
        {"charge_w", "battery_priority", "battery_commanded", "controller"}
        <= {kw.arg for kw in b.keywords} for b in builds)
