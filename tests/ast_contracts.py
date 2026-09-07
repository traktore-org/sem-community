"""Structural assertions that are about the CODE, not about its spelling.

Why this exists
---------------
97 of SEM's test files assert a structural fact by grepping a function's
source text::

    src = inspect.getsource(SEMCoordinator._shadow_energy_plan)
    assert "export_rate=" in src

That is one line, which is why it is everywhere — 121 of them. It is also
the shape that let #924 live for a month: the assertion names ONE function,
so three sibling call sites kept the old behaviour underneath it, and one of
those packed the plan a user reads. It is coupled to the SPELLING of the
code, not to the code. It cannot tell you:

* whether the call is REACHED (it may sit in a dead branch),
* whether siblings elsewhere lack it (the #924 defect exactly),
* whether a rename broke it (a renamed callee makes the test pass on the
  old string until someone notices),
* whether the string is in a COMMENT or a docstring rather than in code.

51 files already do it properly with ``ast``, and every one of them rolls
its own walker — thirty lines to say what the grep says in one. So the
fragile form wins on ergonomics, every time, and the ledger fills up.

This module makes the sound form one line too. Prefer these; reach for
``inspect.getsource`` only when the thing you are pinning genuinely IS text
(a comment, an annotation, a log message a user will read).

Everything here ignores strings, comments and docstrings by construction:
it walks the parsed tree, so a mention in prose is not a call.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from typing import Callable, Iterable, Optional


def _tree_of(fn: Callable) -> ast.AST:
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))


def _callee_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def calls(fn: Callable, callee: str) -> bool:
    """Does ``fn`` contain a CALL to ``callee``? Matches a bare name or an
    attribute (``x.callee()``). A mention in a comment or a string is not a
    call, which is the whole point."""
    return any(isinstance(n, ast.Call) and _callee_name(n) == callee
               for n in ast.walk(_tree_of(fn)))


def call_kwargs(fn: Callable, callee: str) -> list:
    """Every call to ``callee`` inside ``fn``, as its list of keyword names.

    Use it to pin "this call passes X" without pinning how X is spelled::

        assert all("export_rate" in kw for kw in
                   call_kwargs(coord._shadow_energy_plan, "build_day_slots"))
    """
    out = []
    for n in ast.walk(_tree_of(fn)):
        if isinstance(n, ast.Call) and _callee_name(n) == callee:
            out.append([k.arg for k in n.keywords if k.arg])
    return out


def reads_attribute(fn: Callable, obj: str, attr: str) -> bool:
    """Does ``fn`` read ``obj.attr``? (``reads_attribute(f, "self", "_x")``)

    The #915 read-back was dead because three call sites read
    ``self._battery_adapter`` — a name nothing had assigned since #375. A
    grep for that string also matched a docstring and a longer sibling
    attribute; this does not."""
    for n in ast.walk(_tree_of(fn)):
        if (isinstance(n, ast.Attribute) and n.attr == attr
                and isinstance(n.value, ast.Name) and n.value.id == obj):
            return True
    return False


def assigns_attribute(fn: Callable, obj: str, attr: str) -> bool:
    """Does ``fn`` ASSIGN ``obj.attr``? The counterpart to the above — a
    read with no writer anywhere is a dead feature (#915)."""
    for n in ast.walk(_tree_of(fn)):
        if not isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            continue
        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
        for t in targets:
            if (isinstance(t, ast.Attribute) and t.attr == attr
                    and isinstance(t.value, ast.Name) and t.value.id == obj):
                return True
    return False


def call_sites(callee: str, *, root: Optional[Path] = None,
               skip_dirs: Iterable[str] = ("tests", "scripts",
                                           "node_modules", ".git")) -> list:
    """EVERY production call to ``callee`` in the package, as
    ``[(relative_path, lineno, [kwarg names])]``.

    This is the one that answers the #924 question — "are the SIBLINGS
    right?" — which no per-function assertion can ever ask. Write coverage
    rules over this, not over one function's source."""
    root = root or Path(__file__).resolve().parent.parent
    hits = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if set(rel.parts) & set(skip_dirs):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:          # a file we cannot parse is not a pass
            raise
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and _callee_name(n) == callee:
                hits.append((str(rel), n.lineno,
                             [k.arg for k in n.keywords if k.arg]))
    return hits
