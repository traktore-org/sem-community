"""#804 — Zaptec detection must survive a localised or renamed install.

@coppe218's box is Dutch. His installation's current number is
``number.guido_coppes_beschikbare_stroom`` — named after the OWNER and in
Dutch — and the charger's numbers follow the same shape. The word "current"
appears nowhere in any of his entity ids.

``_discover_zaptec`` matched roles with English substrings over entity ids
("current" in eid, "cable" in eid, …), so on his install it found readings by
device class and NO control at all. SEM could read his charger and never
command it — the "SEM may not be actuating the Zaptec at all" he reported,
diagnosed live in #804.

The #562 lesson applies unchanged: entity ids are localised and renameable;
the registry ``unique_id`` is neither. custom-components/zaptec builds them as
``{object_id}_{key}`` with fixed English keys (``charger_max_current``,
``available_current``, …), so the suffix identifies the role in every
language.

Two design facts pinned here, both measured on the reporter's hardware:

* the control is the CHARGER-level ``charger_max_current`` — writing 0 is a
  soft pause and raising it resumes automatically (his half-hour hold test),
  which is exactly SEM's stop=0/start=N model, and how EVCC drives the brand;
* the installation's ``available_current`` is the user's grid guard
  (3×25 A in his case) and must NOT be taken as SEM's throttle, even when the
  charger-level number is missing — a wrong write there constrains the whole
  installation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.hardware_detection import (
    discover_all_ev_chargers_from_registry,
)


def _entry(entity_id, platform, device_id, unique_id, device_class=None):
    return SimpleNamespace(
        entity_id=entity_id,
        platform=platform,
        device_id=device_id,
        unique_id=unique_id,
        original_device_class=device_class,
        disabled_by=None,
    )


def _dutch_registry():
    """coppe218's install, as the registry actually shows it."""
    return [
        # installation device — Dutch, owner-named
        _entry("number.guido_coppes_beschikbare_stroom", "zaptec",
               "install-1", "inst1_available_current", "current"),
        _entry("number.guido_coppes_terugschakelen_van_drie_naar_een_fase",
               "zaptec", "install-1",
               "inst1_three_to_one_phase_switch_current", "current"),
        # charger device — Dutch
        _entry("binary_sensor.guido_coppes_lader_kabel_aangesloten", "zaptec",
               "charger-1", "chg1_cable_connected", "plug"),
        _entry("binary_sensor.guido_coppes_lader_bezig_met_laden", "zaptec",
               "charger-1", "chg1_charging", None),
        _entry("sensor.guido_coppes_lader_laadvermogen", "zaptec",
               "charger-1", "chg1_charge_power", "power"),
        _entry("number.guido_coppes_lader_maximale_laadstroom", "zaptec",
               "charger-1", "chg1_charger_max_current", "current"),
        _entry("number.guido_coppes_lader_minimale_laadstroom", "zaptec",
               "charger-1", "chg1_charger_min_current", "current"),
    ]


def _discover(entries):
    registry = MagicMock()
    registry.entities.values.return_value = entries
    with patch(
        "custom_components.solar_energy_management.hardware_detection."
        "entity_registry.async_get",
        return_value=registry,
    ):
        return discover_all_ev_chargers_from_registry(MagicMock())


class TestLocalisedInstall:
    def test_the_charger_is_found_with_its_control(self):
        found = [c for c in _discover(_dutch_registry())
                 if c.get("_device_id") == "charger-1"]
        assert found, "the Dutch-named charger was not discovered at all"
        c = found[0]
        assert c.get("ev_current_control_entity") == \
            "number.guido_coppes_lader_maximale_laadstroom", (
                f"control={c.get('ev_current_control_entity')!r} — the "
                "charger-level max-current was not identified; English "
                "substring matching cannot see a Dutch install (#804)"
            )

    def test_min_current_is_not_mistaken_for_the_throttle(self):
        found = [c for c in _discover(_dutch_registry())
                 if c.get("_device_id") == "charger-1"]
        assert found and found[0].get("ev_current_control_entity") != \
            "number.guido_coppes_lader_minimale_laadstroom"

    def test_the_installation_guard_is_never_the_throttle(self):
        """available_current is the user's 3×25 A grid guard. Even on a
        charger with NO usable control, SEM must not adopt it."""
        entries = [e for e in _dutch_registry()
                   if e.unique_id != "chg1_charger_max_current"]
        for c in _discover(entries):
            assert c.get("ev_current_control_entity") != \
                "number.guido_coppes_beschikbare_stroom", (
                    "SEM took the INSTALLATION current limit as its throttle "
                    "— that number is the grid guard for every charger on the "
                    "installation (#804)"
                )


class TestEnglishInstallStillWorks:
    def test_the_existing_english_shape_is_unchanged(self):
        entries = [
            _entry("binary_sensor.zaptec_garage_cable_connected", "zaptec",
                   "charger-42", "z42_cable_connected"),
            _entry("binary_sensor.zaptec_garage_charging", "zaptec",
                   "charger-42", "z42_charging"),
            _entry("sensor.zaptec_garage_total_charge_power", "zaptec",
                   "charger-42", "z42_total_charge_power"),
            _entry("number.zaptec_garage_charger_max_current", "zaptec",
                   "charger-42", "z42_charger_max_current", "current"),
        ]
        found = _discover(entries)
        assert len(found) == 1
        assert found[0]["ev_current_control_entity"] == \
            "number.zaptec_garage_charger_max_current"
