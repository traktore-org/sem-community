"""(#1372) AST lint: one place decides what a cheap hour is.

Outside the allow-list, no module may judge a price level itself: it asks
``coordinator/price_view.py``. The lint fails on the names and calls that
used to be spread over the engine, and on a comparison against a level
word. A justified exception carries ``# PRICE-ASK: <reason>`` on the same
line or the line above.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The providers decide levels; value_layer and anything new under tariff/
# are consumers and are linted like the rest.
ALLOWED = {"coordinator/price_view.py", "coordinator/price_signal.py",
           "tariff/tariff_provider.py", "tariff/calendar_provider.py"}
ALLOWED_DIRS = ()
NAMES = frozenset({
    "is_cheap", "is_expensive", "is_cheap_name", "is_expensive_name",
    "comparative_level", "CHEAP_LEVELS", "EXPENSIVE_LEVELS",
    "tariff_cheap_at", "tariff_rate_cheap_at",
})
CALLS = frozenset({"get_price_level", "get_price_level_at", "get_rate_level_at"})
WORDS = frozenset({"cheap", "very_cheap", "expensive", "very_expensive"})
MARK = "# PRICE-ASK:"


def violations(source: str) -> list[tuple[int, str, bool]]:
    """(line, what, excused) for every direct price question in source."""
    lines = source.splitlines()
    found: list[tuple[int, str, bool]] = []

    def add(node: ast.AST, what: str) -> None:
        n = node.lineno
        here = lines[n - 1] if n <= len(lines) else ""
        above = lines[n - 2] if n >= 2 else ""
        ok = MARK in here or MARK in above.strip()[:len(MARK)]
        found.append((n, what, ok))

    tree = ast.parse(source)
    # ``answer.is_cheap`` is the view's own property, not the old function:
    # an attribute counts only when it is CALLED (``price_signal.is_cheap(p)``).
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in NAMES:
            add(node, node.id)
        elif isinstance(node, ast.Attribute) and node.attr in CALLS:
            add(node, node.attr)
        elif (isinstance(node, ast.Attribute) and node.attr in NAMES
              and id(node) in called):
            add(node, node.attr)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in ("getattr", "hasattr")
              and len(node.args) > 1
              and isinstance(node.args[1], ast.Constant)
              and node.args[1].value in CALLS):
            add(node, f"{node.func.id}({node.args[1].value!r})")
        elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
              and node.value.id == "PriceLevel"):
            add(node, "PriceLevel." + node.attr)     # a level judged by hand
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value in WORDS:
                    add(key, f"dict key {key.value!r}")
        elif isinstance(node, ast.alias) and node.name in NAMES:
            add(node, "import " + node.name)
        elif isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                if isinstance(side, ast.Constant) and side.value in WORDS:
                    add(side, repr(side.value))
                elif isinstance(side, (ast.Tuple, ast.List, ast.Set)):
                    for el in side.elts:
                        if isinstance(el, ast.Constant) and el.value in WORDS:
                            add(el, repr(el.value))
    return found


def _files() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if (rel.startswith(("tests/", "node_modules/", ".git", "scripts/"))
                or "/tests/" in rel or rel in ALLOWED
                or rel.startswith(ALLOWED_DIRS)):
            continue
        out.append(p)
    return out


def test_no_direct_price_questions_outside_the_price_view():
    bad, excused = [], 0
    for p in _files():
        rel = p.relative_to(ROOT).as_posix()
        for line, what, ok in violations(p.read_text(encoding="utf-8")):
            if ok:
                excused += 1
            else:
                bad.append(f"{rel}:{line}: {what}")
    print(f"PRICE-ASK exceptions: {excused}")
    assert not bad, (
        "ask coordinator/price_view.py, or mark the line "
        "'# PRICE-ASK: <reason>' (#1372):\n" + "\n".join(bad))


def test_lint_catches_a_planted_violation():
    src = (
        "from .price_signal import is_cheap\n"
        "def f(p, lvl):\n"
        "    if p.get_price_level_at(1) == 'very_cheap':\n"
        "        return is_cheap(p)\n"
        "    return lvl in ('cheap', 'x')\n"
        "def h(p):\n"
        "    return getattr(p, 'get_price_level_at', None)\n"
        "def g(a, m):\n"
        "    return m.is_expensive(a) or a.is_cheap\n"
    )
    whats = {w for _, w, ok in violations(src) if not ok}
    assert {"import is_cheap", "is_cheap", "get_price_level_at",
            "'very_cheap'", "'cheap'", "is_expensive", "getattr('get_price_level_at')"} <= whats
    assert not any(w == "is_cheap" and n == 9 for n, w, _ in violations(src))


def test_lint_ignores_other_strings_and_honours_the_marker():
    src = (
        "def f(src):\n"
        "    a = src == 'cheap_grid'\n"
        "    # PRICE-ASK: a reason\n"
        "    b = src.get_price_level()\n"
        "    c = src.get_price_level_at(1)  # PRICE-ASK: why\n"
        "    return a, b, c\n"
    )
    assert all(ok for _, _, ok in violations(src))
    assert len(violations(src)) == 2
