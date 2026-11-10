"""#1321 — a load's one-off override: Boost (force) and pause (skip).

The decision is ONE clause in ``compute_load_intent`` (3e), fed by
``_override_action``. Since #1335 the three layers are the only load
engine, so the clause acts on every install: ``reconcile_load`` switches
the load, and observer mode withholds it.
"""
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.const import LoadManagementState
from custom_components.solar_energy_management.coordinator import plan_override as po
from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    OVERRIDE_SOURCE, SurplusController, compute_load_intent,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode

FORCE = {"boiler": {"action": "force", "until": "14:30"}}
SKIP = {"boiler": {"action": "skip", "until": "14:30"}}


class _Load:
    """A switched load that counts writes."""

    def __init__(self, device_id="boiler", **kw):
        self.device_id = device_id
        self.name = device_id
        self.priority = kw.get("priority", 1)
        self.control_mode = kw.get("control_mode", DeviceControlMode.SURPLUS)
        self.is_enabled = True
        self.managed_externally = False
        self.device_type = MagicMock(value="switch")
        self.min_power_threshold = 1000.0
        self.rated_power = 1000.0
        self.daily_max_runtime_reached = kw.get("daily_max_runtime_reached", False)
        self.daily_targets_met = False
        self.stop_condition_met = kw.get("stop_condition_met", False)
        self.stop_entity = None
        self.stop_at = 0.0
        self.has_runtime_deficit = False
        self.remaining_daily_runtime_sec = 0
        self.battery_eligible_overnight = False
        self.battery_assist_enabled = False
        self.top_up_policy = "solar_only"
        self.runs_without_surplus = kw.get("runs_without_surplus", False)
        self.vacation = kw.get("vacation", False)
        self._offpeak_forced = False
        self._offpeak_forced_date = None
        self._batt_overnight_forced = False
        self._batt_overnight_forced_date = None
        self._active = kw.get("is_active", False)
        self.status = MagicMock()
        self.status.allocated_power_w = 0.0
        self.activations = 0
        self.deactivations = 0

    @property
    def is_active(self):
        return self._active

    @property
    def needs_offpeak_activation(self):
        return False

    def can_activate(self):
        return True

    def can_deactivate(self):
        return True

    def get_current_consumption(self):
        return self.rated_power if self._active else 0.0

    def record_activated(self):
        pass

    def record_deactivated(self):
        pass

    def reset_surplus_timer(self):
        pass

    async def activate(self, watts):
        self.activations += 1
        if self.vacation:          # a heat pump on vacation sends nothing
            return 0.0
        self._active = True
        return self.rated_power

    async def deactivate(self):
        self.deactivations += 1
        self._active = False

    async def adjust_power(self, watts):
        return self.get_current_consumption()


def _sc(dev, desired=True):
    sc = SurplusController(MagicMock())
    sc.register_device(dev)
    return sc


BOTH = pytest.mark.parametrize("desired", [True], ids=["layers"])


@pytest.mark.asyncio
@BOTH
async def test_a_forced_load_turns_on_without_sun(desired):
    dev = _Load()
    sc = _sc(dev, desired)
    await sc.update(available_power_w=0.0, load_overrides=FORCE)
    assert dev.is_active and dev.activations == 1


@pytest.mark.asyncio
@BOTH
async def test_a_paused_load_stays_off_in_full_sun(desired):
    dev = _Load()
    sc = _sc(dev, desired)
    await sc.update(available_power_w=5000.0, load_overrides=SKIP)
    assert not dev.is_active and dev.activations == 0


@pytest.mark.asyncio
@BOTH
async def test_a_pause_stops_a_running_load(desired):
    dev = _Load(is_active=True)
    sc = _sc(dev, desired)
    await sc.update(available_power_w=5000.0, load_overrides=SKIP)
    assert not dev.is_active and dev.deactivations == 1


