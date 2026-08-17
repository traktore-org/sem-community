"""#440 — per-vehicle minimum current (ADR 0010 pattern 3).

Effective per-charger floor is ``max(ev_min_current, vehicle_min_current)``.
The third leg of the three-way max (the EVSE hardware minimum)
is enforced in the adapter and does NOT appear at the decide layer.

Tested:
1. ``effective_min_amps`` returns the loadpoint min when no vehicle
   override is set.
2. Vehicle override wins when higher than loadpoint min.
3. Loadpoint min wins when higher than vehicle override (you cannot
   lower the SEM-side floor via the vehicle field).
4. Empty / missing / non-numeric vehicle values fall through to
   loadpoint min cleanly.
5. ``decide.MinPlusSolarMode`` honours the effective floor in both
   day (Zone 3/4 commit-then-measure) and night branches.
"""
from __future__ import annotations



from custom_components.solar_energy_management.coordinator.decide import (
    effective_min_amps,
)


# ──────────────────────────────────────────────
# 1. Helper unit tests
# ──────────────────────────────────────────────


class TestEffectiveMinAmpsHelper:

    def test_loadpoint_only(self):
        assert effective_min_amps({"ev_min_current": 6}) == 6
        assert effective_min_amps({"ev_min_current": 10}) == 10

    def test_vehicle_higher_than_loadpoint(self):
        """Renault Zoe pattern: car needs 9 A handshake floor, SEM
        global at 6 A. Effective floor should be 9."""
        cfg = {"ev_min_current": 6, "vehicle_min_current": 9}
        assert effective_min_amps(cfg) == 9

    def test_vehicle_lower_than_loadpoint(self):
        """You cannot lower the SEM-side floor via the vehicle field.
        max() ensures the SEM floor is sticky."""
        cfg = {"ev_min_current": 10, "vehicle_min_current": 6}
        assert effective_min_amps(cfg) == 10

    def test_vehicle_equal_to_loadpoint(self):
        cfg = {"ev_min_current": 8, "vehicle_min_current": 8}
        assert effective_min_amps(cfg) == 8

    def test_vehicle_none_falls_through(self):
        """Default state after migration: vehicle_min_current is None.
        Effective floor equals loadpoint."""
        cfg = {"ev_min_current": 7, "vehicle_min_current": None}
        assert effective_min_amps(cfg) == 7

    def test_vehicle_empty_string_falls_through(self):
        """Config-flow can produce empty strings — must be handled."""
        cfg = {"ev_min_current": 7, "vehicle_min_current": ""}
        assert effective_min_amps(cfg) == 7

    def test_vehicle_garbage_falls_through(self):
        """Non-numeric vehicle value never crashes the decision path."""
        cfg = {"ev_min_current": 7, "vehicle_min_current": "abc"}
        assert effective_min_amps(cfg) == 7

    def test_no_cfg_returns_fallback(self):
        assert effective_min_amps(None, fallback=6) == 6
        assert effective_min_amps({}, fallback=8) == 8

    def test_returns_int(self):
        """Float input → int output (the actuator expects whole amps)."""
        cfg = {"ev_min_current": 6.0, "vehicle_min_current": 9.5}
        out = effective_min_amps(cfg)
        assert isinstance(out, int)
        assert out == 9

    def test_clamped_to_ev_max_current(self):
        """Reviewer-flagged: misconfigured ``vehicle_min_current`` above
        ``ev_max_current`` would otherwise pin commanded amps at max.
        The helper clamps to ev_max_current defensively."""
        cfg = {"ev_min_current": 6, "vehicle_min_current": 20, "ev_max_current": 16}
        assert effective_min_amps(cfg) == 16

    def test_clamp_to_max_does_not_affect_normal_case(self):
        """When floor < max the clamp is a no-op."""
        cfg = {"ev_min_current": 6, "vehicle_min_current": 9, "ev_max_current": 32}
        assert effective_min_amps(cfg) == 9

    def test_no_clamp_when_ev_max_unset(self):
        """If the config doesn't have ev_max_current, behaviour matches
        the simple two-way max (legacy callsites that omit the key)."""
        cfg = {"ev_min_current": 6, "vehicle_min_current": 12}
        assert effective_min_amps(cfg) == 12


