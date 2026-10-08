"""#1021 — the grid operator's "reduce load" signal (§14a EnWG, ripple control)."""
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.shed_signal import (
    LEGAL_FLOOR_KW, ShedSignal, read_shed_signal,
)


def _S(state):
    return SimpleNamespace(state=state)


def _get(states):
    return lambda e: states.get(e)


class TestTheInput:
    def test_no_entity_is_inert(self):
        assert read_shed_signal(None, 4.2, _get({})) == ShedSignal(
            False, None, "none", None)

    def test_on_gives_the_cap(self):
        s = read_shed_signal("binary_sensor.relay", 4.2,
                             _get({"binary_sensor.relay": _S("on")}))
        assert s.active and s.cap_kw == 4.2 and s.state == "on"

    def test_off_is_off(self):
        s = read_shed_signal("binary_sensor.relay", 4.2,
                             _get({"binary_sensor.relay": _S("off")}))
        assert not s.active and s.cap_kw is None and s.state == "off"

    def test_cap_from_a_sensor(self):
        s = read_shed_signal("binary_sensor.relay", "sensor.lpc_kw",
                             _get({"binary_sensor.relay": _S("on"),
                                   "sensor.lpc_kw": _S("6.3")}))
        assert s.cap_kw == 6.3

    def test_a_numeric_string_is_a_number_not_an_entity(self):
        # options may store "5.5" as text — the dot must not make it an entity
        s = read_shed_signal("binary_sensor.relay", "5.5",
                             _get({"binary_sensor.relay": _S("on")}))
        assert s.cap_kw == 5.5

    def test_unreadable_cap_falls_back_to_the_legal_floor(self):
        s = read_shed_signal("binary_sensor.relay", "sensor.lpc_kw",
                             _get({"binary_sensor.relay": _S("on"),
                                   "sensor.lpc_kw": _S("unavailable")}))
        assert s.cap_kw == LEGAL_FLOOR_KW == 4.2

    def test_zero_or_missing_cap_falls_back_to_the_legal_floor(self):
        for limit in (0, None, -1, "", True):
            s = read_shed_signal("binary_sensor.relay", limit,
                                 _get({"binary_sensor.relay": _S("on")}))
            assert s.cap_kw == 4.2, limit

    def test_unavailable_signal_is_off_and_says_so(self):
        s = read_shed_signal("binary_sensor.relay", 4.2,
                             _get({"binary_sensor.relay": _S("unavailable")}))
        assert not s.active and s.state == "unavailable"

    def test_a_missing_entity_is_off_and_says_unknown(self):
        s = read_shed_signal("binary_sensor.gone", 4.2, _get({}))
        assert not s.active and s.state == "unknown"

    def test_input_boolean_true_reads_on(self):
        s = read_shed_signal("input_boolean.relay", 4.2,
                             _get({"input_boolean.relay": _S("on")}))
        assert s.active

    def test_the_reader_never_raises(self):
        def boom(_e):
            raise RuntimeError("state machine gone")
        s = read_shed_signal("binary_sensor.relay", 4.2, boom)
        assert not s.active and s.state == "unknown"


