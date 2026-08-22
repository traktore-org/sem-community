"""#828 — the bounds surface may not get worse, and the guard must say how blind it is.

Bug class 50 ("a field narrower than the thing it describes") produced four
user-reported bugs — #717, #746, #813, #826 — before anyone asked why the same
shape kept arriving. The structural closure (one table, both surfaces generated
from it) is real work. This is the cheap half that holds the line meanwhile.

Two properties, and both must be able to FAIL — today's other lesson was a
release gate that had never once run and could not have refused anything.

1. No two pages may declare the same setting with different bounds. That is
   #813 in miniature: a value saved on one page and refused by the other. The
   audit found `battery_capacity_kwh` doing exactly this (min 5/step 1 vs
   min 1/step 0.5) on its first honest run — nobody had reported it.
2. The page/entity guard's coverage may not silently fall. `#813`'s guard calls
   itself "the systemic guard"; measured, it sees 5 of 45 fields, because it can
   only pair fields that HAVE an entity twin. Its own no-vacuous-pass floor is
   satisfied by duplicate matches of those same 5 keys, so it cannot notice
   going blind. This records the number so a regression is visible.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "audit_bounds", _ROOT / "scripts" / "audit_bounds.py")
_audit = importlib.util.module_from_spec(_spec)
import sys as _sys
_sys.modules["audit_bounds"] = _audit
_spec.loader.exec_module(_audit)

_bspec = importlib.util.spec_from_file_location(
    "bounds", _ROOT / "consts" / "bounds.py")
_bounds = importlib.util.module_from_spec(_bspec)
_sys.modules["bounds"] = _bounds
_bspec.loader.exec_module(_bounds)

# Measured 2026-08-21, AFTER the first migration tranche. A field is guarded
# when it comes from consts/bounds.py (cannot drift, by construction) or when
# it has an entity twin the old page/entity check can compare. RAISE this as
# fields move into the table; never lower it to make a red build green — a
# falling number is the surface going unguarded, which is the thing watched.
MIN_GUARDED_FIELDS = 8
MIN_TOTAL_SURFACE = 45


@pytest.mark.unit
class TestTheBoundsSurfaceDoesNotGetWorse:

    def test_the_scan_still_sees_the_surface(self):
        """No-vacuous-pass: a reformat of config_flow.py must not quietly
        reduce this whole file to assertions about an empty dict. The surface
        is hardcoded fields PLUS table rows — migrating a field moves it
        between the two, it does not shrink the surface."""
        surface = len(_audit.flow_fields()) + len(_bounds.BOUNDS)
        assert surface >= MIN_TOTAL_SURFACE, (
            f"only {surface} number settings found — the scan broke, and "
            "every assertion below is now vacuous"
        )

    def test_no_setting_is_declared_with_two_different_bounds(self):
        """One setting, one range. Two pages disagreeing means a value saved
        on one is refused by the other — #813, in miniature."""
        contradictions = {
            k: sorted(v) for k, v in _audit.flow_fields().items() if len(v) > 1
        }
        assert not contradictions, (
            "the same setting is offered with different bounds on different "
            "pages:\n" + "\n".join(
                f"  {k}: {v}" for k, v in contradictions.items())
        )

    def test_the_guarded_share_has_not_fallen(self):
        """Coverage may only go up. Table rows count as guarded because they
        cannot drift at all; entity-paired fields count because the older
        page/entity check can still compare them."""
        fields, ents = _audit.flow_fields(), _audit.entity_bounds()
        paired = {k for k in fields if k in ents}
        guarded = len(_bounds.BOUNDS) + len(paired)
        assert guarded >= MIN_GUARDED_FIELDS, (
            f"only {guarded} settings are guarded, down from "
            f"{MIN_GUARDED_FIELDS} — either a field left the table or lost its "
            "entity twin. Less of the bounds surface is checked than yesterday"
        )

    def test_no_page_is_narrower_than_its_entity(self):
        """#813's own property, re-asserted here against the anchored scan
        rather than the original guard's looser one."""
        fields, ents = _audit.flow_fields(), _audit.entity_bounds()
        narrow = [
            (k, f, ents[k]) for k, fs in fields.items() if k in ents
            for f in fs if f[0] > ents[k][0] or f[1] < ents[k][1]
        ]
        assert not narrow, (
            "options pages narrower than the entity that writes the value:\n"
            + "\n".join(f"  {k}: page {f} vs entity {e}" for k, f, e in narrow)
        )
