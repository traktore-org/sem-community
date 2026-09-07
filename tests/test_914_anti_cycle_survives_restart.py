"""(#914) The anti-cycle window a user sets on the hot-water row must reach
the live device — and survive a restart.

The reporter's request was to make the windows reachable. They already
were, in the one mode where they have an effect (Solar, the default for a
direct device — #508). What was actually broken:

1. The stored goal was published back to the card and never RE-APPLIED to
   the live object after a restart. Drag priority had that seam
   (`refresh_direct_device_priorities`, #576/#890); the goals did not.
2. The hot-water default was a 60 s pause — the #688 floor-raise to 300 s
   on SwitchDevice never reached this subclass. A heat pump restarted before
   its circuit water had come up.
3. The card's placeholder said "5" whatever the device held.

Two of the earlier plans for this issue proposed gating the row on
Peak-only. That would have shown a setting nothing reads: the peak-only
shedder (`features/load_management.py`) never consults this window and
never has hot water in its roster at all.
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management.tests.ast_contracts import calls


def _registry(goals: dict, live: dict) -> UnifiedDeviceRegistry:
    reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
    reg._device_goals = dict(goals)
    reg._priority_overrides = {}
    reg._surplus_controller = SimpleNamespace(
        _devices=dict(live),
        get_device=lambda did: live.get(did),
    )
    reg.priority_for = lambda did, seed=5: seed
    return reg


def _hot_water(**kw):
    d = dict(device_id="hot_water", priority=5, is_ev=False,
             min_on_seconds=600, min_off_seconds=300)
    d.update(kw)
    return SimpleNamespace(**d)


class TestTheStoredGoalReachesTheLiveDevice:

    def test_a_stored_window_is_applied_on_the_direct_refresh(self):
        live = _hot_water()
        reg = _registry({"hot_water": {"min_on_time_min": 15,
                                       "min_off_time_min": 12}},
                        {"hot_water": live})
        reg.refresh_direct_device_overrides()
        assert live.min_on_seconds == 900, (
            "the stored anti-cycle goal never reached the live device — "
            "which is what a restart looked like before #914")
        assert live.min_off_seconds == 720

    def test_no_stored_goal_leaves_the_constructor_value(self):
        live = _hot_water()
        reg = _registry({}, {"hot_water": live})
        reg.refresh_direct_device_overrides()
        assert (live.min_on_seconds, live.min_off_seconds) == (600, 300)

    def test_energy_dashboard_rows_are_not_touched_here(self):
        """They get theirs from the rebuild — this seam is for the devices
        the rebuild does not re-create."""
        ed = _hot_water(device_id="energy_dashboard_pump")
        reg = _registry({"energy_dashboard_pump": {"min_on_time_min": 15}},
                        {"energy_dashboard_pump": ed})
        reg.refresh_direct_device_overrides()
        assert ed.min_on_seconds == 600


class TestTheSeamIsWiredStructurally:

    def test_the_direct_refresh_applies_goals(self):
        assert calls(UnifiedDeviceRegistry.refresh_direct_device_overrides,
                     "_apply_goals")

    def test_the_per_cycle_sync_reaches_it(self):
        assert calls(UnifiedDeviceRegistry.sync_cycle_priorities,
                     "refresh_direct_device_overrides")


class TestTheCardCanSeeWhatTheDeviceHolds:

    def test_the_effective_window_is_published_in_minutes(self):
        live = _hot_water(min_on_seconds=900, min_off_seconds=720)
        reg = _registry({"hot_water": {"min_on_time_min": 15}},
                        {"hot_water": live})
        p = reg._goal_payload("hot_water")["goals"]
        assert p["min_on_effective_min"] == 15.0
        assert p["min_off_effective_min"] == 12.0

    def test_no_live_device_publishes_absent_not_zero(self):
        reg = _registry({"hot_water": {"min_on_time_min": 15}}, {})
        p = reg._goal_payload("hot_water")["goals"]
        assert p["min_on_effective_min"] is None
        assert p["min_off_effective_min"] is None


class TestTheHotWaterDefaultIsHeatPumpShaped:

    def test_the_constructor_default(self):
        import inspect
        from custom_components.solar_energy_management.devices.hot_water_controller import (
            HotWaterController,
        )
        sig = inspect.signature(HotWaterController.__init__)
        assert sig.parameters["min_on_time"].default == 600
        assert sig.parameters["min_off_time"].default == 300, (
            "the #688 floor-raise never reached this subclass — a heat pump "
            "restarted after a 60 s pause")

    def test_it_matches_the_heat_pump_controllers_own_numbers(self):
        """Consistency with a value the repo already stands behind (#508
        W1), not a new guess."""
        from pathlib import Path
        import ast
        src = (Path(__file__).resolve().parent.parent
               / "devices" / "heat_pump_controller.py").read_text()
        tree = ast.parse(src)
        got = {}
        for n in ast.walk(tree):
            if (isinstance(n, ast.Assign) and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Attribute)
                    and n.targets[0].attr in ("min_on_seconds", "min_off_seconds")
                    and isinstance(n.value, ast.Constant)):
                got[n.targets[0].attr] = n.value.value
        assert got == {"min_on_seconds": 600, "min_off_seconds": 300}


class TestTheBoundsHaveOneHome:

    def test_the_table_declares_one_shared_window(self):
        """One row for both inputs — they share the range. A second,
        identical row for the pause input was the first draft, and the
        orphan check in test_828 caught it: a row nobody reads is a claim."""
        from custom_components.solar_energy_management.consts.bounds import BOUNDS
        r = BOUNDS["anti_cycle_window_min"]
        assert (r.min, r.max, r.step) == (0, 120, 1)
        assert not [k for k in BOUNDS if k.startswith("anti_cycle_") and
                    k != "anti_cycle_window_min"]

    def test_the_card_no_longer_hardcodes_the_range(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "dashboard" / "card"
               / "src" / "cards" / "sem-load-priority-card.js").read_text()
        i = src.index("_renderAntiCycle(device) {")
        body = src[i:i + 3000]
        # CODE only — the comment above the input explains what the old
        # hardcode was, and quoting it is not re-declaring it. The first
        # draft of this test failed on its own explanatory comment.
        code = "\n".join(l for l in body.split("\n")
                        if not l.strip().startswith("//"))
        assert 'max="120"' not in code, (
            "the anti-cycle range is re-declared in JS — a second copy of "
            "consts/bounds.py")
        assert "_antiCycleBounds()" in code
