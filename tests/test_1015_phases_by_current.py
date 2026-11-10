"""#1015 — phase switching for a charger with no phase switch to name.

Some chargers take one current PER PHASE through a service; a phase at 0 A
is off. The phase choice and the current are then one command: 1-phase at
N A is (N, 0, 0), 3-phase is (N, N, N). The crawler finds the service by
its fields (R6), the charger device writes it through its one seam, and the
existing sequencer decides when. The fixture is the Easee capture.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import ev_control
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision, ChargerIntent, ChargerPower,
)
from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
    SETTLE_S,
)
from custom_components.solar_energy_management.coordinator.ev_phases import (
    phase_currents, phases_from_readback,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)
from custom_components.solar_energy_management.hardware_detection import (
    _service_field_roles, wire_phase_service,
)

from . import ast_contracts
from .integrations_rig.rig import load_capture, replay

FIXTURE = "easee"
P = ("current_p1", "current_p2", "current_p3")


# ── the command shape ───────────────────────────────────────────────────

@pytest.mark.unit
def test_one_phase_is_n_0_0_and_three_is_n_n_n():
    assert phase_currents(10, 1) == (10, 0, 0)
    assert phase_currents(10.4, 3) == (10, 10, 10)


@pytest.mark.unit
@pytest.mark.parametrize("amps, phases", [(0, 1), (0, 3), (-1, 3), (10, 2),
                                          (10, None), ("x", 1)])
def test_a_stop_or_an_unknown_count_is_no_command(amps, phases):
    assert phase_currents(amps, phases) is None


@pytest.mark.unit
@pytest.mark.parametrize("attrs, want", [
    ({"state_dynamicCircuitCurrentP1": 10, "state_dynamicCircuitCurrentP2": 0,
      "state_dynamicCircuitCurrentP3": 0}, 1),
    ({"p1": "16", "p2": "16.0", "p3": 16}, 3),
    ({"p1": 10, "p2": 10, "p3": 0}, None),      # two phases: not ours to name
    ({"p1": 0, "p2": 0, "p3": 0}, None),        # all off: nothing to read
    ({"p1": 0, "p2": 10, "p3": 0}, None),       # one phase, but not the first
    ({"p1": 10, "p2": "unknown", "p3": 0}, None),
    ({"p1": 10}, None),
    ({}, None), (None, None),
])
def test_the_read_back_is_one_three_or_could_not_read(attrs, want):
    assert phases_from_readback(attrs) == want


# ── found by the crawler, by its fields ─────────────────────────────────

@pytest.mark.unit
def test_the_temporary_limit_is_the_phase_service_never_a_stored_one():
    services = load_capture(FIXTURE)["services"]
    stored = sorted(n for n, f in services.items()
                    if all(p in f for p in P) and "dynamic" not in n)
    assert len(stored) >= 2, "the fixture has stored per-phase limits too"
    role = _service_field_roles(FIXTURE, services)["phase_service"]
    assert role["service"].endswith(".set_circuit_dynamic_limit")
    # with only the stored ones on offer there is no phase service at all
    only_stored = {n: services[n] for n in stored}
    assert "phase_service" not in _service_field_roles(FIXTURE, only_stored)


def _device(hass, **over):
    kw = dict(hass=hass, device_id="c1", name="Box", priority=1,
              min_current=6, max_current=16, phases=3, voltage=230,
              power_entity_id="sensor.box_power",
              charger_service=f"{FIXTURE}.set_charger_dynamic_limit",
              charger_service_entity_id=None, current_entity_id=None)
    kw.update(over)
    return CurrentControlDevice(**kw)


async def _rig(hass):
    """The fixture replayed, its box wired, every service call recorded."""
    ids = await replay(hass, load_capture(FIXTURE))
    from homeassistant.helpers import entity_registry as er
    box_id = er.async_get(hass).async_get(
        "sensor.easee_home_eh123456_power").device_id
    assert box_id in ids.values()
    calls = []
    for name, svc in list(hass.services.async_services().get(FIXTURE, {}).items()):
        async def _rec(call, _n=name):
            calls.append((_n, dict(call.data)))
        hass.services.async_register(FIXTURE, name, _rec, schema=svc.schema)
    dev = _device(hass)
    dev.service_device_id = box_id
    # the box's own stop, as the crawler offers it for this fixture
    dev.stop_service = f"{FIXTURE}.action_command"
    dev.stop_service_data = {"action_command": "pause"}
    dev.start_service = f"{FIXTURE}.action_command"
    dev.start_service_data = {"action_command": "resume"}
    return dev, box_id, calls


READBACK = "sensor.easee_home_eh123456_dynamic_circuit_limit"


def _enable_readback(hass):
    """The fixture ships the per-phase limit sensor switched off."""
    from homeassistant.helpers import entity_registry as er
    er.async_get(hass).async_update_entity(READBACK, disabled_by=None)


async def test_pipeline_wired_from_the_live_services(hass):
    dev, box_id, _calls = await _rig(hass)
    assert dev.phase_service is None                       # not asked yet
    assert wire_phase_service(hass, dev, "c1") is True
    assert dev.phase_service == f"{FIXTURE}.set_circuit_dynamic_limit"
    assert dev.phase_fields == P
    # the sensor that reports the limit is off by default: no read-back,
    # and that is "could not read", not a failure
    assert dev.phase_readback_entity is None
    assert dev.phase_readback() is None
    _enable_readback(hass)
    assert wire_phase_service(hass, dev, "c1") is True
    assert dev.phase_readback_entity == READBACK


async def test_pipeline_one_write_carries_phases_and_amps(hass):
    dev, box_id, calls = await _rig(hass)
    wire_phase_service(hass, dev, "c1")

    assert await dev.switch_phases(1) is True
    await hass.async_block_till_done()
    # the shape first, then the charger's own limit is raised once
    assert calls == [
        ("set_circuit_dynamic_limit", {"current_p1": 6, "current_p2": 0,
                                       "current_p3": 0, "device_id": box_id}),
        ("set_charger_dynamic_limit", {"current": 16.0, "device_id": box_id}),
    ]
    calls.clear()

    await dev._set_current(10)                # the normal current command
    await hass.async_block_till_done()
    assert calls == [("set_circuit_dynamic_limit", {
        "current_p1": 10, "current_p2": 0, "current_p3": 0,
        "device_id": box_id})]
    calls.clear()

    assert await dev.switch_phases(3) is True
    await dev._set_current(10)
    await hass.async_block_till_done()
    assert [c[1] for c in calls] == [
        {"current_p1": 6, "current_p2": 6, "current_p3": 6, "device_id": box_id},
        {"current_p1": 10, "current_p2": 10, "current_p3": 10, "device_id": box_id},
    ]


async def test_pipeline_a_stop_is_never_three_zeros(hass):
    dev, box_id, calls = await _rig(hass)
    wire_phase_service(hass, dev, "c1")
    await dev.switch_phases(1)
    calls.clear()
    await dev._set_current(0)
    await hass.async_block_till_done()
    assert calls == []          # no three zeros, no 0 A on the charger's limit
    assert dev._phase_command(0) is None


async def test_pipeline_same_amps_on_another_phase_count_is_written(hass):
    """The heartbeat dedup skips an unchanged current — not a new shape."""
    dev, box_id, calls = await _rig(hass)
    wire_phase_service(hass, dev, "c1")
    dev.phase_target = 3
    await dev._set_current(10)
    dev._status.state = type(dev._status.state).ACTIVE
    calls.clear()
    await dev._set_current(10)                       # unchanged: deduped
    await hass.async_block_till_done()
    assert calls == []
    dev.phase_target = 1                             # the sequencer chose
    await dev._set_current(10)
    await hass.async_block_till_done()
    assert calls == [("set_circuit_dynamic_limit", {
        "current_p1": 10, "current_p2": 0, "current_p3": 0,
        "device_id": box_id})]


async def test_pipeline_untouched_until_a_phase_was_chosen(hass):
    """Wired but never asked: the plain current service, as before."""
    dev, box_id, calls = await _rig(hass)
    wire_phase_service(hass, dev, "c1")
    await dev._set_current(10)
    await hass.async_block_till_done()
    assert calls == [("set_charger_dynamic_limit",
                      {"current": 10.0, "device_id": box_id})]


async def test_pipeline_observer_mode_sends_nothing(hass):
    dev, box_id, calls = await _rig(hass)
    wire_phase_service(hass, dev, "c1")
    dev.observer_mode = True
    assert await dev.switch_phases(1) is False
    await dev._set_current(10)
    await hass.async_block_till_done()
    assert calls == []
    assert dev._phase_written is None                # nothing was written


async def test_pipeline_the_read_back_reads_the_box(hass):
    dev, box_id, _calls = await _rig(hass)
    _enable_readback(hass)
    wire_phase_service(hass, dev, "c1")
    eid = dev.phase_readback_entity
    assert eid == READBACK
    hass.states.async_set(eid, "unknown", {})
    assert dev.phase_readback() is None              # no per-phase values yet
    hass.states.async_set(eid, "10", {"state_dynamicCircuitCurrentP1": 10,
                                      "state_dynamicCircuitCurrentP2": 0,
                                      "state_dynamicCircuitCurrentP3": 0})
    assert dev.phase_readback() == 1
    hass.states.async_set(eid, "10", {"state_dynamicCircuitCurrentP1": 10,
                                      "state_dynamicCircuitCurrentP2": 10,
                                      "state_dynamicCircuitCurrentP3": 10})
    assert dev.phase_readback() == 3
    hass.states.async_remove(eid)
    assert dev.phase_readback() is None


async def test_pipeline_not_wired_without_what_it_needs(hass):
    dev, box_id, _calls = await _rig(hass)
    no_id = _with_stop(_device(hass))                # keyed by device, none saved
    assert wire_phase_service(hass, no_id, "c2") is False
    assert no_id.phase_service is None
    number = _device(hass, charger_service=None,
                     current_entity_id="number.other_box_current")
    assert wire_phase_service(hass, number, "c3") is False
    other = _device(hass, charger_service="otherbox.set_current")
    other.service_device_id = box_id
    assert wire_phase_service(hass, other, "c4") is False
    assert other.phase_service is None


# ── the sequencer drives it ─────────────────────────────────────────────

VOLTS = 230.0


class _Box:
    """A charger device as the tick sees it."""

    def __init__(self, service="box.set_phase_currents"):
        self.phase_service = service
        self.switched = []
        self.readback = None
        self.sent = True

    async def switch_phases(self, phases):
        self.switched.append(phases)
        return self.sent

    def phase_readback(self):
        return self.readback


def _host(observer=False, **cfg_over):
    h = SimpleNamespace()
    h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
    h._observer_mode = observer
    h._surplus_controller = None
    h.config = {}
    h.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: None),
        services=SimpleNamespace(async_call=AsyncMock(),
                                 async_services=lambda: {}),
        is_running=True,
    )
    h.cfg = {"ev_phase_switching_enabled": True, "phase_mode": "1",
             "ev_voltage": VOLTS, "ev_min_current": 6, "ev_max_current": 16}
    h.cfg.update(cfg_over)
    return h


def _amps(amps=10):
    return ChargerDecision(charger_id="c1", mode="solar_only",
                           intent=ChargerIntent.CHARGE_AT_AMPS,
                           commanded_amps=amps, budget_w=7000.0,
                           reason="surplus")


def _cp(power_w, charging=True, cid="c1"):
    return ChargerPower(charger_id=cid, power_w=power_w, connected=True,
                        charging=charging)


def _tick(h, box, decision, cp, t, cid="c1", cfg=None):
    return asyncio.run(h._phase_switch_tick(
        cid, cfg if cfg is not None else h.cfg, decision, cp, t,
        setpoint_a=10, device=box))


def _switch_to_one(h, box, t=0.0):
    """Charging on three phases, target 1: stop, switch, settle."""
    d = _tick(h, box, _amps(), _cp(6900.0), t)                 # belief 3
    assert d.intent is ChargerIntent.DISABLE                   # held to stop
    _tick(h, box, _amps(), _cp(0.0, charging=False), t + 20)   # fires
    return t + 20


@pytest.mark.unit
def test_the_switch_is_the_devices_write_never_a_call_from_the_loop():
    h, box = _host(), _Box()
    t = _switch_to_one(h, box)
    assert box.switched == [1]
    h.hass.services.async_call.assert_not_called()
    _tick(h, box, _amps(), _cp(0.0, charging=False), t + SETTLE_S + 5)
    assert h._phase_believed["c1"] == 1
    assert ast_contracts.calls(
        ev_control.EVControlMixin._phase_switch_tick, "switch_phases")


@pytest.mark.unit
def test_switched_off_the_charger_is_not_even_asked():
    h, box = _host(ev_phase_switching_enabled=False), _Box()
    d = _amps()
    assert _tick(h, box, d, _cp(6900.0), 0.0) is d
    assert box.switched == [] and not hasattr(h, "_phase_sequencers")
    assert not hasattr(h, "_phase_wire_asked")


@pytest.mark.unit
def test_observer_mode_runs_the_sequence_and_the_device_withholds():
    h, box = _host(observer=True), _Box()
    box.sent = False                       # the seam withheld it
    _tick(h, box, _amps(), _cp(6900.0), 0.0)
    _tick(h, box, _amps(), _cp(0.0, charging=False), 20.0)
    assert box.switched == [1]
    h.hass.services.async_call.assert_not_called()


@pytest.mark.unit
def test_a_box_that_reports_another_count_did_not_switch():
    h, box = _host(), _Box()
    t = _switch_to_one(h, box)
    t += SETTLE_S + 5
    _tick(h, box, _amps(), _cp(0.0, charging=False), t)        # settle → 1
    box.readback = 3                                           # the box: still 3
    _tick(h, box, _amps(), _cp(0.0, charging=False), t + SETTLE_S + 10)
    assert h._phase_contradictions["c1"]["count"] == 1
    assert h._phase_believed["c1"] == 3


@pytest.mark.unit
def test_a_read_back_that_cannot_be_read_blames_nothing():
    h, box = _host(), _Box()
    t = _switch_to_one(h, box)
    t += SETTLE_S + 5
    _tick(h, box, _amps(), _cp(0.0, charging=False), t)
    box.readback = None
    _tick(h, box, _amps(), _cp(0.0, charging=False), t + 10)
    assert h._phase_contradictions["c1"]["count"] == 0
    box.readback = 1                                           # it agrees
    _tick(h, box, _amps(), _cp(0.0, charging=False), t + 20)
    assert h._phase_contradictions["c1"]["count"] == 0
    assert h._phase_believed["c1"] == 1


@pytest.mark.unit
def test_two_chargers_only_the_one_that_can_is_switched():
    h, box = _host(), _Box()
    plain = SimpleNamespace(phase_service=None, charger_service="other.set",
                            service_device_id=None)
    cfg2 = dict(h.cfg)
    d2 = ChargerDecision(charger_id="c2", mode="solar_only",
                         intent=ChargerIntent.CHARGE_AT_AMPS,
                         commanded_amps=10, budget_w=7000.0, reason="surplus")
    _tick(h, box, _amps(), _cp(6900.0), 0.0)
    out2 = _tick(h, plain, d2, _cp(6900.0, cid="c2"), 0.0, cid="c2", cfg=cfg2)
    _tick(h, box, _amps(), _cp(0.0, charging=False), 20.0)
    assert out2 is d2                                  # passed through
    assert box.switched == [1]
    assert set(h._phase_sequencers) == {"c1"}          # no state for the other
    assert plain.phase_service is None
    # the one that cannot is asked again at most once a minute
    asked = h._phase_wire_asked["c2"]
    _tick(h, plain, d2, _cp(6900.0, cid="c2"), 30.0, cid="c2", cfg=cfg2)
    assert h._phase_wire_asked["c2"] == asked


@pytest.mark.unit
def test_a_mock_device_is_not_a_capability():
    """A fake that answers every attribute must not read as wired."""
    h = _host()
    d = _amps()
    assert _tick(h, MagicMock(), d, _cp(6900.0), 0.0) is d
    assert _tick(h, None, d, _cp(6900.0), 0.0) is d


@pytest.mark.unit
def test_a_named_entity_still_wins():
    """With a phase switch entity the old path is used, untouched."""
    h, box = _host(ev_phase_switch_entity="number.box_phases"), _Box()
    h.hass.states.get = lambda eid: MagicMock()
    _tick(h, box, _amps(), _cp(6900.0), 0.0)
    _tick(h, box, _amps(), _cp(0.0, charging=False), 20.0)
    assert box.switched == []
    h.hass.services.async_call.assert_called_once()


# ── review round: lockout, shared circuit, lagging read-back, lift order ─

STOP = {"action_command": "pause"}


def _with_stop(dev):
    dev.stop_service = f"{FIXTURE}.action_command"
    dev.stop_service_data = dict(STOP)
    dev.start_service = f"{FIXTURE}.action_command"
    dev.start_service_data = {"action_command": "resume"}
    return dev


async def test_stop_then_start_the_car_gets_current_again(hass):
    """A stop on this path never parks 0 A on the charger's own limit, and
    the start after it restores that limit — else the car is locked out."""
    dev, box_id, calls = await _rig(hass)
    _with_stop(dev)
    assert wire_phase_service(hass, dev, "c1") is True
    await dev.switch_phases(3)
    await dev._set_current(10)
    calls.clear()

    await dev.deactivate()                           # the stop
    await hass.async_block_till_done()
    own = [c for c in calls if c[0] == "set_charger_dynamic_limit"]
    assert not [c for c in own if c[1]["current"] <= 0], (
        "0 A parked on the charger's own limit")
    assert not [c for c in calls if c[0] == "set_circuit_dynamic_limit"
                and not any(c[1][p] for p in P)]
    calls.clear()

    await dev._set_current(10)                       # the next start
    await hass.async_block_till_done()
    assert ("set_circuit_dynamic_limit", {
        "current_p1": 10, "current_p2": 10, "current_p3": 10,
        "device_id": box_id}) in calls
    assert ("set_charger_dynamic_limit",
            {"current": 16.0, "device_id": box_id}) in calls, (
        "the charger's own limit was not restored after the stop")


async def test_a_plain_write_in_between_is_lifted_again(hass):
    """Whatever wrote the charger's own limit, the next shape lifts it."""
    dev, box_id, calls = await _rig(hass)
    _with_stop(dev)
    wire_phase_service(hass, dev, "c1")
    await dev.switch_phases(1)
    dev.phase_target = None                          # e.g. switching turned off
    await dev._set_current(8)                        # the plain service: 8 A
    dev.phase_target = 1
    calls.clear()
    await dev._set_current(10)
    await hass.async_block_till_done()
    assert ("set_charger_dynamic_limit",
            {"current": 16.0, "device_id": box_id}) in calls


