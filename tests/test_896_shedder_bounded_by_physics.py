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


def _load(lm, did, *, priority, power_w, on=True, on_for_s=None, critical=False,
          measured=True):
    """A plain peak_only load the shedder owns (legacy switch shape, so the
    shed goes through ``turn_off_device`` like the other LM tests).

    ``measured=False`` is an energy-only load: a switch, a kWh counter, no
    power entity — the wire says nothing about its draw, only its rating."""
    lm._devices[did] = {
        "switch_entity": f"switch.{did}",
        "friendly_name": did.replace("_", " ").title(),
        # WATTS — the same number the Control card shows for the device
        "power_rating": power_w,
        "is_available": True,
        "priority": priority,
        "is_critical": critical,
        "is_controllable": True,
    }
    if on_for_s is not None:
        lm._devices[did]["last_turned_on"] = dt_util.now() - timedelta(seconds=on_for_s)
    lm._live[f"switch.{did}"] = {
        "is_on": on,
        "current_power": (power_w if on else 0) if measured else 0,
        "power_known": measured,
    }


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


@pytest.mark.asyncio
async def test_an_energy_only_load_that_is_on_is_still_sheddable(lm):
    """A Shelly with a kWh counter and no power entity (the rig's towel
    heaters) reads 0 W on the control side whatever it draws. ON is ON:
    the plan takes its rating as the draw — 6 kW at the meter, a 1.2 kW
    heater on, the house sits at 4.8 kW without it — not futile, shed it.
    (Before #896 this load was shed; requiring a measured draw > 0 had
    silently taken it off the list.)"""
    _load(lm, "towel_heater", priority=9, power_w=1200, measured=False)
    with patch(f"{IR}.async_create_issue") as create:
        await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=6.5, import_w=6000)
    create.assert_not_called()
    assert lm._devices_shed == ["towel_heater"]
    data = lm.get_load_management_data()
    assert data["shed_sheddable_w"] == pytest.approx(1200)
    assert data["shed_path"] == "shed:1"


@pytest.mark.asyncio
async def test_a_measured_zero_is_a_zero(lm):
    """A heater whose thermostat is idle: switch on, meter says 0 W.
    Shedding it frees nothing — it is neither authority nor a candidate,
    and the rating is not a substitute for a reading that exists."""
    _load(lm, "idle_heater", priority=9, power_w=0)
    lm._devices["idle_heater"]["power_rating"] = 1200
    with patch(f"{IR}.async_create_issue"):
        await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=6.5, import_w=6000)
    assert lm._devices_shed == []
    assert lm.get_load_management_data()["shed_sheddable_w"] == 0


def test_the_control_state_says_whether_the_draw_was_measured(mock_hass):
    """``get_device_current_state`` is where the plan reads the draw; it has
    to say whether that 0 came from a meter or from the absence of one."""
    from custom_components.solar_energy_management.features.load_device_discovery import (
        LoadDeviceDiscovery,
    )
    disc = LoadDeviceDiscovery.__new__(LoadDeviceDiscovery)
    disc.hass = mock_hass
    on = MagicMock(); on.state = "on"; on.last_updated = None
    zero = MagicMock(); zero.state = "0.0"; zero.last_updated = None
    dark = MagicMock(); dark.state = "unavailable"; dark.last_updated = None
    states = {"switch.a": on, "sensor.a_power": zero, "sensor.b_power": dark}
    mock_hass.states.get = MagicMock(side_effect=lambda e: states.get(e))
    measured = disc.get_device_current_state(
        {"switch_entity": "switch.a", "power_entity": "sensor.a_power"})
    assert measured["is_on"] is True
    assert measured["power_known"] is True
    assert measured["current_power"] == 0
    no_entity = disc.get_device_current_state({"switch_entity": "switch.a"})
    assert no_entity["power_known"] is False
    unavailable = disc.get_device_current_state(
        {"switch_entity": "switch.a", "power_entity": "sensor.b_power"})
    assert unavailable["power_known"] is False


