"""(#1434) An idle senior load holds back only sun it can start with.

Found live on the .175 rig (26.11): a heat pump at the top of the device list,
in Surplus mode, rated 2.0 kW and idle, reserved all 900 W of spare sun. It can
never start on 900 W, so it stayed off, every junior (a car in Sun + tariff
among them) saw 0 W, and the sun was exported.
"""
from types import SimpleNamespace
from datetime import datetime

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    surplus_reserved_w,
)


def _senior(priority=1, *, rated=2000.0, min_w=0.0, active=False,
            dwell=None, name="hp"):
    return SimpleNamespace(
        device_id=name, name=name, priority=priority, is_active=active,
        battery_assist_enabled=False, battery_eligible_overnight=False,
        rated_power=rated, min_power_threshold=min_w, _tier1_batt_w=0.0,
        control_mode="surplus", daily_max_runtime_reached=False,
        _external_off_until=None, _surplus_since=dwell,
        can_activate=lambda: (_ for _ in ()).throw(AssertionError("no")),
    )


def _reserve(devices, available, below=8):
    return surplus_reserved_w(devices, below_priority=below, available_w=available)


def test_the_rig_case_reserves_nothing():
    """Heat pump needs 2000 W to start, 900 W is spare: hold back nothing."""
    assert _reserve([_senior(rated=2000.0)], 900.0) == 0.0


def test_enough_to_start_still_reserves():
    assert _reserve([_senior(rated=2000.0)], 2500.0) == 2000.0


def test_just_at_the_threshold_reserves():
    assert _reserve([_senior(rated=2000.0)], 2000.0) == 2000.0


def test_the_start_threshold_wins_over_the_rating():
    """A modulating load that starts at 800 W reserves on 900 W of sun."""
    assert _reserve([_senior(rated=2000.0, min_w=800.0)], 900.0) == 900.0


def test_a_running_senior_still_reserves_nothing_on_the_solar_axis():
    assert _reserve([_senior(rated=2000.0, active=True)], 900.0) == 0.0


def test_a_senior_waiting_on_its_start_delay_keeps_its_claim():
    """The reservation exists to protect a senior about to start: one whose
    sustained-surplus clock already runs keeps its claim, so a junior cannot
    take the sun during the senior's debounce."""
    assert _reserve([_senior(rated=2000.0, dwell=datetime.now())], 900.0) == 900.0


def test_two_seniors_each_judged_on_what_is_left():
    small = _senior(priority=1, rated=600.0, name="plug")
    big = _senior(priority=2, rated=2000.0, name="hp")
    # 600 W reserved for the plug; 300 W left cannot start the heat pump.
    assert _reserve([small, big], 900.0) == 600.0
    # Plenty: both reserve.
    assert _reserve([small, big], 3000.0) == 2600.0


def test_flapping_around_the_threshold_is_monotonic():
    """More sun never means less for the senior: the reservation does not
    jump back and forth between two values while the sun only grows."""
    seen = [_reserve([_senior(rated=2000.0)], w) for w in range(1500, 2600, 50)]
    for a, b in zip(seen, seen[1:], strict=False):
        assert b >= a


# ---------------------------------------------------------------------------
# Round 2 — the walk asks the load pass's own start question
# ---------------------------------------------------------------------------

def _tier1_reserve(devices, *, sun=None, pack=None, allowance=5000.0, below=8):
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        tier1_battery_reserved_w,
    )
    return tier1_battery_reserved_w(devices, below_priority=below,
                                    allowance_w=allowance, sun_w=sun, pack_w=pack)


def _t1(**kw):
    """A "Solar + battery" senior."""
    dev = _senior(**kw)
    dev.battery_assist_enabled = True
    return dev


def test_the_start_reserve_is_part_of_the_bar():
    """(#688) A fresh start needs its start reserve on top of the threshold.
    On 2100 W a 2000 W pump with a 300 W reserve does not start, so it holds
    nothing; on 2300 W it does."""
    dev = _senior(rated=2000.0)
    dev.start_reserve_w = 300.0
    assert _reserve([dev], 2100.0) == 0.0
    assert _reserve([dev], 2300.0) == 2000.0


def test_a_solar_and_battery_senior_counts_its_pack():
    """900 W of sun plus 1500 W the pack may add starts a 2000 W pump: it
    keeps the sun. With no pack help it cannot start and keeps nothing."""
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        surplus_reserved_w,
    )
    dev = _t1(rated=2000.0)
    assert surplus_reserved_w([dev], below_priority=8, available_w=900.0,
                              pack_w=1500.0) == 900.0
    assert surplus_reserved_w([dev], below_priority=8, available_w=900.0,
                              pack_w=0.0) == 0.0


def test_pack_help_only_for_a_load_that_may_take_it():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        surplus_reserved_w,
    )
    plain = _senior(rated=2000.0)                      # Solar only
    done = _t1(rated=2000.0)
    done.daily_targets_met = True                      # past its daily floor
    for dev in (plain, done):
        assert surplus_reserved_w([dev], below_priority=8, available_w=900.0,
                                  pack_w=1500.0) == 0.0


