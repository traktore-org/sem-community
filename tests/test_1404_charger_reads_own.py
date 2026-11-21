"""#1404 — the charger notice and the SOC-cap Repair read the charger.

Three things about one charger used a value for all chargers:

1. The notice "Solar: {current}A" showed ``calculated_current``, the fleet
   budget sized from the first charger's config, on every charger. Two
   chargers each sent 6 A, and both notices said 13 A.
2. Every charger's notice went to the first display service found, so
   charger B's state showed on charger A's display.
3. The Repair "SOC target cannot be enforced" read the state from before
   the decision. An Always max charger at full power while the home
   battery was low read "Pause", and the Repair was cleared.

The cycle tests run the real cycle (``CycleRig``): real devices, real
loop, real ``decide()``; only the day clock is set.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.consts.states import (
    ChargingState as CS,
)
from custom_components.solar_energy_management.coordinator import (
    repair_issues as _ri,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.notifications import (
    NotificationManager,
    display_owner,
)

from .test_1403_full_power_state import _charger, _day_rig


def _capture_notices(rig):
    """Every ``notify_state_change`` the cycle makes, as
    ``(charger_id, state, data)``."""
    seen = []

    async def _cap(state, data, **kw):
        seen.append((kw.get("charger_id"), str(state), dict(data)))

    rig.coord._notification_manager.notify_state_change = _cap
    return seen


def _two_solar_chargers():
    """Two chargers sharing 9 kW of sun; each starts at 6 A. The fleet
    budget, sized from the first charger's config, is 13 A."""
    rig = _day_rig(
        [_charger("a", mode="solar_only", ev_power_sensor="sensor.a_ev"),
         _charger("b", mode="solar_only", ev_power_sensor="sensor.b_ev",
                  ev_phases=1)],
        solar=14000, grid=9000, soc=95, ev=0)
    rig.coord.config["ev_enable_delay_seconds"] = 0
    rig.hass.states.set("sensor.a_ev", 0)
    rig.hass.states.set("sensor.b_ev", 0)
    return rig


# ── 1. the amps in the notice ─────────────────────────────────────────

@pytest.mark.asyncio
class TestTheNoticeNamesThisChargersAmps:

    async def test_each_notice_names_its_own_amps(self):
        rig = _two_solar_chargers()
        seen = _capture_notices(rig)
        for _ in range(3):
            res = await rig.tick()
        fleet = int(res["calculated_current"])
        last = {cid: data for cid, _state, data in seen[-2:]}
        assert set(last) == {"a", "b"}
        for cid in ("a", "b"):
            assert res[f"charger_{cid}_charging_state"] == CS.SOLAR_CHARGING_ACTIVE
            own = int(res[f"charger_{cid}_commanded_current"])
            assert own >= 6
            assert last[cid]["calculated_current"] == own
        # the case: the fleet budget is not either charger's amps
        assert fleet not in (last["a"]["calculated_current"],
                             last["b"]["calculated_current"])

    async def test_the_watts_are_this_chargers_too(self):
        """The phone text "Solar charging started: 6A (4140W)" — the watts
        are what this charger's decision commands, on its own phases."""
        rig = _two_solar_chargers()
        seen = _capture_notices(rig)
        for _ in range(3):
            await rig.tick()
        last = {cid: data for cid, _state, data in seen[-2:]}
        assert last["a"]["available_power"] == pytest.approx(
            last["a"]["calculated_current"] * 3 * 230)
        assert last["b"]["available_power"] == pytest.approx(
            last["b"]["calculated_current"] * 1 * 230)

    async def test_the_watts_follow_the_phases_it_charges_on(self):
        """(review) After a 3 → 1 phase switch the watts are one phase's."""
        rig = _two_solar_chargers()
        rig.coord._phase_believed = {"a": 1}
        seen = _capture_notices(rig)
        for _ in range(3):
            await rig.tick()
        rig.coord._phase_believed = {"a": 1}
        await rig.tick()
        last = {cid: data for cid, _state, data in seen[-2:]}
        assert last["a"]["available_power"] == pytest.approx(
            last["a"]["calculated_current"] * 1 * 230)

    async def test_the_charger_text_says_its_own_amps(self):
        rig = _two_solar_chargers()
        seen = _capture_notices(rig)
        for _ in range(3):
            res = await rig.tick()
        nm = rig.coord._notification_manager
        cid, state, data = seen[-1]
        text = nm._get_notification_messages(state, data)["charger"]
        own = int(res[f"charger_{cid}_commanded_current"])
        assert text == f"Solar: {own}A"
        assert f"{int(res['calculated_current'])}A" not in text

    async def test_watch_only_names_the_amps_sem_decided(self):
        """When SEM only watches, the state reads the decision, so the
        amps do too — not the zeroed setpoint, not the fleet budget."""
        rig = _two_solar_chargers()
        rig.coord._observer_mode = True
        seen = _capture_notices(rig)
        for _ in range(3):
            res = await rig.tick()
        assert res["charger_a_commanded_current"] == 0      # nothing written
        last = {cid: data for cid, _state, data in seen[-2:]}
        assert res["charger_a_charging_state"] == CS.SOLAR_CHARGING_ACTIVE
        assert last["a"]["calculated_current"] == rig.coord._last_commanded_amps_per_charger["a"]
        assert last["a"]["calculated_current"] >= 6

    async def test_an_idle_charger_names_no_amps(self):
        rig = _day_rig([_charger("a", mode="off"), _charger("b", mode="always_max")])
        seen = _capture_notices(rig)
        await rig.tick()
        last = {cid: data for cid, _state, data in seen[-2:]}
        assert last["a"]["calculated_current"] == 0
        assert last["a"]["available_power"] == 0.0


