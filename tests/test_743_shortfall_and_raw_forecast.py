"""#743 — two holes found auditing the shipped probe against the
reporter's own worked example (5 kW forecast, 1 kW delivered, 0 export).

1. **The probe suspected curtailment with a forecast the curtailment
   itself had dampened.** ``dampening_factor`` is computed live from
   today's actual-vs-forecast ratio — and a curtailed day's actual is
   clamped to consumption, so the factor sinks all day and the probe
   measures its own blindness. The 1.8 half fixed exactly this one
   layer up (probe-confirmed days no longer teach the tracker) and its
   commit message names the class: "every dampened consumer under-plans
   exactly the hidden kilowatts the probe reveals." The probe is also a
   dampened consumer, and was missed. Suspicion now reads the RAW
   forecast — optimism costs one bounded failed probe, which is the
   probe's whole design.

2. **The room test was a cost guard in the one scenario where the cost
   sign is inverted.** With a 3-phase 6 A floor (4140 W) the reporter's
   literal example hides 4000 W — the signature refused over the missing
   140 W, on every dampening setting, even when the inverter EXPLICITLY
   reported its export limit active. Importing ~140 W to unlock 4 kW of
   otherwise-thrown-away solar is the right trade whenever curtailment
   is real (negative prices, or a zero-feed-in install at ANY price), so
   the probe may now overdraw the hidden room by a bounded shortfall:
   10 % of the charger floor. No new mode, no new knob — the probe's
   opt-in is the consent, the bound caps the worst case at ~4 ct/h.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.curtailment import (
    CurtailmentProbe, ProbeInputs, PROBE_MARGIN_W, SUSPECT_HOLD_S,
)

FLOOR_3P = 6 * 230 * 3  # 4140 W — the reporter's charger class


def _inputs(expected_w, production_w, floor_w=FLOOR_3P, **kw):
    defaults = dict(
        enabled=True, export_w=0.0, home_w=production_w,
        battery_charge_w=0.0, ev_draw_w=0.0, ev_connected=True,
        ev_wants_solar=True,
    )
    defaults.update(kw)
    return ProbeInputs(
        expected_w=expected_w, production_w=production_w,
        probe_floor_w=floor_w, **defaults,
    )


@pytest.mark.unit
class TestBoundedShortfall:

    def test_the_reporters_own_example_now_probes(self) -> None:
        # 5 kW forecast, 1 kW delivered, 0 export, 3-phase floor: 4000 W
        # hidden vs 4140 W needed — a 140 W shortfall, well inside the
        # 10 % bound, must not veto the probe.
        p = CurtailmentProbe()
        i = _inputs(5000.0, 1000.0)
        p.tick(i, now=0.0)
        grant = p.tick(i, now=SUSPECT_HOLD_S + 1.0)
        assert p.state == "probing"
        # The grant must actually reach the floor, or decide() can never
        # start the charger it was granted for.
        assert grant >= FLOOR_3P
        assert grant <= FLOOR_3P + PROBE_MARGIN_W

    def test_the_shortfall_is_bounded_not_faith(self) -> None:
        # 3.5 kW hidden vs 4140 W floor: 640 W short, beyond the 10 %
        # bound (414 W) — refused. The bound is the whole point.
        p = CurtailmentProbe()
        i = _inputs(4000.0, 500.0)
        p.tick(i, now=0.0)
        p.tick(i, now=SUSPECT_HOLD_S + 1.0)
        assert p.state != "probing"

    def test_a_room_covering_floor_is_unchanged(self) -> None:
        p = CurtailmentProbe()
        i = _inputs(6000.0, 1000.0)
        p.tick(i, now=0.0)
        grant = p.tick(i, now=SUSPECT_HOLD_S + 1.0)
        assert p.state == "probing"
        assert grant == pytest.approx(FLOOR_3P + PROBE_MARGIN_W)


class _GrantStub:
    """Host for the real ``_curtailment_grant_w`` (pattern:
    test_743_probe_observability.py) — here with a dampening factor a
    curtailed day would actually have."""
    _curtailment_grant_w = SEMCoordinator._curtailment_grant_w

    def __init__(self, *, power_now_w, dampening):
        self.config = {
            "curtailment_probe_enabled": True,
            "ev_min_current": 6, "ev_voltage": 230, "ev_phases": 3,
            "ev_charge_mode": "solar_only",
            "solar_production_sensor": "sensor.solar",
        }
        self.hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _e: None), data={},
        )
        self._sensor_reader = SimpleNamespace(
            detect_export_limit_entity=lambda _a: None,
        )
        self._cycle_forecast = SimpleNamespace(
            available=True, power_now_w=power_now_w,
        )
        self._forecast_tracker = SimpleNamespace(
            apply_dampening=lambda kw: kw * dampening,
        )


@pytest.mark.unit
class TestSuspicionReadsTheRawForecast:

    def test_a_sunken_dampening_factor_cannot_blind_the_probe(self) -> None:
        """The curtailed day drove dampening to its 0.5 clamp floor —
        dampened 'expected' (3 kW) minus production (1 kW) is under the
        floor, so the OLD read never suspects. The raw sky says 6 kW."""
        s = _GrantStub(power_now_w=6000.0, dampening=0.5)
        power = SimpleNamespace(
            solar_power=1000.0, grid_export_power=0.0,
            home_consumption_power=1000.0, battery_charge_power=0.0,
            ev_power=0.0, ev_connected=True,
        )
        s._curtailment_grant_w(power)
        assert s._curtailment_last["expected_w"] == pytest.approx(6000.0)
        assert s._curtailment_last["state"] == "suspect"
