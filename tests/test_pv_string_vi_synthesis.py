"""Tests for v1.7.0 V+I → P synthesis (#312, HA-PROD 2026-06-01).

Background. Several inverter integrations expose per-string voltage
and current sensors but no per-string power. Huawei Solar Modbus
(confirmed on HA-PROD: ``sensor.inverter_pv_1_spannung`` +
``sensor.inverter_pv_1_strom`` exist, ``..._power`` does not) is the
motivating case; generic Modbus drivers and Solarman-based bridges
behave the same.

Without these tests, v1.7.0 would silently leave Huawei users with
zero per-string sensors. The discovery's direct-power regex finds
nothing, the gate ``len >= 2`` holds zero, the sensor surface
stays empty — correct behaviour but useless on the most common
inverter brand in SEM's user base.

These tests pin three layers:

1. ``discover_pv_string_vi_pairs`` matches sibling V+I sensor pairs
   in the entity registry, gated on the same seed-platform rule
   as direct-power discovery.
2. ``SensorReader.set_pv_strings`` accepts the V+I map alongside
   the direct-power map; direct power wins on slot collisions.
3. ``SensorReader._read_pv_string_source`` multiplies V × I at read
   time for tuple-shaped sources; direct power entities use the
   legacy fast path.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.hardware_detection import (
    _PV_CURRENT_PATTERNS,
    _PV_VOLTAGE_PATTERNS,
)


class TestPatterns:
    """Regex matching for the V and I sibling patterns."""

    @pytest.mark.parametrize("eid,expected_n", [
        ("sensor.inverter_pv_1_spannung", 1),     # Huawei German
        ("sensor.inverter_pv1_voltage", 1),       # English
        ("sensor.inverter_pv_2_volt", 2),
        ("sensor.solar_mppt_1_voltage", 1),
        ("sensor.solar_string_3_spannung", 3),
    ])
    def test_voltage_pattern_extracts_string_number(self, eid, expected_n):
        for pat in _PV_VOLTAGE_PATTERNS:
            m = pat.search(eid)
            if m:
                assert int(m.group(1)) == expected_n
                return
        pytest.fail(f"No voltage pattern matched {eid!r}")

    @pytest.mark.parametrize("eid,expected_n", [
        ("sensor.inverter_pv_1_strom", 1),        # Huawei German
        ("sensor.inverter_pv1_current", 1),       # English
        ("sensor.inverter_pv_2_amp", 2),
        ("sensor.solar_mppt_1_current", 1),
        ("sensor.solar_string_3_strom", 3),
    ])
    def test_current_pattern_extracts_string_number(self, eid, expected_n):
        for pat in _PV_CURRENT_PATTERNS:
            m = pat.search(eid)
            if m:
                assert int(m.group(1)) == expected_n
                return
        pytest.fail(f"No current pattern matched {eid!r}")

    def test_power_entities_do_NOT_match_voltage_pattern(self):
        """The direct-power patterns and the V+I patterns must not
        overlap — same entity matching both would double-count."""
        for eid in ("sensor.inverter_pv_1_power", "sensor.inverter_mppt_1_power"):
            for pat in _PV_VOLTAGE_PATTERNS:
                assert pat.search(eid) is None, (
                    f"{eid} should NOT match voltage pattern {pat.pattern!r}"
                )


class TestSensorReaderVISynthesis:
    """``SensorReader._read_pv_string_source`` multiplies V × I for
    tuple-shaped sources; direct power entities take the legacy path."""

    def _make_reader(self):
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        sr = SensorReader.__new__(SensorReader)
        sr._sensor_unavailable = set()
        sr.hass = MagicMock()
        # _read_sensor reads from hass.states[entity].state. We mock it
        # to return whatever the caller stashed in ``_mock_values``.
        sr._mock_values = {}

        def mock_read(entity_id, _purpose):
            return float(sr._mock_values.get(entity_id, 0.0))

        sr._read_sensor = mock_read
        return sr

    def test_direct_power_source_passes_through(self):
        sr = self._make_reader()
        sr._mock_values["sensor.inverter_pv_1_power"] = 3500.0
        # str source → direct read path
        watts = sr._read_pv_string_source("pv1", "sensor.inverter_pv_1_power")
        assert watts == pytest.approx(3500.0)

    def test_vi_pair_multiplies_at_read(self):
        sr = self._make_reader()
        # Huawei PROD layout: V on string 1 = 480 V, I = 7.5 A → 3600 W
        sr._mock_values["sensor.inverter_pv_1_spannung"] = 480.0
        sr._mock_values["sensor.inverter_pv_1_strom"] = 7.5
        watts = sr._read_pv_string_source(
            "pv1",
            ("sensor.inverter_pv_1_spannung", "sensor.inverter_pv_1_strom"),
        )
        assert watts == pytest.approx(3600.0)

    def test_vi_pair_zero_when_either_missing_or_zero(self):
        """If V or I is 0/unavailable (night, fault), the product is 0
        — no negative or NaN leaking through."""
        sr = self._make_reader()
        sr._mock_values["sensor.inverter_pv_1_spannung"] = 480.0
        sr._mock_values["sensor.inverter_pv_1_strom"] = 0.0
        watts = sr._read_pv_string_source(
            "pv1",
            ("sensor.inverter_pv_1_spannung", "sensor.inverter_pv_1_strom"),
        )
        assert watts == 0.0


class TestSensorReaderSetPVStrings:
    """``set_pv_strings`` accepts both direct-power and V+I maps and
    stores them in the same ``_pv_strings`` dict, with the direct-
    power form winning on slot collisions."""

    def _make_reader(self):
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        return SensorReader.__new__(SensorReader)

    def test_direct_power_only(self):
        sr = self._make_reader()
        sr.set_pv_strings({
            "pv1_power": "sensor.inverter_pv_1_power",
            "pv2_power": "sensor.inverter_pv_2_power",
        })
        assert sr._pv_strings == {
            "pv1": "sensor.inverter_pv_1_power",
            "pv2": "sensor.inverter_pv_2_power",
        }

    def test_vi_pairs_only(self):
        sr = self._make_reader()
        sr.set_pv_strings({}, {
            "pv1": ("sensor.inverter_pv_1_spannung",
                    "sensor.inverter_pv_1_strom"),
            "pv2": ("sensor.inverter_pv_2_spannung",
                    "sensor.inverter_pv_2_strom"),
        })
        assert sr._pv_strings == {
            "pv1": ("sensor.inverter_pv_1_spannung",
                    "sensor.inverter_pv_1_strom"),
            "pv2": ("sensor.inverter_pv_2_spannung",
                    "sensor.inverter_pv_2_strom"),
        }

    def test_mixed_direct_power_wins_on_collision(self):
        """When the same slot has BOTH a direct power AND a V+I pair,
        the direct sensor wins — it's a real measurement, the V+I
        synthesis is a computed fallback. Matches the contract in
        ``set_pv_strings``'s docstring."""
        sr = self._make_reader()
        sr.set_pv_strings(
            {"pv1_power": "sensor.real_pv1_power"},
            {"pv1": ("sensor.fake_voltage", "sensor.fake_current")},
        )
        assert sr._pv_strings == {"pv1": "sensor.real_pv1_power"}

    def test_mixed_non_collision_merges(self):
        sr = self._make_reader()
        sr.set_pv_strings(
            {"pv1_power": "sensor.real_pv1_power"},
            {"pv2": ("sensor.pv2_v", "sensor.pv2_i")},
        )
        assert sr._pv_strings == {
            "pv1": "sensor.real_pv1_power",
            "pv2": ("sensor.pv2_v", "sensor.pv2_i"),
        }

    def test_empty_vi_pair_skipped(self):
        """Malformed V+I tuples (one entity missing) shouldn't pollute
        the slot map."""
        sr = self._make_reader()
        sr.set_pv_strings({}, {
            "pv1": ("sensor.pv1_v", ""),  # missing current
            "pv2": ("", "sensor.pv2_i"),  # missing voltage
            "pv3": (),                    # empty tuple
        })
        assert sr._pv_strings == {}


