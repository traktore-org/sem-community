"""#708 cleanup — one function owns "how many kWh to reach the SOC target".

The effective-SOC-remaining math lived in TWO places: the stop decision
(``_ev_charging_need_kwh``) and, re-derived by hand, the estimate-stop /
resume announcement. Two copies of one rule drift: change the stop and the
announcement would tell a user "the estimate stopped your charge" while the
decision no longer does. ``soc_remaining_need`` is now the single source,
and it makes the #708 invariants structural rather than commented.

Three SOC inputs, and the contract about each:
  * ``vehicle_soc`` — the real sensor, the floor of truth.
  * ``ceiling_soc`` — ``energy_accounted_soc()``: anchor + MEASURED delivery.
    A cap on the stop, never a replacement (#708) — and it can only pull the
    stop EARLIER, never charge past the sensor.
  * the speculative virtual/estimated SOC is not an input here at all
    (#440/#446): it never touches a stop.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.ev_soc_need import (
    soc_remaining_need,
)


@pytest.mark.unit
class TestSocRemainingNeed:

    def test_sensor_only_when_no_ceiling(self):
        r = soc_remaining_need(target_soc=80, vehicle_soc=60, ceiling_soc=None,
                               capacity_kwh=40)
        assert r.sensor_kwh == pytest.approx(8.0)      # (80-60)/100*40
        assert r.effective_kwh == pytest.approx(8.0)   # no cap → same

    def test_ceiling_above_sensor_pulls_the_stop_earlier(self):
        """The #708 case: stale 58 sensor, measured ceiling at 61."""
        r = soc_remaining_need(target_soc=60, vehicle_soc=58, ceiling_soc=61,
                               capacity_kwh=40)
        assert r.sensor_kwh == pytest.approx(0.8)      # sensor alone: still owed
        assert r.effective_kwh == 0.0                  # cap: target already met

    def test_the_cap_can_only_pull_earlier_never_later(self):
        """THE invariant, made structural: effective_kwh <= sensor_kwh for any
        inputs. A measured cap can never make SEM charge PAST the sensor."""
        for sensor in range(0, 101, 7):
            for ceiling in (None, 0, sensor - 10, sensor, sensor + 10, 100):
                r = soc_remaining_need(80, sensor, ceiling, 50)
                if r.sensor_kwh is not None and r.effective_kwh is not None:
                    assert r.effective_kwh <= r.sensor_kwh + 1e-9, (
                        f"cap extended the charge: sensor={sensor} ceiling={ceiling}"
                    )

    def test_a_ceiling_below_the_sensor_is_ignored(self):
        """max(sensor, ceiling): a lagging-low ceiling never overrules a
        higher real reading — the sensor stays primary."""
        r = soc_remaining_need(80, 70, ceiling_soc=65, capacity_kwh=40)
        assert r.effective_kwh == pytest.approx(4.0)   # uses 70, not 65

    def test_sensor_missing_uses_the_ceiling(self):
        """Sensor momentarily unavailable but anchored earlier this session:
        the measured estimate keeps counting (better than charging blind)."""
        r = soc_remaining_need(80, vehicle_soc=None, ceiling_soc=72,
                               capacity_kwh=40)
        assert r.sensor_kwh is None
        assert r.effective_kwh == pytest.approx(3.2)    # (80-72)/100*40

    def test_no_soc_information_at_all_is_none(self):
        """No sensor, no anchor → the caller must fall back (charge to taper),
        signalled by None rather than a fabricated number."""
        r = soc_remaining_need(80, None, None, 40)
        assert r.sensor_kwh is None and r.effective_kwh is None

    def test_never_negative(self):
        r = soc_remaining_need(60, vehicle_soc=90, ceiling_soc=95, capacity_kwh=40)
        assert r.sensor_kwh == 0.0 and r.effective_kwh == 0.0

    def test_zero_capacity_is_none_not_a_divide(self):
        r = soc_remaining_need(80, 60, 65, capacity_kwh=0)
        assert r.effective_kwh is None


@pytest.mark.unit
class TestTheStopNeverReadsTheSpeculativeEstimate:
    """#440/#446 as a guard, not a comment: the need/stop path must not call
    get_virtual_soc — only the measured ceiling may cap a stop."""

    def test_need_path_does_not_call_get_virtual_soc(self):
        import ast
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "coordinator"
               / "coordinator.py").read_text()
        tree = ast.parse(src)
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "_calculate_remaining_need"), None)
        assert fn is not None, "premise: the need function exists"
        calls = {getattr(c.func, "attr", None) for c in ast.walk(fn)
                 if isinstance(c, ast.Call)}
        assert "get_virtual_soc" not in calls, (
            "the stop path reads the speculative estimate — #446 wall breached"
        )
        assert "energy_accounted_soc" in calls or "soc_remaining_need" in calls, (
            "the stop path no longer reads the measured ceiling — premise moved"
        )