# ── 2. the display a notice goes to ───────────────────────────────────

IDS = {"a": frozenset({"keba"}), "b": frozenset({"easee", "number"})}


class TestWhoseDisplay:

    def test_one_charger_owns_every_display(self):
        assert display_owner("keba", {"z": frozenset({"zaptec"})}) == "z"
        assert display_owner("anything", {"z": frozenset()}) == "z"

    def test_a_display_belongs_to_the_charger_it_is_named_for(self):
        assert display_owner("keba", IDS) == "a"
        assert display_owner("keba_display", IDS) == "a"
        assert display_owner("easee_garage", IDS) == "b"

    def test_go_e_names_match_both_ways(self):
        ids = {"g": frozenset({"goecharger_mqtt"}), "k": frozenset({"keba"})}
        assert display_owner("go_echarger_1", ids) == "g"
        assert display_owner("goecharger", ids) == "g"

    def test_two_chargers_of_one_brand_own_no_display(self):
        ids = {"a": frozenset({"keba"}), "b": frozenset({"keba"})}
        assert display_owner("keba", ids) is None

    def test_a_display_of_no_charger_is_nobodys(self):
        assert display_owner("zaptec", IDS) is None
        ids = {"a": frozenset(), "b": frozenset()}
        assert display_owner("keba", ids) is None


def _nm(services, identities):
    hass = MagicMock()
    hass.config.language = "en"
    hass.services.async_services = MagicMock(
        return_value={"notify": {s: None for s in services}})
    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_call = AsyncMock()
    nm = NotificationManager(hass, {"enable_charger_notifications": True})
    nm.charger_identities = lambda: identities
    return nm, hass


def _sent(hass):
    return [(c.args[1], c.args[2]["message"])
            for c in hass.services.async_call.await_args_list
            if c.args[0] == "notify"]


