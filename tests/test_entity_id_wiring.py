"""Contract tests locking the entity-id-lookup wiring class.

Background: the observer-mode switch was a silent no-op for a long time because
``ENTITY_OBSERVER_MODE_SWITCH`` held the ``domain.object`` form
(``solar_energy_management.observer_mode``) and the coordinator looked it up as
``hass.states.get(f"switch.{ENTITY_OBSERVER_MODE_SWITCH}")`` — building the
three-segment string ``switch.solar_energy_management.observer_mode``, which is
not a valid entity_id, so the lookup always returned ``None``. The real entity is
``switch.sem_observer_mode``.

These tests would have turned that bug into a red build:
  1. every ``ENTITY_*`` constant is a real, two-segment entity_id whose platform
     matches what the entity actually registers; and
  2. the coordinator never re-prefixes such a constant (the mechanism that broke
     it), so the lookup string can't drift back into a dead three-segment id.
"""
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.consts import core as C
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


# Map each entity-id constant to the platform its real entity registers under.
# (SEM forces ``<platform>.sem_<key>`` in every entity __init__.)
_ENTITY_ID_CONSTANTS = {
    "ENTITY_OBSERVER_MODE_SWITCH": "switch",
    "ENTITY_SOLAR_POWER": "sensor",
}

_VALID_PLATFORMS = {
    "switch", "sensor", "binary_sensor", "number", "select", "button",
    "light", "climate", "input_boolean", "input_number",
}

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
class TestEntityIdConstants:
    """The constants must BE full, valid entity_ids — not the domain.object form."""

    @pytest.mark.parametrize("name,platform", _ENTITY_ID_CONSTANTS.items())
    def test_constant_is_a_valid_two_segment_entity_id(self, name, platform):
        value = getattr(C, name)
        # Exactly two segments: "<platform>.<object_id>". A three-segment string
        # (the old bug) means a dead lookup.
        assert value.count(".") == 1, (
            f"{name}={value!r} is not a 2-segment entity_id — "
            f"this builds a dead lookup that silently returns None"
        )
        plat, _, obj = value.partition(".")
        assert plat in _VALID_PLATFORMS, (
            f"{name}={value!r} has platform {plat!r}; looks like the "
            f"domain.object form (the observer-mode bug), not an entity_id"
        )
        assert plat == platform, (
            f"{name}={value!r} should be on platform {platform!r}"
        )
        # SEM's own entities are always object-id 'sem_<key>'.
        assert obj.startswith("sem_"), (
            f"{name}={value!r} object_id {obj!r} should start with 'sem_'"
        )
        # And the shape must be a legal HA entity_id.
        assert re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", value), (
            f"{name}={value!r} is not a syntactically valid entity_id"
        )


@pytest.mark.unit
class TestNoEntityIdReprefix:
    """The coordinator must look the constants up verbatim, never re-prefix them.

    Re-prefixing (``f"switch.{ENTITY_OBSERVER_MODE_SWITCH}"``) was the exact
    mechanism that produced the dead three-segment id. Guard against it returning.
    """

    def test_coordinator_does_not_reprefix_entity_constants(self):
        src = (_REPO_ROOT / "coordinator" / "coordinator.py").read_text()
        # Any f-string that prepends a platform to an ENTITY_ constant.
        bad = re.findall(
            r'f"(?:switch|sensor|number|select|binary_sensor)\.\{ENTITY_[A-Z_]+\}',
            src,
        )
        assert not bad, (
            "coordinator.py re-prefixes an entity-id constant — this rebuilds "
            f"the dead three-segment lookup bug: {bad}"
        )


@pytest.mark.unit
class TestObserverPullDoesNotClobber:
    """The per-cycle pull must hold the observer flag across transient
    switch ``unavailable``/``unknown`` and only move on a real on/off.

    The switch is a CoordinatorEntity whose ``available`` flaps to False on any
    failed update, so its state momentarily reads ``unavailable``. An earlier
    fix that did ``_observer_mode = (state == 'on')`` clobbered the pushed value
    to False every cycle — silently re-enabling hardware control on a box that
    shares real PROD hardware. This locks the guard.
    """

    @staticmethod
    def _pull(switch_state, start):
        hass = MagicMock()
        hass.states.get.return_value = (
            None if switch_state is None else SimpleNamespace(state=switch_state)
        )
        fake = SimpleNamespace(hass=hass, _observer_mode=start)
        SEMCoordinator._sync_observer_mode_from_switch(fake)
        return fake._observer_mode

    def test_on_enables(self):
        assert self._pull("on", False) is True

    def test_off_disables(self):
        assert self._pull("off", True) is False

    def test_unavailable_holds_true(self):
        # The actual bug: transient unavailable must NOT disable observation.
        assert self._pull("unavailable", True) is True

    def test_unknown_holds_true(self):
        assert self._pull("unknown", True) is True

    def test_missing_entity_holds_true(self):
        assert self._pull(None, True) is True

    def test_unavailable_holds_false_too(self):
        # Symmetric: it must not spuriously enable, either.
        assert self._pull("unavailable", False) is False


@pytest.mark.unit
class TestObserverZeroesSetpoints:
    """Observer mode zeroes every charger setpoint WITHOUT crashing on the
    multi-charger dict. ``_ev_devices`` is a {id: device} dict; iterating it as
    a list yields id strings (no ``_current_setpoint``) and took down the whole
    update cycle (#542) — latent until the observer switch was un-broken.
    """

    @staticmethod
    def _device(initial=6.0):
        d = SimpleNamespace(_current_setpoint=initial)
        return d

    def test_multi_charger_dict_zeroes_values_not_keys(self):
        a, b = self._device(), self._device()
        fake = SimpleNamespace(
            _ev_devices={"charger_a": a, "charger_b": b}, _ev_device=None
        )
        # Must not raise (the bug raised 'str' object has no attribute ...).
        SEMCoordinator._zero_charger_setpoints(fake)
        assert a._current_setpoint == 0.0
        assert b._current_setpoint == 0.0

    def test_single_charger_zeroed(self):
        single = self._device()
        fake = SimpleNamespace(_ev_devices=None, _ev_device=single)
        SEMCoordinator._zero_charger_setpoints(fake)
        assert single._current_setpoint == 0.0

    def test_no_chargers_is_noop(self):
        fake = SimpleNamespace(_ev_devices=None, _ev_device=None)
        SEMCoordinator._zero_charger_setpoints(fake)  # must not raise
