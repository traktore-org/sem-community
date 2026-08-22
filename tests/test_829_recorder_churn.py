"""#829 — SEM's recorder footprint: rows are the currency.

Measured on PROD (21.08): SEM wrote 25 % of all recorder state rows
(192,886/day) with 13 % of the entities. Not because it records too many
attributes — #581 already moved the fat UI maps to ``_unrecorded_attributes``
— but because of ROWS: HA writes a new state row whenever state OR
attributes change, unrecorded ones included. Three mechanisms made a handful
of entities write a row every 10 s cycle:

  * per-cycle ticking values published at needless precision — a daily
    energy at 1 Wh (8k rows/day) where the house standard is 10 Wh (2k),
    session durations in tenths of a minute, averages as raw floats;
  * live numbers riding the attributes of a stable entity — the per-device
    ``current_power`` inside ``sem_controllable_devices_count`` (state "1"
    all day, 8,099 rows) and a per-cycle counter on ``layer_mismatch``;
  * the energy tip ROTATING every cycle (6k rows/day × 2 sensors) — a
    rotation meant for the eye, running at machine speed.

These pin the contracts that turn per-cycle writers into on-change writers.
The exit criteria (SEM < 10 % of rows; no entity > 2k rows/day unexplained)
are measured by ``~/bin/sem-churn-audit.sh``; these tests keep the causes
from coming back.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestEnergyPrecisionMatchesTheHouseStandard:
    """Daily/flow energies publish at 0.01 kWh (10 Wh), like every other
    daily row. 1 Wh granularity ticks every cycle at any real load."""

    def test_true_baseload_today_is_10wh(self):
        from custom_components.solar_energy_management.coordinator.energy_calculator import (
            EnergyCalculator,
        )
        from custom_components.solar_energy_management.utils.time_manager import TimeManager
        calc = EnergyCalculator({"update_interval": 10}, TimeManager(MagicMock()))
        from datetime import date
        today = date(2026, 8, 22)
        calc._daily_accumulators[f"home_{today}"] = 12.34567
        out = calc.get_true_baseload(today)
        for key in ("today_kwh", "controlled_today_kwh", "estimated_today_kwh"):
            v = out.get(key)
            if v is None:
                continue
            assert round(v, 2) == v, f"{key} carries more than 10 Wh: {v}"

    def test_energy_flows_publish_at_10wh(self):
        """The calculator keeps 1 Wh internally (its own tests pin that); what
        the ENTITIES publish is 10 Wh — at 1 Wh flow_battery_to_home wrote
        2,916 rows/day on PROD."""
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyFlows, SEMData,
        )
        d = SEMData(energy_flows=EnergyFlows(battery_to_home=1.23456,
                                             solar_to_home=7.89012)).to_dict()
        assert d["flow_battery_to_home_energy"] == 1.23
        assert d["flow_solar_to_home_energy"] == 7.89


@pytest.mark.unit
class TestTickersPublishOnChangeNotOnCycle:

    def test_battery_session_duration_is_whole_minutes(self):
        """A duration in tenths of a minute changes every 6 s — every cycle."""
        from custom_components.solar_energy_management.coordinator.types import (
            BatterySessionData,
        )
        s = BatterySessionData()
        s.duration_minutes = 12.7
        s.avg_power_w = 1234.56
        s.energy_kwh = 1.23456
        pub = s.published()
        assert pub["duration_minutes"] == 13
        assert pub["avg_power_w"] % 10 == 0, "avg power publishes in 10 W steps"
        assert pub["energy_kwh"] == 1.23

    def test_ev_session_duration_is_whole_minutes(self):
        from custom_components.solar_energy_management.coordinator.types import SessionData
        s = SessionData()
        s.duration_minutes = 45.4
        s.avg_power_w = 3333.3
        pub = s.published()
        assert pub["duration_minutes"] == 45
        assert pub["avg_power_w"] % 10 == 0

    def test_derived_powers_are_whole_watts(self):
        """solar_power (1,777 rows/day) is an integer from the inverter; the
        derived baseload/available powers carried float jitter (5.6k/5.4k)."""
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals, SEMData,
        )
        d = SEMData(energy=EnergyTotals(true_baseload_power=1234.567),
                    available_power=2345.678).to_dict()
        assert d["true_baseload_power"] == 1235
        assert d["available_power"] == 2346


@pytest.mark.unit
class TestLiveValuesDoNotRideStableEntities:

    def test_device_map_power_is_coarse_not_live(self):
        """``sem_controllable_devices_count`` is the count — state '1' all day
        — yet wrote 8,099 rows because the per-device map inside it carried
        raw live ``current_power``. Cards read live power from each row's own
        ``power_entity`` (the system-diagram card already did); the map keeps
        a 100 W-coarse fallback that changes only when the load really does."""
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        assert UnifiedDeviceRegistry._coarse_w(37.5) == 0
        assert UnifiedDeviceRegistry._coarse_w(177.9) == 200
        assert UnifiedDeviceRegistry._coarse_w(1477.2) == 1500
        assert UnifiedDeviceRegistry._coarse_w(None) == 0
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "features"
               / "device_registry.py").read_text()
        raw = [l for l in src.splitlines()
               if '"current_power":' in l and "_coarse_w(" not in l]
        assert not raw, f"raw live power back on the device map: {raw}"

    def test_runtime_progress_is_whole_minutes(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "features"
               / "device_registry.py").read_text()
        assert '"runtime_today_min": round(runtime_min, 1)' not in src, (
            "runtime progress at 0.1 min changes every cycle while a load runs"
        )
        assert '"runtime_today_min": int(round(runtime_min))' in src, (
            "runtime progress must publish whole minutes"
        )

    def test_rating_fallback_is_a_rating_not_a_live_reading(self):
        """With no registered device, power_rating mirrored the raw sensor
        (40.1 -> 37.5 -> …) — a live reading wearing a rating's name. A rating
        is a characterization: round the fallback to 10 W (100 W turned a
        42 W load's rating into 0, which is worse than churn)."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "features"
               / "device_registry.py").read_text()
        i = src.index("def _get_power_rating")
        window = src[i:i + 900]
        assert "round(" in window and "/ 10.0) * 10" in window, (
            "the rating fallback returns the raw live reading"
        )

    def test_priority_card_reads_live_power_from_the_entity(self):
        from pathlib import Path
        card = (Path(__file__).resolve().parent.parent / "dashboard" / "card"
                / "src" / "cards" / "sem-load-priority-card.js").read_text()
        assert "info.power_entity" in card and "states[info.power_entity]" in card, (
            "the priority card must read live power from the device's own "
            "entity now that the map no longer carries it"
        )


