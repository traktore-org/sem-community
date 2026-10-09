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
        from .ast_contracts import calls
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        assert calls(SEMCoordinator._async_update_data, "_refresh_shed_signal")
        assert calls(SEMCoordinator._refresh_shed_signal, "read_shed_signal")

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


# ── Task 7: Germany — the operator's limit lowers the one grid limit ──
import math  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from custom_components.solar_energy_management.features.load_management import (  # noqa: E402
    LoadManagementCoordinator,
)


def _ev_host(config, sig=None, lm=None):
    from custom_components.solar_energy_management.coordinator.ev_control import (
        EVControlMixin,
    )

    class _Host(EVControlMixin):
        def __init__(self, cfg):
            self.config = cfg
            self._load_manager = lm
            self._shed_signal = sig or INERT

    return _Host(config)


def _lm(**opts):
    entry = MagicMock()
    entry.data = {}
    entry.options = {"target_peak_limit": 8.0, "warning_peak_level": 7.5,
                     "emergency_peak_level": 9.0, **opts}
    hass = MagicMock()
    lm = LoadManagementCoordinator.__new__(LoadManagementCoordinator)
    LoadManagementCoordinator.__init__(lm, hass, entry)
    return lm, hass


class TestTheOperatorCapOnTheEV:
    def test_the_cap_lowers_the_limit(self):
        h = _ev_host({"target_peak_limit": 8.0}, _ON)
        assert h._get_peak_limit_w() == 4200.0
        assert h._planning_peak_w() == 4000.0

    def test_the_cap_applies_when_unlimited(self):
        h = _ev_host({"target_peak_limit": 8.0, "peak_limit_unlimited": True}, _ON)
        assert h._get_peak_limit_w() == 4200.0

    def test_a_lower_user_limit_stays(self):
        h = _ev_host({"target_peak_limit": 3.0}, _ON)
        assert h._get_peak_limit_w() == 3000.0

    def test_no_signal_is_todays_behaviour(self):
        assert _ev_host({"target_peak_limit": 8.0})._get_peak_limit_w() == 8000.0
        assert _ev_host({"target_peak_limit": 8.0,
                         "peak_limit_unlimited": True})._get_peak_limit_w() == math.inf
        off = ShedSignal(False, "binary_sensor.relay", "off", None)
        assert _ev_host({"target_peak_limit": 8.0}, off)._get_peak_limit_w() == 8000.0

    def test_the_published_limit_stays_the_users(self):
        """The slider must never jump under the user's finger."""
        h = _ev_host({"target_peak_limit": 8.0}, _ON)
        assert h._target_peak_limit_kw() == 8.0


class TestTheOperatorCapOnTheLoadManager:
    def test_it_sheds_against_the_cap(self):
        lm, _ = _lm()
        assert lm._determine_load_management_state(4.5, 4.5) != "shedding"
        lm.set_operator_cap(4.2)
        assert lm._active_target_kw() == 4.2
        assert lm._determine_load_management_state(4.5, 4.5) == "shedding"
        lm.set_operator_cap(None)
        assert lm._active_target_kw() == 8.0

    def test_unlimited_still_defends_the_cap(self):
        lm, _ = _lm(peak_limit_unlimited=True)
        assert lm._determine_load_management_state(6.0, 6.0) == "normal"
        lm.set_operator_cap(4.2)
        assert lm._determine_load_management_state(6.0, 6.0) != "normal"

    def test_the_cap_is_never_saved(self):
        lm, hass = _lm()
        lm.set_operator_cap(4.2)
        lm.set_operator_cap(None)
        lm.set_operator_cap(4.2)
        hass.config_entries.async_update_entry.assert_not_called()
        assert lm._target_peak_limit == 8.0
        assert lm.get_load_management_data()["target_peak_limit"] == 8.0

    def test_the_emergency_level_stays_the_users(self):
        """House fuse first: the cap never moves the emergency level."""
        lm, _ = _lm()
        lm.set_operator_cap(4.2)
        warning, emergency = lm._effective_levels()
        assert emergency == 9.0
        assert warning < 4.2


class TestTheSlotCeiling:
    def _coord(self, lm=None, sig=None, config=None):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.config = config or {"target_peak_limit": 8.0}
        c._load_manager = lm
        c._shed_signal = sig or INERT
        return c

    def test_the_slot_reads_the_cap(self):
        lm, _ = _lm()
        c = self._coord(lm, _ON)
        lm.set_operator_cap(4.2)
        assert c._slot_ceiling_kw() == 4.2

    def test_the_slot_without_a_cap_is_the_users(self):
        lm, _ = _lm()
        assert self._coord(lm)._slot_ceiling_kw() == 8.0

    def test_unlimited_without_a_cap_has_no_slot(self):
        lm, _ = _lm(peak_limit_unlimited=True)
        assert self._coord(lm)._slot_ceiling_kw() is None

    def test_unlimited_with_a_cap_has_the_caps_slot(self):
        lm, _ = _lm(peak_limit_unlimited=True)
        lm.set_operator_cap(4.2)
        assert self._coord(lm, _ON)._slot_ceiling_kw() == 4.2

    def test_no_load_manager_still_obeys_the_cap(self):
        assert self._coord(None, _ON)._slot_ceiling_kw() == 4.2
        assert self._coord(None)._slot_ceiling_kw() is None

    def test_the_cycle_hands_the_cap_to_the_load_manager(self, hass):
        lm, _ = _lm()
        c = self._coord(lm)
        c.hass = hass
        c.config = {"shed_signal_entity": "binary_sensor.relay",
                    "shed_signal_limit": 4.2}
        c._surplus_controller = SurplusController(hass)
        c._shed_signal_since = None
        hass.states.async_set("binary_sensor.relay", "on")
        c._refresh_shed_signal()
        assert lm._active_target_kw() == 4.2
        hass.states.async_set("binary_sensor.relay", "off")
        c._refresh_shed_signal()
        assert lm._active_target_kw() == 8.0


