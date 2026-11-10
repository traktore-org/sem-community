"""#1102 — a Solar-only boiler kept running while the house imported.

@lostcontrol (Fronius, no battery, 2.2.0-beta.15): a 3 kW boiler stayed on
for more than 20 minutes after the house started buying from the grid. The
solar stayed at about 5.2 kW, the house rose to 5.5–8.5 kW.

The loads' pool is "the surplus that would exist if the controller's own
loads were off": the grid figure plus the loads' own draw (#508 W7). The
coordinator handed it the CLAMPED half of the grid — ``grid_export_power``,
``max(0, grid)`` — so any import read as 0 W and vanished before the add-back.
With 2 kW imported and the 3 kW boiler on, the pool read 3 kW instead of
1 kW; after the boiler's own debit the walk sat at −50 W, inside the −100 W
LIFO band, for as long as the sun stayed above 3 kW. Nothing stopped it.

The fix gives the pool the import back — an import that lasted two minutes
(a charger's power sensor can trail the meter at a start), less what the
chargers' draw explains (a charger leaves a running load above it its sun,
#885), less a 100 W deadband (a zero-export inverter's own setpoint). The
#938 reclaim takes off only the import this side could not, so the two
addends together are ``draw + export + charge − import``, running or not.

A second count lived in the same walk: a running variable load (a watt
setpoint, a current knob) was offered ``remaining + its own draw``, but the
pool already holds its draw (the add-back). With the import seen, that double
count would ramp the load to its maximum, import, and get it stopped — a
cycle. It is now offered ``remaining`` alone.
"""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    CAR_START_HOLD_S,
    LOADS_IMPORT_SUSTAIN_S,
    car_may_be_charging,
    reclaimable_battery_w,
    sustained_car_draw,
    sustained_import,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    IMPORT_DEADBAND_W,
    SurplusController,
    import_absorbed_by_loads_w,
    reclaim_handed_back,
    solar_bounded_reclaim,
    solar_bounded_surplus,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode
from custom_components.solar_energy_management.devices.power_setpoint import (
    PowerSetpointDevice,
)

_ROOT = Path(__file__).resolve().parent.parent
_COORD = _ROOT / "coordinator" / "coordinator.py"
_SC = _ROOT / "coordinator" / "surplus_controller.py"

SOLAR_W = 5200.0
BOILER_W = 3000.0


# ── 1. the pool keeps the import ─────────────────────────────────────────


@pytest.mark.unit
class TestThePoolKeepsTheImport:
    def test_reporters_numbers(self):
        # 2 kW imported with the 3 kW boiler on → about 1 kW would be left
        # if it were off (less the 100 W deadband). The old pool said 3 kW.
        assert solar_bounded_surplus(
            grid_export_w=0.0, active_draw_w=BOILER_W, solar_w=SOLAR_W,
            grid_import_w=2000.0,
        ) == pytest.approx(BOILER_W - 2000.0 + IMPORT_DEADBAND_W)

    def test_the_old_call_lost_it(self):
        # The pre-fix call shape — no import — is the 3 kW the boiler rode on.
        assert solar_bounded_surplus(
            grid_export_w=0.0, active_draw_w=BOILER_W, solar_w=SOLAR_W,
        ) == pytest.approx(BOILER_W)

    def test_import_larger_than_the_draw_floors_at_zero(self):
        assert solar_bounded_surplus(
            grid_export_w=0.0, active_draw_w=BOILER_W, solar_w=SOLAR_W,
            grid_import_w=3500.0,
        ) == 0.0

    def test_a_zero_export_setpoint_is_not_a_deficit(self):
        # Victron ESS holds +50 W of import by default: the pool must not
        # read that as the loads running on the grid.
        assert solar_bounded_surplus(
            grid_export_w=0.0, active_draw_w=BOILER_W, solar_w=SOLAR_W,
            grid_import_w=50.0,
        ) == pytest.approx(BOILER_W)
        assert IMPORT_DEADBAND_W == 100.0

    def test_the_chargers_own_grid_draw_is_not_the_loads(self):
        # A Min+Solar car at its 6 A floor (4.14 kW) imports 2.1 kW; a
        # running boiler ranked above the charger keeps its sun (#885).
        assert solar_bounded_surplus(
            grid_export_w=0.0, active_draw_w=BOILER_W, solar_w=6000.0,
            grid_import_w=2140.0, ev_draw_w=4140.0,
        ) == pytest.approx(BOILER_W)

    def test_import_past_the_chargers_draw_is_the_houses(self):
        assert solar_bounded_surplus(
            grid_export_w=0.0, active_draw_w=BOILER_W, solar_w=SOLAR_W,
            grid_import_w=3000.0, ev_draw_w=1000.0,
        ) == pytest.approx(BOILER_W - 2000.0 + IMPORT_DEADBAND_W)

    @staticmethod
    def _addends(*, solar, draw, charge, imp, export=0.0):
        surplus = solar_bounded_surplus(
            grid_export_w=export, active_draw_w=draw, solar_w=solar,
            grid_import_w=imp)
        absorbed = import_absorbed_by_loads_w(
            grid_export_w=export, active_draw_w=draw, grid_import_w=imp)
        reclaim = solar_bounded_reclaim(
            reclaimable_battery_w(
                battery_charge_power=charge, soc=60.0, priority_soc=30.0,
                battery_commanded=False, grid_import_w=imp,
                absorbed_w=absorbed),
            surplus_w=surplus, solar_w=solar)
        return surplus, reclaim

    def test_a_load_below_a_grid_charging_battery_pays_the_import(self):
        # An inverter's own daytime grid charge (5 kW): sun 4 kW, house
        # 0.5 kW, boiler 3 kW → 4.5 kW imported. The pack does not yield,
        # so a boiler BELOW the battery (export side only) is on the grid.
        surplus, _ = self._addends(solar=4000.0, draw=BOILER_W,
                                   charge=5000.0, imp=4500.0)
        assert surplus == 0.0

    def test_a_load_above_a_charging_pack_pays_the_import_once(self):
        # A single-phase hybrid on a summed meter: sun 4.3 kW, house 1.5 kW,
        # and the meter shows 300 W of import while the pack charges from
        # the sun. A 1 kW pump above the battery takes its watts from the
        # pack's charge. The pool must read the same with the pump off and
        # on — paying the 300 W twice once running made it cycle.
        imp = 300.0
        off_s, off_r = self._addends(solar=4300.0, draw=0.0, charge=3100.0, imp=imp)
        on_s, on_r = self._addends(solar=4300.0, draw=1000.0, charge=2100.0, imp=imp)
        assert on_s + on_r == pytest.approx(off_s + off_r)
        assert off_s + off_r == pytest.approx(3100.0 - imp)

    def test_meter_never_read_takes_nothing_off(self):
        # None = no readable meter yet this lifetime: the running loads keep
        # what they hold (the export side reads 0 too), nothing new starts.
        assert solar_bounded_surplus(
            grid_export_w=0.0, active_draw_w=BOILER_W, solar_w=SOLAR_W,
            grid_import_w=None,
        ) == pytest.approx(BOILER_W)

    def test_export_and_sun_cap_unchanged(self):
        assert solar_bounded_surplus(
            grid_export_w=500.0, active_draw_w=1000.0, solar_w=5000.0,
            grid_import_w=0.0,
        ) == pytest.approx(1500.0)
        assert solar_bounded_surplus(
            grid_export_w=0.0, active_draw_w=1600.0, solar_w=800.0,
            grid_import_w=0.0,
        ) == pytest.approx(800.0)

    def test_the_two_addends_are_the_whole_balance(self):
        """Over a grid of meter / pack / load states: export surplus plus
        the reclaim is ``draw + export + charge − import``, bounded by 0 and
        the sun (the 100 W deadband excused only where no charge stands
        beside the import). Before the fix the sum lost the import whenever
        no charge stood beside it."""
        exact = overlap = 0
        for solar in (0.0, 800.0, 5200.0):
            for draw in (0.0, 1000.0, 3000.0):
                for charge in (0.0, 1000.0, 3000.0):
                    for grid in (-4000.0, -2000.0, -500.0, -60.0, 0.0, 700.0, 2500.0):
                        export, imp = max(0.0, grid), max(0.0, -grid)
                        s = solar_bounded_surplus(
                            grid_export_w=export, active_draw_w=draw,
                            solar_w=solar, grid_import_w=imp)
                        r = solar_bounded_reclaim(
                            reclaimable_battery_w(
                                battery_charge_power=charge, soc=60.0,
                                priority_soc=30.0, battery_commanded=False,
                                grid_import_w=imp,
                                absorbed_w=import_absorbed_by_loads_w(
                                    grid_export_w=export, active_draw_w=draw,
                                    grid_import_w=imp)),
                            surplus_w=s, solar_w=solar)
                        counted = max(0.0, imp - IMPORT_DEADBAND_W)
                        want = min(solar, max(0.0, draw + export + charge - counted))
                        if charge > 0.0 and imp > 0.0:
                            # the reclaim keeps #938's raw import: the
                            # deadband is not excused on the pack's side
                            raw = min(solar, max(0.0, draw + export + charge - imp))
                            assert s + r == pytest.approx(raw), (
                                solar, draw, charge, grid)
                            overlap += 1
                        else:
                            assert s + r == pytest.approx(want), (
                                solar, draw, charge, grid)
                            exact += 1
        assert exact == 3 * 3 * 1 * 7 + 3 * 3 * 2 * 3
        assert overlap == 3 * 3 * 2 * 4