async def test_not_wired_without_a_stop_of_its_own(hass):
    """0 A may not stop this charger (it would cap the per-phase limit), so
    a charger with no stop of its own does not switch phases by current."""
    _dev, box_id, _calls = await _rig(hass)
    dev = _device(hass)
    dev.service_device_id = box_id
    assert wire_phase_service(hass, dev, "c1") is False
    assert dev.phase_service is None
    _with_stop(dev)
    assert wire_phase_service(hass, dev, "c1") is True


async def test_the_shape_goes_first_and_the_lift_never_alone(hass):
    dev, box_id, calls = await _rig(hass)
    _with_stop(dev)
    wire_phase_service(hass, dev, "c1")
    await dev.switch_phases(1)
    await hass.async_block_till_done()
    assert [c[0] for c in calls] == ["set_circuit_dynamic_limit",
                                     "set_charger_dynamic_limit"]

    # the shape write fails: the charger's own limit is left alone
    dev2, _box, calls2 = await _rig_second(hass, box_id)
    _with_stop(dev2)
    wire_phase_service(hass, dev2, "c9")
    real_send = dev2.send

    async def _send(domain, service, data=None, **kw):
        if service == "set_circuit_dynamic_limit":
            return False                              # withheld / not taken
        return await real_send(domain, service, data, **kw)
    dev2.send = _send
    assert await dev2.switch_phases(1) is False
    await hass.async_block_till_done()
    assert calls2 == []