@pytest.mark.asyncio
class TestTheNoticeGoesToItsChargersDisplay:

    async def test_each_charger_to_its_own_display(self):
        nm, hass = _nm(["keba", "easee_garage"], IDS)
        await nm._send_charger_notification("A text", charger_id="a")
        await nm._send_charger_notification("B text", charger_id="b")
        assert _sent(hass) == [("keba", "A text"), ("easee_garage", "B text")]

    async def test_no_display_of_its_own_sends_nothing(self):
        """The case: one KEBA display, two chargers. Charger B's state
        used to show on the KEBA."""
        nm, hass = _nm(["keba"], IDS)
        await nm._send_charger_notification("B text", charger_id="b")
        assert _sent(hass) == []
        await nm._send_charger_notification("A text", charger_id="a")
        assert _sent(hass) == [("keba", "A text")]

    async def test_a_quiet_display_says_why_once(self, caplog):
        nm, hass = _nm(["keba"], IDS)
        with caplog.at_level("INFO"):
            for _ in range(3):
                await nm._send_charger_notification("B text", charger_id="b")
        lines = [r for r in caplog.records
                 if "no display of its own" in r.getMessage()]
        assert len(lines) == 1 and lines[0].levelname == "INFO"
        assert "notify.keba" in lines[0].getMessage()

    async def test_one_charger_keeps_its_display(self):
        nm, hass = _nm(["keba"], {"z": frozenset()})
        await nm._send_charger_notification("Z text", charger_id="z")
        await nm._send_charger_notification("fleet text")
        assert _sent(hass) == [("keba", "Z text"), ("keba", "fleet text")]

    async def test_a_fleet_notice_about_no_charger_goes_nowhere(self):
        nm, hass = _nm(["keba"], IDS)
        await nm._send_charger_notification("fleet text")
        assert _sent(hass) == []

    async def test_no_charger_list_keeps_the_first_display(self):
        nm, hass = _nm(["keba"], {})
        await nm._send_charger_notification("text", charger_id="a")
        assert _sent(hass) == [("keba", "text")]

    async def test_the_state_change_names_its_charger(self):
        nm, hass = _nm(["keba", "easee_garage"], IDS)
        nm._pending_state_per_charger["b"] = CS.SOLAR_FULL_POWER
        nm._pending_state_since_per_charger["b"] = -1e9
        await nm.notify_state_change(
            CS.SOLAR_FULL_POWER, {"battery_soc": 50},
            charger_id="b", charger_name="Garage")
        assert _sent(hass) == [("easee_garage", "Full power")]

    async def test_the_stand_down_notice_names_its_charger(self):
        nm, hass = _nm(["keba"], IDS)
        await nm.notify_charger_stand_down(
            charger_id="b", charger_name="Garage", power_w=4000, minutes=30)
        assert _sent(hass) == []
        await nm.notify_charger_stand_down(
            charger_id="a", charger_name="KEBA", power_w=4000, minutes=30)
        assert _sent(hass) == [("keba", "SEM stood down")]


@pytest.mark.asyncio
class TestTheCoordinatorNamesEachCharger:

    async def test_the_manager_asks_the_coordinator(self):
        rig = _day_rig([
            _charger("a", charger_service="keba.set_current"),
            _charger("b")])
        nm = rig.coord._notification_manager
        ids = nm.charger_identities()
        assert set(ids) == {"a", "b"}
        assert "keba" in ids["a"]
        assert "keba" not in ids["b"]

    async def test_the_integration_of_each_entity_counts(self):
        rig = _day_rig([_charger("a"), _charger("b")])
        owners = {"number.a_current": "keba", "number.b_current": "easee"}
        rig.coord._sensor_reader._owner_platform = owners.get
        ids = rig.coord._charger_identities()
        assert "keba" in ids["a"] and "easee" in ids["b"]
        assert display_owner("keba", ids) == "a"
        assert display_owner("easee_x", ids) == "b"


# ── 3. the SOC-cap Repair ─────────────────────────────────────────────

def _soc_rig():
    """Two chargers by day; the home battery at 20 %. The fleet state is
    "Pause: battery low", and the Always max charger, set to stop at 80 %
    of a car that reports no level, charges at full power."""
    rig = _day_rig([
        _charger("a", mode="solar_only"),
        _charger("b", mode="always_max", ev_target_type="soc",
                 ev_target_soc=80, vehicle_soc_entity="sensor.car_soc")],
        solar=2000, grid=8000, soc=20, ev=11000)
    rig.hass.states.set("sensor.car_soc", "unavailable")
    return rig