# ── 2. the reporter's afternoon, closed loop ─────────────────────────────


def _boiler():
    """A 3 kW switch, past its minimum run (the reporter: > 20 min)."""
    d = MagicMock()
    d.device_id = "boiler"
    d.name = "Boiler"
    d.priority = 5
    d.min_power_threshold = BOILER_W
    d.rated_power = BOILER_W
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = True
    d.device_type = MagicMock(value="switch")
    d.activate = AsyncMock(return_value=BOILER_W)
    d.adjust_power = AsyncMock(return_value=BOILER_W)
    d.get_current_consumption = MagicMock(
        side_effect=lambda: BOILER_W if d.is_active else 0.0)
    d.can_activate = MagicMock(return_value=True)
    d.can_deactivate = MagicMock(return_value=True)
    d.record_activated = MagicMock()
    d.record_deactivated = MagicMock()
    d.reset_surplus_timer = MagicMock()
    d.status = MagicMock()
    d.control_mode = DeviceControlMode.SURPLUS
    d._sem_owned = True
    d.is_deadline_approaching = False
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = False
    d._batt_overnight_forced_date = None
    d._daily_runtime_meter_day = None
    d.needs_offpeak_activation = False
    d.remaining_daily_runtime_sec = 0
    d.daily_min_runtime_sec = 0
    d.daily_targets_met = False
    d.daily_max_runtime_reached = False
    d.stop_condition_met = False
    d.top_up_policy = "solar_only"
    d.battery_assist_enabled = False
    d.battery_eligible_overnight = False
    d.stop_entity = ""
    d.stop_at = 0

    async def _off():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_off)
    return d


async def _afternoon(sc, *, house_w, cycles, with_import, solar_w=SOLAR_W):
    """No battery. Each cycle the meter reads what the house, the loads and
    the sun leave; the pool is built the way the coordinator builds it."""
    imports = []
    window = {}
    for i in range(cycles):
        draw = sc.active_surplus_draw_w()
        grid = solar_w - house_w - draw
        export, imp = max(0.0, grid), max(0.0, -grid)
        imports.append(imp)
        # 10 s cycles, no car: the coordinator hands in the mean of two minutes
        held = sustained_import(window, i * 10.0, grid_import_w=imp,
                                grid_import_known=True, car_active=False)
        kw = {"grid_import_w": held} if with_import else {}
        pool = solar_bounded_surplus(
            grid_export_w=export, active_draw_w=draw, solar_w=solar_w, **kw)
        await sc.update(pool, price_level="normal", grid_import_w=imp)
    return imports


@pytest.mark.asyncio
class TestTheBoilerStopsWhenTheHouseImports:
    async def test_the_reporters_afternoon_stops_it(self):
        # House 4.2 kW + boiler 3 kW against 5.2 kW of sun: 2 kW imported.
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        await _afternoon(sc, house_w=4200.0, cycles=30, with_import=True)
        boiler.deactivate.assert_awaited()

    async def test_without_the_import_it_never_stops(self):
        # Non-vacuous: the same afternoon through the pre-fix call shape
        # keeps the boiler on every cycle — the reported symptom.
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        imports = await _afternoon(sc, house_w=4200.0, cycles=30, with_import=False)
        boiler.deactivate.assert_not_awaited()
        assert min(imports) == pytest.approx(2000.0)

    async def test_a_funded_boiler_keeps_running(self):
        # House 2 kW: the sun covers both, 200 W exported — nothing stops.
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        imports = await _afternoon(sc, house_w=2000.0, cycles=12, with_import=True)
        boiler.deactivate.assert_not_awaited()
        assert max(imports) == 0.0

    async def test_once_stopped_it_does_not_restart_into_the_import(self):
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        await _afternoon(sc, house_w=4200.0, cycles=30, with_import=True)
        assert boiler.is_active is False
        await _afternoon(sc, house_w=4200.0, cycles=12, with_import=True)
        boiler.activate.assert_not_awaited()


