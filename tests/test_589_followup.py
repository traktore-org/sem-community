"""#589 follow-up reliability fixes.

1. EV W2/W3 — the primary EV taper detector must NOT be re-fed the fleet
   ``power.ev_power`` sum after the per-charger loop already updated it with
   its own power (that false-anchored the primary's SOC on another charger's
   draw). Source-structure guard (the method is too heavy to execute; the repo
   already uses AST/source guards for _update_ev_intelligence — see #517/#318).

2. W7 — the read_power ``else`` branch (per_battery_mode off, e.g. a single
   per-battery meter with _n_units == 1) must negate the per-battery
   ``readings.batteries[bid].power_w`` in lockstep with the fleet scalar, since
   the actuator sources BatteryRuntime.last_known_w from the per-battery dict.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_COORD = Path(__file__).resolve().parents[1] / "coordinator" / "coordinator.py"


def _method_src(name: str) -> str:
    text = _COORD.read_text()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(text, node)
    raise AssertionError(f"{name} not found")


class TestEvFleetReadNoDoubleUpdate:
    """The fleet-sum taper update must be on the legacy single-detector path only."""

    def test_primary_taper_captured_from_own_loop(self):
        src = _method_src("_update_ev_intelligence")
        assert "primary_taper_data" in src, (
            "the primary charger's own per-charger taper result must be captured"
        )

    def test_fleet_update_is_legacy_only(self):
        src = _method_src("_update_ev_intelligence")
        # multi-charger selects the primary's own result...
        assert "if self._ev_devices:" in src
        # ...and the fleet-sum update only runs when NO per-charger devices exist
        # (the elif), never unconditionally.
        assert "elif power.ev_power > 0 or power.ev_connected:" in src

    def test_no_unconditional_fleet_taper_update(self):
        """Guard: the fleet `self._ev_taper_detector.update(power.ev_power ...)`
        must not sit directly in the method body (must be inside the elif)."""
        text = _COORD.read_text()
        tree = ast.parse(text)
        method = next(
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_update_ev_intelligence"
        )
        # Any call to self._ev_taper_detector.update with power.ev_power as first
        # arg must be nested under an If (not a top-level statement of the method).
        top_level = set(method.body)
        for node in ast.walk(method):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "_ev_taper_detector"
            ):
                # first positional arg is power.ev_power
                if node.args and isinstance(node.args[0], ast.Attribute) \
                        and node.args[0].attr == "ev_power":
                    # find the Expr/Assign stmt wrapping it and ensure it's not
                    # a direct child of the method body
                    assert not any(
                        isinstance(s, (ast.Assign, ast.Expr)) and s in top_level
                        and any(c is node for c in ast.walk(s))
                        for s in top_level
                    ), "fleet taper update must be gated, not unconditional"


class TestW7ElseBranchPerBatterySync:
    """read_power else-branch negate keeps the per-battery dict in lockstep."""

    def _reader(self):
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        hass = MagicMock()
        hass.states = MagicMock()
        return SensorReader(hass, {})

    def test_else_branch_negates_per_battery_dict(self):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryPower,
        )
        r = self._reader()
        # single per-battery meter → _n_units == 1 → per_battery_mode is False
        ed = MagicMock()
        ed.battery_power_list = ["sensor.b1_power"]
        ed.battery_power_pairs = []
        r.set_energy_dashboard_config(ed)

        readings = PowerReadings()
        readings.battery_power = 500.0
        readings.batteries = {
            "b1": BatteryPower(battery_id="b1", power_w=500.0, soc_pct=80.0, name="sensor.b1_power"),
        }
        # force the fleet auto-detect to say "negate"
        with patch.object(r, "_detect_battery_sign", return_value=True), \
                patch.object(r, "_read_from_energy_dashboard", return_value=readings), \
                patch.object(r, "_audit_battery_sign_lock"):
            result = r.read_power()

        assert result.battery_power == -500.0
        # the per-battery dict MUST be negated in lockstep (actuator reads this)
        assert result.batteries["b1"].power_w == -500.0, (
            "else-branch negate desynced the per-battery power_w from the fleet scalar"
        )

    def test_else_branch_user_flip_negates_per_battery_dict(self):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryPower,
        )
        r = self._reader()
        r._raw_config = {"battery_sign_user_flip": True}
        ed = MagicMock()
        ed.battery_power_list = ["sensor.b1_power"]
        ed.battery_power_pairs = []
        r.set_energy_dashboard_config(ed)

        readings = PowerReadings()
        readings.battery_power = 300.0
        readings.batteries = {
            "b1": BatteryPower(battery_id="b1", power_w=300.0, soc_pct=70.0, name="sensor.b1_power"),
        }
        with patch.object(r, "_detect_battery_sign", return_value=False), \
                patch.object(r, "_read_from_energy_dashboard", return_value=readings), \
                patch.object(r, "_audit_battery_sign_lock"):
            result = r.read_power()

        assert result.battery_power == -300.0
        assert result.batteries["b1"].power_w == -300.0


class TestSurfaceBTaperNoSwap:
    """#589 C step 1 — the primary taper detector is COMPUTED (property), not
    swapped per-cycle. The former `_ev_taper_detector = _ev_taper_detectors[
    primary_id]` reassignment (one of two parallel per-charger swap surfaces)
    is gone, so the primary can never drift out of sync."""

    def _coord(self):
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        hass = MagicMock()
        return SEMCoordinator(hass, {})

    def test_returns_default_when_no_per_charger_detectors(self):
        c = self._coord()
        c._ev_devices = {}
        assert c._ev_taper_detector is c._ev_taper_detector_default

    def test_resolves_primary_from_per_charger_dict(self):
        from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
            EVTaperDetector,
        )
        c = self._coord()
        prim = EVTaperDetector({})
        second = EVTaperDetector({})
        c._ev_devices = {"keba": object(), "wallbox": object()}
        c._ev_taper_detectors = {"keba": prim, "wallbox": second}
        # primary = first _ev_devices key = "keba"
        assert c._ev_taper_detector is prim
        assert c._ev_taper_detector is not second

    def test_no_swap_reassignment_in_update_ev_intelligence(self):
        # Guard: the per-cycle swap must not come back.
        import pathlib
        coord = pathlib.Path(__file__).resolve().parents[1] / "coordinator" / "coordinator.py"
        src = coord.read_text()
        assert "self._ev_taper_detector = self._ev_taper_detectors[primary_id]" not in src, (
            "the Surface-B per-cycle taper swap was reintroduced"
        )
