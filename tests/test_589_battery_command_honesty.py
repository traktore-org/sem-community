"""#589 — honest battery command results + teardown/boot reconcile.

Tests covered:
  FD1 — force-discharge: _write returns False (service raises) →
         _last_intent unchanged AND _last_error set
  FD2 — force-discharge: subsequent call with working service →
         _last_intent becomes FORCE_DISCHARGE, _last_error cleared
  FD3 — force-discharge: within-100W de-dup skip → True → intent recorded
  FD4 — force-discharge: no force_discharge_entity → True → intent recorded

  FC_H1 — force-charge (huawei): delegate returns FAILED →
           _last_intent unchanged + _last_error set
  FC_H2 — force-charge (huawei): delegate returns CHARGING →
           _last_intent = FORCE_CHARGE, _last_error cleared

  FC_G1 — force-charge (generic switch path): delegate returns FAILED →
           _last_intent unchanged + _last_error set
  FC_G2 — force-charge (generic switch path): delegate returns CHARGING →
           _last_intent = FORCE_CHARGE, _last_error cleared
  FC_G3 — force-charge (generic bidirectional): write fails →
           _last_intent unchanged + _last_error set
  FC_G4 — force-charge (generic bidirectional): write succeeds →
           _last_intent = FORCE_CHARGE

  OFF1  — command_off: internal command_normal fails → OFF not recorded
  OFF2  — command_off: command_normal succeeds → OFF recorded

  SFD1  — command_stop_force_discharge (base): write(0) fails → intent unchanged
  SFD2  — command_stop_force_discharge (base): write(0) succeeds → STOP_FORCE_DISCHARGE

  UL1   — async_unload_entry calls command_normal on each cached adapter
  UL2   — async_unload_entry swallows adapter exceptions (never blocks unload)

  BC1   — boot: forcible-charge active + no SEM intent → stop issued (#589 Part C)
  BC2   — boot: status not readable (absent) → no action
  BC3   — boot: _forcible_charging = True → orphan-clear skipped (we started it)
  BC4   — boot: status pending → defer (one-shot not consumed)
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    BatteryControlAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.battery_charge_adapter import (
    ChargeCommandStatus,
    ChargeStatus,
)


# ── Minimal concrete subclass of BatteryControlAdapter for base tests ─────────

class _MinimalAdapter(BatteryControlAdapter):
    """Concrete adapter that delegates everything to the base, with a
    controllable ``command_normal`` outcome."""

    _normal_ok: bool = True  # set to False to simulate a failing command_normal

    @property
    def max_charge_power_w(self) -> float:
        return 5000.0

    @property
    def max_discharge_power_w(self) -> float:
        return 5000.0

    @property
    def supports_forced_charge(self) -> bool:
        return False

    async def command_normal(self) -> None:
        if not self._normal_ok:
            raise RuntimeError("simulated normal failure")
        self._last_intent = BatteryIntent.NORMAL

    async def command_limit_discharge(self, watts: float) -> None:
        self._last_intent = BatteryIntent.LIMIT_DISCHARGE

    async def command_force_charge(
        self, target_soc: float, charge_power_w: float, duration_min: int,
    ) -> None:
        self._last_intent = BatteryIntent.FORCE_CHARGE

    async def command_stop_force_charge(self) -> None:
        self._last_intent = BatteryIntent.STOP_FORCE_CHARGE


def _make_hass(service_raises: bool = False, state=None) -> MagicMock:
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = Mock(return_value=state)
    if service_raises:
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock(
            side_effect=RuntimeError("simulated HA service failure"),
        )
    else:
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock(return_value=None)
    return hass


def _entity_state(current: float, lo: float = 0.0, hi: float = 10000.0) -> Mock:
    st = Mock()
    st.state = str(current)
    st.attributes = {"min": lo, "max": hi}
    return st


# ── Part A: base._write_force_discharge + command_force_discharge ─────────────

class TestForceDischargeHonesty:

    @pytest.mark.asyncio
    async def test_fd1_write_fails_intent_unchanged(self) -> None:
        """FD1: service raises → _last_intent stays None, _last_error set."""
        hass = _make_hass(service_raises=True)
        adapter = _MinimalAdapter(
            hass,
            {"battery_force_discharge_control_entity": "number.fd_power"},
        )
        # Give it a known state so clamping passes.
        hass.states.get.return_value = _entity_state(0.0)
        await adapter.command_force_discharge(3000.0, 20.0)

        assert adapter.last_intent is None
        assert adapter.last_error is not None
        assert "write_force_discharge" in adapter.last_error

    @pytest.mark.asyncio
    async def test_fd2_write_succeeds_intent_recorded(self) -> None:
        """FD2: after a working service call, intent becomes FORCE_DISCHARGE."""
        hass = _make_hass(service_raises=False)
        adapter = _MinimalAdapter(
            hass,
            {"battery_force_discharge_control_entity": "number.fd_power"},
        )
        hass.states.get.return_value = _entity_state(0.0)
        await adapter.command_force_discharge(3000.0, 20.0)

        assert adapter.last_intent is BatteryIntent.FORCE_DISCHARGE
        assert adapter.last_error is None

    @pytest.mark.asyncio
    async def test_fd2_retry_after_failure(self) -> None:
        """FD2 retry: first call fails, second succeeds → intent recorded."""
        hass_fail = _make_hass(service_raises=True)
        adapter = _MinimalAdapter(
            hass_fail,
            {"battery_force_discharge_control_entity": "number.fd_power"},
        )
        hass_fail.states.get.return_value = _entity_state(0.0)
        await adapter.command_force_discharge(3000.0, 20.0)
        assert adapter.last_intent is None

        # Swap to a working hass
        hass_ok = _make_hass(service_raises=False)
        hass_ok.states.get.return_value = _entity_state(0.0)
        adapter._hass = hass_ok
        # Reset de-dup cache so the write goes through
        adapter._last_force_discharge_w = None
        await adapter.command_force_discharge(3000.0, 20.0)
        assert adapter.last_intent is BatteryIntent.FORCE_DISCHARGE
        assert adapter.last_error is None

    @pytest.mark.asyncio
    async def test_fd3_dedup_skip_records_intent(self) -> None:
        """FD3: within-100W de-dup skip → True → intent recorded."""
        hass = _make_hass(service_raises=False)
        adapter = _MinimalAdapter(
            hass,
            {"battery_force_discharge_control_entity": "number.fd_power"},
        )
        hass.states.get.return_value = _entity_state(0.0)
        # Seed the de-dup cache at 3000 W.
        adapter._last_force_discharge_w = 3000.0
        # Request 3050 W — within 100 W → de-dup skip.
        await adapter.command_force_discharge(3050.0, 20.0)

        assert adapter.last_intent is BatteryIntent.FORCE_DISCHARGE
        assert adapter.last_error is None

    @pytest.mark.asyncio
    async def test_fd4_no_entity_no_op_records_intent(self) -> None:
        """FD4: no force_discharge_entity → benign True → intent recorded."""
        hass = _make_hass(service_raises=False)
        adapter = _MinimalAdapter(hass, {})  # no entity configured
        await adapter.command_force_discharge(3000.0, 20.0)

        assert adapter.last_intent is BatteryIntent.FORCE_DISCHARGE
        assert adapter.last_error is None


# ── command_stop_force_discharge (base) ──────────────────────────────────────

class TestStopForceDischarge:

    @pytest.mark.asyncio
    async def test_sfd1_write_zero_fails_intent_unchanged(self) -> None:
        """SFD1: write(0) fails → intent unchanged."""
        hass = _make_hass(service_raises=True)
        adapter = _MinimalAdapter(
            hass,
            {"battery_force_discharge_control_entity": "number.fd_power"},
        )
        hass.states.get.return_value = _entity_state(0.0)
        # Force a prior intent so we can check it doesn't change.
        adapter._last_intent = BatteryIntent.FORCE_DISCHARGE
        adapter._last_force_discharge_w = None  # not yet written
        await adapter.command_stop_force_discharge()

        assert adapter.last_intent is BatteryIntent.FORCE_DISCHARGE
        assert adapter.last_error is not None

    @pytest.mark.asyncio
    async def test_sfd2_stop_succeeds_records_stop(self) -> None:
        """SFD2: write(0) succeeds → STOP_FORCE_DISCHARGE recorded."""
        hass = _make_hass(service_raises=False)
        adapter = _MinimalAdapter(
            hass,
            {"battery_force_discharge_control_entity": "number.fd_power"},
        )
        hass.states.get.return_value = _entity_state(3000.0)
        adapter._last_force_discharge_w = None
        await adapter.command_stop_force_discharge()

        assert adapter.last_intent is BatteryIntent.STOP_FORCE_DISCHARGE
        assert adapter.last_error is None


# ── command_off ───────────────────────────────────────────────────────────────

class TestCommandOff:

    @pytest.mark.asyncio
    async def test_off1_normal_fails_off_not_recorded(self) -> None:
        """OFF1: command_normal raises → OFF not recorded, intent unchanged."""
        hass = _make_hass(service_raises=False)
        adapter = _MinimalAdapter(hass, {})
        adapter._normal_ok = False
        adapter._last_intent = BatteryIntent.NORMAL

        with pytest.raises(RuntimeError):
            await adapter.command_off()

        assert adapter.last_intent is not BatteryIntent.OFF

    @pytest.mark.asyncio
    async def test_off2_normal_succeeds_off_recorded(self) -> None:
        """OFF2: command_normal succeeds → OFF recorded."""
        hass = _make_hass(service_raises=False)
        adapter = _MinimalAdapter(hass, {})
        adapter._last_intent = BatteryIntent.NORMAL
        await adapter.command_off()

        assert adapter.last_intent is BatteryIntent.OFF
        assert adapter.last_error is None

    @pytest.mark.asyncio
    async def test_off3_already_off_is_noop(self) -> None:
        """Already-off path stays silent (no extra command_normal calls)."""
        hass = _make_hass(service_raises=False)
        adapter = _MinimalAdapter(hass, {})
        adapter._last_intent = BatteryIntent.OFF
        # Would raise if command_normal were called because _normal_ok=False.
        adapter._normal_ok = False
        # Should NOT raise — the early-return fires.
        await adapter.command_off()
        assert adapter.last_intent is BatteryIntent.OFF


# ── Force-charge: Huawei ─────────────────────────────────────────────────────

def _make_huawei(service_raises: bool = False) -> HuaweiBatteryAdapter:
    hass = _make_hass(service_raises=service_raises)
    hass.states.async_all = Mock(return_value=[])
    config = {
        "inverter_device_id": "dev-abc",
        "battery_max_charge_power": 5000,
        "battery_max_discharge_power": 5000,
    }
    with patch(
        "custom_components.solar_energy_management.coordinator"
        ".battery_adapters.huawei.HuaweiBatteryAdapter._autodetect_battery_device",
        return_value=None,
    ):
        adapter = HuaweiBatteryAdapter(hass, config)
    return adapter


class TestHuaweiForceChargeHonesty:

    @pytest.mark.asyncio
    async def test_fc_h1_failed_status_intent_unchanged(self) -> None:
        """FC_H1: delegate returns FAILED → _last_intent unchanged, error set."""
        adapter = _make_huawei()
        failed_status = ChargeStatus(
            status=ChargeCommandStatus.FAILED,
            message="no device",
        )
        adapter._charge_adapter.start_forced_charge = AsyncMock(
            return_value=failed_status,
        )
        # Ensure orphan check is already done.
        adapter._startup_orphan_checked = True

        await adapter.command_force_charge(80.0, 3000.0, 120)

        assert adapter.last_intent is None
        assert adapter.last_error is not None
        assert "start_forced_charge" in adapter.last_error

    @pytest.mark.asyncio
    async def test_fc_h2_charging_status_records_intent(self) -> None:
        """FC_H2: delegate returns CHARGING → FORCE_CHARGE recorded."""
        adapter = _make_huawei()
        ok_status = ChargeStatus(
            status=ChargeCommandStatus.CHARGING,
            target_soc=80.0,
            charge_power_w=3000.0,
            message="ok",
        )
        adapter._charge_adapter.start_forced_charge = AsyncMock(
            return_value=ok_status,
        )
        adapter._startup_orphan_checked = True

        await adapter.command_force_charge(80.0, 3000.0, 120)

        assert adapter.last_intent is BatteryIntent.FORCE_CHARGE
        assert adapter.last_error is None
        assert adapter._forcible_charging is True


# ── Force-charge: Generic ─────────────────────────────────────────────────────

def _make_generic(bidirectional: bool = False) -> GenericBatteryAdapter:
    hass = _make_hass(service_raises=False)
    hass.states.get = Mock(return_value=_entity_state(0.0))
    config: dict = {
        "battery_max_charge_power": 5000,
        "battery_max_discharge_power": 5000,
    }
    if bidirectional:
        config["battery_setpoint_bidirectional"] = True
        config["battery_force_discharge_control_entity"] = "number.setpoint"
    else:
        config["battery_force_charge_switch"] = "switch.force_charge"
        config["battery_target_soc_entity"] = "number.target_soc"
    return GenericBatteryAdapter(hass, config)


class TestGenericForceChargeHonesty:

    @pytest.mark.asyncio
    async def test_fc_g1_switch_delegate_failed_intent_unchanged(self) -> None:
        """FC_G1: switch-path delegate FAILED → unchanged + error set."""
        adapter = _make_generic(bidirectional=False)
        failed_status = ChargeStatus(
            status=ChargeCommandStatus.FAILED,
            message="switch unreachable",
        )
        adapter._charge_adapter.start_forced_charge = AsyncMock(
            return_value=failed_status,
        )
        await adapter.command_force_charge(80.0, 3000.0, 120)

        assert adapter.last_intent is None
        assert adapter.last_error is not None
        assert "start_forced_charge" in adapter.last_error

    @pytest.mark.asyncio
    async def test_fc_g2_switch_delegate_charging_records_intent(self) -> None:
        """FC_G2: switch-path delegate CHARGING → FORCE_CHARGE recorded."""
        adapter = _make_generic(bidirectional=False)
        ok_status = ChargeStatus(
            status=ChargeCommandStatus.CHARGING,
            target_soc=80.0,
            message="ok",
        )
        adapter._charge_adapter.start_forced_charge = AsyncMock(
            return_value=ok_status,
        )
        await adapter.command_force_charge(80.0, 3000.0, 120)

        assert adapter.last_intent is BatteryIntent.FORCE_CHARGE
        assert adapter.last_error is None

    @pytest.mark.asyncio
    async def test_fc_g3_bidirectional_write_fails_intent_unchanged(self) -> None:
        """FC_G3: bidirectional write raises → unchanged + error set."""
        adapter = _make_generic(bidirectional=True)
        # Make the service call fail.
        adapter._hass.services.async_call = AsyncMock(
            side_effect=RuntimeError("bus error"),
        )
        # Reset de-dup so the write is attempted.
        adapter._last_force_discharge_w = None
        await adapter.command_force_charge(80.0, 3000.0, 120)

        assert adapter.last_intent is None
        assert adapter.last_error is not None

    @pytest.mark.asyncio
    async def test_fc_g4_bidirectional_write_succeeds_records_intent(self) -> None:
        """FC_G4: bidirectional write OK → FORCE_CHARGE recorded."""
        adapter = _make_generic(bidirectional=True)
        adapter._last_force_discharge_w = None  # force write
        await adapter.command_force_charge(80.0, 3000.0, 120)

        assert adapter.last_intent is BatteryIntent.FORCE_CHARGE
        assert adapter.last_error is None


# ── Part B: unload teardown ───────────────────────────────────────────────────

class TestUnloadTeardown:
    """UL1/UL2 — async_unload_entry calls command_normal on adapters."""

    @pytest.mark.asyncio
    async def test_ul1_command_normal_called_on_each_adapter(self) -> None:
        """UL1: unload iterates _battery_adapters and calls command_normal."""
        from unittest.mock import AsyncMock as AM

        mock_adapter_a = MagicMock()
        mock_adapter_a.command_normal = AM(return_value=None)
        mock_adapter_b = MagicMock()
        mock_adapter_b.command_normal = AM(return_value=None)

        mock_coord = MagicMock()
        mock_coord._battery_adapters = {
            "primary": mock_adapter_a,
            "secondary": mock_adapter_b,
        }
        mock_coord._surplus_controller = None

        hass = MagicMock()
        hass.data = {"solar_energy_management": {"entry-1": mock_coord}}
        hass.config_entries = MagicMock()
        hass.config_entries.async_unload_platforms = AM(return_value=True)
        hass.services = MagicMock()
        hass.services.async_remove = Mock()

        entry = MagicMock()
        entry.entry_id = "entry-1"

        from custom_components.solar_energy_management import async_unload_entry
        result = await async_unload_entry(hass, entry)

        assert result is True
        mock_adapter_a.command_normal.assert_awaited_once()
        mock_adapter_b.command_normal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ul2_adapter_exception_does_not_block_unload(self) -> None:
        """UL2: adapter raising in command_normal never blocks unload."""
        from unittest.mock import AsyncMock as AM

        mock_adapter = MagicMock()
        mock_adapter.command_normal = AM(
            side_effect=RuntimeError("flaky Modbus"),
        )
        mock_coord = MagicMock()
        mock_coord._battery_adapters = {"primary": mock_adapter}
        mock_coord._surplus_controller = None

        hass = MagicMock()
        hass.data = {"solar_energy_management": {"entry-1": mock_coord}}
        hass.config_entries = MagicMock()
        hass.config_entries.async_unload_platforms = AM(return_value=True)
        hass.services = MagicMock()
        hass.services.async_remove = Mock()

        entry = MagicMock()
        entry.entry_id = "entry-1"

        from custom_components.solar_energy_management import async_unload_entry
        result = await async_unload_entry(hass, entry)

        assert result is True  # unload not blocked by adapter failure


# ── Part C: boot orphan-clear for forcible-charge (#589) ─────────────────────

def _make_huawei_boot(forcible_status: str = "absent") -> HuaweiBatteryAdapter:
    """Adapter at boot — _startup_orphan_checked = False."""
    hass = _make_hass(service_raises=False)

    # Simulate a forcible sensor state for _forcible_status_reading.
    if forcible_status == "active":
        st = Mock()
        st.entity_id = "sensor.batteries_forcible_charge"
        st.state = "charge"
        hass.states.async_all = Mock(return_value=[st])
    elif forcible_status == "stopped":
        st = Mock()
        st.entity_id = "sensor.batteries_forcible_charge"
        st.state = "stop"
        hass.states.async_all = Mock(return_value=[st])
    elif forcible_status == "pending":
        st = Mock()
        st.entity_id = "sensor.batteries_forcible_charge"
        st.state = "unknown"
        hass.states.async_all = Mock(return_value=[st])
    else:  # absent
        hass.states.async_all = Mock(return_value=[])

    config = {
        "inverter_device_id": "dev-abc",
        "battery_max_charge_power": 5000,
        "battery_max_discharge_power": 5000,
    }
    with (
        patch(
            "custom_components.solar_energy_management.coordinator"
            ".battery_adapters.huawei.HuaweiBatteryAdapter._autodetect_battery_device",
            return_value=None,
        ),
        patch(
            "custom_components.solar_energy_management.coordinator"
            ".battery_adapters._integration_loaded",
            return_value=True,
        ),
    ):
        adapter = HuaweiBatteryAdapter(hass, config)
    return adapter


class TestBootOrphanClear:

    @pytest.mark.asyncio
    async def test_bc1_active_charge_orphan_stopped(self) -> None:
        """BC1: forcible op active + no SEM intent → stop issued."""
        adapter = _make_huawei_boot(forcible_status="active")
        assert not adapter._startup_orphan_checked
        assert not adapter._forcible_discharging
        assert not adapter._forcible_charging

        # command_normal triggers _maybe_clear_startup_orphan
        with patch(
            "custom_components.solar_energy_management.coordinator"
            ".battery_adapters._integration_loaded",
            return_value=True,
        ):
            await adapter.command_normal()

        adapter._hass.services.async_call.assert_awaited()
        # The stop_forcible_charge service must have been called.
        calls = adapter._hass.services.async_call.call_args_list
        service_names = [c[0][1] for c in calls if len(c[0]) > 1]
        assert "stop_forcible_charge" in service_names

    @pytest.mark.asyncio
    async def test_bc2_absent_status_no_action(self) -> None:
        """BC2: status absent (no sensor) → orphan-clear consumes one-shot,
        no stop issued."""
        adapter = _make_huawei_boot(forcible_status="absent")
        with patch(
            "custom_components.solar_energy_management.coordinator"
            ".battery_adapters._integration_loaded",
            return_value=True,
        ):
            await adapter.command_normal()

        # No stop_forcible_charge should have been called.
        calls = adapter._hass.services.async_call.call_args_list
        service_names = [c[0][1] for c in calls if len(c[0]) > 1]
        assert "stop_forcible_charge" not in service_names

    @pytest.mark.asyncio
    async def test_bc3_forcible_charging_set_skips_orphan_clear(self) -> None:
        """BC3: _forcible_charging = True → we started it, skip orphan clear."""
        adapter = _make_huawei_boot(forcible_status="active")
        adapter._forcible_charging = True  # SEM started this charge

        with patch(
            "custom_components.solar_energy_management.coordinator"
            ".battery_adapters._integration_loaded",
            return_value=True,
        ):
            result = await adapter._maybe_clear_startup_orphan()

        assert result is False  # didn't issue a stop
        assert adapter._startup_orphan_checked is True

    @pytest.mark.asyncio
    async def test_bc4_pending_status_defers(self) -> None:
        """BC4: status pending → one-shot NOT consumed, no stop issued."""
        adapter = _make_huawei_boot(forcible_status="pending")

        with patch(
            "custom_components.solar_energy_management.coordinator"
            ".battery_adapters._integration_loaded",
            return_value=True,
        ):
            result = await adapter._maybe_clear_startup_orphan()

        assert result is False
        # One-shot NOT consumed — retries next cycle.
        assert adapter._startup_orphan_checked is False
