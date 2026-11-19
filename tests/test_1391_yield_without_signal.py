"""#1391 — "Yes, SEM yields" with no signal picked: SEM yields all the time.

The reporter set a Zaptec to "Controlled by another party: Yes, SEM yields"
and left the signal field empty. The book read the empty field as "nobody
steers", so SEM kept writing: the decision log showed "SEM starts charging"
with 6 → 8 → … → 16 A, and the card said the car did not start.

Pinned here: an empty signal in yield mode yields from the first look (a
charger and the battery); observe and a picked-but-missing signal keep the
#1079 rules; a yielded charger's decision is SEM's own idle at 0 A with its
own sentence, its start ladder is forgotten, and the phase guard's stop
(#1381) still reaches it; the real setup, from the card's save to the cycle,
sends the charger nothing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    reason_codes as RC,
)
from custom_components.solar_energy_management.coordinator.active_phase_guard import (
    ActivePhaseGuard,
)
from custom_components.solar_energy_management.coordinator.charge_stability import (
    ChargeStability,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
    commanded_power_w,
    solar_commitment_w,
)
from custom_components.solar_energy_management.coordinator.external_control import (
    HOLD_S,
    MODE_OBSERVE,
    MODE_YIELD,
    ExternalControlBook,
    Spec,
    yielded_charger_decision,
)

NOW = datetime(2026, 11, 19, 21, 23, tzinfo=timezone.utc)


def _hass(**states):
    hass = MagicMock()
    hass.states.get = lambda eid: (
        SimpleNamespace(state=states[eid], attributes={"friendly_name": "Tibber"})
        if eid in states else None)
    return hass


# ── the book ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestNoSignal:
    def test_yield_with_no_signal_yields_from_the_first_look(self):
        book = ExternalControlBook()
        specs = {"charger:c1": Spec(MODE_YIELD, "", "")}
        book.update(_hass(), specs, 0.0, NOW)
        assert book.yielding("charger:c1")
        for t in (30.0, HOLD_S * 3):
            book.update(_hass(), specs, t, NOW)
            assert book.yielding("charger:c1")
        assert book.line("charger:c1", "Zaptec") == (
            "Zaptec: controlled by another party since 21:23 — SEM yielding")
        assert book.rows()[0]["steered"] is True

    def test_a_blank_signal_is_no_signal(self):
        book = ExternalControlBook()
        book.update(_hass(), {"charger:c1": Spec(MODE_YIELD, "  ", "")}, 0.0, NOW)
        assert book.yielding("charger:c1")

    def test_the_battery_too(self):
        book = ExternalControlBook()
        book.update(_hass(), {"battery": Spec(MODE_YIELD, "", "")}, 0.0, NOW)
        assert book.yielding("battery")

    def test_observe_needs_no_signal_and_never_yields(self):
        book = ExternalControlBook()
        book.update(_hass(), {"charger:c1": Spec(MODE_OBSERVE, "", "")}, 0.0, NOW)
        assert not book.yielding("charger:c1")
        assert book.rows()[0]["steered"] is False

    def test_a_picked_signal_that_is_not_there_yet_is_still_not_steered(self):
        """#1079's restart rule stays: a signal that cannot be read changes
        nothing. Only a field left empty means "all the time"."""
        book = ExternalControlBook()
        book.update(_hass(), {"charger:c1": Spec(MODE_YIELD, "binary_sensor.x", "")},
                    0.0, NOW)
        assert not book.yielding("charger:c1")

    def test_a_signal_picked_later_takes_over_after_the_hold(self):
        book = ExternalControlBook()
        book.update(_hass(), {"charger:c1": Spec(MODE_YIELD, "", "")}, 0.0, NOW)
        picked = {"charger:c1": Spec(MODE_YIELD, "binary_sensor.x", "Tibber")}
        off = _hass(**{"binary_sensor.x": "off"})
        book.update(off, picked, 10.0, NOW)
        assert book.yielding("charger:c1")
        book.update(off, picked, 10.0 + HOLD_S, NOW)
        assert not book.yielding("charger:c1")

    def test_the_coordinator_reads_an_unset_signal_as_no_signal(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = MagicMock()
        c.hass = _hass()
        c.config = {"ev_chargers": [{"id": "zaptec", "external_control_mode": "yield"}],
                    "battery_external_control_mode": "yield"}
        c._external_control = ExternalControlBook()
        c._observer_mode = False
        dev = SimpleNamespace(external_yield=False)
        c._ev_devices = {"zaptec": dev}
        c._charger_reconcilers = {}
        c._live_battery_adapters = lambda: []
        c._external_control_specs = lambda: SEMCoordinator._external_control_specs(c)
        SEMCoordinator._refresh_external_control(c)
        assert SEMCoordinator.external_yielding(c, "charger:zaptec") is True
        assert SEMCoordinator.external_yielding(c, "battery") is True
        assert dev.external_yield is True


# ── the yielded decision ─────────────────────────────────────────────────

def _charge(amps=16):
    return ChargerDecision(
        charger_id="zaptec", mode="solar_cheap", intent=ChargerIntent.CHARGE_AT_AMPS,
        commanded_amps=amps, budget_w=11000.0, reason="cheap hour",
        reason_code=RC.CHARGER_START, redirect_w=900.0, assist_w=1200.0)


@pytest.mark.unit
class TestYieldedDecision:
    def test_it_is_an_idle_at_zero_with_its_own_sentence(self):
        d = yielded_charger_decision(_charge())
        assert d.intent is ChargerIntent.IDLE
        assert d.commanded_amps == 0
        assert d.reason_code == RC.CHARGER_YIELDED
        assert d.reason_params == {}
        assert "another party" in d.reason and "cheap hour" in d.reason

    def test_it_takes_no_power_from_the_next_device(self):
        d = yielded_charger_decision(_charge())
        kw = dict(phases=3, voltage=230.0, max_current_a=16)
        assert commanded_power_w(d, **kw) == 0
        assert solar_commitment_w(d, **kw) == 0
        assert d.redirect_w == 0.0 and d.assist_w == 0.0 and d.budget_w == 0.0

    def test_the_phase_guard_still_stops_it_over_the_limit(self):
        """#1381: the guard's stop is the one write a yield lets through.
        The yielded IDLE still becomes that stop while a phase is over."""
        from .test_1381_phase_guard_yield import _snapshot
        g = ActivePhaseGuard()
        g.update(_snapshot(31.2), {"phase_guard_enabled": True,
                                   "phase_guard_enforcement_enabled": True})
        d = g.filter_decision(yielded_charger_decision(_charge()))
        assert d.reason_code == RC.CHARGER_PHASE_STOP
        assert g.yield_override_reason(d) == "phase L2 at 31.2 A > 25.0 A"


@pytest.mark.unit
class TestStartLadderForgotten:
    def test_stand_aside_clears_the_declined_backoff(self):
        s = ChargeStability()
        s._giveup_streak["zaptec"] = 2
        s._giveup_backoff_until["zaptec"] = 9e9
        s._start_offer["zaptec"] = 14
        s._start_since["zaptec"] = 1.0
        s._sem_session.add("zaptec")
        s._session_stops["zaptec"] = 3
        s.stand_aside("zaptec")
        assert "zaptec" not in s._giveup_streak
        assert "zaptec" not in s._giveup_backoff_until
        assert "zaptec" not in s._start_offer
        assert "zaptec" not in s._sem_session
        assert s._session_stops["zaptec"] == 3      # the box's own count

    def _coord(self, *, yielding, observer=False):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = MagicMock()
        c._observer_mode = observer
        c.external_yielding = lambda key: yielding and key == "charger:zaptec"
        c._yields_charger = lambda cid: SEMCoordinator._yields_charger(c, cid)
        c._charge_stability = MagicMock()
        c._charge_stability.filter.side_effect = lambda d, *a, **k: d
        c._charge_stability_kwargs = lambda: {}
        return c, SEMCoordinator

    def test_a_yielded_charger_skips_the_ladder(self):
        c, C = self._coord(yielding=True)
        d = C._yield_or_stabilise(c, "zaptec", _charge(), None, None, 5.0)
        c._charge_stability.filter.assert_not_called()
        c._charge_stability.stand_aside.assert_called_once_with("zaptec")
        assert d.reason_code == RC.CHARGER_YIELDED

    @pytest.mark.parametrize("yielding,observer", [(False, False), (True, True)])
    def test_otherwise_the_ladder_runs(self, yielding, observer):
        c, C = self._coord(yielding=yielding, observer=observer)
        d = C._yield_or_stabilise(c, "zaptec", _charge(), None, None, 5.0)
        c._charge_stability.filter.assert_called_once()
        c._charge_stability.stand_aside.assert_not_called()
        assert d.reason_code == RC.CHARGER_START


# ── the real setup: the card's save, then a cycle ────────────────────────

async def _start(hass, sem_config_entry, mode):
    """The real setup, observer mode off, a car on an always_max charger,
    the charger's mode for another party set to ``mode`` with no signal."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.solar_energy_management.const import DOMAIN
    from .test_services_real import _seed_sem_input_sensors, _setup_sem

    _seed_sem_input_sensors(hass)
    hass.states.async_set("binary_sensor.test_ev_connected", "on")
    hass.states.async_set("binary_sensor.test_ev_charging", "off")
    hass.states.async_set("number.test_charger_current", "6",
                          {"min": 0, "max": 16, "step": 1})
    data = json.loads(json.dumps(dict(sem_config_entry.data)))
    data["observer_mode"] = False
    data["ev_chargers"][0]["charge_mode"] = "always_max"
    if mode:
        data["ev_chargers"][0]["external_control_mode"] = mode
    entry = MockConfigEntry(domain=DOMAIN, version=sem_config_entry.version,
                            minor_version=sem_config_entry.minor_version,
                            data=data, options={})
    # The number component replaces a mock service once it loads, so the
    # writes are counted where every service call is announced.
    writes = []
    hass.bus.async_listen(
        "call_service",
        lambda e: writes.append(SimpleNamespace(data=e.data["service_data"]))
        if (e.data.get("domain"), e.data.get("service")) == ("number", "set_value")
        else None)
    await _setup_sem(hass, entry)
    coord = entry.runtime_data
    for _ in range(3):
        await coord.async_refresh()
        await hass.async_block_till_done()
    return entry, coord, writes