# ──────────────────────────────────────────────
# 2. End-to-end through the mode strategies
# ──────────────────────────────────────────────


def _view(*, is_night=False, connected=True, soc=95, target_kwh=14.0,
          ev_min=6, vehicle_min=None, night_deliverable_kwh=float("inf")):
    """Build a minimal ChargerView for the night/day branches.

    ``night_deliverable_kwh`` defaults to ``inf`` (matching the
    ChargerView default = "the night window can cover any Min").
    Post-#501 the daytime Zone 3/4 floor is need-gated, so day-branch
    tests that want the floor to engage must pass a value below
    ``target_kwh``.
    """
    from custom_components.solar_energy_management.coordinator.charger_types import (
        FleetContext, ChargerView, ChargerPower, ChargerEnergy,
    )
    fleet = FleetContext(
        solar_w=0, home_w=400,
        battery_charge_w=0, battery_discharge_w=0,
        battery_soc=soc, auto_start_soc=90, buffer_soc=70, priority_soc=30,
        is_night=is_night,
    )
    cfg = {
        "ev_min_current": ev_min,
        "ev_max_current": 32,
        "ev_phases": 3,
        "ev_voltage": 230,
    }
    if vehicle_min is not None:
        cfg["vehicle_min_current"] = vehicle_min
    power = ChargerPower(charger_id="ev_charger", connected=connected, power_w=0)
    energy = ChargerEnergy(charger_id="ev_charger")
    return ChargerView(
        power=power, energy=energy, mode="min_plus_solar",
        config=cfg, fleet=fleet,
        target_kwh=target_kwh, deadline_amps=0,
        night_deliverable_kwh=night_deliverable_kwh,
    )


def test_min_plus_solar_night_uses_vehicle_min_when_higher():
    """min_plus_solar night branch commits at effective floor — should
    be 9 A when vehicle_min_current=9 (not the global ev_min_current=6)."""
    from custom_components.solar_energy_management.coordinator.decide import (
        MinPlusSolarMode,
    )
    view = _view(is_night=True, ev_min=6, vehicle_min=9, target_kwh=12.0)
    decision = MinPlusSolarMode().decide(view)
    assert decision.commanded_amps == 9, (
        f"vehicle_min=9 must win; got commanded_amps={decision.commanded_amps}"
    )


def test_min_plus_solar_night_uses_loadpoint_min_when_no_vehicle_override():
    """No vehicle override → effective floor equals loadpoint min."""
    from custom_components.solar_energy_management.coordinator.decide import (
        MinPlusSolarMode,
    )
    view = _view(is_night=True, ev_min=6, vehicle_min=None, target_kwh=12.0)
    decision = MinPlusSolarMode().decide(view)
    assert decision.commanded_amps == 6


def test_min_plus_solar_day_zone4_uses_vehicle_min():
    """Daytime Zone 4 — when the need-gated floor engages (#501: the
    night window can no longer cover the remaining Min), it commits at
    the effective per-vehicle floor (10 A), not the loadpoint min (6 A).
    The #440 invariant (vehicle_min wins) is preserved under #501's
    gating; the gate is exercised by ``night_deliverable_kwh < target``.
    """
    from custom_components.solar_energy_management.coordinator.decide import (
        MinPlusSolarMode,
    )
    view = _view(is_night=False, soc=95, ev_min=6, vehicle_min=10,
                 target_kwh=14.0, night_deliverable_kwh=0.0)
    decision = MinPlusSolarMode().decide(view)
    assert decision.commanded_amps == 10


def test_min_plus_solar_day_zone4_idles_when_min_covered_by_night():
    """#501 — with the Min covered by the night window
    (``night_deliverable_kwh >= target``), daytime Zone 4 does NOT
    force the floor: zero solar surplus → idle, not a grid-backfilled
    6/10 A floor. Pins the self-consumption-maximizing behavior."""
    from custom_components.solar_energy_management.coordinator.decide import (
        MinPlusSolarMode,
    )
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerIntent,
    )
    view = _view(is_night=False, soc=95, ev_min=6, vehicle_min=10,
                 target_kwh=14.0)  # night_deliverable defaults to inf
    decision = MinPlusSolarMode().decide(view)
    assert decision.intent is ChargerIntent.IDLE, (
        f"Min covered by night → must idle, not floor; got {decision.intent}"
    )
