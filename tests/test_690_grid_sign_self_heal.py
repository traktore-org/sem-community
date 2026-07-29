"""#690 — the grid-sign self-heal must not fight the user, and must not oscillate.

@hrdilshan: "Change the Grid sign value… it automatically changes back."

``_check_sign_flip`` runs every daylight cycle and, after ~3 min of negative
energy balance, toggles ``_grid_sign_inverted``. It knew nothing about the two
explicit user layers, so it fought both:

1. With ``grid_sign_invert: True`` the reader negates on a path that
   **short-circuits the autodetect entirely** — ``_grid_sign_inverted`` is never
   read. Toggling it therefore cannot change the balance, the balance stays
   negative, and 3 minutes later it toggles again: ``sensor.sem_diag_grid_sign``
   flips normal↔negated forever. Literally "always changes back".
2. With the one-tap ``grid_sign_user_flip`` the read does flip — but if the
   balance is negative for *any other* reason (a wrong battery sign, an
   unmetered load, a missing sensor) the heal blames the grid and cancels the
   user's tap.

The balance test cannot tell WHICH sensor is wrong; it always blames the grid.
#589 already recognised this and added an observe-only contradiction audit, but
this older *active* correction was left in place. Two guards close it:
an explicit user decision stands the heal down, and a flip that does not fix the
balance is reverted and latched off instead of oscillating.
"""
import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    PowerReadings,
)


class _Reader:
    """Stub reader — real booleans, so nothing is accidentally truthy."""

    def __init__(self, **cfg):
        self._raw_config = dict(cfg)
        self._grid_sign_inverted = False
        self._grid_sign_detected = False
        self._split_grid_discovery = {
            "import": None, "export": None,
            "confidence": "same-device", "warned": False,
        }

    @property
    def grid_sign_user_override(self) -> bool:
        return bool(self._raw_config.get("grid_sign_invert", False)
                    or self._raw_config.get("grid_sign_user_flip", False))


def _coord(**cfg):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c._sensor_reader = _Reader(**cfg)
    c._negative_balance_count = 0
    c._sign_flip_suppression_count = 0
    return c


def _negative_power():
    """Balance = (5000 solar) − (8000 export) = −3000 W → below the −500 trip."""
    p = PowerReadings()
    p.solar_power = 5000.0
    p.grid_power = 3000.0
    p.grid_import_power = 0.0
    p.grid_export_power = 8000.0
    p.battery_power = 0.0
    p.battery_charge_power = 0.0
    p.battery_discharge_power = 0.0
    p.ev_power = 0.0
    return p


def _healthy_power():
    p = _negative_power()
    p.grid_export_power = 1000.0        # balance = +4000 W
    return p


def _run(coord, power, cycles):
    for _ in range(cycles):
        coord._check_sign_flip(power)


@pytest.mark.unit
class TestUserOverrideStandsDown:
    @pytest.mark.parametrize("key", ["grid_sign_invert", "grid_sign_user_flip"])
    def test_explicit_sign_is_never_auto_corrected(self, key):
        coord = _coord(**{key: True})
        _run(coord, _negative_power(), 18 * 4)      # ~12 min of negative balance
        assert coord._sensor_reader._grid_sign_inverted is False, (
            f"{key} is the user's explicit decision — the self-heal must not "
            f"touch it (#690)")

    def test_manual_invert_does_not_oscillate_the_diagnostic(self):
        """The exact reported symptom: with the manual override the flag the
        heal toggles isn't even read, so it flipped every 3 min forever."""
        coord = _coord(grid_sign_invert=True)
        seen = set()
        for _ in range(18 * 6):                      # ~18 min
            coord._check_sign_flip(_negative_power())
            seen.add(coord._sensor_reader._grid_sign_inverted)
        assert seen == {False}, "diag_grid_sign oscillated normal↔negated"


@pytest.mark.unit
class TestSelfHealStillWorks:
    def test_flips_once_when_nothing_is_configured(self):
        """Inertness guard — with no user decision the #166 heal is unchanged."""
        coord = _coord()
        _run(coord, _negative_power(), 18)
        assert coord._sensor_reader._grid_sign_inverted is True
        assert coord._sensor_reader._grid_sign_detected is True

    def test_healthy_balance_confirms_the_flip(self):
        """Flip, then the balance recovers → the attempt is cleared, so a later
        genuine fault (new hardware) can still be healed."""
        coord = _coord()
        _run(coord, _negative_power(), 18)
        assert coord._sign_flip_attempted is True
        _run(coord, _healthy_power(), 18)
        assert coord._sign_flip_attempted is False
        assert coord._sensor_reader._grid_sign_inverted is True   # flip held


@pytest.mark.unit
class TestNoOscillation:
    def test_a_flip_that_does_not_help_is_reverted_and_latched(self):
        """The balance is negative for a NON-grid reason (wrong battery sign,
        unmetered load). One attempt, then put it back and stand down — never
        toggle forever."""
        coord = _coord()
        power = _negative_power()
        _run(coord, power, 18)                      # attempt 1 → flipped
        assert coord._sensor_reader._grid_sign_inverted is True
        _run(coord, power, 18)                      # still negative → revert
        assert coord._sensor_reader._grid_sign_inverted is False
        assert coord._sign_flip_latched is True
        # …and it stays put no matter how long the fault persists.
        _run(coord, power, 18 * 5)
        assert coord._sensor_reader._grid_sign_inverted is False

    def test_an_intermittent_fault_cannot_reopen_the_oscillation(self):
        """A brief healthy window must NOT confirm the flip.

        If one good cycle cleared the attempt, an intermittent non-grid fault
        (a load that only shows up under high draw) would oscillate on a longer
        period: negative ×18 → flip → 1 healthy → cleared → negative ×18 →
        flip back → … Confirmation is as sustained as the trip.
        """
        coord = _coord()
        power = _negative_power()
        _run(coord, power, 18)                      # attempt 1 → flipped
        assert coord._sensor_reader._grid_sign_inverted is True
        _run(coord, _healthy_power(), 5)            # a brief good spell (<3 min)
        assert coord._sign_flip_attempted is True, "flip confirmed too early"
        _run(coord, power, 18)                      # fault returns → revert, latch
        assert coord._sensor_reader._grid_sign_inverted is False
        assert coord._sign_flip_latched is True

    def test_revert_restores_the_detection_lock(self):
        """The flip stamps ``_grid_sign_detected`` (which gets PERSISTED, #476).
        A reverted attempt must not leave that lock poisoned."""
        coord = _coord()
        power = _negative_power()
        _run(coord, power, 18)
        assert coord._sensor_reader._grid_sign_detected is True
        _run(coord, power, 18)
        assert coord._sensor_reader._grid_sign_detected is False
