"""Regression guard for #379 — Growatt 2-PV-string discovery + aggregation.

User #379 reports: Growatt + 2 PV strings, both visible in HA Energy
Dashboard. SEM dashboard shows PV1 value, PV2 empty.

Possible root causes:
  1. ``discover_pv_strings_from_registry`` doesn't match Growatt's
     entity naming → only PV1 detected (PV2 not in result dict).
  2. Discovery finds both but ``solar_power_per_string`` reads only
     one (entity unavailable, state non-numeric, etc.).
  3. Dashboard card doesn't render the per-string data even though
     the underlying ``PowerReadings.solar_power_per_string`` is
     correct.

Discovery for Huawei / Sungrow / Fronius / Kostal / Victron is
already tested in ``tests/test_hardware_detection.py``. Growatt
specifically was NOT — this file fills that gap by pinning the
discovery contract for the most common Growatt naming patterns.

If the user's diagnostic dump shows the discovery result has
entries for both pv1 and pv2, the bug is downstream (#2 or #3
above) and a different test would pin it.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.hardware_detection import (
    discover_pv_strings_from_registry,
)


class _Entry:
    """Minimal mock of an entity_registry entry."""

    def __init__(self, entity_id: str, platform: str,
                 config_entry_id: str = "growatt_cfg",
                 disabled_by=None) -> None:
        self.entity_id = entity_id
        self.platform = platform
        self.config_entry_id = config_entry_id
        self.disabled_by = disabled_by


class _CfgWithSolar:
    def __init__(self, solar_power: str, solar_energy: str = "") -> None:
        self.solar_power = solar_power
        self.solar_energy = solar_energy


def _patch_registry(entries):
    """Patch entity_registry.async_get to return a fake registry."""
    fake_reg = MagicMock()
    fake_reg.entities = MagicMock()
    fake_reg.entities.values = MagicMock(return_value=iter(entries))
    fake_reg.async_get = MagicMock(
        side_effect=lambda eid: next((e for e in entries if e.entity_id == eid), None)
    )
    return patch(
        "custom_components.solar_energy_management.hardware_detection."
        "entity_registry.async_get",
        return_value=fake_reg,
    )


# ---------------------------------------------------------------------------
# #379 — Growatt discovery contract
# ---------------------------------------------------------------------------


class Test379GrowattPVDiscovery:
    """The Growatt modbus integration publishes per-string sensors as
    ``sensor.growatt_..._pv1_power`` / ``sensor.growatt_..._pv2_power``.
    The PV pattern at ``hardware_detection.py:_PV_STRING_PATTERNS``
    must match these.
    """

    def test_growatt_two_strings_both_discovered(self) -> None:
        """The user #379 case: both PV1 and PV2 sensors exist; both
        must appear in the discovery result."""
        entries = [
            # Sibling entity from same integration — seed for discovery.
            _Entry("sensor.growatt_inverter_solar_power", "growatt_local"),
            _Entry("sensor.growatt_inverter_pv1_power", "growatt_local"),
            _Entry("sensor.growatt_inverter_pv2_power", "growatt_local"),
        ]
        cfg = _CfgWithSolar(solar_power="sensor.growatt_inverter_solar_power")

        with _patch_registry(entries):
            result = discover_pv_strings_from_registry(MagicMock(), cfg)

        assert "pv1_power" in result, f"PV1 missing from {result!r}"
        assert "pv2_power" in result, f"PV2 missing from {result!r}"
        assert result["pv1_power"] == "sensor.growatt_inverter_pv1_power"
        assert result["pv2_power"] == "sensor.growatt_inverter_pv2_power"

    def test_growatt_three_strings_all_discovered(self) -> None:
        """Some Growatt MOD-series inverters have 3 MPPT trackers."""
        entries = [
            _Entry("sensor.growatt_inverter_solar_power", "growatt_local"),
            _Entry("sensor.growatt_inverter_pv1_power", "growatt_local"),
            _Entry("sensor.growatt_inverter_pv2_power", "growatt_local"),
            _Entry("sensor.growatt_inverter_pv3_power", "growatt_local"),
        ]
        cfg = _CfgWithSolar(solar_power="sensor.growatt_inverter_solar_power")

        with _patch_registry(entries):
            result = discover_pv_strings_from_registry(MagicMock(), cfg)

        assert {"pv1_power", "pv2_power", "pv3_power"} <= set(result.keys()), (
            f"missing PV strings in {result!r}"
        )

    def test_growatt_disabled_pv2_skipped(self) -> None:
        """If the user disabled the PV2 entity in HA, discovery skips it
        and the dashboard would show only PV1 — this would be the
        user's responsibility to re-enable, NOT a SEM bug."""
        from homeassistant.helpers.entity_registry import RegistryEntryDisabler

        entries = [
            _Entry("sensor.growatt_inverter_solar_power", "growatt_local"),
            _Entry("sensor.growatt_inverter_pv1_power", "growatt_local"),
            _Entry(
                "sensor.growatt_inverter_pv2_power", "growatt_local",
                disabled_by=RegistryEntryDisabler.USER,
            ),
        ]
        cfg = _CfgWithSolar(solar_power="sensor.growatt_inverter_solar_power")

        with _patch_registry(entries):
            result = discover_pv_strings_from_registry(MagicMock(), cfg)

        # Only PV1 found.
        assert "pv1_power" in result
        assert "pv2_power" not in result

    def test_growatt_different_config_entry_filtered(self) -> None:
        """A PV2 entity from a DIFFERENT integration (e.g., user has
        2 inverters configured) must not get pulled into the first
        inverter's per-string set."""
        entries = [
            _Entry("sensor.growatt_inv1_solar_power", "growatt_local",
                   config_entry_id="inverter_1"),
            _Entry("sensor.growatt_inv1_pv1_power", "growatt_local",
                   config_entry_id="inverter_1"),
            _Entry("sensor.growatt_inv2_pv1_power", "growatt_local",
                   config_entry_id="inverter_2"),  # different config entry
        ]
        cfg = _CfgWithSolar(solar_power="sensor.growatt_inv1_solar_power")

        with _patch_registry(entries):
            result = discover_pv_strings_from_registry(MagicMock(), cfg)

        # Only inverter_1's PV1 is in the result. The PV1 from inverter_2
        # would be discovered as inverter_2's pv1 when that's the seed.
        assert result == {"pv1_power": "sensor.growatt_inv1_pv1_power"}


# ---------------------------------------------------------------------------
# Diagnostic — what to check when a user reports the bug
# ---------------------------------------------------------------------------


def test_379_diagnostic_marker_for_user_dump() -> None:
    """Documentation test: when a user reports #379, ask them to share:

      1. ``Developer Tools → States → sensor.growatt_*`` — list of all
         Growatt-related entities. The discovery only finds PV strings
         that match the patterns in
         ``hardware_detection._PV_STRING_PATTERNS``.
      2. The output of ``solar_energy_management.generate_dashboard``
         service in DEBUG log mode — shows discovery's result dict.
      3. Their HA Energy Dashboard config — confirms that both PV
         sensors are listed there.

    If discovery finds both but the dashboard still shows PV2 empty,
    the bug is in the SensorReader read path or the K-Flow card's
    rendering — not in this discovery layer.

    This test is a no-op assertion that exists so ``pytest -k 379``
    surfaces the diagnostic guide in the test name.
    """
    assert True
