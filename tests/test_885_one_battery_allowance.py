"""#885 — one battery allowance, consumed in device order.

Guido, 31.08:

    "The order tells who is first and gets power from the battery. The next
    will get powered from the grid if there is nothing left."

SEM did not implement that. Two subsystems each held a private copy of
``battery_assist_max_power`` and each treated it as its own full budget:

* the EV path, via ``battery_assist_potential_w`` in ``decide.py``
* the load path, via ``build_battery_tier_context`` in ``surplus_controller``

Nothing reconciled them, so on one pack with a 5000 W cap the EV fleet could
ask for 5000 W **and** the loads for 5000 W in the same cycle.

Worse after #878: the load path gates on ``buffer_soc`` alone and had never
seen the dynamic floor, so the EV side would stop at the level the house
needs overnight while the loads drained straight through it — the floor kept
by one consumer and ignored by the other.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    build_battery_tier_context,
)

CFG = {
    "battery_assist_max_power": 5000.0,
    "battery_buffer_soc": 70.0,
    "battery_priority_soc": 30.0,
    "battery_assist_min_surplus": 1200.0,
}


class TestTheAllowanceIsShared:
    def test_loads_see_only_what_the_chargers_left(self):
        btc = build_battery_tier_context(
            CFG, battery_soc=85.0, true_surplus_w=6000.0,
            assist_committed_w=3864.0,
        )
        assert btc.assist_budget_w == 5000.0 - 3864.0, (
            "the loads claimed the whole pack allowance again — one battery "
            "asked twice in the same cycle"
        )

    def test_an_exhausted_allowance_leaves_nothing(self):
        """Guido's sentence: the next device gets powered from the grid."""
        btc = build_battery_tier_context(
            CFG, battery_soc=85.0, true_surplus_w=6000.0,
            assist_committed_w=5000.0,
        )
        assert btc.assist_budget_w == 0.0

    def test_over_commitment_never_goes_negative(self):
        btc = build_battery_tier_context(
            CFG, battery_soc=85.0, true_surplus_w=6000.0,
            assist_committed_w=9999.0,
        )
        assert btc.assist_budget_w == 0.0

    def test_nothing_committed_is_todays_behaviour(self):
        a = build_battery_tier_context(CFG, 85.0, 6000.0, assist_committed_w=0.0)
        b = build_battery_tier_context(CFG, 85.0, 6000.0)
        assert a.assist_budget_w == b.assist_budget_w == 5000.0


class TestLoadsRespectTheSameFloor:
    """#878 gave the EV side a floor that keeps the house covered overnight.
    A floor only one consumer honours is not a floor."""

    def test_below_the_computed_floor_the_loads_get_nothing(self):
        btc = build_battery_tier_context(
            CFG, battery_soc=75.0, true_surplus_w=6000.0,
            dynamic_floor_pct=79.0,
        )
        assert btc.assist_budget_w == 0.0, (
            "loads drained through the level the house needs overnight while "
            "the EV side stopped at it"
        )

    def test_above_the_floor_they_still_get_it(self):
        btc = build_battery_tier_context(
            CFG, battery_soc=85.0, true_surplus_w=6000.0,
            dynamic_floor_pct=79.0,
        )
        assert btc.assist_budget_w == 5000.0

    def test_no_floor_falls_back_to_the_buffer(self):
        """Fail closed: None means "use the buffer", never "no floor"."""
        below = build_battery_tier_context(CFG, 65.0, 6000.0, dynamic_floor_pct=None)
        above = build_battery_tier_context(CFG, 75.0, 6000.0, dynamic_floor_pct=None)
        assert below.assist_budget_w == 0.0      # under the 70 buffer
        assert above.assist_budget_w == 5000.0   # over it, as before

    def test_a_floor_below_the_buffer_never_lowers_it(self):
        btc = build_battery_tier_context(
            CFG, battery_soc=65.0, true_surplus_w=6000.0, dynamic_floor_pct=10.0,
        )
        assert btc.assist_budget_w == 0.0