async def _unload(hass, entry):
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_premise_without_the_setting_sem_drives_the_charger(
        sem_real_hass, sem_config_entry):
    entry, coord, writes = await _start(sem_real_hass, sem_config_entry, None)
    try:
        assert coord._observer_mode is False
        assert [w.data["value"] for w in writes] == [16]
        assert coord.data.get("charging_strategy_reason_code") != RC.CHARGER_YIELDED
    finally:
        await _unload(sem_real_hass, entry)


@pytest.mark.asyncio
async def test_yield_with_no_signal_sends_the_charger_nothing(
        sem_real_hass, sem_config_entry):
    """The reporter's setting. Before the fix the empty signal read as
    "nobody steers" and the same 16 A went out."""
    entry, coord, writes = await _start(sem_real_hass, sem_config_entry, "yield")
    try:
        assert coord.external_yielding("charger:ev_charger") is True
        assert writes == [], [w.data for w in writes]
        assert coord.data.get("charging_strategy_reason_code") == RC.CHARGER_YIELDED
    finally:
        await _unload(sem_real_hass, entry)


@pytest.mark.asyncio
async def test_observe_with_no_signal_still_drives(sem_real_hass, sem_config_entry):
    entry, coord, writes = await _start(sem_real_hass, sem_config_entry, "observe")
    try:
        assert [w.data["value"] for w in writes] == [16]
    finally:
        await _unload(sem_real_hass, entry)


