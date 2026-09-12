"""#933 guard — every Repair clear that hides behind a lifetime memo says
who clears the Repair a PREVIOUS lifetime left.

The class (docs/BUG_CLASSES.md #84): HA's issue registry keeps a persistent
Repair across restarts, and a config-entry reload does not touch it at all.
A clear that runs only when an in-memory flag — reset by every restart and
every reload — says THIS lifetime raised it, or only when a verdict CHANGES
from a memo whose empty value is itself a verdict, swallows the first healthy
verdict of a fresh owner: the Repair outlives every memo that could clear it.
#933: the pin Repair survived its own remedy, because the remedy reloads.

The rule is mechanical, not a naming heuristic. A clear site is MEMO-GATED
when a condition guarding it — an enclosing if/while/for, or an earlier early
exit in the same block — reads instance state the SAME function also writes:
the defining trait of an edge memo. Thin wrappers around a clear (≤ 12
statements, ungated inside) count as clears at their call sites. Every
memo-gated function is declared below with its answer to the one question
the class asks. A new one fails CI until someone answers it; a declaration
whose site is gone fails too.

What it cannot see (the review's probe, recorded so nobody trusts it
further): a memo kept on a helper object built elsewhere (``if
self._w.changed``), a raised-set mutated only through a helper method, a
memo in ``hass.data``, and a clear delivered as an action (#823's
``CLEAR_FAILSAFE_SUSPECTED``). The behaviour tests in
test_933_first_verdict_of_a_lifetime.py prove the fixes; this file makes
each new site ask the question.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_NOT_PRODUCTION = {"tests", "scripts", "tools", "docs", "dashboard", "brand",
                   "translations", "__pycache__"}
_MUTATORS = frozenset({"add", "discard", "remove", "clear", "pop", "popitem",
                       "update", "setdefault", "append", "extend", "insert"})
_EXITS = (ast.Return, ast.Continue, ast.Break, ast.Raise)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_THIN = 12

#: Every memo-gated clear site → how a Repair left by a previous lifetime
#: (before a restart, or before an options reload) gets cleared.
DECLARED: dict[str, str] = {
    "coordinator/battery_adapters/base.py::BatteryControlAdapter._write_force_discharge":
        "the first accepted write of each adapter lifetime clears once "
        "(_force_discharge_repair_reconciled, #933); a refused write proves nothing",
    "coordinator/charger_reconciler.py::ChargerReconciler._retire_stand_down":
        "the memo starts at None, not False, so a fresh reconciler clears "
        "once on its first retire (#944); the Repair is non-persistent anyway",
    "coordinator/coordinator.py::SEMCoordinator._async_update_data":
        "not a Repair memo: _effective_states_per_charger is this cycle's "
        "per-charger state, and _maybe_warn_soc_cap raises or clears on the "
        "current verdict every cycle",
    "coordinator/coordinator.py::SEMCoordinator._check_battery_platform_pin":
        "the verdict memo means 'decided yet?' (hasattr), never None; one "
        "install-wide verdict once every battery answered this cycle, and "
        "none while a brand entry is still loading (#933)",
    "coordinator/coordinator.py::SEMCoordinator._check_charger_control_entities":
        "the first valid verdict per (charger, entity) of each lifetime "
        "clears once (_control_repair_reconciled, #933)",
    "coordinator/coordinator.py::SEMCoordinator._check_soc_zone_order":
        "the memo starts at None but the verdict is a bool, never None, so "
        "a lifetime's first verdict always acts (pinned in test_933)",
    "coordinator/coordinator.py::SEMCoordinator._raise_or_clear_battery_write_repair":
        "the entity a reflected write proves is cleared once per lifetime "
        "(last_verified_entity, _battery_write_reconciled, #933)",
    "coordinator/coordinator.py::SEMCoordinator._run_battery_pipeline":
        "the mode watch's first expected reading is a clear edge "
        "(BatteryModeWatch._settled, #933); a restart drops the "
        "non-persistent Repair, an options reload does not",
    "coordinator/coordinator.py::SEMCoordinator._update_analytics_phases":
        "the relay and hot-water Repairs raise or clear on the current state "
        "every cycle; the memo only gates the once-per-lifetime orphan sweep",
    "coordinator/forecast_reader.py::ForecastReader._clear_no_forecast_repair":
        "the first successful detection of each reader lifetime clears once "
        "(_no_forecast_reconciled, #933)",
    "coordinator/sensor_reader.py::SensorReader._audit_sensor_freshness":
        "cleared once this reader has SEEN the entity report past the stamp "
        "it first saw (_stale_reconciled, #933); a restored stamp is no proof",
    "coordinator/sensor_reader.py::SensorReader._read_from_energy_dashboard":
        "any read by an explicit path — SEM's own pair (the Repair's remedy, "
        "which reloads), a declared pair, a combined sensor — clears the "
        "guess Repair once per reader (_split_guess_reconciled, #933); the "
        "startup sweep never runs on a reload",
    "coordinator/sensor_reader.py::SensorReader._read_sensor":
        "the first live read of each reader lifetime clears once "
        "(_sensor_repair_reconciled, #933)",
    "devices/base.py::CurrentControlDevice._note_enable_unblocked":
        "NOT a first-of-lifetime clear, on purpose (#945): the issue id is "
        "shared with the write side (#462) and an unblocked enable switch is "
        "no evidence that current commands land — a KEBA/service/button "
        "charger has no switch at all, so clearing on its first cycle would "
        "delete a genuine 'every command rejected' Repair. A predecessor's "
        "Repair on this id is retired by #485 H5's first-good-write clear "
        "(_stale_repair_checked), which IS evidence SEM can command it",
    "devices/base.py::CurrentControlDevice._clear_actuation_failure":
        "the first good write of each device instance clears once "
        "(_stale_repair_checked, #485 H5)",
    "features/load_management.py::LoadManagementCoordinator._shed_toward":
        "the first reachable plan of each shedder lifetime clears once "
        "(_futile_reconciled, #933)",
}


# ── the detector ─────────────────────────────────────────────────────────


def _self_attr(node):
    """'X' for ``self.X`` and ``getattr/hasattr/setattr(self, "X", …)``."""
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "self"):
        return node.attr
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("getattr", "hasattr", "setattr")
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name) and node.args[0].id == "self"
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)):
        return node.args[1].value
    return None


def _own_nodes(fn):
    """fn's body, not descending into nested scopes."""
    stack = list(fn.body)
    while stack:
        n = stack.pop()
        yield n
        stack.extend(c for c in ast.iter_child_nodes(n)
                     if not isinstance(c, _SCOPES))