def test_battery_axis_idle_senior_that_cannot_start_holds_no_pack():
    """600 W sun + 1000 W pack cannot start a 2000 W pump: the car keeps the
    pack. With 1500 W of pack help it can, and the claim stands."""
    dev = _t1(rated=2000.0)
    assert _tier1_reserve([dev], sun=600.0, pack=1000.0) == 0.0
    assert _tier1_reserve([dev], sun=600.0, pack=1500.0) == 2000.0


def test_battery_axis_pack_closed_holds_nothing():
    assert _tier1_reserve([_t1(rated=2000.0)], sun=3000.0, pack=0.0) == 0.0


def test_battery_axis_without_figures_keeps_the_old_claim():
    assert _tier1_reserve([_t1(rated=2000.0)]) == 2000.0


def test_battery_axis_start_delay_keeps_the_claim():
    dev = _t1(rated=2000.0, dwell=datetime.now())
    assert _tier1_reserve([dev], sun=0.0, pack=1000.0) == 2000.0


def test_battery_axis_running_load_keeps_its_measured_draw():
    """The #885 flip-flop guard: a running pack-funded load keeps reserving
    what it draws, whatever the start figures say."""
    dev = _t1(rated=2000.0, active=True)
    dev._tier1_batt_w = 900.0
    assert _tier1_reserve([dev], sun=0.0, pack=0.0) == 900.0


def test_battery_axis_mode_and_cap_gate_idle_loads():
    """An idle load that will not switch on holds no pack: mode Off, peak
    only, or done for today (the battery axis never asked)."""
    off = _t1(rated=2000.0)
    off.control_mode = "off"
    peak = _t1(rated=2000.0)
    peak.control_mode = "peak_only"
    capped = _t1(rated=2000.0)
    capped.daily_max_runtime_reached = True
    for dev in (off, peak, capped):
        assert _tier1_reserve([dev]) == 0.0
        assert _tier1_reserve([dev], sun=3000.0, pack=3000.0) == 0.0


class _Away:
    def __init__(self, *, dump=False, heats=False, raises=False):
        self.calls = []
        self.dump, self.heats, self.raises = dump, heats, raises

    def device(self):
        dev = _t1(rated=2000.0)
        dev.vacation = True
        dev.away_pauses = lambda: True
        dev.vacation_dhw_surplus = self.dump

        def heats(running=False, *, peek=False):
            self.calls.append((running, peek))
            if self.raises:
                raise RuntimeError("no reading")
            return self.heats
        dev.comfort_away_heats = heats
        return dev


def test_a_load_paused_while_away_holds_nothing():
    away = _Away()
    dev = away.device()
    assert _reserve([dev], 3000.0) == 0.0
    assert _tier1_reserve([dev], sun=3000.0, pack=3000.0) == 0.0
    assert away.calls and all(peek for _, peek in away.calls), (
        "the walk must only peek at the band, never move it")


def test_away_dump_holds_sun_but_no_pack():
    dev = _Away(dump=True).device()
    assert _reserve([dev], 3000.0) == 2000.0
    assert _tier1_reserve([dev], sun=3000.0, pack=3000.0) == 0.0


def test_away_too_cold_or_unreadable_keeps_the_claim():
    for away in (_Away(heats=True), _Away(raises=True)):
        assert _reserve([away.device()], 3000.0) == 2000.0


def test_the_walk_and_the_load_pass_agree_on_a_start():
    """The oracle: for an idle Solar + battery switch load, the walk holds
    sun back exactly when the load pass would start it on that sun plus
    that pack help."""
    from unittest.mock import MagicMock
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        compute_load_intent, surplus_reserved_w,
    )
    from custom_components.solar_energy_management.devices.base import (
        DeviceControlMode, SwitchDevice,
    )
    dev = SwitchDevice(MagicMock(), "hp", "Heat pump", rated_power=2000.0,
                       entity_id="switch.hp")
    dev.control_mode = DeviceControlMode.SURPLUS
    dev.battery_assist_enabled = True
    dev.start_reserve_w = 250.0
    dev.priority = 1
    checked = 0
    for sun in range(0, 3001, 125):
        for pack in (0.0, 400.0, 1200.0):
            starts = compute_load_intent(
                dev, remaining_surplus_w=float(sun), tier1_headroom_w=pack,
                is_night=False).on
            held = surplus_reserved_w([dev], below_priority=8,
                                      available_w=float(sun), pack_w=pack)
            assert (held > 0.0) == (starts and sun > 0), (sun, pack, held, starts)
            checked += starts
    assert checked > 0, "the sweep never reached a start"


def test_the_loop_hands_the_walks_the_start_figures():
    """Both walks in the charger loop get the start figures (AST, not text)."""
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    from .ast_contracts import call_kwargs
    loop = SEMCoordinator._async_update_data
    solar = call_kwargs(loop, "_surplus_reserved_w")
    batt = call_kwargs(loop, "_tier1_reserved_w")
    assert solar and all("pack_w" in kw for kw in solar)
    assert batt and all({"pack_w", "sun_w"} <= set(kw) for kw in batt)
