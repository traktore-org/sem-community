"""#743 — harvesting solar an export-limited inverter hides.

The reporter's inverter sets its export limit to 0 W when the selling
price is negative; production then clamps to local consumption and the
measured surplus reads 0 while the array could deliver kilowatts more.
SEM cannot *measure* its way out — raising consumption is the only way
to see the hidden power, so the probe IS the measurement:

- SUSPECT: forecast says far more than the array delivers, export is
  pinned at ~0, and production ≈ local consumption (the curtailment
  signature — a merely cloudy day fails the forecast term instead).
- PROBE: grant a floor-sized surplus bonus so the normal decide() path
  starts the EV at minimum amps. If production rises to follow within
  the window, the curtailment was real; if not, revoke and cool down
  (a failed probe costs ~2 min of minimum-amps draw, opt-in).
- HARVEST: the risen production makes the loop self-sustaining; a
  one-step bonus keeps the ladder climbing toward the forecast, and
  every step is itself a probe — production must follow or the bonus
  drops and retries later. No step is ever taken on faith.

Everything here is the pure state machine (coordinator/curtailment.py).
Wiring pins live in TestTheGrantReachesDecide below.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.curtailment import (
    CurtailmentProbe,
    ProbeInputs,
)


def _inputs(**kw):
    base = dict(
        enabled=True,
        expected_w=6000.0,      # dampened forecast says the sun is there
        production_w=1000.0,    # the inverter delivers only the house
        export_w=0.0,
        home_w=1000.0,
        battery_charge_w=0.0,
        ev_draw_w=0.0,
        ev_connected=True,
        ev_wants_solar=True,
        probe_floor_w=4140.0,   # the charger's minimum start (6 A × 3 × 230)
    )
    base.update(kw)
    return ProbeInputs(**base)


class TestSuspicion:
    def test_the_curtailment_signature_leads_to_a_probe(self):
        p = CurtailmentProbe()
        p.tick(_inputs(), now=0.0)
        grant = p.tick(_inputs(), now=61.0)  # suspicion held for 60 s

        assert p.state == "probing"
        assert grant >= 4140.0

    def test_a_cloudy_day_is_not_curtailment(self):
        """Production is low but the forecast agrees — nothing hidden."""
        p = CurtailmentProbe()
        p.tick(_inputs(expected_w=1200.0), now=0.0)
        grant = p.tick(_inputs(expected_w=1200.0), now=61.0)

        assert p.state == "idle"
        assert grant == 0.0

    def test_real_export_means_no_curtailment(self):
        """Power is leaving the house — the limit is not active."""
        p = CurtailmentProbe()
        p.tick(_inputs(export_w=800.0), now=0.0)
        grant = p.tick(_inputs(export_w=800.0), now=61.0)

        assert p.state == "idle"
        assert grant == 0.0

    def test_production_far_above_consumption_is_not_the_signature(self):
        """Curtailment clamps production TO consumption; a big gap means
        something else (e.g. export the meter missed) — do not probe."""
        p = CurtailmentProbe()
        i = _inputs(production_w=3000.0, home_w=1000.0)
        p.tick(i, now=0.0)
        p.tick(i, now=61.0)

        assert p.state == "idle"

    def test_no_car_no_probe(self):
        p = CurtailmentProbe()
        i = _inputs(ev_connected=False)
        p.tick(i, now=0.0)
        p.tick(i, now=61.0)

        assert p.state == "idle"

    def test_disabled_grants_nothing_ever(self):
        p = CurtailmentProbe()
        i = _inputs(enabled=False)
        p.tick(i, now=0.0)
        grant = p.tick(i, now=61.0)

        assert p.state == "off"
        assert grant == 0.0

    def test_a_momentary_dip_does_not_probe(self):
        """The signature must HOLD for the suspicion window."""
        p = CurtailmentProbe()
        p.tick(_inputs(), now=0.0)
        p.tick(_inputs(export_w=900.0), now=30.0)  # export blip resets
        p.tick(_inputs(), now=61.0)

        assert p.state != "probing"


class TestTheLimitEntity:
    """Brands that publish their export limit sharpen the detection
    (autodetected — Huawei active power control, GoodWe grid export
    limit, SolarEdge/SolaX export control…). The physics signature
    stays the brand-agnostic fallback when no entity exists."""

    def test_a_known_active_limit_skips_the_consumption_term(self):
        """The inverter SAYS it is limited to ~0 — production≈consumption
        can be noisy with battery dynamics, so don't require it."""
        p = CurtailmentProbe()
        # Battery dynamics make production ≠ home+batt+ev by a lot.
        i = _inputs(home_w=400.0, battery_charge_w=0.0,
                    export_limited=True)
        p.tick(i, now=0.0)
        p.tick(i, now=61.0)

        assert p.state == "probing"

    def test_a_known_inactive_limit_never_probes(self):
        """The inverter SAYS no limit is active — low production is the
        sky's fault, never probe (kills the false-probe cost on brands
        that publish the entity)."""
        p = CurtailmentProbe()
        i = _inputs(export_limited=False)
        p.tick(i, now=0.0)
        p.tick(i, now=61.0)

        assert p.state == "idle"

    def test_unknown_limit_falls_back_to_physics(self):
        p = CurtailmentProbe()
        p.tick(_inputs(export_limited=None), now=0.0)
        p.tick(_inputs(export_limited=None), now=61.0)

        assert p.state == "probing"