def _load(device_id, draw, priority, *, paid=False):
    """A running on/off load. ``paid`` = on the cheap-hours grid top-up."""
    d = _boiler()
    d.device_id = device_id
    d.name = device_id
    d.priority = priority
    d.min_power_threshold = draw
    d.rated_power = draw
    d.activate = AsyncMock(return_value=draw)
    d.adjust_power = AsyncMock(return_value=draw)
    d.get_current_consumption = MagicMock(
        side_effect=lambda: draw if d.is_active else 0.0)
    if paid:
        day = date(2026, 10, 12)
        d._daily_runtime_meter_day = day
        d._offpeak_forced = True
        d._offpeak_forced_date = day
        d.top_up_policy = "cheap_hours"
        d.remaining_daily_runtime_sec = 3600
    return d


async def _cycles(sc, *, solar_w, house_w, n, price="cheap"):
    for _ in range(n):
        # What the meter sees: every load that is on, credited or not.
        on_w = sum(d.get_current_consumption()
                   for d in sc._devices.values() if d.is_active)
        draw = sc.active_surplus_draw_w()
        grid = solar_w - house_w - on_w
        export, imp = max(0.0, grid), max(0.0, -grid)
        pool = solar_bounded_surplus(
            grid_export_w=export, active_draw_w=draw, solar_w=solar_w,
            grid_import_w=imp)
        await sc.update(pool, price_level=price, grid_import_w=imp)


@pytest.mark.asyncio
class TestAPaidLoadDoesNotStopASolarOne:
    """The import a load on a PAID source causes (a cheap-hours grid top-up)
    is that load's own. Sun 4 kW, house 0.5 kW: 3.5 kW spare. A 1 kW pump on
    solar and a 3 kW boiler buying its daily minimum from the grid."""

    async def test_a_funded_pump_ahead_of_the_top_up_keeps_running(self):
        sc = SurplusController(MagicMock())
        pump = _load("pump", 1000.0, 2)
        boiler = _load("boiler", 3000.0, 5, paid=True)
        sc.register_device(pump)
        sc.register_device(boiler)
        await _cycles(sc, solar_w=4000.0, house_w=500.0, n=12)
        pump.deactivate.assert_not_awaited()
        boiler.deactivate.assert_not_awaited()

    async def test_a_pump_behind_the_top_up_gets_only_what_is_left(self):
        # The boiler is first in line for the sun: 3.5 kW spare minus its
        # 3 kW leaves 0.5 kW — not enough for the 1 kW pump.
        sc = SurplusController(MagicMock())
        boiler = _load("boiler", 3000.0, 2, paid=True)
        pump = _load("pump", 1000.0, 5)
        sc.register_device(boiler)
        sc.register_device(pump)
        await _cycles(sc, solar_w=4000.0, house_w=500.0, n=12)
        pump.deactivate.assert_awaited()
        boiler.deactivate.assert_not_awaited()

    async def test_at_night_the_solar_load_still_stops(self):
        sc = SurplusController(MagicMock())
        pump = _load("pump", 1000.0, 2)
        boiler = _load("boiler", 3000.0, 5, paid=True)
        sc.register_device(pump)
        sc.register_device(boiler)
        await _cycles(sc, solar_w=0.0, house_w=500.0, n=6)
        pump.deactivate.assert_awaited()
        boiler.deactivate.assert_not_awaited()


@pytest.mark.asyncio
class TestOnlyLoadsTheWalkDebitsAreCredited:
    """The add-back is for loads the walk debits. A load in mode Off is the
    user's — the belief sync sees it running, the walk skips it — and one
    behind the operator's relay is cut by the relay. Crediting either hands
    its draw, and the import it causes, to the Solar-only loads."""

    def _washer(self):
        washer = _load("washer", 2000.0, 3)
        washer.control_mode = DeviceControlMode.OFF
        washer._sem_owned = False   # the user started it
        return washer

    async def test_mode_off_and_relay_locked_loads_are_not_credited(self):
        sc = SurplusController(MagicMock())
        locked = _load("heat_pump", 2500.0, 4)
        locked.locked_by_operator = True
        running = _load("boiler", 3000.0, 1)
        for d in (self._washer(), locked, running):
            sc.register_device(d)
        assert sc.active_surplus_draw_w() == pytest.approx(3000.0)

    async def test_a_users_washer_is_not_spare_sun(self):
        # Sun 3 kW, house 1 kW, the user's 2 kW washer on: nothing spare.
        sc = SurplusController(MagicMock())
        pump = _load("pump", 1500.0, 2)
        pump.is_active = False
        sc.register_device(self._washer())
        sc.register_device(pump)
        await _cycles(sc, solar_w=3000.0, house_w=1000.0, n=12, price="normal")
        pump.activate.assert_not_awaited()
        assert sc._devices["washer"].deactivate.await_count == 0

    async def test_crediting_the_washer_started_the_pump(self):
        # Non-vacuous: the same meter with the washer's 2 kW credited.
        sc = SurplusController(MagicMock())
        pump = _load("pump", 1500.0, 2)
        pump.is_active = False
        sc.register_device(self._washer())
        sc.register_device(pump)
        for _ in range(12):
            pool = solar_bounded_surplus(
                grid_export_w=0.0, active_draw_w=2000.0, solar_w=3000.0,
                grid_import_w=0.0)
            await sc.update(pool, price_level="normal", grid_import_w=0.0)
        pump.activate.assert_awaited()


# ── 3. a variable load is offered its pool once, not twice ───────────────


ENTITY = "number.heater_power"


class _Hass:
    """A number entity whose state follows what SEM writes to it."""

    def __init__(self, value: float):
        self._attrs = {"min": 0.0, "max": 9000.0, "step": 1.0}
        self._state = SimpleNamespace(state=str(value), attributes=self._attrs)
        self.states = SimpleNamespace(get=self._get)
        self.services = SimpleNamespace(async_call=self._call)

    def _get(self, entity_id):
        return self._state if entity_id == ENTITY else None

    async def _call(self, domain, service, data=None, **_kw):
        assert (domain, service) == ("number", "set_value")
        self._state = SimpleNamespace(
            state=str(data["value"]), attributes=self._attrs)

    @property
    def value(self) -> float:
        return float(self._state.state)


