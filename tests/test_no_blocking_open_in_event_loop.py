"""AST lint: no bare ``open()`` inside an ``async def``.

Home Assistant wraps ``builtins.open`` with a loop guard
(``homeassistant.block_async_io``) precisely because a file read on the
event loop stalls every other integration on the box for the duration of
the syscall. When SEM calls it from a coroutine, HA logs

    Detected blocking call to open inside the event loop by custom
    integration 'solar_energy_management'

and on a slow SD card or a network-mounted ``/config`` the stall is not
theoretical.

``os.path.exists`` and friends are deliberately NOT covered here: HA does
not guard them (the protected set is ``open``, ``glob``, ``os.listdir``,
``os.scandir``, ``os.walk``, ``Path.read_*``/``write_*``, ``time.sleep``,
``importlib.import_module``, and a few TLS loaders), and a bare ``stat``
is a different order of cost from reading and parsing a file. This lint
tracks HA's actual guard list, not a general purity rule — a lint that
fires on things HA tolerates gets muted, and a muted lint catches
nothing.

The sanctioned pattern is already used a dozen times in ``__init__.py``:
put the filesystem work in a plain function and hand it to
``hass.async_add_executor_job``.

Found by the #783 doc/release audit: the ``generate_dashboard`` service
read ``manifest.json`` inline, three lines below a block that correctly
used the executor for the same directory.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Names HA's loop guard actually patches, as bare calls.
BLOCKING_BUILTINS = frozenset({"open"})

# Attribute calls HA guards, as ``module.attr`` / ``obj.attr``.
BLOCKING_ATTRS = frozenset(
    {
        "os.listdir",
        "os.scandir",
        "os.walk",
        "glob.glob",
        "glob.iglob",
        "time.sleep",
    }
)

# Opt-out for a call that is provably not on the event loop — e.g. a
# nested plain function that is only ever handed to an executor. Put
# ``# EXECUTOR-SAFE: <reason>`` on the call's line or the line above.
OPT_OUT = "EXECUTOR-SAFE:"


def _component_files() -> list[Path]:
    """Every shipped .py file. Tests and the card bundle are not loaded by HA."""
    out = []
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO)
        parts = rel.parts
        if parts[0] in {"tests", "scripts", "node_modules", ".git"}:
            continue
        out.append(path)
    return out


def _dotted(node: ast.AST) -> str | None:
    """Render ``a.b.c`` from an attribute/name chain, else None."""
    bits = []
    while isinstance(node, ast.Attribute):
        bits.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    bits.append(node.id)
    return ".".join(reversed(bits))


def _annotated(src_lines: list[str], lineno: int) -> bool:
    """True if the call carries the opt-out on its line or the one above."""
    for ln in (lineno, lineno - 1):
        if 1 <= ln <= len(src_lines) and OPT_OUT in src_lines[ln - 1]:
            return True
    return False


_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _own_nodes(fn: ast.AST) -> list[ast.AST]:
    """Every node in ``fn``'s body, not descending into nested functions.

    A nested function's body runs when *it* is called, which may be on a
    different thread entirely — so it is scored separately.
    """
    out: list[ast.AST] = []

    def rec(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _FUNC):
                continue
            out.append(child)
            rec(child)

    rec(fn)
    return out


def _functions_by_name(tree: ast.AST) -> dict[str, list[ast.AST]]:
    """Name → every ``def``/``async def`` in the file carrying it.

    Names are unqualified on purpose. Two functions sharing a name in one
    file is rare, and resolving a call to both of them errs toward
    flagging — the safe direction for a guard.
    """
    out: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, []).append(node)
    return out


def _called_names(fn: ast.AST) -> set[str]:
    """Names this function *invokes* — ``f()`` and ``self.f()``.

    A bare reference (``executor_job(_read)``) is not a call and must not
    count: handing a function to an executor is the whole fix.
    """
    names: set[str] = set()
    for node in _own_nodes(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "self":
                names.add(func.attr)
    return names


def _on_loop_functions(tree: ast.AST) -> list[ast.AST]:
    """Every function whose body can run on the event loop.

    Seeded with the coroutines, then closed over direct calls. Lexical
    nesting is NOT the boundary: a plain ``def`` written inside an ``async
    def`` still runs on the loop if the coroutine calls it, and a
    module-level helper is on the loop the moment a coroutine reaches it.
    """
    by_name = _functions_by_name(tree)
    on_loop = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]
    seen = {id(n) for n in on_loop}
    queue = list(on_loop)
    while queue:
        for name in _called_names(queue.pop()):
            for target in by_name.get(name, ()):
                if id(target) not in seen:
                    seen.add(id(target))
                    on_loop.append(target)
                    queue.append(target)
    return on_loop


def _blocking_calls_in_coroutines(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)

    offenders: list[str] = []
    for fn in _on_loop_functions(tree):
        for node in _own_nodes(fn):
            if not isinstance(node, ast.Call):
                continue
            name = None
            if isinstance(node.func, ast.Name):
                if node.func.id in BLOCKING_BUILTINS:
                    name = node.func.id
            else:
                dotted = _dotted(node.func)
                if dotted in BLOCKING_ATTRS:
                    name = dotted
            if name and not _annotated(lines, node.lineno):
                try:
                    where = path.relative_to(REPO)
                except ValueError:  # the self-check's temp file
                    where = path
                offenders.append(f"{where}:{node.lineno}: {name}()")
    return sorted(set(offenders))


def test_no_blocking_filesystem_calls_on_the_event_loop():
    offenders: list[str] = []
    for path in _component_files():
        offenders.extend(_blocking_calls_in_coroutines(path))

    assert not offenders, (
        "These calls block Home Assistant's event loop. HA patches them with "
        "a loop guard and logs 'Detected blocking call ... by custom "
        "integration solar_energy_management'. Move the work into a plain "
        "function and await it via hass.async_add_executor_job, or annotate "
        f"the line with `# {OPT_OUT} <reason>` if it provably runs off the "
        "loop:\n  " + "\n  ".join(offenders)
    )


def test_the_lint_can_actually_see_a_violation():
    """A guard that cannot fail is not a guard.

    The walker skips plain ``def`` bodies on purpose (that is the executor
    pattern), so it would be easy to write a version that skips
    everything. This pins that a bare ``open()`` directly in an ``async
    def`` is still caught, and that the executor form is not.
    """
    import tempfile

    bad = "async def f():\n    with open('x') as fh:\n        return fh.read()\n"
    good = (
        "async def f(hass):\n"
        "    def _read():\n"
        "        with open('x') as fh:\n"
        "            return fh.read()\n"
        "    return await hass.async_add_executor_job(_read)\n"
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sample.py"
        p.write_text(bad, encoding="utf-8")
        assert _blocking_calls_in_coroutines(p), "lint missed a bare open() in a coroutine"
        p.write_text(good, encoding="utf-8")
        assert not _blocking_calls_in_coroutines(p), (
            "lint flagged the executor pattern, which is the fix we recommend"
        )


def test_the_lint_follows_calls_out_of_the_coroutine():
    """Lexical nesting is not the boundary — reachability is.

    The first version of this lint only looked at calls written *inside*
    an ``async def``. It passed on ``generate_dashboard`` while the live
    integration logged, from that very service:

        Detected blocking call to open with args ('.../dist/sem-cards.js',
        'rb') inside the event loop ... at __init__.py, line 64

    Line 64 is ``_content_hash_cache_bust``, a module-level helper. The
    coroutine called a nested ``def`` which called it — two hops, and
    every one of them on the loop, because *calling* a function runs its
    body right there. Only handing a function to an executor moves it.

    So a plain ``def`` is exempt when it is passed as a value, and on the
    loop when it is called by name. That is the distinction this pins.
    """
    import tempfile

    reached = (
        "def _hash(p):\n"
        "    with open(p, 'rb') as fh:\n"
        "        return fh.read()\n"
        "async def f():\n"
        "    def _bust(p):\n"
        "        return _hash(p)\n"
        "    return _bust('x')\n"
    )
    # Same helper, but the coroutine only ever hands it to the executor.
    not_reached = (
        "def _hash(p):\n"
        "    with open(p, 'rb') as fh:\n"
        "        return fh.read()\n"
        "async def f(hass):\n"
        "    return await hass.async_add_executor_job(_hash, 'x')\n"
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sample.py"
        p.write_text(reached, encoding="utf-8")
        assert _blocking_calls_in_coroutines(p), (
            "lint missed a blocking helper reached from a coroutine through a "
            "nested def — the exact shape that got past it live (#785)"
        )
        p.write_text(not_reached, encoding="utf-8")
        assert not _blocking_calls_in_coroutines(p), (
            "lint flagged a helper that is only handed to an executor — that "
            "is the fix we recommend, not a violation"
        )


def test_the_lint_follows_method_calls_on_self():
    """``self._helper()`` runs on the loop just as much as ``_helper()``."""
    import tempfile

    src = (
        "class C:\n"
        "    def _read(self):\n"
        "        with open('x') as fh:\n"
        "            return fh.read()\n"
        "    async def go(self):\n"
        "        return self._read()\n"
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sample.py"
        p.write_text(src, encoding="utf-8")
        assert _blocking_calls_in_coroutines(p), (
            "lint missed a blocking method called from an async method"
        )
