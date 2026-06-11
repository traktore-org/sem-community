import logging

from homeassistant.components.tibber import TibberDataUpdateCoordinator
from homeassistant.components.tibber.const import DOMAIN as TIBBER_DOMAIN
from homeassistant.components.tibber.grid_reward import TibberGridRewardDataUpdateCoordinator
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry):
    """Set up the Tibber sensor."""
    coordinator = hass.data[TIBBER_DOMAIN][entry.entry_id]
    if not isinstance(coordinator, TibberDataUpdateCoordinator):
        return

    # Check if the Tibber Pulse sensor exists
    pulse_sensor = next(
        (
            sensor
            for sensor in hass.states.async_all()
            if sensor.entity_id.startswith("sensor.") and sensor.attributes.get("platform") == "tibber"
        ),
        None,
    )

    # If the Tibber Pulse sensor exists but does not have today/today_raw attributes,
    # try to find the Tibber Grid Reward sensor
    if pulse_sensor and "today" not in pulse_sensor.attributes and "today_raw" not in pulse_sensor.attributes:
        grid_reward_coordinator = next(
            (
                coordinator
                for coordinator in hass.data[TIBBER_DOMAIN].values()
                if isinstance(coordinator, TibberGridRewardDataUpdateCoordinator)
            ),
            None,
        )

        if grid_reward_coordinator:
            # Use the Tibber Grid Reward sensor as the price source
            _LOGGER.info("Using Tibber Grid Reward sensor as price source")
            entry.data["price_source"] = grid_reward_coordinator
        else:
            _LOGGER.warning("No suitable Tibber sensor found for price data")
    else:
        # Use the Tibber Pulse sensor as the price source
        _LOGGER.info("Using Tibber Pulse sensor as price source")
        entry.data["price_source"] = coordinator