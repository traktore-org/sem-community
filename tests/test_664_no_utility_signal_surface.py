"""#664 — SEM does not support ripple control / Sperrzeiten. Keep it that way.

The utility-signal surface was never reachable by a user: ``utility_signal_entity``
had no config-flow step, no card picker, no ``strings.json`` entry and no docs, so
on **every** install the monitor read nothing, the three entities reported
``false`` / ``"none"`` / ``0`` forever, and ``HeatPumpController.block()`` — the
one thing that would have acted on a signal — had no caller at all.

#654 amputated the half that *lied* (a WARNING claiming loads were being shed).
#664 asked the remaining question — build the shedding, or drop it? — and the
answer was drop it (Guido, 2026-07-26). SEM does not implement Sperrzeiten, so it
now says so everywhere instead of carrying a half-built surface that reads like a
feature in the entity list.

This guard pins the removal against three ways it comes back:

1. Someone re-adds the module or the dataclass because a grep in an old
   CHANGELOG entry suggests it should exist.
2. Someone re-adds the entity keys, which would put three permanently-dead
   sensors back on every install.
3. Someone re-adds ``block()``/``unblock()`` **without a caller** — the exact
   orphan state #653 baselined and #664 cleared. Adding them back *with* a real
   ripple-control implementation is a feature, and would come with its own tests;
   what this forbids is the actuator with nobody pulling it.

Deliberately NOT guarded: ``SGReadyState.BLOCKED`` and its row in
``SG_READY_RELAY_MAP``. State 1 belongs to the SG-Ready standard whether or not
SEM commands it, and the SETUP_GUIDE wiring table is verified against that map
(#523/#655). An installer checks their relays against the full table.
"""
from __future__ import annotations

import importlib
import json
import pathlib

import pytest


_ROOT = pathlib.Path(__file__).resolve().parent.parent

_ENTITY_KEYS = (
    "utility_signal_active",
    "utility_signal_source",
    "utility_signal_count_today",
)


def test_the_module_is_gone() -> None:
    """``utility_signals.py`` must not come back."""
    assert not (_ROOT / "utility_signals.py").exists(), (
        "utility_signals.py is back. SEM does not support ripple control "
        "(#664) — if that changed, this test should be deleted as part of "
        "the feature, not left passing next to it."
    )
    with pytest.raises(ImportError):
        importlib.import_module(
            "custom_components.solar_energy_management.utility_signals"
        )


def test_no_coordinator_data_carrier() -> None:
    """``UtilitySignalSensorData`` and its ``SEMData`` field are gone."""
    from custom_components.solar_energy_management import coordinator as pkg
    from custom_components.solar_energy_management.coordinator import types

    assert not hasattr(pkg, "UtilitySignalSensorData")
    assert not hasattr(types, "UtilitySignalSensorData")
    import dataclasses

    assert "utility_signal" not in {f.name for f in dataclasses.fields(types.SEMData)}


def test_no_entity_descriptions() -> None:
    """No sensor or binary_sensor may carry a utility-signal key.

    They were `entity_registry_enabled_default=False` diagnostics, which is
    exactly why nobody noticed they could never report anything — a disabled
    entity that stays empty looks the same as one nobody enabled.
    """
    from custom_components.solar_energy_management import binary_sensor, sensor

    keys = {d.key for d in sensor.SENSOR_TYPES}
    keys |= {d.key for d in binary_sensor.BINARY_SENSOR_TYPES}
    offenders = sorted(k for k in keys if k.startswith("utility_signal"))
    assert not offenders, f"utility-signal entities are back: {offenders}"


@pytest.mark.parametrize(
    "path",
    [
        _ROOT / "strings.json",
        _ROOT / "icons.json",
        *sorted((_ROOT / "translations").glob("*.json")),
    ],
    ids=lambda p: p.name,
)
def test_no_translation_or_icon_keys(path: pathlib.Path) -> None:
    """A stale name/icon key would re-advertise the entities in the UI."""
    blob = json.dumps(json.loads(path.read_text(encoding="utf-8")))
    for key in _ENTITY_KEYS:
        assert key not in blob, f"{path.name} still carries {key}"


def test_no_block_actuator_without_a_caller() -> None:
    """SG-Ready state 1 has no SEM-side actuator.

    ``block``/``unblock`` implemented it and were orphans for their whole life.
    If a future §14a EnWG / Sperrzeiten feature needs them, they come back
    together with the thing that calls them.
    """
    from custom_components.solar_energy_management.devices.heat_pump_controller import (
        HeatPumpController,
    )

    for name in ("block", "unblock"):
        assert not hasattr(HeatPumpController, name), (
            f"HeatPumpController.{name} is back. If SEM now acts on a utility "
            "signal, wire the caller and delete this assertion; an actuator "
            "with no caller is the #653/#664 orphan class."
        )


def test_config_flow_does_not_advertise_a_state_sem_cannot_drive() -> None:
    """The docstring promise and the code must agree.

    #654 kept the orphaned block actuator *because* config_flow advertised a
    "standard 4-state protocol". Deleting the actuator without retracting the
    advertisement would just move the lie.
    """
    src = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
    assert "4-state protocol" not in src, (
        "config_flow advertises the SG-Ready 4-state protocol again, but SEM "
        "drives only NORMAL / BOOST / FORCE_ON (#664)."
    )
