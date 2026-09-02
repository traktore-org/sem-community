"""#896 — the shedder is bounded by what the meter says and by what it owns.

Forum #30: an EV that SEM does not manage held the 15-minute grid average
above the emergency level, and emergency shedding switched off one circuit
after another — the HA host's own supply included — until the house was dark.

Two root causes, one fix:

1. **The shedder judged every shed against the 15-minute average.** A shed
   cannot move a rolling average for minutes, so the average kept saying
   "still over" and the shedder kept answering "shed another". The need is
   now read from the LIVE meter: ``grid_import_w − (target − hysteresis)``.
   Under the aim → hold, whatever the average says; the average is the past
   and no switch can undo the past.

2. **The shedder had no model of its own authority.** When the load driving
   the peak is not SEM's, no amount of shedding helps. Before the first
   switch is thrown the plan asks whether ALL of what SEM may shed would
   bring the meter under the target; when it would not, it sheds nothing
   and files a Repair naming the uncontrolled kilowatts instead.

And a shed is never silent: a persistent notification per episode, updated
in place, dismissed when the last load is restored.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.const import (
    DOMAIN,
    LoadManagementState,
)
from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)

LM = "custom_components.solar_energy_management.features.load_management"
IR = "custom_components.solar_energy_management.coordinator.repair_issues.ir"
PN = "homeassistant.components.persistent_notification"


@pytest.fixture
def lm(mock_hass):
    """A shedder with a 5 kW target, 0.3 kW hysteresis (aim 4.7 kW), 6 kW
    emergency level — the forum reporter's ladder."""
    entry = MagicMock()
    entry.options = {
        "load_management_enabled": True,
        "target_peak_limit": 5.0,
        "warning_peak_level": 4.5,
        "emergency_peak_level": 6.0,
        "peak_hysteresis": 0.3,
    }
    entry.entry_id = "test_entry"
    with patch(f"{LM}.LoadDeviceDiscovery") as MockDiscovery, patch(f"{LM}.Store"):
        disc = MagicMock()
        disc.turn_off_device = AsyncMock(return_value=True)
        disc.turn_on_device = AsyncMock(return_value=True)
        MockDiscovery.return_value = disc
        coord = LoadManagementCoordinator(mock_hass, entry)
        coord._device_discovery = disc
        # Per-device live state, keyed by switch entity. A test flips a
        # device off here after a shed to model the wire responding.
        coord._live = {}
        disc.get_device_current_state = MagicMock(
            side_effect=lambda info: coord._live.get(
                info.get("switch_entity"), {"is_on": False, "current_power": 0}
            )
        )
        state = MagicMock()
        state.state = "on"
        mock_hass.states.get = MagicMock(return_value=state)
        yield coord


def _load(lm, did, *, priority, power_w, on=True, on_for_s=None, critical=False):
    """A plain peak_only load the shedder owns (legacy switch shape, so the
    shed goes through ``turn_off_device`` like the other LM tests)."""
    lm._devices[did] = {
        "switch_entity": f"switch.{did}",
        "friendly_name": did.replace("_", " ").title(),
        "power_rating": power_w / 1000,
        "is_available": True,
        "priority": priority,
        "is_critical": critical,
        "is_controllable": True,
    }
    if on_for_s is not None:
        lm._devices[did]["last_turned_on"] = dt_util.now() - timedelta(seconds=on_for_s)
    lm._live[f"switch.{did}"] = {"is_on": on, "current_power": power_w if on else 0}


async def _pass(lm, state, *, avg_kw, import_w):
    """One coordinator cycle as the shedder sees it: the rolling average
    (what the state machine reads) and the live meter (what the plan reads)."""
    lm._state = state
    lm._last_grid_import_w = float(import_w)
    await lm._execute_load_management(avg_kw, avg_kw)


# ---------------------------------------------------------------------------
# 1. The need comes from the meter, not the average
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state, avg_kw",
    [
        (LoadManagementState.EMERGENCY, 6.5),   # forum #30: the average is stuck high
        (LoadManagementState.SHEDDING, 5.5),
    ],
)
async def test_holds_when_the_meter_is_already_under_the_aim(lm, state, avg_kw):
    """The rolling average says 'over', the live meter says 4.0 kW — the
    previous shed already worked. Shedding again is what darkened the house."""
    _load(lm, "pool_pump", priority=9, power_w=2000)
    _load(lm, "dryer", priority=8, power_w=1500)
    with patch(f"{IR}.async_create_issue") as create:
        await _pass(lm, state, avg_kw=avg_kw, import_w=4000)
    assert lm._devices_shed == []
    assert lm.get_load_management_data()["shed_path"] == "held:under_aim"
    create.assert_not_called()


@pytest.mark.asyncio
async def test_progressive_need_is_read_from_the_meter(lm):
    """avg 5.5 kW used to mean 'need 0.8 kW'. The meter says 7.0 kW → the
    need is 2.3 kW, and the telemetry says so."""
    _load(lm, "pool_pump", priority=9, power_w=2000)
    await _pass(lm, LoadManagementState.SHEDDING, avg_kw=5.5, import_w=7000)
    data = lm.get_load_management_data()
    assert data["shed_need_w"] == pytest.approx(2300)
    assert lm._devices_shed == ["pool_pump"]