# ── Task 8: a device behind the operator's relay is locked (CH) ──
from custom_components.solar_energy_management.coordinator.shed_signal import (  # noqa: E402
    INERT,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (  # noqa: E402
    SurplusController, compute_load_intent,
)
from custom_components.solar_energy_management.devices.base import (  # noqa: E402
    DeviceControlMode, DeviceState, SwitchDevice,
)

_ON = ShedSignal(True, "binary_sensor.relay", "on", 4.2)


def _boiler(hass, behind=True, active=False):
    d = SwitchDevice(hass=hass, device_id="boiler", name="Boiler",
                     rated_power=2000, priority=3,
                     entity_id="switch.boiler")
    d.control_mode = DeviceControlMode.SURPLUS
    d.behind_operator_relay = behind
    if active:
        d._status.state = DeviceState.ACTIVE
    return d


def _controller(hass, sig, *devices):
    c = SurplusController(hass)
    c.shed_signal = sig
    for d in devices:
        c.register_device(d)
    return c


class TestTheLock:
    def test_behind_the_relay_and_on_is_locked(self, hass):
        d = _boiler(hass)
        _controller(hass, _ON, d)
        assert d.locked_by_operator

    def test_relay_off_is_todays_behaviour(self, hass):
        d = _boiler(hass)
        _controller(hass, ShedSignal(False, "binary_sensor.relay", "off", None), d)
        assert not d.locked_by_operator

    def test_not_behind_the_relay_keeps_running(self, hass):
        d = _boiler(hass, behind=False)
        _controller(hass, _ON, d)
        assert not d.locked_by_operator

    def test_no_relay_configured_is_inert(self, hass):
        d = _boiler(hass)
        _controller(hass, INERT, d)
        assert not d.locked_by_operator

    def test_the_intent_says_why_and_never_writes(self, hass):
        for active in (False, True):
            d = _boiler(hass, active=active)
            _controller(hass, _ON, d)
            intent = compute_load_intent(d, remaining_surplus_w=5000.0)
            # keeps whatever state it is in: no turn_on, no turn_off
            assert intent.on is active
            assert intent.power_w == 0.0
            assert intent.reason == "locked by the grid operator"

    def test_unlocked_with_surplus_would_start(self, hass):
        d = _boiler(hass, behind=False)
        _controller(hass, _ON, d)
        intent = compute_load_intent(d, remaining_surplus_w=5000.0)
        assert intent.reason != "locked by the grid operator"

    async def test_the_imperative_walk_does_not_start_it(self, hass):
        d = _boiler(hass)
        c = _controller(hass, _ON, d)
        calls = []
        async def _act(*a, **k):
            calls.append("on")
            return True
        d.activate = _act
        d._surplus_since = None
        d.activation_delay_seconds = 0
        await c.update(available_power_w=6000.0)
        await c.update(available_power_w=6000.0)
        await c.update(available_power_w=6000.0)
        assert calls == []


class TestThePlanLeavesItOut:
    def test_the_signature_names_the_locked_loads(self, hass):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        d = _boiler(hass)
        ctl = _controller(hass, _ON, d)
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.config = {"ev_chargers": []}
        c._surplus_controller = ctl
        on = c._energy_plan_demand_signature(SimpleNamespace(
            ev_connected=False, ev_connected_per_charger=None))
        ctl.shed_signal = ShedSignal(False, "binary_sensor.relay", "off", None)
        off = c._energy_plan_demand_signature(SimpleNamespace(
            ev_connected=False, ev_connected_per_charger=None))
        assert ("operator_locked", ("boiler",)) in on
        assert ("operator_locked", ()) in off
        assert on != off


class TestTheCycleReadsItOnce:
    def _coord(self, hass, config, ctl):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.hass = hass
        c.config = config
        c._surplus_controller = ctl
        return c

    def test_no_entity_stamps_inert(self, hass):
        ctl = SurplusController(hass)
        c = self._coord(hass, {}, ctl)
        assert c._refresh_shed_signal() is INERT
        assert ctl.shed_signal is INERT

    async def test_the_relay_reaches_the_load_walk(self, hass):
        hass.states.async_set("binary_sensor.relay", "on")
        ctl = SurplusController(hass)
        c = self._coord(hass, {"shed_signal_entity": "binary_sensor.relay",
                               "shed_signal_limit": 5.0}, ctl)
        sig = c._refresh_shed_signal()
        assert sig.active and sig.cap_kw == 5.0
        assert ctl.shed_signal is sig is c._shed_signal


class TestTheSignalHasCallers:
    """(#1021) #664 removed a utility-signal surface nobody could reach: no
    form field, no card, no caller. Its guard said a real implementation
    must replace it. This is that replacement: every part of #1021 has a
    caller, so the orphan state #664 cleared cannot come back."""

    _ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent

    def _src(self, rel):
        return (self._ROOT / rel).read_text(encoding="utf-8")

    def test_the_cycle_reads_the_relay(self):
        src = self._src("coordinator/coordinator.py")
        assert "self._refresh_shed_signal()" in src
        assert "read_shed_signal(" in src

    def test_the_load_walk_reads_the_lock(self):
        src = self._src("coordinator/surplus_controller.py")
        assert src.count('"locked_by_operator", False) is True') >= 2

    def test_the_relay_is_in_the_gui_and_the_options_flow(self):
        assert '"shed_signal_entity"' in self._src("config_flow.py")
        card = self._src("dashboard/card/src/cards/sem-config-card.js")
        assert "'shed_signal_entity'" in card and "'shed_signal_limit'" in card

    def test_the_device_switch_is_in_the_gui_and_the_service(self):
        assert '"behind_operator_relay"' in self._src("__init__.py")
        assert "behind_operator_relay" in self._src(
            "dashboard/card/src/cards/sem-load-priority-card.js")
        assert '"behind_operator_relay"' in self._src(
            "features/device_registry.py")

    def test_the_old_surface_stays_gone(self):
        assert not (self._ROOT / "utility_signals.py").exists()


class TestTheBannerPayload:
    def test_since_is_set_on_and_cleared_off(self, hass):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.hass = hass
        c.config = {"shed_signal_entity": "binary_sensor.relay"}
        c._surplus_controller = SurplusController(hass)
        c._shed_signal = INERT
        c._shed_signal_since = None
        hass.states.async_set("binary_sensor.relay", "on")
        c._refresh_shed_signal()
        p = c._shed_signal_payload()
        assert p["shed_signal_active"] is True
        assert p["shed_signal_cap_kw"] == 4.2
        first = p["shed_signal_since"]
        assert first
        c._refresh_shed_signal()                       # still on: same since
        assert c._shed_signal_payload()["shed_signal_since"] == first
        hass.states.async_set("binary_sensor.relay", "off")
        c._refresh_shed_signal()
        p = c._shed_signal_payload()
        assert p["shed_signal_active"] is False and p["shed_signal_since"] is None


class TestTheDeviceFlagIsPersisted:
    def test_the_goal_reaches_the_live_device(self, hass):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry as DeviceRegistry,
        )
        assert "behind_operator_relay" in DeviceRegistry.GOAL_PROPERTIES
        d = _boiler(hass, behind=False)
        reg = DeviceRegistry.__new__(DeviceRegistry)
        reg._device_goals = {"boiler": {"behind_operator_relay": "True"}}
        reg._apply_goals(d)
        assert d.behind_operator_relay is True
        reg._device_goals = {"boiler": {"behind_operator_relay": "False"}}
        reg._apply_goals(d)
        assert d.behind_operator_relay is False
