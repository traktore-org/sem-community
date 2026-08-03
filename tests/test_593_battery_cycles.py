"""#593 — battery cycles: prefer a hardware sensor (manual override or
autodetected on the battery device) over the throughput estimate."""

from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

_resolve = SEMCoordinator._resolve_battery_cycles


# ── the pure resolution: hardware wins, else estimate, else nothing ──
def test_hw_cycles_win_over_estimate():
    cycles, health = _resolve("249", throughput_cycles=165.0)
    assert cycles == 249.0
    # 249 * 0.02 = 4.98 % degradation → health 95.0
    assert health == 95.0


def test_estimate_used_when_no_hw():
    cycles, health = _resolve(None, throughput_cycles=165.0)
    assert cycles == 165.0


def test_unavailable_hw_falls_back_to_estimate():
    for bad in ("unavailable", "unknown"):
        cycles, _ = _resolve(bad, throughput_cycles=165.0)
        assert cycles == 165.0, bad


def test_garbage_hw_falls_back_to_estimate_not_dropped():
    cycles, _ = _resolve("not-a-number", throughput_cycles=165.0)
    assert cycles == 165.0


def test_nothing_available_returns_none():
    assert _resolve(None, throughput_cycles=None) == (None, None)
    assert _resolve("unavailable", throughput_cycles=None) == (None, None)


def test_hw_only_no_estimate():
    cycles, health = _resolve("500", throughput_cycles=None)
    assert cycles == 500.0
    assert health == 90.0  # 500 * 0.02 = 10 % → 90


def test_health_degradation_capped_at_30pct():
    # 2000 cycles * 0.02 = 40 %, capped at 30 → health 70
    _, health = _resolve("2000", throughput_cycles=None)
    assert health == 70.0


# ── the autodetect: find a cycle sensor on the battery device ──
def _reader_with_device(monkeypatch, anchor, device_entities, states):
    """A SensorReader whose entity-registry resolves `anchor` to a device that
    owns `device_entities`, with `states` mocked. Uses ``monkeypatch`` so the
    module-level ``er`` patches are RESTORED after the test (a raw assignment
    would pollute the shared entity_registry module for every later test)."""
    from custom_components.solar_energy_management.coordinator.sensor_reader import (
        SensorReader,
    )
    import custom_components.solar_energy_management.coordinator.sensor_reader as sr_mod

    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    reader = SensorReader(hass, {"update_interval": 10})

    anchor_entry = MagicMock(device_id="dev1")
    entries = [MagicMock(entity_id=e, domain="sensor") for e in device_entities]
    reg = MagicMock()
    reg.async_get = lambda eid: anchor_entry if eid == anchor else None
    monkeypatch.setattr(sr_mod.er, "async_get", lambda _h: reg)
    monkeypatch.setattr(sr_mod.er, "async_entries_for_device", lambda _r, _d: entries)
    return reader


def test_autodetect_finds_cycles_sensor_on_battery_device(monkeypatch):
    st = MagicMock()
    st.state = "249"
    reader = _reader_with_device(
        monkeypatch,
        anchor="sensor.sonnen_battery_power",
        device_entities=["sensor.sonnen_battery_power", "sensor.sonnen_battery_cycles"],
        states={"sensor.sonnen_battery_cycles": st},
    )
    assert reader.detect_battery_cycles_sensor("sensor.sonnen_battery_power") == \
        "sensor.sonnen_battery_cycles"


def test_autodetect_returns_none_when_no_cycle_sensor(monkeypatch):
    reader = _reader_with_device(
        monkeypatch,
        anchor="sensor.batt_power",
        device_entities=["sensor.batt_power", "sensor.batt_soc"],
        states={},
    )
    assert reader.detect_battery_cycles_sensor("sensor.batt_power") is None