class TestEveryLimitReadGoesThroughTheAccessor:
    """(#1021) The operator's limit works only if every decision reads the
    limit through the one accessor. A bare read of the saved number sheds,
    sizes or allows against the user's limit while the rest obeys the cap."""

    _ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent

    def _reads(self, rel, attr):
        import ast
        tree = ast.parse((self._ROOT / rel).read_text(encoding="utf-8"))
        out = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(fn):
                if (isinstance(n, ast.Attribute) and n.attr == attr
                        and isinstance(n.ctx, ast.Load)):
                    out.append(fn.name)
                if (isinstance(n, ast.Constant) and n.value == attr):
                    out.append(fn.name)
        return set(out)

    def test_the_load_manager_reads_the_saved_limit_in_named_places(self):
        allowed = {
            "_active_target_kw", "_limit_active",
            # the setting itself: published and persisted as the user's
            "get_load_management_data", "update_target_peak_limit",
            "update_warning_peak_level", "update_emergency_peak_level",
            "__init__",
            # the startup log line names the saved limit
            "async_initialize",
        }
        for attr in ("_target_peak_limit", "_peak_unlimited"):
            bad = self._reads("features/load_management.py", attr) - allowed
            assert not bad, (attr, sorted(bad))

    def test_the_coordinator_never_reads_the_load_managers_fields(self):
        for attr in ("_target_peak_limit", "_peak_unlimited"):
            assert not self._reads("coordinator/coordinator.py", attr), attr

    def test_the_ev_sizing_reads_the_accessor(self):
        from .ast_contracts import calls
        from custom_components.solar_energy_management.coordinator.ev_control import (
            EVControlMixin,
        )
        assert calls(EVControlMixin._get_peak_limit_w, "_operator_cap_kw")


class TestThePlanningFallbackKeepsTheCap:
    """(#1021 review) ``_planning_peak_w`` falls back to the saved option
    when the live limit cannot be read. That fallback read the user's raw
    limit, so the operator's cap vanished from the plan on exactly the
    cycle the normal path failed."""

    @staticmethod
    def _broken(host):
        def _raise():
            raise AttributeError("no load manager yet")
        host._get_peak_limit_w = _raise
        return host

    def test_the_cap_holds_when_the_normal_path_raises(self):
        h = self._broken(_ev_host({"target_peak_limit": 8.0,
                                   "peak_hysteresis": 0.2}, _ON))
        assert h._planning_peak_w() == 4200.0 - 200.0

    def test_the_cap_holds_with_no_saved_limit(self):
        h = self._broken(_ev_host({"peak_hysteresis": 0.2}, _ON))
        assert h._planning_peak_w() == 4200.0 - 200.0

    def test_without_a_relay_the_fallback_is_the_saved_limit(self):
        h = self._broken(_ev_host({"target_peak_limit": 8.0,
                                   "peak_hysteresis": 0.2}))
        assert h._planning_peak_w() == 8000.0 - 200.0


class TestNoModuleReadsTheSavedLimitBehindTheAccessor:
    """(#1021 review) The accessor test above scanned two files. Every
    module under coordinator/ and features/ is scanned here: a read of the
    saved limit is allowed only in the accessor itself and in the places
    that publish the USER's setting."""

    _ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
    _NAMES = ("target_peak_limit", "peak_limit_unlimited",
              "_target_peak_limit", "_peak_unlimited",
              "_target_peak_limit_kw", "_peak_limit_unlimited")
    _ALLOWED = {
        # the accessor and its two halves; the fallback is pinned below
        "coordinator/ev_control.py": {
            "_get_peak_limit_w", "_target_peak_limit_kw",
            "_peak_limit_unlimited", "_planning_peak_w"},
        # publishes the user's own setting (sensor + Control tab)
        "coordinator/coordinator.py": {"_build_load_management_data"},
        "coordinator/types.py": {"to_dict"},
        # the setting itself; pinned by the load-manager test above
        "features/load_management.py": None,
    }

    def _reads(self, path):
        import ast
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(fn):
                if (isinstance(n, ast.Attribute) and n.attr in self._NAMES
                        and isinstance(n.ctx, ast.Load)):
                    out.add(fn.name)
                elif isinstance(n, ast.Constant) and n.value in self._NAMES:
                    out.add(fn.name)
        return out

    def test_every_module_is_scanned(self):
        bad = {}
        files = sorted([*(self._ROOT / "coordinator").rglob("*.py"),
                        *(self._ROOT / "features").rglob("*.py")])
        assert len(files) > 50, "the scan must cover the whole package"
        for path in files:
            rel = path.relative_to(self._ROOT).as_posix()
            allowed = self._ALLOWED.get(rel, set())
            if allowed is None:
                continue
            extra = self._reads(path) - allowed
            if extra:
                bad[rel] = sorted(extra)
        assert not bad, bad

    def test_the_named_battery_and_surplus_modules_are_in_the_scan(self):
        for rel in ("coordinator/ev_control.py", "coordinator/decide_battery.py",
                    "coordinator/surplus_controller.py", "coordinator/decide.py",
                    "coordinator/peak_guard.py"):
            assert (self._ROOT / rel).is_file(), rel

    def test_the_planning_fallback_reads_the_cap(self):
        from .ast_contracts import calls
        from custom_components.solar_energy_management.coordinator.ev_control import (
            EVControlMixin,
        )
        assert calls(EVControlMixin._planning_peak_w, "_operator_cap_kw")