@pytest.mark.asyncio
class TestAVariableLoadFollowsTheSun:
    async def test_it_settles_on_the_spare_power_not_its_maximum(self):
        # Sun 5.2 kW, house 2 kW: 3.2 kW spare. The heater runs at 1 kW.
        hass = _Hass(1000.0)
        heater = PowerSetpointDevice(
            hass=hass, device_id="heater", name="Heater",
            rated_power=9000.0, min_power_threshold=500.0, entity_id=ENTITY)
        heater.control_mode = DeviceControlMode.SURPLUS
        heater.adopt_if_running()
        assert heater.is_active
        sc = SurplusController(hass)
        sc.register_device(heater)
        imports = await _afternoon(sc, house_w=2000.0, cycles=30, with_import=True)
        # It follows the spare power less the 50 W export margin — it does
        # not ramp to 9 kW on the grid, and nothing has to stop it.
        assert hass.value == pytest.approx(3150.0, abs=60.0)
        assert heater.is_active
        assert max(imports[-10:]) == 0.0

    async def test_a_peak_only_setpoint_is_left_where_the_user_put_it(self):
        # peak_only is the user's load: SEM sheds it on a peak, nothing
        # more. The walk used to steer it — to its maximum, before this fix.
        hass = _Hass(2000.0)
        heater = PowerSetpointDevice(
            hass=hass, device_id="heater", name="Heater",
            rated_power=9000.0, min_power_threshold=500.0, entity_id=ENTITY)
        assert heater.control_mode == DeviceControlMode.PEAK_ONLY
        heater.adopt_if_running()
        sc = SurplusController(hass)
        sc.register_device(heater)
        await _afternoon(sc, house_w=2000.0, cycles=20, with_import=True)
        assert hass.value == pytest.approx(2000.0)

    async def test_the_walk_offers_a_running_load_the_pool_once(self):
        # Source pin: the active branch hands ``adjust_power`` the remaining
        # pool, which already holds the load's own draw (the add-back).
        tree = ast.parse(_SC.read_text(encoding="utf-8"))
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "adjust_power"
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "device"
        ]
        args = [ast.unparse(c.args[0]) for c in calls if c.args]
        # (#1084) the surplus walk adjusts through ``_adjust_owned(device,
        # watts)`` — the one choke point the decision log reads
        args += [
            ast.unparse(n.args[1]) for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_adjust_owned" and len(n.args) > 1
        ]
        # the pool, plus the Tier-1 battery headroom (0 for a plain load)
        assert "remaining_surplus + self._tier1_headroom_w(device)" in args, args
        assert not any("old_consumption" in a or "get_current_consumption" in a
                       for a in args), args


# ── 4. the guard: the coordinator hands the pool the import ──────────────