def _state_of(expr, derived) -> set[str]:
    """The instance state an expression is computed from."""
    out: set[str] = set()
    for n in ast.walk(expr):
        a = _self_attr(n)
        if a:
            out.add(a)
        elif isinstance(n, ast.Name):
            out |= derived.get(n.id, set())
    return out


def _memos(fn):
    """Instance state this function WRITES — its memos — and what each local
    name was computed from (``raised = getattr(self, "_x", None)``,
    ``stale = set(raised)``)."""
    nodes = list(_own_nodes(fn))
    assigns = [n for n in nodes if isinstance(n, ast.Assign)]
    direct: dict[str, str] = {}
    for n in assigns:
        src = next((a for a in map(_self_attr, n.targets) if a), None) \
            or _self_attr(n.value)
        if src:
            for t in n.targets:
                if isinstance(t, ast.Name):
                    direct[t.id] = src
    derived: dict[str, set[str]] = {k: {v} for k, v in direct.items()}
    for _ in range(4):                          # a short fixpoint is plenty
        for n in assigns:
            src = _state_of(n.value, derived)
            for t in n.targets:
                if isinstance(t, ast.Name) and src - derived.get(t.id, set()):
                    derived.setdefault(t.id, set()).update(src)

    def base(expr):
        if isinstance(expr, ast.Name):
            return direct.get(expr.id)
        return _self_attr(expr)

    def targets(t):
        if isinstance(t, (ast.Tuple, ast.List)):
            return [a for e in t.elts for a in targets(e)]
        if isinstance(t, ast.Subscript):
            return [a for a in [base(t.value)] if a]
        return [a for a in [_self_attr(t)] if a]

    written: set[str] = set()
    for n in nodes:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                written.update(targets(t))
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            written.update(targets(n.target))
        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr in _MUTATORS:
                written.update(a for a in [base(f.value)] if a)
            elif isinstance(f, ast.Name) and f.id == "setattr":
                written.update(a for a in [_self_attr(n)] if a)
    return written, derived


def _guards(fn, call):
    """Every condition that decides whether ``call`` runs."""
    parents = {top: fn for top in fn.body}
    for n in _own_nodes(fn):
        for c in ast.iter_child_nodes(n):
            parents[c] = n
    conds, child, node = [], call, parents.get(call)
    while node is not None:
        if isinstance(node, (ast.If, ast.While, ast.IfExp)) and child is not node.test:
            conds.append(node.test)
        elif isinstance(node, (ast.For, ast.AsyncFor)) and child in node.body:
            conds.append(node.iter)
        elif isinstance(node, ast.BoolOp) and child in node.values:
            conds.extend(node.values[:node.values.index(child)])
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and child in block:
                for stmt in block[:block.index(child)]:
                    if isinstance(stmt, ast.If) and any(
                            isinstance(x, _EXITS) for s in stmt.body + stmt.orelse
                            for x in ast.walk(s)):
                        conds.append(stmt.test)
        if node is fn:
            break
        child, node = node, parents.get(node)
    return conds


def _functions(tree, prefix=""):
    for n in ast.iter_child_nodes(tree):
        if isinstance(n, ast.ClassDef):
            yield from _functions(n, f"{prefix}{n.name}.")
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield f"{prefix}{n.name}", n
            yield from _functions(n, f"{prefix}{n.name}.")


