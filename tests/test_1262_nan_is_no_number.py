"""#1262 — a "nan" or "inf" state is no number, in every state parse.

``float("nan")`` does not fail, so about 50 plain ``float(state.state)``
reads took NaN as a known value: "is the level known?" said yes and every
compare with it said no. Each of those sits in a ``try`` that already
catches ``ValueError``; ``units.finite_float`` raises it for NaN and inf.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.units import (
    finite_float,
)

PACKAGE = Path(__file__).resolve().parent.parent


class TestFiniteFloat:
    @pytest.mark.parametrize("raw, want", [("12.5", 12.5), (" 7 ", 7.0), (3, 3.0),
                                           ("-0.5", -0.5), ("1e3", 1000.0)])
    def test_a_number_parses_as_float_does(self, raw, want):
        assert finite_float(raw) == want

    @pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "Infinity",
                                     float("nan"), float("inf")])
    def test_nan_and_inf_are_no_number(self, raw):
        with pytest.raises(ValueError):
            finite_float(raw)

    @pytest.mark.parametrize("raw", ["unknown", "", "error", None])
    def test_text_fails_as_float_does(self, raw):
        with pytest.raises((ValueError, TypeError)):
            finite_float(raw)


def _raw_state_floats():
    """Every ``float(<x>.state)`` in the package outside the tests."""
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE)
        if "tests" in rel.parts or "node_modules" in rel.parts:
            continue
        if rel.parts[0] == "dashboard" or path.name == "units.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "float" and len(node.args) == 1
                    and isinstance(node.args[0], ast.Attribute)
                    and node.args[0].attr == "state"):
                found.append(f"{rel}:{node.lineno}")
    return found


def test_no_state_is_parsed_with_a_plain_float():
    """The guard for the class: a new ``float(state.state)`` fails here."""
    assert _raw_state_floats() == [], (
        "parse a state with units.finite_float (or units.state_number)")


class TestASiteDriven:
    def test_a_nan_charge_level_is_no_level(self):
        from custom_components.solar_energy_management.features import (
            load_device_discovery as ldd,
        )
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _e: SimpleNamespace(state="nan")))
        discovery = ldd.LoadDeviceDiscovery.__new__(ldd.LoadDeviceDiscovery)
        discovery.hass = hass
        assert discovery._get_device_power_rating("sensor.x") == 0.0