async def _rig_second(hass, box_id):
    calls = []
    for name, svc in list(hass.services.async_services().get(FIXTURE, {}).items()):
        async def _rec(call, _n=name):
            calls.append((_n, dict(call.data)))
        hass.services.async_register(FIXTURE, name, _rec, schema=svc.schema)
    dev = _device(hass, device_id="c9")
    dev.service_device_id = box_id
    return dev, box_id, calls


# shared circuit ---------------------------------------------------------

def _circuit_box(circuit=None, service="box.set_phase_currents"):
    b = _Box(service)
    b.charger_service = "box.set_current"
    b.circuit = circuit
    return b


def _share_host(a, b, **kw):
    h = _host(**kw)
    h._ev_devices = {"c1": a, "c2": b}
    return h


@pytest.mark.unit
def test_two_chargers_on_one_circuit_do_not_switch_by_current(monkeypatch):
    from custom_components.solar_energy_management import hardware_detection as hd
    monkeypatch.setattr(hd, "phase_circuit_key",
                        lambda hass, dev: getattr(dev, "circuit", None))
    a, b = _circuit_box("circuit-1"), _circuit_box("circuit-1")
    h = _share_host(a, b)
    d = _amps()
    assert _tick(h, a, d, _cp(6900.0), 0.0) is d       # untouched
    _tick(h, a, d, _cp(0.0, charging=False), 20.0)
    assert a.switched == [] and b.switched == []
    assert h._phase_switch_states["c1"] == "shared_circuit"


