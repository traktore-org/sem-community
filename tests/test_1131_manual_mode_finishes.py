"""#1131 — Force charge stayed on when the battery was full.

The mode was a place to stay: at 100 % the house took 1 % and SEM bought it
back from the grid at once, for as long as nobody changed the mode. Force
discharge did the same at the reserve — the next day's sun was sold down to
it again. Each is one job: when it is done the battery goes back to Auto.

Three links, each driven for real:

* ``manual_mode_done`` — the pure rule (full for a charge, at the reserve for
  a sale, never on a level SEM cannot read);
* ``SEMCoordinator._finish_manual_battery_modes`` — writes Auto into the
  store the battery's control on screen writes (real config entry, real
  select platform), and the select shows it. One shared control ends only
  when every battery it drives is done; the done state must hold three reads
  in a row, so one bad read ends nothing;
* ``_run_battery_pipeline`` — hands it every battery with its level and
  whether that level is a reading, BEFORE the VPP override is laid over the
  user's mode and before the cycle decides.
"""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryPower,
    BatteryRuntime,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    MANUAL_CHARGE_TARGET_SOC,
    manual_mode_done,
)
from custom_components.solar_energy_management.consts.core import (
    BATTERY_SOC_STEP_CONFIRM_READS as READS,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)

_HAS_PHACC = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None


# ── 1. The rule ────────────────────────────────────────────────────────────

class TestTheRule:
    @pytest.mark.parametrize("soc,done", [
        (40.0, False), (99.0, False), (99.9, False), (100.0, True)])
    def test_a_charge_is_done_when_the_battery_reaches_100(self, soc, done):
        assert manual_mode_done("force_charge", soc, soc_read=True,
                                reserve=20.0) is done

    @pytest.mark.parametrize("soc,done", [
        (80.0, False), (30.5, False), (30.0, True), (12.0, True)])
    def test_a_sale_is_done_at_its_reserve(self, soc, done):
        assert manual_mode_done("force_discharge", soc, soc_read=True,
                                reserve=30.0) is done

    @pytest.mark.parametrize("mode,soc", [
        ("force_charge", 100.0), ("force_discharge", 0.0)])
    def test_a_level_sem_cannot_read_finishes_nothing(self, mode, soc):
        # 0.0 is what a unit that never answered carries; 100 % may be held
        # from before a dropout. Neither is the battery's level.
        assert manual_mode_done(mode, soc, soc_read=False, reserve=20.0) is False
        assert manual_mode_done(mode, None, soc_read=True, reserve=20.0) is False

    @pytest.mark.parametrize("mode", [
        "auto", "self_consumption", "off", "allow_arbitrage", None, ""])
    def test_the_standing_modes_never_finish(self, mode):
        for soc in (0.0, 20.0, 100.0):
            assert manual_mode_done(mode, soc, soc_read=True, reserve=20.0) is False

    def test_the_charge_ends_where_decide_battery_aims_it(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryView, FleetContext,
        )
        from custom_components.solar_energy_management.coordinator.decide_battery import (
            decide_battery,
        )
        view = BatteryView(
            runtime=BatteryRuntime(battery_id="b1", last_known_soc=40.0),
            config={"battery_mode": "force_charge"}, fleet=FleetContext(),
            charging_state="idle", ev_charging=False, home_consumption_w=500.0)
        assert decide_battery(view).target_soc == MANUAL_CHARGE_TARGET_SOC == 100.0

    def test_the_sale_ends_exactly_where_decide_battery_stops_selling(self):
        # decide_battery sells while ``soc > reserve``; done is the opposite,
        # so a readable level is always either selling or finished.
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent, BatteryView, FleetContext,
        )
        from custom_components.solar_energy_management.coordinator.decide_battery import (
            decide_battery,
        )
        for soc in (19.0, 19.9, 20.0, 20.1, 21.0, 60.0):
            view = BatteryView(
                runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
                config={"battery_mode": "force_discharge",
                        "battery_reserve_soc": 20.0},
                fleet=FleetContext(), charging_state="idle",
                ev_charging=False, home_consumption_w=500.0)
            sells = decide_battery(view).intent is BatteryIntent.FORCE_DISCHARGE
            done = manual_mode_done("force_discharge", soc, soc_read=True,
                                    reserve=20.0)
            assert sells != done, soc


