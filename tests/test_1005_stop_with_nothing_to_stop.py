"""#1005 — a stop with nothing to stop must not report failure.

@RienduPre, 2× Sessy on the generic adapter, no force-charge switch
configured. ``diagnose`` showed the same line on both units for 28 h::

    last_error: "stop_forced_charge failed: Stop failed: expected 'all' or
                 'none' at 'entity_id'"
    setpoint.device_refusals: 165

The chain, and why every link was working as written:

* ``decide_battery`` returns STOP_FORCE_CHARGE on EVERY cycle a scheduled
  battery sits outside its plan block (#638 C4).
* #757 makes that repeat silent by keying on ``_last_intent``.
* ``_last_intent`` may only be set on a stop that LANDED — a dropped Modbus
  write must be retried, not remembered as a success (#589 honest retry).
* So the guard can only ever engage if the stop can succeed at least once.

With no switch, ``GenericChargeAdapter.stop_forced_charge`` called
``switch.turn_off`` with an empty ``entity_id``. Home Assistant rejects that,
so the stop reported FAILED — for a config gap, which no number of retries can
clear. Honest retry became endless retry, and the full stop path ran every
cycle for the life of the install: the #523 zero-write to the Sessy setpoint
(refused by the device, spending the #840 strikes that withdraw
battery-to-grid) plus the strategy write back to self-consumption.

The cure is at the delegate: with no actuator to turn off, no forced charge
can be running — ``start_forced_charge`` refuses without it — so the stop is
already complete. IDLE, nothing sent, intent recorded, #757 takes over.

Note what the #757 tests could not see: they mock ``stop_forced_charge`` with
a fake that always succeeds, so the layer where this bug lives was replaced by
a layer that cannot have it. The fake ``hass`` here REFUSES an empty
``entity_id``, the way the real one does.
"""
from __future__ import annotations

import inspect