class TestTheCoordinatorFeedsIt:
    def test_the_call_site_passes_both(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        # the call lives in _update_analytics_phases, not the top-level
        # cycle — asserting against the wrong method fails on location
        # rather than on truth
        src = inspect.getsource(SEMCoordinator._update_analytics_phases)
        i = src.index("build_battery_tier_context(")
        # a generous window: the point is that both kwargs reach the call,
        # not how the call is wrapped. A tight window fails on formatting.
        call = src[i:i + 900]
        assert "assist_committed_w" in call, (
            "the loads never learn what the chargers took"
        )
        assert "dynamic_floor_pct" in call, (
            "the loads never learn the floor the EV side respects"
        )


class TestIndividualDevicesStopAtTheFloor:
    """Guido, 31.08: *"we already have everything, we just have to use it
    until the floor is reached — also for the individual devices."*

    The per-device machinery was already there: `_tier1_headroom_w` returns
    `min(assist_budget, tier1_budget_left)`, a running budget that shrinks as
    higher-priority loads claim it, so the battery is not multi-spent within
    the load path.

    What it gated on was `buffer_soc`. That field has exactly ONE consumer —
    this guard — so it now carries the EFFECTIVE floor, and each device stops
    where the house's overnight need begins rather than where the static
    buffer does."""

    def test_the_context_exposes_the_effective_floor(self):
        btc = build_battery_tier_context(
            CFG, battery_soc=85.0, true_surplus_w=6000.0, dynamic_floor_pct=79.0,
        )
        assert btc.effective_floor_soc == 79.0
        assert btc.buffer_soc == 70.0, "the configured buffer stays honest"

    def test_no_floor_leaves_the_buffer_as_the_effective_one(self):
        btc = build_battery_tier_context(CFG, 85.0, 6000.0)
        assert btc.effective_floor_soc == 70.0

    def test_a_lower_floor_never_lowers_the_buffer(self):
        btc = build_battery_tier_context(CFG, 85.0, 6000.0, dynamic_floor_pct=40.0)
        assert btc.effective_floor_soc == 70.0

    def test_the_per_device_guard_uses_the_floor_not_the_buffer(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._update_analytics_phases)
        assert "btc.effective_floor_soc" in src, (
            "the surplus controller is still handed the raw buffer, so each "
            "load drains past the level the house needs overnight"
        )


# ---------------------------------------------------------------------------
# The one order — defect B
# ---------------------------------------------------------------------------

def _load(priority, *, tier1=False, tier2=False, active=False,
          rated=1200.0, min_w=800.0, name="load"):
    """A surplus device as the reservation walk sees it."""
    from types import SimpleNamespace
    return SimpleNamespace(
        name=name, priority=priority, is_active=active,
        battery_assist_enabled=tier1, battery_eligible_overnight=tier2,
        rated_power=rated, min_power_threshold=min_w,
    )


class TestTheOrderDecidesWhoGetsTheBattery:
    """Guido, 31.08: *"if it is not one order for addressing surplus and also
    for planning and load management, there is only one priority — it is the
    device list, and if it is not we have a bug."*

    It was a bug. ``UnifiedDeviceRegistry.priority_for`` calls itself "the
    SINGLE priority axis — loads, the battery, AND every EV charger read
    their slot from here", and both consumers really do read it. But the
    cycle SPENDS the pack in call order: every charger commits in the
    per-charger loop, and the load pass only runs afterwards. So a prio-9
    charger took battery power ahead of a prio-1 hot-water load and dragging
    that load to the top changed nothing at all.
    """

    def _reserve(self, devices, priority, allowance=5000.0):
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            tier1_battery_reserved_w,
        )
        return tier1_battery_reserved_w(
            devices, below_priority=priority, allowance_w=allowance,
        )

    def test_a_higher_ranked_load_reserves_against_the_charger(self):
        hot_water = _load(1, tier1=True, rated=1200.0)
        assert self._reserve([hot_water], 5) == 1200.0

    def test_a_lower_ranked_load_reserves_nothing(self):
        """The junior device yields — that is what the order MEANS."""
        pool_pump = _load(9, tier1=True, rated=1200.0)
        assert self._reserve([pool_pump], 5) == 0.0

    def test_equal_rank_yields_to_the_charger(self):
        assert self._reserve([_load(5, tier1=True)], 5) == 0.0

    def test_dragging_the_load_up_flips_the_outcome(self):
        """The headline case. Same devices, same pack — only the drag order
        differs, and it must decide who charges from the battery."""
        allowance = 5000.0
        below = self._reserve([_load(9, tier1=True, rated=1200.0)], 5, allowance)
        above = self._reserve([_load(1, tier1=True, rated=1200.0)], 5, allowance)
        assert below == 0.0, "ranked below: the charger keeps the whole pack"
        assert above == 1200.0, "dragged above: the load is served first"
        assert above > below, "the drag list must change the answer"

    def test_several_seniors_accumulate(self):
        devices = [_load(1, tier1=True, rated=1200.0),
                   _load(2, tier1=True, rated=2000.0)]
        assert self._reserve(devices, 5) == 3200.0

    def test_the_reservation_never_exceeds_the_allowance(self):
        """"Nothing left" is a floor of zero for the junior, never a debt."""
        devices = [_load(1, tier1=True, rated=9000.0)]
        assert self._reserve(devices, 5, allowance=5000.0) == 5000.0

    def test_no_allowance_reserves_nothing(self):
        assert self._reserve([_load(1, tier1=True)], 5, allowance=0.0) == 0.0


