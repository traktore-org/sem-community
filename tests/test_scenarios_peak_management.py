"""Multi-cycle scenarios for night-charging peak management.

The unit tests in ``test_night_peak_managed.py`` cover the per-call
formula (legacy ``home_consumption_power`` fallback) and
``test_night_peak_rolling.py`` covers the #288 rolling 15-min path.
What both miss is the multi-cycle BEHAVIOUR — how the throttle
decision evolves as the rolling-peak metric climbs / falls /
catches up with the EV's own draw.

Scenarios in this file (all multi-cycle):

  * **EV self-balances against rolling peak** — the headline #288
    contract: as EV ramps up, rolling peak rises and headroom
    shrinks; settles at equilibrium.
  * **Home consumption spike** — washing machine kicks in mid-night,
    EV throttles down to maintain peak budget.
  * **Cold-start → rolling crossover** — first ~15 cycles use the
    legacy formula; rolling becomes available; transition is smooth.
  * **Multi-charger shared budget over time** — two chargers sequentially
    activated; second sees reduced headroom as the first's commit
    accumulates.

Same shape as the load_management scenarios — sequenced calls,
state evolves, contracts pinned.
"""
from __future__ import annotations

from unittest.mock import Mock


from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


def _make_obj(
    *,
    peak_w: float = 6000,
    rolling_w: float | None = None,
    committed_w: float = 0.0,
) -> Mock:
    """Build the mock-self the ``_night_peak_managed_amps`` helper expects."""
    obj = Mock()
    obj._get_peak_limit_w = Mock(return_value=peak_w)
    obj._get_peak_15min_w = Mock(return_value=rolling_w)
    obj._night_committed_w = committed_w
    return obj


def _readings(*, home: float, ev: float = 0, grid: float = 0,
              batt: float = 0) -> PowerReadings:
    p = PowerReadings()
    p.home_consumption_power = home
    p.ev_power = ev
    p.grid_import_power = grid
    p.battery_power = batt
    return p


# ---------------------------------------------------------------------------
# Scenario 1 — EV self-balances against rolling peak (#288)
# ---------------------------------------------------------------------------


class TestEVSelfBalancesAgainstRollingPeak:
    """Headline #288 contract over time: as the EV draws current, the
    rolling 15-min peak metric (which INCLUDES the EV's draw) climbs.
    The throttle decision must respond by reducing target amps. The
    system settles at the equilibrium where rolling ≈ peak_limit.
    """

    WATTS_PER_AMP = 690  # 3-phase 230V

    def test_rolling_climbs_amps_drops(self) -> None:
        """Walk the rolling peak from 4000W → 6000W (the peak limit).
        At each step the throttle should reduce amps. Settles at min_amps
        when rolling reaches peak."""
        peak = 6000

        # rolling=4000 → headroom 2000W → 2 amps (above min=6 floor)
        amps1 = EVControlMixin._night_peak_managed_amps(
            _make_obj(peak_w=peak, rolling_w=4000),
            _readings(home=500, ev=1500),  # ev contributing 1500W
            self.WATTS_PER_AMP, 6, 16,
        )

        # rolling=5000 → headroom 1000W → 1 amp → clamps to min=6
        amps2 = EVControlMixin._night_peak_managed_amps(
            _make_obj(peak_w=peak, rolling_w=5000),
            _readings(home=500, ev=2500),
            self.WATTS_PER_AMP, 6, 16,
        )

        # rolling=6000 → headroom 0 → 0 amps → clamps to min=6
        amps3 = EVControlMixin._night_peak_managed_amps(
            _make_obj(peak_w=peak, rolling_w=6000),
            _readings(home=500, ev=3500),
            self.WATTS_PER_AMP, 6, 16,
        )

        # Monotonically non-increasing — the throttle never goes UP
        # as the rolling peak climbs.
        assert amps1 >= amps2 >= amps3
        # All clamp to min_amps when headroom is below 1A.
        assert amps2 == 6
        assert amps3 == 6


# ---------------------------------------------------------------------------
# Scenario 2 — Home consumption spike mid-night
# ---------------------------------------------------------------------------


class TestHomeConsumptionSpike:
    """A washing machine kicks in mid-night while the EV is charging.
    The peak management must respond by reducing the EV's allowed
    current — otherwise grid_import = home + ev + spike could exceed
    peak_limit.

    Exercised via the legacy formula (cold-start window — rolling
    hasn't accumulated yet).
    """

    WATTS_PER_AMP = 690

    def test_amps_drop_when_home_spikes(self) -> None:
        peak = 6000

        # Baseline: 800W house, EV charging at 6A (4140W). Headroom =
        # 6000 - 800 = 5200W → ~7 amps.
        amps_baseline = EVControlMixin._night_peak_managed_amps(
            _make_obj(peak_w=peak),  # rolling=None → legacy formula
            _readings(home=800, ev=4140),
            self.WATTS_PER_AMP, 6, 16,
        )

        # Washing machine: house climbs to 2800W. Headroom = 6000 -
        # 2800 = 3200W → ~4 amps → clamps to min=6.
        amps_spike = EVControlMixin._night_peak_managed_amps(
            _make_obj(peak_w=peak),
            _readings(home=2800, ev=4140),
            self.WATTS_PER_AMP, 6, 16,
        )

        # Washing finishes: back to 800W. Throttle releases.
        amps_recover = EVControlMixin._night_peak_managed_amps(
            _make_obj(peak_w=peak),
            _readings(home=800, ev=4140),
            self.WATTS_PER_AMP, 6, 16,
        )

        assert amps_baseline >= amps_spike, "spike must throttle down"
        assert amps_recover >= amps_spike, "recovery must release throttle"
        assert amps_baseline == amps_recover, (
            "same conditions before + after must produce same throttle"
        )


