"""#828 — one range, declared once, both surfaces generated from it.

Bug class 50 produced four reported bugs (#717, #746, #813, #826) and two
more the audit found unreported, all from the same structure: every tunable's
range is written twice — a `NumberSelectorConfig(min,max)` in `config_flow.py`
and `native_min_value/native_max_value` in `number.py` — with nothing deriving
one from the other. Agreement was a coincidence maintained by hand.

`consts/bounds.py` is the single declaration. These tests pin the properties
that make the class *unrepresentable* for every migrated field, and — through
a shrink-only allowlist — make the remaining migration inevitable rather than
aspirational. A field cannot drift from itself.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load(name, rel):
    """Load a module by path, WITHOUT triggering the package __init__.

    ``sys.modules[name]`` must be set before ``exec_module``: a @dataclass in
    the loaded module resolves ``cls.__module__`` through sys.modules while
    being built, and finds None otherwise. The repo's other spec-loaded module
    (hardware_matrix) has no dataclasses, so this never came up before.
    """
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_bounds = _load("bounds", "consts/bounds.py")
_audit = _load("audit_bounds", "scripts/audit_bounds.py")

# Number fields in config_flow.py that still hardcode their own bounds.
# SHRINK ONLY. Removing a name here (by migrating it to consts/bounds.py) is
# the point; adding one is refused by the test below, which is what makes the
# migration finish instead of stalling at "we should do that sometime".
_UNMIGRATED = {
    # SEEDED 2026-08-21 from the code as it stood. Every name here is a
    # number field still declaring its own bounds. Remove names by moving
    # them into consts/bounds.py; the test below refuses NEW ones, which
    # is what makes this migration finish rather than stall.
    #
    # vehicle_min_current is a deliberate holdout, not a leftover: its
    # page (1-32 A) is wider than its entity (6-32 A), and picking one is
    # a decision about charging behaviour entangled with #752, not a
    # refactor.
    "battery_assist_max_power",
    "battery_assist_min_surplus",
    "battery_auto_start_soc",
    "battery_buffer_soc",
    "battery_cycle_cost",
    "battery_max_charge_power_w",
    "battery_max_discharge_power",
    "battery_max_target_soc",
    "battery_min_deficit_kwh",
    "battery_pessimism_weight",
    "battery_precharge_trigger_hour",
    "battery_priority_soc",
    "battery_replan_interval_min",
    "battery_roundtrip_efficiency",
    "demand_charge_rate",
    "deye_battery_voltage_max_age_s",
    "deye_max_discharge_power",
    "electricity_export_rate",
    "electricity_import_rate",
    "electricity_off_peak_rate",
    "ev_charger_efficiency",
    "ev_min_current",
    "ev_surplus_priority",
    "ev_target_soc",
    "ev_target_soc_max",
    "grid_import_surcharge",
    "heat_pump_boost_offset",
    "heat_pump_max_setpoint",
    "heat_pump_priority",
    "initial_current",
    "minimum_solar_power",
    "phase_guard_grid_limit_a",
    "phase_guard_inverter_limit_a",
    "phase_guard_max_age_s",
    "phase_guard_recovery_cycles",
    "phase_guard_recovery_margin_a",
    "update_interval",
    "vehicle_min_current",
}


@pytest.mark.unit
class TestTheTableIsTheDeclaration:

    def test_every_row_is_a_real_range(self):
        assert _bounds.BOUNDS, "the table is empty"
        for key, r in _bounds.BOUNDS.items():
            assert r.min < r.max, f"{key}: min {r.min} not below max {r.max}"
            assert r.step > 0, f"{key}: step must be positive"

    def test_no_orphan_rows(self):
        """A row nobody builds from is a claim with no consumer — the shape
        that let `custom_entities` sit unreachable in the forecast reader."""
        flow = (_ROOT / "config_flow.py").read_text()
        num = (_ROOT / "number.py").read_text()
        for key in _bounds.BOUNDS:
            assert f'"{key}"' in flow or f'"{key}"' in num, (
                f"{key} is declared in consts/bounds.py but no surface uses it"
            )

    def test_declared_relations_hold(self):
        """#826: SEM's write ceiling must reach the BMS ceiling it sits under.
        The relationship now has a place to live, so it can be checked."""
        for key, r in _bounds.BOUNDS.items():
            if r.at_most:
                other = _bounds.BOUNDS[r.at_most]
                assert r.max >= other.max, (
                    f"{key} caps at {r.max} but must be settable up to "
                    f"{r.at_most}'s {other.max} — that is #826 exactly"
                )


@pytest.mark.unit
class TestBothSurfacesComeFromTheTable:

    def test_migrated_fields_no_longer_hardcode_bounds(self):
        """The property that makes drift unrepresentable: for a migrated key,
        config_flow.py must not contain its own min=/max= literals."""
        flow = (_ROOT / "config_flow.py").read_text()
        chunks = re.split(r'(?=vol\.(?:Optional|Required)\(\s*\n\s*")', flow)
        offenders = []
        for chunk in chunks:
            m = re.match(r'vol\.(?:Optional|Required)\(\s*\n\s*"([a-z_0-9]+)"', chunk)
            if not m or m.group(1) not in _bounds.BOUNDS:
                continue
            if re.search(r'NumberSelectorConfig\(\s*\n?\s*min=', chunk):
                offenders.append(m.group(1))
        assert not offenders, (
            "these keys are in the table but the flow still hardcodes their "
            f"bounds, so the two can drift again: {sorted(set(offenders))}"
        )

    def test_entity_bounds_match_the_table(self):
        """Where a migrated key also has a runtime entity, the entity's range
        is the table's range — by construction, not by coincidence."""
        ents = _audit.entity_bounds()
        for key, r in _bounds.BOUNDS.items():
            if key not in ents:
                continue
            assert ents[key] == (r.min, r.max), (
                f"{key}: entity {ents[key]} != table ({r.min}, {r.max})"
            )


@pytest.mark.unit
class TestTheMigrationIsForced:

    def test_the_allowlist_only_shrinks(self):
        """A number field must either come from the table or be a KNOWN
        holdout. Adding a new hardcoded field fails here — which is what makes
        this finish rather than stall."""
        flow = _audit.flow_fields()
        hardcoded = set(flow) - set(_bounds.BOUNDS)
        new = hardcoded - _UNMIGRATED
        assert not new, (
            "number fields hardcoding their bounds outside the allowlist — "
            "declare them in consts/bounds.py instead:\n  "
            + "\n  ".join(sorted(new))
        )

    def test_no_stale_allowlist_entries(self):
        flow = _audit.flow_fields()
        stale = _UNMIGRATED - (set(flow) - set(_bounds.BOUNDS))
        assert not stale, (
            f"allowlist entries already migrated — remove them: {sorted(stale)}"
        )