@pytest.mark.asyncio
async def test_the_cards_save_reaches_the_cycle(sem_real_hass, sem_config_entry):
    """The card writes the mode into the charger's entry and no signal,
    through ``set_option``. The next cycle yields."""
    from custom_components.solar_energy_management.const import DOMAIN
    hass = sem_real_hass
    entry, coord, writes = await _start(hass, sem_config_entry, None)
    try:
        chargers = json.loads(json.dumps(
            {**entry.data, **entry.options}["ev_chargers"]))
        chargers[0]["external_control_mode"] = "yield"   # the card's one write
        await hass.services.async_call(
            DOMAIN, "set_option", {"options": {"ev_chargers": chargers}},
            blocking=True)
        await hass.async_block_till_done()
        coord = entry.runtime_data
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert coord.config["ev_chargers"][0].get("external_control_mode") == "yield"
        assert coord.external_yielding("charger:ev_charger") is True
        assert coord._ev_devices["ev_charger"].external_yield is True
        assert coord.data.get("charging_strategy_reason_code") == RC.CHARGER_YIELDED
    finally:
        await _unload(hass, entry)


# ── two chargers: the yielded one's real draw is not the next one's sun ──

async def _two_chargers(hass, base, *, left_draw_w):
    """8 kW of sun, a 1 kW house, the left charger yielded (no signal) and
    first in the order, the right one on sun only and plugged in."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from .test_services_real import _seed_sem_input_sensors, _setup_sem

    _seed_sem_input_sensors(hass)
    hass.states.async_set("sensor.test_solar_power", "8000", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.test_battery_soc", "95", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", str(7000 - left_draw_w),
                          {"unit_of_measurement": "W"})
    for side, draw in (("left", left_draw_w), ("right", 0)):
        hass.states.async_set(f"sensor.test_wb_{side}_charging_power", str(draw),
                              {"unit_of_measurement": "W"})
        hass.states.async_set(f"number.test_wb_{side}_max_current", "6",
                              {"unit_of_measurement": "A", "min": 0, "max": 16, "step": 1})
        hass.states.async_set(f"binary_sensor.test_wb_{side}_cable_connected", "on")
        hass.states.async_set(f"sensor.test_wb_{side}_status",
                              "charging" if draw else "connected")

    def _shape(chargers):
        out = json.loads(json.dumps(chargers))
        for c in out:
            c["charge_mode"] = "solar_only"
            if c["id"] == "ev_charger":
                c["ev_surplus_priority"] = 1
                c["external_control_mode"] = "yield"
            else:
                c["ev_surplus_priority"] = 9
        return out

    data = json.loads(json.dumps(dict(base.data)))
    data["observer_mode"] = False
    data["ev_enable_delay_seconds"] = 0
    data["solar_production_sensor"] = "sensor.test_solar_power"
    if "ev_chargers" in data:
        data["ev_chargers"] = _shape(data["ev_chargers"])
    options = json.loads(json.dumps(dict(base.options)))
    if "ev_chargers" in options:
        options["ev_chargers"] = _shape(options["ev_chargers"])
    entry = MockConfigEntry(domain=base.domain, version=base.version,
                            minor_version=base.minor_version, data=data,
                            options=options)
    await _setup_sem(hass, entry)
    coord = entry.runtime_data
    for _ in range(4):
        await coord.async_refresh()
        await hass.async_block_till_done()
    return entry, coord


@pytest.mark.asyncio
async def test_premise_the_sun_is_enough_for_the_second_charger(
        sem_real_hass, sem_multi_wallbox_config_entry):
    entry, coord = await _two_chargers(
        sem_real_hass, sem_multi_wallbox_config_entry, left_draw_w=0)
    try:
        assert coord.external_yielding("charger:ev_charger") is True
        assert coord._last_commanded_amps_per_charger.get("ev_charger") == 0
        assert coord._last_commanded_amps_per_charger.get("ev_charger_1", 0) >= 6
    finally:
        await _unload(sem_real_hass, entry)


@pytest.mark.asyncio
async def test_the_yielded_chargers_draw_is_not_offered_again(
        sem_real_hass, sem_multi_wallbox_config_entry):
    """The other party charges the left car at 7 kW from the same sun. The
    right charger may not start on those 7 kW as well."""
    entry, coord = await _two_chargers(
        sem_real_hass, sem_multi_wallbox_config_entry, left_draw_w=7000)
    try:
        assert coord.external_yielding("charger:ev_charger") is True
        assert coord._last_commanded_amps_per_charger.get("ev_charger_1", 0) == 0
    finally:
        await _unload(sem_real_hass, entry)


@pytest.mark.unit
class TestOffStaysOff:
    def test_off_keeps_its_release_and_gets_no_phase_stop(self):
        """#898: Off is hands-off and the guard leaves it alone. Adding
        "SEM yields" must not hand Off a stop."""
        from .test_1381_phase_guard_yield import _snapshot
        off = ChargerDecision(
            charger_id="zaptec", mode="off", intent=ChargerIntent.RELEASE,
            reason="off mode", reason_code=RC.CHARGER_OFF)
        d = yielded_charger_decision(off)
        assert d is off
        g = ActivePhaseGuard()
        g.update(_snapshot(31.2), {"phase_guard_enabled": True,
                                   "phase_guard_enforcement_enabled": True})
        assert g.filter_decision(d).intent is ChargerIntent.RELEASE
