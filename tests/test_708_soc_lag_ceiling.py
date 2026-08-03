"""#708 — the energy-accounted SOC ceiling beside a slow/polled sensor.

The reported mechanism: OnStar polls the vehicle SOC every 30 minutes, so
SEM steered an 11.5 kW charge on a 30-minute-old reading — 60 % target,
stopped at 67 %. Overshoot = sensor lag × charge power.

The fix: the pack cannot be emptier than the last sensor reading plus what
this session measurably delivered since, so the stop decision uses
``effective_soc = max(sensor, anchor + delivered × 0.92 / capacity)``.
The sensor stays primary (every fresh value re-anchors and wins) — this is
a CAP, not the #446-banned virtual-SOC substitution. When a later reading
lands below target, remaining need goes positive again and charging
auto-resumes; resumes are spaced by the sensor's own update interval and
each round shrinks.

Reporter's numbers throughout: 85 kWh pack, target 60 %, sensor stuck at
55 %, 11.5 kW.
"""
from datetime import datetime, timedelta

import pytest
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    CHARGE_EFFICIENCY,
    EVTaperDetector,
)


CAPACITY = 85.0


def _detector(capacity=CAPACITY):
    return EVTaperDetector({"ev_battery_capacity_kwh": capacity})


def _feed_energy(det, kwh, power_w=11500.0, start=None):
    """Push ``kwh`` through the detector's session integrator at power_w."""
    t = start or datetime(2026, 8, 3, 22, 0, 0)
    hours = kwh / (power_w / 1000.0)
    steps = max(2, int(hours * 360))  # 10 s cycles
    dt_step = timedelta(hours=hours / steps)
    for _ in range(steps + 1):
        det.update(power_w, 16.0, True, t)
        t += dt_step
    return t


def _make_coordinator(config=None, detectors=None):
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = config or {
        "ev_target_type": "soc",
        "ev_target_soc": 60,
        "ev_battery_capacity_kwh": CAPACITY,
        "daily_ev_target": 10,
    }
    if detectors is not None:
        coord._ev_taper_detectors = detectors
    return coord


def _floor(coord, vehicle_soc, charger_cfg=None):
    energy = MagicMock()
    energy.daily_ev = 0.0
    return coord._calculate_remaining_need(
        energy, vehicle_soc=vehicle_soc, charger_cfg=charger_cfg, bound="min"
    )


# ──────────────────────────────────────────────
# Detector: anchor lifecycle + estimate math
# ──────────────────────────────────────────────

class TestAnchorLifecycle:
    def test_bootstrap_anchor_on_first_reading(self):
        det = _detector()
        det.get_virtual_soc(55.0)
        assert det._soc_anchor_value == 55.0
        assert det._soc_anchor_session_kwh == 0.0

    def test_unchanged_reading_does_not_move_anchor(self):
        det = _detector()
        det.get_virtual_soc(55.0)
        _feed_energy(det, 2.0)
        det.get_virtual_soc(55.0)  # poll re-publishes the same stale value
        assert det._soc_anchor_value == 55.0
        assert det._soc_anchor_session_kwh == 0.0

    def test_fresh_value_reanchors(self):
        det = _detector()
        det.get_virtual_soc(55.0)
        _feed_energy(det, 4.0)
        det.get_virtual_soc(58.0)  # sensor catches up
        assert det._soc_anchor_value == 58.0
        assert det._soc_anchor_session_kwh == pytest.approx(4.0, abs=0.05)

    def test_disconnect_clears_anchor_and_latch(self):
        det = _detector()
        det.get_virtual_soc(55.0)
        det._estimate_stop_active = True
        det.reset_session()
        assert det._soc_anchor_value is None
        assert det._soc_anchor_session_kwh is None
        assert det._estimate_stop_active is False

    def test_rebootstrap_after_disconnect_even_without_value_change(self):
        det = _detector()
        det.get_virtual_soc(55.0)
        det.reset_session()
        # Same value again (< 0.5 delta) — the bootstrap path must re-arm,
        # or a session whose target sits inside the sensor's first polling
        # window would run entirely unguarded.
        det.get_virtual_soc(55.0)
        assert det._soc_anchor_value == 55.0


