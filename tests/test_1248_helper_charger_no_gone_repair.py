"""#1248 — a charger moved to helper entities (no device) keeps no "device
is gone" Repair. The Repair stays when the charger's entities are gone too."""
from __future__ import annotations

from custom_components.solar_energy_management.charger_refs import (
    card_to_ref, problems, resolve,
)
from custom_components.solar_energy_management.hardware_detection import (
    CHARGER_ENTITY_KEYS,
)

from .test_1054_device_refs import GOE_DEV, GOE_LIVE, NEW


def _kinds(entity_exists, device_exists=lambda d: False):
    ref = card_to_ref(dict(NEW), GOE_DEV, GOE_LIVE)
    return [p["kind"] for p in problems(
        [ref], [resolve(ref)], device_exists=device_exists,
        entity_exists=entity_exists)]


def test_the_device_is_gone_and_so_are_its_entities():
    assert _kinds(lambda e: False) == ["charger_device_gone"]


def test_the_device_is_gone_but_the_charger_runs_on_helpers():
    assert "charger_device_gone" not in _kinds(lambda e: True)


def test_one_entity_still_missing_keeps_the_repair():
    ref = card_to_ref(dict(NEW), GOE_DEV, GOE_LIVE)
    one = next(str(resolve(ref)[k]) for k in sorted(CHARGER_ENTITY_KEYS)
               if resolve(ref).get(k) and "." in str(resolve(ref)[k]))
    assert "charger_device_gone" in _kinds(lambda e: e != one)


def test_a_device_that_exists_is_as_before():
    assert _kinds(lambda e: True, device_exists=lambda d: True) == []
