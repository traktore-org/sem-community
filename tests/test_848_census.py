"""#848 — detection asks Home Assistant what is INSTALLED before it
matches anything.

Guido, 27.08: "Do we read out all HACS integrations or HA integrations?"
The honest answer was NEITHER — the glob matrix ran blind against entity
ids. The census inverts that: every installed integration (core and HACS
alike — both are just domains) is enumerated, classified against what SEM
knows, and the two gaps become report lines instead of silent misses:

* ``unknown_energy_domains`` — an integration with energy-shaped devices
  SEM has no row for ("integration X installed, SEM cannot place it");
* ``rows_matched_nothing`` — a known platform present in the registry
  whose discovery produced no device ("row keba: installed but nothing
  matched" — a detection bug surfaced by the install itself).
"""
from __future__ import annotations

from types import SimpleNamespace


def _ent(eid, platform, device_class=None, device_id=None, disabled=False,
         unique_id=None):
    return SimpleNamespace(
        entity_id=eid, platform=platform,
        original_device_class=device_class, device_id=device_id,
        disabled_by=("user" if disabled else None),
        unique_id=unique_id or eid, translation_key=None,
    )


def _registry(entries):
    reg = SimpleNamespace()
    reg.entities = {e.entity_id: e for e in entries}
    return reg


def _census(entries, config_domains=None, matched_charger_platforms=None):
    from custom_components.solar_energy_management.hardware_detection import (
        build_integration_census,
    )
    return build_integration_census(
        registry=_registry(entries), config_domains=config_domains,
        matched_charger_platforms=matched_charger_platforms)


KEBA = [
    _ent("binary_sensor.keba_p30_plug", "keba", device_class="plug", device_id="d1"),
    _ent("sensor.keba_p30_charging_power", "keba", device_class="power", device_id="d1"),
    _ent("sensor.keba_p30_max_current", "keba", device_class="current", device_id="d1"),
]


class TestTheCensusSeesWhatIsInstalled:
    def test_installed_domains_come_from_registry_and_config_entries(self):
        c = _census(KEBA, config_domains={"keba", "huawei_solar", "mqtt"})
        assert "keba" in c["installed"]
        assert "huawei_solar" in c["installed"]          # entry without entities still counts
        assert c["known_charger_platforms_present"] == ["keba"]

    def test_sems_own_platform_is_never_census_material(self):
        c = _census(KEBA + [_ent("sensor.sem_solar_power", "solar_energy_management")])
        assert "solar_energy_management" not in c["installed"]

    def test_a_known_inverter_domain_is_classified(self):
        c = _census([_ent("sensor.inverter_pv", "huawei_solar", device_class="power")])
        assert c["known_inverter_domains_present"] == ["huawei_solar"]
        assert c["unknown_energy_domains"] == []


class TestTheTwoGapLines:
    def test_an_unknown_domain_with_energy_shape_is_named(self):
        """The EG4/Victron case: an integration SEM has no row for, whose
        devices look like energy hardware — the census names it instead of
        silently ignoring it."""
        eg4 = [
            _ent("sensor.flexboss_pv_power", "eg4_web_monitor", device_class="power", device_id="x"),
            _ent("sensor.flexboss_battery_soc", "eg4_web_monitor", device_class="battery", device_id="x"),
            _ent("number.flexboss_charge_limit", "eg4_web_monitor", device_class="current", device_id="x"),
        ]
        c = _census(KEBA + eg4)
        assert c["unknown_energy_domains"] == ["eg4_web_monitor"]

    def test_a_lighting_integration_is_not_energy_noise(self):
        c = _census(KEBA + [
            _ent("light.kitchen", "hue", device_id="h1"),
            _ent("sensor.kitchen_brightness", "hue", device_id="h1"),
        ])
        assert c["unknown_energy_domains"] == []

    def test_a_power_only_domain_is_not_flagged(self):
        """A smart plug's power sensor alone is not energy HARDWARE — the
        flag needs a second signal (SOC, current control, plug state)."""
        c = _census(KEBA + [
            _ent("sensor.plug_power", "shelly", device_class="power", device_id="s1"),
        ])
        assert c["unknown_energy_domains"] == []

    def test_a_present_row_that_matched_nothing_is_a_finding(self):
        """`zaptec` entities exist, but the discover produced no charger →
        that is a DETECTION bug made visible, not a silent miss."""
        weird_zaptec = [
            _ent("sensor.zaptec_something_odd", "zaptec", device_id="z1"),
        ]
        c = _census(KEBA + weird_zaptec, matched_charger_platforms={"keba"})
        assert c["rows_matched_nothing"] == ["zaptec"]

    def test_a_row_that_matched_is_clean(self):
        c = _census(KEBA, matched_charger_platforms={"keba"})
        assert c["rows_matched_nothing"] == []


class TestTheReportCarriesTheCensus:
    def test_build_detection_report_embeds_it_and_serializes(self):
        import json

        from custom_components.solar_energy_management.hardware_detection import (
            build_detection_report,
        )
        rep = build_detection_report(registry=_registry(KEBA))
        assert "census" in rep
        assert rep["census"]["known_charger_platforms_present"] == ["keba"]
        assert rep["census"]["rows_matched_nothing"] == []   # keba matched
        json.dumps(rep)                                       # serializable

    def test_the_gap_feeds_from_the_reports_own_chargers(self):
        """A zaptec device the brand walk cannot place lands in
        rows_matched_nothing without the caller passing anything."""
        from custom_components.solar_energy_management.hardware_detection import (
            build_detection_report,
        )
        rep = build_detection_report(registry=_registry(KEBA + [
            _ent("sensor.zaptec_something_odd", "zaptec", device_id="z1"),
        ]))
        assert rep["census"]["rows_matched_nothing"] == ["zaptec"]
