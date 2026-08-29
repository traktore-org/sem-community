"""#737 — every options/config-flow schema field must have a label.

Home Assistant renders a form field's label by looking up
``component.<domain>.<block>.step.<step>.data.<key>``; when the key is absent
the frontend falls back to the raw ``snake_case`` key. So a ``vol.Optional`` /
``vol.Required`` added to an ``async_step_*`` schema with no matching entry in
``strings.json`` ships as an illegible field — silently, because a missing
translation never raises and the step still opens.

This is **bug class 24** (a hand-maintained list mirroring a structure that
grows), the same shape as #674 (the whole Heat Pump step rendered eight raw
keys). #737 was its recurrence: six steps rendered 37 raw keys — *and* the deye
step's 18 loop-built ``deye_program_N_*`` fields, which the manual audit that
opened #737 missed. A count is exactly what this class defeats; a derivation is
what closes it. So this guard does not carry a field list — it reads the fields
out of the schema and asserts each is declared.

Composition with the other guards:
  * this guard      : every schema field  ⊆  ``strings.json`` labels
  * ``test_674``    : ``strings.json``     ==  every ``translations/<lang>.json``
Together they guarantee every schema field resolves to a real label in all 16
languages HA actually loads at runtime (HA never reads ``strings.json`` for a
custom component — only ``translations/<lang>.json``).

Scope: schemas built inline in the step method. A step whose fields are named
from *runtime* data (``pv_naming`` names ``pv_name_{slot}`` from discovered PV
strings) cannot be declared in a static file; those are enumerated explicitly
below with a reason, and the guard fails if that set grows silently.
"""
from __future__ import annotations

import ast
import itertools
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_FLOW = _ROOT / "config_flow.py"
_STRINGS = _ROOT / "strings.json"

# Flow class in config_flow.py -> strings.json block HA localises its steps in.
_CLASS_BLOCK = {
    "SolarEnergyManagementConfigFlow": "config",
    "OptionsFlowHandler": "options",
}

# Steps whose field keys are built from runtime data and therefore cannot be
# declared in a static strings file. Each needs a reason; the guard asserts the
# set does not grow silently (a new runtime-named step is a deliberate decision,
# not a default). Class-24 tell: an exemption *list* is the class one level up —
# keep this to genuinely-undeclarable keys only, never to "not done yet".
_RUNTIME_NAMED_STEPS = {
    # pv_name_{slot}: slots are discovered PV strings (pv1, pv2, … or V×I
    # composites). The step identifies each field through its description
    # mapping instead. (#566)
    "pv_naming",
}


