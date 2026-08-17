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


def _blocking_calls_in_coroutines(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)

    # Map every node to its enclosing function chain so a plain `def`
    # nested inside an `async def` is NOT flagged — that is exactly the
    # executor pattern, and the whole point of the helper.
    offenders: list[str] = []

    def walk(node: ast.AST, in_coroutine: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AsyncFunctionDef):
                walk(child, True)
                continue
            if isinstance(child, (ast.FunctionDef, ast.Lambda)):
                # A sync def inside a coroutine is the executor target.
                walk(child, False)
                continue
            if in_coroutine and isinstance(child, ast.Call):
                name = None
                if isinstance(child.func, ast.Name):
                    if child.func.id in BLOCKING_BUILTINS:
                        name = child.func.id
                else:
                    dotted = _dotted(child.func)
                    if dotted in BLOCKING_ATTRS:
                        name = dotted
                if name and not _annotated(lines, child.lineno):
                    try:
                        where = path.relative_to(REPO)
                    except ValueError:  # the self-check's temp file
                        where = path
                    offenders.append(f"{where}:{child.lineno}: {name}()")
            walk(child, in_coroutine)

    walk(tree, False)
    return offenders


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
