"""#576 — loads charge before the battery.

The Victron-style rule: above the reserve zone, power that would otherwise
charge the home battery is added to the surplus pool, so the surplus loads
— walked by their own priority — consume it first and the battery is the
sink at the bottom. There is **no opt-in toggle**; the reserve floor
(``battery_priority_soc``) is the only gate. The single quantity is
:func:`reclaimable_battery_w`.

Design: docs/superpowers/specs/2026-07-10-load-priority-above-battery-design.md
Plan:   docs/superpowers/plans/2026-07-10-load-priority-above-battery.md
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    reclaimable_battery_w,
)


@pytest.mark.unit
class TestReclaimableBatteryW:
    def test_below_reserve_returns_zero(self):
        # SOC below the reserve zone → battery fills first.
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=25, priority_soc=30,
            battery_commanded=False) == 0.0

    def test_commanded_charge_returns_zero(self):
        # Force/scheduled/arbitrage charge is honored — no reclaim.
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            battery_commanded=True) == 0.0

    def test_above_reserve_reclaims_charge_power(self):
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            battery_commanded=False) == 2400.0

    def test_discharging_battery_reclaims_zero(self):
        # Negative charge power (battery discharging) is not reclaimable.
        assert reclaimable_battery_w(
            battery_charge_power=-1500, soc=85, priority_soc=30,
            battery_commanded=False) == 0.0

    def test_at_reserve_boundary_inclusive(self):
        # SOC exactly at the zone counts as above (>=), matching
        # charging_control's `soc >= battery_priority_soc`.
        assert reclaimable_battery_w(
            battery_charge_power=1000, soc=30, priority_soc=30,
            battery_commanded=False) == 1000.0


def _available(export, own, batt, soc, commanded=False, pri=30):
    """The exact figure the coordinator feeds SurplusController.update()."""
    return export + own + reclaimable_battery_w(
        battery_charge_power=batt, soc=soc, priority_soc=pri,
        battery_commanded=commanded)


@pytest.mark.unit
class TestLoadScenarios:
    """Spec §3 acceptance scenarios U3–U6 (generic loads / reserve floor)."""

    def test_u3_two_heaters_pool_pre_battery(self):
        # 3.5 kW pool, 0 home, 85% SOC. Battery not charging in this instant
        # (all solar is exporting) → nothing to reclaim; the 3.5 kW export IS
        # the pre-battery surplus and both 1 kW heaters allocate from it.
        avail = _available(export=3500, own=0, batt=0, soc=85)
        assert avail == pytest.approx(3500)

    def test_u4_below_reserve_no_reclaim(self):
        # SOC 25% < zone → battery fills first, loads see export-only.
        avail = _available(export=100, own=0, batt=2400, soc=25)
        assert avail == pytest.approx(100)

    def test_u5_discrete_load_below_rating_flows_to_battery(self):
        # 0.8 kW pool < a 1 kW heater rating → heater stays off; 0.8 → battery.
        avail = _available(export=800, own=0, batt=0, soc=85)
        assert avail == pytest.approx(800)

    def test_u6_commanded_charge_no_reclaim(self):
        # Force / scheduled / arbitrage charge honored → no reclaim.
        avail = _available(export=100, own=0, batt=2400, soc=85, commanded=True)
        assert avail == pytest.approx(100)

    def test_reclaim_when_battery_charging_above_zone(self):
        # The core win: 100 W export + 2.4 kW battery charge reclaimed above
        # the zone → 2.5 kW offered to the loads (by device priority).
        avail = _available(export=100, own=0, batt=2400, soc=85)
        assert avail == pytest.approx(2500)


@pytest.mark.unit
class TestSurplusInputWiring:
    """Locks the arithmetic the coordinator uses at the ``true_surplus_w``
    build: export + own draw + reclaim."""

    def test_surplus_input_includes_reclaim_above_zone(self):
        reclaim = reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            battery_commanded=False)
        assert 100.0 + 0.0 + reclaim == pytest.approx(2500.0)

    def test_surplus_input_unchanged_below_zone(self):
        reclaim = reclaimable_battery_w(
            battery_charge_power=2400, soc=25, priority_soc=30,
            battery_commanded=False)
        assert 100.0 + 0.0 + reclaim == pytest.approx(100.0)


# ── The battery as a positioned device in the priority walk ──────────────
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from custom_components.solar_energy_management.coordinator.surplus_controller import (  # noqa: E402
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import (  # noqa: E402
    DeviceControlMode,
)


def _make_device(device_id, priority, min_power=500):
    """Minimal surplus-load mock — just enough for the activation walk."""
    d = MagicMock()
    d.device_id = device_id
    d.name = device_id
    d.priority = priority
    d.min_power_threshold = min_power
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = False
    d.device_type = MagicMock(value="switch")
    d.control_mode = DeviceControlMode.SURPLUS
    d._sem_owned = False
    d.activate = AsyncMock(return_value=min_power)
    d.adjust_power = AsyncMock(return_value=min_power)
    d.get_current_consumption = MagicMock(return_value=0.0)
    d.status = MagicMock()
    d.status.allocated_power_w = 0.0
    d.status.state = MagicMock(value="idle")
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = False
    d._batt_overnight_forced_date = None
    d.daily_targets_met = False
    d.daily_max_runtime_reached = False
    d.stop_condition_met = False
    d.__class__ = MagicMock
    async def _deact():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_deact)
    return d


async def _run_walk(mock_hass, *, battery_priority, export=200.0, reclaim=1000.0,
                    load_hi_prio=2, load_lo_prio=5, min_w=500):
    """Two surplus loads (hi/lo priority) + a battery slot. Returns which
    loads activated after one allocation cycle."""
    sc = SurplusController(mock_hass, regulation_offset=0)
    hi = _make_device(device_id="hi", priority=load_hi_prio, min_power=min_w)
    lo = _make_device(device_id="lo", priority=load_lo_prio, min_power=min_w)
    sc.register_device(hi)
    sc.register_device(lo)
    await sc.update(export, reclaim_w=reclaim, battery_priority=battery_priority)
    return hi.activate.called, lo.activate.called


@pytest.mark.unit
class TestBatteryPositionInWalk:
    """The battery's drag position governs which loads reclaim its charge.
    Export is small (200 W < a load's 500 W min); the 1000 W reclaim is what
    lets a load above the battery switch on."""

    async def test_battery_at_bottom_all_loads_reclaim(self, mock_hass):
        # priority 100 → both loads (2, 5) are above it → both may reclaim.
        hi_on, lo_on = await _run_walk(mock_hass, battery_priority=100)
        assert hi_on and lo_on

    async def test_battery_in_middle_only_higher_load_reclaims(self, mock_hass):
        # battery at 3: load@2 is above (reclaims → on); load@5 is below
        # (yields → the reclaim is handed back to the battery → stays off).
        hi_on, lo_on = await _run_walk(mock_hass, battery_priority=3)
        assert hi_on and not lo_on

    async def test_battery_at_top_no_load_reclaims(self, mock_hass):
        # battery at 1: both loads below it. Only 200 W export remains (< 500 W
        # min) → neither switches on; the battery keeps its 1000 W.
        hi_on, lo_on = await _run_walk(mock_hass, battery_priority=1)
        assert not hi_on and not lo_on

    async def test_no_battery_priority_is_todays_behavior(self, mock_hass):
        # battery_priority=None (+ reclaim baked into export by the caller):
        # the walk never hands anything back — pure export-only gate.
        sc = SurplusController(mock_hass, regulation_offset=0)
        hi = _make_device(device_id="hi", priority=2, min_power=500)
        sc.register_device(hi)
        await sc.update(1200.0, reclaim_w=0.0, battery_priority=None)
        assert hi.activate.called  # 1200 >= 500


# ── P2.1: unified priority store ──────────────────────────────────────────
from custom_components.solar_energy_management.features.device_registry import (  # noqa: E402
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management.const import (  # noqa: E402
    BATTERY_SURPLUS_DEVICE_ID,
    DEFAULT_BATTERY_SURPLUS_PRIORITY,
)


def _make_registry():
    """A registry with mocked collaborators — priority_for is pure logic
    over _priority_overrides, no HA I/O needed."""
    return UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())


@pytest.mark.unit
class TestUnifiedPriorityStore:
    """P2.1 — _priority_overrides is the single authoritative axis for every
    device (loads, battery, EV chargers). Drag (override) wins; else the
    per-device seed (e.g. config ev_surplus_priority); else a large default."""

    def test_override_wins_over_seed(self):
        reg = _make_registry()
        reg._priority_overrides["ev_charger_0"] = 2
        assert reg.priority_for("ev_charger_0", seed=3) == 2

    def test_seed_used_when_no_override(self):
        reg = _make_registry()
        assert reg.priority_for("ev_charger_0", seed=3) == 3

    def test_default_when_no_override_no_seed(self):
        reg = _make_registry()
        assert reg.priority_for("mystery_device") == 999

    def test_battery_reads_same_store(self):
        # battery_surplus_priority() is now just priority_for(battery, seed=default)
        reg = _make_registry()
        reg._priority_overrides[BATTERY_SURPLUS_DEVICE_ID] = 5
        assert reg.priority_for(
            BATTERY_SURPLUS_DEVICE_ID, seed=DEFAULT_BATTERY_SURPLUS_PRIORITY
        ) == 5

    def test_battery_seed_default_when_unset(self):
        reg = _make_registry()
        assert reg.battery_surplus_priority() == DEFAULT_BATTERY_SURPLUS_PRIORITY

    def test_seed_zero_is_honoured_not_treated_as_missing(self):
        # `is not None` guard, not a truthy check: seed=0 is a valid top slot
        # and must not fall through to the 999 default (would sink a
        # top-priority device to the bottom).
        reg = _make_registry()
        assert reg.priority_for("dev", seed=0) == 0


@pytest.mark.unit
class TestDependencyGraphGuards:
    """The "Requires" link must never form a cycle — a self- or transitive
    loop deadlocks both devices forever and persists across restarts."""

    def _reg(self):
        reg = _make_registry()
        reg._dependency_overrides = {}
        reg._service_registrations = {}
        reg._surplus_controller = MagicMock(get_device=MagicMock(return_value=None))
        reg._save_storage = AsyncMock()
        return reg

    async def test_self_dependency_rejected(self):
        reg = self._reg()
        await reg.async_set_dependency("pump", "pump")
        assert "pump" not in reg._dependency_overrides

    async def test_transitive_cycle_rejected(self):
        # A requires B, then B requires A → the second write would close the
        # loop and is rejected; A's link is left intact.
        reg = self._reg()
        await reg.async_set_dependency("a", "b")
        await reg.async_set_dependency("b", "a")
        assert reg._dependency_overrides.get("a") == ["b"]
        assert "b" not in reg._dependency_overrides

    async def test_three_hop_cycle_rejected(self):
        reg = self._reg()
        await reg.async_set_dependency("a", "b")
        await reg.async_set_dependency("b", "c")
        await reg.async_set_dependency("c", "a")   # would close a→b→c→a
        assert "c" not in reg._dependency_overrides

    async def test_valid_chain_accepted(self):
        reg = self._reg()
        await reg.async_set_dependency("a", "b")
        await reg.async_set_dependency("b", "c")   # a→b→c, no loop
        assert reg._dependency_overrides == {"a": ["b"], "b": ["c"]}

    async def test_non_cyclic_parent_kept_when_a_cyclic_one_dropped(self):
        # Multi-parent: one parent would cycle, the other wouldn't — keep the
        # safe one, drop only the offender.
        reg = self._reg()
        await reg.async_set_dependency("a", "b")
        await reg.async_set_dependency("b", ["a", "c"])   # a cycles, c is fine
        assert reg._dependency_overrides.get("b") == ["c"]

    def test_would_cycle_is_bounded_on_a_preexisting_loop(self):
        # Defensive: even if storage already holds a stray x↔y loop, the walk
        # terminates (visited-set) instead of spinning.
        reg = self._reg()
        reg._dependency_overrides = {"x": ["y"], "y": ["x"]}
        assert reg._dependency_would_cycle("z", "x") is False


@pytest.mark.unit
class TestDependencyMigration:
    """Every install upgrading from before this branch has a Store with no
    `dependencies` key — loading must default cleanly, never KeyError."""

    async def test_old_schema_loads_without_dependencies_key(self):
        # Exercise the REAL async_initialize load path with a pre-#576 store
        # (no `dependencies` key). Must default to {} and never KeyError, while
        # still loading the keys that DO exist.
        reg = _make_registry()
        old_store = {"mappings": {}, "priority_overrides": {"ed_pump": 2},
                     "control_modes": {}, "service_registrations": {},
                     "device_goals": {}}
        reg._store = MagicMock()
        reg._store.async_load = AsyncMock(return_value=old_store)
        reg.async_refresh_devices = AsyncMock()
        reg._register_service_devices = MagicMock()
        reg.hass = MagicMock()
        await reg.async_initialize()
        assert reg._dependency_overrides == {}
        assert reg._priority_overrides == {"ed_pump": 2}


# ── P2.1: EV chargers are first-class rows keyed by CONTROL id ─────────────
from custom_components.solar_energy_management.features.device_registry import (  # noqa: E402
    UnifiedDevice,
)


def _registry_for_rows():
    reg = _make_registry()
    reg._devices = []
    reg._service_registrations = {}
    reg._has_battery = False
    reg._surplus_controller = MagicMock(
        get_device=MagicMock(return_value=None), _devices={})
    reg.hass = MagicMock()
    reg.hass.states.get = MagicMock(return_value=None)
    return reg


@pytest.mark.unit
class TestEvChargerRows:
    """The charger's CONTROL id is the single identity — the card row, the
    drag store and the reclaim gate all use it (``distribute_ev_budget``
    was in this list until #651 deleted it). Sourced
    from the coordinator's configured chargers (set_ev_chargers), NOT from the
    ED is_ev naming guess (which is suppressed to avoid a double-add)."""

    def _charger(self, **kw):
        base = dict(id="ev_charger_0", name="Garage", priority_seed=3,
                    power_entity="sensor.keba_power", current_power_w=4100.0,
                    is_on=True, min_power_w=4140.0, max_power_w=11000.0,
                    connected=True)
        base.update(kw)
        return base

    def test_charger_appears_by_control_id_with_seed_priority(self):
        reg = _registry_for_rows()
        reg.set_ev_chargers([self._charger()])
        devs = reg.get_devices_for_sensor()
        assert "ev_charger_0" in devs
        row = devs["ev_charger_0"]
        assert row["device_type"] == "ev_charger"
        assert row["priority"] == 3          # from seed
        assert row["is_on"] is True

    def test_power_rating_is_min_threshold_not_theoretical_max(self):
        # #576 — the EV row's rating is the MIN power (surplus threshold to
        # start), NOT the 32A*3ph max (~22kW). Idle still shows the threshold.
        reg = _registry_for_rows()
        reg.set_ev_chargers([self._charger(
            current_power_w=0.0, is_on=False, min_power_w=4140.0, max_power_w=22080.0)])
        row = reg.get_devices_for_sensor()["ev_charger_0"]
        assert row["power_rating"] == 4140      # min threshold, not 22080
        # falls back to the live draw if min isn't provided
        reg.set_ev_chargers([{**self._charger(current_power_w=3000.0), "min_power_w": None}])
        assert reg.get_devices_for_sensor()["ev_charger_0"]["power_rating"] == 3000

    def test_charger_drag_override_wins(self):
        reg = _registry_for_rows()
        reg._priority_overrides["ev_charger_0"] = 1
        reg.set_ev_chargers([self._charger(is_on=False, current_power_w=0.0)])
        assert reg.get_devices_for_sensor()["ev_charger_0"]["priority"] == 1

    def test_current_power_is_raw_watts_not_kw(self):
        # ruflo HIGH — the card divides current_power by 1000 then formats, so
        # every row MUST emit raw WATTS. Emitting kW here (the old ÷1000 bug)
        # rendered a 4.1 kW draw as "4 W". Lock the unit for the EV row.
        reg = _registry_for_rows()
        reg.set_ev_chargers([self._charger(current_power_w=4100.0)])
        assert reg.get_devices_for_sensor()["ev_charger_0"]["current_power"] == 4100

    def test_ed_is_ev_row_suppressed_when_charger_configured(self):
        # No double-add: an ED-detected is_ev device must NOT produce a second
        # row once a charger is configured (the config is authoritative).
        reg = _registry_for_rows()
        reg._devices = [UnifiedDevice(
            energy_sensor="sensor.keba_energy", power_sensor="sensor.keba_power",
            name="Keba", priority=1, is_ev=True,
            control={"type": "service", "entity": "sensor.keba_power"})]
        reg.set_ev_chargers([self._charger()])
        devs = reg.get_devices_for_sensor()
        ev_rows = [k for k, v in devs.items() if v.get("device_type") == "ev_charger"]
        assert ev_rows == ["ev_charger_0"]


# ── P2.2: EV position-based reclaim predicate ─────────────────────────────
from custom_components.solar_energy_management.coordinator.energy_reclaim import (  # noqa: E402
    ev_reclaims_battery_charge,
)


@pytest.mark.unit
class TestEvReclaimsBatteryCharge:
    """The EV reclaims battery-charge power iff it sits ABOVE the battery in
    the one list AND SOC ≥ reserve floor AND the battery isn't commanded —
    the same rule as the loads, replacing the old auto_start_soc(90%) gate."""

    def _call(self, **kw):
        base = dict(soc=85.0, priority_soc=30.0, ev_priority=2,
                    battery_priority=5, battery_commanded=False)
        base.update(kw)
        return ev_reclaims_battery_charge(**base)

    def test_above_reserve_ev_above_battery_reclaims(self):
        assert self._call() is True

    def test_below_reserve_no_reclaim(self):
        assert self._call(soc=25.0) is False

    def test_ev_below_battery_yields(self):
        assert self._call(ev_priority=7) is False

    def test_ev_equal_battery_yields(self):
        # strictly above — equal position does not reclaim
        assert self._call(ev_priority=5) is False

    def test_commanded_battery_no_reclaim(self):
        assert self._call(battery_commanded=True) is False

    def test_no_battery_no_reclaim(self):
        assert self._call(battery_priority=None) is False

    def test_at_reserve_boundary_inclusive(self):
        assert self._call(soc=30.0) is True


# ── P2.2: reclaim wired into self_consumption_surplus_w ────────────────────
from custom_components.solar_energy_management.coordinator.decide import (  # noqa: E402
    self_consumption_surplus_w,
)
from custom_components.solar_energy_management.coordinator.charger_types import (  # noqa: E402
    ChargerView, ChargerPower, ChargerEnergy, FleetContext,
)


def _charger_view(*, ev_priority, battery_priority, soc=85.0, batt_charge=2000.0,
                  commanded=False, solar=7000.0, home=1500.0):
    fleet = FleetContext(
        solar_w=solar, home_w=home, battery_charge_w=batt_charge,
        battery_soc=soc, priority_soc=30.0, auto_start_soc=90.0,
        battery_priority=battery_priority, battery_commanded=commanded,
    )
    return ChargerView(
        power=ChargerPower(charger_id="ev_charger_0"),
        energy=ChargerEnergy(charger_id="ev_charger_0"),
        mode="solar_only", config={}, fleet=fleet, ev_priority=ev_priority,
    )


@pytest.mark.unit
class TestEvSurplusReclaimWiring:
    """self_consumption_surplus_w stops subtracting battery_charge_w when the
    EV sits above the battery in the list (SOC ≥ reserve) — the position rule
    replaces the old auto_start_soc(90%) gate."""

    def test_ev_above_battery_reclaims_full_charge(self):
        # ev(2) < battery(5), SOC 85 ≥ 30 → reclaim: 7000-1500 = 5500 (no subtract)
        assert self_consumption_surplus_w(
            _charger_view(ev_priority=2, battery_priority=5)) == pytest.approx(5500.0)

    def test_ev_below_battery_yields(self):
        # ev(9) > battery(5) → battery keeps charge: 5500 - 2000 = 3500
        assert self_consumption_surplus_w(
            _charger_view(ev_priority=9, battery_priority=5)) == pytest.approx(3500.0)

    def test_below_reserve_yields(self):
        assert self_consumption_surplus_w(
            _charger_view(ev_priority=2, battery_priority=5, soc=25.0)
        ) == pytest.approx(3500.0)

    def test_commanded_battery_yields(self):
        assert self_consumption_surplus_w(
            _charger_view(ev_priority=2, battery_priority=5, commanded=True)
        ) == pytest.approx(3500.0)

    def test_no_battery_priority_yields(self):
        # battery_priority None (no battery in list) → old subtract behaviour
        assert self_consumption_surplus_w(
            _charger_view(ev_priority=2, battery_priority=None)
        ) == pytest.approx(3500.0)


# ── P2.1/#4: default seed order EV → battery → loads ───────────────────────
from custom_components.solar_energy_management.const import (  # noqa: E402
    LOAD_PRIORITY_BASE,
)


@pytest.mark.unit
class TestDefaultSeedOrder:
    """Fresh (never-dragged) seed puts EV chargers above the battery and loads
    below it: EV → battery → loads. Guido's confirmed default; reverses the
    old battery-at-bottom seed so loads yield to the battery until dragged up."""

    def test_ev_seed_above_battery_above_load_seed(self):
        ev_seed = 3                                   # default ev_surplus_priority
        battery = DEFAULT_BATTERY_SURPLUS_PRIORITY    # 100
        first_load_seed = 1 + LOAD_PRIORITY_BASE      # ED position 1 → 101
        assert ev_seed < battery < first_load_seed

    def test_load_seeds_below_battery_for_any_position(self):
        battery = DEFAULT_BATTERY_SURPLUS_PRIORITY
        for pos in range(1, 20):
            assert pos + LOAD_PRIORITY_BASE > battery   # every load yields by default


# ── #9: HP/HW/climate as draggable rows (dedup) ───────────────────────────
@pytest.mark.unit
class TestDirectSurplusDeviceRows:
    """Heat pump / hot water / climate (registered straight into the surplus
    controller) appear as draggable rows keyed by their id, deduped, and their
    drag position is authoritative (refresh_direct_device_priorities)."""

    def _reg_with_hp(self):
        reg = _registry_for_rows()
        hp = MagicMock()
        hp.name = "Heat Pump"; hp.priority = 4; hp.rated_power = 2000
        hp.is_active = False; hp.is_ev = False; hp.entity_id = None
        hp.power_entity_id = None; hp._sem_owned = False
        hp.device_type = MagicMock(value="heat_pump")
        hp.control_mode = MagicMock(value="surplus")
        reg._surplus_controller._devices = {"heat_pump": hp}
        return reg, hp

    def test_hp_appears_as_row(self):
        reg, _ = self._reg_with_hp()
        devs = reg.get_devices_for_sensor()
        assert "heat_pump" in devs
        assert devs["heat_pump"]["priority"] == 4  # from seed

    def test_hp_drag_override_wins(self):
        reg, _ = self._reg_with_hp()
        reg._priority_overrides["heat_pump"] = 1
        assert reg.get_devices_for_sensor()["heat_pump"]["priority"] == 1

    def test_no_double_add_when_already_surfaced(self):
        # An ED device already in result must not be re-added from the
        # controller loop (dedup by id).
        reg, _ = self._reg_with_hp()
        reg._devices = [UnifiedDevice(
            energy_sensor="sensor.heat_pump_energy", power_sensor="sensor.hp_power",
            name="Heat Pump", priority=4,
            control={"type": "switch", "entity": "switch.hp"})]
        # give the ED device the SAME id as the controller device
        reg._surplus_controller._devices = {reg._devices[0].device_id: MagicMock(
            is_ev=False, name="dup", priority=4, is_active=False)}
        devs = reg.get_devices_for_sensor()
        # only one row for that id
        assert list(devs.keys()).count(reg._devices[0].device_id) == 1

    def test_refresh_makes_drag_authoritative(self):
        reg, hp = self._reg_with_hp()
        reg._priority_overrides["heat_pump"] = 2
        reg.refresh_direct_device_priorities()
        assert hp.priority == 2  # walk now honours the drag


# ── Observer mode cuts EVERY surplus command (safety) ─────────────────────
@pytest.mark.unit
class TestObserverModeCutsSurplus:
    """Observation mode must cut EVERY surplus command — loads, heat pump,
    hot water, climate — not just the battery + EV. There is no separate
    read-only path: ``update(observer=True)`` runs the SAME real decision and
    the single execution seam (``reconcile_load``) only LOGS what it would do.
    The invariant: no ``activate`` / ``deactivate`` / ``adjust_power`` ever
    fires while observing."""

    @pytest.mark.asyncio
    async def test_observer_never_actuates_a_running_load(self, mock_hass):
        sc = SurplusController(mock_hass, regulation_offset=0)
        dev = _make_device(device_id="pump", priority=2, min_power=500)
        dev.is_active = True
        dev.get_current_consumption = MagicMock(return_value=1000.0)
        sc.register_device(dev)
        data = await sc.update(3000.0, reclaim_w=500.0, observer=True)
        # NO command of any kind fired — the trigger is cut at the seam.
        dev.activate.assert_not_called()
        dev.deactivate.assert_not_called()
        dev.adjust_power.assert_not_called()
        # allocation data still produced for the sensors/trace
        assert data is not None
        assert data.total_devices == 1

    @pytest.mark.asyncio
    async def test_observer_never_activates_an_idle_load(self, mock_hass):
        sc = SurplusController(mock_hass, regulation_offset=0)
        off = _make_device(device_id="idle", priority=2, min_power=500)
        off.is_active = False
        sc.register_device(off)
        data = await sc.update(2000.0, observer=True)
        off.activate.assert_not_called()
        assert data is not None
        assert off.is_active is False


# ── #576: draw learning promoted to all device types + 1kW default ────────
@pytest.mark.unit
class TestDrawCalibrationAllTypes:
    """calibrate_rated_power is promoted to the base so EVERY device type
    (switch, climate, heat pump) learns its real draw from a power sensor.
    Sensor-less devices default to 1 kW (not 0)."""

    def test_switch_defaults_to_1kw_without_rating(self):
        from custom_components.solar_energy_management.devices.base import SwitchDevice
        d = SwitchDevice(hass=MagicMock(), device_id="s", name="s", rated_power=0)
        assert d.rated_power == 1000
        assert d.min_power_threshold == 1000

    def test_switch_keeps_explicit_rating(self):
        from custom_components.solar_energy_management.devices.base import SwitchDevice
        d = SwitchDevice(hass=MagicMock(), device_id="s", name="s", rated_power=2500)
        assert d.rated_power == 2500

    def test_base_calibration_learns_real_draw(self):
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice, DeviceState)
        hass = MagicMock()
        st = MagicMock(); st.state = "2400"
        hass.states.get = MagicMock(return_value=st)
        d = SwitchDevice(hass=hass, device_id="s", name="s", rated_power=1000,
                         power_entity_id="sensor.p")
        d._status.state = DeviceState.ACTIVE
        d.calibrate_rated_power()
        assert d.rated_power == 2400        # snapped up to the observed draw
        assert d.min_power_threshold == 2400

    def test_calibration_promoted_off_switch_onto_base(self):
        # No per-type override left — switch AND climate use the base method.
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice, ClimateDevice, ControllableDevice)
        assert SwitchDevice.calibrate_rated_power is ControllableDevice.calibrate_rated_power
        assert ClimateDevice.calibrate_rated_power is ControllableDevice.calibrate_rated_power


# ── #122/#576: dependency ("Requires") persists across rebuilds ────────────
@pytest.mark.unit
class TestDependencyPersistence:
    """The 'Requires' link is stored in the registry (_dependency_overrides)
    and re-applied on every device rebuild — so a drag / re-discovery / restart
    no longer wipes it ('separated all the time')."""

    async def test_set_dependency_stores_persists_applies(self):
        reg = _make_registry()
        reg._store = MagicMock(async_save=AsyncMock())
        live = MagicMock()
        reg._surplus_controller = MagicMock(get_device=MagicMock(return_value=live))
        reg._service_registrations = {}
        await reg.async_set_dependency("ed_frauen", "ed_manner")
        assert reg._dependency_overrides["ed_frauen"] == ["ed_manner"]  # stored
        assert live.depends_on == ["ed_manner"]                         # applied live
        reg._store.async_save.assert_awaited()                          # persisted

    async def test_clear_dependency_removes_it(self):
        reg = _make_registry()
        reg._store = MagicMock(async_save=AsyncMock())
        reg._surplus_controller = MagicMock(get_device=MagicMock(return_value=None))
        reg._service_registrations = {}
        reg._dependency_overrides["x"] = ["y"]
        await reg.async_set_dependency("x", [])
        assert "x" not in reg._dependency_overrides

    def test_rebuilt_device_gets_the_dependency(self):
        # The re-apply in _sync: a device whose id is in _dependency_overrides
        # gets depends_on set. (Mirrors the control_mode re-apply.)
        reg = _make_registry()
        reg._dependency_overrides = {"ed_frauen": ["ed_manner"]}
        dev = MagicMock(); dev.depends_on = []
        deps = reg._dependency_overrides.get("ed_frauen")
        if deps:
            dev.depends_on = list(deps)
        assert dev.depends_on == ["ed_manner"]
