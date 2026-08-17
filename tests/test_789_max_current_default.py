"""#789 — one default for ``ev_max_current``, not thirteen.

Split out of #746. #746 is the enhancement (there is still no
maximum-charging-current field in the UI). This is the defect that hid behind
it: because nothing ever writes the key, EVERY read is a read of its default —
and the defaults did not agree.

``coordinator/build_view.py:202-209`` states it, verified live:

    Nothing writes ``ev_max_current`` or ``ev_voltage`` into that entry — there
    is no config-flow field for either ... A fresh install carries NONE of them.

So this was never an edge case. Six sites defaulted to 32 A (``decide.py`` ×3,
``ev_control.py:156``, ``energy_calculator.py``, ``__init__.py``) and five to
16 A (``ev_control.py:270-271`` and four in ``coordinator.py``).
``ev_control.py`` disagreed with ITSELF: it planned the night-charge ceiling at
32 A and then sized ``_night_deliverable_kwh`` — how much energy the night can
deliver — at 16 A. On a 32 A charger the deliverable came out at exactly half,
so SEM believed it needed to start earlier and book more cheap slots than the
night actually required.

No over-current ever reached hardware: the adapters clamp every command to
``max_current_a`` (``build_view.py:211``) and #678 resolves the view path from
the hardware ceiling. The damage was to the arithmetic, and the paths that read
raw config rather than ``view.config`` never saw #678's resolution — which is
exactly where the split sites lived.

``DEFAULT_MAX_CHARGING_CURRENT = 32`` has existed in ``consts/core.py`` since
the initial release. Every call site simply open-coded its own literal instead
of importing it. (The fossil is still visible in
``test_peak_aware_charging.py``: ``assert safe_current == DEFAULT_MAX_CHARGING_CURRENT  # 16A``
— a comment that has disagreed with the constant it annotates for the whole
life of the repo.)

This is #716's bug class one turn further on: that issue fixed a hardcoded
230 V in ``_compute_night_plan`` while leaving the same literal in
``_night_deliverable_kwh`` forty lines below. Fixing one call site does not
fix a duplicated default — so the second test here is an AST guard over the
whole package rather than an assertion about two functions.
"""
import ast
import pathlib

from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.consts.core import (
    DEFAULT_MAX_CHARGING_CURRENT,
)
from custom_components.solar_energy_management.consts.states import ChargingState
from custom_components.solar_energy_management.coordinator import SEMCoordinator


# The keys that name a charger's maximum current. Both spellings are live:
# the per-charger dicts use ``ev_max_current``, the older top-level config and
# the device factory use ``max_charging_current``.
MAX_CURRENT_KEYS = {"ev_max_current", "max_charging_current"}

PACKAGE = pathlib.Path(__file__).resolve().parent.parent


def _coordinator(fleet=None, charger=None):
    """A coordinator carrying NO ``ev_max_current`` anywhere — the shape
    ``build_view`` documents as what a fresh install actually looks like."""
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
    cfg = {"id": "keba", "ev_min_current": 6, "charge_mode": "min_plus_solar"}
    cfg.update(charger or {})
    coord.config = {
        "ev_chargers": [cfg],
        "ev_phases": 1,
        "target_peak_limit": 6.0,
        "daily_home_consumption_estimate": 18.0,
    }
    coord.config.update(fleet or {})
    coord._load_manager = None
    coord._surplus_controller = None
    coord._night_committed_w = 0.0
    coord._ev_device = None
    coord.time_manager = MagicMock()
    coord.time_manager.get_night_window = MagicMock(return_value=("22:00", "06:00"))
    coord.time_manager.get_night_end_time = MagicMock(return_value="07:00")
    coord.time_manager.get_night_window_hours = MagicMock(return_value=8.0)
    coord.hass = MagicMock()
    coord._tariff_provider = None
    coord._state_machine = MagicMock()
    coord._state_machine.current_state = ChargingState.SOLAR_IDLE
    return coord, cfg


class TestAbsentBehavesLikeTheDocumentedDefault:
    """The invariant that makes a default trustworthy: leaving a key out must
    do what setting it to its documented default does. Anything else means the
    'default' is a different number depending on who is asking."""

    def test_night_deliverable_matches_an_explicit_32_a(self):
        coord, _ = _coordinator()

        absent = coord._night_deliverable_kwh({})
        explicit = coord._night_deliverable_kwh(
            {"ev_max_current": DEFAULT_MAX_CHARGING_CURRENT})

        assert absent == explicit

    def test_night_deliverable_is_the_full_night_not_half_of_it(self):
        """8 h × 32 A × 1 phase × 230 V = 58.88 kWh. The pre-fix 16 A literal
        produced 29.44 — the half-sized night that made SEM over-book."""
        coord, _ = _coordinator()

        assert coord._night_deliverable_kwh({}) == 8.0 * 32 * 1 * 230 / 1000.0

    def test_the_night_plan_ceiling_agrees_with_the_deliverable(self):
        """The two reads that disagreed inside one file. Same config, same
        ceiling: the plan must not size the rate off one number while the
        deliverable is sized off another."""
        coord, cfg = _coordinator()

        absent = coord._night_deliverable_kwh(cfg)
        coord.config["ev_max_current"] = DEFAULT_MAX_CHARGING_CURRENT
        pinned = coord._night_deliverable_kwh(cfg)

        assert absent == pinned

    def test_an_explicit_value_still_wins(self):
        """A user (or #678's hardware resolution) setting a real ceiling must
        still be obeyed — the fix is about the fallback, not the value."""
        coord, _ = _coordinator()

        assert coord._night_deliverable_kwh({"ev_max_current": 16}) == (
            8.0 * 16 * 1 * 230 / 1000.0)


