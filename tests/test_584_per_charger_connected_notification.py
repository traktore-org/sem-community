"""#584 — push notification for a charger with no car connected.

Repro (RienduPre): a multi-charger fleet with a car plugged into ONE
charger fired a *"Zonneladen gestart: 7A (4963W)"* ("Solar charging
started") push for the OTHER, car-less charger ("Laadpaal Links").

Root cause: ``sensor_reader`` computed the fleet-OR ``ev_connected`` for
multi-charger fleets but NEVER populated ``ev_connected_per_charger``.
``build_charger_view`` reads that per-charger map to gate each charger's
``decide()`` on its OWN plug state — and, finding the map empty, silently
degraded EVERY charger to the fleet OR. So a car on the Right charger made
the Left (car-less) charger read ``connected=True`` → ``decide()``
commanded a solar charge → ``SOLAR_CHARGING_ACTIVE`` → the push.

Fix: populate ``ev_connected_per_charger`` / ``ev_charging_per_charger``
from each charger's own plug/charging sensor (both the energy-dashboard
and legacy reader paths).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.build_view import (
    build_charger_view,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
)
from custom_components.solar_energy_management.coordinator.decide import decide


CHARGERS = [
    {
        "id": "left",
        "ev_connected_sensor": "binary_sensor.left_plug",
        "ev_charging_sensor": "binary_sensor.left_charging",
    },
    {
        "id": "right",
        "ev_connected_sensor": "binary_sensor.right_plug",
        "ev_charging_sensor": "binary_sensor.right_charging",
    },
]


def _state(val):
    return SimpleNamespace(state=val, attributes={})


def _reader(states):
    hass = MagicMock()
    hass.states.get = lambda e: states.get(e)
    return SensorReader(hass, {"ev_chargers": CHARGERS})


def _fleet_state(power_readings):
    # build_charger_view only does attribute access on the fleet state —
    # a SimpleNamespace stands in without pulling the full builder.
    return SimpleNamespace(
        power=power_readings,
        config={},
        is_night=False,
        tariff_level=None,
        forecast_remaining_kwh=0.0,
        # #576 reclaim-gate inputs build_charger_view now reads (None/False =
        # no battery in the priority walk → no reclaim gating, backward-compat).
        battery_priority=None,
        battery_commanded=False,
    )


def test_fields_exist_and_default_empty():
    """The per-charger maps must be real PowerReadings fields (they were
    only ever read via defensive getattr before #584)."""
    pr = PowerReadings()
    assert pr.ev_connected_per_charger == {}
    assert pr.ev_charging_per_charger == {}


def test_sensor_reader_populates_per_charger_maps():
    """Car on the RIGHT charger only — the reader must record each
    charger's individual plug state, not just the fleet OR."""
    states = {
        "binary_sensor.left_plug": _state("off"),
        "binary_sensor.left_charging": _state("off"),
        "binary_sensor.right_plug": _state("on"),
        "binary_sensor.right_charging": _state("on"),
    }
    readings = _reader(states)._read_from_legacy_config()

    # Fleet OR is True because the right charger has a car ...
    assert readings.ev_connected is True
    # ... but the per-charger maps distinguish the two chargers.
    assert readings.ev_connected_per_charger == {"left": False, "right": True}
    assert readings.ev_charging_per_charger == {"left": False, "right": True}


def test_build_view_gates_car_less_charger_off_fleet_or():
    """The seam: with the map populated, the car-less charger reports
    connected=False even though the fleet OR is True. Pre-#584 (empty
    map) it degraded to True — the bug."""
    pr = PowerReadings()
    pr.ev_connected = True  # fleet OR — right charger has a car
    pr.ev_connected_per_charger = {"left": False, "right": True}
    pr.ev_charging_per_charger = {"left": False, "right": True}
    fs = _fleet_state(pr)

    left = build_charger_view(
        fs, charger_id="left", charger_cfg=CHARGERS[0],
        mode="solar_only", daily_ev_kwh=0.0,
    )
    right = build_charger_view(
        fs, charger_id="right", charger_cfg=CHARGERS[1],
        mode="solar_only", daily_ev_kwh=0.0,
    )
    assert left.power.connected is False
    assert right.power.connected is True


def test_car_less_charger_does_not_command_charge():
    """End-to-end tie to the symptom: a car-less charger with ample solar
    surplus must NOT command a charge — a CHARGE intent is what produced
    the 'Solar charging started' push."""
    pr = PowerReadings()
    pr.ev_connected = True  # fleet OR — a car IS on another charger
    pr.ev_connected_per_charger = {"left": False, "right": True}
    pr.solar_power = 6000.0
    pr.home_consumption_power = 500.0
    pr.battery_soc = 80.0
    fs = _fleet_state(pr)

    left = build_charger_view(
        fs, charger_id="left", charger_cfg=CHARGERS[0],
        mode="solar_only", daily_ev_kwh=0.0,
    )
    decision = decide(left)
    assert decision.intent in (ChargerIntent.IDLE, ChargerIntent.DISABLE)


def test_pre_fix_degradation_would_have_charged():
    """Guard the regression from the other side: WITHOUT the per-charger
    map (the pre-#584 state) the same car-less charger degrades to the
    fleet OR and decide() DOES command a charge — proving the map is what
    prevents the spurious push."""
    pr = PowerReadings()
    pr.ev_connected = True  # fleet OR
    pr.ev_connected_per_charger = {}  # pre-#584: never populated
    pr.solar_power = 6000.0
    pr.home_consumption_power = 500.0
    pr.battery_soc = 80.0
    fs = _fleet_state(pr)

    left = build_charger_view(
        fs, charger_id="left", charger_cfg=CHARGERS[0],
        mode="solar_only", daily_ev_kwh=0.0,
    )
    assert left.power.connected is True  # the degradation
    decision = decide(left)
    # A concrete charge intent — this is exactly what produced the push.
    assert decision.intent in (
        ChargerIntent.CHARGE_AT_AMPS, ChargerIntent.CHARGE_MAX,
    )


def test_physics_defence_mirrors_into_per_charger_map():
    """#584 follow-up: a lying plug sensor ("off" while its own charger
    draws current) must still flip THAT charger's per-charger entry, or
    build_charger_view — which now reads the map first — would stop
    supervising it (re-exposing #285+1 for multi-charger fleets)."""
    r = _reader({})
    readings = PowerReadings()
    # Left plug lies "off" but the left charger is drawing 7 kW; right is
    # genuinely idle/unplugged.
    readings.ev_connected_per_charger = {"left": False, "right": False}
    readings.ev_charging_per_charger = {"left": False, "right": False}
    readings.ev_power_per_charger = {"left": 7000.0, "right": 0.0}

    r._infer_per_charger_connection_from_physics(readings)

    assert readings.ev_connected_per_charger["left"] is True   # corrected
    assert readings.ev_connected_per_charger["right"] is False  # untouched


def test_physics_defence_mirror_uses_per_charger_charging_signal():
    """When per-charger power isn't populated (legacy path), the charger's
    own charging sensor still drives the physics correction."""
    r = _reader({})
    readings = PowerReadings()
    readings.ev_connected_per_charger = {"left": False, "right": False}
    readings.ev_charging_per_charger = {"left": True, "right": False}
    # no ev_power_per_charger (legacy path leaves it empty)

    r._infer_per_charger_connection_from_physics(readings)

    assert readings.ev_connected_per_charger["left"] is True
    assert readings.ev_connected_per_charger["right"] is False
