"""#900 — the Huawei discharge limit was rewritten every cycle, and the
options wizard pins a Huawei install to the generic adapter.

koen71 (HA community, post #31): ``battery_maximum_discharging_power`` is
"always updating". Two mechanisms, both real, both on HA-PROD as well:

1. Under ``LIMIT_DISCHARGE`` the value written is the LIVE house load,
   re-decided every 10 s against a 100 W hysteresis. A fridge is a 150 W
   step, so the register followed the noise all day.
2. The options wizard's platform select offered only generic / deye and
   DEFAULTED to generic. One walk through that page and a Huawei install
   lost its Huawei adapter — PROD's own options carry
   ``battery_charge_platform = 'generic'`` — and the generic adapter's
   write path had no equal-value skip at all: ``command_normal`` wrote the
   max EVERY cycle.

The fixes, each in one place:

* ``quantise_discharge_limit_w`` — the limit follows the load's TREND. It
  rises the moment the house exceeds it (coverage first) and falls only
  when the load has dropped a full step below it (leak tolerance).
* ``async_write_power_setpoint`` skips a write whose value the entity
  already holds — for EVERY adapter, not one.
* The wizard offers auto / huawei / goodwe / deye / generic and defaults to
  the stored value, ``auto`` when there is none.
* An explicit ``generic`` on an install where a brand integration is loaded
  is named by a Repair — the wizard put it there, the user did not.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    DISCHARGE_LIMIT_LOWER_DWELL_CYCLES,
    DISCHARGE_LIMIT_STEP_W,
    quantise_discharge_limit_w,
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.power_control import (
    async_write_power_setpoint,
)
from custom_components.solar_energy_management.coordinator.battery_adapters import (
    pinned_generic_brand,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)


# ─── 1. the quantiser ──────────────────────────────────────────────────────

class TestQuantiser:
    def test_no_previous_value_rounds_up_to_the_step(self):
        assert quantise_discharge_limit_w(999.0, -1.0) == 1000.0
        assert quantise_discharge_limit_w(1001.0, -1.0) == 1250.0
        assert quantise_discharge_limit_w(0.0, -1.0) == 0.0

    def test_a_wobble_under_the_limit_holds(self):
        """The fridge: 1100 ↔ 1249 under a 1250 W limit — nothing to write."""
        assert quantise_discharge_limit_w(1100.0, 1250.0) == 1250.0
        assert quantise_discharge_limit_w(1249.0, 1250.0) == 1250.0

    def test_the_house_exceeding_the_limit_raises_it_at_once(self):
        """Coverage first: a limit below the house load imports from grid."""
        assert quantise_discharge_limit_w(1251.0, 1250.0) == 1500.0

    def test_a_real_drop_lowers_it(self):
        assert quantise_discharge_limit_w(900.0, 1250.0) == 1000.0
        assert quantise_discharge_limit_w(0.0, 1250.0) == 0.0

    def test_a_small_drop_is_leak_tolerance_not_a_write(self):
        """1250 → 1050 is a 200 W drop: the pack may cover up to 200 W of
        something else for a while; that is cheaper than a modbus write."""
        assert quantise_discharge_limit_w(1050.0, 1250.0) == 1250.0

    def test_step_is_coarser_than_the_old_hysteresis(self):
        assert DISCHARGE_LIMIT_STEP_W >= 250


class _LimitAdapter:
    """Records what the actuator commands; the hysteresis under test is the
    actuator's, so this stub applies every command verbatim."""
    def __init__(self, last=-1.0):
        self.last_intent = BatteryIntent.LIMIT_DISCHARGE if last >= 0 else None
        self.last_discharge_limit_w = last
        self.writes = []

    async def command_limit_discharge(self, watts):
        if watts != self.last_discharge_limit_w:
            self.writes.append(watts)
        self.last_discharge_limit_w = watts
        self.last_intent = BatteryIntent.LIMIT_DISCHARGE


async def _cycle(adapter, raw):
    await actuate_battery(BatteryDecision(
        battery_id="b1", intent=BatteryIntent.LIMIT_DISCHARGE,
        discharge_limit_w=raw, reason="house",
    ), adapter)


