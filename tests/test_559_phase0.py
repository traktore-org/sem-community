"""#559 Phase 0 — foundation hardening for generic surplus loads.

- Service registrations persist across restarts (pre-fix: memory-only,
  silently gone after every restart).
- One-call registration defaulting to control_mode=surplus
  (auto-discovered devices keep peak_only).
- Explicit registration owns its switch: ED auto-discovery duplicates
  are dropped/skipped (two device objects driving one switch fight).
- Debounced surplus-availability signal (binary sensor + bus event on
  transitions only) for user automations of self-managed devices.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode
from custom_components.solar_energy_management.coordinator.surplus_availability import (
    SurplusAvailability,
    SUSTAIN_ON_SECONDS,
    SUSTAIN_OFF_SECONDS,
    HYSTERESIS_FACTOR,
)


# ---------------------------------------------------------------------------
# Registration persistence + dedupe
# ---------------------------------------------------------------------------

class _FakeSurplusController:
    def __init__(self):
        self._devices = {}

    def register_device(self, device):
        self._devices[device.device_id] = device

    def unregister_device(self, device_id):
        self._devices.pop(device_id, None)

    def get_device(self, device_id):
        return self._devices.get(device_id)


@pytest.fixture
def registry():
    controller = _FakeSurplusController()
    reg = UnifiedDeviceRegistry(
        MagicMock(), controller, MagicMock(), MagicMock()
    )
    reg._store = AsyncMock()
    reg.async_refresh_devices = AsyncMock()
    return reg


SPEC = {
    "device_id": "kia_socket",
    "entity_id": "switch.kia_socket",
    "name": "Kia Socket",
    "priority": 5,
    "rated_power": 2300,
    "power_entity_id": None,
    "control_mode": "surplus",
}


# ---------------------------------------------------------------------------
# #559 — explicit rated_power must show on the Control card, not the live 0 W
# ---------------------------------------------------------------------------

def _ud(energy, switch, power=None, name="Dev", prio=1):
    from custom_components.solar_energy_management.features.device_registry import (
        UnifiedDevice,
    )
    return UnifiedDevice(
        energy_sensor=energy, power_sensor=power, name=name, priority=prio,
        control={"type": "switch", "entity": switch},
    )


def test_explicit_rated_power_wins_over_autodiscovered(registry):
    """A register_surplus_device rated_power must show on the card even when an
    auto-discovered ED device covers the SAME switch (reporter: power_rating
    stuck at 0 W because the live-sensor autodiscovered row shadowed it)."""
    from custom_components.solar_energy_management.devices.base import SwitchDevice
    ud = _ud("sensor.piscina_energy_2", "switch.piscina_2",
             power="sensor.piscina_power", name="Pool")
    registry._devices = [ud]
    # power sensor reads 0 (pump off)
    registry.hass.states.get = lambda e: SimpleNamespace(state="0")
    # explicit registration for the same switch, rated_power 710
    registry._service_registrations = {ud.device_id: {
        "entity_id": "switch.piscina_2", "name": "Pool", "priority": 1,
        "rated_power": 710, "control_mode": "surplus"}}
    registry._surplus_controller._devices[ud.device_id] = SwitchDevice(
        hass=registry.hass, device_id=ud.device_id, name="Pool",
        rated_power=710, entity_id="switch.piscina_2")
    result = registry.get_devices_for_sensor()
    # exactly one row for the switch (no shadow duplicate), showing 710 W
    assert len(result) == 1
    assert result[ud.device_id]["power_rating"] == 710


def test_autodiscovered_shows_calibrated_rating_not_live_zero(registry):
    """An OFF auto-discovered device shows its device rated_power (self-
    calibrated), not the raw 0 W live reading."""
    from custom_components.solar_energy_management.devices.base import SwitchDevice
    ud = _ud("sensor.heater_energy", "switch.heater", power="sensor.heater_power")
    registry._devices = [ud]
    registry.hass.states.get = lambda e: SimpleNamespace(state="0")  # off
    registry._service_registrations = {}
    registry._surplus_controller._devices[ud.device_id] = SwitchDevice(
        hass=registry.hass, device_id=ud.device_id, name="Heater",
        rated_power=1800, entity_id="switch.heater")
    result = registry.get_devices_for_sensor()
    assert result[ud.device_id]["power_rating"] == 1800


def test_autodiscovered_falls_back_to_live_when_no_rating(registry):
    """No live device / zero rating → fall back to the live sensor reading."""
    ud = _ud("sensor.x_energy", "switch.x", power="sensor.x_power")
    registry._devices = [ud]
    registry.hass.states.get = lambda e: SimpleNamespace(state="42")
    registry._service_registrations = {}
    result = registry.get_devices_for_sensor()
    assert result[ud.device_id]["power_rating"] == 42.0


@pytest.mark.asyncio
async def test_register_persists_and_registers(registry):
    summary = await registry.async_register_service_device(dict(SPEC))

    assert registry._service_registrations["kia_socket"]["entity_id"] == "switch.kia_socket"
    device = registry._surplus_controller.get_device("kia_socket")
    assert device is not None
    assert device.control_mode == DeviceControlMode.SURPLUS
    assert device.rated_power == 2300
    registry._store.async_save.assert_awaited()
    assert summary["device_id"] == "kia_socket"
    assert summary["control_mode"] == "surplus"
    assert summary["total_devices"] == 1


@pytest.mark.asyncio
async def test_register_defaults_to_surplus(registry):
    spec = dict(SPEC)
    del spec["control_mode"]
    await registry.async_register_service_device(spec)
    device = registry._surplus_controller.get_device("kia_socket")
    assert device.control_mode == DeviceControlMode.SURPLUS


CLIMATE_SPEC = {
    "device_id": "living_ac",
    "entity_id": "climate.living_room_ac",
    "name": "Living Room AC",
    "priority": 6,
    "rated_power": 1800,
    "power_entity_id": None,
    "control_mode": "surplus",
    "device_type": "climate",
    "hvac_mode": "cool",
    "target_temperature": 22.0,
}


@pytest.mark.asyncio
async def test_register_climate_builds_climate_device(registry):
    """(#569) A climate spec builds a ClimateDevice, not a SwitchDevice."""
    from custom_components.solar_energy_management.devices.base import ClimateDevice
    summary = await registry.async_register_service_device(dict(CLIMATE_SPEC))
    device = registry._surplus_controller.get_device("living_ac")
    assert isinstance(device, ClimateDevice)
    assert device.hvac_mode == "cool"
    assert device.target_temperature == 22.0
    assert device.control_mode == DeviceControlMode.SURPLUS
    assert summary["device_type"] == "climate"
    # device_type persists so it rehydrates correctly after a restart
    assert registry._service_registrations["living_ac"]["device_type"] == "climate"


@pytest.mark.asyncio
async def test_climate_rehydrates_as_climate_device_after_restart(registry):
    """(#569) After a restart, the persisted climate spec re-owns as a
    ClimateDevice (not a SwitchDevice)."""
    from custom_components.solar_energy_management.devices.base import ClimateDevice
    await registry.async_register_service_device(dict(CLIMATE_SPEC))
    # Simulate restart: wipe live devices, keep persisted registrations.
    registry._surplus_controller._devices.clear()
    registry._register_service_devices()
    device = registry._surplus_controller.get_device("living_ac")
    assert isinstance(device, ClimateDevice)
    assert device.hvac_mode == "cool"
    assert device.target_temperature == 22.0


@pytest.mark.asyncio
async def test_register_respects_explicit_peak_only(registry):
    await registry.async_register_service_device({**SPEC, "control_mode": "peak_only"})
    device = registry._surplus_controller.get_device("kia_socket")
    assert device.control_mode == DeviceControlMode.PEAK_ONLY


def test_boot_reregisters_persisted_devices(registry):
    registry._service_registrations = {"kia_socket": {k: v for k, v in SPEC.items() if k != "device_id"}}
    registry._register_service_devices()
    device = registry._surplus_controller.get_device("kia_socket")
    assert device is not None
    assert device.name == "Kia Socket"
    assert device.control_mode == DeviceControlMode.SURPLUS


@pytest.mark.asyncio
async def test_unregister_removes_device_and_persistence(registry):
    await registry.async_register_service_device(dict(SPEC))
    removed = await registry.async_unregister_service_device("kia_socket")
    assert removed is True
    assert "kia_socket" not in registry._service_registrations
    assert registry._surplus_controller.get_device("kia_socket") is None


@pytest.mark.asyncio
async def test_unregister_unknown_returns_false(registry):
    assert await registry.async_unregister_service_device("nope") is False


@pytest.mark.asyncio
async def test_register_drops_discovered_duplicate(registry):
    # ED auto-discovery already controls the same switch
    dup = MagicMock()
    dup.entity_id = "switch.kia_socket"
    registry._surplus_controller._devices["energy_dashboard_kia"] = dup

    await registry.async_register_service_device(dict(SPEC))
    assert registry._surplus_controller.get_device("energy_dashboard_kia") is None
    assert registry._surplus_controller.get_device("kia_socket") is not None


@pytest.mark.asyncio
async def test_control_mode_update_persists_to_spec(registry):
    await registry.async_register_service_device(dict(SPEC))
    await registry.update_device_control_mode("kia_socket", "peak_only")
    assert registry._service_registrations["kia_socket"]["control_mode"] == "peak_only"
    device = registry._surplus_controller.get_device("kia_socket")
    assert device.control_mode == DeviceControlMode.PEAK_ONLY


# ---------------------------------------------------------------------------
# Surplus availability debounce
# ---------------------------------------------------------------------------

TH = 2000.0


class TestSurplusAvailability:

    def test_requires_sustain_before_on(self):
        sa = SurplusAvailability()
        assert sa.update(3000, TH, 0.0) is None
        assert sa.available is False
        # still below sustain
        assert sa.update(3000, TH, SUSTAIN_ON_SECONDS - 1) is None
        t = sa.update(3000, TH, SUSTAIN_ON_SECONDS)
        assert t is not None and t.available is True
        assert sa.available is True

    def test_dip_resets_on_sustain(self):
        sa = SurplusAvailability()
        sa.update(3000, TH, 0.0)
        sa.update(500, TH, 30.0)   # dip below threshold — restart clock
        assert sa.update(3000, TH, SUSTAIN_ON_SECONDS + 10) is None
        t = sa.update(3000, TH, SUSTAIN_ON_SECONDS + 10 + SUSTAIN_ON_SECONDS)
        assert t is not None and t.available is True

    def test_hysteresis_holds_in_band(self):
        sa = SurplusAvailability()
        sa.update(3000, TH, 0.0)
        sa.update(3000, TH, SUSTAIN_ON_SECONDS)
        assert sa.available is True
        # In the hysteresis band (>= 80% of threshold): stays ON forever
        band_value = TH * HYSTERESIS_FACTOR + 1
        assert sa.update(band_value, TH, 1000.0) is None
        assert sa.update(band_value, TH, 5000.0) is None
        assert sa.available is True

    def test_off_requires_sustain_below_floor(self):
        sa = SurplusAvailability()
        sa.update(3000, TH, 0.0)
        sa.update(3000, TH, SUSTAIN_ON_SECONDS)
        base = 1000.0
        assert sa.update(100, TH, base) is None
        assert sa.update(100, TH, base + SUSTAIN_OFF_SECONDS - 1) is None
        t = sa.update(100, TH, base + SUSTAIN_OFF_SECONDS)
        assert t is not None and t.available is False
        assert sa.available is False

    def test_flapping_produces_no_transitions(self):
        # Rapid cloud flapping around the threshold: no event storm
        sa = SurplusAvailability()
        sa.update(3000, TH, 0.0)
        sa.update(3000, TH, SUSTAIN_ON_SECONDS)  # ON
        transitions = []
        t_now = 1000.0
        for i in range(50):
            v = 100 if i % 2 == 0 else 3000
            t_now += 10  # 10s cycles, always recovering before 120s
            tr = sa.update(v, TH, t_now)
            if tr:
                transitions.append(tr)
        assert transitions == []
        assert sa.available is True

    def test_zero_threshold_falls_back_to_default(self):
        sa = SurplusAvailability()
        sa.update(1600, 0, 0.0)
        t = sa.update(1600, 0, SUSTAIN_ON_SECONDS)
        assert t is not None and t.available is True  # default 1500W


@pytest.mark.asyncio
async def test_register_with_depends_on(registry):
    # docs always showed depends_on on register — now the service accepts it
    await registry.async_register_service_device({**SPEC, "depends_on": ["pool_pump"]})
    device = registry._surplus_controller.get_device("kia_socket")
    assert device.depends_on == ["pool_pump"]
    assert registry._service_registrations["kia_socket"]["depends_on"] == ["pool_pump"]
    # …and it survives the boot re-register
    registry._surplus_controller._devices.clear()
    registry._register_service_devices()
    device = registry._surplus_controller.get_device("kia_socket")
    assert device.depends_on == ["pool_pump"]
