"""#1321 — a load's one-off override: Boost (force) and pause (skip).

The decision is ONE clause in ``compute_load_intent`` (3c), fed by
``_override_action``. Proven here on the three-layer path
(``_use_desired_state=True``) and in observer mode. The old passes, which
switch loads with observer off, do not read it yet: that lands on its own
branch.
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
    """A switched load that behaves under both engines and counts writes."""

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


def _sc(dev, desired=False):
    sc = SurplusController(MagicMock())
    sc._use_desired_state = desired
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
    sc = _sc(dev, desired=False)
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
@pytest.mark.parametrize("desired", [False, True], ids=["passes", "layers"])
@pytest.mark.parametrize("sun,active", [(0.0, False), (5000.0, False), (5000.0, True), (0.0, True)])
async def test_no_override_changes_nothing(desired, sun, active):
    a, b = _Load(is_active=active), _Load(is_active=active)
    await _sc(a, desired).update(available_power_w=sun)
    await _sc(b, desired).update(available_power_w=sun, load_overrides={})
    assert (a.is_active, a.activations, a.deactivations) == \
        (b.is_active, b.activations, b.deactivations)


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

def _coord(mode=DeviceControlMode.SURPLUS):
    sc = SimpleNamespace(_devices={"boiler": _Load(control_mode=mode),
                                   "ev_box": SimpleNamespace(is_ev=True)})
    return SimpleNamespace(
        config={"ev_chargers": [{"id": "keba"}]},
        _known_battery_ids={"b1"},
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