class TestOnlyOptedInDevicesReserve:
    """Guido, 31.08: *"on every individual device there is a setting whether
    it will charge with battery or not ... for the individual devices it is
    the option 'finish overnight with battery'."*

    Two flags, two BANDS. Conflating them is a real bug in either direction.
    """

    def _reserve(self, devices, priority=5, allowance=5000.0):
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            tier1_battery_reserved_w,
        )
        return tier1_battery_reserved_w(
            devices, below_priority=priority, allowance_w=allowance,
        )

    def test_a_load_with_no_opt_in_reserves_nothing(self):
        """Default is off for both flags. A device nobody enrolled must
        never push a car onto the grid."""
        assert self._reserve([_load(1)]) == 0.0

    def test_a_tier2_only_load_reserves_nothing(self):
        """BAND ISOLATION. ``battery_eligible_overnight`` draws BELOW the
        buffer, down to the hard Reserve — a band the charger's floor
        (``max(buffer, dynamic_floor)``) forbids it from entering. They are
        not competing for the same watts, so reserving here would starve the
        car for energy it was never going to lose."""
        overnight_only = _load(1, tier1=False, tier2=True, rated=2000.0)
        assert self._reserve([overnight_only]) == 0.0

    def test_a_device_on_both_tiers_still_reserves_via_tier1(self):
        both = _load(1, tier1=True, tier2=True, rated=1500.0)
        assert self._reserve([both]) == 1500.0

    def test_an_already_running_load_reserves_nothing(self):
        """Its draw is already inside ``home_consumption_power``, so it has
        ALREADY reduced the surplus every charger sees. Reserving again
        bills the same watts twice."""
        running = _load(1, tier1=True, active=True, rated=1200.0)
        assert self._reserve([running]) == 0.0

    def test_the_threshold_stands_in_when_no_rating_is_known(self):
        unrated = _load(1, tier1=True, rated=0.0, min_w=800.0)
        assert self._reserve([unrated]) == 800.0

    def test_a_junk_priority_is_skipped_not_crashed(self):
        junk = _load("not-a-number", tier1=True, rated=1200.0)
        assert self._reserve([junk]) == 0.0

    def test_no_devices_at_all(self):
        assert self._reserve([]) == 0.0
        assert self._reserve(None) == 0.0


# ---------------------------------------------------------------------------
# Per-charger permission — defect C
# ---------------------------------------------------------------------------

class TestTheBatteryPermissionIsPerCharger:
    """Guido, 31.08: *"and the same on the charger, therefore not every
    charger has to be activated."*

    Loads have had a per-device opt-in since #620. Chargers had ONE
    fleet-wide switch resolved from "the per-install EV-assist permission",
    so a two-charger install could not say "the garage may, the guest
    charger may not".
    """

    def _resolve(self, charger_cfg, **config):
        from custom_components.solar_energy_management.coordinator.build_view import (
            _battery_may_assist_ev,
        )
        return _battery_may_assist_ev(config, charger_cfg)

    def test_unset_inherits_the_install_answer(self):
        """Nothing changes for anyone who has not asked."""
        assert self._resolve({}) is True

    def test_a_charger_can_opt_out_on_its_own(self):
        assert self._resolve({"ev_battery_may_assist": False}) is False

    def test_one_charger_opting_out_leaves_its_sibling_alone(self):
        garage = {"ev_battery_may_assist": True}
        guest = {"ev_battery_may_assist": False}
        assert self._resolve(garage) is True
        assert self._resolve(guest) is False

    def test_a_charger_cannot_overrule_an_install_that_said_no(self):
        """Fail-closed: the per-charger key RESTRICTS, never grants. One
        rule ("both must agree") instead of a precedence table."""
        assert self._resolve(
            {"ev_battery_may_assist": True}, battery_mode="off",
        ) is False

    def test_no_charger_cfg_at_all_is_the_install_answer(self):
        assert self._resolve(None) is True