@pytest.mark.asyncio
async def test_observer_sends_nothing(caplog):
    dev = _Load()
    sc = _sc(dev)
    with caplog.at_level(logging.INFO):
        await sc.update(available_power_w=0.0, observer=True, load_overrides=FORCE)
    assert dev.activations == 0 and not dev.is_active
    assert "WOULD ACTIVATE" in caplog.text and f"source={OVERRIDE_SOURCE}" in caplog.text


@pytest.mark.asyncio
@BOTH
async def test_vacation_blocks_a_forced_heat_pump(desired):
    dev = _Load(vacation=True)
    sc = _sc(dev, desired)
    await sc.update(available_power_w=0.0, load_overrides=FORCE)
    assert dev.activations == 0 and not dev.is_active


@pytest.mark.asyncio
@BOTH
async def test_a_peak_shed_still_sheds_a_forced_load(desired):
    dev = _Load(is_active=True)
    sc = _sc(dev, desired)
    await sc.update(available_power_w=0.0, peak_state=LoadManagementState.EMERGENCY,
                    load_overrides=FORCE)
    assert not dev.is_active


@pytest.mark.asyncio
@BOTH
async def test_a_peak_warning_holds_a_forced_start(desired):
    dev = _Load()
    sc = _sc(dev, desired)
    await sc.update(available_power_w=0.0, peak_state=LoadManagementState.WARNING,
                    load_overrides=FORCE)
    assert dev.activations == 0


@pytest.mark.asyncio
@BOTH
@pytest.mark.parametrize("gate", ["daily_max_runtime_reached", "stop_condition_met"])
async def test_the_cap_and_the_own_stop_win_over_a_force(desired, gate):
    dev = _Load(**{gate: True})
    sc = _sc(dev, desired)
    await sc.update(available_power_w=0.0, load_overrides=FORCE)
    assert not dev.is_active


@pytest.mark.asyncio
@BOTH
async def test_legionella_wins_over_a_pause(desired):
    dev = _Load(is_active=True, runs_without_surplus=True)
    sc = _sc(dev, desired)
    await sc.update(available_power_w=0.0, load_overrides=SKIP)
    assert dev.is_active and dev.deactivations == 0


@pytest.mark.asyncio
@BOTH
@pytest.mark.parametrize("mode", [DeviceControlMode.OFF, DeviceControlMode.PEAK_ONLY])
async def test_an_override_acts_only_in_smart_mode(desired, mode):
    dev = _Load(control_mode=mode)
    sc = _sc(dev, desired)
    await sc.update(available_power_w=0.0, load_overrides=FORCE)
    assert dev.activations == 0


@pytest.mark.asyncio
@BOTH
async def test_when_the_force_ends_the_load_returns_to_its_mode(desired):
    dev = _Load()
    sc = _sc(dev, desired)
    await sc.update(available_power_w=0.0, load_overrides=FORCE)
    assert dev.is_active
    for _ in range(3):   # the override is gone; no sun
        await sc.update(available_power_w=0.0)
    assert not dev.is_active
    assert not dev._offpeak_forced and not dev._batt_overnight_forced


@pytest.mark.asyncio
@BOTH
@pytest.mark.parametrize("sun,active", [(0.0, False), (5000.0, False), (5000.0, True), (0.0, True)])
async def test_no_override_changes_nothing(desired, sun, active):
    a, b = _Load(is_active=active), _Load(is_active=active)
    await _sc(a, desired).update(available_power_w=sun)
    await _sc(b, desired).update(available_power_w=sun, load_overrides={})
    assert (a.is_active, a.activations, a.deactivations) == \
        (b.is_active, b.activations, b.deactivations)


