"""The load Mode table's promises, each one a test (#1112).

docs/LOAD_PRIORITY.md says what each Mode and each "Finish overnight from"
choice does; the page was written from the code. Each test here quotes one
sentence of that page and drives the REAL path: a real ``SwitchDevice`` on a fake switch
entity, the real ``SurplusController.update`` walk, and the pool built the
way the coordinator builds it (``solar_bounded_surplus`` with the sustained
import, the #938 reclaim, ``build_battery_tier_context``). The house around
it is a small physics model: a self-consumption battery covers the house's
deficit first, the grid takes the rest.

Peak-only shedding lives in the load manager, so those promises drive the
real ``LoadManagementCoordinator`` shed pass instead.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.const import LoadManagementState
from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    reclaimable_battery_w,
    sustained_import,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
    build_battery_tier_context,
    import_absorbed_by_loads_w,
    solar_bounded_reclaim,
    solar_bounded_surplus,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    SwitchDevice,
)
from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)

DOC = "docs/LOAD_PRIORITY.md"
H = 3600.0
BOILER_W = 3000.0
SWITCH = "switch.boiler"

#: The coordinator's battery settings for the tiers (buffer 70 %, reserve 30 %).
BATTERY_CFG = {
    "battery_buffer_soc": 70,
    "battery_priority_soc": 30,
    "battery_assist_min_surplus": 1200,
    "battery_assist_max_power": 4500,
}
BATTERY_MAX_W = 5000.0
#: The inverter's own cut-off; the pack does not discharge below it.
INVERTER_EMPTY_SOC = 5.0


class _Hass:
    """A switch entity that follows the services SEM calls."""

    def __init__(self):
        self.on: dict[str, bool] = {}
        self.calls: list[tuple[str, str]] = []
        self.states = SimpleNamespace(get=self._get)
        self.services = SimpleNamespace(async_call=self._call)

    def _get(self, entity_id):
        if entity_id not in self.on:
            return None
        return SimpleNamespace(
            state="on" if self.on[entity_id] else "off", attributes={})

    async def _call(self, domain, service, data=None, **_kw):
        eid = (data or {}).get("entity_id")
        self.calls.append((service, eid))
        if service == "turn_on":
            self.on[eid] = True
        elif service == "turn_off":
            self.on[eid] = False

    def turned_on(self, eid=SWITCH) -> bool:
        return ("turn_on", eid) in self.calls

    def turned_off(self, eid=SWITCH) -> bool:
        return ("turn_off", eid) in self.calls


def _boiler(hass, *, mode, running=False, deficit=False,
            battery_assist=False, overnight_battery=False, overnight_grid=False):
    """A 3 kW boiler switch with the Mode and picker set as the card sets them.

    ``deficit`` = a 4 h daily minimum with nothing run yet today.
    """
    d = SwitchDevice(
        hass, device_id="boiler", name="Boiler", rated_power=BOILER_W,
        entity_id=SWITCH, min_on_time=0, min_off_time=0,
        daily_min_runtime_sec=int(4 * H) if deficit else 0,
        battery_assist_enabled=battery_assist,
        battery_eligible_overnight=overnight_battery,
    )
    d.control_mode = mode
    d.top_up_policy = "cheap_hours" if overnight_grid else "solar_only"
    hass.on[SWITCH] = False
    if running:
        hass.on[SWITCH] = True
        d.adopt_if_running()
    return d


class _House:
    """One house: sun, a base load, an optional self-consumption battery,
    the real controller, and the coordinator's pool arithmetic."""

    def __init__(self, hass, device, *, battery=True, soc=50.0,
                 max_charge_w=BATTERY_MAX_W):
        self.hass = hass
        self.device = device
        self.sc = SurplusController(MagicMock())
        self.sc.register_device(device)
        self.battery = battery
        self.soc = soc
        self.max_charge_w = max_charge_w
        self.t = 0.0
        self._import_window: dict = {}
        self.last = {}

    def _flows(self, solar_w, house_w):
        loads_w = sum(
            d.get_current_consumption() for d in self.sc._devices.values()
            if d.is_active)
        net = solar_w - house_w - loads_w
        charge = discharge = 0.0
        if self.battery and net > 0 and self.soc < 100.0:
            charge = min(net, self.max_charge_w)
        elif self.battery and net < 0 and self.soc > INVERTER_EMPTY_SOC:
            discharge = min(-net, BATTERY_MAX_W)
        grid = net - charge + discharge
        return max(0.0, grid), max(0.0, -grid), charge, discharge

    async def cycle(self, *, solar_w, house_w=500.0, is_night=False,
                    price="normal", daylight_s=None, peak_state=None, n=1):
        for _ in range(n):
            self.t += 10.0
            export, imp, charge, discharge = self._flows(solar_w, house_w)
            held = sustained_import(
                self._import_window, self.t, grid_import_w=imp,
                grid_import_known=True, car_active=False)
            draw = self.sc.active_surplus_draw_w()
            pool = solar_bounded_surplus(
                grid_export_w=export, active_draw_w=draw, solar_w=solar_w,
                grid_import_w=held)
            absorbed = import_absorbed_by_loads_w(
                grid_export_w=export, active_draw_w=draw, grid_import_w=held)
            reclaim = solar_bounded_reclaim(
                reclaimable_battery_w(
                    battery_charge_power=charge,
                    soc=self.soc if self.battery else 0.0,
                    priority_soc=BATTERY_CFG["battery_priority_soc"],
                    battery_commanded=False, grid_import_w=imp,
                    absorbed_w=absorbed),
                surplus_w=pool, solar_w=solar_w)
            soc = self.soc if self.battery else None
            btc = build_battery_tier_context(BATTERY_CFG, soc, pool)
            await self.sc.update(
                pool, price_level=price, peak_state=peak_state,
                reclaim_w=reclaim,
                battery_soc=btc.soc, battery_buffer_soc=btc.effective_floor_soc,
                battery_reserve_soc=btc.reserve_soc,
                battery_assist_budget_w=btc.assist_budget_w,
                is_night=is_night, grid_import_w=imp,
                daylight_remaining_s=daylight_s)
            self.last = {"export": export, "import": imp,
                         "charge": charge, "discharge": discharge}


