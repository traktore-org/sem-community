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