class TestRaiseFastLowerSlow:
    @pytest.mark.asyncio
    async def test_the_fridge_day(self):
        """A house alternating 1100/1300 W for 500 cycles under a 1250 W
        limit produces ONE write (the first 1300), then silence."""
        a = _LimitAdapter(last=1250.0)
        for i in range(500):
            await _cycle(a, 1300.0 if i % 2 else 1100.0)
        assert a.writes == [1500.0], a.writes

    @pytest.mark.asyncio
    async def test_a_sustained_drop_is_followed_within_the_dwell(self):
        a = _LimitAdapter(last=1500.0)
        for _ in range(DISCHARGE_LIMIT_LOWER_DWELL_CYCLES):
            await _cycle(a, 900.0)
        assert a.writes == [1000.0], a.writes

    @pytest.mark.asyncio
    async def test_a_raise_never_waits(self):
        a = _LimitAdapter(last=1000.0)
        await _cycle(a, 1600.0)
        assert a.writes == [1750.0], a.writes

    @pytest.mark.asyncio
    async def test_a_drop_that_does_not_persist_is_not_followed(self):
        a = _LimitAdapter(last=1500.0)
        for _ in range(DISCHARGE_LIMIT_LOWER_DWELL_CYCLES - 1):
            await _cycle(a, 900.0)
        await _cycle(a, 1400.0)        # back up before the dwell ran out
        for _ in range(DISCHARGE_LIMIT_LOWER_DWELL_CYCLES - 1):
            await _cycle(a, 900.0)
        assert a.writes == [], a.writes


class TestActuateUsesTheQuantiser:
    @pytest.mark.asyncio
    async def test_limit_discharge_is_quantised_against_the_adapters_last_value(self):
        adapter = MagicMock()
        adapter.last_intent = BatteryIntent.LIMIT_DISCHARGE
        adapter.last_discharge_limit_w = 1250.0
        adapter.command_limit_discharge = AsyncMock()
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.LIMIT_DISCHARGE,
            discharge_limit_w=1100.0, reason="fridge",
        ), adapter)
        adapter.command_limit_discharge.assert_awaited_once_with(1250.0)

    @pytest.mark.asyncio
    async def test_a_fresh_adapter_gets_the_rounded_value(self):
        adapter = MagicMock()
        adapter.last_intent = None
        adapter.last_discharge_limit_w = -1.0
        adapter.command_limit_discharge = AsyncMock()
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.LIMIT_DISCHARGE,
            discharge_limit_w=1100.0, reason="first",
        ), adapter)
        adapter.command_limit_discharge.assert_awaited_once_with(1250.0)


# ─── 2. one equal-value skip for every writer ──────────────────────────────

def _state(value, unit="W", lo=0.0, hi=10000.0):
    st = Mock()
    st.state = str(value)
    st.attributes = {"min": lo, "max": hi, "unit_of_measurement": unit}
    return st


def _hass(state):
    h = MagicMock()
    h.states.get = MagicMock(return_value=state)
    h.services.async_call = AsyncMock()
    return h


class TestWriterSkipsAnEqualValue:
    @pytest.mark.asyncio
    async def test_same_value_is_not_written(self):
        hass = _hass(_state("5000"))
        ok = await async_write_power_setpoint(hass, "number.limit", 5000.0, context="t")
        assert ok is True
        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_same_value_in_native_kw_is_not_written(self):
        hass = _hass(_state("5.0", unit="kW", lo=0.0, hi=10.0))
        ok = await async_write_power_setpoint(hass, "number.limit", 5000.0, context="t")
        assert ok is True
        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_different_value_is_written(self):
        hass = _hass(_state("5000"))
        ok = await async_write_power_setpoint(hass, "number.limit", 1250.0, context="t")
        assert ok is True
        hass.services.async_call.assert_awaited_once()
        assert hass.services.async_call.await_args.args[2]["value"] == pytest.approx(1250.0)

    @pytest.mark.asyncio
    async def test_prod_case_generic_command_normal_is_idempotent(self):
        """PROD: a Huawei pinned to the generic adapter wrote the max every
        cycle through command_normal. With the skip in the writer the second
        (and 8 000th) call touches nothing."""
        hass = _hass(_state("5000"))
        gen = GenericBatteryAdapter(hass, {
            "battery_discharge_control_entity": "number.limit",
            "battery_max_discharge_power": 5000,
        })
        await gen.command_normal()
        await gen.command_normal()
        assert hass.services.async_call.await_count == 0


