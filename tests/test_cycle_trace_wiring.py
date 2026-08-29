"""Coordinator wiring for the layered trace (1.7.5).

Verifies the read-only ``_trace_ev`` / ``_trace_battery`` / ``_collect_trace``
capture methods map this-cycle values into the trace correctly — in
particular that the 2026-07-10 EV flap (commanded a charge, observed 0 W)
surfaces as a layer-boundary mismatch. Methods are bound onto a light stub
so we don't stand up a full coordinator.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.cycle_trace import (
    TraceCollector,
)


class _Stub:
    """Minimal host for the unbound trace methods."""
    _collect_trace = SEMCoordinator._collect_trace
    _trace_ev = SEMCoordinator._trace_ev
    _trace_battery = SEMCoordinator._trace_battery
    _trace_loads = SEMCoordinator._trace_loads
    _trace_heat_pump = SEMCoordinator._trace_heat_pump
    trace_recent = SEMCoordinator.trace_recent
    trace_latest_mismatch = SEMCoordinator.trace_latest_mismatch

    def __init__(self):
        self._trace = TraceCollector(maxlen=10)
        self.time_manager = SimpleNamespace(is_night_mode=lambda: False)
        self.config = {}
        self._ev_device = None
        self._observer_mode = False      # not in observer mode


def _power(*, ev_power, ev_connected=True, battery_soc=100.0,
           battery_charge_power=0.0, battery_discharge_power=0.0):
    return SimpleNamespace(
        ev_power=ev_power, ev_connected=ev_connected, battery_soc=battery_soc,
        battery_charge_power=battery_charge_power,
        battery_discharge_power=battery_discharge_power,
    )


def _semdata(*, calculated_current, reason, available_power, battery_status="",
             surplus_control=None, heat_pump=None):
    return SimpleNamespace(
        calculated_current=calculated_current,
        charging_strategy_reason=reason,
        available_power=available_power,
        status=SimpleNamespace(battery_status=battery_status),
        surplus_control=surplus_control,
        heat_pump=heat_pump,
    )


@pytest.mark.unit
class TestTraceWiring:
    def test_healthy_charge_no_mismatch(self):
        s = _Stub()
        sem = _semdata(calculated_current=16, reason="min_plus_solar Zone 4 → 16A",
                       available_power=11000)
        pw = _power(ev_power=10450)     # commanded 16A, drawing 10.4kW → match
        s._collect_trace(sem, pw, None)
        recent = s.trace_recent(1)
        ev = recent[0]["subsystems"]["ev"]
        assert ev["process"]["status"] == "ok"
        assert ev["process"]["data"]["commanded_amps"] == 16
        assert ev["integration"]["data"]["match"] is True
        assert s.trace_latest_mismatch() is None

    def test_flap_surfaces_as_mismatch(self):
        s = _Stub()
        # commanded 16A, but observed 0W (the KEBA blip / dropped session)
        sem = _semdata(calculated_current=16, reason="min_plus_solar Zone 4 → 16A",
                       available_power=11000)
        pw = _power(ev_power=0.0)
        s._collect_trace(sem, pw, None)
        m = s.trace_latest_mismatch()
        assert m is not None and m["subsystem"] == "ev"
        assert m["integration"]["data"]["match"] is False

    def test_idle_is_not_a_mismatch(self):
        s = _Stub()
        sem = _semdata(calculated_current=0, reason="surplus 2.3k < min 5.5k — idle",
                       available_power=2300)
        pw = _power(ev_power=0.0)
        s._collect_trace(sem, pw, None)
        ev = s.trace_recent(1)[0]["subsystems"]["ev"]
        assert ev["process"]["status"] == "idle"
        assert s.trace_latest_mismatch() is None   # observed 0 is EXPECTED

    def test_disconnected_car_has_no_match_verdict(self):
        s = _Stub()
        sem = _semdata(calculated_current=0, reason="EV disconnected",
                       available_power=0)
        pw = _power(ev_power=0.0, ev_connected=False)
        s._collect_trace(sem, pw, None)
        ev = s.trace_recent(1)[0]["subsystems"]["ev"]
        assert ev["integration"]["data"]["match"] is None

    def test_battery_layer_captured(self):
        s = _Stub()
        sem = _semdata(calculated_current=0, reason="", available_power=0,
                       battery_status="charging")
        pw = _power(ev_power=0.0, battery_charge_power=2400)
        s._collect_trace(sem, pw, None)
        bat = s.trace_recent(1)[0]["subsystems"]["battery"]
        assert bat["process"]["detail"] == "charging"
        assert bat["integration"]["data"]["charge_w"] == 2400

    def test_observer_mode_is_not_a_mismatch(self):
        # observer mode: commanded 16A on paper, observed 0W — but SEM never
        # commands anything in observer mode, so it must NOT count as a
        # layer-boundary fault.
        s = _Stub()
        s._observer_mode = True
        sem = _semdata(calculated_current=16, reason="min_plus_solar → 16A",
                       available_power=11000)
        s._collect_trace(sem, _power(ev_power=0.0), None)
        ev = s.trace_recent(1)[0]["subsystems"]["ev"]
        assert ev["integration"]["data"]["match"] is None
        assert "observer mode" in ev["integration"]["detail"]
        assert s.trace_latest_mismatch() is None

    def test_loads_subsystem_captured(self):
        s = _Stub()
        sc = SimpleNamespace(surplus_total_devices=3, surplus_active_devices=1,
                             surplus_available=True, surplus_total_w=2400,
                             surplus_distributable_w=1800, surplus_allocated_w=710)
        sem = _semdata(calculated_current=0, reason="", available_power=0,
                       surplus_control=sc)
        s._collect_trace(sem, _power(ev_power=0.0), None)
        loads = s.trace_recent(1)[0]["subsystems"]["loads"]
        assert loads["process"]["status"] == "ok"          # 1 active
        assert loads["process"]["data"]["allocated_w"] == 710
        assert loads["integration"]["detail"] == "1 device(s) on"

    def test_loads_absent_when_no_devices(self):
        s = _Stub()
        sc = SimpleNamespace(surplus_total_devices=0, surplus_active_devices=0,
                             surplus_available=False, surplus_total_w=0,
                             surplus_distributable_w=0, surplus_allocated_w=0)
        sem = _semdata(calculated_current=0, reason="", available_power=0,
                       surplus_control=sc)
        s._collect_trace(sem, _power(ev_power=0.0), None)
        assert "loads" not in s.trace_recent(1)[0]["subsystems"]

    def test_heat_pump_subsystem_captured(self):
        s = _Stub()
        hp = SimpleNamespace(heat_pump_registered=True, heat_pump_mode="boost",
                             heat_pump_sg_ready_state=3, heat_pump_solar_boost=True)
        sem = _semdata(calculated_current=0, reason="", available_power=0,
                       heat_pump=hp)
        s._collect_trace(sem, _power(ev_power=0.0), None)
        h = s.trace_recent(1)[0]["subsystems"]["heat_pump"]
        assert h["process"]["detail"] == "boost"
        assert h["integration"]["data"]["sg_ready_state"] == 3

    def test_heat_pump_absent_when_not_registered(self):
        s = _Stub()
        hp = SimpleNamespace(heat_pump_registered=False)
        sem = _semdata(calculated_current=0, reason="", available_power=0,
                       heat_pump=hp)
        s._collect_trace(sem, _power(ev_power=0.0), None)
        assert "heat_pump" not in s.trace_recent(1)[0]["subsystems"]

    def test_loads_observer_mode_in_integration(self):
        s = _Stub(); s._observer_mode = True
        sc = SimpleNamespace(surplus_total_devices=2, surplus_active_devices=0,
                             surplus_available=True, surplus_total_w=1000,
                             surplus_distributable_w=1000, surplus_allocated_w=0)
        sem = _semdata(calculated_current=0, reason="", available_power=0,
                       surplus_control=sc)
        s._collect_trace(sem, _power(ev_power=0.0), None)
        loads = s.trace_recent(1)[0]["subsystems"]["loads"]
        assert loads["integration"]["detail"] == "observer mode — not commanding"

    def test_capture_never_raises_on_missing_fields(self):
        # observability must never break the cycle — a malformed sem_data
        # is swallowed (the try/except in _collect_trace).
        s = _Stub()
        s._collect_trace(object(), object(), None)   # no attributes at all
        # nothing committed, but no exception propagated
        assert s.trace_latest_mismatch() is None