def test_the_shedder_sees_the_rating_the_card_shows():
    """The LM row's ``power_rating`` used to be the LIVE sensor tick — 0 W for
    a load that is off, and 0 W forever for an energy-only load — while the
    Control card showed the learned rating from ``_rated_power_for``. Two
    numbers for one device; the shedder's estimate of what a switch would
    free must be the card's number, in the card's unit (watts)."""
    from .test_895_consent_reaches_the_shedder import DID, _registry

    reg = _registry({DID: "peak_only"})
    reg._sync_to_load_manager()
    row = reg._load_manager._devices[DID]
    assert row["power_rating"] == 1000.0, (
        "the LM row carries _rated_power_for (the card's rating, W), not "
        "_get_power_rating (the live sensor tick)"
    )
    assert row["power_rating"] == reg.get_devices_for_sensor()[DID]["power_rating"]


@pytest.mark.asyncio
async def test_observer_mode_names_what_it_withheld(lm):
    """Observer mode throws no switch — and must say so. The path used to
    read ``waiting:shed_delay`` (a delay that was never the reason), so a
    rig in observer mode could not be told apart from a real shed delay.
    The plan is still made; the verdict names the loads it would have shed."""
    lm._observer_mode = True
    _load(lm, "heater_a", priority=9, power_w=1500)
    _load(lm, "heater_b", priority=8, power_w=1500)
    with patch(f"{IR}.async_create_issue") as create:
        await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=6.5, import_w=6200)
    create.assert_not_called()
    assert lm._devices_shed == []
    assert lm._device_discovery.turn_off_device.await_count == 0
    data = lm.get_load_management_data()
    # need 1500 W: heater_a alone covers it
    assert data["shed_path"] == "observer:withheld:1"
    assert data["shed_sheddable_w"] == pytest.approx(3000)


class TestTheShedderKnowsEveryConsentedLoad:
    """``peak_only`` means "SEM may shed this to protect the peak". The surplus
    controller never sheds a peak_only load ("the load manager owns their
    peak shedding") — and the load manager's roster was built from the
    Energy Dashboard list alone, so a load added with
    ``register_surplus_device`` and set to peak_only was shed by NOBODY. Its
    toggle was a promise nothing kept, and the plan counted its kilowatts as
    uncontrolled. The roster the shedder sees is the roster the card shows."""

    SPEC = {
        "entity_id": "switch.heizband",
        "name": "Heizband",
        "priority": 7,
        "rated_power": 500,
        "power_entity_id": None,
        "energy_entity_id": "sensor.heizband_energy",
        "control_mode": "peak_only",
        "depends_on": [],
        "device_type": "switch",
    }

    def _reg(self, spec=None):
        from .test_895_consent_reaches_the_shedder import _registry

        reg = _registry()
        reg._service_registrations = {"test_heizband": dict(spec or self.SPEC)}
        reg._control_mode_overrides["test_heizband"] = (spec or self.SPEC)["control_mode"]
        reg._priority_overrides = {}
        return reg

    def test_a_service_registered_peak_only_load_is_on_the_roster(self):
        from custom_components.solar_energy_management.features.device_axes import may_actuate

        reg = self._reg()
        reg._sync_to_load_manager()
        row = reg._load_manager._devices["test_heizband"]
        assert row["switch_entity"] == "switch.heizband"
        assert row["control"] == {"type": "switch", "entity": "switch.heizband"}
        assert row["control_mode"] == "peak_only"
        assert may_actuate(row) is True
        assert row["energy_entity"] == "sensor.heizband_energy"
        assert row["priority"] == 7
        assert row["power_rating"] == 1000.0, "the card's rating, in watts"
        assert row["surplus_managed"] is False, "no live surplus object → the LM sheds it"

    def test_the_row_carries_the_users_drag(self):
        reg = self._reg()
        reg._priority_overrides = {"test_heizband": 2}
        reg._sync_to_load_manager()
        assert reg._load_manager._devices["test_heizband"]["priority"] == 2

    def test_an_ed_row_for_the_same_switch_is_folded_into_the_registration(self):
        """The card already suppresses the ED twin of a service-registered
        switch; two LM rows on one switch would be two shedders on one load."""
        from custom_components.solar_energy_management.features.device_registry import UnifiedDevice

        reg = self._reg()
        reg._devices = [
            UnifiedDevice(
                energy_sensor="sensor.heizband_energy",
                power_sensor=None,
                name="Heizband (ED)",
                priority=5,
                control={"type": "switch", "entity": "switch.heizband"},
            )
        ]
        reg._sync_to_load_manager()
        rows = reg._load_manager._devices
        assert "test_heizband" in rows
        assert [d for d in rows if d.startswith("energy_dashboard_")] == []

    def test_a_stale_ed_twin_is_pruned_on_the_next_sync(self):
        """A row the sync no longer derives must not survive from an earlier
        pass — the prune is keyed on what THIS pass wrote."""
        from custom_components.solar_energy_management.features.device_registry import UnifiedDevice

        reg = self._reg()
        reg._devices = [
            UnifiedDevice(
                energy_sensor="sensor.heizband_energy",
                power_sensor=None,
                name="Heizband (ED)",
                priority=5,
                control={"type": "switch", "entity": "switch.heizband"},
            )
        ]
        reg._load_manager._devices["energy_dashboard_heizband"] = {"stale": True}
        changed = reg._sync_to_load_manager()
        assert "energy_dashboard_heizband" not in reg._load_manager._devices
        assert changed is True


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


