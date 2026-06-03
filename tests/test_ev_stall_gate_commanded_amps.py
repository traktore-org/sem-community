"""Regression: the fleet-level "0 W → 100 % SOC" stall detector must NOT
fire when SEM itself isn't asking for charge.

PROD symptom (HA-PROD, 2026-06-03): ``solar_only`` mode on a 3-phase
KEBA — surplus 869 W < 6 A floor 4 140 W, so SEM correctly idles. After
3 minutes of idle, the legacy stall path latched ``estimated_soc=100%``,
which made ``charge_needed=False`` permanently, so the EV never started
on later high-surplus cycles even after a real drive.

The fix gates the stall block on
``self._last_commanded_amps_fleet >= 6``: only the case where SEM was
actively *commanding* 6+ A and the EV still drew 0 W counts as a real
"BMS refusing further current" event. The reset to 0 happens at the
top of every per-charger decide-loop.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def _stall_gate(*, ev_connected, ev_charging, ev_power_w,
                last_commanded_amps_fleet, full_detected):
    """In-test mirror of the gate at coordinator.py ~3725.

    Kept tiny + dependency-free so it doesn't have to import the
    coordinator module (which pulls HomeAssistant). Two tests below
    cross-check that ``coordinator.py`` still has the same gate.
    """
    return (
        ev_connected
        and not ev_charging
        and ev_power_w < 50
        and last_commanded_amps_fleet >= 6
        and not full_detected
    )


class TestStallGateCommandedAmps:
    def test_solar_only_idle_does_not_trip_stall(self):
        """PROD reproduction: connected EV, SEM idle by decision (0 A
        commanded because surplus < 3-phase floor), 0 W power. The gate
        MUST stay False — otherwise SOC gets falsely anchored at 100 %."""
        assert _stall_gate(
            ev_connected=True,
            ev_charging=False,
            ev_power_w=0,
            last_commanded_amps_fleet=0,
            full_detected=False,
        ) is False

    def test_actively_commanding_and_ev_refusing_trips_stall(self):
        """When SEM is asking for 6 A but the EV still draws 0 W, that's
        a real BMS-refusing-further-current event — gate must fire."""
        assert _stall_gate(
            ev_connected=True,
            ev_charging=False,
            ev_power_w=0,
            last_commanded_amps_fleet=6,
            full_detected=False,
        ) is True

    def test_high_amps_commanded_also_trips(self):
        assert _stall_gate(
            ev_connected=True,
            ev_charging=False,
            ev_power_w=10,
            last_commanded_amps_fleet=16,
            full_detected=False,
        ) is True

    def test_already_full_short_circuits(self):
        assert _stall_gate(
            ev_connected=True,
            ev_charging=False,
            ev_power_w=0,
            last_commanded_amps_fleet=16,
            full_detected=True,
        ) is False

    def test_disconnected_short_circuits(self):
        assert _stall_gate(
            ev_connected=False,
            ev_charging=False,
            ev_power_w=0,
            last_commanded_amps_fleet=16,
            full_detected=False,
        ) is False

    def test_actually_charging_short_circuits(self):
        """If the EV is reporting active charging, this isn't a stall."""
        assert _stall_gate(
            ev_connected=True,
            ev_charging=True,
            ev_power_w=3000,
            last_commanded_amps_fleet=16,
            full_detected=False,
        ) is False


class TestCoordinatorGateStaysAligned:
    """If someone edits the gate in ``coordinator.py`` and forgets to
    update the in-test mirror above, this test fails fast on CI."""

    def test_coordinator_gate_contains_last_commanded_amps_check(self):
        """The fleet-level stall block (legacy single-detector path) MUST
        gate on ``self._last_commanded_amps_fleet``. Asserting the source
        text rather than calling the method keeps the test free of the
        coordinator's heavy init."""
        import pathlib
        coord_src = pathlib.Path(
            __file__,
        ).resolve().parent.parent.joinpath("coordinator/coordinator.py").read_text()

        # The gate string we care about — both halves on the same logical
        # ``if`` block. Substring search is enough because the formatting
        # is stable (one statement per line).
        assert "self._last_commanded_amps_fleet >= 6" in coord_src, (
            "stall gate must check commanded amps — see "
            "test_ev_stall_gate_commanded_amps for PROD repro context"
        )

    def test_reset_at_top_of_per_charger_loop_present(self):
        import pathlib
        coord_src = pathlib.Path(
            __file__,
        ).resolve().parent.parent.joinpath("coordinator/coordinator.py").read_text()
        assert "self._last_commanded_amps_fleet = 0" in coord_src

    def test_update_after_decision_present(self):
        import pathlib
        coord_src = pathlib.Path(
            __file__,
        ).resolve().parent.parent.joinpath("coordinator/coordinator.py").read_text()
        assert (
            "decision.commanded_amps > self._last_commanded_amps_fleet"
            in coord_src
        )
