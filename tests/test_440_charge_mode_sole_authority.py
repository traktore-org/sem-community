"""#440 — charge mode is the sole authority on whether to charge.

Pre-#440, ``coordinator/ev_control.py:_calculate_forecast_night_target``
ran two override paths (SOC-based skip + solar-forecast-based reduction)
that could zero out the night target even when the user's mode and Min
slider said "charge tonight". This violated the architectural principle
established for v1.7.1-beta.4:

> The truth sources for SEM are the user's sliders (Min / Max), the
> charge mode, and — only if target type is ``%`` — the real vehicle SOC.

These tests pin the post-#440 behaviour:

1. No forecast night-target path remains at all (#1318 removed the
   pass-through and the mode-derived smart-night switch).
2. (folded into 1.)
3. The skip-decision API surface is gone: ``calculate_nights_until_charge``,
   ``record_skip``, ``reset_skips``, ``_consecutive_skips``,
   ``notify_ev_charge_skip``, ``notify_ev_charge_recommended``.
4. The corresponding sensor entity keys (``ev_charge_needed``,
   ``ev_nights_until_charge``, ``ev_charge_skip_reason``) are no longer
   present in ``SENSOR_TYPES``.
"""
from __future__ import annotations



from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)


# ───────────────────────────────────────────────────────────────────
# 1. No reduction path exists at all (#1318)
# ───────────────────────────────────────────────────────────────────


def test_no_forecast_night_target_path_remains():
    """#440 made ``_calculate_forecast_night_target`` a pass-through; #1318
    removed it and the mode-derived smart-night switch with it. The night
    target is the user's remaining floor, read straight from the counters —
    no method may stand between the two again."""
    from pathlib import Path
    root = Path(__file__).parent.parent
    for rel in ("coordinator/coordinator.py", "coordinator/ev_control.py",
                "consts/ev_charge_modes.py"):
        src = (root / rel).read_text()
        for name in ("_calculate_forecast_night_target", "_mode_uses_smart_night",
                     "_smart_night_charging_enabled", "MODE_USES_SMART_NIGHT"):
            assert name not in src, f"{rel} still names {name}"


# ──────────────────────────────────────────────
# 2. Removed API surface — pin the deletions
# ──────────────────────────────────────────────


class TestRemovedAPIs:
    """The skip-decision API surface is gone. These tests fail loudly if
    anyone resurrects it without re-evaluating the architectural choice."""

    def test_detector_has_no_calculate_nights_until_charge(self):
        det = EVTaperDetector({})
        assert not hasattr(det, "calculate_nights_until_charge"), (
            "calculate_nights_until_charge resurrected — see #440."
        )

    def test_detector_has_no_record_skip(self):
        det = EVTaperDetector({})
        assert not hasattr(det, "record_skip")

    def test_detector_has_no_reset_skips(self):
        det = EVTaperDetector({})
        assert not hasattr(det, "reset_skips")

    def test_detector_has_no_consecutive_skips_field(self):
        det = EVTaperDetector({})
        assert not hasattr(det, "_consecutive_skips")

    def test_intelligence_data_has_no_charge_needed(self):
        from custom_components.solar_energy_management.coordinator.types import (
            EVIntelligenceData,
        )
        d = EVIntelligenceData()
        assert not hasattr(d, "charge_needed")
        assert not hasattr(d, "nights_until_charge")
        assert not hasattr(d, "charge_skip_reason")

    def test_notification_manager_has_no_skip_methods(self):
        from custom_components.solar_energy_management.coordinator.notifications import (
            NotificationManager,
        )
        assert not hasattr(NotificationManager, "notify_ev_charge_skip")
        assert not hasattr(NotificationManager, "notify_ev_charge_recommended")


# ──────────────────────────────────────────────
# 3. Sensor entity registry — keys are gone
# ──────────────────────────────────────────────


def test_obsolete_sensor_keys_absent_from_registry():
    from custom_components.solar_energy_management import sensor as sem_sensor
    keys = {d.key for d in sem_sensor.SENSOR_TYPES}
    for obsolete in ("ev_charge_needed", "ev_nights_until_charge",
                     "ev_charge_skip_reason"):
        assert obsolete not in keys, (
            f"sensor.{obsolete} resurrected — see #440. Charge mode is "
            "the sole authority on charging now."
        )


# ──────────────────────────────────────────────
# 4. Persistence — old payloads remain readable
# ──────────────────────────────────────────────


def test_restore_state_ignores_legacy_consecutive_skips():
    """A legacy payload with the removed ``consecutive_skips`` key must
    still restore cleanly (forward-compat for users upgrading from
    v1.7.1-beta.3)."""
    det = EVTaperDetector({"ev_battery_capacity_kwh": 40})
    det.restore_state({
        "last_full_charge": "2026-06-01T10:00:00",
        "energy_since_full": 5.0,
        "estimated_soc": 87.5,
        "battery_health_samples": [],
        "battery_health_pct": 98.0,
        "consecutive_skips": 4,   # legacy field — must be silently ignored
        "soc_anchored": True,
        "hw_total_at_full": 1234.5,
    })
    assert det._estimated_soc == 87.5
    assert det._soc_anchored is True
    assert det._hw_total_at_full == 1234.5
    assert not hasattr(det, "_consecutive_skips")
