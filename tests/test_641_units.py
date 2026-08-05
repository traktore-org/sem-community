"""#641 — one unit-normalization rule, and nothing outside it.

The shape being closed: 'sensor state → watts' was a copy-pasted inline block
with four different match rules (exact ``== "kW"``, lowercase ``== "kw"``,
strip+lower+synonyms, and no check at all), so the same physical sensor was read
at different magnitudes by different subsystems in the same cycle.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator.units import (
    energy_state_to_kwh,
    is_energy_unit,
    is_power_unit,
    is_temperature_unit,
    normalize_unit,
    power_state_to_watts,
    power_unit_scale,
    temperature_state_to_celsius,
)


class _S:
    """Minimal HA State stand-in."""

    def __init__(self, state, unit=None):
        self.state = state
        self.attributes = {} if unit is None else {"unit_of_measurement": unit}


@pytest.mark.unit
class TestPowerNormalization641:
    @pytest.mark.parametrize("unit", ["kW", "kw", "KW", " kW ", "kilowatt", "kilowatts"])
    def test_every_spelling_of_kilowatt_converts(self, unit):
        """The bug: only ONE of these spellings converted at any given call
        site. A template/MQTT sensor emitting ``kw`` was 1000x off in half the
        codebase."""
        assert power_state_to_watts(_S("11", unit)) == 11000.0

    @pytest.mark.parametrize("unit", ["W", "w", " W", None])
    def test_watts_and_missing_unit_pass_through(self, unit):
        assert power_state_to_watts(_S("2400", unit)) == 2400.0

    def test_megawatt(self):
        assert power_state_to_watts(_S("1.5", "MW")) == 1_500_000.0

    def test_negative_power_keeps_its_sign(self):
        """Grid and battery power are signed — the conversion must not clamp."""
        assert power_state_to_watts(_S("-3.2", "kW")) == -3200.0

    @pytest.mark.parametrize("raw", ["unknown", "unavailable", "", None, "abc"])
    def test_unreadable_states_return_the_default(self, raw):
        assert power_state_to_watts(_S(raw, "kW")) is None
        assert power_state_to_watts(_S(raw, "kW"), default=0.0) == 0.0

    def test_a_missing_state_object_returns_the_default(self):
        assert power_state_to_watts(None, default=0.0) == 0.0

    def test_an_unrecognised_unit_is_passed_through_not_dropped(self):
        """A sensor with a unit SEM has no opinion about is not an error — every
        inline copy fell through at 1.0 and so does this."""
        assert power_state_to_watts(_S("5", "VA")) == 5.0


@pytest.mark.unit
class TestEnergyNormalization641:
    def test_wh_counter(self):
        """#551 — Fronius Gen24 lifetime counters report Wh. Reading them raw
        inflated the lifetime accumulators 1000x."""
        assert energy_state_to_kwh(_S("21350", "Wh")) == 21.35

    @pytest.mark.parametrize("unit", ["kWh", "kwh", " kWh ", None])
    def test_kwh_and_missing_unit_pass_through(self, unit):
        assert energy_state_to_kwh(_S("12.5", unit)) == 12.5

    def test_mwh_counter(self):
        assert energy_state_to_kwh(_S("2", "MWh")) == 2000.0

    def test_unreadable_states_return_the_default(self):
        assert energy_state_to_kwh(_S("unavailable", "kWh"), default=0.0) == 0.0

    def test_power_and_energy_tables_do_not_bleed(self):
        """``Wh`` is not a power unit and ``W`` is not an energy unit — a
        mixed-up call must not silently scale."""
        assert power_state_to_watts(_S("1000", "Wh")) == 1000.0
        assert energy_state_to_kwh(_S("1000", "W")) == 1000.0


def _capacity_kwh(state):
    """The battery-capacity heuristic as both autodetect sites now spell it.

    Kept here rather than reaching into ``config_flow`` / ``sensor_reader``
    (both need a full hass) — the point is to pin the ARITHMETIC, which is what
    the refactor could get wrong.
    """
    val = float(state.state)
    labelled = bool(normalize_unit(state))
    val = energy_state_to_kwh(state, default=val)
    if not labelled and val > 500:
        val = val / 1000
    return val


@pytest.mark.unit
class TestCapacityHeuristicNotDoubleApplied641:
    """The magnitude heuristic (``> 500`` ⇒ it must be Wh) and the unit
    conversion must never BOTH fire. Review caught the naive rewrite dividing a
    labelled 600 kWh bank twice, down to 0.6 kWh."""

    def test_a_labelled_wh_counter_above_500kwh_is_divided_once(self):
        assert _capacity_kwh(_S("600000", "Wh")) == 600.0

    def test_a_labelled_kwh_bank_above_500_is_not_divided_at_all(self):
        assert _capacity_kwh(_S("600", "kWh")) == 600.0

    def test_an_unlabelled_wh_counter_still_gets_the_heuristic(self):
        """The case the heuristic exists for — no unit to go on."""
        assert _capacity_kwh(_S("10000", None)) == 10.0

    def test_a_residential_labelled_wh_counter(self):
        """LUNA2000-shaped: 15 kWh reported as 15000 Wh."""
        assert _capacity_kwh(_S("15000", "Wh")) == 15.0

    def test_a_small_unlabelled_value_is_left_alone(self):
        assert _capacity_kwh(_S("15", None)) == 15.0

    def test_an_mwh_counter_converts(self):
        """Not reachable before: the old rule was Wh-only."""
        assert _capacity_kwh(_S("0.015", "MWh")) == 15.0


@pytest.mark.unit
class TestTemperatureNormalization727:
    """#727 — a °F source read as °C showed a 48 °F reading as 118 °C in the
    Home view. SEM's sensor is °C-native and HA converts for display, so the
    source unit must be honoured on ingest."""

    @pytest.mark.parametrize("unit", ["°C", "c", " Celsius ", "CELSIUS"])
    def test_celsius_and_synonyms_pass_through(self, unit):
        assert temperature_state_to_celsius(_S("40", unit)) == 40.0

    @pytest.mark.parametrize("unit", ["°C", None, "", "junk"])
    def test_missing_or_unknown_unit_assumed_celsius(self, unit):
        assert temperature_state_to_celsius(_S("24.5", unit)) == 24.5

    def test_fahrenheit_converts(self):
        # 118 °F is a real inverter temp; must land near 47.8 °C, never stay 118.
        assert temperature_state_to_celsius(_S("118.4", "°F")) == pytest.approx(48.0)

    def test_the_727_report_value(self):
        """A source mislabeled 48 °F (SolarAssistant #727) → 8.9 °C native, which
        HA renders back as 48 °F on a US install — matching the source, not 118."""
        assert temperature_state_to_celsius(_S("48", "°F")) == pytest.approx(8.888, abs=1e-2)

    @pytest.mark.parametrize("unit", ["F", "fahrenheit"])
    def test_fahrenheit_synonyms(self, unit):
        assert temperature_state_to_celsius(_S("32", unit)) == pytest.approx(0.0)

    def test_kelvin_converts(self):
        assert temperature_state_to_celsius(_S("300", "K")) == pytest.approx(26.85)

    def test_negative_celsius_kept(self):
        """Cold-climate inverters read below 0 — the conversion must not clamp."""
        assert temperature_state_to_celsius(_S("-10", "°C")) == -10.0

    @pytest.mark.parametrize("raw", ["unknown", "unavailable", "", None, "abc"])
    def test_unreadable_returns_default(self, raw):
        assert temperature_state_to_celsius(_S(raw, "°C")) is None
        assert temperature_state_to_celsius(_S(raw, "°C"), default=99.0) == 99.0

    def test_missing_state_object_returns_default(self):
        assert temperature_state_to_celsius(None, default=0.0) == 0.0

    def test_is_temperature_unit(self):
        assert is_temperature_unit("°C") and is_temperature_unit(" °f ")
        assert is_temperature_unit("K") and is_temperature_unit("celsius")
        assert not is_temperature_unit("W") and not is_temperature_unit("kWh")
        assert not is_temperature_unit(_S("1", None))

    def test_temperature_table_does_not_bleed_into_power(self):
        """°C is not a power unit and W is not a temperature unit."""
        assert not is_power_unit("°C")
        assert not is_temperature_unit("W")


@pytest.mark.unit
class TestUnitPredicates641:
    def test_is_energy_unit(self):
        assert is_energy_unit("kWh") and is_energy_unit(" wh ") and is_energy_unit("MWh")
        assert not is_energy_unit("W") and not is_energy_unit("kW")

    def test_is_energy_unit_of_a_state(self):
        assert is_energy_unit(_S("1", "kWh"))
        assert not is_energy_unit(_S("1", "kW"))

    def test_a_missing_unit_is_not_claimed_as_energy(self):
        """Assume-kWh is a CONVERSION fallback, not evidence. The #461 config
        check must not accuse an unlabelled sensor of being a counter."""
        assert not is_energy_unit(_S("1", None))

    def test_normalize_unit_of_a_junk_state(self):
        assert normalize_unit(None) == ""
        assert normalize_unit(_S("1", None)) == ""

    def test_power_unit_scale_distinguishes_converted_from_passed_through(self):
        """``forecast_reader``'s #575 conversion counter needs this: a 0.0 kW
        dawn reading and a 0.0 W dawn reading are both 0.0, so before/after
        comparison can't tell them apart."""
        assert power_unit_scale(_S("0", "kW")) == 1000.0
        assert power_unit_scale(_S("0", "W")) == 1.0
        assert power_unit_scale(_S("0", None)) == 1.0
        assert power_unit_scale(_S("0", "VA")) == 1.0

    def test_is_power_unit(self):
        assert is_power_unit("W") and is_power_unit(" kw ") and is_power_unit("MW")
        assert not is_power_unit("kWh") and not is_power_unit("%")
        assert not is_power_unit(_S("1", None))


_ROOT = Path(__file__).resolve().parent.parent
_UNIT_LITERALS = {
    "w", "kw", "mw", "gw",
    "wh", "kwh", "mwh", "gwh",
    "kilowatt", "kilowatts", "watt", "watts",
    # #727 — temperature joined units.py; an inline ``unit in ("°C", "°F")`` in
    # hardware_detection was the same divergent-copy shape, now is_temperature_unit().
    "°c", "°f", "°k", "c", "f", "k", "celsius", "fahrenheit", "kelvin",
}
# Files allowed to compare a unit string against a power/energy literal.
_ALLOWED = {
    "coordinator/units.py",                 # the one implementation
}


def _unit_bearing_names(tree):
    """Names assigned from a ``unit_of_measurement`` lookup in this module."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        src = ast.dump(node.value)
        if "unit_of_measurement" not in src:
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                names.add(tgt.id)
    return names


@pytest.mark.unit
class TestNoFifthCopy641:
    """The guard. A new inline ``if unit == "kW"`` is what created this bug
    four times over; make it unrepresentable rather than trusting review.

    KNOWN GAP: the lint keys off ``unit = <...unit_of_measurement...>`` followed
    by a comparison on that NAME. A fully inline
    ``state.attributes.get("unit_of_measurement", "").lower() == "w"`` has no
    name to key off and slips through. That exact form lived in
    ``ev_taper_detector`` and was migrated as part of #641; if you find yourself
    writing one, that is the shape this guard cannot see."""

    def test_no_module_compares_a_unit_against_a_power_or_energy_literal(self):
        # #727 widened the ban to temperature literals too — same divergent-copy
        # shape, now that units.py owns °C/°F/K via is_temperature_unit().
        offenders = []
        for path in sorted(_ROOT.rglob("*.py")):
            rel = path.relative_to(_ROOT).as_posix()
            if rel.startswith(("tests/", "dashboard/", "scripts/")) or rel in _ALLOWED:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:            # not ours to police
                continue
            unit_names = _unit_bearing_names(tree)
            if not unit_names:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                left = node.left
                # ``unit == "kW"`` and ``unit.lower() == "kw"`` both start from
                # a Name that was assigned out of unit_of_measurement.
                base = left.func.value if (
                    isinstance(left, ast.Call)
                    and isinstance(left.func, ast.Attribute)
                ) else left
                while isinstance(base, ast.Call) and isinstance(base.func, ast.Attribute):
                    base = base.func.value
                if not (isinstance(base, ast.Name) and base.id in unit_names):
                    continue
                for cmp_node in node.comparators:
                    literals = (
                        [cmp_node] if isinstance(cmp_node, ast.Constant)
                        else list(getattr(cmp_node, "elts", []))
                    )
                    for lit in literals:
                        if (isinstance(lit, ast.Constant)
                                and isinstance(lit.value, str)
                                and lit.value.strip().lower() in _UNIT_LITERALS):
                            offenders.append(f"{rel}:{node.lineno} → {lit.value!r}")
        assert not offenders, (
            "#641: inline unit normalization outside coordinator/units.py — "
            "use power_state_to_watts()/energy_state_to_kwh()/is_energy_unit():\n  "
            + "\n  ".join(offenders)
        )

    def test_the_known_divergent_copies_are_gone(self):
        """Named sites from the #641 sweep, pinned by delegation rather than by
        the AST rule — two of them (``devices/base``, ``ev_taper_detector``) had
        nothing for the AST rule to find, which is precisely why they were the
        worst offenders."""
        expect = {
            "coordinator/energy_calculator.py": "energy_state_to_kwh",
            "coordinator/ev_taper_detector.py": "power_unit_scale",
            "coordinator/ev_control.py": "power_state_to_watts",
            "coordinator/forecast_reader.py": "power_state_to_watts",
            "coordinator/sensor_reader.py": "power_state_to_watts",
            "coordinator/coordinator.py": "power_state_to_watts",
            "devices/base.py": "power_state_to_watts",
            "ha_energy_reader.py": "is_power_unit",
            "config_flow.py": "energy_state_to_kwh",
            "hardware_detection.py": "is_temperature_unit",  # #727
        }
        missing = [
            rel for rel, symbol in expect.items()
            if symbol not in (_ROOT / rel).read_text(encoding="utf-8")
        ]
        assert not missing, f"#641: these no longer route through units.py: {missing}"