# ─── 3. the wizard ─────────────────────────────────────────────────────────

async def _run_step(flow, step_name, *args):
    entry = flow.hass.data.get("_entry")
    step = getattr(flow, step_name)
    with patch.object(
        type(flow), "config_entry",
        new_callable=lambda: property(lambda self: entry if entry is not None else MagicMock()),
    ):
        return await step(*args)


def _platform_field(schema):
    for key, val in schema.schema.items():
        if getattr(key, "schema", None) == "battery_charge_platform":
            return key, val
    raise AssertionError("battery_charge_platform not on the form")


class TestWizardPlatformSelect:
    @pytest.mark.asyncio
    async def test_offers_every_platform_and_defaults_to_auto(self, mock_hass, config_entry):
        from custom_components.solar_energy_management.config_flow import OptionsFlowHandler
        config_entry.options = {}
        config_entry.data = {}
        flow = OptionsFlowHandler(config_entry)
        flow.hass = mock_hass
        flow.hass.data = {"_entry": config_entry}
        result = await _run_step(flow, "async_step_battery_scheduler")
        key, sel = _platform_field(result["data_schema"])
        values = [o["value"] for o in sel.config["options"]]
        assert values[0] == "auto", values
        assert set(values) >= {"auto", "huawei", "goodwe", "deye", "generic"}, values
        assert key.default() == "auto"

    @pytest.mark.asyncio
    async def test_defaults_to_the_stored_choice(self, mock_hass, config_entry):
        from custom_components.solar_energy_management.config_flow import OptionsFlowHandler
        config_entry.options = {"battery_charge_platform": "huawei"}
        config_entry.data = {}
        flow = OptionsFlowHandler(config_entry)
        flow.hass = mock_hass
        flow.hass.data = {"_entry": config_entry}
        result = await _run_step(flow, "async_step_battery_scheduler")
        key, _ = _platform_field(result["data_schema"])
        assert key.default() == "huawei"


# ─── 4. the pinned-generic Repair ──────────────────────────────────────────

def _hass_with_loaded(domain):
    h = MagicMock()
    h.data = {domain: object()}
    return h


class TestPinnedGeneric:
    def test_generic_on_a_huawei_install_is_named(self):
        assert pinned_generic_brand(_hass_with_loaded("huawei_solar"),
                                    {"battery_charge_platform": "generic"}) == "huawei"

    def test_generic_on_a_goodwe_install_is_named(self):
        assert pinned_generic_brand(_hass_with_loaded("goodwe"),
                                    {"battery_charge_platform": "generic"}) == "goodwe"

    def test_auto_is_never_pinned(self):
        assert pinned_generic_brand(_hass_with_loaded("huawei_solar"), {}) is None
        assert pinned_generic_brand(_hass_with_loaded("huawei_solar"),
                                    {"battery_charge_platform": "auto"}) is None

    def test_generic_with_its_own_control_surface_is_a_real_choice(self):
        """A Sessy beside a Huawei fleet (#531): generic IS right."""
        assert pinned_generic_brand(_hass_with_loaded("huawei_solar"), {
            "battery_charge_platform": "generic",
            "battery_strategy_control_entity": "select.sessy_strategy",
        }) is None

    def test_generic_with_no_brand_loaded_is_a_real_choice(self):
        h = MagicMock(); h.data = {}
        h.config_entries.async_entries.return_value = []
        assert pinned_generic_brand(h, {"battery_charge_platform": "generic"}) is None

    def test_repair_strings_exist(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        for f in ("strings.json", "translations/en.json"):
            issues = json.loads((root / f).read_text())["issues"]
            assert "battery_platform_pinned_generic" in issues, f

    def test_repair_helper_exists(self):
        from custom_components.solar_energy_management.coordinator import repair_issues
        assert callable(getattr(repair_issues, "raise_battery_platform_pinned_generic", None))
        assert callable(getattr(repair_issues, "clear_battery_platform_pinned_generic", None))

    def test_the_coordinator_asks_at_adapter_creation(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator
        src = inspect.getsource(coordinator)
        assert "pinned_generic_brand(" in src