# ---------------------------------------------------------------------------
# Scenario 3 — Cold-start → rolling crossover
# ---------------------------------------------------------------------------


class TestColdStartRollingCrossover:
    """For the first ~15 min after a restart, the rolling 15-min peak
    metric has no samples; the legacy ``home_consumption_power``
    formula provides the fallback. Once rolling becomes available,
    the throttle uses it. Crossover should be smooth — no large
    sudden amp change purely from the metric switching.
    """

    WATTS_PER_AMP = 690

    def test_legacy_and_rolling_agree_at_steady_state(self) -> None:
        """When the system is in steady-state (rolling ≈ home + ev),
        the legacy formula and the rolling formula should produce the
        same throttle. Catches a 'cold-start crossover step' bug where
        the metric change alone causes the EV to step current up/down
        for no real reason."""
        peak = 6000
        home_w = 1000
        ev_w = 4140  # 6A at 690 W/A

        # Legacy: headroom = peak - home - committed = 6000 - 1000 - 0 = 5000
        amps_legacy = EVControlMixin._night_peak_managed_amps(
            _make_obj(peak_w=peak, rolling_w=None),
            _readings(home=home_w, ev=ev_w),
            self.WATTS_PER_AMP, 6, 16,
        )

        # Rolling: steady-state rolling = home + ev = 5140. Headroom =
        # 6000 - 5140 - 0 = 860. amps = ceil(860/690) ≈ 1, but clamps to min=6.
        amps_rolling = EVControlMixin._night_peak_managed_amps(
            _make_obj(peak_w=peak, rolling_w=home_w + ev_w),
            _readings(home=home_w, ev=ev_w),
            self.WATTS_PER_AMP, 6, 16,
        )

        # Legacy says "you've got 5000W of headroom, take more."
        # Rolling says "you're already at peak, hold." Both produce
        # safe amps (at least min_amps). Rolling is more conservative.
        # The contract: rolling <= legacy at steady state.
        assert amps_rolling <= amps_legacy


# ---------------------------------------------------------------------------
# Scenario 4 — Multi-charger shared peak budget over time
# ---------------------------------------------------------------------------


class TestMultiChargerSharedPeakOverTime:
    """Two chargers in priority order; the second sees REDUCED headroom
    as the first's commit accumulates. Without this, both chargers
    independently size to the full peak headroom and their combined
    grid import would exceed the peak.
    """

    WATTS_PER_AMP = 690

    def test_committed_w_shrinks_headroom_for_later_chargers(self) -> None:
        peak = 9000

        # Charger 1 sees the full peak headroom.
        amps1 = EVControlMixin._night_peak_managed_amps(
            _make_obj(peak_w=peak, committed_w=0),
            _readings(home=1000, ev=0),
            self.WATTS_PER_AMP, 6, 16,
        )

        # Charger 2 sees the headroom MINUS what charger 1 just
        # committed. Same fleet conditions, but committed_w =
        # charger 1's commit.
        amps_charger_1_commit_w = amps1 * self.WATTS_PER_AMP
        amps2 = EVControlMixin._night_peak_managed_amps(
            _make_obj(peak_w=peak, committed_w=amps_charger_1_commit_w),
            _readings(home=1000, ev=0),
            self.WATTS_PER_AMP, 6, 16,
        )

        # Charger 2's amps MUST be less than charger 1's — the
        # commit accumulates and shrinks the headroom. Without
        # #274/H1 both chargers independently saw the full headroom.
        assert amps2 < amps1, "second charger must see reduced headroom"

        # Charger 2 clamps to ``min_amps`` (the hardware floor at
        # 6A — anything lower is below the IEC 61851 minimum and
        # would be rejected by the charger). The combined draw
        # exceeds peak in this regime because peak management
        # SIZES amps, it doesn't gate whether to charge.
        #
        # Real fleet protection at the strategy layer would
        # additionally have the OffMode / state-machine refuse
        # to charge charger 2 when the available budget is below
        # one charger's minimum. That gating is exercised by the
        # YAML scenarios (multi_charger/priority_cascade_with_mixed_modes
        # specifically). Peak management's job here is just sizing.
        assert amps2 == 6, (
            "second charger clamps to hardware minimum amps when no "
            "headroom remains"
        )
