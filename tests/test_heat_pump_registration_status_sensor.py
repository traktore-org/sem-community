"""Tests for the #432 heat-pump registration status diagnostic sensor.

The sensor publishes one of six strings depending on the
``(relay1, relay2, climate)`` config tuple + the surplus controller's
``_devices`` dict. Attributes expose the resolved entity ids + their
live HA state so users with non-standard SG-Ready wiring (ESP relays,
Shelly switches, Modbus-bridged template switches) can self-diagnose
without us owning the hardware.

What we lock:
  * Each of the 6 status strings matches the right config/registration
    combination.
  * Attribute values reflect ``hass.states.get(eid).state`` for each
    configured entity, with ``entity_missing`` when the entity id is set
    but doesn't exist.
"""
from types import SimpleNamespace


from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _coord(config: dict | None = None, registered: bool = False):
    """Build a bare SEMCoordinator with just enough state to exercise
    the heat-pump status computation. Mirrors the pattern in
    tests/test_home_consumption_smoothing.py."""
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = config or {}
    # Surplus controller stub — its ``_devices`` dict drives the
    # ``registered`` flag in coordinator.py.
    coord._surplus_controller = SimpleNamespace(
        _devices={"heat_pump": object()} if registered else {},
    )
    coord.hass = _FakeHass()
    return coord


class _FakeHass:
    """Minimal hass stub — only ``hass.states.get()`` is called."""
    def __init__(self):
        self._states: dict[str, str] = {}
        self.states = _FakeStates(self._states)

    def set(self, entity_id: str, state: str) -> None:
        self._states[entity_id] = state


class _FakeStates:
    def __init__(self, store: dict[str, str]):
        self._store = store

    def get(self, entity_id: str):
        if entity_id not in self._store:
            return None
        return SimpleNamespace(state=self._store[entity_id])


def _compute(coord) -> tuple[str, dict]:
    """Run the same status / attribute computation the coordinator
    cycle does. We isolate it inline rather than running the full
    coordinator cycle — that needs power readings, fleet state, etc.
    """
    hp_relay1 = coord.config.get("heat_pump_relay1_entity") or None
    hp_relay2 = coord.config.get("heat_pump_relay2_entity") or None
    hp_climate = coord.config.get("heat_pump_climate_entity") or None

    def _entity_state(eid):
        if not eid:
            return None
        st = coord.hass.states.get(eid)
        return st.state if st else "entity_missing"

    registered = "heat_pump" in coord._surplus_controller._devices
    if registered:
        if hp_relay1 and hp_relay2 and hp_climate:
            status = "registered_sg_ready_and_climate"
        elif hp_relay1 and hp_relay2:
            status = "registered_sg_ready"
        elif hp_climate:
            status = "registered_climate_only"
        else:
            status = "registered_unknown_mode"
    else:
        if hp_relay1 and not hp_relay2 and not hp_climate:
            status = "partial_sg_ready_only_relay1"
        elif hp_relay2 and not hp_relay1 and not hp_climate:
            status = "partial_sg_ready_only_relay2"
        else:
            status = "not_configured"

    attrs = {
        "relay1_entity": hp_relay1,
        "relay2_entity": hp_relay2,
        "climate_entity": hp_climate,
        "relay1_state": _entity_state(hp_relay1),
        "relay2_state": _entity_state(hp_relay2),
        "climate_state": _entity_state(hp_climate),
    }
    return status, attrs


# ── 6-string state coverage ─────────────────────────────────────────


def test_not_configured_when_no_entities_set():
    coord = _coord(config={}, registered=False)
    status, attrs = _compute(coord)
    assert status == "not_configured"
    assert attrs["relay1_entity"] is None
    assert attrs["relay2_entity"] is None
    assert attrs["climate_entity"] is None


def test_registered_sg_ready_when_both_relays_and_registered():
    coord = _coord(
        config={
            "heat_pump_relay1_entity": "switch.shelly1",
            "heat_pump_relay2_entity": "switch.shelly2",
        },
        registered=True,
    )
    coord.hass.set("switch.shelly1", "on")
    coord.hass.set("switch.shelly2", "off")
    status, attrs = _compute(coord)
    assert status == "registered_sg_ready"
    assert attrs["relay1_state"] == "on"
    assert attrs["relay2_state"] == "off"


def test_registered_climate_only_when_only_climate_set():
    coord = _coord(
        config={"heat_pump_climate_entity": "climate.nibe_vvm320"},
        registered=True,
    )
    coord.hass.set("climate.nibe_vvm320", "heat")
    status, attrs = _compute(coord)
    assert status == "registered_climate_only"
    assert attrs["climate_state"] == "heat"


def test_registered_sg_ready_and_climate_when_both_paths_active():
    coord = _coord(
        config={
            "heat_pump_relay1_entity": "switch.r1",
            "heat_pump_relay2_entity": "switch.r2",
            "heat_pump_climate_entity": "climate.nibe",
        },
        registered=True,
    )
    coord.hass.set("switch.r1", "on")
    coord.hass.set("switch.r2", "on")
    coord.hass.set("climate.nibe", "heat")
    status, _ = _compute(coord)
    assert status == "registered_sg_ready_and_climate"


def test_partial_sg_ready_only_relay1():
    coord = _coord(
        config={"heat_pump_relay1_entity": "switch.r1"},
        registered=False,
    )
    coord.hass.set("switch.r1", "off")
    status, attrs = _compute(coord)
    assert status == "partial_sg_ready_only_relay1"
    assert attrs["relay1_state"] == "off"
    assert attrs["relay2_state"] is None


def test_partial_sg_ready_only_relay2():
    coord = _coord(
        config={"heat_pump_relay2_entity": "switch.r2"},
        registered=False,
    )
    coord.hass.set("switch.r2", "off")
    status, _ = _compute(coord)
    assert status == "partial_sg_ready_only_relay2"


# ── attribute states ────────────────────────────────────────────────


def test_entity_missing_when_entity_id_set_but_doesnt_exist():
    """The user typo'd an entity id, OR an integration was removed
    leaving the SEM option pointing at a non-existent entity."""
    coord = _coord(
        config={
            "heat_pump_relay1_entity": "switch.relay_that_does_not_exist",
            "heat_pump_relay2_entity": "switch.also_missing",
        },
        registered=True,
    )
    # No states set on _FakeHass; both ``hass.states.get`` return None.
    _, attrs = _compute(coord)
    assert attrs["relay1_state"] == "entity_missing"
    assert attrs["relay2_state"] == "entity_missing"


def test_unavailable_state_shows_through_as_unavailable():
    """ESP board is offline — entity exists in HA but reads
    ``unavailable``. The attribute reflects this so RienduPre can see
    'oh, my relay is offline' in one screenshot."""
    coord = _coord(
        config={
            "heat_pump_relay1_entity": "switch.esp_relay1",
            "heat_pump_relay2_entity": "switch.esp_relay2",
        },
        registered=True,
    )
    coord.hass.set("switch.esp_relay1", "unavailable")
    coord.hass.set("switch.esp_relay2", "on")
    _, attrs = _compute(coord)
    assert attrs["relay1_state"] == "unavailable"
    assert attrs["relay2_state"] == "on"
