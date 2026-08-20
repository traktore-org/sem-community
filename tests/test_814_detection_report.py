"""#814 Pillar B — detection shows its work.

Every discovery carries evidence: which entity took which role, which
entities on the same device were left unmapped, and — the #803/#802 class
made visible — platforms whose entities were present but no role matched
(near-misses). Built at the assembly layer over the existing per-brand
functions, so no brand logic changes.
"""
from types import SimpleNamespace

from custom_components.solar_energy_management.hardware_detection import (
    build_detection_report,
)


def _ent(entity_id, platform, device_id="dev1", device_class=None, disabled=False):
    return SimpleNamespace(
        entity_id=entity_id, platform=platform, device_id=device_id,
        original_device_class=device_class, disabled_by=("user" if disabled else None),
    )


def _registry(entries):
    reg = SimpleNamespace()
    reg.entities = {e.entity_id: e for e in entries}
    return reg


class TestChargerEvidence:

    def test_mapped_roles_carry_their_entities_and_why(self):
        reg = _registry([
            _ent("binary_sensor.keba_p30_plug", "keba", device_class="plug"),
            _ent("binary_sensor.keba_p30_charging_state", "keba", device_class="power"),
            _ent("sensor.keba_p30_charging_power", "keba", device_class="power"),
            _ent("sensor.keba_p30_total_energy", "keba", device_class="energy"),
            _ent("sensor.keba_p30_max_current", "keba", device_class="current"),
            _ent("sensor.keba_p30_status", "keba"),              # no role
        ])
        rep = build_detection_report(registry=reg)
        assert len(rep["chargers"]) == 1
        ch = rep["chargers"][0]
        assert ch["platform"] == "keba"
        assert ch["device_id"] == "dev1"
        assert ch["mapped"]["ev_connected_sensor"]["entity"] == "binary_sensor.keba_p30_plug"
        assert ch["mapped"]["ev_connected_sensor"]["device_class"] == "plug"
        assert ch["mapped"]["ev_charging_power_sensor"]["entity"] == "sensor.keba_p30_charging_power"
        # the status sensor was on the device but took no role — said so
        assert any(u["entity"] == "sensor.keba_p30_status" for u in ch["unmapped"])
        assert ch["control"] == "service: keba.set_current"

    def test_near_miss_is_reported_not_swallowed(self):
        # A brand platform with entities SEM recognizes as a platform but
        # can map to NOTHING — today this detects silently as "no charger";
        # the report names it so the user sees the gap, not broken behavior.
        reg = _registry([
            _ent("sensor.wallbox_portal_temperature", "wallbox", device_class="temperature"),
            _ent("sensor.wallbox_portal_firmware", "wallbox"),
        ])
        rep = build_detection_report(registry=reg)
        assert rep["chargers"] == []
        assert len(rep["near_misses"]) == 1
        nm = rep["near_misses"][0]
        assert nm["platform"] == "wallbox"
        assert {e["entity"] for e in nm["entities"]} == {
            "sensor.wallbox_portal_temperature", "sensor.wallbox_portal_firmware"}

    def test_disabled_entities_are_ignored_and_listed(self):
        reg = _registry([
            _ent("binary_sensor.keba_p30_plug", "keba", device_class="plug"),
            _ent("sensor.keba_p30_charging_power", "keba", device_class="power"),
            _ent("sensor.keba_p30_session_energy", "keba", device_class="energy", disabled=True),
        ])
        rep = build_detection_report(registry=reg)
        ch = rep["chargers"][0]
        assert "ev_session_energy_sensor" not in ch["mapped"]
        assert "sensor.keba_p30_session_energy" in rep["disabled_ignored"]

    def test_two_devices_of_one_brand_are_two_chargers(self):
        reg = _registry([
            _ent("binary_sensor.wallbox_a_status", "wallbox", device_id="A", device_class="plug"),
            _ent("sensor.wallbox_a_charging_power", "wallbox", device_id="A", device_class="power"),
            _ent("binary_sensor.wallbox_b_status", "wallbox", device_id="B", device_class="plug"),
            _ent("sensor.wallbox_b_charging_power", "wallbox", device_id="B", device_class="power"),
        ])
        rep = build_detection_report(registry=reg)
        assert {c["device_id"] for c in rep["chargers"]} >= {"A", "B"} or \
            len(rep["chargers"]) + len(rep["near_misses"]) == 2

    def test_scanned_platforms_listed_and_empty_registry_is_quiet(self):
        rep = build_detection_report(registry=_registry([]))
        assert rep["chargers"] == [] and rep["near_misses"] == []
        assert "keba" in rep["scanned_platforms"]
        assert rep["generated_at"]