@pytest.mark.unit
def test_an_unknown_circuit_counts_as_shared(monkeypatch):
    from custom_components.solar_energy_management import hardware_detection as hd
    monkeypatch.setattr(hd, "phase_circuit_key",
                        lambda hass, dev: getattr(dev, "circuit", None))
    a, b = _circuit_box("circuit-1"), _circuit_box(None)
    h = _share_host(a, b)
    d = _amps()
    assert _tick(h, a, d, _cp(6900.0), 0.0) is d
    assert h._phase_switch_states["c1"] == "shared_circuit"


@pytest.mark.unit
def test_two_circuits_or_another_integration_switch_as_before(monkeypatch):
    from custom_components.solar_energy_management import hardware_detection as hd
    monkeypatch.setattr(hd, "phase_circuit_key",
                        lambda hass, dev: getattr(dev, "circuit", None))
    a, b = _circuit_box("circuit-1"), _circuit_box("circuit-2")
    h = _share_host(a, b)
    _switch_to_one(h, a)
    assert a.switched == [1]
    other = SimpleNamespace(phase_service=None, charger_service="otherbox.set",
                            service_device_id=None)
    a2 = _circuit_box(None)
    h2 = _share_host(a2, other)
    _switch_to_one(h2, a2)
    assert a2.switched == [1]


