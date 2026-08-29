"""#743 — the probe has to be WATCHABLE while it runs.

The probe's whole job is invisible from the outside: it grants watts the
meters cannot see, and when it declines to fire there is nothing at all
to look at. Live on real hardware that is useless — "it didn't probe"
has six possible causes (no forecast, export present, production too
high, no solar-mode charger, cooldown, the inverter says unlimited) and
the operator can distinguish none of them.

So each tick records its state + the terms it judged, and the EV
subsystem's management layer carries them into the per-cycle trace the
``diagnose`` service dumps. Read-only: nothing here changes a decision.
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


class _TraceStub:
    _collect_trace = SEMCoordinator._collect_trace
    _trace_ev = SEMCoordinator._trace_ev
    _trace_battery = SEMCoordinator._trace_battery
    _trace_loads = SEMCoordinator._trace_loads
    _trace_heat_pump = SEMCoordinator._trace_heat_pump
    trace_recent = SEMCoordinator.trace_recent

    def __init__(self):
        self._trace = TraceCollector(maxlen=5)
        self.time_manager = SimpleNamespace(is_night_mode=lambda: False)
        self.config = {}
        self._ev_device = None
        self._observer_mode = False


def _power(**kw):
    base = dict(
        ev_power=0.0, ev_connected=True, battery_soc=50.0,
        battery_charge_power=0.0, battery_discharge_power=0.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _semdata():
    return SimpleNamespace(
        calculated_current=0, charging_strategy_reason="idle",
        available_power=0.0, status=SimpleNamespace(battery_status=""),
        surplus_control=None, heat_pump=None,
    )


@pytest.mark.unit
class TestTheTraceCarriesTheProbe:
    def test_probe_state_reaches_the_ev_management_layer(self):
        s = _TraceStub()
        s._curtailment_last = {
            "state": "probing", "grant_w": 4340.0, "expected_w": 6000.0,
            "production_w": 1000.0, "export_w": 0.0, "export_limited": True,
            "floor_w": 4140.0,
        }
        s._collect_trace(_semdata(), _power(), None)
        mgmt = s.trace_recent(1)[0]["subsystems"]["ev"]["management"]["data"]
        assert mgmt["curtailment"]["state"] == "probing"
        assert mgmt["curtailment"]["grant_w"] == 4340.0
        assert mgmt["curtailment"]["export_limited"] is True

    def test_silent_when_the_probe_never_ran(self):
        """Opt-in feature: an install that never enabled it must not
        grow a key in every EV trace record."""
        s = _TraceStub()
        s._collect_trace(_semdata(), _power(), None)
        mgmt = s.trace_recent(1)[0]["subsystems"]["ev"]["management"]["data"]
        assert "curtailment" not in mgmt


class _GrantStub:
    """Host for the real ``_curtailment_grant_w`` with the few
    collaborators it reads."""
    _curtailment_grant_w = SEMCoordinator._curtailment_grant_w

    def __init__(self, *, enabled: bool, limit_state=None):
        self.config = {
            "curtailment_probe_enabled": enabled,
            "ev_min_current": 6, "ev_voltage": 230, "ev_phases": 3,
            "ev_charge_mode": "solar_only",
            "solar_production_sensor": "sensor.solar",
        }
        state = (
            SimpleNamespace(state=limit_state, attributes={})
            if limit_state is not None else None
        )
        self.hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _e: state),
            data={},
        )
        self._sensor_reader = SimpleNamespace(
            detect_export_limit_entity=lambda _a: (
                "sensor.limit" if limit_state is not None else None
            ),
        )
        self._cycle_forecast = SimpleNamespace(available=True, power_now_w=6000.0)
        self._forecast_tracker = SimpleNamespace(apply_dampening=lambda kw: kw)


@pytest.mark.unit
class TestEachTickRecordsItself:
    def test_a_declining_tick_still_records_why(self):
        """Export is flowing, so the signature fails and no grant is
        made — the operator still has to SEE that it was 0 W export
        that was judged, not a missing forecast."""
        s = _GrantStub(enabled=True, limit_state="Limited to 0.0 W")
        power = SimpleNamespace(
            solar_power=1000.0, grid_export_power=2000.0,
            home_consumption_power=1000.0, battery_charge_power=0.0,
            ev_power=0.0, ev_connected=True,
        )
        assert s._curtailment_grant_w(power) == 0.0
        snap = s._curtailment_last
        assert snap["state"] == "idle"
        assert snap["grant_w"] == 0.0
        assert snap["export_w"] == 2000.0
        assert snap["expected_w"] == 6000.0
        assert snap["export_limited"] is True
        assert snap["floor_w"] == pytest.approx(4140.0)

    def test_disabled_records_off(self):
        s = _GrantStub(enabled=False)
        power = SimpleNamespace(
            solar_power=1000.0, grid_export_power=0.0,
            home_consumption_power=1000.0, battery_charge_power=0.0,
            ev_power=0.0, ev_connected=True,
        )
        assert s._curtailment_grant_w(power) == 0.0
        assert s._curtailment_last["state"] == "off"
