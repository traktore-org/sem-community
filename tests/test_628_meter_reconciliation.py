"""#628 — grid/battery daily energy follows the hardware meters.

The user declares their utility meter and BMS counters in HA's Energy
Dashboard. Until now SEM read those registers exactly ONCE, at boot, to seed
lifetime totals; the daily grid/battery rows — the ones the user compares
against the Energy Dashboard — were pure power integration. Every dropped or
mis-signed power sample stayed in them for the rest of the day (reporter: SEM
export 3.06 kWh against a meter reading 0.16 kWh, with import short by almost
exactly the same amount).

Same baseline/anchor/delta model as #556/#658, with three differences that get
their own tests here: BIDIRECTIONAL adoption, ALL-OR-NOTHING per category, and
no sun gate.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
    METER_RECONCILIATION_THRESHOLD,
)

TODAY = date(2026, 7, 26)
MONTH = "2026_7"
YEAR = "2026"

IMPORT_METER = "sensor.p1_import"
EXPORT_METER = "sensor.p1_export"


def _state(value, unit="kWh"):
    return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit})


def _hass_with(states: dict):
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    return hass


def _calc(states, mapping=None, enabled=True, config=None):
    calc = EnergyCalculator(config=config or {}, time_manager=MagicMock())
    calc.configure_meter_counters(
        _hass_with(states),
        mapping if mapping is not None else {"grid_import": [IMPORT_METER]},
        enabled,
    )
    return calc


def _reconcile(calc, category="grid_import", **kwargs):
    calc._reconcile_metered_energy(category, TODAY, MONTH, YEAR, **kwargs)


def _daily(calc, category="grid_import"):
    return calc._daily_accumulators.get(f"{category}_{TODAY}", 0.0)


@pytest.mark.unit
class TestMeterReconciliation:

    def test_lifetime_register_tracks_the_daily_row(self):
        states = {IMPORT_METER: _state(12345.0)}
        calc = _calc(states)
        _reconcile(calc)  # baseline at 12345, integrated 0
        assert _daily(calc) == 0.0

        states[IMPORT_METER] = _state(12348.2)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(3.2)

    def test_correction_is_bidirectional(self):
        """The whole point: a meter can prove the integrator over-counted.

        Upward-only (#556/#658) can never fix the reporter's export row.
        """
        states = {EXPORT_METER: _state(500.0)}
        calc = _calc(states, {"grid_export": [EXPORT_METER]})
        # The integrator has already booked 3.06 kWh of export today from
        # mis-signed grid samples; the meter says 0.16.
        calc._daily_accumulators[f"grid_export_{TODAY}"] = 3.06
        calc._monthly_accumulators[f"grid_export_{MONTH}"] = 50.0
        _reconcile(calc, "grid_export")  # anchor lands on 3.06
        states[EXPORT_METER] = _state(500.16)
        calc._daily_accumulators[f"grid_export_{TODAY}"] = 3.06
        # anchor was taken at 3.06, so target = 3.06 + 0.16 — the anchor
        # protects pre-baseline energy. Re-anchor as a mid-day restart would:
        calc._meter_baselines["grid_export"]["anchor"] = 0.0
        _reconcile(calc, "grid_export")
        assert _daily(calc, "grid_export") == pytest.approx(0.16)
        # ...and the month came down with it.
        assert calc._monthly_accumulators[f"grid_export_{MONTH}"] == pytest.approx(
            50.0 - 2.90
        )

    def test_a_longer_period_is_never_dragged_below_zero(self):
        states = {IMPORT_METER: _state(100.0)}
        calc = _calc(states)
        calc._daily_accumulators[f"grid_import_{TODAY}"] = 8.0
        calc._monthly_accumulators[f"grid_import_{MONTH}"] = 1.0
        _reconcile(calc)
        calc._meter_baselines["grid_import"]["anchor"] = 0.0
        _reconcile(calc)
        assert _daily(calc) == 0.0
        assert calc._monthly_accumulators[f"grid_import_{MONTH}"] == 0.0

    def test_partial_counter_set_is_skipped_entirely(self):
        """All-or-nothing: a two-tariff meter with one register unavailable
        must NOT look like the day shrank — the upward-only safety net that
        made a partial set harmless is gone here."""
        t1, t2 = "sensor.p1_t1", "sensor.p1_t2"
        states = {t1: _state(1000.0), t2: _state(2000.0)}
        calc = _calc(states, {"grid_import": [t1, t2]})
        _reconcile(calc)
        states[t1] = _state(1004.0)
        states[t2] = _state(2001.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(5.0)

        # t2 drops out — the row must hold, not fall to t1's delta alone.
        states[t2] = SimpleNamespace(state="unavailable", attributes={})
        states[t1] = _state(1006.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(5.0)

        # ...and when it returns, the energy it counted while away is still
        # owed: the baseline was NOT rolled forward during the outage.
        states[t2] = _state(2003.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(9.0)

    def test_a_register_reset_rebaselines_without_losing_the_day(self):
        states = {IMPORT_METER: _state(9.0)}  # daily-type register
        calc = _calc(states)
        _reconcile(calc)
        states[IMPORT_METER] = _state(11.5)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(2.5)

        states[IMPORT_METER] = _state(0.2)  # midnight reset / meter reboot
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(2.5)  # nothing lost
        states[IMPORT_METER] = _state(1.2)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(3.5)  # and nothing double-counted

    def test_costs_move_with_the_energy(self):
        states = {IMPORT_METER: _state(0.0)}
        calc = _calc(states)
        _reconcile(calc, cost_key="cost_import", rate=0.30)
        states[IMPORT_METER] = _state(4.0)
        _reconcile(calc, cost_key="cost_import", rate=0.30)
        assert calc._daily_cost_accumulators[f"cost_import_{TODAY}"] == pytest.approx(1.2)

    def test_disabled_by_prefer_hardware_energy_off(self):
        states = {IMPORT_METER: _state(1000.0)}
        calc = _calc(states, enabled=False)
        _reconcile(calc)
        states[IMPORT_METER] = _state(1005.0)
        _reconcile(calc)
        assert _daily(calc) == 0.0

    def test_no_sun_gate_for_a_grid_register(self):
        """#681 keeps the solar YIELD counter out of the night because it does
        not measure PV production. A grid import register measures grid import
        at 03:00 exactly as it does at noon — gating it would be the same
        mistake in reverse."""
        states = {IMPORT_METER: _state(700.0), "sun.sun": _state("below_horizon")}
        calc = _calc(states)
        _reconcile(calc)
        states[IMPORT_METER] = _state(702.5)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(2.5)

    def test_noise_below_the_threshold_stays_with_the_integrator(self):
        states = {IMPORT_METER: _state(100.0)}
        calc = _calc(states)
        _reconcile(calc)
        states[IMPORT_METER] = _state(100.0 + METER_RECONCILIATION_THRESHOLD / 2)
        _reconcile(calc)
        assert _daily(calc) == 0.0

    def test_absurd_target_is_refused(self):
        """A Wh register mis-declared as kWh is 1000× out."""
        states = {IMPORT_METER: _state(0.0)}
        calc = _calc(states)
        _reconcile(calc)
        states[IMPORT_METER] = _state(4_000_000.0)
        _reconcile(calc)
        assert _daily(calc) == 0.0

    def test_day_rollover_starts_fresh_baselines(self):
        states = {IMPORT_METER: _state(1000.0)}
        calc = _calc(states)
        _reconcile(calc)
        states[IMPORT_METER] = _state(1006.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(6.0)

        tomorrow = date(2026, 7, 27)
        calc._reconcile_metered_energy("grid_import", tomorrow, MONTH, YEAR)
        states[IMPORT_METER] = _state(1007.5)
        calc._reconcile_metered_energy("grid_import", tomorrow, MONTH, YEAR)
        assert calc._daily_accumulators[f"grid_import_{tomorrow}"] == pytest.approx(1.5)
        assert _daily(calc) == pytest.approx(6.0)  # yesterday untouched

    def test_categories_are_independent(self):
        states = {IMPORT_METER: _state(10.0), EXPORT_METER: _state(20.0)}
        calc = _calc(
            states,
            {"grid_import": [IMPORT_METER], "grid_export": [EXPORT_METER]},
        )
        _reconcile(calc, "grid_import")
        _reconcile(calc, "grid_export")
        states[IMPORT_METER] = _state(13.0)
        states[EXPORT_METER] = _state(21.0)
        _reconcile(calc, "grid_import")
        _reconcile(calc, "grid_export")
        assert _daily(calc, "grid_import") == pytest.approx(3.0)
        assert _daily(calc, "grid_export") == pytest.approx(1.0)


@pytest.mark.unit
class TestMeterBaselinePersistence:

    def test_baselines_survive_a_restart(self):
        states = {IMPORT_METER: _state(1000.0)}
        calc = _calc(states)
        _reconcile(calc)
        states[IMPORT_METER] = _state(1002.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(2.0)

        blob = calc.get_state()
        assert "meter_baselines" in blob

        # SEM restarts; the meter kept counting while it was down.
        fresh = _calc(states)
        fresh.restore_state(blob)
        states[IMPORT_METER] = _state(1005.0)
        fresh._reconcile_metered_energy("grid_import", TODAY, MONTH, YEAR)
        # 5 kWh since this morning's baseline, including the downtime — not
        # 0 (which is what re-baselining at the current value would give).
        assert fresh._daily_accumulators[f"grid_import_{TODAY}"] == pytest.approx(5.0)

    def test_corrupt_blob_does_not_poison_other_categories(self):
        states = {IMPORT_METER: _state(1000.0)}
        calc = _calc(states)
        calc.restore_state({"meter_baselines": {"grid_import": "not-a-dict"}})
        assert "grid_import" not in calc._meter_baselines
        _reconcile(calc)
        states[IMPORT_METER] = _state(1003.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(3.0)

    def test_entity_set_change_drops_only_that_category(self):
        states = {IMPORT_METER: _state(10.0), EXPORT_METER: _state(20.0)}
        mapping = {"grid_import": [IMPORT_METER], "grid_export": [EXPORT_METER]}
        calc = _calc(states, mapping)
        _reconcile(calc, "grid_import")
        _reconcile(calc, "grid_export")
        assert "grid_import" in calc._meter_baselines

        calc.configure_meter_counters(
            _hass_with(states),
            {"grid_import": [IMPORT_METER, "sensor.p1_import_t2"],
             "grid_export": [EXPORT_METER]},
            True,
        )
        assert "grid_import" not in calc._meter_baselines
        assert "grid_export" in calc._meter_baselines
