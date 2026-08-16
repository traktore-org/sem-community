"""#744 — a load's rated power must be a measurement, not a guess that sticks.

Azlinon runs 47 loads, many of them small: a shower light on a Shelly PM
drawing 6.4–8 W, dimmers, a furnace blower. His report: *"the Device
priority view doesn't report anything below 1 kW, and some of the items
occasionally show up classified as ~1 kW even though peak draw is much,
much less"*.

The mechanism is one missing distinction. ``SwitchDevice.__init__`` invents
``DEFAULT_DEVICE_RATED_POWER`` (1 kW) whenever the passed rating is 0 — and
a sensor-equipped load reads 0 W for the entire time it is *off*, which is
most of the time. From there nothing can bring it down:

  * ``calibrate_rated_power`` is an up-only ratchet, so 8 W < 1 kW is ignored;
  * ``_capture_calibrated_ratings`` persists only ``rated > 1 kW``;
  * ``_seed_and_apply_ratings`` seeds history only when ``hist_max > 1 kW``
    and otherwise only ever raises the live device.

Every one of those guards is defensible against a *measurement*. They are
all wrong against an *invention* — and the code cannot tell the two apart.
So every load under 1 kW is pinned at exactly 1 kW forever: the card prints
"~1.0 kW" when it is off, its surplus-activation threshold demands a
kilowatt before an 8 W bulb is ever offered, and the planner sizes 47 loads
at 47 kW of phantom demand.

The fix is the distinction itself — ``rated_power_measured``. The 1 kW
placeholder stays (a sensor-less switch still needs a saner floor than 0 W,
#576), but it is now labelled as the guess it is: the first real reading
*replaces* it in either direction, and only after that does the up-only
ratchet apply. Estimates still never teach the model (#744's earlier half,
``test_744_rated_ratchet``) — this is about measurements being allowed to.
"""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.devices.base import (
    DeviceState, SwitchDevice, surplus_device_from_spec,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry, _DEFAULT_RATED_POWER,
)

requires_hass = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)


def _switch(rated=0.0, power_entity="sensor.shower_light_power"):
    """A discovered Shelly-PM load: the registry passes the live sensor
    reading as the rating, which is 0 W while the light is off."""
    return SwitchDevice(
        MagicMock(), "shower_light", "Shower Light", rated_power=rated,
        entity_id="switch.shower_light", power_entity_id=power_entity,
    )


def _running(dev, watts):
    """Put the device ON and have its power sensor report ``watts``."""
    dev._status.state = DeviceState.ACTIVE
    dev.observed_power_w = lambda: watts
    return dev


def _live(rated=8.0, measured=True, sensor="sensor.p", is_ev=False, mpt=0.0):
    return SimpleNamespace(
        rated_power=rated, rated_power_measured=measured,
        power_entity_id=sensor, is_ev=is_ev, min_power_threshold=mpt,
    )


def _reg(devices=None):
    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    reg._rated_power_overrides = {}
    reg._rating_seed_attempted = set()
    reg._surplus_controller = MagicMock()
    reg._surplus_controller._devices = devices or {}
    reg.hass = MagicMock()
    reg.hass.states.get = MagicMock(return_value=None)
    reg._save_storage = AsyncMock()
    return reg


@pytest.mark.unit
class TestTheGuessIsLabelledAsOne:
    def test_a_load_that_is_off_starts_unmeasured(self):
        # 0 W passed in = "the sensor reads 0 because the light is off",
        # NOT "this load draws nothing".
        dev = _switch(rated=0.0)
        assert dev.rated_power == _DEFAULT_RATED_POWER
        assert dev.rated_power_measured is False

    def test_a_rating_we_were_given_counts_as_known(self):
        dev = _switch(rated=1500.0)
        assert dev.rated_power == 1500.0
        assert dev.rated_power_measured is True

    def test_a_spec_without_a_rating_is_a_guess_too(self):
        # The service/spec build site invented its own 1 kW, spelled
        # differently — same lie, so it must carry the same label.
        dev = surplus_device_from_spec(MagicMock(), "d", {
            "entity_id": "switch.d", "power_entity_id": "sensor.d_power",
        })
        assert dev.rated_power == _DEFAULT_RATED_POWER
        assert dev.rated_power_measured is False

    def test_a_spec_rating_is_kept_and_trusted(self):
        dev = surplus_device_from_spec(MagicMock(), "d", {
            "entity_id": "switch.d", "rated_power": 2200,
        })
        assert dev.rated_power == 2200
        assert dev.rated_power_measured is True


@pytest.mark.unit
class TestTheFirstMeasurementReplacesTheGuess:
    def test_an_eight_watt_bulb_learns_eight_watts(self):
        dev = _running(_switch(), 8.0)
        dev.calibrate_rated_power()
        assert dev.rated_power == 8.0
        # the activation gate follows — no more "a kilowatt of surplus
        # before we will switch on a shower light".
        assert dev.min_power_threshold == 8.0
        assert dev.rated_power_measured is True

    def test_after_the_first_measurement_only_the_peak_counts(self):
        dev = _running(_switch(), 8.0)
        dev.calibrate_rated_power()
        dev.observed_power_w = lambda: 5.0      # a dimmed reading
        dev.calibrate_rated_power()
        assert dev.rated_power == 8.0           # never ratchets back down
        dev.observed_power_w = lambda: 40.0     # full brightness
        dev.calibrate_rated_power()
        assert dev.rated_power == 40.0

    def test_a_load_we_were_told_about_is_not_overwritten_downward(self):
        dev = _running(_switch(rated=2200.0), 300.0)   # compressor spinning up
        dev.calibrate_rated_power()
        assert dev.rated_power == 2200.0

    def test_a_sensorless_load_keeps_the_placeholder(self):
        # No power sensor → the energy deriver's estimate must not teach the
        # model (#744, test_744_rated_ratchet). The guess stays a guess.
        dev = _running(_switch(power_entity=None), 8.0)
        dev.calibrate_rated_power()
        assert dev.rated_power == _DEFAULT_RATED_POWER
        assert dev.rated_power_measured is False