# ---------------------------------------------------------------------------
# 2. Bounded blast radius — never past the need, in priority order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emergency_sheds_only_what_the_need_requires(lm):
    """8 kW at the meter, aim 4.7 → need 3.3 kW. The two highest-priority
    loads cover it (3.5 kW); the third stays on. EMERGENCY may throw several
    switches in one pass — it is bounded by the need, not by a timer."""
    _load(lm, "pool_pump", priority=9, power_w=2000)
    _load(lm, "dryer", priority=8, power_w=1500)
    _load(lm, "fridge_garage", priority=3, power_w=1000)
    await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=7.0, import_w=8000)
    assert lm._devices_shed == ["pool_pump", "dryer"]
    assert lm.get_load_management_data()["shed_path"] == "shed:2"


@pytest.mark.asyncio
async def test_progressive_keeps_one_shed_per_pass(lm):
    """SHEDDING is not an emergency: one switch, then wait for the meter."""
    _load(lm, "pool_pump", priority=9, power_w=2000)
    _load(lm, "dryer", priority=8, power_w=1500)
    await _pass(lm, LoadManagementState.SHEDDING, avg_kw=5.5, import_w=8000)
    assert lm._devices_shed == ["pool_pump"]


# ---------------------------------------------------------------------------
# 3. Futility — the peak is not SEM's to fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_futile_sheds_nothing_and_files_a_repair(lm):
    """9 kW at the meter, 3.5 kW is everything SEM may shed: even a dark
    house sits at 5.5 kW, above the 5 kW target. That peak belongs to a load
    SEM does not control — say so, and leave the lights on."""
    _load(lm, "pool_pump", priority=9, power_w=2000)
    _load(lm, "dryer", priority=8, power_w=1500)
    with patch(f"{IR}.async_create_issue") as create:
        await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=8.0, import_w=9000)
    assert lm._devices_shed == []
    data = lm.get_load_management_data()
    assert data["shed_path"] == "futile"
    assert data["shed_futile"] is True
    assert data["uncontrolled_w"] == pytest.approx(5500)
    create.assert_called_once()
    kw = create.call_args.kwargs
    assert kw["translation_key"] == "load_shed_futile"
    assert kw["issue_id"] == "load_shed_futile"
    assert kw["translation_placeholders"] == {
        "grid_import_kw": "9.0",
        "target_kw": "5.0",
        "uncontrolled_kw": "5.5",
    }


@pytest.mark.asyncio
async def test_futility_is_filed_once_per_episode_and_cleared_when_it_passes(lm):
    _load(lm, "pool_pump", priority=9, power_w=2000)
    _load(lm, "dryer", priority=8, power_w=1500)
    with patch(f"{IR}.async_create_issue") as create, \
            patch(f"{IR}.async_delete_issue") as delete:
        await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=8.0, import_w=9000)
        await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=8.0, import_w=9000)
        assert create.call_count == 1
        delete.assert_not_called()
        # The oven finished: 6 kW at the meter is reachable → the repair goes,
        # and the plan sheds again.
        await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=8.0, import_w=6000)
    delete.assert_called_once()
    assert delete.call_args.args[-1] == "load_shed_futile"
    assert lm._devices_shed == ["pool_pump"]
    assert lm.get_load_management_data()["shed_futile"] is False


@pytest.mark.asyncio
async def test_anti_flicker_blocked_loads_still_count_as_authority(lm):
    """A 3 kW load that switched on 10 s ago cannot be shed yet (min on
    300 s) — but it IS SEM's, so 6 kW at the meter is not futile. Wait,
    do not file a repair, do not shed the fridge instead."""
    _load(lm, "heat_rod", priority=9, power_w=3000, on_for_s=10)
    with patch(f"{IR}.async_create_issue") as create:
        await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=6.5, import_w=6000)
    assert lm._devices_shed == []
    create.assert_not_called()
    data = lm.get_load_management_data()
    assert data["shed_path"] == "waiting:anti_flicker"
    assert data["shed_sheddable_w"] == pytest.approx(3000)


@pytest.mark.asyncio
async def test_a_surplus_managed_load_is_sem_authority_not_uncontrolled(lm):
    """The surplus controller sheds its own actives on SHEDDING/EMERGENCY
    (#649: one per cycle, then all of them). A 3 kW surplus-mode heat rod
    is therefore SEM's to shed — through the other engine, not this one —
    and 7 kW at the meter is NOT futile: a dark house sits at 4 kW, under
    the 5 kW target. Counting it as "uncontrolled" filed a Repair naming
    kilowatts SEM was switching off on the very same cycle."""
    _load(lm, "heat_rod", priority=9, power_w=3000)
    lm._devices["heat_rod"]["control_mode"] = "surplus"
    lm._devices["heat_rod"]["surplus_managed"] = True
    with patch(f"{IR}.async_create_issue") as create:
        await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=6.5, import_w=7000)
    # Never thrown from here — the surplus controller owns that switch.
    assert lm._devices_shed == []
    lm._device_discovery.turn_off_device.assert_not_awaited()
    create.assert_not_called()
    data = lm.get_load_management_data()
    assert data["shed_futile"] is False
    assert data["shed_sheddable_w"] == pytest.approx(3000)
    assert data["uncontrolled_w"] == pytest.approx(4000)
    assert data["shed_path"] == "waiting:surplus_controller"