import pytest
import voluptuous as vol
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from custom_components.solar_energy_management.coordinator import (
    battery_adapters as pkg,
)
from custom_components.solar_energy_management.coordinator.battery_adapters import (
    force_charge as fc,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    BatteryControlAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.deye import (
    DeyeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.goodwe import (
    GoodWeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)


def _state(value, attrs=None) -> Mock:
    st = Mock()
    st.state = str(value)
    st.attributes = attrs or {}
    return st


def _setpoint_state(current: float = 0.0) -> Mock:
    return _state(current, {"min": -2200.0, "max": 2200.0,
                            "unit_of_measurement": "W"})


def _strict_hass(states: dict | None = None) -> MagicMock:
    """A hass whose service call refuses an empty target, like the real one.

    ``{"entity_id": ""}`` never reaches an integration: the service schema
    rejects it first — ``expected 'all' or 'none' at 'entity_id'``, the exact
    message from the reporter's diagnostics. A fake that accepts it hides
    every bug of this shape, which is why the #757 tests could not see this
    one.

    ``select_option`` is REFLECTED into the state map, the #978 rule: a fake
    that swallows a flip models away the very write it should prove.
    """
    table = dict(states or {})
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = Mock(side_effect=lambda ent: table.get(ent))
    hass.states.async_all = Mock(return_value=[])
    hass.services = MagicMock()

    async def _call(domain, service, data=None, **kw):
        data = data or {}
        ent = str(data.get("entity_id", "") or "").strip()
        if "entity_id" in data and not ent:
            raise vol.Invalid("expected 'all' or 'none' at 'entity_id'")
        if "device_id" in data and not str(data["device_id"] or "").strip():
            raise vol.Invalid("expected a device id at 'device_id'")
        if service == "select_option" and ent:
            table[ent] = _state(data["option"])
        return None

    hass.services.async_call = AsyncMock(side_effect=_call)
    hass.sem_states = table
    return hass


# ── the reporter's own three cases, at the delegate ──────────────────────

class TestTheDelegateSaysNothingToStop:
    @pytest.mark.asyncio
    async def test_generic_no_switch_is_idle_and_silent(self) -> None:
        hass = _strict_hass()
        adapter = fc.GenericChargeAdapter(hass, {})

        status = await adapter.stop_forced_charge()

        assert status.status is fc.ChargeCommandStatus.IDLE
        assert hass.services.async_call.await_count == 0
        assert adapter.is_active is False

    @pytest.mark.asyncio
    async def test_generic_with_a_switch_still_turns_it_off(self) -> None:
        """The guard is on the switch, never on ``_active``: a fresh adapter
        after a restart must still clear a charge a prior lifetime left
        running (#757's boot-orphan rule)."""
        hass = _strict_hass()
        adapter = fc.GenericChargeAdapter(
            hass, {"battery_force_charge_switch": "switch.force_charge"})
        assert adapter.is_active is False   # fresh — knows nothing

        status = await adapter.stop_forced_charge()

        assert status.status is fc.ChargeCommandStatus.IDLE
        hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_off", {"entity_id": "switch.force_charge"})

    @pytest.mark.asyncio
    async def test_goodwe_no_work_mode_entity_is_idle_and_silent(self) -> None:
        hass = _strict_hass()
        adapter = fc.GoodWeChargeAdapter(hass, {})

        status = await adapter.stop_forced_charge()

        assert status.status is fc.ChargeCommandStatus.IDLE
        assert hass.services.async_call.await_count == 0

    @pytest.mark.asyncio
    async def test_goodwe_with_a_work_mode_entity_still_restores(self) -> None:
        hass = _strict_hass()
        adapter = fc.GoodWeChargeAdapter(
            hass, {"inverter_work_mode_entity": "select.work_mode"})

        status = await adapter.stop_forced_charge()

        assert status.status is fc.ChargeCommandStatus.IDLE
        hass.services.async_call.assert_awaited_once_with(
            "select", "select_option",
            {"entity_id": "select.work_mode", "option": "General"})

    @pytest.mark.asyncio
    async def test_huawei_no_device_id_is_idle_and_silent(self) -> None:
        """A number-entity Huawei is a real install. Its charge adapter can
        never START a charge (the service needs the device id), so it has
        nothing to stop — and a forcible DISCHARGE is stopped one layer up."""
        hass = _strict_hass()
        adapter = fc.HuaweiChargeAdapter(hass, {})

        status = await adapter.stop_forced_charge()

        assert status.status is fc.ChargeCommandStatus.IDLE
        assert hass.services.async_call.await_count == 0

    @pytest.mark.asyncio
    async def test_huawei_with_a_device_id_still_stops(self) -> None:
        hass = _strict_hass()
        adapter = fc.HuaweiChargeAdapter(hass, {"inverter_device_id": "dev-abc"})

        status = await adapter.stop_forced_charge()

        assert status.status is fc.ChargeCommandStatus.IDLE
        hass.services.async_call.assert_awaited_once_with(
            "huawei_solar", "stop_forcible_charge", {"device_id": "dev-abc"})

    @pytest.mark.asyncio
    async def test_a_real_refusal_is_still_FAILED(self) -> None:
        """Only the unsatisfiable case became IDLE. Hardware that refuses a
        configured stop must still fail, so the next cycle retries."""
        hass = _strict_hass()
        hass.services.async_call = AsyncMock(side_effect=RuntimeError("modbus"))
        adapter = fc.GenericChargeAdapter(
            hass, {"battery_force_charge_switch": "switch.force_charge"})

        status = await adapter.stop_forced_charge()

        assert status.status is fc.ChargeCommandStatus.FAILED


# ── the reporter's night, through the real adapter ───────────────────────

SETPOINT = "number.sessy_1_power_setpoint"
STRATEGY = "select.sessy_1_power_strategy"


class TestTheReportersNight:
    """2× Sessy through the generic adapter: a bidirectional setpoint, a
    power-strategy select, and no force-charge switch."""

    def _sessy(self, strategy: str = "nom"):
        hass = _strict_hass({
            SETPOINT: _setpoint_state(0.0),
            STRATEGY: _state(strategy),
        })
        adapter = GenericBatteryAdapter(hass, {
            "battery_max_charge_power": 2200,
            "battery_max_discharge_power": 2200,
            "battery_force_discharge_control_entity": SETPOINT,
            "battery_strategy_control_entity": STRATEGY,
            "battery_setpoint_bidirectional": True,
        })
        return hass, adapter

    @pytest.mark.asyncio
    async def test_the_first_stop_records_the_intent(self) -> None:
        hass, adapter = self._sessy()

        await adapter.command_stop_force_charge()

        assert adapter.last_error is None
        assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE

    @pytest.mark.asyncio
    async def test_the_night_writes_nothing_after_the_first_cycle(self) -> None:
        """~1800 cycles between a 21:00 verdict and a 02:00 block. Before the
        fix each one re-ran the whole stop: the setpoint zero-write the Sessy
        refuses, and the strategy write."""
        hass, adapter = self._sessy()

        await adapter.command_stop_force_charge()
        after_first = hass.services.async_call.await_count

        for _ in range(300):
            await adapter.command_stop_force_charge()

        assert hass.services.async_call.await_count == after_first
        assert adapter.last_error is None

    @pytest.mark.asyncio
    async def test_the_setpoint_is_not_written_into_nom(self) -> None:
        """The 165 refusals. The battery reads ``nom``: it is not following
        the setpoint at all, so the mutual-exclusion zero lands nowhere — and
        #978 measured that this device REFUSES it, which spends the #840
        strikes that withdraw battery-to-grid. Three are enough."""
        hass, adapter = self._sessy(strategy="nom")

        for _ in range(50):
            await adapter.command_stop_force_charge()

        setpoint_writes = [
            c for c in hass.services.async_call.await_args_list
            if (c.args[2] if len(c.args) > 2 else {}).get("entity_id") == SETPOINT
        ]
        assert setpoint_writes == []
        assert adapter._force_discharge_failures == 0
        assert adapter.supports_forced_discharge is True

    @pytest.mark.asyncio
    async def test_an_unreadable_strategy_still_gets_the_zero(self) -> None:
        """Fail-safe (#925): "cannot read the select" is not "the setpoint is
        inert". When SEM cannot tell, it writes the zero — a zero can only
        ever stop the battery."""
        hass, adapter = self._sessy(strategy="unavailable")

        await adapter.command_stop_force_charge()

        assert any(
            (c.args[2] if len(c.args) > 2 else {}).get("entity_id") == SETPOINT
            for c in hass.services.async_call.await_args_list
        )

    @pytest.mark.asyncio
    async def test_a_real_charge_is_still_stopped(self) -> None:
        """Silence must not become deafness: a bidirectional charge SEM
        actually started is still zeroed — the strategy reads ``api`` there,
        so the setpoint is live and the zero goes out."""
        hass, adapter = self._sessy(strategy="api")

        await adapter.command_force_charge(80.0, 1500.0, 120)
        assert adapter.last_intent is BatteryIntent.FORCE_CHARGE
        assert adapter._last_force_discharge_w == -1500.0

        await adapter.command_stop_force_charge()
        assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE
        assert adapter._last_force_discharge_w == 0.0


# ── the class guard: no brand may answer a config gap with FAILED ────────

class TestNoDelegateFailsForAConfigGap:
    """The oracle, not an instance (#1005 class).

    Every ``stop_forced_charge`` in ``force_charge.py`` needs an actuator its
    own ``start_forced_charge`` refuses to run without. Asked to stop with
    NOTHING configured, it must report a status the caller can record — never
    FAILED, which the caller is required to retry forever.

    Brands are discovered, not listed: a new delegate is covered the day it
    is written.
    """

    def _delegates(self):
        found = [
            obj for _, obj in inspect.getmembers(fc, inspect.isclass)
            if issubclass(obj, fc.BatteryChargeAdapter)
            and obj is not fc.BatteryChargeAdapter
            and obj.__module__ == fc.__name__
        ]
        assert found, "no charge delegates discovered — the oracle is blind"
        return found

    @pytest.mark.asyncio
    async def test_every_delegate_is_silent_and_not_failed(self) -> None:
        for cls in self._delegates():
            hass = _strict_hass()
            adapter = cls(hass, {})

            status = await adapter.stop_forced_charge()

            assert status.status is not fc.ChargeCommandStatus.FAILED, (
                f"{cls.__name__}.stop_forced_charge reports FAILED with no "
                f"config. The caller must retry a FAILED stop every cycle "
                f"for ever (#589 honest retry), and a config gap never "
                f"clears — return IDLE via _nothing_to_stop() instead (#1005)"
            )
            assert hass.services.async_call.await_count == 0, (
                f"{cls.__name__}.stop_forced_charge called a service with "
                f"nothing configured to call it on"
            )


class TestEveryAdapterGoesQuiet:
    """The same question one layer up: the wrapper's per-cycle path.

    An unconfigured battery of ANY brand must fall silent after the first
    stop — that is what #757 promises and what an unsatisfiable delegate
    took away.
    """

    def _builders(self):
        return {
            GenericBatteryAdapter: lambda h: GenericBatteryAdapter(h, {}),
            GoodWeBatteryAdapter: lambda h: GoodWeBatteryAdapter(h, {}),
            HuaweiBatteryAdapter: self._huawei,
            DeyeBatteryAdapter: self._deye,
        }

    @staticmethod
    def _huawei(hass):
        with patch(
            "custom_components.solar_energy_management.coordinator"
            ".battery_adapters.huawei.HuaweiBatteryAdapter"
            "._autodetect_battery_device",
            return_value=None,
        ):
            adapter = HuaweiBatteryAdapter(hass, {})
        adapter._startup_orphan_checked = True   # steady state
        return adapter

    @staticmethod
    def _deye(hass):
        adapter = DeyeBatteryAdapter(hass, {})
        adapter._load_snapshot = AsyncMock(return_value=None)
        adapter._snapshot_load_failed = False
        adapter._unsafe_latched = False
        return adapter

    def test_every_brand_has_a_builder(self) -> None:
        """A new brand adapter must be wired in here, or this test says so —
        a silent gap in the oracle is how the class comes back."""
        discovered = {
            obj for _, obj in inspect.getmembers(pkg, inspect.isclass)
            if issubclass(obj, BatteryControlAdapter)
            and obj is not BatteryControlAdapter
        }
        missing = discovered - set(self._builders())
        assert not missing, (
            f"battery adapters with no #1005 oracle builder: "
            f"{sorted(c.__name__ for c in missing)}"
        )

    @pytest.mark.asyncio
    async def test_the_repeat_is_silent_on_every_brand(self) -> None:
        for cls, build in self._builders().items():
            hass = _strict_hass()
            adapter = build(hass)

            await adapter.command_stop_force_charge()
            after_first = hass.services.async_call.await_count

            for _ in range(50):
                await adapter.command_stop_force_charge()

            assert hass.services.async_call.await_count == after_first, (
                f"{cls.__name__} keeps writing after the first stop"
            )
            assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE, (
                f"{cls.__name__} never recorded the stop, so #757's guard "
                f"can never engage"
            )
            assert adapter.last_error is None, (
                f"{cls.__name__} left an error standing: {adapter.last_error}"
            )