# ---------------------------------------------------------------------------
# 7. The verdict reaches the sensor
# ---------------------------------------------------------------------------
#
# ``LoadManager.get_load_management_data()`` is a rich dict and
# ``_build_load_management_data`` copies a HAND-PICKED subset of it into
# ``LoadManagementData`` — so every telemetry key added to the dict since has
# died at that hop. #657 found ``devices`` dead there; #433's four
# ``*_path`` keys ("Four new keys on sensor.sem_load_management_status", the
# CHANGELOG says) never reached a sensor either; the #896 verdict would have
# followed. The USER_GUIDE tells the user to read ``shed_path`` off the
# load-management sensor — this is what makes that sentence true.

from custom_components.solar_energy_management.coordinator import SEMCoordinator  # noqa: E402
from custom_components.solar_energy_management.coordinator.types import (  # noqa: E402
    PowerReadings,
    SEMData,
)

# What the LM dict reports and the sensor must carry. The verdict strings are
# low-churn (they change on transitions) and worth a history row; the watt
# figures wiggle every cycle of an episode and stay live-only (#829).
_VERDICT_KEYS = ("shed_path", "shed_futile",
                 "state_decision_path", "process_path", "action_path", "last_error")
_LIVE_ONLY_KEYS = ("shed_need_w", "shed_sheddable_w", "uncontrolled_w")
_TELEMETRY_KEYS = _VERDICT_KEYS + _LIVE_ONLY_KEYS

# LM-dict keys that are published under another name, or on purpose not at
# all. A key that is neither here nor in ``to_dict()`` is the #657/#433 bug
# again — add it to the copy, not to this list.
_RENAMED = {
    "state": "load_management_status",
    "controllable_devices": "controllable_devices_count",
    "devices_shed_list": "loads_currently_shed",
    "devices": "load_management_devices",
}
_NOT_PUBLISHED = {
    "warning_level": "config — diagnose's option set carries warning_peak_level",
    "emergency_level": "config — diagnose's option set carries emergency_peak_level",
    "enabled": "config — diagnose's option set carries load_management_enabled",
    "total_devices": "len(devices); the card counts the table it is given",
    "devices_shed": "len(devices_shed_list); the sensor joins the list",
}


def _coordinator_over(lm):
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = {}
    coord.hass = MagicMock()
    coord._load_manager = lm
    return coord


