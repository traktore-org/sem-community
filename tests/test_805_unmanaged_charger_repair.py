"""#805 fix 3 — name the charger SEM found but does not manage.

The existing ``ev_charger_not_configured`` repair fires for everyone
without a charger, including solar-only installs that own no car. It nags
people about something absent and names nothing, which is why the #803
reporter — who DID own a wallbox — got no useful signal from it.

The replacement fires only when discovery actually found something
charger-shaped that SEM is not managing, and says which device. That is
the one line that would have prevented #803: it turns an invisible import
into an offer.

Guido's calls: a Repair (persists in the UI, has an action to take), a
name-based guess, and HA's own translation machinery so the text arrives
in the user's language exactly like the dashboard does.
"""
from __future__ import annotations

from custom_components.solar_energy_management import (
    CHARGER_NAME_MARKERS, charger_shaped_devices,
)


class TestTheGuess:

    def test_it_recognises_the_common_brands(self):
        found = charger_shaped_devices([
            "switch.wallbox_pro", "switch.keba_p30_enable",
            "switch.easee_charger", "switch.go_echarger_alw",
            "switch.evse_freigabe", "switch.zaptec_go",
        ])
        assert len(found) == 6

    def test_a_german_wallbox_name_counts(self):
        assert charger_shaped_devices(["switch.wb_einfahrt_ladefreigabe"])

    def test_it_does_not_grab_ordinary_loads(self):
        assert charger_shaped_devices([
            "switch.towel_rail", "switch.pool_pump", "switch.dishwasher",
            "switch.garage_light", "switch.kaffeetoaster",
        ]) == []

    def test_the_marker_list_is_word_ish_not_substring_soup(self):
        # "charge" must not match "recharge_reminder"; a marker that fires
        # on any substring turns the guess into noise (#781's lesson).
        assert charger_shaped_devices(["switch.recharge_reminder"]) == []

    def test_markers_are_declared_not_inlined(self):
        assert "wallbox" in CHARGER_NAME_MARKERS
        assert "keba" in CHARGER_NAME_MARKERS


class TestWhenItFires:

    def test_a_found_but_unconfigured_charger_is_reported(self):
        from custom_components.solar_energy_management import (
            unmanaged_charger_repair,
        )
        r = unmanaged_charger_repair(
            config={}, candidates=["switch.wallbox_pro"])
        assert r is not None
        assert r["translation_key"] == "unmanaged_charger_found"
        assert r["placeholders"]["name"] == "switch.wallbox_pro"

    def test_a_configured_install_is_silent(self):
        from custom_components.solar_energy_management import (
            unmanaged_charger_repair,
        )
        assert unmanaged_charger_repair(
            config={"ev_charging_power_sensor": "sensor.wb"},
            candidates=["switch.wallbox_pro"]) is None

    def test_a_solar_only_install_is_not_nagged(self):
        # THE noise fix: no car, no charger-shaped device, no repair.
        from custom_components.solar_energy_management import (
            unmanaged_charger_repair,
        )
        assert unmanaged_charger_repair(config={}, candidates=[]) is None

    def test_several_candidates_name_one_and_count_the_rest(self):
        from custom_components.solar_energy_management import (
            unmanaged_charger_repair,
        )
        r = unmanaged_charger_repair(config={}, candidates=[
            "switch.wallbox_pro", "switch.keba_p30_enable"])
        assert r["placeholders"]["name"] == "switch.wallbox_pro"
        assert r["placeholders"]["count"] == "2"


class TestItSpeaksTheUsersLanguage:

    def test_the_key_exists_in_strings_and_every_translation(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        base = json.loads((root / "strings.json").read_text())
        assert "unmanaged_charger_found" in base["issues"]
        for f in sorted((root / "translations").glob("*.json")):
            d = json.loads(f.read_text())
            iss = d.get("issues", {})
            assert "unmanaged_charger_found" in iss, f"{f.name} missing the key"
            for field in ("title", "description"):
                assert iss["unmanaged_charger_found"].get(field), \
                    f"{f.name}: {field} empty"
