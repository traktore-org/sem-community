"""#788 — a service-registered device loses its device_type on the way to the card.

Split out of #685 ("Heat Pump configuration only supports one unit"), where it
was the reason the reporter's second heat pump "did not appear as expected".

More than one climate unit HAS been supported since the one-device-list work:
``register_surplus_device`` with ``device_type: climate`` persists the kind
(``async_register_service_device`` normalises it into ``stored["device_type"]``)
and ``surplus_device_from_spec`` rehydrates a real ``ClimateDevice``. The
device is registered, prioritised and controlled correctly.

What was wrong is the row the sensor publishes for the frontend. In
``get_devices_for_sensor`` the service-registration branch wrote a LITERAL:

    "device_type": "service_device",

throwing away the ``device_type`` the caller passed and the registry stored.
The card's icon map (``sem-load-priority-card._resolveDeviceIcon``) knows
``climate`` (mdi:thermostat) and ``heat_pump`` (mdi:heat-pump) but not
``service_device``, so every service-registered device fell through to the
generic ``mdi:power-plug`` — a heat pump that renders as a plug reads as "my
heat pump was not added".

The sibling branch for DIRECTLY registered surplus devices (``_surplus_device_row``)
reads the type properly off the live device. The two paths were written to
mirror each other and drifted — the same shape as BUG_CLASSES class 12.

Fix: read the stored type, keeping the old literal only as the fallback for
registrations persisted before the kind was stored at all.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


class _SurplusController:
    def __init__(self, devices=None):
        self._devices = dict(devices or {})

    def get_device(self, did):
        return self._devices.get(did)


def _stored(device_type, name="Wärmepumpe OG", entity="climate.wp_og"):
    """What ``async_register_service_device`` persists — the normalised spec,
    not the caller's raw kwargs."""
    return {
        "entity_id": entity,
        "name": name,
        "priority": 5,
        "rated_power": 2000,
        "power_entity_id": None,
        "energy_entity_id": None,
        "control_mode": "surplus",
        "depends_on": [],
        "device_type": device_type,
        "hvac_mode": "heat",
        "target_temperature": 21.0,
    }


def _reg(service_regs):
    r = UnifiedDeviceRegistry(
        MagicMock(), _SurplusController(), MagicMock(), MagicMock()
    )
    r._has_battery = False
    r._devices = []
    r._ev_charger_rows = []
    r._service_registrations = dict(service_regs)
    r.hass.states.get = MagicMock(return_value=None)
    return r


@pytest.mark.unit
class TestServiceDeviceTypeSurvives:
    def test_climate_registration_reports_climate_not_service_device(self):
        """The kind the caller passed is the kind the card is told about."""
        reg = _reg({"wp_og": _stored("climate")})

        row = reg.get_devices_for_sensor()["wp_og"]

        assert row["device_type"] == "climate"

    def test_every_registered_kind_round_trips(self):
        """Not just climate — the literal discarded EVERY kind, so a switch
        stayed a switch and a setpoint stayed a setpoint too."""
        reg = _reg({
            "wp_og": _stored("climate", "Wärmepumpe OG", "climate.wp_og"),
            "boiler": _stored("setpoint", "Boiler", "water_heater.boiler"),
            "pool": _stored("switch", "Poolpumpe", "switch.pool"),
        })

        rows = reg.get_devices_for_sensor()

        assert rows["wp_og"]["device_type"] == "climate"
        assert rows["boiler"]["device_type"] == "setpoint"
        assert rows["pool"]["device_type"] == "switch"

    def test_two_climate_units_keep_their_own_identity(self):
        """#685's actual ask: N heat pumps, each recognisable as one. Before
        the fix both rendered as the same generic plug, which is what made a
        working multi-unit setup look like it had not been added."""
        reg = _reg({
            "wp_og": _stored("climate", "Wärmepumpe OG", "climate.wp_og"),
            "wp_ug": _stored("climate", "Wärmepumpe UG", "climate.wp_ug"),
        })

        rows = reg.get_devices_for_sensor()

        assert [rows["wp_og"]["device_type"], rows["wp_ug"]["device_type"]] == [
            "climate", "climate",
        ]
        assert rows["wp_og"]["name"] != rows["wp_ug"]["name"]

    def test_registration_without_a_stored_kind_keeps_the_old_label(self):
        """Backward compatibility: a registration persisted before the kind
        was stored has no ``device_type`` key. It must not become ``None`` —
        the card would then miss even the generic-plug fallback path."""
        legacy = _stored("climate")
        legacy.pop("device_type")
        reg = _reg({"old": legacy})

        assert reg.get_devices_for_sensor()["old"]["device_type"] == "service_device"

    def test_the_row_still_carries_everything_it_carried_before(self):
        """A regression fence around the one-line change: nothing else in the
        payload may move while fixing the type."""
        reg = _reg({"wp_og": _stored("climate")})

        row = reg.get_devices_for_sensor()["wp_og"]

        assert row["name"] == "Wärmepumpe OG"
        assert row["priority"] == 5
        assert row["is_controllable"] is True
        assert row["switch_entity"] == "climate.wp_og"
        assert row["control_mode"] == "surplus"
        assert row["is_available"] is True
