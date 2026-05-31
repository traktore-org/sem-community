"""Per-charger SOC isolation in multi-charger setups (#318).

Regression test for the bug where Charger 1 and Charger 2 both reported
identical SOC values, and Charger 2's SOC rose when only Charger 1 was
actively charging.

Reported 2026-05-31 by @RienduPre on a multi-charger Wallbox Pulsar +
Growatt setup (SEM v1.6.3). Root cause: ``_update_ev_intelligence`` at
``coordinator/coordinator.py`` ran a per-charger loop that called
``EVTaperDetector.update(...)`` per charger but the energy-tracking
call ``update_energy(...)`` was only made for the PRIMARY detector at
line ~3326 — every per-charger detector's ``_energy_since_full`` stayed
at 0 forever, so ``get_virtual_soc()`` returned the same default for
every charger.

v1.6.5 fix: extract ``_update_per_charger_detector_energy(cid, …)`` as
a small helper called inside the per-charger loop. Each detector gets
its own power increment and (if configured) its own
``ev_total_energy_sensor`` hardware counter — completely decoupled from
sibling chargers.
"""
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import SEMCoordinator


def _make_coordinator(ev_chargers, hw_total_states=None):
    """Build a minimal coordinator stub for the helper method under test.

    The helper only reads ``self.config``, ``self._ev_taper_detectors``,
    and ``self.hass.states.get`` — nothing else. Keeping the fixture
    surface small makes the tests robust to unrelated coordinator
    refactors.
    """
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = {"ev_chargers": ev_chargers}
    coord._ev_taper_detectors = {c["id"]: MagicMock() for c in ev_chargers}
    coord.hass = MagicMock()

    def _states_get(eid):
        if hw_total_states and eid in hw_total_states:
            s = MagicMock()
            s.state = hw_total_states[eid]
            return s
        return None
    coord.hass.states.get = _states_get
    return coord


# 10-second coordinator cycle in hours — matches the production
# ``update_interval=10s`` so the increments below are directly
# comparable to a real cycle.
INTERVAL_HOURS = 10 / 3600


class TestPerChargerSOCIsolation:
    """The helper ``_update_per_charger_detector_energy`` is what the
    fix calls inside the per-charger loop. Test it in isolation so we
    don't drag the rest of ``_update_ev_intelligence`` in.
    """

    def test_active_charger_gets_its_own_increment(self):
        """3 kW charger gets ``3000 × interval / 1000`` kWh — load-bearing
        for #318."""
        coord = _make_coordinator([
            {"id": "left"}, {"id": "right"},
        ])

        coord._update_per_charger_detector_energy("left", 3000.0, INTERVAL_HOURS)

        det = coord._ev_taper_detectors["left"]
        det.update_energy.assert_called_once()
        increment, hw_total = det.update_energy.call_args[0]
        assert increment == pytest.approx(3000.0 * INTERVAL_HOURS / 1000)
        assert hw_total is None  # no per-charger HW counter configured

    def test_two_active_chargers_get_distinct_increments(self):
        """Two chargers at different power → two distinct increments.
        Pre-fix both ``update_energy`` calls were skipped entirely; now
        each detector gets its own value."""
        coord = _make_coordinator([
            {"id": "left"}, {"id": "right"},
        ])

        coord._update_per_charger_detector_energy("left", 3000.0, INTERVAL_HOURS)
        coord._update_per_charger_detector_energy("right", 7000.0, INTERVAL_HOURS)

        left_inc = coord._ev_taper_detectors["left"].update_energy.call_args[0][0]
        right_inc = coord._ev_taper_detectors["right"].update_energy.call_args[0][0]
        assert right_inc > left_inc
        assert right_inc == pytest.approx(7000.0 * INTERVAL_HOURS / 1000)
        assert left_inc == pytest.approx(3000.0 * INTERVAL_HOURS / 1000)

    def test_idle_charger_gets_no_update(self):
        """No power → no energy increment delivered. Matches the
        existing ``charger_power > 0`` gating at the call site so we
        don't pollute detector state with zero-energy cycles."""
        coord = _make_coordinator([{"id": "left"}])

        coord._update_per_charger_detector_energy("left", 0.0, INTERVAL_HOURS)

        coord._ev_taper_detectors["left"].update_energy.assert_not_called()

    def test_negative_power_is_treated_as_idle(self):
        """Defensive: a negative reading (sensor glitch) is treated as
        idle, not as "discharge"."""
        coord = _make_coordinator([{"id": "left"}])

        coord._update_per_charger_detector_energy("left", -100.0, INTERVAL_HOURS)

        coord._ev_taper_detectors["left"].update_energy.assert_not_called()

    def test_per_charger_hw_counter_passed_when_configured(self):
        """If a charger has its own ``ev_total_energy_sensor`` configured,
        the HW counter value is read from HA state and passed to
        ``update_energy`` as the drift-correction anchor — the same
        drift-free tracking the primary detector has."""
        coord = _make_coordinator(
            [{"id": "left",
              "ev_total_energy_sensor": "sensor.left_total_energy"}],
            hw_total_states={"sensor.left_total_energy": "42.5"},
        )

        coord._update_per_charger_detector_energy("left", 5000.0, INTERVAL_HOURS)

        increment, hw_total = (
            coord._ev_taper_detectors["left"].update_energy.call_args[0]
        )
        assert hw_total == pytest.approx(42.5)

    def test_unavailable_hw_counter_falls_back_to_increment_only(self):
        """If the HW counter sensor exists but reads ``unavailable``,
        the helper passes ``None`` so the detector falls back to
        incremental-only tracking. No crash, no spurious anchor."""
        coord = _make_coordinator(
            [{"id": "left",
              "ev_total_energy_sensor": "sensor.left_total_energy"}],
            hw_total_states={"sensor.left_total_energy": "unavailable"},
        )

        coord._update_per_charger_detector_energy("left", 5000.0, INTERVAL_HOURS)

        increment, hw_total = (
            coord._ev_taper_detectors["left"].update_energy.call_args[0]
        )
        assert hw_total is None

    def test_no_per_charger_hw_counter_passes_none(self):
        """Without per-charger ``ev_total_energy_sensor``, falls back to
        incremental-only tracking. Same behaviour the primary detector
        had pre-fix for installs without a hardware counter."""
        coord = _make_coordinator([{"id": "left"}])

        coord._update_per_charger_detector_energy("left", 5000.0, INTERVAL_HOURS)

        hw_total = (
            coord._ev_taper_detectors["left"].update_energy.call_args[0][1]
        )
        assert hw_total is None

    def test_unknown_charger_id_is_no_op(self):
        """Defensive: an unknown ``cid`` (config inconsistency mid-cycle)
        is a quiet no-op rather than ``KeyError``. Pinning this
        explicitly so the fix doesn't introduce a new crash class."""
        coord = _make_coordinator([{"id": "left"}])

        # Should NOT raise.
        coord._update_per_charger_detector_energy("ghost", 5000.0, INTERVAL_HOURS)

        # And of course the left detector wasn't touched.
        coord._ev_taper_detectors["left"].update_energy.assert_not_called()
