"""#708 — replay @Azlinon's actual sessions through the real detector.

A LIVE reproduction on the sim rig is impossible: the SOC-anchor and
energy-accounting path runs only through the observer-gated per-charger
loop, so on .46 (observer on) the estimate never anchors — confirmed
22.08 (the estimate sat at the raw 58 % for nine minutes while 11 kW
"flowed", because SEM correctly was not charging). This is the same
constraint that put #589 and #804 on in-process oracles instead.

So this replays his two reported sessions through the REAL
``EVTaperDetector`` — the exact object the coordinator drives — with a
hand-advanced clock. It is the faithful end-to-end proof that the live
rig cannot give, and it is his numbers, not invented ones.

The three #708 unit files pin the pieces (ceiling math, sign, provenance
line). This pins the WHOLE session behaving, which is what "closure"
means to the reporter.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    CHARGE_EFFICIENCY,
    EVTaperDetector,
)


def _deliver(det, kwh, *, power_w=11500.0, start):
    """Push ``kwh`` of real charging through the detector's integrator,
    exactly as the per-charger loop would, 10 s at a time."""
    t = start
    hours = kwh / (power_w / 1000.0)
    steps = max(2, int(hours * 360))
    dt = timedelta(hours=hours / steps)
    for _ in range(steps + 1):
        det.update(power_w, 16.0, True, t)
        t += dt
    return t


@pytest.mark.unit
class TestAzlinonSessionReplay:

    def test_frozen_sensor_estimate_walks_up_not_down(self):
        """His second report: 85 kWh Blazer, started 36 %, let it reach 38 %,
        then STOPPED OnStar so the sensor froze. The car kept charging and the
        EVSE metered 11.5 kWh; "SOC (EST.)" walked DOWN 32 % → 25 %. His own
        arithmetic: 11.5/85 × 0.92 ≈ 12.4 %, the amount of the *decrease*.
        After the fix the same 11.5 kWh must ADD ~12.4 %."""
        det = EVTaperDetector({"ev_battery_capacity_kwh": 85})
        t = datetime(2026, 8, 3, 22, 0, 0)

        # Live reading anchors at 38 %, then OnStar goes dark.
        t = _deliver(det, 0.2, start=t)          # a little draw before the freeze
        det.get_virtual_soc(38.0)                # the last real reading
        anchored = det.energy_accounted_soc()
        assert anchored == pytest.approx(38.0, abs=0.5), anchored

        # Sensor frozen: 11.5 kWh delivered with NO new reading.
        _deliver(det, 11.5, start=t)
        after = det.energy_accounted_soc()

        expected = 38.0 + 11.5 * CHARGE_EFFICIENCY / 85 * 100      # ≈ 50.4 %
        assert after == pytest.approx(expected, abs=0.6), (after, expected)
        assert after > anchored, "the estimate walked DOWN — the #708 sign bug is back"

    def test_stale_sensor_does_not_overshoot_the_target(self):
        """His first report: EVSE set to stop at 60 %, OnStar 30 min stale, an
        11.5 kW charge overshot to 67 %. Overshoot = lag × power. The ceiling
        must reach the target off a stale reading, so the stop can fire while
        the sensor still lags."""
        det = EVTaperDetector({"ev_battery_capacity_kwh": 40})
        t = datetime(2026, 8, 3, 22, 0, 0)

        det.get_virtual_soc(58.0)                # stale reading, target is 60
        # 0.8 kWh lifts a 40 kWh pack ~2 %: 58 → 60 by measured energy alone.
        _deliver(det, 0.8 / CHARGE_EFFICIENCY, start=t)
        eff = det.energy_accounted_soc()

        assert eff >= 60.0, (
            f"effective SOC {eff:.1f}% never reached the 60% target off a "
            "stale 58% sensor — the charge would overshoot as it did to 67%"
        )
        # And the sensor is untouched — this CAPS, it does not replace (#446).
        assert det._last_real_soc == 58.0

    def test_a_fresh_reading_always_re_anchors(self):
        """The sensor stays primary: a new value wins over the accumulated
        estimate, so the cap can only ever pull the stop EARLIER, never hold a
        charge past a real reading."""
        det = EVTaperDetector({"ev_battery_capacity_kwh": 40})
        t = datetime(2026, 8, 3, 22, 0, 0)
        det.get_virtual_soc(58.0)
        t = _deliver(det, 2.0, start=t)          # estimate now well above 58
        assert det.energy_accounted_soc() > 60.0

        det.get_virtual_soc(55.0)                # a fresh, LOWER real reading
        assert det.energy_accounted_soc() == pytest.approx(55.0, abs=0.5), (
            "a fresh sensor value did not re-anchor — the estimate outranked "
            "the sensor, which is the #446 line this must never cross"
        )
