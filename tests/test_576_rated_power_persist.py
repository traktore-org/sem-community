"""#576 — persist + history-seed a sensor-equipped load's rated power.

A Shelly load self-calibrates its real draw at runtime (calibrate_rated_power),
but that value used to reset to the 1 kW default floor on every restart / device
rebuild, so the Control card showed a 1 kW placeholder until the load ran again.
These tests lock the two fixes:
  1. PERSIST the learned rating (survives restart + the 35 s rebuild), and
  2. SEED it once from the power sensor's recorder-history running max, so a
     fresh sensor-equipped device shows its real rating immediately.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry, _DEFAULT_RATED_POWER,
)


def _dev(rated=1000.0, sensor="sensor.p", is_ev=False, mpt=0.0, measured=True):
    # (#744) ``measured`` is the provenance of ``rated``: False = the 1 kW
    # placeholder SwitchDevice invents when it has nothing to go on.
    return SimpleNamespace(
        rated_power=rated, power_entity_id=sensor, is_ev=is_ev,
        min_power_threshold=mpt, rated_power_measured=measured,
    )


def _reg(devices=None):
    devices = devices or {}
    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    reg._rated_power_overrides = {}
    reg._rating_seed_attempted = set()
    reg._surplus_controller = MagicMock()
    reg._surplus_controller._devices = devices
    reg.hass = MagicMock()
    reg.hass.states.get = MagicMock(return_value=None)   # sensor unavailable → 0 W
    reg._save_storage = AsyncMock()
    return reg


@pytest.mark.unit
class TestInitialRatedPower:
    def test_persisted_override_wins(self):
        reg = _reg()
        reg._rated_power_overrides["d"] = 1140.0
        assert reg._initial_rated_power("d", "sensor.p") == 1140.0

    def test_no_override_falls_to_sensor(self):
        reg = _reg()
        # sensor unavailable → 0.0 (SwitchDevice.__init__ then applies the 1 kW default)
        assert reg._initial_rated_power("d", "sensor.p") == 0.0


@pytest.mark.unit
class TestCaptureCalibratedRatings:
    def test_captures_above_floor_calibration(self):
        devs = {"d": _dev(rated=1140.0)}
        reg = _reg(devs)
        assert reg._capture_calibrated_ratings() is True
        assert reg._rated_power_overrides["d"] == 1140.0

    def test_ignores_the_default_floor(self):
        # (#744) ignored because it is the INVENTED placeholder, not because
        # 1000 is a magic number — a measured 1 kW load would be kept.
        reg = _reg({"d": _dev(rated=_DEFAULT_RATED_POWER, measured=False)})
        assert reg._capture_calibrated_ratings() is False
        assert "d" not in reg._rated_power_overrides

    def test_ignores_the_ev(self):
        reg = _reg({"ev": _dev(rated=7000.0, is_ev=True)})
        assert reg._capture_calibrated_ratings() is False

    def test_ignores_sensorless_device(self):
        reg = _reg({"d": _dev(rated=1500.0, sensor=None)})
        assert reg._capture_calibrated_ratings() is False

    def test_only_captures_increases(self):
        reg = _reg({"d": _dev(rated=1100.0)})
        reg._rated_power_overrides["d"] = 1200.0   # already learned higher
        assert reg._capture_calibrated_ratings() is False
        assert reg._rated_power_overrides["d"] == 1200.0

    def test_ignores_device_without_rated_power(self):
        # e.g. the modulating EV path — rated_power is None
        reg = _reg({"d": _dev(rated=None)})
        assert reg._capture_calibrated_ratings() is False


@pytest.mark.unit
class TestSeedAndApplyRatings:
    async def test_applies_override_to_rebuilt_device_at_floor(self):
        devs = {"d": _dev(rated=1000.0, mpt=1000.0)}   # rebuilt back at the floor
        reg = _reg(devs)
        reg._rated_power_overrides["d"] = 1140.0
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power == 1140.0
        assert devs["d"].min_power_threshold == 1140.0   # gate follows the rating

    async def test_seeds_from_history_when_unlearned(self):
        devs = {"d": _dev(rated=1000.0)}
        reg = _reg(devs)
        reg._history_max_power = AsyncMock(return_value=1144.0)
        changed = await reg._seed_and_apply_ratings()
        assert changed is True
        assert reg._rated_power_overrides["d"] == 1144.0
        assert devs["d"].rated_power == 1144.0

    async def test_history_does_not_lower_a_rating_we_were_given(self):
        # (#744) 600 W of history is a measurement, but this device's 1 kW is
        # one too (measured=True) — history only ever raises a known rating.
        # The placeholder case is the opposite, and lives in
        # test_744_measured_rating::test_history_seeds_a_small_load.
        devs = {"d": _dev(rated=1000.0)}
        reg = _reg(devs)
        reg._history_max_power = AsyncMock(return_value=600.0)
        changed = await reg._seed_and_apply_ratings()
        assert changed is False
        assert "d" not in reg._rated_power_overrides
        assert devs["d"].rated_power == 1000.0

    async def test_history_seed_attempted_only_once_per_session(self):
        devs = {"d": _dev(rated=1000.0)}
        reg = _reg(devs)
        reg._history_max_power = AsyncMock(return_value=0.0)   # no history yet
        await reg._seed_and_apply_ratings()
        await reg._seed_and_apply_ratings()
        assert reg._history_max_power.await_count == 1   # not re-queried every refresh

    async def test_does_not_lower_a_higher_live_rating(self):
        devs = {"d": _dev(rated=1500.0)}   # live already above the override
        reg = _reg(devs)
        reg._rated_power_overrides["d"] = 1140.0
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power == 1500.0   # never clamped down


@pytest.mark.unit
class TestPersistence:
    async def test_save_includes_rated_power_overrides(self):
        reg = _reg()
        reg._rated_power_overrides = {"d": 1140.0}
        reg._store = MagicMock()
        reg._store.async_save = AsyncMock()
        # exercise the real _save_storage (the _reg fixture mocks it)
        await UnifiedDeviceRegistry._save_storage(reg)
        saved = reg._store.async_save.call_args.args[0]
        assert saved["rated_power_overrides"] == {"d": 1140.0}

    async def test_load_populates_overrides(self):
        reg = _reg()
        reg._store = MagicMock()
        reg._store.async_load = AsyncMock(return_value={
            "rated_power_overrides": {"d": 1140.0}})
        reg.async_refresh_devices = AsyncMock()
        reg._register_service_devices = MagicMock()
        reg.hass = MagicMock()
        await reg.async_initialize()
        assert reg._rated_power_overrides == {"d": 1140.0}

    async def test_load_missing_key_defaults_empty(self):
        # a store from before this feature has no rated_power_overrides key
        reg = _reg()
        reg._store = MagicMock()
        reg._store.async_load = AsyncMock(return_value={"priority_overrides": {}})
        reg.async_refresh_devices = AsyncMock()
        reg._register_service_devices = MagicMock()
        reg.hass = MagicMock()
        await reg.async_initialize()
        assert reg._rated_power_overrides == {}