# ---------------------------------------------------------------------------
# The decision reports its own battery draw — no re-derivation
# ---------------------------------------------------------------------------

def _fleet_view(*, soc=85.0, floor=79.0, solar=6000.0, committed=0.0):
    from types import SimpleNamespace
    f = SimpleNamespace(
        solar_w=solar, curtailment_grant_w=0.0, home_w=0.0,
        battery_charge_w=0.0, solar_committed_w=0.0,
        battery_soc=soc, buffer_soc=70.0, auto_start_soc=90.0,
        priority_soc=30.0, battery_assist_max_power_w=5000.0,
        battery_assist_min_surplus_w=1200.0, battery_may_assist_ev=True,
        dynamic_floor_pct=floor, forecast_spending_enabled=True,
        battery_spendable_kwh=4.0, battery_priority=None,
        battery_commanded=False, assist_committed_w=committed,
    )
    return SimpleNamespace(fleet=f, ev_priority=1)


class TestTheDecisionCarriesItsOwnAssist:
    """The coordinator used to RE-DERIVE each charger's battery share by
    subtracting a locally-reconstructed "solar this charger could see" from
    the commitment. ``decide`` had already computed that number with the real
    surplus in hand — and a second implementation of one value is the #282
    class that drifts. ``decide`` computes, ``decide`` reports.
    """

    def _split(self, view):
        from custom_components.solar_energy_management.coordinator.decide import (
            _battery_assist_split,
        )
        return _battery_assist_split(view)

    def test_the_split_sums_to_the_public_budget(self):
        """The refactor must not move the number every other caller reads."""
        from custom_components.solar_energy_management.coordinator.decide import (
            battery_assist_budget_w,
        )
        view = _fleet_view()
        surplus, assist = self._split(view)
        assert surplus + assist == battery_assist_budget_w(view)

    def test_the_split_names_a_real_battery_share(self):
        surplus, assist = self._split(_fleet_view())
        assert surplus == 6000.0, "the sun's part"
        assert assist > 0.0, "the pack's part, reported separately"

    def test_a_blocked_permission_yields_no_assist_component(self):
        view = _fleet_view()
        view.fleet.battery_may_assist_ev = False
        surplus, assist = self._split(view)
        assert assist == 0.0
        assert surplus == 6000.0

    def test_below_the_floor_there_is_no_assist_component(self):
        surplus, assist = self._split(_fleet_view(soc=75.0, floor=79.0))
        assert assist == 0.0

    def test_a_seniors_claim_shrinks_the_component(self):
        _, alone = self._split(_fleet_view())
        _, after = self._split(_fleet_view(committed=alone))
        assert after == 0.0, "one pack: the second charger sees it emptied"

    def test_the_charge_decisions_stamp_it(self):
        """AST guard. A value computed and never carried is the inert-half
        class this branch has already hit three times."""
        import inspect
        from custom_components.solar_energy_management.coordinator import decide as D
        src = inspect.getsource(D)
        assert "assist_w=_assist_share(amps)" in src, (
            "the Zone 3/4 charge decisions must stamp the battery share"
        )

    def test_the_coordinator_reads_it_instead_of_recomputing(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert 'getattr(decision, "assist_w", 0.0)' in src, (
            "must read the share the decision reported"
        )
        assert "_solar_seen" not in src, (
            "the re-derivation is back — decide already computed this "
            "number with the real surplus in hand (#282)"
        )


class TestTheCoordinatorSpendsItInOrder:
    """Pin the wiring: the reservation is worthless unless the per-charger
    loop actually consults it before offering the pack."""

    def test_the_loop_reserves_for_higher_ranked_loads(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert "_tier1_reserved_w(" in src, (
            "the charger loop never asks what outranks it — chargers still "
            "drain the pack before the load pass runs"
        )
        assert "below_priority=self._ev_priority_for(cid)" in src, (
            "the reservation must use THIS charger's slot in the one list"
        )

    def test_the_reservation_rides_the_same_seam_as_the_accumulator(self):
        """One netting seam, not two: the charger's potential is reduced by
        seniors' draws AND higher-ranked loads' reservations together."""
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._async_update_data)
        i = src.index("assist_committed_w=(")
        window = src[i:i + 500]
        assert "_assist_committed_w_per_cycle" in window
        assert "_tier1_reserved_w(" in window