# ── 2. The write, and the select that shows it ─────────────────────────────

def _entry(hass, options):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.solar_energy_management.const import DOMAIN
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=dict(options),
                            title="SEM #1131")
    entry.add_to_hass(hass)
    return entry


def _coordinator(hass, entry, slugs):
    """A coordinator double with the captured battery controls and the REAL
    ``_per_battery_config`` and VPP override."""
    from custom_components.solar_energy_management.const import DOMAIN
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.config_entry = entry
    coordinator.hass = hass
    coordinator.setup_presence = {m: Presence.PRESENT for m in Module}
    coordinator.config = {**entry.data, **entry.options}
    coordinator.battery_control_slugs = slugs
    coordinator._manual_done_streaks = {}
    coordinator._vpp_battery_override = None
    coordinator._sensor_reader._energy_dashboard_config.battery_power_list = []
    coordinator._per_battery_config = (
        lambda i, c=1: SEMCoordinator._per_battery_config(coordinator, i, c))
    coordinator._vpp_apply_battery_override = (
        lambda pbc: SEMCoordinator._vpp_apply_battery_override(coordinator, pbc))
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return coordinator


async def _selects(hass, entry):
    from custom_components.solar_energy_management import select
    added: list = []
    await select.async_setup_entry(hass, entry, added.extend)
    out = {}
    for ent in added:
        key = ent.entity_description.key
        if key.startswith("battery_") and key.endswith("_mode"):
            ent.hass = hass
            ent.async_write_ha_state = lambda: None
            out[key] = ent
    return out


def _cycles(coordinator, levels, count=None, reads=READS, unread=()):
    """``reads`` cycles of ``_finish_manual_battery_modes`` on ``levels``
    ({battery id: SOC}); ids in ``unread`` are not a reading."""
    items = [(bid, BatteryRuntime(battery_id=bid, last_known_soc=soc))
             for bid, soc in levels.items()]
    read = {bid: bid not in unread for bid in levels}
    for _ in range(reads):
        SEMCoordinator._finish_manual_battery_modes(
            coordinator, items, read, count or len(items))


def _runs(coordinator, idx, count):
    cfg = SEMCoordinator._per_battery_config(coordinator, idx, count)
    return str(cfg.get("battery_mode", "auto") or "auto").lower()


def _shows(select_entity):
    select_entity._handle_coordinator_update()
    return select_entity.current_option


