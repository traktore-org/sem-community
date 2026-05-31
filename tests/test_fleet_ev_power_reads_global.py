"""Global AST lint: every ``power.ev_power`` read in ``coordinator/``
must acknowledge fleet semantics (v1.6.16).

Expands the v1.6.8 ``test_ev_control_fleet_reads.py`` (which only
covered ``ev_control.py``) to every module under ``coordinator/``.
The recurring bug class through v1.6.0 → v1.6.6 was per-charger code
paths accidentally reading the fleet-summed ``power.ev_power`` —
those fixes landed first in ``ev_control.py`` (where it bit hardest)
and the rest of ``coordinator/`` got the comment annotations
retroactively in v1.6.16.

Two equivalent acknowledgement forms — pick the cleaner per site:

1. **Comment annotation** (v1.6.8 form): ``# FLEET-READ: <reason>``
   on the same line as the read or the immediately preceding line.

2. **Method call** (v1.6.16 form): rewrite the read as
   ``power.ev_power.as_fleet_total("<reason>")``. ``FleetEvPower``
   is a ``float`` subclass so arithmetic still works; the call site
   carries the reason in the bytecode.

The v1.6.16 form is preferred for NEW code because the reason
appears in ``git blame``, mypy output, IDE hover and AST tools —
not just in the line above. Existing comment annotations stay
valid; there is no flag-day.

The ``_this_charger_power`` helper body remains exempt — it's the
sanctioned fallback that DOES read the fleet for single-charger
setups.

See ``docs/MULTI_CHARGER.md`` for the full invariant.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


COORDINATOR_DIR = (
    Path(__file__).resolve().parent.parent / "coordinator"
)

# Functions whose body is allowed to read ``power.ev_power`` directly.
EXEMPT_FUNCTIONS = frozenset({"_this_charger_power"})

# Files exempt entirely. Currently:
#  - ``types.py`` defines ``PowerReadings.ev_power`` itself + the
#    ``to_dict`` emitter, both legitimate self-references.
#  - ``per_charger_context.py`` only mentions ``power.ev_power`` in
#    docstrings (no code reads).
# Anything else added here needs a maintainer review.
EXEMPT_FILES = frozenset({"types.py", "per_charger_context.py"})

ANNOTATION = "# FLEET-READ:"
METHOD_NAME = "as_fleet_total"


def _find_function_for_line(tree: ast.Module, line: int) -> str | None:
    """Innermost function definition enclosing ``line`` (or ``None``)."""
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)
            if start <= line <= end:
                if best is None or start > best[0]:
                    best = (start, node.name)
    return best[1] if best else None


def _is_method_call_form(node: ast.AST) -> bool:
    """True iff ``node`` (a ``power.ev_power`` Attribute) is the receiver
    of a ``.as_fleet_total(...)`` call.

    Matches ``power.ev_power.as_fleet_total("reason")``. The AST shape
    is:

        Call(
          func=Attribute(
            value=Attribute(value=Name("power"), attr="ev_power"),  ← node
            attr="as_fleet_total"),
          args=[Constant("reason")])

    We get the ``Call.func.value`` to check whether the read node is
    the inner ``Attribute``. ``ast.walk`` doesn't give us parents, so
    we re-walk the surrounding source — instead we accept any chained
    attribute access where the OUTER attribute name is ``as_fleet_total``.

    Because ``ast`` doesn't carry parent pointers, this check is done
    at the AST level by spotting whether the read is wrapped by a
    parent ``Attribute(attr="as_fleet_total")``. The walker in
    ``_find_ev_power_reads`` does this by checking each visited node's
    enclosing context — see that function.
    """
    return False  # not used directly; see _find_ev_power_reads


def _find_ev_power_reads(tree: ast.Module) -> list[tuple[int, str, bool]]:
    """Return ``(line, enclosing_function, is_method_form)`` for every
    ``power.ev_power`` read in the file.

    ``is_method_form`` is True when the read is the inner attribute of
    a ``power.ev_power.as_fleet_total(...)`` chain — i.e. the v1.6.16
    deliberate-unwrap form. We compute it by attaching parent pointers
    to every node before walking (``ast`` doesn't ship parent links).
    """
    # Attach parent pointers — the standard workaround for ast's
    # parentless tree. Cheap (one walk) and self-contained to this test.
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent  # type: ignore[attr-defined]

    hits: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "ev_power"
            and isinstance(node.value, ast.Name)
            and node.value.id == "power"
        ):
            # Method-form check: is the parent an Attribute whose attr
            # is ``as_fleet_total``? If yes, this read is the chained
            # ``power.ev_power.as_fleet_total(...)`` and counts as
            # explicitly acknowledged.
            parent = getattr(node, "parent", None)
            is_method_form = (
                isinstance(parent, ast.Attribute)
                and parent.attr == METHOD_NAME
            )
            func = _find_function_for_line(tree, node.lineno) or "<module>"
            hits.append((node.lineno, func, is_method_form))
    return hits


def _is_annotated(lines: list[str], line_no: int, lookback: int = 5) -> bool:
    """``# FLEET-READ:`` on the read's line or any of the ``lookback``
    lines above, walking back ONLY through ``#``-comment lines.

    The walk-back stops on the first non-comment, non-blank line — so a
    FLEET-READ tag at the head of a multi-line comment block above the
    read counts, but a tag inside an unrelated function above doesn't
    leak through.

    ``lookback`` defaults to 3 — enough for "tag + two explanation
    lines" without losing locality.
    """
    idx = line_no - 1
    if 0 <= idx < len(lines) and ANNOTATION in lines[idx]:
        return True
    # Walk back through ``#``-comment lines only (or whitespace-only
    # lines). A code line breaks the chain.
    for back in range(1, lookback + 1):
        j = idx - back
        if j < 0:
            break
        stripped = lines[j].strip()
        if not stripped:
            continue  # blank line — keep looking
        if not stripped.startswith("#"):
            return False  # ran out of comment block
        if ANNOTATION in lines[j]:
            return True
    return False


def _coordinator_files() -> list[Path]:
    return sorted(
        p for p in COORDINATOR_DIR.glob("*.py")
        if p.is_file() and p.name not in EXEMPT_FILES
    )


class TestGlobalFleetEvPowerLint:
    """Every ``power.ev_power`` read in ``coordinator/`` outside the
    exempt files must be acknowledged via comment OR method form."""

    def test_every_read_is_acknowledged(self):
        offenders: list[str] = []
        for path in _coordinator_files():
            source = path.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError as e:  # pragma: no cover — guard CI sanity
                pytest.fail(f"Syntax error parsing {path.name}: {e}")
            lines = source.splitlines()
            for line_no, func, is_method_form in _find_ev_power_reads(tree):
                if func in EXEMPT_FUNCTIONS:
                    continue
                if is_method_form:
                    continue  # ``.as_fleet_total(...)`` form is acknowledged
                if _is_annotated(lines, line_no):
                    continue  # ``# FLEET-READ:`` form is acknowledged
                offenders.append(
                    f"  {path.name}:L{line_no} in {func}()"
                )
        assert not offenders, (
            "Found unannotated ``power.ev_power`` reads in coordinator/"
            " modules. In multi-charger setups ``power.ev_power`` is the"
            " GLOBAL SUM across all chargers — reading it directly inside"
            " a per-charger code path is the bug class that caused #284,"
            " #289, #315 and #318.\n\nOffenders:\n"
            + "\n".join(offenders)
            + "\n\nFix: either replace with ``this_power_w`` cached via "
            "``self._this_charger_power(ev, power)`` (per-charger code"
            " paths), or acknowledge the fleet semantics via one of:\n"
            "  (a) ``# FLEET-READ: <reason>`` on the same line or above\n"
            "  (b) ``power.ev_power.as_fleet_total(\"<reason>\")`` "
            "(preferred for new code — reason in bytecode)\n\n"
            "See docs/MULTI_CHARGER.md for the full invariant."
        )

    def test_exempt_files_are_minimal(self):
        """Exemption list intentionally tiny — anything added needs
        a maintainer review."""
        assert EXEMPT_FILES == frozenset({"types.py", "per_charger_context.py"})

    def test_exempt_helper_is_minimal(self):
        assert EXEMPT_FUNCTIONS == frozenset({"_this_charger_power"})

    def test_method_form_detected_in_synthetic_code(self):
        """Sanity: if a synthetic snippet uses ``power.ev_power
        .as_fleet_total("...")``, the walker tags it as method form."""
        synthetic = (
            "def f(power):\n"
            "    return power.ev_power.as_fleet_total(\"sanity\")\n"
        )
        tree = ast.parse(synthetic)
        hits = _find_ev_power_reads(tree)
        assert len(hits) == 1
        assert hits[0][2] is True  # is_method_form

    def test_bare_read_flagged_in_synthetic_code(self):
        synthetic = (
            "def f(power):\n"
            "    if power.ev_power > 100:\n"
            "        return True\n"
        )
        tree = ast.parse(synthetic)
        lines = synthetic.splitlines()
        hits = _find_ev_power_reads(tree)
        assert len(hits) == 1
        assert hits[0][2] is False
        assert not _is_annotated(lines, hits[0][0])

    def test_comment_form_still_accepted(self):
        """v1.6.8 idiom: ``# FLEET-READ: reason`` on the previous
        line. Still valid in v1.6.16."""
        synthetic = (
            "def f(power):\n"
            "    # FLEET-READ: sanity check\n"
            "    return power.ev_power > 100\n"
        )
        tree = ast.parse(synthetic)
        lines = synthetic.splitlines()
        hits = _find_ev_power_reads(tree)
        assert len(hits) == 1
        assert _is_annotated(lines, hits[0][0])


class TestFleetEvPowerNewtype:
    """``FleetEvPower`` itself: float subclass with ``.as_fleet_total``."""

    def test_is_float_subclass(self):
        from custom_components.solar_energy_management.coordinator.types import (
            FleetEvPower,
        )
        assert issubclass(FleetEvPower, float)

    def test_arithmetic_works(self):
        """Arithmetic with a regular float must still work — no
        migration cost for the ~15 legitimate fleet reads across
        coordinator/."""
        from custom_components.solar_energy_management.coordinator.types import (
            FleetEvPower,
        )
        p = FleetEvPower(4140.0)
        assert p > 100  # float comparison
        assert p / 1000 == 4.140  # arithmetic
        assert p + 100 == 4240.0
        assert float(p) == 4140.0

    def test_as_fleet_total_returns_plain_float(self):
        from custom_components.solar_energy_management.coordinator.types import (
            FleetEvPower,
        )
        p = FleetEvPower(4140.0)
        out = p.as_fleet_total("test")
        assert out == 4140.0
        assert type(out) is float

    def test_as_fleet_total_reason_is_documentation_only(self):
        """The reason argument has no runtime effect — it's there for
        readers, ``git blame``, and (future) static analyzers. We
        accept ANY string."""
        from custom_components.solar_energy_management.coordinator.types import (
            FleetEvPower,
        )
        p = FleetEvPower(100.0)
        # All accepted, no validation.
        assert p.as_fleet_total("a reason") == 100.0
        assert p.as_fleet_total("") == 100.0
        assert p.as_fleet_total("123") == 100.0

    def test_default_powerreadings_ev_power_is_fleet_type(self):
        """``PowerReadings.ev_power`` default is a ``FleetEvPower``,
        not a plain float — pins the dataclass field type."""
        from custom_components.solar_energy_management.coordinator.types import (
            FleetEvPower, PowerReadings,
        )
        r = PowerReadings()
        assert isinstance(r.ev_power, FleetEvPower)
        # Defaults to 0.0.
        assert r.ev_power == 0.0

    def test_repr_includes_class_name(self):
        from custom_components.solar_energy_management.coordinator.types import (
            FleetEvPower,
        )
        assert repr(FleetEvPower(4140.0)) == "FleetEvPower(4140.0)"
