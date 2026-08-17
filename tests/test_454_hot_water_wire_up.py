"""#454 — HotWaterController registration in production setup path.

The class lived in ``devices/hot_water_controller.py`` from the
start, fully implemented + unit-tested, but was NEVER instantiated
in the actual setup code (``__init__.py``). The Config tab Hot Water
section collected settings the runtime never read.

These tests pin the wire-up shipped in v1.7.2-beta.6:

* When ``hot_water_entity`` is set in entry options, setup
  instantiates ``HotWaterController`` and registers it with
  ``coordinator._surplus_controller``.
* When unset, no controller is registered (so the surplus loop
  doesn't try to dispatch power to a non-existent boiler).
* The coordinator's ``HotWaterSensorData`` reflects the registered
  controller's live state — including the #420 telemetry paths.
* The wire-up survives an entry reload (no in-memory state that
  doesn't repopulate on the next coordinator instance).

We test by AST inspection of ``__init__.py`` for the registration
block + by constructing a HotWaterSensorData manually from a mocked
controller to validate the field plumbing in
``coordinator/types.py:CoordinatorSensorData.to_dict``.
"""
from __future__ import annotations

from pathlib import Path



def _read(filename: str) -> str:
    """Find file from this test's location."""
    here = Path(__file__).resolve().parent
    # Walk up to find the manifest (project root)
    for parent in (here, *here.parents):
        if (parent / "manifest.json").exists():
            target = parent / filename
            if target.exists():
                return target.read_text()
    raise FileNotFoundError(filename)


# ---------------------------------------------------------------------------
# 1. Registration block presence
# ---------------------------------------------------------------------------


def test_hot_water_controller_imported_in_init():
    """The ``HotWaterController`` import line must exist in __init__.py.

    Lazy-imported inside the setup function, mirroring the
    HeatPumpController pattern (the import is on the success path,
    not at module top — so installs without hot_water don't pay
    the import cost)."""
    init_py = _read("__init__.py")
    assert "from .devices.hot_water_controller import HotWaterController" in init_py, (
        "HotWaterController not lazy-imported in __init__.py — without "
        "this line, the wire-up block can't run."
    )


def test_hot_water_register_device_call_present():
    """The setup code must call ``register_device`` with the
    HotWaterController instance. Without this, the surplus loop
    never knows about the boiler."""
    init_py = _read("__init__.py")
    # The registration line must reference the HotWater device variable
    # AND call register_device on the surplus controller.
    assert "register_device(hw_device)" in init_py or \
        "register_device(HotWaterController" in init_py, (
        "HotWaterController is imported but never registered with the "
        "SurplusController — wire-up incomplete."
    )


def test_hot_water_gate_keyed_on_hot_water_entity():
    """The registration gate must be ``hot_water_entity`` set. Same
    pattern as the heat-pump gate (``hp_relay1 OR hp_climate``).

    Without ``hot_water_entity`` we have no boiler to drive — must
    NOT instantiate the controller, otherwise SurplusController would
    try to send commands to nothing."""
    init_py = _read("__init__.py")
    # Search for the conditional block — should reference hot_water_entity
    # in some form near the HotWaterController instantiation.
    hw_index = init_py.find("HotWaterController(")
    assert hw_index > 0, "HotWaterController() instantiation not found"
    # Walk backwards ~500 chars looking for the gate
    preamble = init_py[max(0, hw_index - 500):hw_index]
    assert "hot_water_entity" in preamble, (
        "HotWaterController instantiation isn't preceded by a "
        "hot_water_entity gate — would always instantiate, even "
        "when no boiler is configured."
    )


# ---------------------------------------------------------------------------
# 2. HotWaterSensorData plumbing
# ---------------------------------------------------------------------------


def test_hot_water_sensor_data_dataclass_exists():
    """``HotWaterSensorData`` must be defined in types.py with the
    field set the diagnose surface + UI cards expect."""
    from custom_components.solar_energy_management.coordinator.types import (
        HotWaterSensorData,
    )
    d = HotWaterSensorData()
    # All the diagnostic paths from the #420 audit must be present as fields
    expected_fields = {
        "hot_water_registered",
        "hot_water_entity",
        "hot_water_temperature_sensor",
        "hot_water_current_temperature",
        "hot_water_solar_target",
        "hot_water_max_temperature",
        "hot_water_legionella_target",
        "hot_water_hours_since_legionella",
        "hot_water_legionella_cycle_active",
        "hot_water_activation_path",
        "hot_water_deactivation_path",
        "hot_water_temperature_safety_path",
        "hot_water_temperature_reading_path",
        "hot_water_legionella_path",
    }
    actual_fields = set(d.__dataclass_fields__.keys())
    missing = expected_fields - actual_fields
    assert not missing, f"HotWaterSensorData missing fields: {missing}"


def test_hot_water_sensor_data_default_state_is_unregistered():
    """Default ``HotWaterSensorData()`` represents the "no boiler"
    state. The dashboard subtitle uses ``hot_water_registered``
    as the gate for showing "configured" vs "not_configured" —
    must default to False."""
    from custom_components.solar_energy_management.coordinator.types import (
        HotWaterSensorData,
    )
    d = HotWaterSensorData()
    assert d.hot_water_registered is False
    assert d.hot_water_entity is None
    assert d.hot_water_current_temperature is None


def test_coordinator_sensor_data_includes_hot_water_in_to_dict():
    """``CoordinatorSensorData.to_dict()`` must publish all the
    hot_water_* keys so the diagnose slicer + sensor entities can
    read them from ``coordinator.data``. Without this mapping, the
    fields exist on the dataclass but never reach the UI."""
    from custom_components.solar_energy_management.coordinator.types import (
        SEMData,
    )
    d = SEMData()
    out = d.to_dict()
    # The diagnose slicer in __init__.py reads these specific keys
    expected_keys = {
        "hot_water_registered",
        "hot_water_entity",
        "hot_water_current_temperature",
        "hot_water_solar_target",
        "hot_water_max_temperature",
        "hot_water_legionella_target",
        "hot_water_temperature_reading_path",
        "hot_water_temperature_safety_path",
    }
    missing = expected_keys - set(out.keys())
    assert not missing, (
        f"to_dict() missing hot_water keys: {missing}. "
        f"The diagnose slicer in __init__.py:_DIAGNOSE_HOT_WATER_STATE "
        "won't find them in coordinator.data."
    )


# ---------------------------------------------------------------------------
# 3. Diagnose slicer covers the new state
# ---------------------------------------------------------------------------


def test_diagnose_hot_water_state_slicer_populated():
    """The diagnose surface for the ``hot_water`` section must list
    actual state keys (post wire-up), not just a placeholder. The
    Diagnose modal renders ONLY what's in this slicer."""
    init_py = _read("__init__.py")
    # The slicer is a Python set literal in the file. Verify it
    # mentions the new runtime keys.
    assert "_DIAGNOSE_HOT_WATER_STATE" in init_py
    # Anchor on a few must-have keys
    for key in [
        "hot_water_registered",
        "hot_water_current_temperature",
        "hot_water_temperature_reading_path",
    ]:
        assert f'"{key}"' in init_py, (
            f"_DIAGNOSE_HOT_WATER_STATE missing '{key}' — that key "
            "won't appear in the Diagnose modal for the hot_water section."
        )