@pytest.mark.unit
class TestASmallRatingSurvivesTheRebuild:
    def test_a_measured_sub_kilowatt_rating_is_persisted(self):
        reg = _reg({"d": _live(rated=8.0, measured=True)})
        assert reg._capture_calibrated_ratings() is True
        assert reg._rated_power_overrides["d"] == 8.0

    def test_the_placeholder_is_never_persisted(self):
        reg = _reg({"d": _live(rated=_DEFAULT_RATED_POWER, measured=False)})
        assert reg._capture_calibrated_ratings() is False
        assert "d" not in reg._rated_power_overrides

    async def test_history_seeds_a_small_load(self):
        devs = {"d": _live(rated=_DEFAULT_RATED_POWER, measured=False,
                           mpt=_DEFAULT_RATED_POWER)}
        reg = _reg(devs)
        reg._history_max_power = AsyncMock(return_value=8.0)
        assert await reg._seed_and_apply_ratings() is True
        assert reg._rated_power_overrides["d"] == 8.0
        assert devs["d"].rated_power == 8.0
        assert devs["d"].min_power_threshold == 8.0
        assert devs["d"].rated_power_measured is True

    async def test_a_learned_small_rating_is_reapplied_after_a_rebuild(self):
        # The rebuild handed the device the 1 kW guess again; the persisted
        # 8 W must win even though it is *lower*.
        devs = {"d": _live(rated=_DEFAULT_RATED_POWER, measured=False,
                           mpt=_DEFAULT_RATED_POWER)}
        reg = _reg(devs)
        reg._rated_power_overrides["d"] = 8.0
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power == 8.0
        assert devs["d"].rated_power_measured is True

    async def test_a_measured_live_rating_is_never_lowered_by_the_store(self):
        devs = {"d": _live(rated=1500.0, measured=True)}
        reg = _reg(devs)
        reg._rated_power_overrides["d"] = 1140.0
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power == 1500.0


@pytest.mark.unit
class TestTheServicePathTellsTheTruthToo:
    """The same fabrication, twice more, on the service-registration path —
    fixed in the same pass rather than one report at a time."""

    async def test_registering_without_a_rating_stores_no_rating(self):
        # Baking 1000 into the STORE is the worst spelling of the guess: it
        # outlives the process that made it up and comes back as fact.
        reg = _reg()
        reg._save_storage = AsyncMock()
        reg._dependency_would_cycle = MagicMock(return_value=False)
        reg._apply_goals = MagicMock()
        reg._surplus_controller.register_device = MagicMock()
        await reg.async_register_service_device({
            "device_id": "pump", "entity_id": "switch.pump",
            "power_entity_id": "sensor.pump_power",
        })
        assert not reg._service_registrations["pump"]["rated_power"]

    def test_the_card_reads_the_live_rating_not_the_stored_guess(self):
        # The ED rows already ask ``_rated_power_for``; the service rows read
        # the spec, so a service-registered 8 W load stayed "~1.0 kW" on the
        # card forever — even after it had measured itself.
        reg = _reg()
        reg._devices = []
        reg._ev_charger_rows = []
        reg._service_registrations = {"pump": {
            "name": "Pump", "entity_id": "switch.pump",
            "power_entity_id": "sensor.pump_power",
        }}
        reg._configured_charger_entities = MagicMock(return_value=set())
        reg._direct_registration_entities = MagicMock(return_value=set())
        reg._goal_payload = MagicMock(return_value={})
        live = SimpleNamespace(
            rated_power=8.0, rated_power_measured=True, is_active=False,
            get_current_consumption=lambda: 0.0,
        )
        reg._surplus_controller._devices = {}
        reg._surplus_controller.get_device = MagicMock(return_value=live)
        rows = reg.get_devices_for_sensor()
        assert rows["pump"]["power_rating"] == 8.0


@requires_hass
@pytest.mark.asyncio
async def test_the_service_schema_does_not_manufacture_a_rating(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """The store now refuses to invent a rating — but only if it ever gets
    to SEE an omission. ``vol.Optional(..., default=1000)`` means validation
    fills the key before the handler runs, so *every* call arrives carrying
    a rating and the absence is unrepresentable. The guess simply moved one
    layer out, where it looks like the user's own number.

    This drives the real service, so it fails while the schema still has a
    default no matter what the handler and the store do downstream."""
    sem_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][sem_config_entry.entry_id]
    registry = coordinator._device_registry
    assert registry is not None, "device registry not wired by setup"

    await hass.services.async_call(
        DOMAIN, "register_surplus_device",
        {
            "device_id": "shower_light",
            "entity_id": "switch.shower_light",
            "power_entity_id": "sensor.shower_light_power",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    stored = registry._service_registrations["shower_light"]
    assert not stored["rated_power"], (
        f"the service invented {stored['rated_power']}W for a caller who "
        f"never named one — an 8W bulb registered this way is pinned at "
        f"1 kW from its first second on disk"
    )