# ── Boost acts in production, through layer 3 (#1335) ─────────────────────
from custom_components.solar_energy_management.devices.base import (  # noqa: E402
    SwitchDevice,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (  # noqa: E402
    _Hass,
)

ZRH = ZoneInfo("Europe/Zurich")
T0 = datetime(2026, 11, 10, 21, 0, tzinfo=ZRH)       # night


def _real_boiler(observer=False):
    hass = _Hass()
    hass.set("switch.boiler", "off")
    dev = SwitchDevice(hass=hass, device_id="boiler", name="Boiler",
                       rated_power=2000.0, entity_id="switch.boiler")
    dev.control_mode = DeviceControlMode.SURPLUS       # Smart
    dev.observer_mode = observer
    sc = SurplusController(hass)
    assert sc.regulation_offset == 50                  # the production default
    sc.register_device(dev)
    return hass, sc, dev


def _payloads(overrides, now):
    """What the coordinator hands ``update()``: active overrides only."""
    p = po.status_payload(overrides, "boiler", now)
    return {"boiler": p} if p else {}


async def _night(sc, overrides, now, **kw):
    await sc.update(0.0, solar_w=0.0, is_night=True,
                    load_overrides=_payloads(overrides, now), **kw)


@pytest.mark.asyncio
async def test_boost_switches_a_smart_load_on_stays_on_at_night_and_stops_at_until():
    hass, sc, dev = _real_boiler()
    ovs = po.set_override({}, "boiler", "force", T0 + timedelta(minutes=30), T0)

    await _night(sc, ovs, T0)
    assert dev.is_active and dev._sem_commanded        # layer 3 switched it
    assert len(hass.calls("turn_on")) == 1
    rows = [r for r in sc.decision_log.records() if r["device_id"] == "boiler"]
    assert (rows[-1]["new"], rows[-1]["reason_code"]) == ("on", RC.LOAD_OVERRIDE_RUN)

    # solar 0 all night: neither "no sun" nor the deficit stop touches it
    for minute in range(1, 30):
        await _night(sc, ovs, T0 + timedelta(minutes=minute))
    assert dev.is_active and not hass.calls("turn_off")
    assert len(hass.calls("turn_on")) == 1

    # ``until`` passes: the override is no longer handed over
    dev._last_activated = datetime.now() - timedelta(hours=1)   # past min run
    late = T0 + timedelta(minutes=31)
    assert _payloads(ovs, late) == {}
    for _ in range(3):
        await _night(sc, ovs, late)
    assert not dev.is_active and len(hass.calls("turn_off")) == 1
    await _night(sc, ovs, late)
    assert len(hass.calls("turn_on")) == 1             # and it stays off


@pytest.mark.asyncio
async def test_boost_is_withheld_in_observer_mode():
    hass, sc, dev = _real_boiler(observer=True)
    ovs = po.set_override({}, "boiler", "force", T0 + timedelta(minutes=30), T0)
    for minute in range(3):
        await _night(sc, ovs, T0 + timedelta(minutes=minute), observer=True)
    hass.services.async_call.assert_not_awaited()
    assert not dev.is_active
    would = sc.observer_decisions["boiler"]
    assert (would["action"], would["source"]) == ("activate", OVERRIDE_SOURCE)


@pytest.mark.asyncio
async def test_a_pause_waits_for_the_minimum_run():
    """``skip`` is an ordinary stop: only Mode Off beats the minimum run."""
    hass, sc, dev = _real_boiler()
    for _ in range(3):
        await sc.update(5000.0, solar_w=6000.0)
    assert dev.is_active and dev.can_deactivate() is False
    await sc.update(5000.0, solar_w=6000.0, load_overrides=SKIP)
    assert dev.is_active and not hass.calls("turn_off")
    dev._last_activated = datetime.now() - timedelta(hours=1)
    await sc.update(5000.0, solar_w=6000.0, load_overrides=SKIP)
    assert not dev.is_active


@pytest.mark.asyncio
async def test_a_boosted_load_is_not_the_deficit_stops_to_end():
    """Two loads, the pool far short: the sun load goes, the Boost stays."""
    boost, sun = _Load("boiler", priority=2, is_active=True), _Load("pump", priority=1, is_active=True)
    sc = SurplusController(MagicMock())
    sc.register_device(boost)
    sc.register_device(sun)
    for _ in range(3):
        await sc.update(available_power_w=0.0, solar_w=3000.0, load_overrides=FORCE)
    assert boost.is_active and not sun.is_active


def test_the_clause_names_itself():
    run = compute_load_intent(_Load(), remaining_surplus_w=0.0, override="force")
    assert run.on and run.source == OVERRIDE_SOURCE and run.code == RC.LOAD_OVERRIDE_RUN
    stop = compute_load_intent(_Load(is_active=True), remaining_surplus_w=5000.0, override="skip")
    assert not stop.on and stop.source is None and stop.code == RC.LOAD_OVERRIDE_STOP
    plain = compute_load_intent(_Load(), remaining_surplus_w=0.0)
    assert plain == compute_load_intent(_Load(), remaining_surplus_w=0.0, override=None)
    assert not plain.on


def test_the_device_map_shows_the_override():
    sc = SurplusController(MagicMock())
    sc._load_overrides = dict(FORCE)
    assert sc.load_override_status("boiler") == {"action": "force", "until": "14:30"}
    assert sc.load_override_status("other") is None


def test_until_is_on_the_local_clock():
    zrh = ZoneInfo("Europe/Zurich")
    now = datetime(2026, 11, 10, 13, 30, tzinfo=zrh)
    ovs = po.set_override({}, "boiler", "force", now + timedelta(minutes=60), now)
    assert po.status_payload(ovs, "boiler", now)["until"] == "14:30"
    utc_now = now.astimezone(timezone.utc)
    assert po.status_payload(ovs, "boiler", utc_now)["until"] == "13:30"


# ── set_plan_override takes a load id ─────────────────────────────────

def _real_charger():
    """A charger the way setup registers it: a current-control device the
    per-charger loop owns (``managed_externally``)."""
    from custom_components.solar_energy_management.devices.base import CurrentControlDevice
    dev = CurrentControlDevice(hass=MagicMock(), device_id="ev_box",
                               name="Box", min_current=6.0, max_current=32.0,
                               phases=3)
    dev.managed_externally = True
    return dev


def _coord(mode=DeviceControlMode.SURPLUS):
    sc = SimpleNamespace(_devices={"boiler": _Load(control_mode=mode),
                                   "ev_box": _real_charger()})
    return SimpleNamespace(
        config={"ev_chargers": [{"id": "keba"}]},
        _known_battery_ids={"b1"},
        _battery_ids_read=True,
        _plan_overrides={},
        _storage=MagicMock(),
        _surplus_controller=sc,
    )


@pytest.mark.parametrize("action", ["force", "skip"])
def test_a_load_id_is_taken(action):
    c = _coord()
    SEMCoordinator.set_plan_override(c, "boiler", action, 60)
    assert c._plan_overrides["boiler"].action == action


@pytest.mark.parametrize("device_id", ["nope", "ev_box", ""])
def test_an_unknown_id_is_refused(device_id):
    c = _coord()
    with pytest.raises(ValueError, match="not a charger, a battery or a load"):
        SEMCoordinator.set_plan_override(c, device_id, "force", 60)
    assert c._plan_overrides == {}


def test_a_load_takes_only_skip_or_force():
    c = _coord()
    with pytest.raises(ValueError, match="skip or force"):
        SEMCoordinator.set_plan_override(c, "boiler", "cap", 60)
    assert c._plan_overrides == {}


@pytest.mark.parametrize("mode", [DeviceControlMode.OFF, DeviceControlMode.PEAK_ONLY])
def test_a_load_outside_smart_mode_is_refused(mode):
    c = _coord(mode)
    with pytest.raises(ValueError, match="Smart mode"):
        SEMCoordinator.set_plan_override(c, "boiler", "force", 60)
    assert c._plan_overrides == {}


def test_a_real_charger_or_battery_is_never_a_load():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        _override_load, _override_load_ids,
    )
    c = _coord()
    c._surplus_controller._devices["b1"] = _Load(device_id="b1")
    assert _override_load_ids(c) == {"boiler"}
    assert _override_load(c, "ev_box") is None
    assert _override_load(c, "b1") is None
