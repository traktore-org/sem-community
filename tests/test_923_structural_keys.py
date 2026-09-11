"""#923 — adding hardware through set_option must create its entities.

set_option reloads the entry only for _SET_OPTION_STRUCTURAL_KEYS. A module
wiring key outside that set would be stored and do nothing visible until the
next restart: the module's entities are created at platform setup."""
from custom_components.solar_energy_management import _SET_OPTION_STRUCTURAL_KEYS
from custom_components.solar_energy_management.coordinator.install_modules import (
    MODULE_EVIDENCE_KEYS,
)


def test_every_module_wiring_key_reloads_when_set():
    missing = sorted(MODULE_EVIDENCE_KEYS - _SET_OPTION_STRUCTURAL_KEYS)
    assert not missing, f"module wiring keys that would not reload: {missing}"
