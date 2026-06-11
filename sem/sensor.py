from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import Entity

class SEMSensor(SensorEntity):
    """Base class for SEM sensors."""

    def __init__(self, coordinator, name, icon):
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._name = name
        self._icon = icon

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return self._icon

    @property
    def should_poll(self):
        """Return True if the sensor should poll."""
        return False

    @property
    def available(self):
        """Return True if the sensor is available."""
        return self.coordinator.last_update_success

    async def async_update(self):
        """Update the sensor."""
        await self.coordinator.async_request_refresh()

class PriceSensor(SEMSensor):
    """Sensor for the current price."""

    def __init__(self, coordinator, name, icon):
        """Initialize the sensor."""
        super().__init__(coordinator, name, icon)

    @property
    def state(self):
        """Return the state of the sensor."""
        if self.coordinator.data.get("price_source"):
            return self.coordinator.data["price_source"].data.get("current_price")
        return None

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return "€/kWh"

    @property
    def device_class(self):
        """Return the device class."""
        return "monetary"