@pytest.mark.asyncio
class TestTheRepairReadsThisChargersDecision:

    async def test_full_power_with_a_low_battery_raises(self):
        """The case: it used to read the fleet's "Pause" and clear."""
        rig = _soc_rig()
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it, \
                patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
            res = await rig.tick()
        # the fleet state waits for the battery; it does not charge
        assert res["charging_state"] in (
            CS.SOLAR_PAUSE_LOW_BATTERY, CS.SOLAR_WAITING_BATTERY_PRIORITY)
        assert res["charger_b_charging_state"] == CS.SOLAR_FULL_POWER
        raised = [c.args[1] for c in raise_it.call_args_list]
        cleared = [c.args[1] for c in clear_it.call_args_list]
        assert "b" in raised
        assert "b" not in cleared

    async def test_a_real_level_clears_it(self):
        rig = _soc_rig()
        rig.hass.states.set("sensor.car_soc", 55)
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it, \
                patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
            await rig.tick()
        assert "b" not in [c.args[1] for c in raise_it.call_args_list]
        assert "b" in [c.args[1] for c in clear_it.call_args_list]

    async def test_an_unplugged_car_clears_it(self):
        rig = _soc_rig()
        rig.coord._boot_monotonic = None    # past the start-up hold of the plug
        await rig.tick()
        rig.hass.states.set("binary_sensor.b_connected", "off")
        rig.hass.states.set("sensor.ev", 0)
        for _ in range(6):     # the unplug is confirmed over a few cycles
            await rig.tick()
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it, \
                patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
            await rig.tick()
        assert rig.coord._last_ev_connected_per_charger["b"] is False
        assert "b" not in [c.args[1] for c in raise_it.call_args_list]
        assert "b" in [c.args[1] for c in clear_it.call_args_list]


@pytest.mark.asyncio
class TestTheRepairReadsThisChargersOwnLevel:

    async def test_a_dark_own_sensor_is_no_level(self):
        """(review) The flat sensor is car A's. With charger b's own
        sensor dark, b used to read car A's 55 % and clear its Repair."""
        rig = _soc_rig()
        rig.coord.config["vehicle_soc_entity"] = "sensor.car_a_soc"
        rig.hass.states.set("sensor.car_a_soc", 55)
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it, \
                patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
            await rig.tick()
        assert "b" in [c.args[1] for c in raise_it.call_args_list]
        assert "b" not in [c.args[1] for c in clear_it.call_args_list]

    async def test_a_dark_own_sensor_plans_from_no_level(self):
        """The same seed sized charger b's plan from car A's level. With
        no level the plan counts the full pack, as documented."""
        rig = _soc_rig()
        rig.coord.config["vehicle_soc_entity"] = "sensor.car_a_soc"
        rig.hass.states.set("sensor.car_a_soc", 55)
        seen = []
        real = rig.coord._calculate_remaining_need

        def _spy(energy, vehicle_soc=None, charger_cfg=None, bound="min"):
            seen.append(((charger_cfg or {}).get("id"), vehicle_soc))
            return real(energy, vehicle_soc, charger_cfg, bound)

        rig.coord._calculate_remaining_need = _spy
        await rig.tick()
        assert ("b", None) in seen
        assert ("b", 55.0) not in seen
        rig.hass.states.set("sensor.car_soc", 61)
        seen.clear()
        await rig.tick()
        assert ("b", 61.0) in seen

    async def test_a_charger_with_no_sensor_of_its_own_reads_the_flat_one(self):
        """Unchanged: one charger, its level only in the flat setting."""
        rig = _day_rig([_charger("b", mode="always_max", ev_target_type="soc",
                                 ev_target_soc=80)],
                       solar=2000, grid=8000, soc=20, ev=11000)
        rig.coord.config["vehicle_soc_entity"] = "sensor.car_soc"
        rig.hass.states.set("sensor.car_soc", 55)
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it, \
                patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
            await rig.tick()
        assert "b" not in [c.args[1] for c in raise_it.call_args_list]
        assert "b" in [c.args[1] for c in clear_it.call_args_list]

    async def test_off_clears_it(self):
        """(review) Off charges nothing, so there is nothing to enforce. A
        pause keeps the Repair; Off does not."""
        rig = _soc_rig()
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it:
            await rig.tick()
        assert "b" in [c.args[1] for c in raise_it.call_args_list]
        rig.coord.config["ev_chargers"][1]["charge_mode"] = "off"
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it, \
                patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
            res = await rig.tick()
        assert res["charger_b_charging_state"] != CS.SOLAR_FULL_POWER
        assert "b" not in [c.args[1] for c in raise_it.call_args_list]
        assert "b" in [c.args[1] for c in clear_it.call_args_list]


