"""#422's attribution must REACH the state, not stop at the analyzer.

Walking a live dashboard on 30.08 found the solar card showing "—" for
degradation and trend with no way to tell "not enough history yet" from
"broken". #422 added `*_path` fields for exactly that question — but
`PVPerformanceResult.to_dict()` exposes ~13 fields while the coordinator
copied four, so every path was computed and dropped and a diagnose dump
carried no `pv_degradation_path` at all. The inert-half pattern (#819).
"""
from __future__ import annotations

import inspect

from custom_components.solar_energy_management.coordinator.types import (
    PVAnalyticsData,
)

PATHS = ("pv_yield_path", "pv_performance_path",
         "pv_degradation_path", "pv_system_age_path")


class TestThePathsAreCarried:
    def test_the_dataclass_has_them(self):
        d = PVAnalyticsData()
        for name in PATHS:
            assert hasattr(d, name), name
            assert getattr(d, name) == "uninitialized"

    def test_the_coordinator_copies_every_one(self):
        from custom_components.solar_energy_management.coordinator import (
            coordinator as cm,
        )
        src = inspect.getsource(cm)
        for name in PATHS:
            assert f"pv_data.{name} = pv." in src, (
                f"{name} is computed by the analyzer and never copied — the "
                "telemetry that explains a blank value must reach the state"
            )

    def test_the_state_dict_publishes_every_one(self):
        from custom_components.solar_energy_management.coordinator import types
        src = inspect.getsource(types)
        for name in PATHS:
            assert f'"{name}": self.pv_analytics.{name}' in src, name

    def test_the_analyzer_and_the_dataclass_agree(self):
        """Whatever the analyzer names a path, the carrier must have it."""
        from custom_components.solar_energy_management.analytics import (
            pv_performance,
        )
        src = inspect.getsource(pv_performance)
        analyzer_paths = {f"pv_{n}" for n in
                          ("yield_path", "performance_path",
                           "degradation_path", "system_age_path")
                          if f"{n}: str" in src}
        carried = set(PATHS)
        missing = analyzer_paths - carried
        assert not missing, f"analyzer paths with no carrier: {missing}"
