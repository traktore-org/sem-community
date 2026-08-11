"""#638 one-gate C3 — the EV's private cheap-window selector is RETIRED.

The joint plan's blocks are the only WHEN for the night. What remains in
`plan_night_charge` is guarantee math — deadline resolution, reachability,
floor amps, the peak-managed top-up rate. The wait/next-cheap fields stay
on `NightChargePlan` but their ONLY writer is the plan-gate overlay
(coordinator.py, both sites); the pure planner can no longer produce a
wait, so an uncovered night fails open to CHARGING — the agreed direction
(the floor is a guarantee; an expensive night is a visible planner bug,
named by the `#638 coverage` line).

The dwell hysteresis (`_tariff_decision_per_charger`) dies with the
selector: it damped the selector's own price flapping, and the plan's
blocks don't flap. The KEBA's contactor protection moves to the PACKER:
EV demands now carry `min_run_s`/`min_gap_s`, so a 15-minute jagged
market cannot hand the charger scattered quarter-hour blocks.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    plan_night_charge,
)

NOW = datetime(2026, 5, 26, 22, 0)


def _plan(**kw):
    base = dict(
        now=NOW, remaining_to_min_kwh=10.0, min_amps=6, max_amps=32,
        watts_per_amp=690.0, target_time="07:00", night_end="07:00",
    )
    base.update(kw)
    return plan_night_charge(**base)


@pytest.mark.unit
class TestThePurePlannerCannotWait:
    def test_cheap_slots_is_no_longer_a_parameter(self):
        with pytest.raises(TypeError):
            _plan(cheap_slots=[NOW + timedelta(hours=2)])

    def test_slot_hours_is_no_longer_a_parameter(self):
        with pytest.raises(TypeError):
            _plan(slot_hours=0.25)

    def test_tariff_optimized_alone_never_waits(self):
        """Without slots there is nothing to wait FOR — the wait can only
        come from the overlay's plan gate."""
        p = _plan(tariff_optimized=True)
        assert p.should_wait_for_cheap is False
        assert p.next_cheap_start is None

    def test_the_guarantees_survive(self):
        """Deadline scaling, reachability and the opt-in unreachable warn
        are the kept half — pin they still work post-retirement.
        (60 kWh in 9 h at 7 A x 690 W ~ 43 kWh -> unreachable.)"""
        p = _plan(remaining_to_min_kwh=60.0, tariff_optimized=True,
                  peak_managed_amps=7)
        assert p.reachable is False
        assert p.should_warn_unreachable is True
        q = _plan(remaining_to_min_kwh=60.0, peak_managed_amps=7)
        assert q.should_warn_unreachable is False  # never opted in


@pytest.mark.unit
class TestTheCallerNeverTouchesTheTariff:
    """`_compute_night_plan` must not consult the provider at all — the
    one-selector ratchet enforces it at the AST level; this pins it at
    the behaviour level."""

    def test_no_provider_call_even_when_tariff_optimized(self):
        from .test_ev_deadline_tariff import _build_coordinator
        coord = _build_coordinator(tariff_on=True)
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "07:00",
               "charge_mode": "solar_plus_cheap"}
        coord._compute_night_plan(cfg, remaining_to_min_kwh=8.0)
        assert not coord._tariff_provider.find_cheapest_hours.called

    def test_the_dwell_state_is_gone(self):
        """The hysteresis damped the retired selector's own flapping.
        Nothing may recreate its state dict."""
        import inspect
        from custom_components.solar_energy_management.coordinator.ev_control import (
            EVControlMixin,
        )
        src = inspect.getsource(EVControlMixin._compute_night_plan)
        assert "_tariff_decision_per_charger" not in src


# Make the shadow world's fixtures available here (pytest resolves
# fixtures by name once imported).
from .test_638_shadow_mode import (  # noqa: E402,F401
    _fake_self,
    _power,
    _scheduler,
    freeze_targets,
)


@pytest.mark.unit
class TestEvDemandsCarryTheAntiCycleWindow:
    """The packer's #688 quantization protects the contactor now — EV
    demands pack with min_run/min_gap like loads always did."""

    def test_the_packed_ev_demand_has_min_run_and_min_gap(self, freeze_targets):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        fake = _fake_self()
        captured = {}
        import custom_components.solar_energy_management.coordinator.overnight_planner as onp
        real_pack = onp.pack_night

        def spy(demands, ledger, **kw):
            captured["demands"] = list(demands)
            return real_pack(demands, ledger, **kw)

        with patch.object(onp, "pack_night", side_effect=spy):
            SEMCoordinator._shadow_overnight_plan(
                fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=0,
                phantom_ev_w=0, power=_power())
        ev = [d for d in captured.get("demands", []) if d.id.startswith("ev:")]
        assert ev, "the fake world must produce an EV demand"
        assert ev[0].min_run_s >= 900, "EV blocks must be >= 15 min"
        assert ev[0].min_gap_s >= 900, "EV block gaps must be >= 15 min"