# ── Mode — how SEM drives the load ─────────────────────────────────────────


@pytest.mark.asyncio
class TestModeOff:
    async def test_off_is_never_turned_on(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Off** | Monitor only. SEM never turns it on or off, and the peak guard
        does not shed it."

        5.5 kW of spare sun and a full pack: SEM still does not switch it on."""
        hass = _Hass()
        house = _House(hass, _boiler(hass, mode=DeviceControlMode.OFF), soc=100.0)
        await house.cycle(solar_w=6000.0, n=12)
        assert not hass.turned_on()

    async def test_off_is_never_turned_off(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Off** | Monitor only. SEM never turns it on or off, and the peak guard
        does not shed it."

        The user switched it on; it is night, the house imports, the pack is
        empty and the peak is in EMERGENCY. SEM still does not switch it off."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.OFF, running=True)
        house = _House(hass, dev, soc=INVERTER_EMPTY_SOC)
        await house.cycle(solar_w=0.0, house_w=2000.0, is_night=True,
                          peak_state=LoadManagementState.EMERGENCY, n=12)
        assert house.last["import"] > 0
        assert not hass.turned_off()
        assert hass.on[SWITCH] is True


@pytest.mark.asyncio
class TestModePeakOnly:
    async def test_peak_only_is_never_turned_on(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Peak only** | Your automations run it. SEM never starts it; it
        only turns it off while the grid peak is at risk […]"

        Spare sun does not start it — your automations run it."""
        hass = _Hass()
        house = _House(hass, _boiler(hass, mode=DeviceControlMode.PEAK_ONLY),
                       soc=100.0)
        await house.cycle(solar_w=6000.0, n=12)
        assert not hass.turned_on()

    async def test_peak_only_is_not_stopped_for_lack_of_sun(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Peak only** | Your automations run it. SEM never starts it; it
        only turns it off while the grid peak is at risk […]"

        Your automation started it at night on grid. No peak risk → SEM
        leaves it on."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.PEAK_ONLY, running=True)
        house = _House(hass, dev, battery=False)
        await house.cycle(solar_w=0.0, is_night=True, n=12)
        assert house.last["import"] >= BOILER_W
        assert not hass.turned_off()


# The load manager, set up as tests/test_896_shedder_bounded_by_physics.py
# sets it up: 5 kW target, 0.3 kW hysteresis, 6 kW emergency level.
_LM = "custom_components.solar_energy_management.features.load_management"


@pytest.fixture
def shedder(mock_hass):
    entry = MagicMock()
    entry.options = {
        "load_management_enabled": True,
        "target_peak_limit": 5.0,
        "warning_peak_level": 4.5,
        "emergency_peak_level": 6.0,
        "peak_hysteresis": 0.3,
    }
    entry.entry_id = "test_entry"
    with patch(f"{_LM}.LoadDeviceDiscovery") as discovery, patch(f"{_LM}.Store"):
        disc = MagicMock()
        disc.turn_off_device = AsyncMock(return_value=True)
        disc.turn_on_device = AsyncMock(return_value=True)
        discovery.return_value = disc
        lm = LoadManagementCoordinator(mock_hass, entry)
        lm._device_discovery = disc
        disc.get_device_current_state = MagicMock(
            return_value={"is_on": True, "current_power": BOILER_W})
        state = MagicMock()
        state.state = "on"
        mock_hass.states.get = MagicMock(return_value=state)
        yield lm


def _shed_row(lm, mode):
    lm._devices["boiler"] = {
        "switch_entity": SWITCH,
        "friendly_name": "Boiler",
        "power_rating": BOILER_W,
        "is_available": True,
        "priority": 9,
        "is_critical": False,
        "is_controllable": True,
        "control_mode": mode,
        "last_turned_on": None,
    }


async def _emergency(lm):
    """8 kW at the meter against a 5 kW target: the boiler's 3 kW is needed."""
    lm._state = LoadManagementState.EMERGENCY
    lm._last_grid_import_w = 8000.0
    await lm._execute_load_management(7.0, 7.0)


@pytest.mark.asyncio
async def test_peak_only_is_shed_to_protect_the_peak(shedder):
    """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
    "**Peak only** | Your automations run it. SEM never starts it; it only
    turns it off while the grid peak is at risk […]"

    The meter is over the peak: the Peak-only load is shed."""
    _shed_row(shedder, "peak_only")
    await _emergency(shedder)
    assert shedder._devices_shed == ["boiler"]


@pytest.mark.asyncio
async def test_off_is_not_shed_for_the_peak(shedder):
    """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
    "**Off** | Monitor only. SEM never turns it on or off, and the peak guard
        does not shed it."

    The same peak, the same load in Off: the shedder leaves it alone."""
    _shed_row(shedder, "off")
    await _emergency(shedder)
    assert shedder._devices_shed == []
    shedder._device_discovery.turn_off_device.assert_not_awaited()


@pytest.mark.asyncio
class TestModeSolarOnly:
    async def test_runs_on_pv_surplus(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Solar only** | Starts on spare sun. Stops when the house buys power
        from the grid for it, or when the sun makes less than the load draws.
        It never starts on the battery."

        5.5 kW spare, pack full: the boiler starts on the sun."""
        hass = _Hass()
        house = _House(hass, _boiler(hass, mode=DeviceControlMode.SURPLUS),
                       soc=100.0)
        await house.cycle(solar_w=6000.0, n=6)
        assert hass.turned_on()
        await house.cycle(solar_w=6000.0, n=6)
        assert house.last["import"] == 0.0
        assert house.last["discharge"] == 0.0

    async def test_stops_when_the_house_imports(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Solar only** | Starts on spare sun. Stops when the house buys power
        from the grid for it […]"

        No battery. A cloud: 5.2 kW sun, house 4.2 kW, the boiler's 3 kW now
        comes 2 kW from the grid. It stops."""
        hass = _Hass()
        house = _House(hass, _boiler(hass, mode=DeviceControlMode.SURPLUS),
                       battery=False)
        await house.cycle(solar_w=6000.0, n=6)
        assert hass.on[SWITCH] is True
        await house.cycle(solar_w=5200.0, house_w=4200.0, n=30)
        assert hass.turned_off()
        assert hass.on[SWITCH] is False

    async def test_never_force_imports_in_a_cheap_night(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Solar only** | Starts on spare sun. Stops when the house buys power
        from the grid for it […]"

        No battery, night, the cheapest hour of the day, 4 h still owed and
        "Finish overnight from" left on Off: it is not started."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True)
        house = _House(hass, dev, battery=False)
        await house.cycle(solar_w=0.0, is_night=True, price="very_cheap",
                          daylight_s=0.0, n=12)
        assert not hass.turned_on()

    async def test_never_touches_a_full_pack_at_night(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Solar only** | Starts on spare sun. Stops when the house buys power
        from the grid for it, or when the sun makes less than the load draws.
        It never starts on the battery."

        Night, pack at 100 %, 4 h still owed: it is not started."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True)
        house = _House(hass, dev, soc=100.0)
        await house.cycle(solar_w=0.0, is_night=True, n=12)
        assert not hass.turned_on()

    async def test_is_not_started_on_battery_assist_by_day(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Solar only** | Starts on spare sun. Stops when the house buys power
        from the grid for it, or when the sun makes less than the load draws.
        It never starts on the battery."

        Day, 1.5 kW spare sun, pack at 95 % with 4.5 kW of assist on offer:
        the 3 kW boiler would need the pack, so it stays off. (The same
        afternoon with a full pack starts a "Solar + battery" boiler.)"""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True)
        house = _House(hass, dev, soc=95.0)
        await house.cycle(solar_w=2000.0, n=12)
        assert not hass.turned_on()

    async def test_stops_at_night_when_the_pack_carries_it(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Solar only** | Starts on spare sun. Stops when the house buys power
        from the grid for it, or when the sun makes less than the load draws.
        It never starts on the battery."

        It ran on the afternoon sun. The sun sets (0 W), the pack at 90 %
        covers the house and the boiler, the grid reads 0 W. It stops."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS)
        house = _House(hass, dev, soc=90.0)
        await house.cycle(solar_w=6000.0, n=30)
        assert hass.on[SWITCH] is True
        await house.cycle(solar_w=0.0, is_night=True, n=12)
        assert hass.on[SWITCH] is False

    async def test_runs_on_while_the_pack_covers_the_fading_sun(self):
        """docs/LOAD_PRIORITY.md — "Solar only in the evening": "A running
        Solar-only load keeps going while the sun still makes at least what
        the load itself draws. If the house then needs more, a home battery
        covers the gap and the grid reads 0 W, so SEM does not stop the load."

        Edge case — open for discussion, see #1112.

        It ran all afternoon with the pack full. Evening: sun 3.2 kW, house
        1.5 kW, boiler 3 kW. The boiler runs on and the pack gives 1.3 kW."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS)
        house = _House(hass, dev, soc=100.0)
        await house.cycle(solar_w=6000.0, n=30)
        assert hass.on[SWITCH] is True
        await house.cycle(solar_w=3200.0, house_w=1500.0, n=30)
        assert hass.on[SWITCH] is True
        assert house.last["import"] == 0.0
        assert house.last["discharge"] == pytest.approx(1300.0)


@pytest.mark.asyncio
class TestModeSolarPlusBattery:
    async def test_the_pack_assists_above_the_buffer_by_day(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Solar + battery** | As Solar only, and by day the home battery may
        help it, down to the Buffer SoC […]"

        Day, 1.5 kW spare sun, pack full (buffer 70 %): the 3 kW boiler
        starts with the pack's help."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      battery_assist=True)
        house = _House(hass, dev, soc=100.0)
        await house.cycle(solar_w=2000.0, n=12)
        assert hass.on[SWITCH] is True
        assert house.last["discharge"] > 0

    async def test_no_help_while_the_pack_charges(self):
        """docs/LOAD_PRIORITY.md — "Solar + battery while the battery
        charges": "While the battery is still charging from spare sun, little
        goes to the grid, so the battery's help usually waits until the
        battery is full."

        Edge case — open for discussion, see #1114.

        Day, sun 2 kW, house 0.5 kW, pack at 95 % taking the 1.5 kW spare:
        the 3 kW boiler stays off."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      battery_assist=True)
        house = _House(hass, dev, soc=95.0)
        await house.cycle(solar_w=2000.0, n=12)
        assert house.last["charge"] == pytest.approx(1500.0)
        assert not hass.turned_on()

    async def test_no_assist_below_the_buffer(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Solar + battery** | As Solar only, and by day the home battery may
        help it, down to the Buffer SoC […]"

        The pack is not charging (its charge limit is 0 W), so the 1.5 kW
        spare sun is exported. At 60 % (buffer 70 %) there is no assist and
        the 3 kW boiler stays off; the same afternoon at 95 % starts it."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      battery_assist=True)
        house = _House(hass, dev, soc=60.0, max_charge_w=0.0)
        await house.cycle(solar_w=2000.0, n=12)
        assert house.last["export"] > 0
        assert not hass.turned_on()

        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      battery_assist=True)
        house = _House(hass, dev, soc=95.0, max_charge_w=0.0)
        await house.cycle(solar_w=2000.0, n=12)
        assert hass.turned_on()

    async def test_no_daytime_assist_at_night(self):
        """docs/LOAD_PRIORITY.md — "Mode — how SEM drives the load":
        "**Solar + battery** | As Solar only, and by day the home battery may
        help it, down to the Buffer SoC […]"

        Night, pack at 95 %, "Finish overnight from" Off: the daytime
        assist does not start it."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      battery_assist=True)
        house = _House(hass, dev, soc=95.0)
        await house.cycle(solar_w=0.0, is_night=True, n=12)
        assert not hass.turned_on()


# ── Finish overnight from — the overnight source (axis 2) ──────────────────


@pytest.mark.asyncio
class TestFinishOvernightFrom:
    async def test_off_waits_for_the_sun(self):
        """docs/LOAD_PRIORITY.md — "Finish overnight from — the overnight
        source (axis 2)": "**Off** | Nothing finishes it. The load waits for
        the sun and may miss its target on a dark day."

        Night, 4 h owed, pack full, cheap hour: nothing starts it. The
        morning sun does."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True)
        house = _House(hass, dev, soc=100.0)
        await house.cycle(solar_w=0.0, is_night=True, price="cheap",
                          daylight_s=0.0, n=12)
        assert not hass.turned_on()
        await house.cycle(solar_w=6000.0, daylight_s=10 * H, n=6)
        assert hass.turned_on()

    async def test_battery_runs_it_overnight(self):
        """docs/LOAD_PRIORITY.md — "Finish overnight from — the overnight
        source (axis 2)": "**Battery** | At night, while runtime is still owed,
        it runs off the **home battery** and stops at `Battery priority SOC`
        (default 30 %). It does not start again below it, and it stops at
        daybreak."

        Night, 4 h owed, pack at 80 % (reserve 30 %): it runs."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      overnight_battery=True)
        house = _House(hass, dev, soc=80.0)
        await house.cycle(solar_w=0.0, is_night=True, n=3)
        assert hass.on[SWITCH] is True
        assert house.last["discharge"] > 0

    async def test_battery_stops_at_the_reserve(self):
        """docs/LOAD_PRIORITY.md — "Finish overnight from — the overnight
        source (axis 2)": "**Battery** | At night, while runtime is still owed,
        it runs off the **home battery** and stops at `Battery priority SOC`
        (default 30 %). It does not start again below it, and it stops at
        daybreak."

        Running off the pack; the pack falls to the 30 % reserve: it stops,
        and it does not start again below it."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      overnight_battery=True)
        house = _House(hass, dev, soc=80.0)
        await house.cycle(solar_w=0.0, is_night=True, n=3)
        assert hass.on[SWITCH] is True
        house.soc = 30.0
        await house.cycle(solar_w=0.0, is_night=True, n=3)
        assert hass.on[SWITCH] is False
        hass.calls.clear()
        house.soc = 25.0
        await house.cycle(solar_w=0.0, is_night=True, n=6)
        assert not hass.turned_on()

    async def test_battery_is_night_only(self):
        """docs/LOAD_PRIORITY.md — "Finish overnight from — the overnight
        source (axis 2)": "**Battery** | At night […] it stops at
        daybreak."

        A run off the pack at night stops at daybreak, though 4 h are still
        owed and the pack is at 80 %."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      overnight_battery=True)
        house = _House(hass, dev, soc=80.0)
        await house.cycle(solar_w=0.0, is_night=True, n=3)
        assert hass.on[SWITCH] is True
        await house.cycle(solar_w=200.0, is_night=False, daylight_s=12 * H, n=6)
        assert hass.on[SWITCH] is False

    async def test_grid_runs_it_in_the_cheap_window(self):
        """docs/LOAD_PRIORITY.md — "Finish overnight from — the overnight
        source (axis 2)": "**Grid** | While runtime is still owed and the day
        left is too short to cover it, it runs off the **grid** in cheap-price
        hours only."

        Night, no battery, 4 h owed, cheap hour: it runs on the grid."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      overnight_grid=True)
        house = _House(hass, dev, battery=False)
        await house.cycle(solar_w=0.0, is_night=True, price="cheap",
                          daylight_s=0.0, n=3)
        assert hass.on[SWITCH] is True

    async def test_grid_waits_outside_the_cheap_window(self):
        """docs/LOAD_PRIORITY.md — "Finish overnight from — the overnight
        source (axis 2)": "**Grid** | While runtime is still owed and the day
        left is too short to cover it, it runs off the **grid** in cheap-price
        hours only."

        The same night in an expensive hour: it waits."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      overnight_grid=True)
        house = _House(hass, dev, battery=False)
        await house.cycle(solar_w=0.0, is_night=True, price="expensive",
                          daylight_s=0.0, n=12)
        assert not hass.turned_on()

    async def test_grid_never_in_a_morning_the_sun_can_cover(self):
        """docs/LOAD_PRIORITY.md — "Finish overnight from — the overnight
        source (axis 2)": "**Grid** (2.1, #953) engages whenever today's
        remaining daylight is shorter than the runtime still owed […] but
        never in a morning the sun still has time to cover."

        08:00, 12 h of daylight ahead, 4 h owed, a cheap hour, no sun yet:
        the meter waits."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      overnight_grid=True)
        house = _House(hass, dev, battery=False)
        await house.cycle(solar_w=100.0, is_night=False, price="cheap",
                          daylight_s=12 * H, n=12)
        assert not hass.turned_on()

    async def test_switching_the_picker_stops_a_grid_run(self):
        """docs/LOAD_PRIORITY.md — "Finish overnight from — the overnight
        source (axis 2)": "Switching the picker also **stops a load that's
        already running** on the source you moved away from."

        A cheap-hour grid run; the picker moves Grid → Off: it stops."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      overnight_grid=True)
        house = _House(hass, dev, battery=False)
        await house.cycle(solar_w=0.0, is_night=True, price="cheap",
                          daylight_s=0.0, n=3)
        assert hass.on[SWITCH] is True
        dev.top_up_policy = "solar_only"
        await house.cycle(solar_w=0.0, is_night=True, price="cheap",
                          daylight_s=0.0, n=3)
        assert hass.on[SWITCH] is False

    async def test_switching_the_picker_stops_a_battery_run(self):
        """docs/LOAD_PRIORITY.md — "Finish overnight from — the overnight
        source (axis 2)": "Switching the picker also **stops a load that's
        already running** on the source you moved away from — you don't have
        to wait for the reserve floor or the cheap window to end."

        A run off the pack at 80 %; the picker moves Battery → Off: it
        stops long before the reserve."""
        hass = _Hass()
        dev = _boiler(hass, mode=DeviceControlMode.SURPLUS, deficit=True,
                      overnight_battery=True)
        house = _House(hass, dev, soc=80.0)
        await house.cycle(solar_w=0.0, is_night=True, n=3)
        assert hass.on[SWITCH] is True
        dev.battery_eligible_overnight = False
        await house.cycle(solar_w=0.0, is_night=True, n=3)
        assert hass.on[SWITCH] is False

