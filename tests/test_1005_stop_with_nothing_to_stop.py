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


def _strict_hass(states: dict | None = None, gate: tuple | None = None,
                 setpoint_raises: bool = False) -> MagicMock:
    """A hass whose service calls refuse what the real ones refuse.

    Three refusals, each one a thing the fix depends on:

    * ``{"entity_id": ""}`` never reaches an integration — the service schema
      rejects it first, ``expected 'all' or 'none' at 'entity_id'``, the exact
      message from the reporter's diagnostics. A fake that accepts it hides
      every bug of this shape, which is why the #757 tests could not see this
      one: they mock the delegate with a fake that always succeeds.
    * ``gate=(setpoint, select, active)`` makes the SETPOINT refuse a write
      while the strategy select reads anything but ``active`` — what #978
      measured on this hardware, and the source of the reporter's 165
      ``device_refusals``. Without it the strike assertions below are
      vacuous (found in review).
    * ``setpoint_raises`` refuses the setpoint unconditionally — a plain
      dropped write.

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
        if service == "set_value" and setpoint_raises:
            raise RuntimeError("the device refused the setpoint")
        if service == "set_value" and gate and ent == gate[0]:
            seen = getattr(table.get(gate[1]), "state", None)
            if seen != gate[2]:
                raise RuntimeError(
                    f"the device refuses a setpoint while its strategy "
                    f"reads {seen}")
        if service == "select_option" and ent:
            table[ent] = _state(data["option"])
        if service == "set_value" and ent in table:
            table[ent] = _setpoint_state(data["value"])
        return None

    hass.services.async_call = AsyncMock(side_effect=_call)
    hass.sem_states = table
    return hass


def _writes_to(hass, entity: str) -> list:
    """Every service call that targeted ``entity``."""
    return [
        c for c in hass.services.async_call.await_args_list
        if (c.args[2] if len(c.args) > 2 else {}).get("entity_id") == entity
    ]


def _subclasses_in_package(base) -> list:
    """Every concrete subclass of ``base`` defined ANYWHERE in the
    ``battery_adapters`` package.

    Walks the package's modules rather than reading what ``__init__.py``
    re-exports: an oracle that can only see today's exports is a
    hand-maintained list wearing discovery's clothes (found in review), and a
    brand added in a new module would slip past it in silence.
    """
    import importlib
    import pkgutil

    for info in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{pkg.__name__}.{info.name}")
    found, seen = [], set()
    stack = list(base.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
        if cls.__module__.startswith(pkg.__name__) and not inspect.isabstract(cls):
            found.append(cls)
    return found


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

    def _sessy(self, strategy: str = "nom", gated: bool = False,
               setpoint_raises: bool = False, **extra):
        """``gated`` = the device refuses a setpoint unless the strategy reads
        the active value, which is what #978 measured on this hardware."""
        hass = _strict_hass(
            {SETPOINT: _setpoint_state(0.0), STRATEGY: _state(strategy)},
            gate=(SETPOINT, STRATEGY, "api") if gated else None,
            setpoint_raises=setpoint_raises,
        )
        config = {
            "battery_max_charge_power": 2200,
            "battery_max_discharge_power": 2200,
            "battery_force_discharge_control_entity": SETPOINT,
            "battery_strategy_control_entity": STRATEGY,
            "battery_setpoint_bidirectional": True,
        }
        config.update(extra)
        return hass, GenericBatteryAdapter(hass, config)

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
        """The 165 refusals, with the refusal modelled. The battery reads
        ``nom``: it is not following the setpoint, and #978 measured that it
        REFUSES a write in that mode. Each refusal is a strike, and three
        withdraw battery-to-grid (#840) — for a fault that is not the
        device's."""
        hass, adapter = self._sessy(strategy="nom", gated=True)

        for _ in range(50):
            await adapter.command_stop_force_charge()

        assert _writes_to(hass, SETPOINT) == []
        assert adapter._force_discharge_failures == 0
        assert adapter.supports_forced_discharge is True
        assert adapter.last_error is None

    @pytest.mark.asyncio
    async def test_an_unreadable_strategy_still_gets_the_zero(self) -> None:
        """Fail-safe (#925): "cannot read the select" is not "the setpoint is
        inert". When SEM cannot tell, it writes the zero — a zero can only
        ever stop the battery."""
        hass, adapter = self._sessy(strategy="unavailable")

        await adapter.command_stop_force_charge()

        assert _writes_to(hass, SETPOINT)

    @pytest.mark.asyncio
    async def test_a_mode_sem_cannot_place_still_gets_the_zero(self) -> None:
        """Found in review. "Not the active value" is not "inert": a Sessy in
        ``roi``, or an install whose ``battery_strategy_active_value`` is
        misconfigured while the battery really is in its API mode, would have
        been read as proof the register was dead. Here the battery IS
        exporting 1700 W and the select reads a mode SEM does not set — the
        zero must go out."""
        hass, adapter = self._sessy(strategy="roi")
        hass.sem_states[SETPOINT] = _setpoint_state(1700.0)

        await adapter.command_normal()

        writes = _writes_to(hass, SETPOINT)
        assert writes, "SEM reported NORMAL while the battery kept selling"
        assert writes[-1].args[2]["value"] == 0.0

    @pytest.mark.asyncio
    async def test_a_dropped_zero_is_not_remembered_as_the_register(self) -> None:
        """Found in review. A skipped zero must FORGET the register, or the
        ±100 W de-dup trusts the old value: one dropped write on the hand-back
        cycle and the next force op at the same power is de-dup'd away — no
        write, no error, no strike, and SEM reporting a sale that never
        happened."""
        hass, adapter = self._sessy(strategy="api")

        await adapter.command_force_discharge(1700.0, 20.0)
        assert adapter._last_force_discharge_w == 1700.0

        # The hand-back cycle's zero is dropped, and the select still moves.
        hass.services.async_call = AsyncMock(
            side_effect=RuntimeError("modbus write dropped"))
        await adapter.command_normal()
        hass.sem_states[STRATEGY] = _state("nom")

        # Cycles pass in self-consumption; nothing is written.
        hass.services.async_call = AsyncMock(side_effect=lambda *a, **k: None)
        for _ in range(20):
            await adapter.command_normal()
        assert adapter._last_force_discharge_w is None

        # The next window: the same 1700 W must reach the register.
        hass2, adapter2 = self._sessy(strategy="api")
        adapter2._last_force_discharge_w = adapter._last_force_discharge_w
        await adapter2.command_force_discharge(1700.0, 20.0)
        assert _writes_to(hass2, SETPOINT), "the de-dup swallowed the sale"

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
        found = _subclasses_in_package(fc.BatteryChargeAdapter)
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
        discovered = set(_subclasses_in_package(BatteryControlAdapter))
        assert len(discovered) >= 4, (
            f"the walker sees only {sorted(c.__name__ for c in discovered)} — "
            f"an oracle that discovers nothing passes everything"
        )
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