class TestReportIsSerializable:

    def test_json_round_trip(self):
        import json
        reg = _registry([
            _ent("binary_sensor.keba_p30_plug", "keba", device_class="plug"),
            _ent("sensor.keba_p30_charging_power", "keba", device_class="power"),
        ])
        rep = build_detection_report(registry=reg)
        assert json.loads(json.dumps(rep)) == rep


class TestPublishedEveryCycle:

    def test_publish_diag_carries_the_report(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.coordinator.publish_diag import (
            build_diagnostics,
        )
        coord = MagicMock()
        coord.trace_health.return_value = {"ok": True}
        coord._ev_devices = {}
        coord.config = {}
        coord.update_interval = SimpleNamespace(total_seconds=lambda: 10)
        coord._observer_mode = False
        coord._detection_report = {"chargers": [], "near_misses": [{"platform": "wallbox"}]}
        out = build_diagnostics(coord)
        assert out["detection_report"]["near_misses"][0]["platform"] == "wallbox"


class TestGenericProber:
    """(#814 Pillar A, land-asleep) A capability prober that classifies
    charger candidates from what entities ARE on one registry device —
    domain + device_class — never from brand names. Runs BESIDE the brand
    functions; its candidates and any disagreement ride the report."""

    def _dev(self, platform, device_id, specs):
        return [_ent(eid, platform, device_id=device_id, device_class=dc)
                for eid, dc in specs]

    def test_unknown_platform_with_charger_shape_is_a_candidate(self):
        from custom_components.solar_energy_management.hardware_detection import (
            probe_charger_candidates,
        )
        reg = _registry(self._dev("abl_emh1", "d9", [
            ("sensor.abl_power", "power"),
            ("binary_sensor.abl_plug", "plug"),
            ("number.abl_max_current", "current"),
        ]))
        cands = probe_charger_candidates(registry=reg)
        assert len(cands) == 1
        c = cands[0]
        assert c["platform"] == "abl_emh1"
        assert c["roles"]["ev_charging_power_sensor"] == "sensor.abl_power"
        assert c["roles"]["ev_connected_sensor"] == "binary_sensor.abl_plug"
        assert c["roles"]["ev_current_control_entity"] == "number.abl_max_current"
        assert c["evidence"]  # says why each role matched

    def test_an_inverter_device_is_not_a_charger_candidate(self):
        from custom_components.solar_energy_management.hardware_detection import (
            probe_charger_candidates,
        )
        # power + energy but no plug/charging binary and no current control
        reg = _registry(self._dev("huawei_solar", "inv", [
            ("sensor.inverter_input_power", "power"),
            ("sensor.inverter_daily_yield", "energy"),
            ("sensor.inverter_temperature", "temperature"),
        ]))
        assert probe_charger_candidates(registry=reg) == []

    def test_report_carries_prober_candidates_and_disagreements(self):
        # KEBA: brand function AND prober should agree (same device).
        # ABL-shaped unknown platform: only the prober sees it → disagreement
        # that reads "prober found a charger shape the brand list does not".
        reg = _registry(
            self._dev("keba", "k1", [
                ("binary_sensor.keba_p30_plug", "plug"),
                ("sensor.keba_p30_charging_power", "power"),
                ("binary_sensor.keba_p30_charging_state", "power"),
            ]) + self._dev("abl_emh1", "d9", [
                ("sensor.abl_power", "power"),
                ("binary_sensor.abl_plug", "plug"),
                ("number.abl_max_current", "current"),
            ]))
        rep = build_detection_report(registry=reg)
        plats = {c["platform"] for c in rep["prober_candidates"]}
        assert "abl_emh1" in plats
        assert any(d["platform"] == "abl_emh1" and d["kind"] == "prober_only"
                   for d in rep["disagreements"])
        assert not any(d["platform"] == "keba" for d in rep["disagreements"])
