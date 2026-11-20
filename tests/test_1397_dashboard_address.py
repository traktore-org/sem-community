"""(#1397, class 187) An address SEM gives for its dashboard is where the dashboard is.

A Lovelace dashboard with url_path ``x`` lives at ``/x``. The notices of
``generate_dashboard`` said ``/lovelace/x``: Home Assistant's default dashboard
with a view called ``x``, which it does not have, so it shows its own start
screen — the same place the beta.18-20 Plan button sent users (fixed in the
cards, guarded by ``dashboard/card/test/screen-links.test.js``).
"""
from __future__ import annotations

import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(__file__))
INIT = os.path.join(ROOT, "__init__.py")
SERVICE = "async_generate_dashboard_service"
PATH = "sem-dashboard"   # a migrated install keeps the old address


def _service() -> ast.AsyncFunctionDef:
    with open(INIT, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    found = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == SERVICE]
    assert len(found) == 1, SERVICE
    return found[0]


def _dict_values(fn: ast.AST, key: str) -> list[ast.expr]:
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == key:
                    out.append(v)
    return sorted(out, key=lambda v: v.lineno)   # in source order


def _messages() -> list[str]:
    """Every notice text the service can create, filled in as on a migrated install."""
    names = {"dashboard_title": "SEM-dashboard", "dashboard_path": PATH, "views": [0] * 5}
    texts = []
    for node in _dict_values(_service(), "message"):
        code = compile(ast.Expression(node), INIT, "eval")
        texts.append(eval(code, {"len": len}, dict(names)))  # noqa: S307 — our own f-string
    return texts


def test_the_dashboard_is_registered_at_its_path():
    """The address in the notices is only right if the dashboard is registered under it."""
    values = _dict_values(_service(), "url_path")
    assert values and all(isinstance(v, ast.Name) and v.id == "dashboard_path" for v in values)


def test_every_notice_gives_the_dashboard_address():
    texts = _messages()
    assert len(texts) == 3, "updated live, created with a restart, ready after a restart"
    for text in texts:
        assert "/lovelace/" not in text, text
        addresses = re.findall(r"(?<![\w/])/[^\s)\]]+", text)
        assert addresses, text
        assert set(addresses) == {f"/{PATH}"}, text


def test_only_the_live_notice_links_the_dashboard():
    """Only the "updated" notice is shown while the dashboard is loaded.

    The other two wait for a restart: a link there would open the start screen,
    and Home Assistant does not keep a notice across a restart.
    """
    links = [re.findall(r"\]\(([^)]*)\)", t) for t in _messages()]
    assert links == [[f"/{PATH}"], [], []]


def _py_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in {"tests", "tools", "node_modules", "__pycache__", ".git"}]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def test_no_code_builds_a_dashboard_address_under_lovelace():
    """A dashboard path is never put after /lovelace/: that is a view of the default dashboard."""
    hits = []
    for path in _py_files():
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                parts = node.values
                for a, b in zip(parts, parts[1:], strict=False):
                    if isinstance(a, ast.Constant) and str(a.value).endswith("/lovelace/") and isinstance(b, ast.FormattedValue):
                        hits.append(f"{os.path.relpath(path, ROOT)}:{node.lineno}")
    assert hits == []
