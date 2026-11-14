"""#1323 — a heat pump steps DOWN in a shortfall; a climate unit picks heat or cool.

SEM raised a heat pump's setpoint on spare sun and never lowered it. Two
additions, both off unless the user asks:

1. **Step down.** When the house buys grid power in an expensive hour, or
   nears its peak limit, the pump is held below its normal state: a lower
   setpoint, or the SG-Ready "blocked" signal. It is a layer-1 reason
   (``compute_load_intent``, clause 3f, its own reason codes); layer 2 hands
   it the price level and the peak state it already has; layer 3
   (``reconcile_load``) is the only place that sends it and takes it back.
2. **Heat or cool by itself.** ``hvac_mode: by_forecast`` on a climate unit:
   the season comes from the outdoor outlook, with a dead band and a day's
   dwell. The device reports its mode; nothing is switched outside layer 3.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.const import LoadManagementState
from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    LoadIntent,
    STEP_DOWN_VERB,
    SurplusController,
    _activate_owned,
    _release_step_down,
    compute_load_intent,
    deactivate_devices,
    reconcile_load,
)
from custom_components.solar_energy_management.devices.base import (
    HVAC_BY_FORECAST,
    ClimateDevice,
    DeviceControlMode,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
    SGReadyState,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)

from .ast_contracts import call_sites, calls

ROOM = "sensor.room"
EXPENSIVE, NORMAL = "expensive", "normal"


def _pump(hass, *, action="block", room="20.5", climate=None, band=True):
    hass.set("switch.sg1", "off")
    hass.set("switch.sg2", "off")
    hass.set(ROOM, room, unit_of_measurement="°C")
    hp = HeatPumpController(hass, relay1_entity_id="switch.sg1",
                            relay2_entity_id="switch.sg2",
                            climate_entity_id=climate,
                            rated_power=2000.0, min_power_threshold=2000.0,
                            step_down=action)
    hp._boot_adoption_pending = False
    if band:
        # Keep at 21 °C, run now past 19 °C: 20.5 °C is inside the range
        hp.comfort_entity, hp.comfort_target = ROOM, 21.0
        hp.comfort_offset, hp.comfort_limit = 1.0, 19.0
    sc = SurplusController(hass)
    sc.register_device(hp)
    return sc, hp


async def _cycle(sc, n=1, *, price=NORMAL, buying=0.0, peak=None, surplus=0.0,
                 observer=False):
    for _ in range(n):
        await sc.update(surplus, price_level=price, peak_state=peak,
                        grid_import_w=buying, observer=observer,
                        is_night=True)


def _sg(hass):
    return (hass._states["switch.sg1"].state, hass._states["switch.sg2"].state)


def _served(hp):
    """The minimum hold and gap are over."""
    hp._stepped_down_at = datetime.now() - timedelta(hours=1)
    hp._step_released_at = datetime.now() - timedelta(hours=1)


def _intent(dev, **kw):
    kw.setdefault("remaining_surplus_w", 0.0)
    return compute_load_intent(dev, **kw)


# ── both switches off: nothing changes ────────────────────────────────────

class TestOffByDefault:
    def test_the_default_action_is_off(self):
        hp = HeatPumpController(_Hass())
        assert hp.step_down_action == "off"
        assert hp.step_down_ready is False
        assert LoadIntent(False, 0.0, None, "x").step_down is False

    @pytest.mark.parametrize("peak_freeze", [False, True])
    def test_layer_1_gives_the_same_intent_as_before(self, peak_freeze):
        """Off: an expensive hour with import decides exactly what a normal
        hour with none decides — the new inputs are not read."""
        hass = _Hass()
        _sc, hp = _pump(hass, action="off")
        before = _intent(hp, peak_freeze=peak_freeze)
        now = _intent(hp, peak_freeze=peak_freeze,
                      price_is_expensive=True, buying_w=4000.0)
        assert now == before and now.code == before.code
        assert now.step_down is False

    @pytest.mark.asyncio
    async def test_an_hour_of_shortfall_writes_nothing(self):
        hass = _Hass()
        sc, hp = _pump(hass, action="off")
        await _cycle(sc, 360, price=EXPENSIVE, buying=3000.0,
                     peak=LoadManagementState.WARNING)
        assert not hass.services.async_call.await_args_list
        assert hp.sg_ready_state is SGReadyState.NORMAL
        assert not sc.decision_log.records()


# ── the two causes ────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTheTwoCauses:
    async def test_expensive_grid_power_blocks_the_pump(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert hp.is_stepped_down
        assert hp.sg_ready_state is SGReadyState.BLOCKED
        assert _sg(hass) == ("on", "off")          # the standard's 1:0
        rec = sc.decision_log.records()[-1]
        assert (rec["new"], rec["reason_code"]) == (
            STEP_DOWN_VERB, RC.LOAD_STEP_DOWN_PRICE)

    async def test_the_peak_limit_near_blocks_the_pump(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, peak=LoadManagementState.WARNING)
        assert hp.is_stepped_down
        assert sc.decision_log.records()[-1]["reason_code"] == RC.LOAD_STEP_DOWN_PEAK

    @pytest.mark.parametrize("price, buying", [
        (NORMAL, 3000.0),      # buying, but not in an expensive hour
        ("cheap", 3000.0),
        (EXPENSIVE, 60.0),     # expensive, but the house buys next to nothing
    ])
    async def test_no_cause_no_step_down(self, price, buying):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, 5, price=price, buying=buying)
        assert not hp.is_stepped_down
        assert not hass.services.async_call.await_args_list

    async def test_an_unread_meter_is_not_a_purchase(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await sc.update(0.0, price_level=EXPENSIVE, grid_import_w=3000.0,
                        grid_import_known=False)
        assert not hp.is_stepped_down

    async def test_the_setpoint_action_lowers_and_puts_back(self):
        hass = _Hass()
        hass.set("climate.hp", "heat", temperature=21.0)
        sc, hp = _pump(hass, action="setpoint", climate="climate.hp")
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert hp.is_stepped_down
        sent = hass.calls("set_temperature", "climate.hp")
        assert [c.args[2]["temperature"] for c in sent] == [19.0]   # 21 − 2
        assert _sg(hass) == ("off", "off")         # the contacts are not used
        _served(hp)
        await _cycle(sc, price=NORMAL)
        sent = hass.calls("set_temperature", "climate.hp")
        assert [c.args[2]["temperature"] for c in sent] == [19.0, 21.0]
        assert not hp.is_stepped_down

    async def test_the_setpoint_never_goes_under_the_minimum(self):
        hass = _Hass()
        hass.set("climate.hp", "heat", temperature=18.5)
        sc, hp = _pump(hass, action="setpoint", climate="climate.hp")
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert hass.calls("set_temperature", "climate.hp")[0].args[2][
            "temperature"] == 18.0                 # min_setpoint


# ── it does not flap ──────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestNoFlapping:
    async def test_its_own_effect_does_not_release_it(self):
        """Blocked, the pump no longer draws, so the import is gone. The
        hour is still expensive and there is no sun: it stays down."""
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        _served(hp)
        await _cycle(sc, 30, price=EXPENSIVE, buying=0.0)
        assert hp.is_stepped_down
        assert len(hass.calls("turn_on", "switch.sg1")) == 1

    async def test_a_flickering_price_over_an_hour_switches_once(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        for i in range(360):                       # an hour of 10 s cycles
            await _cycle(sc, price=EXPENSIVE if i % 2 == 0 else NORMAL,
                         buying=800.0)
        assert hp.is_stepped_down, "the hold keeps it down"
        assert len(hass.calls("turn_on", "switch.sg1")) == 1
        assert not hass.calls("turn_off", "switch.sg1")

    async def test_the_cause_gone_and_the_hold_served_releases_once(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        _served(hp)
        await _cycle(sc, 10, price=NORMAL, buying=800.0)
        assert not hp.is_stepped_down
        assert hp.sg_ready_state is SGReadyState.NORMAL
        assert _sg(hass) == ("off", "off")
        assert len(hass.calls("turn_off", "switch.sg1")) == 1
        assert sc.decision_log.records()[-1]["reason_code"] == RC.LOAD_STEP_DOWN_END

    async def test_the_next_step_down_waits_for_the_gap(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        _served(hp)
        await _cycle(sc, price=NORMAL)             # released just now
        await _cycle(sc, 20, price=EXPENSIVE, buying=800.0)
        assert not hp.is_stepped_down, "inside the gap"
        hp._step_released_at = datetime.now() - timedelta(hours=1)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert hp.is_stepped_down

    async def test_sun_returning_ends_the_expensive_hour_cause(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        _served(hp)
        it = _intent(hp, price_is_expensive=True, buying_w=0.0,
                     remaining_surplus_w=900.0)
        assert it.step_down is False


# ── what outranks it ──────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestPrecedence:
    async def test_too_cold_is_never_stepped_down(self):
        hass = _Hass()
        sc, hp = _pump(hass, room="19.0")          # at the limit: forced
        it = _intent(hp, price_is_expensive=True, buying_w=3000.0)
        assert it.step_down is False
        assert (it.on, it.code) == (True, RC.LOAD_COMFORT_FLOOR)

    async def test_getting_too_cold_ends_it_at_once(self):
        """The hold is against a flickering cause, not against the cold."""
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, peak=LoadManagementState.WARNING)
        assert hp.is_stepped_down                  # hold NOT served
        hass.set(ROOM, "18.9", unit_of_measurement="°C")
        await _cycle(sc, peak=LoadManagementState.WARNING)
        assert not hp.is_stepped_down
        assert hp.sg_ready_state is not SGReadyState.BLOCKED

    async def test_no_band_or_no_reading_is_never_stepped_down(self):
        hass = _Hass()
        sc, hp = _pump(hass, band=False)
        await _cycle(sc, 3, price=EXPENSIVE, buying=3000.0)
        assert not hp.is_stepped_down              # no range the user allowed
        sc2, hp2 = _pump(_Hass(), room="unavailable")
        await _cycle(sc2, 3, price=EXPENSIVE, buying=3000.0)
        assert not hp2.is_stepped_down             # SEM does not block blind

    async def test_away_is_not_stepped_down_and_ends_one(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        hp.vacation = True
        assert _intent(hp, price_is_expensive=True, buying_w=800.0).step_down is False
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert not hp.is_stepped_down              # NORMAL: frost logic is the pump's

    async def test_mode_off_ends_it_at_once(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        hp.control_mode = DeviceControlMode.OFF
        assert _intent(hp, price_is_expensive=True, buying_w=800.0).step_down is False
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert not hp.is_stepped_down
        assert _sg(hass) == ("off", "off")

    async def test_a_disabled_pump_is_still_released(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        hp._enabled = False
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert not hp.is_stepped_down

    async def test_a_peak_shed_stops_a_boost_first(self):
        """A running boost is ended by its own reason (the shed); the pump
        is stepped down only once it is off."""
        hass = _Hass()
        sc, hp = _pump(hass)
        assert await _activate_owned(hp, 3000.0) > 0
        it = _intent(hp, is_shed_target=True, peak_freeze=True)
        assert (it.on, it.code, it.step_down) == (False, RC.LOAD_PEAK_SHED, False)
        kept = _intent(hp, peak_freeze=True, price_is_expensive=True,
                       buying_w=3000.0)
        assert kept.step_down is False             # 3e never ends a run

    async def test_a_legionella_run_outranks_it(self):
        dev = SimpleNamespace(
            device_id="tank", name="Tank", control_mode=DeviceControlMode.SURPLUS,
            is_active=False, is_enabled=True, rated_power=2000.0,
            min_power_threshold=2000.0, runs_without_surplus=True,
            step_down_ready=True, is_stepped_down=False,
            get_current_consumption=lambda: 0.0)
        it = _intent(dev, price_is_expensive=True, buying_w=3000.0)
        assert (it.on, it.code, it.step_down) == (True, RC.LOAD_LEGIONELLA, False)
        # (#1344) …but a due run does not START into a peak (the shed ended
        # it the next cycle, on and off for as long as the peak lasted): it
        # waits, and the peak's own step-down applies meanwhile
        it = _intent(dev, peak_freeze=True, price_is_expensive=True,
                     buying_w=3000.0)
        assert (it.on, it.code, it.step_down) == (False, RC.LOAD_STEP_DOWN_PEAK, True)

    async def test_a_boost_replaces_the_step_down(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert hp.is_stepped_down
        await reconcile_load(hp, LoadIntent(True, 2000.0, "solar", "sun"),
                             controller=sc)
        assert not hp.is_stepped_down and hp.is_active
        assert hp.sg_ready_state is SGReadyState.BOOST


# ── observer mode, restart, teardown ──────────────────────────────────────

@pytest.mark.asyncio
class TestObserverRestartTeardown:
    async def test_observer_mode_sends_nothing_and_says_so_every_cycle(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        for _ in range(3):
            sc.observer_decisions.clear()          # the roster is swept
            await _cycle(sc, price=EXPENSIVE, buying=800.0, observer=True)
            would = sc.observer_decisions[hp.device_id]
            assert (would["action"], would["reason_code"]) == (
                "step_down", RC.LOAD_STEP_DOWN_PRICE)
        assert not hass.services.async_call.await_args_list
        assert not hp.is_stepped_down
        rec = sc.decision_log.records()
        assert [(r["new"], r["observer"]) for r in rec] == [(STEP_DOWN_VERB, True)]

    async def test_the_device_seam_holds_it_back_too(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        hp.observer_mode = True
        hp.withheld_commands = []
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert not hass.services.async_call.await_args_list
        assert not hp.is_stepped_down and hp._last_step_down_path == "withheld"

    async def test_a_restart_takes_a_block_back(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        memo = hp.step_down_memo()
        assert memo == {"action": "block", "restore": None, "target": None}

        sc2, fresh = _pump_keeping_contacts(hass)
        assert fresh.restore_step_down(memo) is True
        assert fresh.is_stepped_down
        await _cycle(sc2, price=NORMAL)            # no cause: released at once
        assert not fresh.is_stepped_down and _sg(hass) == ("off", "off")

    async def test_a_restart_puts_the_setpoint_back(self):
        hass = _Hass()
        hass.set("climate.hp", "heat", temperature=21.0)
        sc, hp = _pump(hass, action="setpoint", climate="climate.hp")
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        memo = hp.step_down_memo()
        hass.set("climate.hp", "heat", temperature=19.0)
        sc2, fresh = _pump(hass, action="setpoint", climate="climate.hp")
        assert fresh.restore_step_down(memo)
        await _cycle(sc2, price=NORMAL)
        assert hass.calls("set_temperature", "climate.hp")[-1].args[2][
            "temperature"] == 21.0

    async def test_a_block_someone_else_ended_is_not_believed(self):
        hass = _Hass()
        _sc, fresh = _pump(hass)                   # contacts read NORMAL
        assert fresh.restore_step_down({"action": "block", "restore": None}) is False
        assert not fresh.is_stepped_down

    async def test_teardown_takes_it_back(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        await deactivate_devices([hp], "removed")
        assert not hp.is_stepped_down and _sg(hass) == ("off", "off")


def _pump_keeping_contacts(hass):
    """A fresh controller on the contacts as the last one left them."""
    hp = HeatPumpController(hass, relay1_entity_id="switch.sg1",
                            relay2_entity_id="switch.sg2", rated_power=2000.0,
                            min_power_threshold=2000.0, step_down="block")
    hp._boot_adoption_pending = False
    hp.comfort_entity, hp.comfort_target = ROOM, 21.0
    hp.comfort_offset, hp.comfort_limit = 1.0, 19.0
    sc = SurplusController(hass)
    sc.register_device(hp)
    return sc, hp


# ── one place switches ────────────────────────────────────────────────────

class TestOnePlaceSwitches:
    def test_layer_3_sends_and_takes_back(self):
        assert calls(reconcile_load, "step_down")
        assert calls(reconcile_load, "_release_step_down")
        assert calls(_release_step_down, "release_step_down")
        assert not calls(compute_load_intent, "step_down")
        assert not calls(SurplusController._desired_intents, "step_down")

    def test_nothing_else_sends_a_step_down(self):
        sites = {str(s[0]).rsplit("/", 1)[-1] for s in call_sites("step_down")}
        assert sites <= {"surplus_controller.py"}, sites
        release = {str(s[0]).rsplit("/", 1)[-1]
                   for s in call_sites("release_step_down")}
        assert release <= {"surplus_controller.py"}, release


# ── heat or cool by the outdoor outlook ───────────────────────────────────

def _unit(hass=None, mode=HVAC_BY_FORECAST):
    hass = hass or _Hass()
    hass.set("climate.ac", "off", current_temperature=22.0)
    return ClimateDevice(hass, "ac", "AC", rated_power=1500.0,
                         entity_id="climate.ac", hvac_mode=mode,
                         target_temperature=22.0), hass


T0 = datetime(2026, 5, 1, 12, 0)


class TestHeatOrCoolByForecast:
    def test_a_fixed_mode_is_untouched(self):
        dev, _ = _unit(mode="cool")
        assert dev.update_season(2.0, T0) is None
        assert dev.hvac_mode == "cool" and dev.start_refusal is None
        heat, _ = _unit(mode="heat")
        heat.update_season(35.0, T0)
        assert heat.hvac_mode == "heat"

    def test_ha_auto_stays_the_units_own_mode(self):
        dev, _ = _unit(mode="auto")
        dev.update_season(2.0, T0)
        assert dev.hvac_mode == "auto"

    def test_the_first_outlook_decides(self):
        cold, _ = _unit()
        assert cold.update_season(8.0, T0) == "heat" and cold.hvac_mode == "heat"
        warm, _ = _unit()
        assert warm.update_season(27.0, T0) == "cool" and warm.hvac_mode == "cool"

    def test_no_outlook_yet_waits_with_its_own_reason(self):
        dev, _ = _unit()
        assert dev.update_season(None, T0) is None
        assert dev.start_refusal == "season"
        dev.control_mode = DeviceControlMode.SURPLUS
        it = _intent(dev, remaining_surplus_w=5000.0)
        assert (it.on, it.code) == (False, RC.LOAD_NO_SEASON)

    def test_the_dead_band_changes_nothing(self):
        dev, _ = _unit()
        dev.update_season(8.0, T0)
        for i, outlook in enumerate((16.0, 19.0, 21.9)):
            assert dev.update_season(outlook, T0 + timedelta(days=2 + i)) == "heat"

    def test_past_the_threshold_waits_a_day(self):
        dev, _ = _unit()
        dev.update_season(8.0, T0)
        assert dev.update_season(23.5, T0 + timedelta(hours=6)) == "heat"
        assert dev.update_season(23.5, T0 + timedelta(hours=25)) == "cool"
        # …and back the same way
        t1 = T0 + timedelta(hours=25)
        assert dev.update_season(13.0, t1 + timedelta(hours=3)) == "cool"
        assert dev.update_season(13.0, t1 + timedelta(hours=24)) == "heat"

    def test_a_clear_flip_does_not_wait(self):
        dev, _ = _unit()
        dev.update_season(8.0, T0)
        assert dev.update_season(25.0, T0 + timedelta(hours=2)) == "cool"

    def test_no_reading_keeps_the_season(self):
        dev, _ = _unit()
        dev.update_season(27.0, T0)
        assert dev.update_season(None, T0 + timedelta(days=3)) == "cool"

    def test_never_while_the_unit_runs(self):
        dev, hass = _unit()
        dev.update_season(8.0, T0)
        hass.set("climate.ac", "heat", current_temperature=20.0)
        from custom_components.solar_energy_management.devices.base import DeviceState
        dev._status.state = DeviceState.ACTIVE
        assert dev.update_season(30.0, T0 + timedelta(days=3)) == "heat"

    def test_one_band_serves_both_seasons(self):
        dev, _ = _unit()
        dev.comfort_target, dev.comfort_limit = 22.0, 25.0   # typed for cooling
        dev.update_season(27.0, T0)
        assert dev.comfort_limit == 25.0
        dev.update_season(2.0, T0 + timedelta(days=2))
        assert dev.hvac_mode == "heat" and dev.comfort_limit == 19.0
        fixed, _ = _unit(mode="cool")
        fixed.comfort_target, fixed.comfort_limit = 22.0, 25.0
        assert fixed.comfort_limit == 25.0

    @pytest.mark.asyncio
    async def test_the_start_sends_the_season(self):
        dev, hass = _unit()
        dev.update_season(8.0, T0)
        await dev.activate(1500.0)
        sent = hass.calls("set_hvac_mode", "climate.ac")
        assert sent and sent[0].args[2]["hvac_mode"] == "heat"

    @pytest.mark.asyncio
    async def test_no_season_sends_nothing(self):
        dev, hass = _unit()
        assert await dev.activate(1500.0) == 0.0
        assert not hass.services.async_call.await_args_list


class TestTheOutlookReusesWhatSemReads:
    def _host(self, forecast, now_c):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        host = SimpleNamespace(_temp_forecast=forecast, _OUTLOOK_HOURS=24,
                               _outdoor_temperature_or_none=lambda: now_c)
        return SEMCoordinator._outdoor_outlook_c(host)

    def test_the_mean_of_the_next_day(self):
        from homeassistant.util import dt as dt_util
        now = dt_util.now()
        rows = [(now + timedelta(hours=h), t, "hourly")
                for h, t in ((1, 10.0), (12, 20.0), (23, 12.0), (40, 99.0))]
        assert self._host(rows, 5.0) == pytest.approx(14.0)

    def test_no_forecast_reads_the_thermometer(self):
        assert self._host([], 7.5) == 7.5
        assert self._host(None, None) is None

    def test_the_stamp_writes_no_service(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        assert not calls(SEMCoordinator._stamp_outdoor_outlook, "async_call")
        assert not calls(SEMCoordinator._stamp_outdoor_outlook, "send")
        assert calls(SEMCoordinator._stamp_outdoor_outlook, "update_season")


# ── the setting reaches the pump, and the memo survives ───────────────────

class TestSettingAndMemo:
    def test_the_option_is_read_each_refresh(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        hass = _Hass()
        sc, hp = _pump(hass, action="off")
        hp.device_id = "heat_pump"
        host = SimpleNamespace(
            config={"heat_pump_step_down": "setpoint"},
            _surplus_controller=SimpleNamespace(
                get_device=lambda did: hp if did == "heat_pump" else None,
                regulation_offset=50.0, max_export_w=0.0))
        SEMCoordinator.refresh_runtime_config(host)
        assert hp.step_down_action == "setpoint"
        host.config = {"heat_pump_step_down": "nonsense"}
        SEMCoordinator.refresh_runtime_config(host)
        assert hp.step_down_action == "off"

    def test_the_memo_is_stored_and_seeded(self):
        from custom_components.solar_energy_management import _seed_step_down
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.storage import (
            SEMStorage,
        )
        store = SimpleNamespace(_energy_data={})
        assert SEMStorage.get_step_down_state(store) == {}
        hass = _Hass()
        hass.set("climate.hp", "heat", temperature=21.0)
        sc, hp = _pump(hass, action="setpoint", climate="climate.hp")
        hp._stepped_down, hp._step_restore_setpoint = True, 21.0
        host = SimpleNamespace(_surplus_controller=sc)
        memos = SEMCoordinator._step_down_memos(host)
        assert memos == {hp.device_id: {
            "action": "setpoint", "restore": 21.0, "target": None}}
        SEMStorage.set_step_down_state(store, memos)

        hass.set("climate.hp", "heat", temperature=19.0)   # still SEM's value
        _sc2, fresh = _pump(hass, action="setpoint", climate="climate.hp")
        coord = SimpleNamespace(_storage=SimpleNamespace(
            get_step_down_state=lambda: SEMStorage.get_step_down_state(store)))
        _seed_step_down(coord, fresh)
        assert fresh.is_stepped_down and fresh._step_restore_setpoint == 21.0
        # nothing stored: nothing believed
        _seed_step_down(SimpleNamespace(_storage=None), fresh)
        _sc3, other = _pump(hass)
        _seed_step_down(SimpleNamespace(_storage=SimpleNamespace(
            get_step_down_state=lambda: {})), other)
        assert not other.is_stepped_down


# ── every heat pump reads the setting; the mode is set in the editor ──────

class TestEveryPumpAndTheEditor:
    def test_every_heat_pump_reads_its_own_row_at_refresh(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        pumps = {did: HeatPumpController(_Hass(), device_id=did)
                 for did in ("heat_pump", "hp_cellar", "heat_pump_3")}
        sc = SimpleNamespace(get_device=pumps.get, regulation_offset=50.0,
                             max_export_w=0.0)
        host = SimpleNamespace(_surplus_controller=sc, config={
            "heat_pump_step_down": "block",
            "heat_pumps": [
                {"id": "hp_cellar", "heat_pump_step_down": "setpoint"},
                {"heat_pump_step_down": "block"},     # no id: heat_pump_3
            ]})
        SEMCoordinator.refresh_runtime_config(host)
        assert {d: p.step_down_action for d, p in pumps.items()} == {
            "heat_pump": "block", "hp_cellar": "setpoint", "heat_pump_3": "block"}
        host.config = {"heat_pumps": [{"id": "hp_cellar"}, {}]}
        SEMCoordinator.refresh_runtime_config(host)
        assert {p.step_down_action for p in pumps.values()} == {"off"}

    def _registry(self):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._device_goals = {}
        return reg, UnifiedDeviceRegistry

    def test_the_mode_is_a_goal_the_editor_sets(self):
        reg, cls = self._registry()
        assert "hvac_mode" in cls.GOAL_PROPERTIES
        dev, _ = _unit(mode="cool")
        reg._device_goals[dev.device_id] = {"hvac_mode": "by_forecast"}
        reg._apply_goals(dev)
        assert dev.hvac_setting == HVAC_BY_FORECAST
        reg._device_goals[dev.device_id] = {"hvac_mode": "heat"}
        reg._apply_goals(dev)
        assert dev.hvac_mode == "heat"

    def test_an_unknown_mode_and_a_switch_are_left_alone(self):
        reg, _cls = self._registry()
        dev, _ = _unit(mode="cool")
        reg._device_goals[dev.device_id] = {"hvac_mode": "warp"}
        reg._apply_goals(dev)
        assert dev.hvac_mode == "cool"
        from custom_components.solar_energy_management.devices.base import SwitchDevice
        plug = SwitchDevice(_Hass(), "plug", "Plug", rated_power=500.0,
                            entity_id="switch.plug")
        reg._device_goals["plug"] = {"hvac_mode": "heat"}
        reg._apply_goals(plug)
        assert not hasattr(plug, "hvac_setting")

    def test_the_service_takes_the_mode(self):
        from custom_components.solar_energy_management.devices.base import (
            CLIMATE_HVAC_MODES,
        )
        assert {"heat", "cool", HVAC_BY_FORECAST} <= set(CLIMATE_HVAC_MODES)


# ── review round: the season is kept, a stale memo is dropped ─────────────

def _cold_unit(room="20.5"):
    """A by-forecast unit with a band: Keep at 21 °C, run now past 19 °C."""
    hass = _Hass()
    hass.set("climate.ac", "off", current_temperature=float(room))
    dev = ClimateDevice(hass, "ac", "AC", rated_power=1500.0,
                        entity_id="climate.ac", hvac_mode=HVAC_BY_FORECAST)
    dev.comfort_target, dev.comfort_limit = 21.0, 19.0
    dev.control_mode = DeviceControlMode.SURPLUS
    return dev, hass


def _stamp(dev, *, stored=None, outlook=None):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    host = SimpleNamespace(
        _surplus_controller=SimpleNamespace(_devices={dev.device_id: dev}),
        _storage=SimpleNamespace(get_season_state=lambda: dict(stored or {})),
        _outdoor_outlook_c=lambda: outlook)
    SEMCoordinator._stamp_outdoor_outlook(host)
    return host


class TestTheSeasonIsKept:
    def test_a_restart_keeps_the_dead_band_and_the_dwell(self):
        """Yesterday heat, outlook 19 °C, restart: 19 °C is inside the dead
        band, so it stays heat — it used to decide anew at the middle."""
        old, _ = _unit()
        old.update_season(8.0, datetime.now() - timedelta(hours=20))
        memo = old.season_memo()
        assert memo["mode"] == "heat" and memo["since"]

        fresh, _ = _unit()
        _stamp(fresh, stored={"ac": memo}, outlook=19.0)
        assert fresh.hvac_mode == "heat"
        # …and the dwell goes on from the stored start, not from the restart
        _stamp(fresh, stored={"ac": memo}, outlook=23.5)
        assert fresh.hvac_mode == "heat", "20 h in: the day is not over"
        assert fresh._season_since == datetime.fromisoformat(memo["since"])

    def test_no_outlook_keeps_the_stored_mode(self):
        fresh, _ = _unit()
        _stamp(fresh, stored={"ac": {"mode": "cool", "since": None}}, outlook=None)
        assert fresh.hvac_mode == "cool" and fresh.start_refusal is None

    def test_a_bad_memo_is_no_memo(self):
        fresh, _ = _unit()
        _stamp(fresh, stored={"ac": {"mode": "warp"}}, outlook=None)
        assert fresh.start_refusal == "season"
        fixed, _ = _unit(mode="cool")
        assert fixed.restore_season({"mode": "heat", "since": None}) is False

    def test_the_season_is_stored_beside_the_other_device_state(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.storage import (
            SEMStorage,
        )
        dev, _ = _unit()
        dev.update_season(27.0, T0)
        host = SimpleNamespace(_surplus_controller=SimpleNamespace(
            _devices={"ac": dev, "plug": SimpleNamespace()}))
        memos = SEMCoordinator._season_memos(host)
        assert memos == {"ac": {"mode": "cool", "since": T0.isoformat()}}
        store = SimpleNamespace(_energy_data={})
        SEMStorage.set_season_state(store, memos)
        assert SEMStorage.get_season_state(store) == memos

    def test_no_season_and_too_cold_heats(self):
        """Nothing stored, no outlook, 18.5 °C against a 19 °C limit: the
        comfort floor starts it in heat. It used to be refused ahead of
        the floor, as a dead thermometer."""
        dev, hass = _cold_unit("18.5")
        _stamp(dev, outlook=None)
        assert dev.start_refusal is None and dev.hvac_mode == "heat"
        it = _intent(dev)
        assert (it.on, it.code) == (True, RC.LOAD_COMFORT_FLOOR)

    @pytest.mark.asyncio
    async def test_the_too_cold_start_sends_heat_and_stays_heat(self):
        dev, hass = _cold_unit("18.5")
        _stamp(dev, outlook=None)
        await dev.activate(1500.0)
        assert hass.calls("set_hvac_mode", "climate.ac")[0].args[2][
            "hvac_mode"] == "heat"
        from custom_components.solar_energy_management.devices.base import DeviceState
        dev._status.state = DeviceState.ACTIVE
        hass.set("climate.ac", "heat", current_temperature=19.5)
        _stamp(dev, outlook=21.0)          # the first outlook, mid-run
        assert dev.hvac_mode == "heat"

    def test_no_season_and_warm_enough_waits_with_its_own_reason(self):
        dev, _ = _cold_unit("20.5")
        _stamp(dev, outlook=None)
        it = _intent(dev, remaining_surplus_w=5000.0)
        assert (it.on, it.code) == (False, RC.LOAD_NO_SEASON)
        assert "sensor" not in it.reason


@pytest.mark.asyncio
class TestAStaleMemoIsDropped:
    MEMO = {"action": "setpoint", "restore": 21.0, "target": 19.0}

    def _fresh(self, live, action="setpoint", **attrs):
        hass = _Hass()
        hass.set("climate.hp", "heat", temperature=live, **attrs)
        sc, hp = _pump(hass, action=action, climate="climate.hp")
        return hass, sc, hp

    async def test_a_setpoint_the_user_changed_is_left_alone(self):
        """A crash between the release and the save leaves an old memo.
        The user has since set 22 °C: SEM must not write 21 °C over it."""
        hass, sc, hp = self._fresh(22.0)
        assert hp.restore_step_down(self.MEMO) is False
        assert not hp.is_stepped_down
        await _cycle(sc, 3, price=NORMAL)
        assert not hass.calls("set_temperature", "climate.hp")

    async def test_a_setpoint_still_sems_is_put_back(self):
        hass, sc, hp = self._fresh(19.0)
        assert hp.restore_step_down(self.MEMO) is True
        await _cycle(sc, price=NORMAL)
        assert [c.args[2]["temperature"]
                for c in hass.calls("set_temperature", "climate.hp")] == [21.0]

    async def test_the_devices_own_step_is_the_tolerance(self):
        hass, _sc, hp = self._fresh(19.4)            # default step 0.5
        assert hp.restore_step_down(self.MEMO) is True
        hass, _sc, hp = self._fresh(19.4, target_temp_step=0.1)
        assert hp.restore_step_down(self.MEMO) is False
        hass, _sc, hp = self._fresh("unknown")       # no reading: not believed
        assert hp.restore_step_down(self.MEMO) is False

    async def test_the_option_switched_off_still_puts_sems_value_back(self):
        hass, sc, hp = self._fresh(19.0, action="off")
        assert hp.restore_step_down(self.MEMO) is True
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert not hp.is_stepped_down
        assert [c.args[2]["temperature"]
                for c in hass.calls("set_temperature", "climate.hp")] == [21.0]

    async def test_the_option_switched_off_and_not_sems_writes_nothing(self):
        hass, sc, hp = self._fresh(22.0, action="off")
        assert hp.restore_step_down(self.MEMO) is False
        await _cycle(sc, 3, price=EXPENSIVE, buying=800.0)
        assert not hass.services.async_call.await_args_list

    async def test_the_memo_names_the_value_sem_wrote(self):
        hass, sc, hp = self._fresh(21.0)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert hp.step_down_memo() == self.MEMO


class TestTheOutlookAndDailyForecasts:
    def _outlook(self, rows, now_c=9.0):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        host = SimpleNamespace(_temp_forecast=rows, _OUTLOOK_HOURS=24,
                               _outdoor_temperature_or_none=lambda: now_c)
        return SEMCoordinator._outdoor_outlook_c(host)

    def test_a_days_row_counts_for_its_day(self):
        from homeassistant.util import dt as dt_util
        today = dt_util.start_of_local_day()
        rows = [(today, 12.0, "daily"),                      # today: (high+low)/2
                (today + timedelta(days=1), 16.0, "daily"),
                (today + timedelta(days=3), 40.0, "daily")]
        assert self._outlook(rows) == pytest.approx(14.0)

    def test_a_day_known_by_its_high_alone_is_not_the_outlook(self):
        from homeassistant.util import dt as dt_util
        today = dt_util.start_of_local_day()
        assert self._outlook([(today, 28.0, "daily_high")], now_c=9.0) == 9.0

    @pytest.mark.asyncio
    async def test_a_daily_forecast_without_a_low_is_marked(self):
        from unittest.mock import AsyncMock

        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        async def _call(domain, service, data, **_kw):
            if data["type"] == "hourly":
                raise ValueError("not offered")
            return {"weather.home": {"forecast": [
                {"datetime": "2026-11-11T00:00:00+01:00", "temperature": 28.0},
                {"datetime": "2026-11-12T00:00:00+01:00", "temperature": 20.0,
                 "templow": 10.0}]}}

        host = SimpleNamespace(
            hass=SimpleNamespace(
                services=SimpleNamespace(async_call=AsyncMock(side_effect=_call)),
                states=SimpleNamespace(get=lambda _e: SimpleNamespace(
                    attributes={"temperature_unit": "°C"}))),
            _forecast_weather_entity=lambda: "weather.home", _temp_forecast=[])
        await SEMCoordinator._refresh_temperature_forecast(host)
        assert [(t, kind) for _s, t, kind in host._temp_forecast] == [
            (28.0, "daily_high"), (15.0, "daily")]


@pytest.mark.asyncio
class TestOneWriteWhenAStartReplacesABlock:
    async def test_the_contacts_move_once(self):
        """Blocked (1:0), then a start: straight to boost (0:1) — two
        writes, one per contact. It used to pass through normal first."""
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        hass.services.async_call.reset_mock()
        await reconcile_load(hp, LoadIntent(True, 2000.0, "solar", "sun"),
                             controller=sc)
        assert hp.is_active and not hp.is_stepped_down
        assert hp.sg_ready_state is SGReadyState.BOOST
        assert len(hass.services.async_call.await_args_list) == 2
        assert _sg(hass) == ("off", "on")

    async def test_a_start_that_cannot_go_still_releases(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        hp._last_deactivated = datetime.now()        # inside its minimum pause
        hp._status.last_deactivated = hp._last_deactivated
        assert hp.can_activate() is False
        await reconcile_load(hp, LoadIntent(True, 2000.0, "solar", "sun"),
                             controller=sc)
        assert not hp.is_stepped_down and not hp.is_active
        assert hp.sg_ready_state is SGReadyState.NORMAL


# ── a pause (#1321) and a step-down ───────────────────────────────────────

PAUSE = {"heat_pump": {"action": "skip", "until": "23:00"}}
BOOST = {"heat_pump": {"action": "force", "until": "23:00"}}
NEAR = LoadManagementState.WARNING


async def _paused(sc, n=1, *, overrides=PAUSE, price=NORMAL, buying=0.0, peak=None):
    for _ in range(n):
        await sc.update(0.0, price_level=price, peak_state=peak,
                        grid_import_w=buying, is_night=True,
                        load_overrides=overrides)


@pytest.mark.asyncio
class TestAPauseAndAStepDown:
    async def test_a_pause_does_not_release_a_peak_step_down(self):
        """Stepped down for the peak, then paused: the plain off intent let
        layer 3 release it after the 900 s hold, the peak still near."""
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, peak=NEAR)
        assert hp.is_stepped_down
        await _paused(sc, 5, peak=NEAR)
        _served(hp)                                # the 900 s hold is over
        await _paused(sc, 30, peak=NEAR)
        assert hp.is_stepped_down and not hp.is_active
        assert not hass.calls("turn_off", "switch.sg1")
        assert len(hass.calls("turn_on", "switch.sg1")) == 1
        it = _intent(hp, peak_freeze=True, override="skip")
        assert not it.on and it.step_down and it.code == RC.LOAD_STEP_DOWN_PEAK

    async def test_the_peak_gone_the_pause_lets_it_go(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, peak=NEAR)
        _served(hp)
        await _paused(sc, 5)                       # paused, no peak
        assert not hp.is_stepped_down and not hp.is_active
        assert _intent(hp, override="skip").code == RC.LOAD_OVERRIDE_STOP

    async def test_a_pause_may_release_a_price_step_down(self):
        """A pause means SEM does nothing: the pump goes back to its own
        control once the hold is served."""
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, price=EXPENSIVE, buying=800.0)
        assert hp.is_stepped_down
        await _paused(sc, 3, price=EXPENSIVE, buying=800.0)
        assert hp.is_stepped_down, "inside its hold"
        _served(hp)
        await _paused(sc, 3, price=EXPENSIVE, buying=800.0)
        assert not hp.is_stepped_down and not hp.is_active
        it = _intent(hp, price_is_expensive=True, buying_w=800.0, override="skip")
        assert not it.on and not it.step_down and it.code == RC.LOAD_OVERRIDE_STOP

    async def test_with_the_option_off_a_pause_is_unchanged(self):
        hass = _Hass()
        sc, hp = _pump(hass, action="off")
        await _paused(sc, 5, peak=NEAR)
        assert not hp.is_stepped_down and not hp.is_active
        hass.services.async_call.assert_not_awaited()
        it = _intent(hp, peak_freeze=True, override="skip")
        assert not it.step_down and it.code == RC.LOAD_OVERRIDE_STOP

    async def test_a_boost_during_a_peak_step_down_does_not_start(self):
        hass = _Hass()
        sc, hp = _pump(hass)
        await _cycle(sc, peak=NEAR)
        _served(hp)
        await _paused(sc, 5, overrides=BOOST, peak=NEAR)
        assert hp.is_stepped_down and not hp.is_active
        assert _intent(hp, peak_freeze=True, override="force").code == RC.LOAD_STEP_DOWN_PEAK
