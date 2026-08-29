"""#813 — an options page must accept the state SEM itself stored.

Two live failures, both found configuring PROD (20.08):

1. ``daily_ev_target_max`` — the runtime entity spans 0–200 kWh (#746/#680),
   but all three options-flow pages capped the field at 100, so a user with
   a max target above 100 could never re-save those pages: the form 400s on
   its own suggested value.
2. ``emergency_peak_level`` — stored EQUAL to ``target_peak_limit`` (6.0/6.0
   on PROD) while the page demands emergency strictly above target. Here the
   validator is RIGHT: ``load_management`` already treats ``emergency <=
   target`` as a broken ladder and repairs it for decisions, because the
   EMERGENCY branch would otherwise win before SHEDDING is ever considered.
   The bug is that the state was reachable at all — raising the target via
   the Control-tab slider left the ladder inverted in the STORED config.

The class: **every writer must leave a state its own form would accept.**
"""
class TestTargetMaxBounds:
    """The flow's bounds must match the entity the value comes from."""

    def _flow_bounds(self, key):
        import re, pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "config_flow.py").read_text()
        out = []
        for m in re.finditer(rf'"{key}",\n(?:.*\n){{0,4}}?.*?NumberSelectorConfig\(\s*\n?\s*min=([\d.]+), max=([\d.]+)', src):
            out.append((float(m.group(1)), float(m.group(2))))
        return out

    def _entity_bounds(self, key):
        import re, pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "number.py").read_text()
        m = re.search(rf'key=f?"[^"]*{key}",(?:.*\n){{0,8}}?.*?native_min_value=([\d.]+), native_max_value=([\d.]+)', src)
        return (float(m.group(1)), float(m.group(2))) if m else None

    def test_every_flow_page_spans_the_entity_range(self):
        """#828 note: this key now comes from `consts/bounds.py`, so the flow
        carries no literals to compare and the property is guaranteed by
        construction rather than checked here. The assertion moved DOWN a
        level — the table's range must match the entity's — which is the same
        promise with one fewer way to break."""
        ent = self._entity_bounds("daily_ev_target_max")
        assert ent == (0.0, 200.0), f"premise moved: entity is {ent}"
        pages = self._flow_bounds("daily_ev_target_max")
        if pages:
            bad = [p for p in pages if p != ent]
            assert not bad, (
                f"options pages cap daily_ev_target_max at {bad} while the "
                f"entity allows {ent} — a user above the cap cannot re-save")
            return
        # Migrated: assert the table agrees with the entity instead.
        import importlib.util
        import pathlib as _pl
        import sys as _sys
        _root = _pl.Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "bounds", _root / "consts" / "bounds.py")
        mod = importlib.util.module_from_spec(spec)
        _sys.modules["bounds"] = mod
        spec.loader.exec_module(mod)
        r = mod.BOUNDS["daily_ev_target_max"]
        assert (r.min, r.max) == ent, (
            f"consts/bounds.py says {(r.min, r.max)} but the entity allows "
            f"{ent} — the single declaration disagrees with the value it writes")


