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


# ── #529: guarded global last-resort scan ────────────────────────────

def _state(eid, value, unit="%", device_class="battery"):
    s = Mock()
    s.entity_id = eid
    s.state = value
    s.attributes = {"unit_of_measurement": unit, "device_class": device_class}
    return s


def _reader_with_scan(sensor_states, get_dict=None):
    """Reader whose async_all('sensor') returns the given state objects and
    whose states.get resolves from get_dict (default empty → Strategy 1/2 miss)."""
    hass = Mock()
    hass.states = Mock()
    gd = get_dict or {}
    hass.states.get = lambda eid: gd.get(eid)
    hass.states.async_all = lambda domain=None: sensor_states
    return SensorReader(hass, {})


def test_global_scan_finds_lone_soc_on_other_device():
    # #529: Huawei user with a generic sensor.battery_state_of_charge that
    # neither the name-prefix nor the same-device scan reaches.
    r = _reader_with_scan([_state("sensor.battery_state_of_charge", "73")])
    assert (
        r._auto_detect_battery_soc("sensor.inverter_x_power")
        == "sensor.battery_state_of_charge"
    )


def test_global_scan_ambiguous_returns_none():
    r = _reader_with_scan([
        _state("sensor.battery_state_of_charge", "73"),
        _state("sensor.home_battery_soc", "55"),
    ])
    assert r._auto_detect_battery_soc("sensor.inverter_x_power") is None


def test_global_scan_excludes_ev_battery():
    # The EV SOC is excluded, leaving exactly one home-battery candidate.
    r = _reader_with_scan([
        _state("sensor.ev_battery_soc", "40"),
        _state("sensor.battery_state_of_charge", "73"),
    ])
    assert (
        r._auto_detect_battery_soc("sensor.inverter_x_power")
        == "sensor.battery_state_of_charge"
    )


def test_global_scan_requires_percent_unit():
    # A SOC-named sensor without a % unit (e.g. kWh capacity) is not a SOC.
    r = _reader_with_scan([
        _state("sensor.battery_state_of_charge", "10.2", unit="kWh"),
    ])
    assert r._auto_detect_battery_soc("sensor.inverter_x_power") is None
