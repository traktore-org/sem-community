"""#845 — the inverter's operating mode is observed, warned about once,
and never written.

The premise every plan stands on — "the battery is in a self-consumption-
shaped mode" — was assumed and never checked. The watch reads the policy
selector, publishes it beside the battery evidence, and raises ONE Repair
after the unexpected reading has held steadily. It tolerates the reference
install's reality: the modbus feed is blind 5 % of wall time (137
dropouts/day), and a dropout is not a mode change.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.battery_mode_watch import (
    CONFIRM_READS,
    BatteryModeWatch,
)

EXPECTED = {"maximise_self_consumption"}


class TestTheDebounce:
    def test_expected_is_ok_forever(self):
        w = BatteryModeWatch(EXPECTED)
        for _ in range(50):
            assert w.feed("maximise_self_consumption") == "ok"
        assert not w.raised

    def test_unexpected_raises_only_after_the_streak(self):
        w = BatteryModeWatch(EXPECTED)
        for i in range(CONFIRM_READS - 1):
            assert w.feed("fully_fed_to_grid") == "unknown", f"read {i} raised early"
        assert not w.raised
        assert w.feed("fully_fed_to_grid") == "unexpected"
        assert w.raised and w.changed                # the raise EDGE
        assert w.feed("fully_fed_to_grid") == "unexpected"
        assert not w.changed                         # …only once

    def test_a_dropout_neither_counts_nor_resets(self):
        """The 5 % blind time: unavailable mid-streak must not clear the
        evidence, or the Repair could never be reached on this hardware."""
        w = BatteryModeWatch(EXPECTED)
        for _ in range(CONFIRM_READS - 1):
            w.feed("time_of_use_luna2000")
        for _ in range(20):
            w.feed("unavailable")                    # long dropout
            w.feed(None)
        assert not w.raised
        w.feed("time_of_use_luna2000")               # streak continues at 6
        assert w.raised

    def test_returning_to_expected_clears_on_an_edge(self):
        w = BatteryModeWatch(EXPECTED)
        for _ in range(CONFIRM_READS):
            w.feed("fully_fed_to_grid")
        assert w.raised
        assert w.feed("maximise_self_consumption") == "ok"
        assert not w.raised and w.changed            # the clear EDGE

    def test_no_expectation_means_publish_only(self):
        w = BatteryModeWatch(None)
        for _ in range(50):
            assert w.feed("anything_at_all") == "ok"
        assert not w.raised
        assert w.last_mode == "anything_at_all"

    def test_the_last_real_reading_survives_dropouts(self):
        w = BatteryModeWatch(EXPECTED)
        w.feed("maximise_self_consumption")
        w.feed("unavailable")
        assert w.last_mode == "maximise_self_consumption"


class TestTheBrandExpectations:
    def test_huawei_expects_self_consumption(self):
        from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
            HuaweiBatteryAdapter,
        )
        assert HuaweiBatteryAdapter.expected_operating_modes() == {
            "maximise_self_consumption"}

    def test_the_base_has_no_opinion(self):
        from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
            BatteryControlAdapter,
        )
        assert BatteryControlAdapter.expected_operating_modes() is None


class TestObserveActNever:
    def test_no_write_path_exists_for_the_mode_entity(self):
        """The issue's hard boundary (the one #804 got wrong with the Zaptec
        installation limit): SEM never writes a policy selector. No
        select_option call may reference the operating-mode entity."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        for f in list((root / "coordinator").rglob("*.py")) + [root / "__init__.py"]:
            src = f.read_text()
            if "battery_operating_mode_entity" not in src:
                continue
            assert "select_option" not in src, (
                f"{f.name} references the mode entity AND calls "
                "select_option — the never-write boundary")

    def test_the_repair_pair_exists(self):
        from custom_components.solar_energy_management.coordinator import repair_issues as ri
        assert callable(ri.raise_battery_operating_mode_unexpected)
        assert callable(ri.clear_battery_operating_mode_unexpected)


class TestTheEvidenceReachesTheEntity:
    """The #846 lesson, applied on day one: a coordinator key nobody
    surfaces is not a diagnostic. Assert the ENTITY, not the dict."""

    def test_the_spendable_sensor_exposes_the_mode(self):
        import inspect

        from custom_components.solar_energy_management import sensor as sm
        src = inspect.getsource(sm)
        assert '"battery_operating_mode": d.get(' in src

    def test_the_coordinator_publishes_it(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        src = inspect.getsource(cm)
        assert 'result["battery_operating_mode"]' in src
