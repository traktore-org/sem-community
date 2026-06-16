"""#523 — per-battery SOC auto-detect must handle INDEXED device names.

The per-battery tiles read 0% SOC on multi-battery installs because
``_auto_detect_battery_soc`` only tried a 2-part prefix:
``test_battery_2_power`` → prefix ``test_battery`` → looked for
``sensor.test_battery_soc`` and missed the real
``sensor.test_battery_2_soc``. The fix tries progressively shorter
stems (longest first) so the indexed stem matches before the 2-part
fallback that still finds Huawei's ``sensor.battery_1_batterieladung``.
"""
from __future__ import annotations

from unittest.mock import Mock

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def _reader_with_states(states: dict):
    """SensorReader whose hass.states.get resolves from a plain dict of
    ``entity_id -> state_string``."""
    hass = Mock()
    hass.states = Mock()
    hass.states.get = lambda eid: (
        Mock(state=states[eid]) if eid in states else None
    )
    return SensorReader(hass, {})


def test_indexed_device_soc_detected():
    """``test_battery_2_power`` resolves ``sensor.test_battery_2_soc``."""
    r = _reader_with_states({"sensor.test_battery_2_soc": "65"})
    assert (
        r._auto_detect_battery_soc("sensor.test_battery_2_power")
        == "sensor.test_battery_2_soc"
    )


def test_huawei_two_part_prefix_still_works():
    """The 2-part fallback still finds Huawei's localized SOC sensor."""
    r = _reader_with_states({"sensor.battery_1_batterieladung": "95"})
    assert (
        r._auto_detect_battery_soc("sensor.battery_1_lade_entladeleistung")
        == "sensor.battery_1_batterieladung"
    )


def test_two_part_source_name_not_regressed():
    """A 2-token source (``goodwe_pbattery1``) still matches its
    ``_soc`` sibling — the loop must include the full-length stem."""
    r = _reader_with_states({"sensor.goodwe_pbattery1_soc": "40"})
    assert (
        r._auto_detect_battery_soc("sensor.goodwe_pbattery1")
        == "sensor.goodwe_pbattery1_soc"
    )


def test_longest_stem_wins_over_shorter():
    """When both an indexed and a 2-part SOC sensor exist, the indexed
    (more specific) one is chosen — longest stem is tried first."""
    r = _reader_with_states({
        "sensor.test_battery_2_soc": "65",
        "sensor.test_battery_soc": "10",  # wrong (shared/2-part) sibling
    })
    assert (
        r._auto_detect_battery_soc("sensor.test_battery_2_power")
        == "sensor.test_battery_2_soc"
    )


def test_no_soc_sensor_returns_none():
    """No matching SOC sensor and no device registry → None (card shows —)."""
    r = _reader_with_states({"sensor.unrelated": "5"})
    # Device-registry strategy 2 will raise/short-circuit on the Mock;
    # the contract is simply: no fabricated SOC.
    try:
        result = r._auto_detect_battery_soc("sensor.myinv_battery_3_power")
    except Exception:
        result = None
    assert result is None
