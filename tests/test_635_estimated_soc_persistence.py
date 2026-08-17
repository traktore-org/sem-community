"""#635 — estimated SOC survives restarts: the save/restore asymmetry fix."""

from custom_components.solar_energy_management.coordinator.storage import SEMStorage


def _storage():
    st = SEMStorage.__new__(SEMStorage)
    st._energy_data = {}
    return st


class TestIntelPersistence635:
    def test_per_charger_state_round_trip(self):
        st = _storage()
        st.set_per_charger_intelligence_state("ev_charger", {"estimated_soc": 82.0,
                                                             "soc_anchored": True})
        stored = st.get_ev_intelligence_state()
        assert stored["chargers"]["ev_charger"]["estimated_soc"] == 82.0
        assert stored["chargers"]["ev_charger"]["soc_anchored"] is True

    def test_primary_save_preserves_chargers_and_history(self):
        """The restart-blank bug: the legacy wholesale replace wiped the
        chargers dict (and session_history) every cycle."""
        st = _storage()
        st.set_per_charger_intelligence_state("c1", {"estimated_soc": 55.0})
        st.add_session_to_history({"kwh": 2.0})
        st.set_ev_intelligence_state({"estimated_soc": 90.0, "soc_anchored": True})
        stored = st.get_ev_intelligence_state()
        assert stored["estimated_soc"] == 90.0                 # primary updated
        assert stored["chargers"]["c1"]["estimated_soc"] == 55.0   # NOT wiped
        assert stored["session_history"] == [{"kwh": 2.0}]         # NOT wiped

    def test_restore_path_sees_saved_charger_state(self):
        """End-to-end shape: what the boot restore reads is what the save wrote."""
        st = _storage()
        st.set_per_charger_intelligence_state("ev_charger", {"estimated_soc": 82.0,
                                                             "soc_anchored": True,
                                                             "energy_since_full": 7.2})
        from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
            EVTaperDetector)
        det = EVTaperDetector({"ev_battery_capacity_kwh": 40})
        per = st.get_ev_intelligence_state().get("chargers", {}).get("ev_charger")
        det.restore_state(per)
        assert det._estimated_soc == 82.0
        assert det._soc_anchored is True                       # sensor shows after boot