class TestEstimateMath:
    def test_no_anchor_returns_none(self):
        det = _detector()
        assert det.energy_accounted_soc() is None

    def test_zero_capacity_returns_none(self):
        det = _detector(capacity=0)
        det.get_virtual_soc(55.0)
        assert det.energy_accounted_soc() is None

    def test_estimate_advances_with_delivered_energy(self):
        det = _detector()
        det.get_virtual_soc(55.0)
        _feed_energy(det, 4.0)
        expected = 55.0 + 4.0 * CHARGE_EFFICIENCY / CAPACITY * 100.0
        assert det.energy_accounted_soc() == pytest.approx(expected, abs=0.15)

    def test_estimate_caps_at_100(self):
        det = _detector(capacity=10.0)
        det.get_virtual_soc(95.0)
        _feed_energy(det, 3.0, power_w=7000.0)
        assert det.energy_accounted_soc() == 100.0

    def test_estimate_counts_from_anchor_not_session_start(self):
        det = _detector()
        det.get_virtual_soc(50.0)
        _feed_energy(det, 3.0)
        det.get_virtual_soc(53.0)  # re-anchor mid-session
        end = _feed_energy(det, 2.0, start=datetime(2026, 8, 3, 23, 0, 0))
        expected = 53.0 + 2.0 * CHARGE_EFFICIENCY / CAPACITY * 100.0
        assert det.energy_accounted_soc() == pytest.approx(expected, abs=0.15)


# ──────────────────────────────────────────────
# The stop decision — reporter's exact scenario
# ──────────────────────────────────────────────

