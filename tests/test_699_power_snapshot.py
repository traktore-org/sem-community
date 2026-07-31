"""#699 — the balance set reaches the cards as ONE atomic snapshot.

The system-diagram/flow cards used to read five separate entities; each
commits to the state machine on its own (EV even sub-cycle, #289), so a
render instant could compose values from different moments — caught live on
PROD when a 15 s KEBA burst put 4.8 kW on the grid tile while the EV tile
still read 0 (the coordinator's internal equation held throughout; only the
view was incoherent). The fix carries every balance value from the SAME
coordinator cycle as a ``power_snapshot`` attribute on the home sensor,
excluded from the recorder, and the cards read that first.
"""
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DIAGRAM = _ROOT / "dashboard" / "card" / "sem-system-diagram-card.js"
_FLOW = _ROOT / "dashboard" / "card" / "src" / "cards" / "sem-flow-card.js"

_SNAP_KEYS = {
    "solar_w", "grid_w", "grid_import_w", "grid_export_w",
    "battery_w", "battery_charge_w", "battery_discharge_w",
    "ev_w", "home_w", "battery_soc",
}


def _home_sensor():
    from custom_components.solar_energy_management.sensor import SEMSolarSensor
    s = SEMSolarSensor.__new__(SEMSolarSensor)
    s.entity_description = MagicMock()
    s.entity_description.key = "home_consumption_power"
    s.coordinator = MagicMock()
    return s


@pytest.mark.unit
class TestSnapshotAttribute:
    def test_snapshot_carries_the_whole_balance_set_from_one_cycle(self):
        s = _home_sensor()
        cycle = {
            "solar_power": 3800.0, "grid_power": -4766.0,
            "grid_import_power": 4766.0, "grid_export_power": 0.0,
            "battery_power": -111.0, "battery_charge_power": 0.0,
            "battery_discharge_power": 111.0, "ev_power": 4460.0,
            "home_consumption_power": 3705.0, "battery_soc": 89.0,
        }
        s.coordinator.data = dict(cycle)
        snap = s.extra_state_attributes["power_snapshot"]
        assert set(snap) == _SNAP_KEYS
        # every value is the cycle's own — no other source can leak in
        assert snap["solar_w"] == 3800.0
        assert snap["grid_import_w"] == 4766.0
        assert snap["ev_w"] == 4460.0
        assert snap["home_w"] == 3705.0
        assert snap["battery_soc"] == 89.0

    def test_missing_cycle_keys_read_as_none_not_crash(self):
        s = _home_sensor()
        s.coordinator.data = {"home_consumption_power": 500.0}
        snap = s.extra_state_attributes["power_snapshot"]
        assert snap["home_w"] == 500.0
        assert snap["ev_w"] is None

    def test_snapshot_is_unrecorded(self):
        from custom_components.solar_energy_management.sensor import SEMSolarSensor
        assert "power_snapshot" in SEMSolarSensor._unrecorded_attributes


@pytest.mark.unit
class TestCardsReadTheSnapshot:
    """Source pins: both cards must prefer the snapshot for every balance
    value in prefix mode, with the per-entity fallback intact."""

    @pytest.mark.parametrize("path", [_DIAGRAM, _FLOW], ids=["diagram", "flow"])
    def test_snapshot_helper_and_usage(self, path):
        src = path.read_text(encoding="utf-8")
        assert "_powerSnapshot()" in src
        assert "power_snapshot" in src
        # each balance read is snapshot-first
        for token in ("snap.solar_w", "snap.battery_w", "snap.grid_import_w",
                      "snap.grid_export_w", "snap.ev_w", "snap.home_w",
                      "snap.battery_soc"):
            assert token in src, f"{path.name} missing {token}"
        # the fallback per-entity reads survive for older backends
        for token in ("_getState('solar_power')", "_getState('ev_power')"):
            assert token in src, f"{path.name} lost the fallback {token}"

    def test_bundle_carries_the_flow_card_change(self):
        bundle = (_ROOT / "dashboard" / "card" / "dist" / "sem-cards.js"
                  ).read_text(encoding="utf-8")
        assert "power_snapshot" in bundle, (
            "dist/sem-cards.js predates the #699 flow-card change — "
            "run `npm run build` in dashboard/card"
        )