class TestTheProbe:
    def _probing(self):
        p = CurtailmentProbe()
        p.tick(_inputs(), now=0.0)
        p.tick(_inputs(), now=61.0)
        assert p.state == "probing"
        return p

    def test_production_following_confirms_the_harvest(self):
        p = self._probing()
        # The EV started at the floor and the inverter un-curtailed.
        followed = _inputs(production_w=5100.0, ev_draw_w=4140.0)
        p.tick(followed, now=100.0)

        assert p.state == "harvest"

    def test_production_not_following_revokes_and_cools_down(self):
        p = self._probing()
        # 2 minutes on, the array never rose — the forecast lied.
        stalled = _inputs(production_w=1050.0, ev_draw_w=4140.0)
        p.tick(stalled, now=100.0)
        grant = p.tick(stalled, now=200.0)  # probe window expired

        assert p.state == "cooldown"
        assert grant == 0.0

    def test_cooldown_blocks_an_immediate_reprobe(self):
        p = self._probing()
        stalled = _inputs(production_w=1050.0, ev_draw_w=4140.0)
        p.tick(stalled, now=200.0)
        assert p.state == "cooldown"
        # The signature is back immediately — but we just burned a probe.
        p.tick(_inputs(), now=260.0)
        p.tick(_inputs(), now=330.0)

        assert p.state == "cooldown"

    def test_cooldown_expires_and_allows_a_new_probe(self):
        p = self._probing()
        stalled = _inputs(production_w=1050.0, ev_draw_w=4140.0)
        p.tick(stalled, now=200.0)
        p.tick(_inputs(), now=1200.0)   # 15 min later, signature holds
        p.tick(_inputs(), now=1261.0)

        assert p.state == "probing"


class TestTheHarvest:
    def _harvesting(self):
        p = CurtailmentProbe()
        p.tick(_inputs(), now=0.0)
        p.tick(_inputs(), now=61.0)
        p.tick(_inputs(production_w=5100.0, ev_draw_w=4140.0), now=100.0)
        assert p.state == "harvest"
        return p

    def test_the_ladder_bonus_keeps_the_climb_alive(self):
        """Self-sustaining at the floor, the measured surplus equals the
        draw — without a bonus the ladder can never offer more. One
        step's worth of headroom keeps it climbing toward the forecast."""
        p = self._harvesting()
        grant = p.tick(
            _inputs(production_w=5100.0, ev_draw_w=4140.0), now=110.0,
        )

        assert 0.0 < grant <= 1000.0

    def test_a_step_that_is_not_followed_drops_the_bonus(self):
        """Production plateaued — the array's potential is reached.
        Offering more would pull the difference from grid/battery."""
        p = self._harvesting()
        plateau = _inputs(production_w=5100.0, ev_draw_w=4830.0)
        p.tick(plateau, now=110.0)
        p.tick(plateau, now=210.0)   # a step window passed, no follow
        grant = p.tick(plateau, now=220.0)

        assert grant == 0.0
        assert p.state == "harvest"

    def test_export_appearing_ends_the_harvest(self):
        """The limit lifted (price went positive) — measured surplus is
        real again and the normal loop needs no help."""
        p = self._harvesting()
        p.tick(_inputs(production_w=5100.0, ev_draw_w=4140.0,
                       export_w=900.0), now=120.0)

        assert p.state == "idle"

    def test_the_car_leaving_ends_the_harvest(self):
        p = self._harvesting()
        p.tick(_inputs(production_w=1000.0, ev_draw_w=0.0,
                       ev_connected=False), now=120.0)

        assert p.state == "idle"

    def test_the_grant_never_exceeds_the_forecast_room(self):
        """Physics cap: never grant more than the forecast says the
        array could still add."""
        p = self._harvesting()
        nearly_there = _inputs(production_w=5800.0, ev_draw_w=4140.0)
        grant = p.tick(nearly_there, now=110.0)

        assert grant <= 6000.0 - 5800.0 + 1e-6
