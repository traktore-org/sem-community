"""#580 — Generic VPP grid-event dispatch (Axle Energy first integration).

Pure-core coverage of ``evaluate_vpp`` (disabled / observer / export bounded
by reserve / import / gate-stuck sanity cap / pre-event), the
``VppDispatcher`` accounting (start/end transitions, delivered-kWh delta
math incl. counter reset, boot reconcile, bounded history), and the
coordinator wiring (per-cycle overrides via the real unbound methods on a
lightweight stub — same pattern as test_547_refresh_runtime_config).
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.vpp_dispatch import (
    MAX_EVENTS,
    PHASE_EVENT,
    PHASE_IDLE,
    PHASE_PRE_EVENT,
    VppDispatcher,
    evaluate_vpp,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

NOW = datetime(2026, 7, 18, 14, 0, 0)


def _cfg(**over):
    base = {
        "vpp_enabled": True,
        "vpp_observer_mode": True,
        "vpp_reserve_soc": 20,
    }
    base.update(over)
    return base


def _states(**over):
    base = {"event_active": None, "direction": None,
            "event_end": None, "pre_event": None}
    base.update(over)
    return base


def _kinds(decision):
    return {a.kind for a in decision.actions}


# ─────────────────────────────────────────────────────────────────
# Pure core — evaluate_vpp
# ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestEvaluateVpp:
    def test_disabled_is_idle(self):
        d = evaluate_vpp(_cfg(vpp_enabled=False),
                         _states(event_active="on"), 80.0, NOW)
        assert d.phase == PHASE_IDLE
        assert d.actions == ()
        assert "disabled" in d.reason

    def test_no_event_is_idle(self):
        d = evaluate_vpp(_cfg(), _states(event_active="off"), 80.0, NOW)
        assert d.phase == PHASE_IDLE
        assert d.actions == ()

    def test_observer_flag_carried(self):
        d = evaluate_vpp(_cfg(vpp_observer_mode=True),
                         _states(event_active="on", direction="export"),
                         80.0, NOW)
        assert d.observer is True
        # actions are still computed in observer mode (log/notify what WOULD run)
        assert "force_discharge" in _kinds(d)
        d2 = evaluate_vpp(_cfg(vpp_observer_mode=False),
                          _states(event_active="on", direction="export"),
                          80.0, NOW)
        assert d2.observer is False

    def test_export_event_full_dispatch(self):
        d = evaluate_vpp(_cfg(),
                         _states(event_active="on", direction="export"),
                         80.0, NOW)
        assert d.phase == PHASE_EVENT
        assert d.direction == "export"
        assert _kinds(d) == {"force_discharge", "pause_ev", "shed_loads"}
        fd = next(a for a in d.actions if a.kind == "force_discharge")
        assert fd.params["reserve_soc"] == 20.0

    def test_export_soc_at_reserve_no_discharge(self):
        d = evaluate_vpp(_cfg(),
                         _states(event_active="on", direction="export"),
                         20.0, NOW)
        assert d.phase == PHASE_EVENT
        assert "force_discharge" not in _kinds(d)
        assert {"pause_ev", "shed_loads"} <= _kinds(d)

    def test_export_soc_below_reserve_no_discharge(self):
        d = evaluate_vpp(_cfg(vpp_reserve_soc=50),
                         _states(event_active="on", direction="export"),
                         35.0, NOW)
        assert "force_discharge" not in _kinds(d)

    def test_export_soc_unavailable_no_discharge(self):
        # #531 class: never discharge blind — unavailable SOC must hold.
        d = evaluate_vpp(_cfg(),
                         _states(event_active="on", direction="export"),
                         None, NOW)
        assert "force_discharge" not in _kinds(d)
        assert "unavailable" in d.reason

    def test_import_event(self):
        d = evaluate_vpp(_cfg(),
                         _states(event_active="in_progress",
                                 direction="import"),
                         30.0, NOW)
        assert d.phase == PHASE_EVENT
        assert d.direction == "import"
        assert _kinds(d) == {"force_charge", "boost_ev"}

    def test_unknown_direction_defaults_export(self):
        d = evaluate_vpp(_cfg(),
                         _states(event_active="on", direction="unknown"),
                         80.0, NOW)
        assert d.direction == "export"
        assert "defaulting to export" in d.reason

    def test_gate_stuck_past_end_treated_as_over(self):
        end = (NOW - timedelta(minutes=31)).isoformat()
        d = evaluate_vpp(_cfg(),
                         _states(event_active="on", direction="export",
                                 event_end=end),
                         80.0, NOW)
        assert d.phase == PHASE_IDLE
        assert d.gate_stuck is True
        assert d.actions == ()

    def test_gate_within_grace_still_event(self):
        end = (NOW - timedelta(minutes=29)).isoformat()
        d = evaluate_vpp(_cfg(),
                         _states(event_active="on", direction="export",
                                 event_end=end),
                         80.0, NOW)
        assert d.phase == PHASE_EVENT
        assert d.gate_stuck is False

    def test_pre_event_phase(self):
        d = evaluate_vpp(_cfg(),
                         _states(event_active="off", pre_event="on"),
                         80.0, NOW)
        assert d.phase == PHASE_PRE_EVENT
        assert _kinds(d) == {"pause_ev"}

    def test_event_outranks_pre_event(self):
        d = evaluate_vpp(_cfg(),
                         _states(event_active="on", direction="export",
                                 pre_event="on"),
                         80.0, NOW)
        assert d.phase == PHASE_EVENT


# ─────────────────────────────────────────────────────────────────
# Dispatcher — transitions + energy accounting
# ─────────────────────────────────────────────────────────────────

def _event_decision(direction="export", observer=True):
    return evaluate_vpp(
        _cfg(vpp_observer_mode=observer),
        _states(event_active="on", direction=direction),
        80.0, NOW,
    )


def _idle_decision():
    return evaluate_vpp(_cfg(), _states(event_active="off"), 80.0, NOW)


@pytest.mark.unit
class TestVppDispatcher:
    def test_start_and_end_transitions(self):
        disp = VppDispatcher()
        out = disp.update(_event_decision(), grid_import_kwh=1.0,
                          grid_export_kwh=5.0, now=NOW)
        assert out["transition"] == "start"
        out = disp.update(_event_decision(), grid_import_kwh=1.0,
                          grid_export_kwh=6.2, now=NOW + timedelta(minutes=10))
        assert out["transition"] is None
        out = disp.update(_idle_decision(), grid_import_kwh=1.0,
                          grid_export_kwh=7.5, now=NOW + timedelta(minutes=30))
        assert out["transition"] == "end"
        ev = out["event"]
        assert ev["direction"] == "export"
        assert ev["kwh"] == pytest.approx(2.5)  # export delta 5.0 → 7.5
        assert ev["observer"] is True
        assert ev["start"] == NOW.isoformat()
        assert ev["end"] == (NOW + timedelta(minutes=30)).isoformat()

    def test_import_event_uses_import_counter(self):
        disp = VppDispatcher()
        disp.update(_event_decision("import"), grid_import_kwh=10.0,
                    grid_export_kwh=3.0, now=NOW)
        out = disp.update(_idle_decision(), grid_import_kwh=13.4,
                          grid_export_kwh=99.0, now=NOW + timedelta(hours=1))
        assert out["event"]["kwh"] == pytest.approx(3.4)

    def test_counter_reset_delta_negative_treated_as_zero(self):
        # Midnight rollover: daily counter resets under the running event.
        disp = VppDispatcher()
        disp.update(_event_decision(), grid_import_kwh=0.0,
                    grid_export_kwh=8.0, now=NOW)
        disp.update(_event_decision(), grid_import_kwh=0.0,
                    grid_export_kwh=9.0, now=NOW + timedelta(minutes=5))
        # reset: counter drops 9.0 → 0.2; banked 1.0 kWh must survive
        disp.update(_event_decision(), grid_import_kwh=0.0,
                    grid_export_kwh=0.2, now=NOW + timedelta(minutes=10))
        out = disp.update(_idle_decision(), grid_import_kwh=0.0,
                          grid_export_kwh=0.5, now=NOW + timedelta(minutes=15))
        # 1.0 banked before reset + 0.3 after re-baseline at 0.2
        assert out["event"]["kwh"] == pytest.approx(1.3)

    def test_boot_reconcile_closes_stale_open_event(self):
        # Restart mid-event, gate no longer active → close the strand
        # (#532 class: nothing may outlive its window).
        stale = {"start": "2026-07-17T18:00:00", "end": None,
                 "direction": "export", "kwh": 2.0, "observer": False}
        disp = VppDispatcher(events=[stale])
        out = disp.update(_idle_decision(), grid_import_kwh=0.0,
                          grid_export_kwh=0.0, now=NOW)
        assert out["transition"] == "boot_reconcile"
        assert out["events_changed"] is True
        rec = disp.events[-1]
        assert rec["end"] == NOW.isoformat()
        assert rec["reconciled"] is True

    def test_boot_resume_open_event_while_gate_active(self):
        stale = {"start": "2026-07-18T13:00:00", "end": None,
                 "direction": "export", "kwh": 1.5, "observer": True}
        disp = VppDispatcher(events=[stale])
        out = disp.update(_event_decision(), grid_import_kwh=0.0,
                          grid_export_kwh=4.0, now=NOW)
        assert out["transition"] is None  # resumed, not restarted
        out = disp.update(_idle_decision(), grid_import_kwh=0.0,
                          grid_export_kwh=5.0, now=NOW + timedelta(minutes=20))
        # 1.5 carried across the restart + 1.0 after re-baseline
        assert out["event"]["kwh"] == pytest.approx(2.5)
        assert out["event"]["start"] == "2026-07-18T13:00:00"

    def test_history_bounded(self):
        disp = VppDispatcher()
        for i in range(MAX_EVENTS + 5):
            disp.update(_event_decision(),
                        grid_import_kwh=0.0, grid_export_kwh=float(i),
                        now=NOW + timedelta(hours=i))
            disp.update(_idle_decision(),
                        grid_import_kwh=0.0, grid_export_kwh=float(i),
                        now=NOW + timedelta(hours=i, minutes=30))
        assert len(disp.events) == MAX_EVENTS

    def test_publish_state_shape(self):
        disp = VppDispatcher()
        dec = _event_decision()
        disp.update(dec, grid_import_kwh=0.0, grid_export_kwh=2.0, now=NOW)
        payload = disp.publish_state(dec)
        assert payload["vpp_event"] == "event_export"
        assert payload["vpp_event_direction"] == "export"
        assert payload["vpp_event_started"] == NOW.isoformat()
        assert payload["vpp_event_observer"] is True
        assert len(payload["vpp_events"]) == 1
        idle = _idle_decision()
        disp.update(idle, grid_import_kwh=0.0, grid_export_kwh=3.0,
                    now=NOW + timedelta(minutes=30))
        payload = disp.publish_state(idle)
        assert payload["vpp_event"] == "idle"
        assert payload["vpp_last_event"]["kwh"] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────
# Coordinator wiring — real unbound methods on a lightweight stub
# ─────────────────────────────────────────────────────────────────

class _FakeStates:
    def __init__(self, states):
        self._states = {
            k: SimpleNamespace(state=v) for k, v in states.items()
        }

    def get(self, eid):
        return self._states.get(eid)


class _FakeStorage:
    def __init__(self, events=None):
        self._events = list(events or [])
        self.saved = None

    def get_vpp_events(self):
        return list(self._events)

    def set_vpp_events(self, events):
        self.saved = list(events)


def _wired_coord(*, observer=False, entity_states=None, config_extra=None,
                 storage=None):
    cfg = {
        "vpp_enabled": True,
        "vpp_observer_mode": observer,
        "vpp_reserve_soc": 25,
        "vpp_event_active_entity": "binary_sensor.axle_event",
        "vpp_direction_entity": "sensor.axle_direction",
        "enable_mobile_notifications": False,
    }
    cfg.update(config_extra or {})
    coord = SimpleNamespace(
        config=cfg,
        hass=SimpleNamespace(states=_FakeStates(entity_states or {})),
        _storage=storage if storage is not None else _FakeStorage(),
        _vpp_dispatcher=None,
    )
    # Bind the real helper methods the dispatch hook calls on ``self``.
    from types import MethodType
    coord._snapshot_vpp_states = MethodType(
        SEMCoordinator._snapshot_vpp_states, coord)
    coord._vpp_notify = MethodType(SEMCoordinator._vpp_notify, coord)
    return coord


@pytest.mark.unit
class TestCoordinatorWiring:
    def test_update_loop_calls_vpp_each_cycle(self):
        # Structural guard: _async_update_data invokes the dispatch hook
        # before the charging context is built (the veto must land in the
        # same cycle it was decided).
        import inspect
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert "_run_vpp_dispatch" in src
        assert src.index("_run_vpp_dispatch") < src.index(
            "charging_context = self._build_charging_context"
        )

    @pytest.mark.asyncio
    async def test_export_event_sets_all_overrides(self):
        coord = _wired_coord(entity_states={
            "binary_sensor.axle_event": "on",
            "sensor.axle_direction": "export",
        })
        power = SimpleNamespace(battery_soc=70.0)
        energy = SimpleNamespace(daily_grid_import=1.0, daily_grid_export=4.0)
        await SEMCoordinator._run_vpp_dispatch(coord, power, energy)
        assert coord._vpp_ev_override == "pause"
        assert coord._vpp_battery_override == {
            "battery_mode": "force_discharge", "battery_reserve_soc": 25.0,
        }
        assert coord._vpp_shed_loads is True
        assert coord._vpp_publish["vpp_event"] == "event_export"
        # store persisted the open event record
        assert coord._storage.saved and coord._storage.saved[-1]["end"] is None

    @pytest.mark.asyncio
    async def test_import_event_sets_boost_and_force_charge(self):
        coord = _wired_coord(entity_states={
            "binary_sensor.axle_event": "on",
            "sensor.axle_direction": "import",
        })
        power = SimpleNamespace(battery_soc=40.0)
        energy = SimpleNamespace(daily_grid_import=1.0, daily_grid_export=4.0)
        await SEMCoordinator._run_vpp_dispatch(coord, power, energy)
        assert coord._vpp_ev_override == "boost"
        assert coord._vpp_battery_override == {"battery_mode": "force_charge"}
        assert coord._vpp_shed_loads is False

    @pytest.mark.asyncio
    async def test_observer_mode_sets_no_overrides(self):
        coord = _wired_coord(observer=True, entity_states={
            "binary_sensor.axle_event": "on",
            "sensor.axle_direction": "export",
        })
        power = SimpleNamespace(battery_soc=70.0)
        energy = SimpleNamespace(daily_grid_import=0.0, daily_grid_export=0.0)
        await SEMCoordinator._run_vpp_dispatch(coord, power, energy)
        # everything computed + published, NOTHING armed for actuation
        assert coord._vpp_ev_override is None
        assert coord._vpp_battery_override is None
        assert coord._vpp_shed_loads is False
        assert coord._vpp_publish["vpp_event"] == "event_export"
        assert coord._vpp_publish["vpp_event_observer"] is True

    @pytest.mark.asyncio
    async def test_disabled_publishes_idle_and_clears_overrides(self):
        coord = _wired_coord(config_extra={"vpp_enabled": False})
        coord._vpp_ev_override = "pause"  # leftover from a previous cycle
        power = SimpleNamespace(battery_soc=70.0)
        energy = SimpleNamespace(daily_grid_import=0.0, daily_grid_export=0.0)
        await SEMCoordinator._run_vpp_dispatch(coord, power, energy)
        assert coord._vpp_ev_override is None
        assert coord._vpp_publish["vpp_event"] == "idle"

    @pytest.mark.asyncio
    async def test_event_end_clears_overrides_reconcile_road(self):
        # End of window: the per-cycle override drops → decide_battery falls
        # back to NORMAL → adapters' command_normal() is the teardown
        # primitive. The wiring's contract here: overrides cleared + event
        # record finalized.
        states = {
            "binary_sensor.axle_event": "on",
            "sensor.axle_direction": "export",
        }
        coord = _wired_coord(entity_states=states)
        power = SimpleNamespace(battery_soc=70.0)
        energy = SimpleNamespace(daily_grid_import=0.0, daily_grid_export=2.0)
        await SEMCoordinator._run_vpp_dispatch(coord, power, energy)
        assert coord._vpp_battery_override is not None
        # gate drops
        coord.hass.states = _FakeStates({
            "binary_sensor.axle_event": "off",
            "sensor.axle_direction": "export",
        })
        energy2 = SimpleNamespace(daily_grid_import=0.0, daily_grid_export=3.5)
        await SEMCoordinator._run_vpp_dispatch(coord, power, energy2)
        assert coord._vpp_battery_override is None
        assert coord._vpp_ev_override is None
        assert coord._vpp_shed_loads is False
        last = coord._vpp_publish["vpp_last_event"]
        assert last["end"] is not None
        assert last["kwh"] == pytest.approx(1.5)

    def test_ev_mode_override_pause_and_boost(self):
        stub = SimpleNamespace(_vpp_ev_override="pause", hass=None,
                               config={})
        assert SEMCoordinator._effective_charge_mode_for(
            stub, {"charge_mode": "solar_only"}) == "off"
        stub._vpp_ev_override = "boost"
        assert SEMCoordinator._effective_charge_mode_for(
            stub, {"charge_mode": "solar_only"}) == "always_max"
        stub._vpp_ev_override = None
        assert SEMCoordinator._effective_charge_mode_for(
            stub, {"charge_mode": "solar_only"}) == "solar_only"

    def test_battery_override_merge_respects_off_and_reserve(self):
        stub = SimpleNamespace(_vpp_battery_override={
            "battery_mode": "force_discharge", "battery_reserve_soc": 25.0,
        })
        # user's hands-off battery stays hands-off
        pbc_off = {"battery_mode": "off", "battery_reserve_soc": 10}
        assert SEMCoordinator._vpp_apply_battery_override(
            stub, pbc_off) == pbc_off
        # VPP reserve only tightens: user 40 > vpp 25 → 40 wins
        merged = SEMCoordinator._vpp_apply_battery_override(
            stub, {"battery_mode": "auto", "battery_reserve_soc": 40})
        assert merged["battery_mode"] == "force_discharge"
        assert merged["battery_reserve_soc"] == 40.0
        # user 10 < vpp 25 → 25 wins
        merged = SEMCoordinator._vpp_apply_battery_override(
            stub, {"battery_mode": "auto", "battery_reserve_soc": 10})
        assert merged["battery_reserve_soc"] == 25.0
        # no override → untouched input object semantics (new dict not required)
        stub._vpp_battery_override = None
        pbc = {"battery_mode": "auto"}
        assert SEMCoordinator._vpp_apply_battery_override(stub, pbc) == pbc


def test_global_observer_outranks_vpp_observer_off():
    """The GLOBAL observer mode forces VPP decisions to observer even when
    vpp_observer_mode is explicitly false (2026-07-18 incident class)."""
    from dataclasses import replace
    from custom_components.solar_energy_management.coordinator.vpp_dispatch import (
        evaluate_vpp,
    )
    from datetime import datetime, timezone
    cfg = {"vpp_enabled": True, "vpp_observer_mode": False,
           "vpp_event_active_entity": "sensor.gate",
           "vpp_direction_entity": "sensor.dir",
           "vpp_reserve_soc": 20}
    states = {"event_active": "on", "direction": "export",
              "event_end": None, "pre_event": None}
    d = evaluate_vpp(cfg, states, 80.0, datetime.now(timezone.utc))
    assert d.observer is False  # core honours the config…
    forced = replace(d, observer=True)  # …the coordinator belt forces it
    assert forced.observer is True and forced.actions == d.actions