class _Coord:
    _maybe_warn_soc_cap = SEMCoordinator._maybe_warn_soc_cap
    _resolve_target = SEMCoordinator._resolve_target
    SOLAR_CHARGING_STATES = SEMCoordinator.SOLAR_CHARGING_STATES

    def __init__(self, connected=True):
        self.hass = MagicMock()
        self.config = {"ev_target_type": "soc"}
        self._last_ev_connected_per_charger = {"b": connected}


CFG = {"name": "Garage", "ev_target_type": "soc", "ev_target_soc": 80}


def _verdict(coord, cfg, soc, state):
    with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it, \
            patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
        coord._maybe_warn_soc_cap("b", cfg, soc, state)
    return raise_it.call_count, clear_it.call_count


class TestTheRepairDoesNotFollowTheClouds:

    @pytest.mark.parametrize("state", [
        CS.SOLAR_IDLE, CS.SOLAR_PAUSE_LOW_BATTERY,
        CS.SOLAR_WAITING_BATTERY_PRIORITY, CS.NIGHT_CHARGING_ACTIVE,
        CS.TARIFF_WAITING_FOR_CHEAP])
    def test_a_pause_keeps_it(self, state):
        """Still a percent target, still no level, still a car: the
        Repair is still true. It used to clear and come back with every
        cloud."""
        assert _verdict(_Coord(), CFG, None, state) == (0, 0)

    @pytest.mark.parametrize("state", [
        CS.SOLAR_CHARGING_ACTIVE, CS.SOLAR_FULL_POWER, CS.SOLAR_MIN_PV])
    def test_a_charge_raises_it(self, state):
        assert _verdict(_Coord(), CFG, None, state) == (1, 0)

    @pytest.mark.parametrize("state", [CS.SOLAR_IDLE, CS.SOLAR_CHARGING_ACTIVE])
    def test_off_clears_it(self, state):
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it, \
                patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
            _Coord()._maybe_warn_soc_cap("b", CFG, None, state, mode_off=True)
        assert (raise_it.call_count, clear_it.call_count) == (0, 1)

    @pytest.mark.parametrize("state", [CS.SOLAR_CHARGING_ACTIVE, CS.SOLAR_IDLE])
    def test_what_ends_it_clears_it(self, state):
        assert _verdict(_Coord(), CFG, 61.0, state) == (0, 1)
        assert _verdict(_Coord(connected=False), CFG, None, state) == (0, 1)
        kwh = {"name": "Garage", "ev_target_type": "kwh"}
        assert _verdict(_Coord(), kwh, None, state) == (0, 1)


def _loop_source() -> str:
    return textwrap.dedent(inspect.getsource(SEMCoordinator._async_update_data))


class TestTheCallReadsTheDecision:

    def test_the_repair_check_runs_once_after_the_day_state_rule(self):
        tree = ast.parse(_loop_source())
        lines = {"soc": [], "rule": []}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name)):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name == "_maybe_warn_soc_cap":
                    lines["soc"].append(node.lineno)
                elif name == "solar_state_from_decision":
                    lines["rule"].append(node.lineno)
        assert len(lines["soc"]) == 1, lines
        assert lines["rule"] and lines["soc"][0] > max(lines["rule"]), lines
