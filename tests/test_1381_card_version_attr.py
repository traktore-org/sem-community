"""(#1381) The server tells the cards which bundle it registered.

25.11 on PROD: the phone app kept the previous card after an update. It knew
only the old charge-mode names, drew one "Off" button, and a tap on it stopped
a night charge. The cards now compare their own ``?v=`` token with the one the
server registered, published on ``sensor.sem_diag_version`` as ``card``.
"""
from unittest.mock import MagicMock

from custom_components.solar_energy_management.const import DOMAIN


def test_the_version_sensor_carries_the_registered_bundle_token():
    from custom_components.solar_energy_management.sensor import SEMSolarSensor
    me = MagicMock()
    me.entity_description.key = "diag_version"
    me.coordinator.data = {"diag_version": "2.3.0-beta.27"}
    me.hass.data = {f"{DOMAIN}_card_version": "2.3.0-beta.27-0683a281"}
    attrs = SEMSolarSensor._extra_state_attributes_base(me)
    assert attrs["card"] == "2.3.0-beta.27-0683a281"


def test_no_token_registered_yet_publishes_none():
    from custom_components.solar_energy_management.sensor import SEMSolarSensor
    me = MagicMock()
    me.entity_description.key = "diag_version"
    me.coordinator.data = {"diag_version": "2.3.0-beta.27"}
    me.hass.data = {}
    attrs = SEMSolarSensor._extra_state_attributes_base(me)
    assert attrs.get("card") is None


def test_the_registration_stores_the_token_it_put_on_the_url():
    import inspect
    from custom_components.solar_energy_management import _async_register_frontend_resources
    src = inspect.getsource(_async_register_frontend_resources)
    assert 'f"{DOMAIN}_card_version"' in src and "asset_v['bundle']" in src
