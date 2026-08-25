"""#835 — the 3.13 rung's event-loop fixture override must stay in place.

The CI ladder runs three rungs (#787). The 3.13 one — Home Assistant 2026.2.3,
the middle version between the ``hacs.json`` floor and what PROD runs — had
NEVER passed. It is ``continue-on-error``, so the workflow badge stayed green
and 5,935 errors were invisible unless you opened the run and read the inner
jobs.

The cause was upstream, in the phacc release that rung is pinned to::

    @pytest.fixture(autouse=True)          # phacc 0.13.316
    def enable_event_loop_debug() -> None:
        asyncio.get_event_loop().set_debug(True)

``asyncio.get_event_loop()`` auto-creates a loop only while nobody has
explicitly set one; after ``set_event_loop(None)`` it raises. pytest-asyncio
1.3.0 sets None when tearing a test's loop down, so the first async test in a
session poisons every sync test that follows. phacc fixed it in 0.13.356 by
making the fixture async, but 0.13.316 is the LAST release supporting Python
3.13, so the correction lives in our conftest instead.

These tests pin the two properties that make the override work, so a future
edit cannot quietly reintroduce the failure:

* our conftest defines the name at all (a plugin fixture is shadowed by a
  conftest fixture of the same name — that shadowing IS the fix);
* it asks for the RUNNING loop rather than the current one, which is what
  survives ``set_event_loop(None)``.

The third property — that it actually holds on every rung — is asserted by the
suite passing on 3.12, 3.13 and 3.14, which is the only place it can be
asserted.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest


def _fixture_func():
    from . import conftest
    fn = getattr(conftest, "enable_event_loop_debug", None)
    assert fn is not None, (
        "tests/conftest.py no longer defines enable_event_loop_debug — the "
        "override is gone and phacc's broken sync fixture takes over again, "
        "which fails every sync test after the first async one on the 3.13 "
        "rung (#835)"
    )
    return getattr(fn, "__wrapped__", fn)


class TestTheOverrideExists:
    def test_conftest_defines_it(self):
        assert _fixture_func() is not None

    def test_it_is_async(self):
        """Sync is precisely what was broken — a sync fixture runs outside any
        loop, which is why get_event_loop() had nothing to return."""
        fn = _fixture_func()
        assert inspect.iscoroutinefunction(fn), (
            "the override must be async so pytest-asyncio runs it inside the "
            "test's loop; a sync version reintroduces #835"
        )

    def test_it_asks_for_the_running_loop(self):
        """Checks the CODE, not the raw source: the docstring quotes the
        broken call while explaining it, and a text search over the whole
        function reads that quotation as the bug itself. (It did on the first
        run of this test, which is the argument for parsing rather than
        grepping.)"""
        import ast, textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(_fixture_func())))
        body = tree.body[0].body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]                      # drop the docstring
        calls = {
            node.func.attr
            for stmt in body
            for node in ast.walk(stmt)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "get_running_loop" in calls, (
            f"must call get_running_loop(); found {sorted(calls)}"
        )
        assert "get_event_loop" not in calls, (
            "get_event_loop() is the broken call — it raises once anything has "
            "called set_event_loop(None), which pytest-asyncio does on teardown"
        )


class TestTheFailureModeIsReal:
    """Guard the premise itself. If a future Python or pytest-asyncio makes
    get_event_loop() safe again, this test fails and the override can be
    reconsidered — rather than being carried forever as folklore."""

    def test_get_event_loop_raises_once_the_loop_is_unset(self):
        prev = None
        try:
            prev = asyncio.get_event_loop_policy().get_event_loop()
        except RuntimeError:
            pass
        asyncio.set_event_loop(None)
        try:
            with pytest.raises(RuntimeError, match="no current event loop"):
                asyncio.get_event_loop()
        finally:
            asyncio.set_event_loop(prev)

    async def test_the_running_loop_is_reachable_from_an_async_fixture(self):
        """The positive half: what the override actually relies on."""
        assert asyncio.get_running_loop() is not None
