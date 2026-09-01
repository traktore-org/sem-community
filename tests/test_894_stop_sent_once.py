"""#894 — the EV stop signal must be sent exactly ONCE.

@DigitalOptics (Fronius, "Other" charger, SEM 2.0.0): with no start/stop
entity configured, SEM stopped by writing 0 A as the current — and did it
*twice within a few milliseconds*. On an install where the stop is realised
by an HA automation watching for the 0 A write, the automation fired twice
and produced a burst of SEM warnings.

Root cause (the reporter diagnosed it exactly): ``GenericAdapter``'s
``command_disable`` / ``command_idle`` wrote 0 A **directly** and then also
called ``stop_session()`` — which, finding no brand-specific stop mechanism
(no stop_service, charge-mode select, start/stop entity or ``<domain>.disable``),
falls back to writing 0 A itself. Two 0 A dispatches for one stop.

``_set_current``'s heartbeat de-dup did NOT collapse the second write: it is
gated on ``is_active`` (``_status.state == ACTIVE``), and the EV reconciler
path never marks the device ACTIVE, so the guard was always False during a
stop. Relying on that de-dup would be a workaround anyway; the fix removes the
redundant call so ``stop_session`` is the single owner of the stop.

KEBA was always correct — ``KebaAdapter.command_disable`` / ``command_idle``
delegate to ``stop_session()`` alone. This is the mirror of bug-class #25
(mutual delegation → *neither* layer acts); here the belt-and-suspenders makes
*both* act. The invariant below: one stop call → at most one 0 A dispatch.
"""
from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters import (
    GenericAdapter,
    KebaAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_adapters import (
    generic as generic_mod,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
)


# ── Adapter-structure harness (stop_session mocked out) ───────────────
def _mock_device(session_active: bool = True):
    """A device whose _set_current / stop_session are independent spies,
    so a test can see which one an adapter method reaches."""
    dev = MagicMock()
    dev.max_current = 32
    dev.phases = 3
    dev.voltage = 230
    dev._session_active = session_active
    dev._set_current = AsyncMock()
    dev.start_session = AsyncMock()
    dev.stop_session = AsyncMock()
    return dev


class TestAdapterDelegatesStopToStopSession:
    """command_disable / command_idle must NOT write 0 A directly when a
    session is open — stop_session owns the single 0 A write."""

    @pytest.mark.asyncio
    async def test_generic_command_disable_delegates_to_stop_session(self):
        dev = _mock_device(session_active=True)
        await GenericAdapter(dev).command_disable()
        dev.stop_session.assert_awaited_once()
        dev._set_current.assert_not_awaited()  # no redundant 0 A (#894)

    @pytest.mark.asyncio
    async def test_generic_command_idle_with_session_delegates(self):
        dev = _mock_device(session_active=True)
        await GenericAdapter(dev).command_idle()
        dev.stop_session.assert_awaited_once()
        dev._set_current.assert_not_awaited()  # no redundant 0 A (#894)

    @pytest.mark.asyncio
    async def test_generic_command_idle_without_session_writes_zero_once(self):
        """No session to tear down → a single direct 0 A, no stop_session."""
        dev = _mock_device(session_active=False)
        await GenericAdapter(dev).command_idle()
        dev._set_current.assert_awaited_once_with(0)
        dev.stop_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_keba_command_disable_delegates_to_stop_session(self):
        """The reference behaviour the generic path now matches (#894)."""
        dev = _mock_device(session_active=True)
        await KebaAdapter(dev).command_disable()
        dev.stop_session.assert_awaited_once()
        dev._set_current.assert_not_awaited()


# ── End-to-end harness (real stop_session, _set_current spied) ────────
def _real_device_no_stop_mechanism():
    """A real CurrentControlDevice with NO brand stop mechanism — the
    reporter's config. ``_set_current`` is a spy so we can count exactly
    how many 0 A dispatches ONE stop produces through the REAL
    ``command_disable`` → REAL ``stop_session`` composition."""
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
        DeviceState,
    )
    d = CurrentControlDevice.__new__(CurrentControlDevice)
    d.name = "EV Charger"
    d.stop_service = None
    d.charge_mode_entity = None
    d.charge_mode_stop = None
    d.start_stop_entity = None          # ← the reporter's case
    d.charger_service = None
    d.service_device_id = None
    d.max_current = 32
    d.min_current = 6
    d.phases = 3
    d.voltage = 230
    d._session_active = True
    d._current_setpoint = 16.0
    # EV path never marks the device ACTIVE — the de-dup that "should" have
    # collapsed the second write is gated on this and was always False.
    d._status = SimpleNamespace(
        state=DeviceState.IDLE, current_consumption_w=0.0, allocated_power_w=0.0,
    )
    d._last_write_at = 0.0
    d.hass = MagicMock()
    d._set_current = AsyncMock()
    d.arm_failsafe_off = AsyncMock()
    return d


class TestOneStopOneDispatch:
    """The reporter's invariant: one stop → one 0 A dispatch."""

    @pytest.mark.asyncio
    async def test_command_disable_dispatches_zero_exactly_once(self):
        d = _real_device_no_stop_mechanism()
        await GenericAdapter(d).command_disable()
        # Before #894: 2 (adapter's explicit write + stop_session's fallback).
        assert d._set_current.await_count == 1, (
            f"stop sent {d._set_current.await_count}× — must be exactly once "
            "(#894 double-send)"
        )
        assert d._set_current.await_args.args[0] == 0

    @pytest.mark.asyncio
    async def test_command_idle_dispatches_zero_exactly_once(self):
        d = _real_device_no_stop_mechanism()
        await GenericAdapter(d).command_idle()
        assert d._set_current.await_count == 1, (
            f"idle sent {d._set_current.await_count}× — must be exactly once "
            "(#894 double-send)"
        )
        assert d._set_current.await_args.args[0] == 0

    @pytest.mark.asyncio
    async def test_disable_intent_is_still_tagged(self):
        """The stop still happens and is tagged DISABLE for the self-resume
        guard — we removed a redundant write, not the stop."""
        d = _real_device_no_stop_mechanism()
        a = GenericAdapter(d)
        await a.command_disable()
        assert a.last_intent is ChargerIntent.DISABLE


# ── Structural guard (branch-safe) ────────────────────────────────────
def _calls_set_current(node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_set_current"
        for n in ast.walk(node)
    )


def test_generic_command_disable_does_not_write_current_directly():
    """command_disable must delegate the whole stop to stop_session — a
    direct _set_current here is the #894 double-send re-introduced. Parsed
    from source so a future edit that re-adds the redundant write fails CI."""
    tree = ast.parse(inspect.getsource(generic_mod))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "command_disable"
    )
    assert not _calls_set_current(fn), (
        "GenericAdapter.command_disable calls _set_current directly — "
        "stop_session already owns the 0 A stop; this re-opens #894"
    )