@pytest.mark.unit
class TestTipsRotateForTheEyeNotTheRecorder:

    def test_tips_do_not_rotate_every_cycle(self, monkeypatch):
        """Two analyze() calls 10 s apart must show the SAME tip; rotation is
        time-based (every few minutes), not per coordinator cycle."""
        import custom_components.solar_energy_management.analytics.energy_assistant as ea_mod
        clock = {"t": 1000.0}
        monkeypatch.setattr(ea_mod.time, "monotonic", lambda: clock["t"])
        ea = ea_mod.EnergyAssistant(MagicMock())
        kw = dict(daily_ev_kwh=10.0, solar_to_ev_kwh=2.0, grid_to_ev_kwh=8.0,
                  self_consumption_rate=30.0, daily_solar_kwh=10.0,
                  daily_grid_export_kwh=3.0)
        ea.analyze(**kw); first = ea.assistant_data.current_tip
        clock["t"] += 10
        ea.analyze(**kw); second = ea.assistant_data.current_tip
        assert first == second, "the tip rotated within one cycle"
        clock["t"] += ea_mod.TIP_ROTATION_INTERVAL_S + 1
        ea.analyze(**kw); third = ea.assistant_data.current_tip
        if len(ea._tips) > 1:
            assert third != first, "the tip never rotates at all"


@pytest.mark.unit
class TestMismatchCounterDoesNotChurn:

    def test_persisted_cycles_is_exact_then_coarse(self):
        """The diagnosis window (first cycles) stays exact — the #589 test pins
        ==4 — but a standing mismatch must not write a row per cycle forever."""
        from custom_components.solar_energy_management.binary_sensor import (
            coarse_cycles,
        )
        assert [coarse_cycles(n) for n in range(1, 7)] == [1, 2, 3, 4, 5, 5]
        assert coarse_cycles(9) == 5
        assert coarse_cycles(10) == 10
        assert coarse_cycles(47) == 40
        assert coarse_cycles(3144) == 3000