class TestRemainingNeedCeiling:
    def test_azlinon_scenario_stops_at_target_not_67(self):
        """Sensor frozen at 55 while 5 kWh flow in: the pre-fix path still
        wanted (60−55)% × 85 = 4.25 kWh more; the ceiling says done."""
        det = _detector()
        det.get_virtual_soc(55.0)
        # Enough energy that anchor + delivered×0.92 reaches the 60 % target:
        # (60−55)/100 × 85 / 0.92 = 4.62 kWh
        _feed_energy(det, 4.7)
        coord = _make_coordinator(detectors={"c1": det})
        cfg = {"id": "c1", "ev_target_type": "soc", "ev_target_soc": 60,
               "ev_battery_capacity_kwh": CAPACITY}
        assert _floor(coord, vehicle_soc=55.0, charger_cfg=cfg) == 0

    def test_before_ceiling_reached_sensor_math_unchanged(self):
        det = _detector()
        det.get_virtual_soc(55.0)
        _feed_energy(det, 1.0)  # est ≈ 56.1 — sensor still the binding term? No:
        # effective = max(55, 56.1) = 56.1 → remaining shrinks as energy flows.
        coord = _make_coordinator(detectors={"c1": det})
        cfg = {"id": "c1", "ev_target_type": "soc", "ev_target_soc": 60,
               "ev_battery_capacity_kwh": CAPACITY}
        remaining = _floor(coord, vehicle_soc=55.0, charger_cfg=cfg)
        est = det.energy_accounted_soc()
        assert remaining == pytest.approx((60 - est) / 100 * CAPACITY, abs=0.1)
        assert 0 < remaining < 4.25

    def test_no_detector_falls_back_to_sensor_only(self):
        coord = _make_coordinator(detectors={})
        cfg = {"ev_target_type": "soc", "ev_target_soc": 60,
               "ev_battery_capacity_kwh": CAPACITY}
        assert _floor(coord, vehicle_soc=55.0, charger_cfg=cfg) == pytest.approx(4.25)

    def test_bare_coordinator_without_detector_attr_is_safe(self):
        """The __new__-built harness coordinator has no _ev_taper_detectors."""
        coord = _make_coordinator()
        cfg = {"ev_target_type": "soc", "ev_target_soc": 60,
               "ev_battery_capacity_kwh": CAPACITY}
        assert _floor(coord, vehicle_soc=55.0, charger_cfg=cfg) == pytest.approx(4.25)

    def test_sensor_ahead_of_estimate_wins(self):
        """A fresh reading ABOVE the estimate steers directly (re-anchored)."""
        det = _detector()
        det.get_virtual_soc(55.0)
        _feed_energy(det, 1.0)
        det.get_virtual_soc(59.0)  # car reports more than we estimated
        coord = _make_coordinator(detectors={"c1": det})
        cfg = {"id": "c1", "ev_target_type": "soc", "ev_target_soc": 60,
               "ev_battery_capacity_kwh": CAPACITY}
        assert _floor(coord, vehicle_soc=59.0, charger_cfg=cfg) == pytest.approx(0.85)

    def test_auto_resume_when_late_reading_lands_below_target(self):
        """Estimate stopped the charge; the sensor then reports 58 → need
        goes positive again (the auto-resume Guido chose, no dead band)."""
        det = _detector()
        det.get_virtual_soc(55.0)
        _feed_energy(det, 4.7)  # estimate reached 60, charge stopped
        coord = _make_coordinator(detectors={"c1": det})
        cfg = {"id": "c1", "ev_target_type": "soc", "ev_target_soc": 60,
               "ev_battery_capacity_kwh": CAPACITY}
        assert _floor(coord, vehicle_soc=55.0, charger_cfg=cfg) == 0
        det.get_virtual_soc(58.0)  # fresh reading, below target → re-anchor
        remaining = _floor(coord, vehicle_soc=58.0, charger_cfg=cfg)
        assert remaining == pytest.approx((60 - 58) / 100 * CAPACITY, abs=0.05)

    def test_sensor_unavailable_with_anchor_uses_ceiling_not_full_capacity(self):
        """Mid-session sensor dropout: pre-#708 returned the full capacity
        (charge until taper); with an anchor the estimate keeps counting."""
        det = _detector()
        det.get_virtual_soc(55.0)
        _feed_energy(det, 2.0)
        coord = _make_coordinator(detectors={"c1": det})
        cfg = {"id": "c1", "ev_target_type": "soc", "ev_target_soc": 60,
               "ev_battery_capacity_kwh": CAPACITY}
        remaining = _floor(coord, vehicle_soc=None, charger_cfg=cfg)
        est = det.energy_accounted_soc()
        assert remaining == pytest.approx((60 - est) / 100 * CAPACITY, abs=0.1)
        assert remaining < CAPACITY

    def test_sensor_unavailable_without_anchor_keeps_full_capacity(self):
        det = _detector()  # never saw a reading
        coord = _make_coordinator(detectors={"c1": det})
        cfg = {"id": "c1", "ev_target_type": "soc", "ev_target_soc": 60,
               "ev_battery_capacity_kwh": CAPACITY}
        assert _floor(coord, vehicle_soc=None, charger_cfg=cfg) == CAPACITY

    def test_kwh_mode_never_consults_the_ceiling(self):
        det = _detector()
        det.get_virtual_soc(55.0)
        _feed_energy(det, 4.7)
        coord = _make_coordinator(
            config={"ev_target_type": "kwh", "daily_ev_target": 10,
                    "ev_battery_capacity_kwh": CAPACITY},
            detectors={"c1": det},
        )
        cfg = {"id": "c1", "ev_target_type": "kwh", "daily_ev_target": 10}
        energy = MagicMock()
        energy.daily_ev = 3.0
        coord._charger_daily_kwh = lambda cid, e: 3.0
        remaining = coord._calculate_remaining_need(
            energy, vehicle_soc=None, charger_cfg=cfg, bound="min"
        )
        assert remaining == pytest.approx(7.0)

    def test_two_chargers_use_their_own_anchors(self):
        det_a = _detector()
        det_a.get_virtual_soc(55.0)
        _feed_energy(det_a, 4.7)          # A's estimate at target
        det_b = _detector()
        det_b.get_virtual_soc(55.0)       # B delivered nothing
        coord = _make_coordinator(detectors={"a": det_a, "b": det_b})
        cfg_a = {"id": "a", "ev_target_type": "soc", "ev_target_soc": 60,
                 "ev_battery_capacity_kwh": CAPACITY}
        cfg_b = {"id": "b", "ev_target_type": "soc", "ev_target_soc": 60,
                 "ev_battery_capacity_kwh": CAPACITY}
        assert _floor(coord, vehicle_soc=55.0, charger_cfg=cfg_a) == 0
        assert _floor(coord, vehicle_soc=55.0, charger_cfg=cfg_b) == pytest.approx(4.25)


# ──────────────────────────────────────────────
# Restart safety
# ──────────────────────────────────────────────

class TestRestartSafety:
    def test_anchor_not_persisted(self):
        """get_state must not carry the session anchor — a restored anchor
        against a reset session-energy counter would over-credit the pack."""
        det = _detector()
        det.get_virtual_soc(55.0)
        _feed_energy(det, 4.0)
        state = det.get_state()
        fresh = _detector()
        fresh.restore_state(state)
        assert fresh._soc_anchor_value is None
        assert fresh.energy_accounted_soc() is None
