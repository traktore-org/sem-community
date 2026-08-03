"""#639 — the fleet energy block must not double-feed per-charger detectors."""
import pathlib
import re
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

REPO = pathlib.Path(__file__).resolve().parents[1]


class TestFleetBlockGate639:
    def test_fleet_update_energy_gated_on_no_ev_devices(self):
        """Shape guard (the audit's lint suggestion): the fleet update_energy
        block must carry the legacy-only gate, mirroring #589 W2/W3."""
        src = (REPO / "coordinator" / "coordinator.py").read_text()
        # scope to the block that calls _ev_taper_detector.update_energy
        blk = re.search(
            r'if hasattr\(energy, "daily_ev"\)([^\n]*)\n(?:.*\n){0,25}?.*_ev_taper_detector\.update_energy',
            src)
        assert blk and "not self._ev_devices" in blk.group(1), (
            "the fleet energy block lost its legacy-only gate — per-charger "
            "installs get double-fed (#639, class 3)")


class TestPrimaryCounterFallback639:
    def _coord(self, chargers, top_level=None):
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.config = {"ev_chargers": chargers}
        if top_level:
            c.config["ev_total_energy_sensor"] = top_level
        c.hass = MagicMock()
        st = MagicMock(); st.state = "1234.5"
        c.hass.states.get = MagicMock(return_value=st)
        c._ev_taper_detectors = {ch["id"]: MagicMock() for ch in chargers}
        return c

    def test_primary_falls_back_to_top_level_counter(self):
        c = self._coord([{"id": "a"}, {"id": "b"}], top_level="sensor.keba_total")
        SEMCoordinator._update_per_charger_detector_energy(c, "a", 5000.0, 0.00278)
        inc, hw = c._ev_taper_detectors["a"].update_energy.call_args.args
        assert hw == 1234.5                       # legacy anchor preserved

    def test_sibling_never_gets_top_level_counter(self):
        c = self._coord([{"id": "a"}, {"id": "b"}], top_level="sensor.keba_total")
        SEMCoordinator._update_per_charger_detector_energy(c, "b", 5000.0, 0.00278)
        inc, hw = c._ev_taper_detectors["b"].update_energy.call_args.args
        assert hw is None                         # no cross-contamination

    def test_per_charger_counter_wins_over_fallback(self):
        c = self._coord([{"id": "a", "ev_total_energy_sensor": "sensor.own"}],
                        top_level="sensor.keba_total")
        SEMCoordinator._update_per_charger_detector_energy(c, "a", 5000.0, 0.00278)
        c.hass.states.get.assert_called_with("sensor.own")