@pytest.mark.asyncio
async def test_surplus_authority_does_not_hide_a_real_futility(lm):
    """Same heat rod, 9 kW at the meter: even with the rod off the house
    sits at 6 kW, above target — that IS a load SEM does not control."""
    _load(lm, "heat_rod", priority=9, power_w=3000)
    lm._devices["heat_rod"]["control_mode"] = "surplus"
    lm._devices["heat_rod"]["surplus_managed"] = True
    with patch(f"{IR}.async_create_issue") as create:
        await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=8.0, import_w=9000)
    create.assert_called_once()
    assert create.call_args.kwargs["translation_placeholders"]["uncontrolled_kw"] == "6.0"


# ---------------------------------------------------------------------------
# 4. A shed is never silent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_shed_episode_raises_a_notification_and_dismisses_on_restore(lm):
    _load(lm, "pool_pump", priority=9, power_w=2000)
    with patch(f"{PN}.async_create") as create, patch(f"{PN}.async_dismiss") as dismiss:
        await _pass(lm, LoadManagementState.SHEDDING, avg_kw=5.5, import_w=6000)
        assert lm._devices_shed == ["pool_pump"]
        create.assert_called_once()
        kw = create.call_args.kwargs
        assert kw["notification_id"] == "sem_load_shed"
        assert "Pool Pump" in create.call_args.args[1]
        assert "6.0" in create.call_args.args[1] and "5.0" in create.call_args.args[1]
        events = [
            c for c in lm.hass.bus.async_fire.call_args_list
            if c.args[0] == f"{DOMAIN}_notification" and c.args[1].get("event") == "load_shed"
        ]
        assert len(events) == 1
        assert events[0].args[1]["devices"] == ["pool_pump"]

        # The wire responded, the peak passed, NORMAL restores the pump —
        # and the notification goes with the last restored load.
        lm._live["switch.pool_pump"] = {"is_on": False, "current_power": 0}
        lm._devices["pool_pump"]["_pre_shed_was_on"] = True
        lm._devices["pool_pump"]["last_turned_off"] = dt_util.now() - timedelta(seconds=900)
        dismiss.assert_not_called()
        await _pass(lm, LoadManagementState.NORMAL, avg_kw=3.0, import_w=3000)
    assert lm._devices_shed == []
    dismiss.assert_called_once()
    assert dismiss.call_args.args[-1] == "sem_load_shed"


# ---------------------------------------------------------------------------
# 5. What SEM switched off, SEM switches back on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_load_sem_shed_stays_tracked_until_restored(lm):
    """``_cleanup_shed_list`` (#40) evicted every shed load on the very next
    cycle: the switch read *off*, and off looked like "powered off
    naturally". So nothing SEM switched off was ever switched back on — the
    forum's dark house stayed dark. A load is ours to restore until it has
    RUN again since the shed; only a load that ran and then stopped on its
    own has nothing left for us to restore."""
    _load(lm, "pool_pump", priority=9, power_w=2000)
    await _pass(lm, LoadManagementState.SHEDDING, avg_kw=5.5, import_w=6000)
    assert lm._devices_shed == ["pool_pump"]

    lm._live["switch.pool_pump"] = {"is_on": False, "current_power": 0}  # wire responded
    lm._cleanup_shed_list()
    assert lm._devices_shed == ["pool_pump"]

    lm._live["switch.pool_pump"] = {"is_on": True, "current_power": 2000}  # somebody switched it on
    lm._cleanup_shed_list()
    assert lm._devices_shed == ["pool_pump"]  # the #649 contract: on → still tracked

    lm._live["switch.pool_pump"] = {"is_on": False, "current_power": 0}  # ...and it finished
    lm._cleanup_shed_list()
    assert lm._devices_shed == []


# ---------------------------------------------------------------------------
# 6. The dead constant is gone
# ---------------------------------------------------------------------------


def test_the_dead_critical_protection_constant_is_deleted():
    """``DEFAULT_CRITICAL_DEVICE_PROTECTION = True`` had zero readers — a
    promise in the constants file that nothing kept. ``is_critical`` on the
    device row is the protection; there is no second switch."""
    from custom_components.solar_energy_management.consts import core
    assert not hasattr(core, "DEFAULT_CRITICAL_DEVICE_PROTECTION")
    from custom_components.solar_energy_management import const
    assert not hasattr(const, "DEFAULT_CRITICAL_DEVICE_PROTECTION")
