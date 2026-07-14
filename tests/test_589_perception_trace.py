"""#589 B — Perception-layer cross-check folds into the trace health engine.

A sign/counter contradiction is a two-view (perception) fault the three control
layers cannot catch (they all cohere on the mis-signed input). It now rides the
SAME streak/health engine as control faults, so a persistent contradiction trips
binary_sensor.sem_layer_mismatch.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.cycle_trace import (
    TraceCollector, CrossCheck, LayerStatus,
)


class TestCrossCheckIsFault:
    def test_disagree_while_judging_is_fault(self):
        cc = CrossCheck("battery_sign", status=LayerStatus.OK, data={"agree": False})
        assert cc.is_fault is True

    def test_agree_is_not_fault(self):
        cc = CrossCheck("battery_sign", status=LayerStatus.OK, data={"agree": True})
        assert cc.is_fault is False

    def test_none_agree_is_not_fault(self):
        # nothing to judge this cycle (too little flow / counters unavailable)
        cc = CrossCheck("grid_sign", status=LayerStatus.OK, data={"agree": None})
        assert cc.is_fault is False

    def test_idle_status_never_faults(self):
        cc = CrossCheck("grid_sign", status=LayerStatus.IDLE, data={"agree": False})
        assert cc.is_fault is False


class TestPerceptionFoldsIntoHealth:
    def _cycle(self, tc, *, agree: bool):
        t = tc.begin()
        t.cross_checks["battery_sign"] = CrossCheck(
            "battery_sign", status=LayerStatus.OK, data={"agree": agree},
        )
        tc.commit()

    def test_persistent_contradiction_trips_health_after_threshold(self):
        tc = TraceCollector()
        # 2 contradiction cycles — below the default threshold of 3
        self._cycle(tc, agree=False)
        self._cycle(tc, agree=False)
        assert tc.health()["ok"] is True
        # third consecutive → trips
        self._cycle(tc, agree=False)
        h = tc.health()
        assert h["ok"] is False
        assert h["subsystem"] == "perception:battery_sign"
        assert h["cycles"] == 3

    def test_recovery_clears_health(self):
        tc = TraceCollector()
        for _ in range(4):
            self._cycle(tc, agree=False)
        assert tc.health()["ok"] is False
        # sign agrees again → streak resets → healthy
        self._cycle(tc, agree=True)
        assert tc.health()["ok"] is True

    def test_agreeing_perception_never_trips(self):
        tc = TraceCollector()
        for _ in range(10):
            self._cycle(tc, agree=True)
        assert tc.health()["ok"] is True

    def test_latest_mismatch_names_the_signal(self):
        tc = TraceCollector()
        for _ in range(3):
            self._cycle(tc, agree=False)
        lm = tc.latest_mismatch()
        assert lm is not None
        assert lm["subsystem"] == "perception:battery_sign"
        assert lm["cross_check"]["data"]["agree"] is False

    def test_cross_checks_in_serialised_trace(self):
        tc = TraceCollector()
        self._cycle(tc, agree=True)
        dump = tc.recent()
        assert dump[-1]["cross_checks"]["battery_sign"]["data"]["agree"] is True
