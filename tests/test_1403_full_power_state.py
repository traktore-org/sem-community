"""#1403 — by day, a full-current charge said "Battery assist".

A charger in "Always max", or one where you press "Start now", gets the
full current (``CHARGE_MAX``). The per-charger loop turned that intent into
``SOLAR_SUPER_CHARGING`` — "Solar mode - Battery assist" — and the charger
notice said "Bat+Sol". The grid often fed that charge, and the battery may
have given nothing. Real battery assist is ``CHARGE_AT_AMPS`` at set amps
and already read "Solar mode - Charging active".

Now ``CHARGE_MAX`` reads ``SOLAR_FULL_POWER`` — "Charging at full power" —
and the notice says "Full power". The state keeps the roles the old one
had: an active solar status and the flap hold of the notices.

The cycle tests run the real cycle (``CycleRig``): real devices, real
loop, real ``decide()``; only the day clock is set.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import textwrap
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.consts import states as states_mod
from custom_components.solar_energy_management.consts.states import (
    ChargingState as CS,
    get_status_message,
)
from custom_components.solar_energy_management.coordinator import plan_override as po
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.decide import (
    SOLAR_STATE_BY_INTENT,
    solar_state_from_decision,
)
from custom_components.solar_energy_management.coordinator import (
    notifications as notif_mod,
)
from custom_components.solar_energy_management.coordinator.types import SEMData

from .cycle_rig import CycleRig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSLATIONS = os.path.join(ROOT, "dashboard", "translations.json")

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "ev_power_sensor": "sensor.ev",
    "battery_capacity_kwh": 15.0,
    "battery_reserve_soc": 20,
}


def _charger(cid="zap", mode="always_max", **over):
    c = {
        "id": cid, "name": cid, "ev_min_current": 6, "ev_max_current": 16,
        "ev_phases": 3, "ev_voltage": 230,
        "ev_current_control_entity": f"number.{cid}_current",
        "ev_connected_sensor": f"binary_sensor.{cid}_connected",
        "ev_power_sensor": "sensor.ev",
        "charge_mode": mode, "ev_target_type": "kwh", "daily_ev_target": 20,
    }
    c.update(over)
    return c


def _day_rig(chargers, *, solar=2000, grid=8000, soc=30, ev=11000):
    """By day, little sun, the car drawing 11 kW from the grid — what a
    full-current charge looks like when the battery gives nothing."""
    states = {"sensor.solar": solar, "sensor.grid": grid, "sensor.batt": 0,
              "sensor.soc": soc, "sensor.ev": ev}
    for c in chargers:
        states[f"binary_sensor.{c['id']}_connected"] = "on"
        states[f"number.{c['id']}_current"] = 0
    rig = CycleRig(config=dict(WIRED), chargers=chargers, states=states)
    rig.coord.time_manager.is_night_mode = lambda: False
    return rig


def _amps_sent(rig, cid):
    return [c[2].get("value") for c in rig.calls
            if c[2].get("entity_id") == f"number.{cid}_current"]


def _translations():
    with open(TRANSLATIONS, encoding="utf-8") as f:
        return json.load(f)


# ── the real cycle ─────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestFullPowerByDay:

    async def test_always_max_says_full_power(self):
        """The reported case: Always max by day, the grid feeding the car."""
        rig = _day_rig([_charger()])
        res = await rig.tick()
        assert 16 in _amps_sent(rig, "zap")
        assert res["charger_zap_charging_state"] == CS.SOLAR_FULL_POWER
        assert str(res["charging_state"]) == CS.SOLAR_FULL_POWER
        assert res["charger_zap_charging_state"] != CS.SOLAR_SUPER_CHARGING

    async def test_start_now_says_full_power(self):
        """"Start now" on a Solar + cheapest hours charger by day."""
        rig = _day_rig([_charger(mode="solar_plus_cheap")])
        res = await rig.tick()
        assert res["charger_zap_charging_state"] != CS.SOLAR_FULL_POWER
        now = dt_util.now()
        rig.coord._plan_overrides = po.set_override(
            rig.coord._plan_overrides, "zap", "force",
            now + timedelta(hours=6), now)
        res = await rig.tick()
        assert "plan override — forced to charge" in res["charging_strategy"]
        assert 16 in _amps_sent(rig, "zap")
        assert res["charger_zap_charging_state"] == CS.SOLAR_FULL_POWER

    async def test_each_charger_reads_its_own_decision(self):
        """Two chargers: only the Always max one says full power."""
        rig = _day_rig([_charger("a"), _charger("b", mode="solar_only")],
                       solar=0, grid=11000)
        res = await rig.tick()
        assert res["charger_a_charging_state"] == CS.SOLAR_FULL_POWER
        assert res["charger_b_charging_state"] != CS.SOLAR_FULL_POWER


# ── the rule alone ─────────────────────────────────────────────────────

class TestTheRule:

    def test_every_intent_is_in_the_table(self):
        """A new intent must name its day state; the fallback would show it
        as "System ready" while it charges."""
        assert set(SOLAR_STATE_BY_INTENT) == set(ChargerIntent)

    @pytest.mark.parametrize("ceiling", [True, False])
    def test_no_intent_reads_battery_assist(self, ceiling):
        """No decision carries "the battery helps" as an intent."""
        for intent in ChargerIntent:
            state = solar_state_from_decision(
                intent, soc_ceiling_reached=ceiling)
            assert state in states_mod.STATUS_MESSAGES, intent
            assert state != CS.SOLAR_SUPER_CHARGING, intent

    def test_a_charging_intent_reads_charging(self):
        charging = {CS.SOLAR_CHARGING_ACTIVE, CS.SOLAR_FULL_POWER}
        for intent in ChargerIntent:
            sends = intent in (ChargerIntent.CHARGE_AT_AMPS,
                               ChargerIntent.CHARGE_MAX)
            assert (SOLAR_STATE_BY_INTENT[intent] in charging) is sends, intent

    def test_the_map(self):
        f = solar_state_from_decision
        assert f(ChargerIntent.CHARGE_MAX, soc_ceiling_reached=False) \
            == CS.SOLAR_FULL_POWER
        assert f(ChargerIntent.CHARGE_AT_AMPS, soc_ceiling_reached=False) \
            == CS.SOLAR_CHARGING_ACTIVE
        assert f(ChargerIntent.IDLE, soc_ceiling_reached=True) \
            == CS.SOLAR_TARGET_REACHED
        assert f(ChargerIntent.IDLE, soc_ceiling_reached=False) == CS.SOLAR_IDLE
        for intent in (ChargerIntent.DISABLE, ChargerIntent.RELEASE):
            # the ceiling only names an IDLE
            assert f(intent, soc_ceiling_reached=True) == CS.SOLAR_IDLE

    def test_the_loop_uses_the_rule(self):
        """AST pin: the day branch of the per-charger loop calls the rule
        and names no battery-assist state of its own."""
        src = textwrap.dedent(inspect.getsource(
            SEMCoordinator._async_update_data))
        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "solar_state_from_decision"]
        assert calls, "the loop no longer derives the day state from the rule"
        named = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "SOLAR_SUPER_CHARGING" not in named


# ── what the state says, and the roles it keeps ───────────────────────

class TestWhatItSays:

    def test_the_text_names_no_source(self):
        text = states_mod.STATUS_MESSAGES[CS.SOLAR_FULL_POWER]
        assert text == "Charging at full power"
        for word in ("battery", "solar", "grid"):
            assert word not in text.lower()

    @pytest.mark.parametrize("lang", sorted(_translations()))
    def test_the_sensor_text_in_each_language(self, lang):
        tr = _translations()[lang]
        hass = SimpleNamespace(config=SimpleNamespace(language=lang))
        assert get_status_message(CS.SOLAR_FULL_POWER, hass) \
            == tr["state_full_power"]
        if lang != "en":
            assert tr["state_full_power"] != _translations()["en"]["state_full_power"]
            assert tr["notif_charger_full_power"] \
                != _translations()["en"]["notif_charger_full_power"]

    def test_the_charger_notice_says_full_power(self):
        hass = MagicMock()
        hass.config.language = "en"
        nm = notif_mod.NotificationManager(hass, {"daily_ev_target": 10})
        msgs = nm._get_notification_messages(
            CS.SOLAR_FULL_POWER, {"calculated_current": 6})
        assert msgs["charger"] == "Full power"
        assert "mobile" not in msgs

    @pytest.mark.asyncio
    async def test_the_event_carries_the_charger_text(self):
        """The notification event read a key ("keba") nothing sets, so a
        state with only a charger text fired an empty message."""
        hass = MagicMock()
        hass.config.language = "en"
        nm = notif_mod.NotificationManager(
            hass, {"daily_ev_target": 10, "enable_charger_notifications": True})
        nm._charger_notify_checked = True
        nm._charger_notify_available = False
        nm._pending_state_per_charger["_fleet"] = CS.SOLAR_FULL_POWER
        nm._pending_state_since_per_charger["_fleet"] = -1e9  # flap hold over
        await nm.notify_state_change(CS.SOLAR_FULL_POWER, {"calculated_current": 6})
        fired = [c.args[1] for c in hass.bus.async_fire.call_args_list
                 if c.args and str(c.args[0]).endswith("_notification")]
        assert fired and fired[-1]["message"] == "Full power"

    def test_it_keeps_the_roles_of_the_old_state(self):
        assert CS.SOLAR_FULL_POWER in notif_mod._COOLDOWN_STATES
        d = SEMData()
        d.charging_state = CS.SOLAR_FULL_POWER
        assert d._get_solar_charging_status() == "active"
        assert d._get_night_charging_status() == "idle"


class TestEveryStateHasItsText:
    """Guard: a state SEM can show has an English text and a key that every
    language holds. A new state without them shows the bare value, or
    English to every user."""

    def _states(self):
        return {v for k, v in vars(CS).items()
                if k.isupper() and isinstance(v, str)}

    def test_every_state_has_text_and_key(self):
        for state in self._states():
            assert state in states_mod.STATUS_MESSAGES, state
            assert state in states_mod._STATE_TRANSLATION_KEYS, state

    def test_every_key_is_in_every_language(self):
        tr = _translations()
        for key in states_mod._STATE_TRANSLATION_KEYS.values():
            for lang, table in tr.items():
                assert key in table, f"{key} missing in {lang}"