class TestPeakLadderStaysCoherent:
    """Raising the target must carry the ladder, so the stored state is one
    the options page accepts."""

    def _mgr(self, target=5.0, warning=4.5, emergency=6.0):
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.features.load_management import (
            LoadManagementCoordinator,
        )
        entry = MagicMock()
        entry.options = {"target_peak_limit": target,
                         "warning_peak_level": warning,
                         "emergency_peak_level": emergency}
        entry.data = {}
        entry.runtime_data = None
        hass = MagicMock()
        stored = {}
        def _update(_entry, options=None, **kw):
            stored.clear(); stored.update(options or {})
        hass.config_entries.async_update_entry = _update
        mgr = LoadManagementCoordinator.__new__(LoadManagementCoordinator)
        mgr.hass = hass
        mgr.config_entry = entry
        mgr._target_peak_limit = target
        mgr._warning_level = warning
        mgr._emergency_level = emergency
        mgr._peak_unlimited = False
        mgr._logged_ladder_repair = False
        mgr._trigger_callbacks = lambda: None
        return mgr, stored

    def test_raising_the_target_past_emergency_carries_the_ladder(self):
        import asyncio
        mgr, stored = self._mgr(target=5.0, warning=4.5, emergency=6.0)
        asyncio.run(mgr.update_target_peak_limit(6.0))   # PROD's exact move
        assert stored["target_peak_limit"] == 6.0
        assert stored["emergency_peak_level"] > 6.0, (
            "emergency must stay above the target — the stored ladder was "
            "left inverted and the options page then refused to save")
        assert stored["warning_peak_level"] < 6.0

    def test_lowering_the_target_leaves_a_healthy_ladder_alone(self):
        import asyncio
        mgr, stored = self._mgr(target=5.0, warning=4.5, emergency=6.0)
        asyncio.run(mgr.update_target_peak_limit(4.0))
        assert stored["target_peak_limit"] == 4.0
        assert stored["emergency_peak_level"] == 6.0, "untouched: already above"
        assert stored["warning_peak_level"] == 4.5 or stored["warning_peak_level"] < 4.0

    def test_the_stored_state_passes_the_pages_own_validator(self):
        """The point of the whole issue: what we store, the form accepts."""
        import asyncio
        mgr, stored = self._mgr(target=5.0, warning=4.5, emergency=6.0)
        asyncio.run(mgr.update_target_peak_limit(6.0))
        t = float(stored["target_peak_limit"])
        w = float(stored["warning_peak_level"])
        e = float(stored["emergency_peak_level"])
        assert not (w >= t), "would raise peak_warning_not_below_target"
        assert not (e <= t), "would raise peak_emergency_not_above_target"


class TestEveryFlowFieldSpansItsEntity:
    """The systemic guard (#813's real ask): a number the user can set on an
    ENTITY must be settable on the options PAGE that also offers it. When
    the two drift, the page rejects a value SEM itself wrote — which is how
    both live failures were found. Pairs are matched by config key."""

    def _pairs(self):
        import re, pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        flow = (root / "config_flow.py").read_text()
        num = (root / "number.py").read_text()
        ent = {}
        for m in re.finditer(
                r'key=f?"(?:charger_\{cid\}_)?([a-z_0-9]+)",(?:.*\n){0,10}?'
                r'.*?native_min_value=([\d.]+), native_max_value=([\d.]+)', num):
            ent.setdefault(m.group(1), (float(m.group(2)), float(m.group(3))))
        out = []
        for m in re.finditer(
                r'"([a-z_0-9]+)",\n(?:.*\n){0,5}?.*?NumberSelectorConfig\(\s*\n?\s*'
                r'min=([\d.]+), max=([\d.]+)', flow):
            key, lo, hi = m.group(1), float(m.group(2)), float(m.group(3))
            if key in ent:
                out.append((key, (lo, hi), ent[key]))
        return out

    def test_no_flow_field_is_narrower_than_its_entity(self):
        narrow = [
            (k, f, e) for k, f, e in self._pairs()
            if f[0] > e[0] or f[1] < e[1]
        ]
        assert not narrow, (
            "options pages narrower than the entity that writes the value — a "
            "user at the entity's extreme cannot re-save the page:\n"
            + "\n".join(f"  {k}: page {f} vs entity {e}" for k, f, e in narrow))

    def test_the_guard_actually_sees_pairs(self):
        """No-vacuous-pass: the scan must find real settings, or it proves
        nothing when someone reformats either file.

        #828: a migrated field leaves this scan (it has no literals left) and
        joins `consts/bounds.py`, where it cannot drift at all. So the floor
        counts BOTH — literal pairs plus table rows — and a field moving
        between them is progress, not a broken scan. The old floor was 5 and
        counted duplicate matches of the same 5 keys, which is how it would
        have passed while going blind."""
        import importlib.util
        import pathlib as _pl
        import sys as _sys
        _root = _pl.Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "bounds", _root / "consts" / "bounds.py")
        mod = importlib.util.module_from_spec(spec)
        _sys.modules["bounds"] = mod
        spec.loader.exec_module(mod)
        covered = len(self._pairs()) + len(mod.BOUNDS)
        assert covered >= 5, (
            f"only {covered} settings covered (literal pairs + table rows) — "
            "the scan broke")
