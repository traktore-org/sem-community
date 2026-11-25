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
    """The resource URL's ``?v=`` and the published token are one value."""
    import ast
    import pathlib
    tree = ast.parse((pathlib.Path(__file__).resolve().parents[1] / "__init__.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_async_register_frontend_resources")
    stores = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
              and isinstance(n.targets[0], ast.Subscript)
              and isinstance(n.value, ast.Subscript)
              and getattr(n.value.value, "id", "") == "asset_v"
              and getattr(n.value.slice, "value", None) == "bundle"]
    assert len(stores) == 1
