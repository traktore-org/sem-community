"""#753 — a warm-up 'disconnect' must not end the charging session.

PROD, 2026-08-11 21:22: top chip Session 1.6 kWh, charger tile 6.0 kWh.
The #282 persistence WORKED — storage held a full session — but the
restart's sensor warm-up published ``ev_connected=False`` for the first
cycles, the end-detection took it as a real unplug, finalized the session
into lifetime stats, and a fresh session started when charging resumed at
20:53. Every session-derived number (cost, solar share) was silently
rewritten. Same warm-up class as the 23-kWh target blip logged the same
evening: a sensor that has not spoken yet is not a sensor saying "no".

A disconnect must therefore be CONFIRMED: never during the boot warm-up
window, and only after three consecutive disconnected cycles (which also
absorbs the KEBA UDP blip family, #35/#595).

The confirmation moved to the source in #638 — ``_confirm_ev_connection``
filters ``power`` once, at the top of the cycle, so the session layer and
every other consumer share one answer. These tests therefore drive the
production pair in production order: confirm, then track.
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerFlows, SessionData,
)


def _host(*, boot_ago_s=9999.0, session_kwh=6.0):
    h = SimpleNamespace()
    h.config = {"update_interval": 10}
    h._boot_monotonic = time.monotonic() - boot_ago_s
    # The car has been on the cable: both the session edge and the plug
    # confirmation carry that history into the cycle under test.
    h._last_ev_connected = True
    h._ev_conn_confirmed = {"": True}
    h._ev_conn_streak = {}
    h._session_data = SessionData(
        active=True, start_time="2026-08-11T08:00:00+02:00",
        energy_kwh=session_kwh, solar_energy_kwh=session_kwh * 0.8,
        grid_energy_kwh=session_kwh * 0.2)
    h._storage = MagicMock()
    h._ev_device = None
    h._this_charger_power = lambda ev, p: float(getattr(p, "ev_power", 0.0))
    h._energy_calculator = SimpleNamespace(_import_rate=0.3)
    return h


def _power(connected, ev_power=0.0):
    return SimpleNamespace(ev_connected=connected, ev_power=ev_power,
                           ev_connected_per_charger=None)


def _tick(h, connected, ev_power=0.0):
    """One coordinator cycle's EV path: the plug answer is confirmed at the
    source (step 1), then session tracking reads it (step 4.5)."""
    p = _power(connected, ev_power)
    EVControlMixin._confirm_ev_connection(h, p)
    EVControlMixin._update_session_tracking(h, p, PowerFlows())


@pytest.mark.unit
class TestWarmupDisconnectHoldsTheSession:
    def test_a_boot_window_disconnect_never_ends_the_session(self):
        h = _host(boot_ago_s=30.0)  # 30 s after boot — sensors warming
        for _ in range(6):
            _tick(h, connected=False)
        assert h._session_data.active is True
        assert h._session_data.energy_kwh == pytest.approx(6.0)
        assert not h._storage.update_lifetime_ev_stats.called
        # The edge stays armed — the flag must not flip on a held cycle.
        assert h._last_ev_connected is True

    def test_the_session_resumes_accumulating_after_the_warmup(self):
        h = _host(boot_ago_s=30.0)
        _tick(h, connected=False)          # warm-up blip
        _tick(h, connected=True, ev_power=4000.0)  # sensor back
        assert h._session_data.active is True
        assert h._session_data.energy_kwh >= 6.0   # same session, still counting


@pytest.mark.unit
class TestARealDisconnectStillEnds:
    def test_three_consecutive_cycles_end_the_session(self):
        h = _host()
        _tick(h, connected=False)
        _tick(h, connected=False)
        assert h._session_data.active is True   # debouncing
        _tick(h, connected=False)
        assert h._session_data.active is False  # confirmed
        assert h._storage.update_lifetime_ev_stats.called
        assert h._last_ev_connected is False

    def test_a_blip_resets_the_streak(self):
        """The KEBA UDP blip family: False, False, True must NOT leave the
        streak armed — two more Falses are a new count, not a third."""
        h = _host()
        _tick(h, connected=False)
        _tick(h, connected=False)
        _tick(h, connected=True, ev_power=4000.0)
        _tick(h, connected=False)
        _tick(h, connected=False)
        assert h._session_data.active is True
        _tick(h, connected=False)
        assert h._session_data.active is False

    def test_a_host_without_the_boot_stamp_is_not_in_warmup(self):
        """Mocks / old hosts without _boot_monotonic must behave as
        long-booted — the debounce alone protects them."""
        h = _host()
        del h._boot_monotonic
        _tick(h, connected=False)
        _tick(h, connected=False)
        assert h._session_data.active is True
        _tick(h, connected=False)
        assert h._session_data.active is False