class TestTheVerdictReachesTheSensor:

    @pytest.mark.asyncio
    async def test_the_coordinator_publishes_the_verdict(self, lm):
        """A futile pass on the real shedder → the same verdict and numbers
        on ``coordinator.data``, under the names the docs use."""
        _load(lm, "pool_pump", priority=9, power_w=2000)
        _load(lm, "dryer", priority=8, power_w=1500)
        with patch(f"{IR}.async_create_issue"):
            await _pass(lm, LoadManagementState.EMERGENCY, avg_kw=8.0, import_w=9000)

        lm_data = _coordinator_over(lm)._build_load_management_data(PowerReadings())
        published = SEMData(load_management=lm_data).to_dict()

        assert published["shed_path"] == "futile"
        assert published["shed_futile"] is True
        assert published["shed_need_w"] == pytest.approx(9000 - 4700)
        assert published["shed_sheddable_w"] == pytest.approx(3500)
        assert published["uncontrolled_w"] == pytest.approx(5500)
        # #433's telemetry rides the same copy. ``_pass`` enters below the
        # state machine, so only the action path is decided here; the
        # ratchet below pins the other three.
        assert published["action_path"] == "emergency_shedding"
        assert published["last_error"] is None

    def test_every_key_the_load_manager_reports_is_published(self, lm):
        """The ratchet: a key ``get_load_management_data()`` returns is either
        on ``coordinator.data`` (same name or a listed rename) or listed here
        with the reason it stays behind."""
        reported = set(lm.get_load_management_data())
        published = set(SEMData(
            load_management=_coordinator_over(lm)._build_load_management_data(
                PowerReadings())
        ).to_dict())
        dead = sorted(
            k for k in reported
            if k not in published
            and _RENAMED.get(k) not in published
            and k not in _NOT_PUBLISHED
        )
        assert dead == [], f"reported by the load manager, published by nobody: {dead}"

    def test_the_sensor_carries_the_verdict(self, mock_coordinator):
        from homeassistant.components.sensor import SensorEntityDescription
        from custom_components.solar_energy_management.sensor import SEMSolarSensor

        mock_coordinator.data = {
            "load_management_status": "emergency",
            "shed_path": "futile", "shed_futile": True,
            "shed_need_w": 4300, "shed_sheddable_w": 3500, "uncontrolled_w": 5500,
            "state_decision_path": "emergency", "process_path": "state_stable:emergency",
            "action_path": "emergency_shedding", "last_error": None,
        }
        sensor = SEMSolarSensor(
            coordinator=mock_coordinator,
            description=SensorEntityDescription(
                key="load_management_status", name="lm", icon="mdi:flash"),
            entry_id="test_entry_id",
        )
        attrs = sensor.extra_state_attributes
        for key in _TELEMETRY_KEYS:
            assert attrs[key] == mock_coordinator.data[key], key
        for key in _VERDICT_KEYS:
            assert key not in sensor._unrecorded_attributes, key
        for key in _LIVE_ONLY_KEYS:
            assert key in sensor._unrecorded_attributes, key

    def test_diagnose_lists_the_verdict(self):
        """The Diagnose modal renders ONLY what its slicer lists. The set is
        a local of ``async_setup_entry``, so read the literal out of the
        source (the #454 pattern)."""
        import ast
        import pathlib
        import re
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "__init__.py").read_text(encoding="utf-8")
        m = re.search(r"_DIAGNOSE_LOAD_MGMT_STATE = (\{.*?\})", src, re.S)
        assert m, "retarget this scan — the slicer moved"
        listed = ast.literal_eval(m.group(1))
        missing = sorted(set(_TELEMETRY_KEYS) - listed)
        assert missing == [], f"not in the Diagnose modal's load_management section: {missing}"

    def test_the_user_guide_names_the_sensor_it_is_on(self):
        import pathlib
        guide = (pathlib.Path(__file__).resolve().parent.parent
                 / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
        assert "`sensor.sem_load_management_status`" in guide
        assert "`shed_path`" in guide