def _literal_range(node: ast.AST) -> list | None:
    """``range(a[, b[, c]])`` with constant int args -> the concrete list."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
        and all(isinstance(a, ast.Constant) and isinstance(a.value, int) for a in node.args)
        and node.args
    ):
        return list(range(*[a.value for a in node.args]))
    if isinstance(node, (ast.Tuple, ast.List)) and all(
        isinstance(e, ast.Constant) for e in node.elts
    ):
        return [e.value for e in node.elts]
    return None


def _resolve_fstring(joined: ast.JoinedStr, bindings: dict) -> str | None:
    """Resolve an f-string to a concrete string given loop-var bindings, or
    None if any interpolated value is not a bound loop variable."""
    parts: list[str] = []
    for piece in joined.values:
        if isinstance(piece, ast.Constant):
            parts.append(str(piece.value))
        elif isinstance(piece, ast.FormattedValue):
            if isinstance(piece.value, ast.Name) and piece.value.id in bindings:
                parts.append(str(bindings[piece.value.id]))
            else:
                return None
        else:
            return None
    return "".join(parts)


def _marker_calls(node: ast.AST) -> list[ast.Call]:
    """Every ``vol.Optional(...)`` / ``vol.Required(...)`` call under ``node``."""
    return [
        n
        for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("Optional", "Required")
        and n.args
    ]


def _enumerate_comprehension(comp: ast.AST) -> tuple[set[str], list[int]]:
    """Concrete keys + unresolved f-string linenos for one comprehension."""
    key_node = comp.key if isinstance(comp, ast.DictComp) else getattr(comp, "elt", None)
    literal: set[str] = set()
    unresolved: list[int] = []
    calls = _marker_calls(key_node) if key_node is not None else []
    if not calls:
        return literal, unresolved

    # Resolve every generator's iterable to a literal list, else bail.
    var_values: list[tuple[str, list]] = []
    resolvable = True
    for gen in comp.generators:
        values = _literal_range(gen.iter)
        if values is None or not isinstance(gen.target, ast.Name):
            resolvable = False
            break
        var_values.append((gen.target.id, values))

    for call in calls:
        arg = call.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            literal.add(arg.value)
        elif isinstance(arg, ast.JoinedStr):
            if not resolvable:
                unresolved.append(call.lineno)
                continue
            names = [v for v, _ in var_values]
            for combo in itertools.product(*[vals for _, vals in var_values]):
                key = _resolve_fstring(arg, dict(zip(names, combo, strict=False)))
                if key is None:
                    unresolved.append(call.lineno)
                    break
                literal.add(key)
        else:
            unresolved.append(call.lineno)
    return literal, unresolved


def _collect() -> tuple[dict[tuple[str, str], set[str]], set[str], list[str]]:
    """Return ({(block, step): literal_keys}, runtime_named_steps, complaints)."""
    tree = ast.parse(_FLOW.read_text(encoding="utf-8"))
    per_step: dict[tuple[str, str], set[str]] = {}
    runtime_steps: set[str] = set()
    complaints: list[str] = []

    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef) or cls.name not in _CLASS_BLOCK:
            continue
        block = _CLASS_BLOCK[cls.name]
        for fn in cls.body:
            if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            if not fn.name.startswith("async_step_"):
                continue
            step = fn.name[len("async_step_"):]
            literal: set[str] = set()
            unresolved: list[int] = []

            comps = [
                n
                for n in ast.walk(fn)
                if isinstance(n, (ast.DictComp, ast.SetComp, ast.ListComp, ast.GeneratorExp))
            ]
            comp_call_ids = set()
            for comp in comps:
                lit, unres = _enumerate_comprehension(comp)
                literal |= lit
                unresolved += unres
                key_node = comp.key if isinstance(comp, ast.DictComp) else getattr(comp, "elt", None)
                if key_node is not None:
                    comp_call_ids |= {id(c) for c in _marker_calls(key_node)}

            # Markers outside any comprehension (the common case).
            for call in _marker_calls(fn):
                if id(call) in comp_call_ids:
                    continue
                arg = call.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    literal.add(arg.value)
                elif isinstance(arg, ast.JoinedStr):
                    unresolved.append(call.lineno)
                else:
                    unresolved.append(call.lineno)

            if literal:
                per_step[(block, step)] = literal
            if unresolved:
                runtime_steps.add(step)
    return per_step, runtime_steps, complaints


@pytest.mark.unit
class TestOptionsFlowLabelCoverage737:
    def _strings(self) -> dict:
        return json.loads(_STRINGS.read_text(encoding="utf-8"))

    def test_the_scan_sees_the_schemas(self):
        """Bug class 8: a scan that silently matched nothing would make every
        coverage assertion below pass vacuously."""
        per_step, runtime, _ = _collect()
        assert len(per_step) >= 10, (
            f"only {len(per_step)} steps with schema fields found — the AST scan "
            "broke; fix it, do not relax the coverage check below."
        )
        # The deye step is the fat one and the reason #737 exists: 15 scalar +
        # 18 loop-built program fields must ALL be seen, or the f-string
        # enumeration silently dropped the program group.
        deye = per_step.get(("options", "deye"), set())
        assert len(deye) == 38, (  # +5: the #827 System Work Mode block
            f"expected 38 deye schema keys (20 scalar + 18 program), saw "
            f"{len(deye)} — the comprehension enumeration is broken: {sorted(deye)}"
        )
        assert {f"deye_program_{n}_{k}" for n in range(1, 7)
                for k in ("time", "soc", "charge")} <= deye

    def test_every_schema_field_has_a_label(self):
        strings = self._strings()
        per_step, _, _ = _collect()
        problems: list[str] = []
        for (block, step), keys in sorted(per_step.items()):
            if step in _RUNTIME_NAMED_STEPS:
                continue
            data = (
                strings.get(block, {}).get("step", {}).get(step, {}).get("data", {})
            )
            missing = sorted(k for k in keys if k not in data)
            if missing:
                problems.append(
                    f"{block}.step.{step}: {len(missing)} schema field(s) with no "
                    f"label — HA renders the raw key: {missing}"
                )
        assert not problems, (
            "options/config-flow schema fields with no strings.json label "
            "(#737, bug class 24):\n  "
            + "\n  ".join(problems)
            + "\n\nAdd each key under the step's `data` block in strings.json AND "
            "every translations/<lang>.json (test_674 enforces that mirror). HA "
            "reads only translations/<lang>.json at runtime."
        )

    def test_runtime_named_steps_do_not_grow_silently(self):
        """A step whose field keys come from runtime data cannot be declared in
        a static strings file. Adding one is a deliberate design choice, not a
        default — so the guard fails if the set changes without this list."""
        _, runtime, _ = _collect()
        assert runtime == _RUNTIME_NAMED_STEPS, (
            "the set of steps with runtime-named schema fields changed.\n"
            f"  found:    {sorted(runtime)}\n"
            f"  expected: {sorted(_RUNTIME_NAMED_STEPS)}\n"
            "If you added a step whose field keys interpolate runtime values, "
            "either give the fields static keys (so they can be labelled) or add "
            "the step here WITH a reason. If you removed one, drop it here."
        )

    def test_the_rule_can_actually_fire(self):
        """Real bad input rejected, real good input accepted — so the coverage
        assertion is not merely always-green."""
        strings = self._strings()
        per_step, _, _ = _collect()
        # Good: the settings step's #550 grid-sign toggle now resolves.
        assert "grid_sign_invert" in strings["options"]["step"]["settings"]["data"]
        assert "grid_sign_invert" in per_step[("options", "settings")]
        # Bad: a schema key that is deliberately absent from strings.json must be
        # reported by the coverage logic.
        data = dict(strings["options"]["step"]["settings"]["data"])
        data.pop("grid_sign_invert")
        keys = per_step[("options", "settings")]
        assert [k for k in keys if k not in data] == ["grid_sign_invert"], (
            "removing a label produced no coverage gap — the check cannot fire"
        )
