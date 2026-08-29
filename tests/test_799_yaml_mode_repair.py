"""#799 — a YAML-mode Lovelace install must be TOLD, not logged at.

RonaldHass installed SEM on HA 2026.8.2, got a dashboard full of
"Configuration Error" cards, removed and reinstalled twice, and only
solved it by finding a single WARNING line in the HA log that carried the
resource URLs. The information existed (#283 added it); the surface
didn't. A Repair issue is the surface: it appears in Settings, it carries
the URLs, and it clears itself once the resources are in place.
"""
from custom_components.solar_energy_management import yaml_mode_repair


class TestRepairPayload:

    def test_yaml_mode_repair_names_the_urls(self):
        r = yaml_mode_repair(
            yaml_mode=True,
            urls=["/local/custom_components/solar_energy_management/dashboard/card/dist/sem-cards.js?v=2.0.0-abc",
                  "/local/custom_components/solar_energy_management/dashboard/card/sem-localize.js?v=2.0.0-def"],
        )
        assert r is not None
        assert r["translation_key"] == "lovelace_yaml_mode"
        # the payload must carry something the user can paste
        blob = r["placeholders"]["resources"]
        assert "sem-cards.js" in blob and "sem-localize.js" in blob
        assert "type: module" in blob
        assert blob.count("- url:") == 2

    def test_storage_mode_is_silent(self):
        assert yaml_mode_repair(yaml_mode=False, urls=["x"]) is None

    def test_no_urls_is_silent_not_a_broken_repair(self):
        assert yaml_mode_repair(yaml_mode=True, urls=[]) is None


class TestTranslations:

    def test_issue_string_exists_in_every_language(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        en = json.loads((root / "strings.json").read_text())
        assert "lovelace_yaml_mode" in en["issues"], "strings.json missing the issue"
        body = en["issues"]["lovelace_yaml_mode"]["description"]
        assert "{resources}" in body, "the repair must show the URLs"
        for f in sorted((root / "translations").glob("*.json")):
            data = json.loads(f.read_text())
            assert "lovelace_yaml_mode" in data.get("issues", {}), f"{f.name} missing"
