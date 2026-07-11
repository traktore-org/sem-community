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