def _callee(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return ast.unparse(f)
    return ""


def _kw(node: ast.Call, name: str):
    for k in node.keywords:
        if k.arg == name:
            return k.value
    return None


def _enclosing(tree: ast.AST, target: ast.AST) -> ast.AST:
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= target.lineno <= (node.end_lineno or node.lineno):
                if best is None or node.lineno > best.lineno:
                    best = node
    assert best is not None
    return best


def _bindings(name: str, scope: ast.AST):
    out = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                out.append(node.value)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
            t = node.target
            if isinstance(t, ast.Name) and t.id == name:
                out.append(node if isinstance(node, ast.AugAssign) else node.value)
    return out


@pytest.mark.unit
class TestCoordinatorWiringGuard:
    """Every ``solar_bounded_surplus`` call in the coordinator carries the
    held meter import (a refactor that drops it puts the reporter's boiler
    back on the grid) and the chargers' draw (one that drops it stops a
    load ranked above a charger whenever the car imports)."""

    def setup_method(self):
        self.tree = ast.parse(_COORD.read_text(encoding="utf-8"))

    def _calls(self, name):
        return [n for n in ast.walk(self.tree)
                if isinstance(n, ast.Call) and _callee(n) == name]

    def _sources(self, value, scope):
        if isinstance(value, ast.Call):
            return [value]
        assert isinstance(value, ast.Name), ast.unparse(value)
        srcs = _bindings(value.id, scope)
        assert srcs, f"{value.id} is never assigned"
        return srcs

    def _sustained(self, call, kw):
        """``kw`` of ``call`` is a name bound only to ``sustained_import(…)``
        of the live import, driven by the reader's dark flag."""
        scope = _enclosing(self.tree, call)
        val = _kw(call, kw)
        assert val is not None, f"{_callee(call)}() called without {kw}"
        for s in self._sources(val, scope):
            assert isinstance(s, ast.Call) and _callee(s) == "sustained_import", (
                f"{kw} must come from sustained_import(), got {ast.unparse(s)}")
            live = _kw(s, "grid_import_w")
            known = _kw(s, "grid_import_known")
            assert live is not None and "grid_import_power" in ast.unparse(live)
            assert known is not None
            known_src = " ".join(ast.unparse(b) for b in (
                self._sources(known, scope) if isinstance(known, ast.Name) else [known]))
            assert "grid_power_unavailable" in known_src
            car = self._car_signal(_kw(s, "car_active"), scope)
            plugged = _kw(car, "plugged")
            offer = _kw(car, "commanded_amps")
            assert plugged is not None and "ev_connected" in ast.unparse(plugged), (
                "the window opens on a plugged car — it comes before the power")
            assert offer is not None and (
                "_last_commanded_amps_fleet" in ast.unparse(offer)), (
                "…and on SEM's own offer this cycle")
            assert "ev_charging" not in ast.unparse(car), (
                "ev_charging is held False below 500 W (#739): it lags with "
                "the power sensor and cannot open the window ahead of it")
        return ast.unparse(val)

    def _car_signal(self, car, scope):
        """``car_active`` is ``car_may_be_charging(…)`` — inline, or a
        name bound only to it."""
        assert car is not None, "sustained_import() must be told when a car may charge"
        if isinstance(car, ast.Name):
            srcs = self._sources(car, scope)
            assert len(srcs) == 1, f"{car.id} is bound more than once"
            car = srcs[0]
        assert isinstance(car, ast.Call) and _callee(car) == "car_may_be_charging", (
            "sustained_import() must be told when a car may charge, "
            "by car_may_be_charging()")
        return car

    def test_the_chargers_draw_is_paired_with_the_import(self):
        # The lowest import of two minutes goes with the car's highest draw
        # of the same two minutes, judged on the same car signal.
        for c in self._calls("solar_bounded_surplus"):
            scope = _enclosing(self.tree, c)
            ev, imp = _kw(c, "ev_draw_w"), _kw(c, "grid_import_w")
            assert isinstance(ev, ast.Name) and isinstance(imp, ast.Name)
            (ev_src,) = self._sources(ev, scope)
            (imp_src,) = self._sources(imp, scope)
            assert _callee(ev_src) == "sustained_car_draw", ast.unparse(ev_src)
            assert "ev_power" in " ".join(
                ast.unparse(b) for b in self._sources(_kw(ev_src, "ev_draw_w"), scope))
            assert ast.unparse(_kw(ev_src, "car_active")) == ast.unparse(
                _kw(imp_src, "car_active"))

    def test_every_pool_call_carries_the_sustained_import(self):
        calls = self._calls("solar_bounded_surplus")
        assert calls, "solar_bounded_surplus() is no longer called from the coordinator"
        for c in calls:
            self._sustained(c, "grid_import_w")
            assert _kw(c, "ev_draw_w") is not None, (
                "solar_bounded_surplus() must be handed the chargers' draw")

    def test_the_reclaim_is_told_what_the_pool_already_took(self):
        pools = self._calls("solar_bounded_surplus")
        absorbed = self._calls("import_absorbed_by_loads_w")
        assert absorbed, "import_absorbed_by_loads_w() is not called"
        pool_imp = {self._sustained(c, "grid_import_w") for c in pools}
        for c in absorbed:
            assert self._sustained(c, "grid_import_w") in pool_imp, (
                "the reclaim's share must be judged on the pool's own import")
        for c in self._calls("reclaimable_battery_w"):
            scope = _enclosing(self.tree, c)
            val = _kw(c, "absorbed_w")
            assert val is not None, "reclaimable_battery_w() called without absorbed_w"
            for s in self._sources(val, scope):
                assert isinstance(s, ast.Call) and _callee(s) == "import_absorbed_by_loads_w"


# ── 5. the import that lasted ────────────────────────────────────────────


@pytest.mark.unit
class TestOnlyAnImportThatLastedCounts:
    @staticmethod
    def _feed(state, readings, *, car):
        out = None
        for t, w in readings:
            out = sustained_import(state, t, grid_import_w=w,
                                   grid_import_known=True, car_active=car)
        return out

    def test_no_car_is_the_mean_of_two_minutes(self):
        st = {}
        assert self._feed(st, [(0.0, 0.0), (10.0, 2500.0)], car=False) == 1250.0
        steady = [(10.0 + t * 10.0, 2500.0) for t in range(1, 13)]
        assert self._feed(st, steady, car=False) == 2500.0

    def test_a_charging_car_counts_the_lowest_of_two_minutes(self):
        st = {}
        quiet = [(t * 10.0, 0.0) for t in range(15)]       # 0–140 s
        assert self._feed(st, quiet, car=False) == 0.0
        assert self._feed(st, [(150.0, 8000.0)], car=True) == 0.0
        lasting = [(150.0 + t * 10.0, 8000.0) for t in range(1, 14)]
        assert self._feed(st, lasting, car=True) == 8000.0

    def test_after_a_restart_a_charging_cars_import_waits(self):
        st = {}
        assert self._feed(st, [(0.0, 3000.0), (60.0, 3000.0)], car=True) == 0.0
        assert self._feed(st, [(130.0, 3000.0)], car=True) == 3000.0

    def test_a_dark_meter_is_no_evidence(self):
        st = {}
        self._feed(st, [(t * 10.0, 0.0) for t in range(20)], car=False)
        assert sustained_import(st, 200.0, grid_import_w=0.0,
                                grid_import_known=False, car_active=True) is None

    def test_a_blink_keeps_the_history(self):
        # Two minutes of a steady 4 kW house import while a car is plugged
        # in, then one dark cycle: the import still counts on the next one.
        # Clearing the history on a blink gave the house two more minutes
        # of uncounted import every time (class 58).
        st = {}
        lasting = [(t * 10.0, 4000.0) for t in range(14)]
        assert self._feed(st, lasting, car=True) == 4000.0
        assert sustained_import(st, 140.0, grid_import_w=0.0,
                                grid_import_known=False, car_active=True) is None
        assert self._feed(st, [(150.0, 4000.0)], car=True) == 4000.0

    def test_a_gap_longer_than_the_window_starts_over(self):
        st = {}
        self._feed(st, [(t * 10.0, 0.0) for t in range(5)], car=True)
        for t in range(5, 20):   # 150 s dark
            sustained_import(st, t * 10.0, grid_import_w=0.0,
                             grid_import_known=False, car_active=True)
        assert self._feed(st, [(200.0, 4000.0)], car=True) == 0.0
        lasting = [(200.0 + t * 10.0, 4000.0) for t in range(1, 13)]
        assert self._feed(st, lasting, car=True) == 4000.0

    def test_negative_reads_as_zero(self):
        assert self._feed({}, [(0.0, -300.0)], car=False) == 0.0

    def test_the_cars_share_is_its_highest_draw_while_it_may_charge(self):
        st = {}
        for t, w in [(0.0, 11000.0), (60.0, 11000.0), (70.0, 4100.0)]:
            got = sustained_car_draw(st, t, ev_draw_w=w, car_active=True)
        assert got == 11000.0
        assert sustained_car_draw(st, 200.0, ev_draw_w=4100.0,
                                  car_active=True) == 4100.0
        assert sustained_car_draw(st, 210.0, ev_draw_w=300.0,
                                  car_active=False) == 300.0

    def test_the_window_is_two_minutes(self):
        assert LOADS_IMPORT_SUSTAIN_S == 120.0


async def _car_start(sc, *, sensor_lag_cycles, sustained, signal="plug"):
    """Sun 6 kW, house 1 kW, the 3 kW boiler running above the charger.
    At cycle 15 a car is plugged in and starts at 11 kW in the same cycle
    (a cloud box: plug and start in one poll; SEM did not offer it). The
    charger's power sensor reads 0 for ``sensor_lag_cycles`` cycles (10 s
    each), then 11 kW.

    ``signal`` — what opens the window: ``"plug"`` is production
    (``car_may_be_charging``); ``"ev_charging"`` is the reader's charging
    flag, which #739 holds False until the power reads above 500 W."""
    window, starts = {}, {}
    for i in range(50):
        car_w = 11000.0 if i >= 15 else 0.0
        car_seen = car_w if i >= 15 + sensor_lag_cycles else 0.0
        on_w = sc.active_surplus_draw_w()
        grid = 6000.0 - 1000.0 - on_w - car_w
        export, imp = max(0.0, grid), max(0.0, -grid)
        if signal == "plug":
            car = car_may_be_charging(starts, i * 10.0, plugged=i >= 15,
                                      commanded_amps=0, ev_draw_w=car_seen)
        else:
            car = car_seen > 500.0
        held = (sustained_import(window, i * 10.0, grid_import_w=imp,
                                 grid_import_known=True, car_active=car)
                if sustained else imp)
        pool = solar_bounded_surplus(
            grid_export_w=export, active_draw_w=on_w, solar_w=6000.0,
            grid_import_w=held, ev_draw_w=car_seen)
        await sc.update(pool, price_level="normal", grid_import_w=imp)


@pytest.mark.asyncio
class TestACarStartDoesNotStopTheBoiler:
    async def test_a_minute_of_sensor_lag_is_the_cars(self):
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        await _car_start(sc, sensor_lag_cycles=6, sustained=True)
        boiler.deactivate.assert_not_awaited()

    async def test_without_the_window_the_lag_stops_it(self):
        # Non-vacuous: the raw import books the car's first minute to the
        # house and the boiler goes off.
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        await _car_start(sc, sensor_lag_cycles=6, sustained=False)
        boiler.deactivate.assert_awaited()

    async def test_the_charging_flag_opens_the_window_too_late(self):
        # Non-vacuous for the signal: the reader's charging flag turns on
        # with the lagging power reading, so the window opens after the
        # car's first minute has already been booked to the house. (A 20 s
        # lag no longer stops it either way: the mean of two minutes
        # thins it out.)
        for lag in (6,):
            sc = SurplusController(MagicMock())
            boiler = _boiler()
            sc.register_device(boiler)
            await _car_start(sc, sensor_lag_cycles=lag, sustained=True,
                             signal="ev_charging")
            boiler.deactivate.assert_awaited()

    async def test_the_plug_opens_it_in_time_at_every_lag(self):
        for lag in (0, 1, 2, 6):
            sc = SurplusController(MagicMock())
            boiler = _boiler()
            sc.register_device(boiler)
            await _car_start(sc, sensor_lag_cycles=lag, sustained=True)
            boiler.deactivate.assert_not_awaited()


@pytest.mark.unit
class TestWhatOpensTheWindow:
    @staticmethod
    def _at(st, t, *, plugged=False, amps=0, draw=0.0):
        return car_may_be_charging(st, t, plugged=plugged,
                                   commanded_amps=amps, ev_draw_w=draw)

    def test_a_plug_in_opens_it_for_a_while_then_it_closes(self):
        st = {}
        assert not self._at(st, 0.0)
        assert self._at(st, 10.0, plugged=True)                # plugged in
        assert self._at(st, 10.0 + CAR_START_HOLD_S, plugged=True)
        # still plugged, full, drawing nothing: the window closes
        assert not self._at(st, 20.0 + CAR_START_HOLD_S, plugged=True)

    def test_a_rising_offer_opens_it_a_steady_one_does_not_keep_it(self):
        st = {}
        assert self._at(st, 0.0, plugged=True, amps=6)
        assert not self._at(st, 10.0 + CAR_START_HOLD_S, plugged=True, amps=6)
        assert self._at(st, 20.0 + CAR_START_HOLD_S, plugged=True, amps=10)

    def test_a_stop_opens_it_too(self):
        # The meter still shows the car's import after the charger reads
        # 0 W: a falling draw, a falling offer and an unplug each open it,
        # and it closes again once nothing changes.
        h = CAR_START_HOLD_S
        for before, after in (
                ({"plugged": True, "amps": 16, "draw": 11000.0},
                 {"plugged": True, "amps": 16, "draw": 0.0}),
                ({"plugged": True, "amps": 16, "draw": 0.0},
                 {"plugged": True, "amps": 0, "draw": 0.0}),
                ({"plugged": True, "amps": 0, "draw": 0.0},
                 {"plugged": False, "amps": 0, "draw": 0.0})):
            st = {}
            self._at(st, 0.0, **before)
            self._at(st, 10.0 + h, **before)
            if before["draw"] == 0.0:
                assert not self._at(st, 20.0 + h, **before)
            assert self._at(st, 30.0 + h, **after)
            assert self._at(st, 30.0 + 2 * h, **after)
            assert not self._at(st, 40.0 + 2 * h, **after)

    def test_a_real_draw_keeps_it_open(self):
        st = {}
        self._at(st, 0.0, plugged=True, amps=16)
        assert self._at(st, 3600.0, plugged=True, amps=16, draw=11000.0)

    def test_a_chargers_standby_is_not_a_car(self):
        # KEBA idles at 110-140 W (#739): that must not hold the window
        # open all day.
        for standby in (0.0, 90.0, 140.0, 500.0):
            assert not self._at({}, 0.0, draw=standby)


async def _square_wave(sc, *, standby_w=0.0, car_active=None,
                       plugged=False, amps=0):
    """The reporter's 12:30–12:45 square wave: sun 5.3 kW, house 2.2 kW,
    a 4 kW load 110 s on / 60 s off, no car charging. ``standby_w`` — an
    idle charger's own draw; ``plugged`` / ``amps`` — a car left plugged in
    (full), and what SEM offers it. ``car_active`` forces the window (None =
    what production decides)."""
    window, starts = {}, {}
    for i in range(180):
        extra = 4000.0 if (i % 17) < 11 else 0.0
        on_w = sc.active_surplus_draw_w()
        grid = 5300.0 - 2200.0 - standby_w - extra - on_w
        export, imp = max(0.0, grid), max(0.0, -grid)
        car = (car_may_be_charging(starts, i * 10.0, plugged=plugged,
                                   commanded_amps=amps, ev_draw_w=standby_w)
               if car_active is None else car_active)
        held = sustained_import(window, i * 10.0, grid_import_w=imp,
                                grid_import_known=True, car_active=car)
        pool = solar_bounded_surplus(
            grid_export_w=export, active_draw_w=on_w, solar_w=5300.0,
            grid_import_w=held, ev_draw_w=standby_w)
        await sc.update(pool, price_level="normal", grid_import_w=imp)


@pytest.mark.asyncio
class TestACyclingHouseLoadStillCounts:
    async def test_a_4kw_load_two_minutes_on_one_off_stops_the_boiler(self):
        # Every on-phase imports ~3.9 kW with the boiler on; a two-minute
        # minimum would never see it.
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        await _square_wave(sc)
        boiler.deactivate.assert_awaited()

    async def test_an_idle_chargers_standby_does_not_hide_it(self):
        for standby in (90.0, 120.0, 140.0):
            sc = SurplusController(MagicMock())
            boiler = _boiler()
            sc.register_device(boiler)
            await _square_wave(sc, standby_w=standby)
            boiler.deactivate.assert_awaited()

    async def test_a_full_car_left_plugged_in_does_not_hide_it(self):
        # Plugged in all afternoon, drawing 0 W; SEM may keep offering it
        # 6 A. Neither is a start, so the window closes.
        for amps in (0, 6):
            sc = SurplusController(MagicMock())
            boiler = _boiler()
            sc.register_device(boiler)
            await _square_wave(sc, plugged=True, amps=amps)
            boiler.deactivate.assert_awaited()

    async def test_an_open_window_would_hide_it(self):
        # Non-vacuous: with the window open (a 100 W floor read KEBA's
        # standby as a car), the lowest reading of two minutes is always an
        # off-phase and the boiler is never stopped.
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        await _square_wave(sc, standby_w=140.0, car_active=True)
        boiler.deactivate.assert_not_awaited()


@pytest.mark.asyncio
class TestAPaidRunIsNotSteeredBySun:
    async def test_a_paid_setpoint_holds_its_power_at_night(self):
        # A watt setpoint on the cheap-hours top-up at night: the sun's pool
        # is 0, and offering it that wrote its floor every other cycle.
        sc = SurplusController(MagicMock())
        heater = _load("heater", 500.0, 2, paid=True)
        sc.register_device(heater)
        await _cycles(sc, solar_w=0.0, house_w=300.0, n=12)
        heater.adjust_power.assert_not_awaited()
        heater.deactivate.assert_not_awaited()


# ── 9. the deficit pass keeps develop's order: lowest first ─────────────


def _stuck(device_id, draw, priority, *, refuses_stop):
    """A running load the deficit pass cannot end this cycle:
    ``refuses_stop`` — a started appliance run (``ScheduleDevice`` ignores
    ``deactivate``); otherwise its minimum run time is not over."""
    d = _load(device_id, draw, priority)
    if refuses_stop:
        d.deactivate = AsyncMock()          # stays on
        # (#1335) …and says so where the walk asks, as ScheduleDevice does
        d.can_deactivate = MagicMock(return_value=False)
    else:
        d.can_deactivate = MagicMock(return_value=False)
    return d


@pytest.mark.asyncio
class TestTheDeficitPassKeepsTheOrder:
    """A 1 kW Solar pump at priority 2 and a 2 kW load at priority 7 that
    cannot be stopped now. The pass tries the lowest load first and, when
    it cannot stop, the next one up — develop's order (develop reached it
    only through the sun cap; see class 137, residual 8). A first cut
    of this fix kept the pump on (it was "covered" at its turn), and the
    house bought the lower load's share for its whole run (found in
    review: develop stopped the pump through the sun cap)."""

    async def test_a_started_appliance_run_stops_the_pump_as_before(self):
        # Sun 2 kW, house 0.5 kW: develop's sun cap stops the pump too.
        sc = SurplusController(MagicMock())
        pump = _load("pump", 1000.0, 2)
        dishwasher = _stuck("dishwasher", 2000.0, 7, refuses_stop=True)
        sc.register_device(pump)
        sc.register_device(dishwasher)
        await _cycles(sc, solar_w=2000.0, house_w=500.0, n=12, price="normal")
        # (#1335) the started run says it cannot stop; the walk does not try
        dishwasher.deactivate.assert_not_awaited()
        pump.deactivate.assert_awaited()

    async def test_a_load_in_its_minimum_run_stops_the_pump(self):
        # Sun 3 kW, house 0.5 kW: the house buys 500 W.
        sc = SurplusController(MagicMock())
        pump = _load("pump", 1000.0, 2)
        heater = _stuck("heater", 2000.0, 7, refuses_stop=False)
        sc.register_device(pump)
        sc.register_device(heater)
        await _cycles(sc, solar_w=3000.0, house_w=500.0, n=12, price="normal")
        pump.deactivate.assert_awaited()

    async def test_a_load_the_sun_did_not_cover_is_still_stopped(self):
        # Sun 3.5 kW, house 2 kW: the 3 kW boiler at priority 1 is not
        # covered either, so it goes, though the pump below it cannot.
        sc = SurplusController(MagicMock())
        boiler = _load("boiler", 3000.0, 1)
        pump = _stuck("pump", 1000.0, 2, refuses_stop=False)
        sc.register_device(boiler)
        sc.register_device(pump)
        await _cycles(sc, solar_w=3500.0, house_w=2000.0, n=12, price="normal")
        boiler.deactivate.assert_awaited()


@pytest.mark.asyncio
class TestAnIdleSwitchIsStillStopped:
    """A 3 kW boiler whose thermostat holds it off: the switch is on, its
    power sensor reads 0 W. Giving back the 0 W it read made the pass skip
    it, and the 1 kW pump below it never ran while 2.5 kW went to the grid
    (found in review). (#1335/#1156) The walk now books the running boiler
    its MEASURED draw, 0 W: it costs the sun nothing, so the pump below
    runs and the boiler is left on for its thermostat."""

    async def test_the_pump_below_runs(self):
        sc = SurplusController(MagicMock())
        boiler = _load("boiler", 3000.0, 3)
        boiler.get_current_consumption = MagicMock(return_value=0.0)
        pump = _load("pump", 1000.0, 5)

        async def _on(*_a):
            pump.is_active = True
            return 1000.0
        pump.activate = AsyncMock(side_effect=_on)
        sc.register_device(boiler)
        sc.register_device(pump)
        on = 0
        for _ in range(30):
            await _cycles(sc, solar_w=3000.0, house_w=500.0, n=1,
                          price="normal")
            on += bool(pump.is_active)
        assert on >= 25


async def _house_spike(sc, *, spike_cycles, live):
    """Sun 5 kW, house 1.5 kW, the 3 kW boiler on: 500 W to the grid. A
    1.2 kW appliance runs for ``spike_cycles`` cycles of 10 s. ``live`` —
    hand the pool the live import instead of the coordinator's window."""
    window = {}
    for i in range(40):
        extra = 1200.0 if 10 <= i < 10 + spike_cycles else 0.0
        draw = sc.active_surplus_draw_w()
        grid = 5000.0 - 1500.0 - extra - draw
        export, imp = max(0.0, grid), max(0.0, -grid)
        held = sustained_import(window, i * 10.0, grid_import_w=imp,
                                grid_import_known=True, car_active=False)
        pool = solar_bounded_surplus(
            grid_export_w=export, active_draw_w=draw, solar_w=5000.0,
            grid_import_w=imp if live else held)
        await sc.update(pool, price_level="normal", grid_import_w=imp)


@pytest.mark.asyncio
class TestAShortImportDoesNotStopTheBoiler:
    async def test_a_kettles_20_seconds(self):
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        await _house_spike(sc, spike_cycles=2, live=False)
        boiler.deactivate.assert_not_awaited()

    async def test_the_live_reading_stopped_it(self):
        # Non-vacuous: the live import goes past the median of 3.
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        await _house_spike(sc, spike_cycles=2, live=True)
        boiler.deactivate.assert_awaited()

    async def test_an_import_that_lasts_still_stops_it(self):
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        await _house_spike(sc, spike_cycles=30, live=False)
        boiler.deactivate.assert_awaited()


async def _car_change(sc, *, car_after_w, amps_after, meter_lag_cycles,
                      paired=True):
    """Sun 6 kW, house 1 kW, the 3 kW boiler on. A car charges at 11 kW
    (16 A) — 9 kW from the grid — and at cycle 20 it stops or ramps down
    to ``car_after_w`` (SEM's offer ``amps_after``). The charger reads its
    new draw at once; the meter shows each import ``meter_lag_cycles``
    cycles late. ``paired=False`` hands the pool the live car draw."""
    window, starts, car_win = {}, {}, {}
    true_imports = []
    for i in range(60):
        car_w = 11000.0 if i < 20 else car_after_w
        amps = 16 if i < 20 else amps_after
        on_w = sc.active_surplus_draw_w()
        grid = 6000.0 - 1000.0 - on_w - car_w
        true_imports.append(max(0.0, -grid))
        export = max(0.0, grid)
        imp = true_imports[max(0, i - meter_lag_cycles)]
        car = car_may_be_charging(starts, i * 10.0, plugged=True,
                                  commanded_amps=amps, ev_draw_w=car_w)
        held = sustained_import(window, i * 10.0, grid_import_w=imp,
                                grid_import_known=True, car_active=car)
        ev = sustained_car_draw(car_win, i * 10.0, ev_draw_w=car_w,
                                car_active=car)
        pool = solar_bounded_surplus(
            grid_export_w=export, active_draw_w=on_w, solar_w=6000.0,
            grid_import_w=held, ev_draw_w=ev if paired else car_w)
        await sc.update(pool, price_level="normal", grid_import_w=imp)


@pytest.mark.asyncio
class TestACarStopDoesNotStopTheBoiler:
    """The meter is slower than the charger's power sensor: at a stop or a
    ramp-down the import the car caused is still on the meter (found in
    review: a 30 s meter stopped the boiler at every car stop)."""

    async def test_a_stop(self):
        for lag in (3, 6):
            sc = SurplusController(MagicMock())
            boiler = _boiler()
            sc.register_device(boiler)
            await _car_change(sc, car_after_w=0.0, amps_after=0,
                              meter_lag_cycles=lag)
            boiler.deactivate.assert_not_awaited()

    async def test_a_ramp_down(self):
        for lag in (3, 6):
            sc = SurplusController(MagicMock())
            boiler = _boiler()
            sc.register_device(boiler)
            await _car_change(sc, car_after_w=4100.0, amps_after=6,
                              meter_lag_cycles=lag)
            boiler.deactivate.assert_not_awaited()

    async def test_the_live_car_draw_stopped_it_at_a_ramp_down(self):
        # Non-vacuous: the lowest import of two minutes against the car's
        # live draw books the lag to the house.
        sc = SurplusController(MagicMock())
        boiler = _boiler()
        sc.register_device(boiler)
        await _car_change(sc, car_after_w=4100.0, amps_after=6,
                          meter_lag_cycles=6, paired=False)
        boiler.deactivate.assert_awaited()


@pytest.mark.unit
class TestTheBatterySlotKeepsADeficit:
    def test_hand_back(self):
        assert reclaim_handed_back(2000.0, 500.0) == 1500.0
        assert reclaim_handed_back(300.0, 500.0) == 0.0
        # a deficit made above the battery stays a deficit
        assert reclaim_handed_back(-1550.0, 500.0) == -1550.0
        assert reclaim_handed_back(-200.0, 0.0) == -200.0

    async def test_a_load_above_the_battery_that_overdraws_is_stopped(self):
        # 1 kW pool + 500 W of the pack's charge for the boiler above the
        # battery; it draws 3 kW. Crossing the battery's slot used to
        # clamp the walk to 0, and the deficit pass never ran.
        sc = SurplusController(MagicMock())
        boiler = _load("boiler", 3000.0, 1)
        below = _load("pump", 800.0, 6)
        below.is_active = False
        sc.register_device(boiler)
        sc.register_device(below)
        await sc.update(1000.0, price_level="normal", reclaim_w=500.0,
                        battery_priority=5)
        boiler.deactivate.assert_awaited()
        below.activate.assert_not_awaited()


@pytest.mark.asyncio
class TestALoadWaitingToStopIsStillDebited:
    async def test_the_load_below_does_not_get_its_watts(self):
        # Sun 4 kW, house 0.5 kW. A 2 kW heater at priority 1 met its stop
        # condition but its minimum run is not over; it still draws. The
        # 2 kW pump below must not start on the heater's watts.
        sc = SurplusController(MagicMock())
        heater = _load("heater", 2000.0, 1)
        heater.stop_condition_met = True
        heater.can_deactivate = MagicMock(return_value=False)
        pump = _load("pump", 2000.0, 2)
        pump.is_active = False
        sc.register_device(heater)
        sc.register_device(pump)
        await _cycles(sc, solar_w=4000.0, house_w=500.0, n=6, price="normal")
        pump.activate.assert_not_awaited()


@pytest.mark.asyncio
class TestTheStopPassGivesBackWhatItTook:
    async def test_a_battery_covered_load_below_is_not_stopped_for_one_above(self):
        # Pool 1 kW + 500 W reclaim; battery at priority 5. The 3 kW boiler
        # at priority 1 overdraws. A 2 kW heater at priority 6 runs on its
        # battery share (Tier-1). Stopping the heater gives the pool nothing
        # back; crediting its full draw ended the pass before the boiler.
        sc = SurplusController(MagicMock())
        boiler = _load("boiler", 3000.0, 1)
        heater = _load("heater", 2000.0, 6)
        heater.battery_assist_enabled = True
        sc.register_device(boiler)
        sc.register_device(heater)
        await sc.update(1000.0, price_level="normal", reclaim_w=500.0,
                        battery_priority=5, battery_soc=80.0,
                        battery_buffer_soc=20.0, battery_reserve_soc=10.0,
                        battery_assist_budget_w=2000.0)
        assert heater._tier1_batt_w == pytest.approx(2000.0)
        boiler.deactivate.assert_awaited()
        heater.deactivate.assert_not_awaited()