class TestDiscoveryFunction:
    """The discovery walks the entity registry; this exercises it
    against a small fake registry stub."""

    def _make_hass(self, entries):
        """``entries`` is a list of dicts with ``entity_id``,
        ``platform``, ``config_entry_id`` (default None),
        ``disabled_by`` (default None)."""
        hass = MagicMock()

        class FakeEntry:
            def __init__(self, eid, platform, config_entry_id=None, disabled_by=None):
                self.entity_id = eid
                self.platform = platform
                self.config_entry_id = config_entry_id
                self.disabled_by = disabled_by

        entries_objs = [
            FakeEntry(
                e["entity_id"], e["platform"],
                e.get("config_entry_id"), e.get("disabled_by"),
            )
            for e in entries
        ]

        registry = MagicMock()

        def get(entity_id):
            for e in entries_objs:
                if e.entity_id == entity_id:
                    return e
            return None
        registry.async_get = get
        registry.entities = MagicMock()
        registry.entities.values = lambda: entries_objs

        # Patch the global registry getter.
        from custom_components.solar_energy_management import hardware_detection
        from unittest.mock import patch
        return hass, patch.object(
            hardware_detection.entity_registry,
            "async_get",
            return_value=registry,
        )

    def test_huawei_layout_finds_vi_pairs(self):
        """The PROD-observed Huawei layout — German names, no power
        sensors — should yield 2 V+I pairs."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_pv_string_vi_pairs,
        )
        hass, patcher = self._make_hass([
            {"entity_id": "sensor.inverter_eingangsleistung", "platform": "huawei_solar"},
            {"entity_id": "sensor.inverter_pv_1_spannung", "platform": "huawei_solar"},
            {"entity_id": "sensor.inverter_pv_1_strom", "platform": "huawei_solar"},
            {"entity_id": "sensor.inverter_pv_2_spannung", "platform": "huawei_solar"},
            {"entity_id": "sensor.inverter_pv_2_strom", "platform": "huawei_solar"},
        ])
        ed_config = MagicMock(
            solar_power="sensor.inverter_eingangsleistung",
            solar_energy=None,
        )
        with patcher:
            result = discover_pv_string_vi_pairs(hass, ed_config)
        assert result == {
            "pv1": ("sensor.inverter_pv_1_spannung", "sensor.inverter_pv_1_strom"),
            "pv2": ("sensor.inverter_pv_2_spannung", "sensor.inverter_pv_2_strom"),
        }

    def test_returns_empty_when_seed_missing(self):
        from custom_components.solar_energy_management.hardware_detection import (
            discover_pv_string_vi_pairs,
        )
        hass, patcher = self._make_hass([])
        with patcher:
            # No ed_config → empty
            assert discover_pv_string_vi_pairs(hass, None) == {}
            # ed_config with no solar source → empty
            empty = MagicMock(solar_power=None, solar_energy=None)
            assert discover_pv_string_vi_pairs(hass, empty) == {}

    def test_returns_empty_when_fewer_than_2_pairs(self):
        """Single-string installs aren't worth a per-string surface —
        the v1.7.0 gate is ``len >= 2``. Return empty before SEM
        creates a misleading single-entity row."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_pv_string_vi_pairs,
        )
        hass, patcher = self._make_hass([
            {"entity_id": "sensor.inverter_eingangsleistung", "platform": "huawei_solar"},
            {"entity_id": "sensor.inverter_pv_1_spannung", "platform": "huawei_solar"},
            {"entity_id": "sensor.inverter_pv_1_strom", "platform": "huawei_solar"},
        ])
        ed_config = MagicMock(
            solar_power="sensor.inverter_eingangsleistung",
            solar_energy=None,
        )
        with patcher:
            assert discover_pv_string_vi_pairs(hass, ed_config) == {}

    def test_returns_empty_when_only_voltage_present(self):
        """Voltage without matching current → no pair. Return empty."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_pv_string_vi_pairs,
        )
        hass, patcher = self._make_hass([
            {"entity_id": "sensor.inverter_eingangsleistung", "platform": "huawei_solar"},
            {"entity_id": "sensor.inverter_pv_1_spannung", "platform": "huawei_solar"},
            {"entity_id": "sensor.inverter_pv_2_spannung", "platform": "huawei_solar"},
            # No _strom entries
        ])
        ed_config = MagicMock(
            solar_power="sensor.inverter_eingangsleistung",
            solar_energy=None,
        )
        with patcher:
            assert discover_pv_string_vi_pairs(hass, ed_config) == {}