def _callee(call):
    f = call.func
    return f.id if isinstance(f, ast.Name) else (
        f.attr if isinstance(f, ast.Attribute) else None)


def _clear_calls(fn, names):
    return [n for n in _own_nodes(fn)
            if isinstance(n, ast.Call) and _callee(n) in names]


def _gating_memos(fn, names) -> set[str]:
    written, derived = _memos(fn)
    return {m for call in _clear_calls(fn, names)
            for c in _guards(fn, call) for m in _state_of(c, derived) & written}


def memo_gated_sites(sources: dict[str, str], clears: set[str]) -> dict[str, set[str]]:
    """``{"path::Qual.name": memos}`` for every function whose Repair clear —
    direct, or through a thin wrapper — is guarded by a memo it writes."""
    funcs = [(path, qual, fn) for path, src in sources.items()
             for qual, fn in _functions(ast.parse(src))]
    wrappers = {fn.name for _p, _q, fn in funcs
                if _clear_calls(fn, clears) and not _gating_memos(fn, clears)
                and sum(isinstance(n, ast.stmt) for n in _own_nodes(fn)) <= _THIN}
    names = clears | wrappers
    out = {}
    for path, qual, fn in funcs:
        memos = _gating_memos(fn, names)
        if memos:
            out[f"{path}::{qual}"] = memos
    return out


def _production_sources() -> dict[str, str]:
    out = {}
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT)
        if rel.parts[0] in _NOT_PRODUCTION or any(
                part.startswith(".") for part in rel.parts):
            continue
        out[rel.as_posix()] = p.read_text(encoding="utf-8")
    return out


def _repair_clears() -> set[str]:
    tree = ast.parse((ROOT / "coordinator" / "repair_issues.py").read_text())
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.name.startswith("clear_")} | {"async_delete_issue"}


def found_sites() -> dict[str, set[str]]:
    return memo_gated_sites(_production_sources(), _repair_clears())


# ── the guard ────────────────────────────────────────────────────────────


def test_every_memo_gated_clear_answers_the_lifetime_question():
    found = found_sites()
    undeclared = set(found) - set(DECLARED)
    assert not undeclared, (
        "A Repair clear is gated on a memo its own function writes:\n  "
        + "\n  ".join(f"{s}  (memo: {', '.join(sorted(found[s]))})"
                      for s in sorted(undeclared))
        + "\nThe memo dies with every restart and every options reload; a "
        "persistent Repair does not. Who clears the Repair a PREVIOUS "
        "lifetime left? Fix it (the first healthy verdict of a fresh owner "
        "clears once — #933) and declare the answer in DECLARED "
        "(docs/BUG_CLASSES.md #84).")


def test_no_declaration_outlives_its_site():
    gone = set(DECLARED) - set(found_sites())
    assert not gone, (
        "Declared memo-gated clear sites that no longer exist (moved, "
        "renamed, or no longer memo-gated) — update DECLARED:\n  "
        + "\n  ".join(sorted(gone)))


def test_every_declaration_says_something():
    assert all(len(v.split()) >= 6 for v in DECLARED.values())


# ── the detector can fire (the #660 no-vacuous-check discipline) ─────────

_SHAPES = '''
class C:
    def pin(self, pinned):                      # #933: early-return memo
        seen = getattr(self, "_seen", None)
        if seen is None:
            seen = self._seen = {}
        if seen.get("b") == pinned:
            return
        seen["b"] = pinned
        if pinned:
            raise_x(self.hass)
        else:
            clear_x(self.hass)

    def raised_set(self, ok):                   # #824: enclosing-if memo
        if ok and "e" in self._raised:
            self._raised.discard("e")
            clear_x(self.hass)

    def loop_over_memo(self, ok):               # #915: the memo is the loop
        raised = getattr(self, "_r", None)
        if raised is None:
            raised = self._r = set()
        if ok:
            stale = set(raised)
            for eid in sorted(stale):
                clear_x(self.hass, eid)
            raised.clear()

    def _clear_wrapper(self):
        clear_x(self.hass)

    def through_wrapper(self, ok):              # #840: gate at the caller
        if ok and self._fails:
            self._fails = 0
            self._clear_wrapper()

    def reads_but_never_writes(self, ok):       # a reading, not a memo
        if ok and self._last_connected:
            clear_x(self.hass)

    def unconditional(self, ok):
        if ok:
            clear_x(self.hass)
'''


def test_the_detector_fires_on_every_shape_and_only_there():
    found = memo_gated_sites({"m.py": _SHAPES}, {"clear_x"})
    assert set(found) == {"m.py::C.pin", "m.py::C.raised_set",
                          "m.py::C.loop_over_memo",
                          "m.py::C.through_wrapper"}, found
    assert found["m.py::C.pin"] == {"_seen"}


def test_the_detector_sees_the_tree():
    """A walker that silently parsed nothing would pass the guard above."""
    assert len(found_sites()) >= 10
