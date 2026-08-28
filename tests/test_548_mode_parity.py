"""#548 — every charge mode reacts on the Wallbox exactly as on KEBA.

The four charge modes (off / solar_only / min_plus_solar / always_max)
are decided by the brand-agnostic ``decide()``; it emits the SAME
:class:`ChargerIntent` regardless of charger brand. What differs per
brand is how the adapter *actuates* that intent. This test pins the
parity: for each intent a mode can produce, both the KEBA adapter and
the Wallbox adapter issue an effective hardware command (a stop the
contactor honours, a charge at the right current), and the status-driven
observation added in #548 does not break the charge path.

KEBA stops via ``stop_session()`` (keba.disable — set_current(0) is a
no-op on KEBA). Wallbox stops via ``set_current(0)`` + pause switch.
Same outcome, brand-correct mechanism.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters import (
    KebaAdapter,
    WallboxAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerPower,
)


def _keba_device():
    d = Mock()
    d.name = "keba"
    d.charger_service = "keba.set_current"
    d.charger_service_entity_id = "binary_sensor.keba_p30_plug"
    d.start_stop_entity = None
    d.hass = MagicMock()
    d.hass.services.async_call = AsyncMock()
    d._set_current = AsyncMock()
    d.stop_session = AsyncMock()
    d.start_session = AsyncMock()
    d.arm_failsafe = AsyncMock()
    d.park_off = AsyncMock()  # (#853)
    d._session_active = False
    d._current_setpoint = 0
    d.min_current = 6
    d.max_current = 32
    d.phases = 3
    d.voltage = 230
    return d


def _wallbox_device(status="Charging"):
    d = Mock()
    d.name = "wallbox"
    d.charger_service = "input_number.set_value"
    d.charger_service_entity_id = "number.wallbox_pulsar_charging_current"
    d.current_entity_id = "input_number.mock_wallbox_current"
    d.start_stop_entity = "input_boolean.mock_wallbox_pause"
    d.charging_status_entity = "input_select.mock_wallbox_status"
    d.hass = MagicMock()
    states = {
        "input_select.mock_wallbox_status": SimpleNamespace(state=status),
        "input_boolean.mock_wallbox_pause": SimpleNamespace(state="on"),
    }
    d.hass.states.get = lambda eid: states.get(eid)
    d.hass.services.async_call = AsyncMock()
    d._set_current = AsyncMock()
    d.stop_session = AsyncMock()
    d.start_session = AsyncMock()
    d._session_active = False
    d._current_setpoint = 0
    d.min_current = 6
    d.max_current = 32
    d.phases = 3
    d.voltage = 230
    return d


def _power(w):
    return ChargerPower(charger_id="c", power_w=w)


# ── off mode → DISABLE: both contactors open ──────────────────────────

class TestOffMode:
    @pytest.mark.asyncio
    async def test_keba_disable_parks_the_box(self):
        """(#853) A hard no PARKS — disable + failsafe, zero allowance.
        The quota-hold (stop_session) would grant a fresh 1 kWh floor."""
        d = _keba_device()
        await KebaAdapter(d).command_disable()
        d.park_off.assert_called()
        d.stop_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_wallbox_disable_stops_via_setpoint(self):
        d = _wallbox_device()
        a = WallboxAdapter(d)
        a._pause_switch_entity = "input_boolean.mock_wallbox_pause"
        a._pause_switch_searched = True
        await a.command_disable()
        d._set_current.assert_called_with(0)  # contactor open


# ── always_max → CHARGE_MAX: both command hardware max ────────────────

class TestAlwaysMax:
    @pytest.mark.asyncio
    async def test_keba_max(self):
        d = _keba_device()
        await KebaAdapter(d).command_max()
        d._set_current.assert_called_with(32)

    @pytest.mark.asyncio
    async def test_wallbox_max(self):
        d = _wallbox_device()
        a = WallboxAdapter(d)
        a._pause_switch_entity = "input_boolean.mock_wallbox_pause"
        a._pause_switch_searched = True
        await a.command_max()
        d._set_current.assert_called_with(32)


# ── solar / min_plus_solar with surplus → CHARGE_AT_AMPS ──────────────

class TestChargeAtAmps:
    @pytest.mark.asyncio
    async def test_keba_charge_at_amps(self):
        d = _keba_device()
        await KebaAdapter(d).command_current(10)
        d._set_current.assert_called_with(10)

    @pytest.mark.asyncio
    async def test_wallbox_charge_at_amps(self):
        d = _wallbox_device()
        a = WallboxAdapter(d)
        a._pause_switch_entity = "input_boolean.mock_wallbox_pause"
        a._pause_switch_searched = True
        await a.command_current(10)
        d._set_current.assert_called_with(10)

    @pytest.mark.asyncio
    async def test_below_min_routes_to_idle_on_both(self):
        # surplus drops below 6 A — both must stop, not hold the last setpoint.
        dk = _keba_device()
        await KebaAdapter(dk).command_current(3)
        dk.stop_session.assert_called()  # KEBA: keba.disable

        dw = _wallbox_device()
        aw = WallboxAdapter(dw)
        aw._pause_switch_entity = "input_boolean.mock_wallbox_pause"
        aw._pause_switch_searched = True
        await aw.command_current(3)
        dw._set_current.assert_called_with(0)  # Wallbox: setpoint 0


# ── solar_only with NO surplus → IDLE: both contactors open ───────────

class TestIdle:
    @pytest.mark.asyncio
    async def test_keba_idle(self):
        d = _keba_device()
        d._session_active = True
        await KebaAdapter(d).command_idle()
        d.stop_session.assert_called()

    @pytest.mark.asyncio
    async def test_wallbox_idle(self):
        d = _wallbox_device()
        a = WallboxAdapter(d)
        a._pause_switch_entity = "input_boolean.mock_wallbox_pause"
        a._pause_switch_searched = True
        await a.command_idle()
        d._set_current.assert_called_with(0)


# ── observation parity: the #548 status read doesn't break charging ───

class TestObservationParity:
    def test_wallbox_charging_status_reads_charging(self):
        # While charging, both adapters report actual_charging True. KEBA
        # via power; Wallbox via the status enum (even before cloud power
        # catches up).
        assert KebaAdapter(_keba_device()).actual_charging(_power(4000)) is True
        assert WallboxAdapter(_wallbox_device("Charging")).actual_charging(_power(0)) is True

    def test_wallbox_paused_status_reads_not_charging(self):
        # KEBA at handshake power = not charging; Wallbox Paused = not
        # charging even if cloud power lags high.
        assert KebaAdapter(_keba_device()).actual_charging(_power(100)) is False
        assert WallboxAdapter(_wallbox_device("Paused")).actual_charging(_power(5000)) is False