@pytest.mark.unit
class TestChargingStateBlobDoesNotChurn:
    """charging_state was the worst offender (5 MB/day, ~375 distinct blobs).
    Its attributes carried live values that wiggle every cycle — battery_soc,
    calculated_current, available_power (each ALREADY its own recorded
    entity), plus solar_sufficient and the strategy strings. Recorded, each
    wiggle stored a fresh blob. They must be excluded from the recorder while
    staying on the live state for the cards."""

    def test_churning_attrs_are_unrecorded(self):
        from custom_components.solar_energy_management.sensor import SEMSolarSensor
        must_exclude = {
            "battery_soc", "calculated_current", "available_power",
            "solar_sufficient", "battery_too_low", "battery_needs_priority",
            "charging_strategy", "strategy_reason",
        }
        missing = must_exclude - set(SEMSolarSensor._unrecorded_attributes)
        assert not missing, (
            f"charging_state still records live-wiggling attributes: {missing}"
        )

    def test_the_measurements_still_have_their_own_entities(self):
        """Excluding them as ATTRIBUTES is only safe because they are recorded
        as their own sensors — history is not lost, just not duplicated."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "sensor.py").read_text()
        for key in ("battery_soc", "calculated_current", "available_power"):
            assert f'key="{key}"' in src, (
                f"{key} is excluded from charging_state but has no own entity "
                "— that would lose its history"
            )


@pytest.mark.unit
class TestTheRemainingPerCycleWriters:
    """Measured on the rig after the first pass: four entities still wrote a
    row every 10 s cycle, all for the same reason — raw float precision on a
    value that moves constantly.

        surplus_distributable_w  5965.464021148     (707 rows/2h)
        surplus_unallocated_w    5874.764021148     (706)
        forecast_dampening_factor 0.809             (700)
        battery_session_savings  0.00684362166666667 (632)

    A watt is a watt; a currency figure nobody can read to 17 digits is
    noise. Rounding at publish costs nothing a human can see.
    """

    def test_surplus_watts_are_whole(self):
        from custom_components.solar_energy_management.coordinator.types import (
            SEMData, SurplusControlData,
        )
        d = SEMData(surplus_control=SurplusControlData(
            surplus_distributable_w=5965.464021148,
            surplus_unallocated_w=5874.764021148)).to_dict()
        assert d["surplus_distributable_w"] == 5965
        assert d["surplus_unallocated_w"] == 5875

    def test_session_savings_is_currency_precision(self):
        from custom_components.solar_energy_management.coordinator.types import (
            BatterySessionData, SEMData,
        )
        d = SEMData(battery_session=BatterySessionData(
            savings=0.00684362166666667)).to_dict()
        assert d["battery_session_savings"] == 0.01

    def test_dampening_factor_is_two_decimals(self):
        from custom_components.solar_energy_management.coordinator.types import (
            ForecastSensorData, SEMData,
        )
        d = SEMData(forecast=ForecastSensorData(
            forecast_dampening_factor=0.80912345)).to_dict()
        assert d["forecast_dampening_factor"] == 0.81

    def test_the_tracker_publishes_rounded_too(self):
        """THE lesson of this fix. ``SEMData.to_dict`` rounds it, but the
        forecast tracker publishes the SAME key and
        ``result.update(tracker_data)`` makes the tracker win — so the entity
        stayed unrounded and kept writing a row every cycle (0.694 -> 0.707 ->
        0.719 on the rig, 20 s apart) while the unit test above passed happily.

        Two publishers of one key, later one wins — the #828 class again.
        Pin the WINNING path, not the one that is easy to construct."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "coordinator"
               / "forecast_tracker.py").read_text()
        for key in ("forecast_dampening_factor", "forecast_correction_factor"):
            assert f'"{key}": round(' in src, (
                f"{key} is published raw by the tracker, which overwrites the "
                "rounded value from SEMData.to_dict"
            )