@pytest.mark.skipif(not _HAS_PHACC, reason="pytest-homeassistant-custom-component not installed")
class TestTheModeGoesBackToAuto:
    @pytest.mark.asyncio
    async def test_one_battery_at_100_goes_back_to_auto(self, hass):
        entry = _entry(hass, {"battery_mode": "auto"})
        coordinator = _coordinator(hass, entry, ())
        selects = await _selects(hass, entry)
        await selects["battery_mode"].async_select_option("force_charge")
        assert _runs(coordinator, 0, 1) == "force_charge"

        _cycles(coordinator, {"primary": 99.0}, reads=10)
        assert entry.options["battery_mode"] == "force_charge", (
            "not full yet: the charge goes on")

        _cycles(coordinator, {"primary": 100.0}, reads=READS - 1)
        assert entry.options["battery_mode"] == "force_charge", (
            "full must hold a few reads before the job counts as done")
        _cycles(coordinator, {"primary": 100.0}, reads=1)
        assert entry.options["battery_mode"] == "auto"
        assert _runs(coordinator, 0, 1) == "auto"
        assert _shows(selects["battery_mode"]) == "auto", (
            "the select must show the mode SEM runs")

    @pytest.mark.asyncio
    async def test_a_level_sem_cannot_read_keeps_the_mode(self, hass):
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, ())
        _cycles(coordinator, {"primary": 100.0}, reads=10, unread={"primary"})
        assert entry.options["battery_mode"] == "force_charge"

    @pytest.mark.asyncio
    async def test_a_sale_goes_back_to_auto_at_the_reserve(self, hass):
        entry = _entry(hass, {"battery_mode": "force_discharge",
                              "battery_reserve_soc": 30})
        coordinator = _coordinator(hass, entry, ())
        selects = await _selects(hass, entry)
        _cycles(coordinator, {"primary": 31.0}, reads=10)
        assert entry.options["battery_mode"] == "force_discharge"
        _cycles(coordinator, {"primary": 30.0})
        assert entry.options["battery_mode"] == "auto"
        assert _shows(selects["battery_mode"]) == "auto"

    @pytest.mark.asyncio
    async def test_one_bad_read_ends_nothing(self, hass):
        # A unit's level blinks to 0 % for one cycle (#902's Huawei dropout
        # shape): the sale goes on, and the count starts again.
        entry = _entry(hass, {"battery_mode": "force_discharge",
                              "battery_reserve_soc": 30})
        coordinator = _coordinator(hass, entry, ())
        for soc in (60.0, 0.0, 60.0, 0.0, 0.0, 60.0):
            _cycles(coordinator, {"primary": soc}, reads=1)
        assert entry.options["battery_mode"] == "force_discharge"

    @pytest.mark.asyncio
    async def test_two_batteries_only_the_finished_one_moves(self, hass):
        entry = _entry(hass, {"battery_modes": ["force_discharge", "force_charge"],
                              "battery_reserve_socs": [20, 20],
                              # a stale scalar the per-battery controls never read
                              "battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, ("b1", "b2"))
        selects = await _selects(hass, entry)
        assert set(selects) == {"battery_b1_mode", "battery_b2_mode"}

        # b1 sells and is full: not done. b2 charges and is full: done.
        _cycles(coordinator, {"b1": 100.0, "b2": 100.0})
        assert entry.options["battery_modes"] == ["force_discharge", "auto"]
        assert entry.options["battery_mode"] == "force_charge", (
            "the per-battery controls own the mode; the scalar is not theirs")
        assert _runs(coordinator, 0, 2) == "force_discharge"
        assert _runs(coordinator, 1, 2) == "auto"
        assert _shows(selects["battery_b1_mode"]) == "force_discharge"
        assert _shows(selects["battery_b2_mode"]) == "auto"

    @pytest.mark.asyncio
    async def test_one_control_for_two_batteries_ends_when_both_are_done(self, hass):
        # (review) An Energy Dashboard that lists each battery as two sensors
        # gets ONE select for both. b1 full must not stop b2's charge.
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, ())
        selects = await _selects(hass, entry)
        assert set(selects) == {"battery_mode"}

        _cycles(coordinator, {"b1": 100.0, "b2": 60.0}, reads=10)
        assert entry.options["battery_mode"] == "force_charge"
        assert _runs(coordinator, 1, 2) == "force_charge"
        _cycles(coordinator, {"b1": 100.0, "b2": 100.0}, unread={"b2"}, reads=10)
        assert entry.options["battery_mode"] == "force_charge", (
            "b2's level is not a reading: its job is not known to be done")

        _cycles(coordinator, {"b1": 100.0, "b2": 100.0})
        assert entry.options["battery_mode"] == "auto"
        assert _shows(selects["battery_mode"]) == "auto"

    @pytest.mark.asyncio
    async def test_a_cold_start_on_one_synthetic_battery_ends_no_unit(self, hass):
        # Two per-battery selects, but this cycle runs one synthetic battery
        # on the fleet level: no unit's own level is known.
        entry = _entry(hass, {"battery_modes": ["force_charge", "force_charge"]})
        coordinator = _coordinator(hass, entry, ("b1", "b2"))
        _cycles(coordinator, {"primary": 100.0}, count=1, reads=10)
        assert entry.options["battery_modes"] == ["force_charge", "force_charge"]

    @pytest.mark.asyncio
    async def test_a_grid_event_force_charge_never_moves_the_select(self, hass):
        # The VPP override lays force_charge over an Auto battery for the
        # event (the real override is bound on the double). Full or not, the
        # user's mode is Auto and is not written.
        entry = _entry(hass, {"battery_mode": "auto"})
        coordinator = _coordinator(hass, entry, ())
        coordinator._vpp_battery_override = {"battery_mode": "force_charge"}
        assert coordinator._vpp_apply_battery_override(
            coordinator._per_battery_config(0, 1))["battery_mode"] == "force_charge"
        writes = []
        hass.config_entries.async_update_entry = (
            lambda *a, **kw: writes.append(kw))
        _cycles(coordinator, {"primary": 100.0}, reads=10)
        assert writes == []

    @pytest.mark.asyncio
    async def test_the_select_follows_a_mode_written_anywhere(self, hass):
        # The set_option service writes the scalar the same way.
        from custom_components.solar_energy_management import persist_global_option
        entry = _entry(hass, {"battery_mode": "auto"})
        coordinator = _coordinator(hass, entry, ())
        selects = await _selects(hass, entry)
        persist_global_option(hass, entry, coordinator, "battery_mode",
                              "self_consumption")
        assert _shows(selects["battery_mode"]) == "self_consumption"


# ── 3. The pipeline asks, for every battery, before it decides ─────────────

class _Decided(Exception):
    """Raised by the patched decide_battery: the cycle reached the decision."""


def _pipeline_stub():
    stub = MagicMock()
    stub.setup_presence = {m: Presence.PRESENT for m in Module}
    stub._observer_mode = False
    stub._battery_charge_scheduler.enabled = False
    stub.config = {}
    return stub


async def _run_pipeline(monkeypatch, power):
    from custom_components.solar_energy_management.coordinator import (
        decide_battery as db,
    )
    order: list = []
    stub = _pipeline_stub()
    stub._finish_manual_battery_modes = (
        lambda items, soc_read, count, power_read=False, site=None: order.append((
            "finish", [(bid, rt.last_known_soc) for bid, rt in items],
            dict(soc_read), count)))
    stub._vpp_apply_battery_override = (
        lambda pbc: order.append(("vpp",)) or {})

    def _decide(view):
        order.append(("decide", view.runtime.battery_id))
        raise _Decided

    monkeypatch.setattr(db, "decide_battery", _decide)
    with pytest.raises(_Decided):
        await SEMCoordinator._run_battery_pipeline(
            stub, power, SimpleNamespace(), "idle")
    return order


def _single(**kw):
    base = dict(batteries={}, battery_soc=100.0, battery_power=0.0,
                battery_soc_unavailable=False, battery_soc_known=True)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
class TestThePipelineAsksFirst:
    async def test_a_full_battery_is_asked_before_the_cycle_decides(self, monkeypatch):
        order = await _run_pipeline(monkeypatch, _single())
        assert order[0] == ("finish", [("primary", 100.0)], {"primary": True}, 1)
        assert [o[0] for o in order] == ["finish", "vpp", "decide"], (
            "the mode must be finished before the VPP override is laid over "
            "it and before the cycle decides")

    async def test_a_failed_mode_write_does_not_end_the_cycle(self, monkeypatch):
        from custom_components.solar_energy_management.coordinator import (
            decide_battery as db,
        )
        stub = _pipeline_stub()
        stub._finish_manual_battery_modes = MagicMock(
            side_effect=RuntimeError("entry gone"))
        stub._vpp_apply_battery_override = lambda pbc: {}
        decided = []

        def _decide(view):
            decided.append(view.runtime.battery_id)
            raise _Decided

        monkeypatch.setattr(db, "decide_battery", _decide)
        with pytest.raises(_Decided):
            await SEMCoordinator._run_battery_pipeline(
                stub, _single(), SimpleNamespace(), "idle")
        assert stub._finish_manual_battery_modes.called
        assert decided == ["primary"], "the battery is still decided this cycle"

    async def test_a_held_level_is_not_a_reading(self, monkeypatch):
        order = await _run_pipeline(
            monkeypatch, _single(battery_soc_unavailable=True))
        assert order[0][2] == {"primary": False}

    async def test_a_level_never_read_is_not_a_reading(self, monkeypatch):
        order = await _run_pipeline(
            monkeypatch, _single(battery_soc=0.0, battery_soc_known=False))
        assert order[0][2] == {"primary": False}

    async def test_each_unit_brings_its_own_level(self, monkeypatch):
        power = _single(batteries={
            "b1": BatteryPower(battery_id="b1", power_w=0.0, soc_pct=None),
            "b2": BatteryPower(battery_id="b2", power_w=0.0, soc_pct=100.0),
        })
        order = await _run_pipeline(monkeypatch, power)
        # b1's sensor has not answered: its 0.0 is no reading. b2 is full.
        assert order[0] == ("finish", [("b1", 0.0), ("b2", 100.0)],
                            {"b1": False, "b2": True}, 2)
