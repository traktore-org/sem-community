"""Night-remaining must be measured on the DISPLAYED daily basis.

PROD 2026-07-17 23:10: user raised the daily target to 14.5 kWh with the
dashboard showing "Today 13.1 kWh" — night charging stayed idle with
"target reached (remaining=0.00)". Root cause: ``_calculate_remaining_need``
read the RAW per-charger integrator (15.42 kWh, drifted high during a flap
incident) while the dashboard shows the persisted global ``daily_ev``
(13.09). Same quantity, two accumulators — the paired-figure basis-mismatch
class (BUG_CLASSES #11). The user tunes the target against the displayed
figure, so every decision/preview read now routes through
``_charger_daily_kwh`` (which applies the #536 single-charger global
substitution ``_per_charger_daily_report`` already had).
"""
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _coord(*, raw_per_charger, global_daily, chargers):
    """Stub with just what the accessor + remaining-need read."""
    c = SimpleNamespace(
        config={"ev_chargers": chargers},
        _daily_ev_per_charger=dict(raw_per_charger),
    )
    c.primary_charger_id = lambda: (chargers[0].get("id") or "ev_charger")
    c._per_charger_daily_report = (
        lambda energy: SEMCoordinator._per_charger_daily_report(c, energy)
    )
    c._charger_daily_kwh = (
        lambda cid, energy: SEMCoordinator._charger_daily_kwh(c, cid, energy)
    )
    c._resolve_target = (
        lambda cfg, key, bound, default, full:
        SEMCoordinator._resolve_target(c, cfg, key, bound, default, full)
    )
    return c


ENERGY = SimpleNamespace(daily_ev=13.09)
CFG = {"id": "ev_charger", "daily_ev_target": 14.5, "ev_target_type": "kwh"}


@pytest.mark.unit
class TestNightRemainingDisplayBasis:
    def test_single_charger_uses_displayed_global_not_raw_integrator(self):
        """The PROD repro: raw integrator 15.42 vs displayed 13.09 —
        remaining must be 14.5 − 13.09 = 1.41, NOT 0."""
        c = _coord(raw_per_charger={"ev_charger": 15.42},
                   global_daily=13.09, chargers=[CFG])
        remaining = SEMCoordinator._calculate_remaining_need(
            c, ENERGY, None, CFG, bound="min")
        assert remaining == pytest.approx(1.41, abs=0.01)

    def test_single_charger_target_actually_reached(self):
        """Displayed global ≥ target → genuinely reached (0)."""
        c = _coord(raw_per_charger={"ev_charger": 10.0},
                   global_daily=13.09, chargers=[CFG])
        cfg = {**CFG, "daily_ev_target": 12.0}
        remaining = SEMCoordinator._calculate_remaining_need(
            c, ENERGY, None, cfg, bound="min")
        assert remaining == 0

    def test_multi_charger_keeps_per_charger_accounting(self):
        """Two chargers: each measures against ITS OWN accumulator."""
        chargers = [CFG, {"id": "wb2", "daily_ev_target": 5.0,
                          "ev_target_type": "kwh"}]
        c = _coord(raw_per_charger={"ev_charger": 12.0, "wb2": 2.0},
                   global_daily=14.0, chargers=chargers)
        r1 = SEMCoordinator._calculate_remaining_need(
            c, ENERGY, None, CFG, bound="min")
        r2 = SEMCoordinator._calculate_remaining_need(
            c, ENERGY, None, chargers[1], bound="min")
        assert r1 == pytest.approx(2.5, abs=0.01)   # 14.5 − 12.0 (own accum)
        assert r2 == pytest.approx(3.0, abs=0.01)   # 5.0 − 2.0