async def test_the_circuit_is_read_from_what_the_install_exposes(hass):
    from custom_components.solar_energy_management.hardware_detection import (
        phase_circuit_key,
    )
    dev, box_id, _calls = await _rig(hass)
    assert phase_circuit_key(hass, dev) is None        # nothing says which
    hass.states.async_set("sensor.easee_home_eh123456_status", "charging",
                          {"config_circuitId": 4711})
    assert phase_circuit_key(hass, dev) == "4711"


# a lagging read-back ----------------------------------------------------

@pytest.mark.unit
def test_a_read_back_that_lags_is_not_yet_an_answer():
    h, box = _host(), _Box()
    t = _switch_to_one(h, box)
    box.readback = 3                       # the cloud still shows the old count
    t += SETTLE_S + 5
    _tick(h, box, _amps(), _cp(0.0, charging=False), t)        # settle → 1
    _tick(h, box, _amps(), _cp(0.0, charging=False), t + 10)
    _tick(h, box, _amps(), _cp(0.0, charging=False), t + 20)
    assert h._phase_contradictions["c1"]["count"] == 0, (
        "a stale reading inside the settle time counted as not switched")
    assert h._phase_believed["c1"] == 1
    box.readback = 1                       # it catches up
    _tick(h, box, _amps(), _cp(0.0, charging=False), t + SETTLE_S + 30)
    assert h._phase_contradictions["c1"]["count"] == 0


@pytest.mark.unit
def test_the_measured_draw_overrules_a_stale_read_back():
    h, box = _host(), _Box()
    t = _switch_to_one(h, box)
    t += SETTLE_S + 5
    _tick(h, box, _amps(), _cp(0.0, charging=False), t)        # settle → 1
    box.readback = 3                       # stale for good
    t += 2 * SETTLE_S + 60
    _tick(h, box, _amps(), _cp(2300.0), t)                     # 10 A × 1 phase
    _tick(h, box, _amps(), _cp(2300.0), t + 10)
    assert h._phase_contradictions["c1"]["count"] == 0
    assert h._phase_believed["c1"] == 1
    assert h._phase_switch_states["c1"] != "not_taking"
