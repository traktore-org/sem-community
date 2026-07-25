"""#461 residual triage — balance-check noise + delegated-mode labels.

RienduPre's 2026-06-12 beta.10 dump: flows finally coherent, but
(1) ``diag_health_violations: 69`` with WARNING spam — every one a
re-report of the home-consumption hold bridging a Growatt solar
sensor frozen for ~5 min (``home_consumption_power`` is the residual
of the other readings, so supply≈demand is an identity UNLESS the
clamp/hold fired); and (2) ``charging_strategy: "solar_only: …"`` on
chargers configured ``solar_plus_cheap``, reading like the configured
mode was ignored.
"""
import logging

import pytest
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import decide


def _power(**overrides):
    defaults = dict(
        solar_power=4192.0, grid_import_power=0.0,
        battery_discharge_power=0.0,
        # Held home value + live EV reading — the user's exact
        # supply=4192W / demand=9310W shape.
        home_consumption_power=2811.0, ev_power=4513.0,
        grid_export_power=1558.0, battery_charge_power=428.0,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


@pytest.mark.unit
class TestBalanceCheckDuringHomeHold:
    def test_gap_not_a_violation_while_hold_active(self, caplog):
        hc = HealthCheck()
        with caplog.at_level(logging.DEBUG):
            violations = hc.run_all_checks(_power(), home_hold_active=True)
        assert violations == []
        assert hc.total_violations == 0
        # Still observable at debug for diagnose dumps.
        assert any(
            "bridged by the home-consumption hold" in r.message
            for r in caplog.records if r.levelno == logging.DEBUG
        )

    def test_gap_still_fires_without_hold(self):
        hc = HealthCheck()
        violations = hc.run_all_checks(_power(), home_hold_active=False)
        assert any(v.startswith("Energy balance:") for v in violations)

    def test_hold_does_not_mask_other_violations(self):
        # The hold flag must scope to the balance identity only — a negative
        # reading is an independent integrity violation and still fires.
        #
        # #661: this used to also assert an "import and export both active"
        # violation, built by hand-setting both fields on a MagicMock. No
        # production path can produce that state — ``calculate_derived``
        # re-derives both from one signed scalar — so the assertion proved only
        # that the test could bypass the derivation. Split-pair exclusivity is
        # now audited at the netting site instead; see
        # ``tests/test_661_split_pair_exclusivity.py``.
        hc = HealthCheck()
        violations = hc.run_all_checks(
            _power(solar_power=-500.0, grid_import_power=200.0),
            home_hold_active=True,
        )
        assert any("solar_power is negative" in v for v in violations)
        assert not any(v.startswith("Energy balance:") for v in violations)

    def test_balanced_cycle_unaffected(self):
        hc = HealthCheck()
        violations = hc.run_all_checks(
            _power(
                solar_power=6260.0, grid_import_power=1492.0,
                home_consumption_power=2811.0, ev_power=4513.0,
                grid_export_power=0.0, battery_charge_power=428.0,
            ),
            home_hold_active=False,
        )
        assert violations == []


def _view(
    mode: str,
    *,
    solar_w: float = 7000.0,
    home_w: float = 500.0,
    battery_soc: float = 92.0,
    tariff_level: str | None = "normal",
    is_night: bool = False,
) -> ChargerView:
    return ChargerView(
        power=ChargerPower(charger_id="wb", power_w=0.0, connected=True, charging=False),
        energy=ChargerEnergy(charger_id="wb"),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=FleetContext(
            solar_w=solar_w, home_w=home_w, battery_soc=battery_soc,
            is_night=is_night, tariff_level=tariff_level,
        ),
    )


@pytest.mark.unit
class TestDelegatedModeLabels:
    def test_solar_plus_cheap_day_normal_keeps_mode_label(self):
        decision = decide(_view("solar_plus_cheap"))
        assert decision.mode == "solar_plus_cheap"
        assert decision.reason.startswith("solar_plus_cheap day: tariff=normal")
        # Inner solar_only detail preserved for diagnostics.
        assert "solar_only:" in decision.reason
        assert decision.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_solar_plus_cheap_day_normal_idle_below_min(self):
        # The user's dump shape: surplus 3293W < 4140W min → idle,
        # but the strategy string must still name solar_plus_cheap.
        decision = decide(_view("solar_plus_cheap", solar_w=3800.0))
        assert decision.intent is ChargerIntent.IDLE
        assert decision.mode == "solar_plus_cheap"
        assert decision.reason.startswith("solar_plus_cheap day:")

    def test_solar_plus_cheap_expensive_pause_label_unchanged(self):
        decision = decide(_view("solar_plus_cheap", tariff_level="expensive"))
        assert decision.mode == "solar_plus_cheap"
        assert "pausing grid imports" in decision.reason

    def test_min_plus_solar_day_zone2_keeps_mode_label(self):
        # SOC 50 with defaults (priority 30, buffer 70) → Zone 2 →
        # delegates to solar_only; label must say min_plus_solar.
        decision = decide(_view("min_plus_solar", battery_soc=50.0))
        assert decision.mode == "min_plus_solar"
        assert decision.reason.startswith("min_plus_solar day Zone 2")
        assert "solar_only:" in decision.reason