def _mentions_max_current_key(node):
    return any(
        isinstance(n, ast.Constant) and n.value in MAX_CURRENT_KEYS
        for n in ast.walk(node)
    )


def _literal_defaults_for_max_current(path):
    """Every place in ``path`` that names a max-current key and pins a bare
    number to it — i.e. open-codes the default instead of importing the
    constant.

    A default is written two ways here and the guard has to see both, because
    the SPLIT lived in the second one. As a trailing argument:

        cfg.get("ev_max_current", 32)
        _pc("ev_max_current", 32)
        _cfg_charger(ccfg, "max_charging_current", 32)

    and as an ``or`` fallback, which is not an argument at all:

        int(charger_cfg.get("ev_max_current") or 16)
        cfg.get("ev_max_current") or self.config.get("ev_max_current", 16)

    A guard that only understood the first shape would have reported the two
    ``ev_control`` sites and missed three 16s in ``coordinator.py`` — passing
    while the disagreement it exists to prevent was still in the tree.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for i, arg in enumerate(node.args[:-1]):
                if not (isinstance(arg, ast.Constant)
                        and arg.value in MAX_CURRENT_KEYS):
                    continue
                nxt = node.args[i + 1]
                if isinstance(nxt, ast.Constant) and isinstance(nxt.value, (int, float)):
                    found.append((node.lineno, arg.value, nxt.value))
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            last = node.values[-1]
            if not (isinstance(last, ast.Constant)
                    and isinstance(last.value, (int, float))):
                continue
            if any(_mentions_max_current_key(v) for v in node.values[:-1]):
                found.append((node.lineno, "ev_max_current", last.value))
    return sorted(set(found))


class TestNoOpenCodedDefaultSurvives:
    """The anti-drift pin. #716 fixed one hardcoded literal and left its twin
    forty lines away; a per-site fix cannot close a duplicated default, so the
    guard is over the package."""

    def test_no_module_open_codes_a_max_current_default(self):
        offenders = {}
        for path in sorted(PACKAGE.rglob("*.py")):
            rel = path.relative_to(PACKAGE)
            if rel.parts[0] in ("tests", "consts", "node_modules"):
                continue
            hits = _literal_defaults_for_max_current(path)
            if hits:
                offenders[str(rel)] = hits

        assert not offenders, (
            "open-coded max-current defaults — import "
            "DEFAULT_MAX_CHARGING_CURRENT from consts.core instead:\n"
            + "\n".join(
                f"  {f}:{ln} {key} -> {val}"
                for f, hits in offenders.items()
                for ln, key, val in hits
            )
        )

    def test_the_guard_can_actually_see_both_shapes(self):
        """A lint that never fires is indistinguishable from a lint that is
        broken. Feed it both shapes it exists to catch — the ``or`` form is
        the one the first draft of this guard walked straight past."""
        probe = pathlib.Path(__file__).parent / "_789_probe.py"
        probe.write_text(
            'a = cfg.get("ev_max_current", 16)\n'
            'b = int(cfg.get("ev_max_current") or 16)\n'
            'c = _cfg_charger(ccfg, "max_charging_current", 32)\n',
            encoding="utf-8",
        )
        try:
            assert _literal_defaults_for_max_current(probe) == [
                (1, "ev_max_current", 16),
                (2, "ev_max_current", 16),
                (3, "max_charging_current", 32),
            ]
        finally:
            probe.unlink()

    def test_the_guard_does_not_fire_on_the_fixed_shape(self):
        """The inverse fence: importing the constant must satisfy it, or the
        guard would simply be unsatisfiable and get deleted by the next person."""
        probe = pathlib.Path(__file__).parent / "_789_probe_ok.py"
        probe.write_text(
            'a = cfg.get("ev_max_current", DEFAULT_MAX_CHARGING_CURRENT)\n'
            'b = int(cfg.get("ev_max_current") or DEFAULT_MAX_CHARGING_CURRENT)\n'
            'c = cfg.get("ev_max_current")\n',
            encoding="utf-8",
        )
        try:
            assert _literal_defaults_for_max_current(probe) == []
        finally:
            probe.unlink()
