"""Tests for the SEM layered-trace observability collector (2026-07-11).

Spec: docs/superpowers/specs/2026-07-11-sem-layered-trace-observability-design.md
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.cycle_trace import (
    LayerStatus, LayerRecord, SubsystemTrace, CycleTrace, TraceCollector,
)


@pytest.mark.unit
class TestLayerAndSubsystem:
    def test_layer_record_to_dict(self):
        r = LayerRecord(LayerStatus.BLOCKED, "battery below reserve", {"soc": 25})
        assert r.to_dict() == {
            "status": "blocked",
            "detail": "battery below reserve",
            "data": {"soc": 25},
        }

    def test_subsystem_get_or_create_is_stable(self):
        t = CycleTrace(seq=1)
        a = t.subsystem("ev:keba")
        b = t.subsystem("ev:keba")
        assert a is b                      # same object, not recreated
        a.process = LayerRecord(LayerStatus.OK, "charge 16A")
        assert t.subsystem("ev:keba").process.detail == "charge 16A"

    def test_cycle_to_dict_shape(self):
        t = CycleTrace(seq=7, wall_iso="2026-07-11T10:00:00")
        st = t.subsystem("battery")
        st.management = LayerRecord(LayerStatus.OK, "zone 4")
        d = t.to_dict()
        assert d["seq"] == 7 and d["wall"] == "2026-07-11T10:00:00"
        assert d["subsystems"]["battery"]["management"]["detail"] == "zone 4"


@pytest.mark.unit
class TestMismatch:
    def _acting_but_off(self):
        st = SubsystemTrace()
        st.process = LayerRecord(LayerStatus.OK, "charge 16A", {"commanded_amps": 16})
        st.integration = LayerRecord(
            LayerStatus.DEGRADED, "observed 0W",
            {"action": "set_current", "observed_w": 0, "match": False},
        )
        return st

    def test_mismatch_fires_when_acting_but_observed_disagrees(self):
        assert self._acting_but_off().has_mismatch is True

    def test_no_mismatch_when_process_idle(self):
        # process deliberately idle → observed 0 is EXPECTED, not a fault
        st = SubsystemTrace()
        st.process = LayerRecord(LayerStatus.IDLE, "surplus < min")
        st.integration = LayerRecord(LayerStatus.OK, "disabled", {"match": True})
        assert st.has_mismatch is False

    def test_no_mismatch_when_match_true(self):
        st = SubsystemTrace()
        st.process = LayerRecord(LayerStatus.OK, "charge 16A")
        st.integration = LayerRecord(LayerStatus.OK, "drawing", {"match": True})
        assert st.has_mismatch is False

    def test_no_mismatch_when_match_absent(self):
        # match=None (unobservable) is not a fault
        st = SubsystemTrace()
        st.process = LayerRecord(LayerStatus.OK, "charge 16A")
        st.integration = LayerRecord(LayerStatus.OK, "commanded", {"match": None})
        assert st.has_mismatch is False


@pytest.mark.unit
class TestCollector:
    def test_begin_commit_and_ring_buffer_cap(self):
        c = TraceCollector(maxlen=3)
        for i in range(5):
            t = c.begin(wall_iso=f"t{i}")
            t.subsystem("ev:keba").process = LayerRecord(LayerStatus.OK, f"cycle {i}")
            c.commit()
        recent = c.recent()
        assert len(recent) == 3                      # capped at maxlen
        assert [r["seq"] for r in recent] == [3, 4, 5]  # monotonic, last 3

    def test_recent_n_slices_the_tail(self):
        c = TraceCollector(maxlen=10)
        for _ in range(6):
            c.begin(); c.commit()
        assert [r["seq"] for r in c.recent(2)] == [5, 6]

    def test_current_is_none_outside_window(self):
        c = TraceCollector()
        assert c.current() is None
        t = c.begin()
        assert c.current() is t
        c.commit()
        assert c.current() is None

    def test_latest_mismatch_surfaces_the_flap(self):
        c = TraceCollector()
        # a clean cycle, then a flap cycle
        c.begin(); c.commit()
        t = c.begin()
        st = t.subsystem("ev:keba")
        st.process = LayerRecord(LayerStatus.OK, "charge 16A")
        st.integration = LayerRecord(LayerStatus.DEGRADED, "observed 0W",
                                     {"match": False})
        c.commit()
        m = c.latest_mismatch()
        assert m is not None
        assert m["subsystem"] == "ev:keba"
        assert m["integration"]["data"]["match"] is False

    def test_latest_mismatch_none_when_healthy(self):
        c = TraceCollector()
        t = c.begin()
        t.subsystem("ev:keba").integration = LayerRecord(
            LayerStatus.OK, "drawing", {"match": True})
        c.commit()
        assert c.latest_mismatch() is None


@pytest.mark.unit
class TestHealthDebounce:
    def _flap_cycle(self, c):
        t = c.begin()
        st = t.subsystem("ev")
        st.process = LayerRecord(LayerStatus.OK, "charge 16A")
        st.integration = LayerRecord(LayerStatus.DEGRADED, "0W", {"match": False})
        c.commit()

    def _healthy_cycle(self, c):
        t = c.begin()
        st = t.subsystem("ev")
        st.process = LayerRecord(LayerStatus.OK, "charge 16A")
        st.integration = LayerRecord(LayerStatus.OK, "drawing", {"match": True})
        c.commit()

    def test_single_cycle_mismatch_does_not_alarm(self):
        c = TraceCollector()
        self._flap_cycle(c)
        assert c.health(threshold=3)["ok"] is True   # 1 < 3

    def test_persistent_mismatch_alarms(self):
        c = TraceCollector()
        for _ in range(3):
            self._flap_cycle(c)
        h = c.health(threshold=3)
        assert h["ok"] is False and h["subsystem"] == "ev" and h["cycles"] == 3

    def test_recovery_clears_the_streak(self):
        c = TraceCollector()
        for _ in range(4):
            self._flap_cycle(c)
        assert c.health()["ok"] is False
        self._healthy_cycle(c)                        # one good cycle
        assert c.health()["ok"] is True               # streak reset

    def test_two_cycles_below_threshold_do_not_alarm(self):
        c = TraceCollector()
        for _ in range(2):
            self._flap_cycle(c)
        assert c.health(threshold=3)["ok"] is True    # exactly 2 < 3

    def test_streak_resets_fully_between_flap_bursts(self):
        # 2 flaps, one recovery, 2 more flaps — the resumed streak starts at 0,
        # so it must NOT alarm at threshold 3 (the recovery didn't leave a
        # residual count).
        c = TraceCollector()
        self._flap_cycle(c); self._flap_cycle(c)
        self._healthy_cycle(c)
        self._flap_cycle(c); self._flap_cycle(c)
        assert c.health(threshold=3)["ok"] is True

    def test_non_default_threshold_one_alarms_immediately(self):
        c = TraceCollector()
        self._flap_cycle(c)
        assert c.health(threshold=1)["ok"] is False

    def test_worst_subsystem_is_the_longest_streak(self):
        # ev mismatched 3×, battery 5× → health reports battery (the worst).
        c = TraceCollector()
        for i in range(5):
            t = c.begin()
            bat = t.subsystem("battery")
            bat.process = LayerRecord(LayerStatus.OK, "force_charge")
            bat.integration = LayerRecord(LayerStatus.DEGRADED, "0W", {"match": False})
            if i < 3:
                ev = t.subsystem("ev")
                ev.process = LayerRecord(LayerStatus.OK, "16A")
                ev.integration = LayerRecord(LayerStatus.DEGRADED, "0W", {"match": False})
            c.commit()
        h = c.health(threshold=3)
        assert h["ok"] is False and h["subsystem"] == "battery" and h["cycles"] == 5

    def test_commit_without_begin_is_a_noop(self):
        c = TraceCollector()
        c.commit()                                    # never began a cycle
        assert c.recent() == [] and c.health()["ok"] is True


# ── #576: Today's Plan device rows ────────────────────────────────────────
from datetime import datetime, timedelta, timezone  # noqa: E402
from custom_components.solar_energy_management.coordinator.today_plan import (  # noqa: E402
    compose_today_plan,
)


def _now():
    return datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc)


class TestTodayPlanDeviceRows:
    """#576 — the OTHER surplus devices appear in the forward timeline, like
    the battery/EV: an 'expected to run' row, or a 'goal met' row."""

    def test_device_run_row_emitted(self):
        rows = compose_today_plan(
            now=_now(), horizon_hours=24,
            device_runs=[{"name": "Pool pump", "when": _now() + timedelta(hours=2)}],
        )
        run = [r for r in rows if r["kind"] == "device_run"]
        assert len(run) == 1
        assert run[0]["values"]["name"] == "Pool pump"
        assert run[0]["label"] == "plan_device_run"

    def test_device_done_row_emitted(self):
        rows = compose_today_plan(
            now=_now(),
            device_runs=[{"name": "Hot water", "when": _now() + timedelta(hours=1),
                          "done": True}],
        )
        done = [r for r in rows if r["kind"] == "device_done"]
        assert done and done[0]["values"]["name"] == "Hot water"

    def test_device_outside_horizon_skipped(self):
        rows = compose_today_plan(
            now=_now(), horizon_hours=4,
            device_runs=[{"name": "Late", "when": _now() + timedelta(hours=10)}],
        )
        assert not [r for r in rows if r["kind"] in ("device_run", "device_done")]

    def test_no_device_runs_is_noop(self):
        rows = compose_today_plan(now=_now())
        assert not [r for r in rows if r["kind"] in ("device_run", "device_done")]


# ── #576: battery role in the 3-layer trace reflects device priority + mode ─
from custom_components.solar_energy_management.coordinator.cycle_trace import (  # noqa: E402
    battery_list_role,
)


class TestBatteryListRole:
    """The battery's management-layer role in the 3-layer trace is driven by
    its POSITION in the device-priority list, its mode, and the reserve floor
    (#576) — precedence: command > reserve floor > drag position."""

    def _role(self, **kw):
        base = dict(battery_priority=4, battery_commanded=False, soc=80.0,
                    priority_soc=30.0, discharge_w=0.0)
        base.update(kw)
        return battery_list_role(**base)

    def test_passive_sink_shows_list_position(self):
        assert self._role(battery_priority=4) == "sink at list position 4"
        assert self._role(battery_priority=2) == "sink at list position 2"

    def test_below_reserve_charges_first(self):
        assert "below reserve" in self._role(soc=25.0)

    def test_commanded_charge_goes_to_top(self):
        assert "commanded" in self._role(battery_commanded=True)

    def test_commanded_discharge_leaves_the_walk(self):
        r = self._role(battery_commanded=True, discharge_w=1500.0)
        assert "discharging" in r and "feeding" in r

    def test_no_battery_in_list(self):
        assert self._role(battery_priority=None) == "no battery in the priority list"

    def test_command_takes_precedence_over_position(self):
        assert "commanded" in self._role(battery_priority=2, battery_commanded=True)

    def test_reserve_takes_precedence_over_position(self):
        assert "below reserve" in self._role(battery_priority=2, soc=10.0)

    def test_command_beats_reserve_when_both_true(self):
        # commanded charge AND below reserve → command wins (checked first).
        assert self._role(battery_commanded=True, soc=10.0) == "charging first — commanded"

    def test_commanded_discharge_beats_no_battery_in_list(self):
        # discharge branch fires before the None-position check.
        r = self._role(battery_commanded=True, discharge_w=1500.0, battery_priority=None)
        assert "feeding" in r

    def test_reserve_beats_no_battery_in_list(self):
        # below-reserve is checked before the None-position label.
        assert "below reserve" in self._role(battery_priority=None, soc=10.0)

    def test_uncommanded_discharge_still_shows_position(self):
        # Normal self-consumption discharge (NOT commanded) → position label,
        # not "feeding": the discharge branch requires battery_commanded=True.
        assert self._role(battery_commanded=False, discharge_w=3000.0,
                          battery_priority=4) == "sink at list position 4"


# ── #576: integration-layer match functions (the sealed watchdog) ──────────
from custom_components.solar_energy_management.coordinator.cycle_trace import (  # noqa: E402
    ev_layer_match, battery_layer_match, device_layer_match, heat_pump_layer_match,
)


class TestLayerMatch:
    """Every subsystem's commanded-vs-observed match — what makes the
    layer-mismatch watchdog fire (or correctly stay silent)."""

    # EV — the flap linchpin
    def test_ev_none_when_idle(self):
        assert ev_layer_match(0, 5000, 3, 230, True) is None       # not commanding
    def test_ev_none_when_disconnected(self):
        assert ev_layer_match(10, 0, 3, 230, False) is None
    def test_ev_true_when_drawing(self):
        assert ev_layer_match(10, 5000, 3, 230, True) is True
    def test_ev_false_commanded_not_drawing(self):
        assert ev_layer_match(12, 100, 3, 230, True) is False      # 12A commanded, 100W → flap

    # Battery — force-command verification
    def test_battery_force_charge(self):
        assert battery_layer_match("force_charge", 2000, 0) is True
        assert battery_layer_match("force_charge", 0, 0) is False
    def test_battery_force_discharge(self):
        assert battery_layer_match("force_discharge", 0, 1500) is True
        assert battery_layer_match("force_discharge", 0, 0) is False
    def test_battery_normal_none(self):
        assert battery_layer_match("normal", 100, 0) is None

    # Device — relay reality, thermostat-safe
    def test_device_none_when_not_driving(self):
        assert device_layer_match(False, True) is None
    def test_device_none_when_unobservable(self):
        assert device_layer_match(True, None) is None
    def test_device_true_when_relay_on(self):
        assert device_layer_match(True, True) is True              # incl. heater on @ 0W
    def test_device_false_when_relay_off(self):
        assert device_layer_match(True, False) is False            # commanded on, relay off

    # Heat pump — SG-Ready boost verification
    def test_hp_none_when_not_boosting(self):
        assert heat_pump_layer_match(False, 2) is None
    def test_hp_true_when_boosted(self):
        assert heat_pump_layer_match(True, 3) is True
        assert heat_pump_layer_match(True, 4) is True
    def test_hp_false_when_boost_not_set(self):
        assert heat_pump_layer_match(True, 2) is False             # commanded boost, relay normal
