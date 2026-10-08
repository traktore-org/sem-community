"""#1067 — a load's rating is the power it HOLDS, not one reading of it.

lostcontrol's dehumidifier draws ~200 W when it runs (Fronius, 2.2.0-beta.12).
The Control card said "~1.4 kW", and SEM never switched it on: the rating is
also the surplus it waits for. A compressor start reads several times the
running draw for a moment, and every learning path kept the HIGHEST reading
it was ever shown:

  * ``calibrate_rated_power`` adopted any live reading above the rating;
  * ``_history_max_power`` seeded the largest value in 7 days of history;
  * ``_initial_rated_power`` handed a load that was running at build time
    its instant reading as a measured rating;
  * ``_capture_calibrated_ratings`` then saved it, up only, for good.

Now each path asks for the level the sensor held for ``RATED_POWER_HOLD_S``.
Ratings saved under the old rule are checked once more against history. Only
a device built from the saved number moves down, and only to a level a start
peak could be at most ``RATED_POWER_START_PEAK_RATIO`` times of.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.consts.core import (
    RATED_POWER_HOLD_S as HOLD,
    RATED_POWER_RULE,
)
from custom_components.solar_energy_management.devices.base import (
    _MAX_PLAUSIBLE_LOAD_W,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceState, SwitchDevice,
)
from custom_components.solar_energy_management.devices.held_power import (
    HeldPower, held_power_w,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)

START_PEAK_W = 1400.0     # one reading as the compressor starts
RUNNING_W = 200.0         # what the dehumidifier draws for hours


def _dehumidifier(rated=0.0):
    dev = SwitchDevice(
        MagicMock(), "dehumidifier", "Dehumidifier", rated_power=rated,
        entity_id="switch.dehumidifier",
        power_entity_id="sensor.dehumidifier_power",
    )
    dev._status.state = DeviceState.ACTIVE
    return dev


def _feed(dev, readings, start=0.0, step=10.0):
    """One coordinator cycle every ``step`` s, the sensor reading each value."""
    t = start
    for w in readings:
        dev.observed_power_w = lambda w=w: w
        dev.calibrate_rated_power(now=t)
        t += step
    return t


def _start_then_run(seconds):
    return [START_PEAK_W] + [RUNNING_W] * int(seconds // 10)


# ── the live path ─────────────────────────────────────────────────────────
@pytest.mark.unit
class TestTheLivePathLearnsTheHeldLevel:
    def test_the_reporters_start_peak_is_not_the_rating(self):
        dev = _dehumidifier()
        _feed(dev, _start_then_run(10 * 60))
        assert dev.rated_power == RUNNING_W
        assert dev.min_power_threshold == RUNNING_W, (
            "SEM would wait for 1.4 kW of surplus before it switched on a "
            "200 W load"
        )
        assert dev.rated_power_measured is True

    def test_a_start_peak_does_not_raise_a_learned_rating(self):
        dev = _dehumidifier(rated=RUNNING_W)
        _feed(dev, _start_then_run(10 * 60))
        assert dev.rated_power == RUNNING_W

    def test_nothing_is_learned_before_the_hold_time(self):
        dev = _dehumidifier()
        _feed(dev, [RUNNING_W] * int(HOLD // 10))      # 0 .. HOLD-10 s
        assert dev.rated_power_measured is False

    def test_a_higher_level_held_long_enough_still_raises_it(self):
        # A washing machine's heating phase: real, and held for minutes.
        dev = _dehumidifier(rated=RUNNING_W)
        _feed(dev, [2000.0] * 30)
        assert dev.rated_power == 2000.0

    def test_a_noisy_run_learns_its_floor_not_its_top(self):
        dev = _dehumidifier()
        _feed(dev, [195.0, 205.0, 199.0, 260.0, 201.0] * 6)
        assert dev.rated_power == 195.0

    def test_a_gap_in_the_readings_starts_the_hold_again(self):
        dev = _dehumidifier()
        t = _feed(dev, [START_PEAK_W] * 6)               # 50 s of peak
        # 5 minutes we did not see: the peak must not join the next run.
        _feed(dev, [START_PEAK_W] * 7, start=t + 300.0)  # 60 s more
        assert dev.rated_power_measured is False

    def test_an_off_load_starts_the_hold_again(self):
        dev = _dehumidifier()
        t = _feed(dev, [START_PEAK_W] * 7)               # 0 .. 60 s
        dev._status.state = DeviceState.IDLE
        dev.calibrate_rated_power(now=t)
        dev._status.state = DeviceState.ACTIVE
        _feed(dev, [START_PEAK_W] * 7, start=t + 10.0)   # 70 .. 130 s
        assert dev.rated_power_measured is False

    def test_the_daily_tick_resets_the_hold_while_off(self):
        dev = _dehumidifier()
        _feed(dev, [START_PEAK_W] * 7)
        assert dev._held_power.running
        dev._status.state = DeviceState.IDLE
        dev.update_daily_runtime(datetime.now().date())
        assert not dev._held_power.running

    def test_the_longest_update_interval_still_learns(self):
        # The options allow a 60 s cycle; HA adds a little each time.
        dev = _dehumidifier()
        for i, w in enumerate([START_PEAK_W, RUNNING_W, RUNNING_W, RUNNING_W]):
            dev.observed_power_w = lambda w=w: w
            dev.calibrate_rated_power(now=i * 60.01)
        assert dev.rated_power == RUNNING_W

    def test_a_peak_held_ninety_seconds_is_not_held_for_two_minutes(self):
        # 30 s cycles: the reading in force when the hold began counts too.
        dev = _dehumidifier(rated=RUNNING_W)
        for t, w in [(0.0, RUNNING_W), (30.1, START_PEAK_W), (60.2, START_PEAK_W),
                     (90.3, START_PEAK_W), (120.4, START_PEAK_W)]:
            dev.observed_power_w = lambda w=w: w
            dev.calibrate_rated_power(now=t)
        assert dev.rated_power == RUNNING_W

    def test_a_re_registration_keeps_the_hold(self):
        # A service device re-registered (an edit) is a FRESH object; the
        # hold travels with the other volatile fields. Energy Dashboard
        # loads are unregistered first, so theirs starts again (class 129).
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            SurplusController,
        )
        assert "_held_power" in SurplusController._VOLATILE_CONTROL_FIELDS
        sc = SurplusController(MagicMock())
        old = _dehumidifier()
        sc.register_device(old)
        t = _feed(old, [RUNNING_W] * 7)                  # 0 .. 60 s
        fresh = _dehumidifier()
        sc.register_device(fresh)
        _feed(fresh, [RUNNING_W] * 7, start=t)           # 70 .. 130 s
        assert fresh.rated_power == RUNNING_W


@pytest.mark.unit
class TestHeldPowerAlone:
    def test_one_reading_holds_nothing(self):
        assert HeldPower().add(0.0, 500.0) is None

    def test_the_held_level_is_the_lowest_in_the_window(self):
        h = HeldPower(hold_s=30.0, gap_s=20.0)
        for t, w in [(0, 900), (10, 300), (20, 310), (30, 305)]:
            out = h.add(float(t), float(w))
        assert out == 300.0                   # the 900 W start is not it
        assert h.add(40.0, 320.0) == 300.0    # 10 s is still in the window
        assert h.add(50.0, 330.0) == 305.0    # now it has left


# ── the history path ──────────────────────────────────────────────────────
@pytest.mark.unit
class TestHistoryLearnsTheHeldLevel:
    def test_the_reporters_afternoon(self):
        # 0 W, a 2 s start peak, two hours at ~200 W, a 270 W blip, off.
        points = [(0, 0.0), (100, START_PEAK_W), (102, 170.0), (160, 198.0),
                  (2800, 270.0), (2805, 200.0), (7300, 0.0)]
        assert held_power_w(points, end=9000.0) == 200.0

    def test_a_level_held_for_the_hold_time_counts(self):
        assert held_power_w([(0, 0.0), (10, 500.0), (10 + HOLD, 0.0)],
                            end=1000.0) == 500.0

    def test_a_level_held_a_second_too_short_does_not(self):
        assert held_power_w([(0, 0.0), (10, 500.0), (9 + HOLD, 0.0)],
                            end=1000.0) == 0.0

    def test_the_last_state_holds_until_now(self):
        assert held_power_w([(0, 0.0), (10, 450.0)], end=10 + HOLD) == 450.0

    def test_an_unreadable_state_breaks_a_run(self):
        points = [(0, 800.0), (60, None), (61, 800.0), (121, 0.0)]
        assert held_power_w(points, end=500.0) == 0.0

    def test_no_history_is_no_level(self):
        assert held_power_w([], end=0.0) == 0.0


def _state(value, ts):
    return SimpleNamespace(
        state=str(value),
        last_changed=datetime.fromtimestamp(ts, tz=timezone.utc))


@pytest.mark.unit
class TestTheHistoryRead:
    async def _held(self, states, unit, live=True):
        reg = _reg()
        reg.hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="0", attributes={"unit_of_measurement": unit}) if live else None)
        reg.hass.async_add_executor_job = AsyncMock(
            side_effect=lambda f, *a: f(*a))
        now = datetime.now(tz=timezone.utc).timestamp()
        rows = [_state(v, now - 3600 + t) for t, v in states]
        with patch(
            "custom_components.solar_energy_management.coordinator."
            "recorder_history.read_states", AsyncMock(return_value=rows),
        ):
            return await reg._history_held_power("sensor.dehumidifier_power")

    async def test_seven_days_with_one_start_peak(self):
        held = await self._held(
            [(0, 0), (100, 1400), (102, 200), (1900, 0)], "W")
        assert held == 200.0

    async def test_a_kilowatt_sensor_is_read_in_watts(self):
        held = await self._held([(0, 0), (100, 2.0), (1000, 0)], "kW")
        assert held == 2000.0

    async def test_a_missing_sensor_has_no_unit_to_read_with(self):
        held = await self._held([(0, 0), (100, 2.0), (1000, 0)], "kW", live=False)
        assert held == 0.0

    async def test_a_value_no_load_can_draw_breaks_the_run(self):
        # The unit changed from W to kW inside the week: old rows read 1000x
        # (caught for loads above 100 W only — class 129).
        held = await self._held(
            [(0, 0), (100, 200.0), (1000, 0.2), (1900, 0)], "kW")
        assert held == 200.0
        assert 200.0 * 1000 > _MAX_PLAUSIBLE_LOAD_W


# ── the build path ────────────────────────────────────────────────────────
def _reg(devices=None):
    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    reg._rated_power_overrides = {}
    reg._rating_seed_attempted = set()
    reg._surplus_controller = MagicMock()
    reg._surplus_controller._devices = devices or {}
    reg.hass = MagicMock()
    reg.hass.states.get = MagicMock(return_value=None)
    reg._save_storage = AsyncMock()
    reg._history_seeds_enabled = True
    return reg


@pytest.mark.unit
class TestTheBuildTakesNoReading:
    def test_a_load_starting_at_build_time_is_not_rated_by_that_reading(self):
        reg = _reg()
        reg.hass.states.get = MagicMock(return_value=SimpleNamespace(
            state=str(START_PEAK_W), attributes={"unit_of_measurement": "W"}))
        assert reg._initial_rated_power("d", "sensor.dehumidifier_power") == 0.0

    def test_a_saved_rating_is_still_used(self):
        reg = _reg()
        reg._rated_power_overrides["d"] = RUNNING_W
        assert reg._initial_rated_power("d", "sensor.p") == RUNNING_W


# ── ratings saved under the old rule ──────────────────────────────────────
def _live(rated, measured=True, mpt=None):
    return SimpleNamespace(
        rated_power=rated, rated_power_measured=measured, is_ev=False,
        power_entity_id="sensor.dehumidifier_power",
        min_power_threshold=rated if mpt is None else mpt,
    )


def _old_store_reg(saved, devices):
    """A registry upgraded from a store with ``saved`` ratings, each marked
    for its re-check. A device whose value is None is built here the way the
    registry builds an Energy Dashboard load: from the saved number."""
    reg = _reg({})
    reg._rated_power_overrides = dict(saved)
    reg._ratings_to_recheck = set(saved)
    for did, dev in devices.items():
        if dev is None:
            devices[did] = _live(reg._initial_rated_power(did, "sensor.p"))
    reg._surplus_controller._devices = devices
    return reg, devices


@pytest.mark.unit
class TestAnOldRatingIsCheckedAgain:
    def _store_reg(self, store):
        reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        reg._store = MagicMock()
        reg._store.async_load = AsyncMock(return_value=store)
        reg._store.async_save = AsyncMock()
        return reg

    async def test_a_store_from_before_the_rule_marks_every_rating(self):
        reg = self._store_reg({"legacy_flags_adopted": True,
                               "rated_power_overrides": {"d": 1400.0, "e": 8.0}})
        await reg._load_storage()
        assert reg._ratings_to_recheck == {"d", "e"}

    async def test_the_marks_and_the_rule_survive_a_restart(self):
        reg = self._store_reg({"legacy_flags_adopted": True,
                               "rated_power_overrides": {"d": 1400.0, "e": 8.0}})
        await reg._load_storage()
        reg._ratings_to_recheck.discard("e")
        await reg._save_storage()
        saved = reg._store.async_save.await_args.args[0]
        assert saved["rated_power_rule"] == RATED_POWER_RULE
        assert saved["rated_power_recheck"] == ["d"]
        again = self._store_reg(saved)
        await again._load_storage()
        assert again._ratings_to_recheck == {"d"}
        assert again._rated_power_overrides == {"d": 1400.0, "e": 8.0}

    async def test_a_store_under_the_rule_checks_nothing_again(self):
        reg = self._store_reg({"legacy_flags_adopted": True,
                               "rated_power_rule": RATED_POWER_RULE,
                               "rated_power_overrides": {"d": 200.0}})
        await reg._load_storage()
        assert reg._ratings_to_recheck == set()

    @pytest.mark.parametrize("marks", [5, [["d"]], "d", None])
    async def test_a_damaged_mark_list_loses_nothing_else(self, marks):
        reg = self._store_reg({"legacy_flags_adopted": True,
                               "rated_power_rule": RATED_POWER_RULE,
                               "rated_power_overrides": {"d": 200.0},
                               "rated_power_recheck": marks,
                               "device_goals": {"d": {"x": 1}}})
        await reg._load_storage()
        assert reg._ratings_to_recheck == set()
        assert reg._device_goals == {"d": {"x": 1}}

    async def test_history_moves_the_old_peak_down(self):
        reg, devs = _old_store_reg({"d": 1400.0}, {"d": None})
        reg._history_held_power = AsyncMock(return_value=198.0)
        assert await reg._seed_and_apply_ratings() is True
        assert reg._rated_power_overrides["d"] == 198.0
        assert devs["d"].rated_power == 198.0
        assert devs["d"].min_power_threshold == 198.0
        assert devs["d"].rated_power_measured is True
        assert reg._ratings_to_recheck == set()

    async def test_a_start_fifteen_times_the_run_is_still_a_start(self):
        # A small fan: 100 W running, 1.5 kW for a moment at each start.
        reg, devs = _old_store_reg({"fan": 1500.0}, {"fan": None})
        reg._history_held_power = AsyncMock(return_value=100.0)
        await reg._seed_and_apply_ratings()
        assert devs["fan"].rated_power == 100.0

    async def test_without_history_nothing_changes_and_it_asks_again(self):
        reg, devs = _old_store_reg({"d": 1400.0}, {"d": None})
        reg._history_held_power = AsyncMock(return_value=0.0)
        assert await reg._seed_and_apply_ratings() is False
        assert devs["d"].rated_power == 1400.0
        assert devs["d"].rated_power_measured is True
        assert reg._ratings_to_recheck == {"d"}

    async def test_an_idle_load_does_not_replace_its_rating(self):
        # A boiler left on with its thermostat satisfied holds 4 W all week.
        # 4 W is no start peak's running level for a 2.5 kW rating.
        reg, devs = _old_store_reg({"boiler": 2500.0}, {"boiler": None})
        reg._history_held_power = AsyncMock(return_value=4.0)
        await reg._seed_and_apply_ratings()
        assert devs["boiler"].rated_power == 2500.0
        assert reg._rated_power_overrides["boiler"] == 2500.0
        assert reg._ratings_to_recheck == {"boiler"}

    async def test_setup_waits_and_the_started_pass_settles_it(self):
        reg, devs = _old_store_reg({"d": 1400.0}, {"d": None})
        reg._history_seeds_enabled = False
        reg._history_held_power = AsyncMock(return_value=198.0)
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power == 1400.0
        reg._history_held_power.assert_not_awaited()
        await reg.async_seed_ratings_from_history()
        assert devs["d"].rated_power == 198.0
        assert reg._rated_power_overrides["d"] == 198.0
        reg._save_storage.assert_awaited()

    async def test_a_placeholder_still_gets_the_saved_number(self):
        # A service device registered with no rating holds the 1 kW guess;
        # the saved 2500 is a measurement and wins until history answers.
        reg, devs = _old_store_reg(
            {"svc": 2500.0}, {"svc": _live(1000.0, measured=False)})
        reg._history_held_power = AsyncMock(return_value=0.0)
        await reg._seed_and_apply_ratings()
        assert devs["svc"].rated_power == 2500.0
        assert devs["svc"].rated_power_measured is True
        assert reg._ratings_to_recheck == {"svc"}

    async def test_a_store_from_a_later_rule_is_not_checked_again(self):
        reg = TestAnOldRatingIsCheckedAgain._store_reg(self, {
            "legacy_flags_adopted": True, "rated_power_rule": RATED_POWER_RULE + 1,
            "rated_power_overrides": {"d": 200.0}})
        await reg._load_storage()
        assert reg._ratings_to_recheck == set()

    def test_a_build_record_lasts_one_sync(self):
        reg = _reg()
        reg._rated_power_overrides["d"] = 1400.0
        reg._initial_rated_power("d", "sensor.p")
        assert reg._built_from_store == {"d": 1400.0}
        reg._devices = []
        reg._ev_charger_rows = []
        reg._surplus_controller._devices = {}
        reg._sync_to_surplus_controller()
        assert reg._built_from_store == {}

    async def test_a_failed_history_job_is_no_level(self):
        reg = _reg()
        reg.hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="0", attributes={"unit_of_measurement": "W"}))
        reg.hass.async_add_executor_job = AsyncMock(side_effect=RuntimeError("shutdown"))
        with patch(
            "custom_components.solar_energy_management.coordinator."
            "recorder_history.read_states",
            AsyncMock(return_value=[_state(200, 0.0)]),
        ):
            assert await reg._history_held_power("sensor.p") == 0.0

    async def test_a_rating_the_device_was_given_is_not_lowered(self):
        # A hot-water heater configured at 2500 W; the old store saved the
        # same number. History settles the store; the device keeps 2500.
        reg, devs = _old_store_reg({"hw": 2500.0}, {"hw": _live(2500.0)})
        reg._history_held_power = AsyncMock(return_value=1800.0)
        await reg._seed_and_apply_ratings()
        assert reg._rated_power_overrides["hw"] == 1800.0
        assert devs["hw"].rated_power == 2500.0

    async def test_a_given_rating_is_not_raised_to_an_old_peak(self):
        # Given 2000 W, the old store raised it to a 2500 W peak. Before the
        # history answers (setup, the 35 s rediscovery) nothing is applied.
        reg, devs = _old_store_reg({"hp": 2500.0}, {"hp": _live(2000.0)})
        reg._history_seeds_enabled = False
        await reg._seed_and_apply_ratings()
        assert devs["hp"].rated_power == 2000.0
        reg._history_held_power = AsyncMock(return_value=1800.0)
        await reg.async_seed_ratings_from_history()
        assert devs["hp"].rated_power == 2000.0
        assert reg._rated_power_overrides["hp"] == 1800.0

    async def test_a_level_learned_live_is_not_overwritten(self):
        # The load held 1600 W live before the history answered with less.
        reg, devs = _old_store_reg({"d": 1400.0}, {"d": None})
        devs["d"].rated_power = 1600.0
        reg._history_held_power = AsyncMock(return_value=900.0)
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power == 1600.0

    def test_a_live_level_above_the_saved_number_settles_it(self):
        reg, devs = _old_store_reg({"d": 1400.0}, {"d": None})
        devs["d"].rated_power = 1600.0
        assert reg._capture_calibrated_ratings() is True
        assert reg._rated_power_overrides["d"] == 1600.0
        assert reg._ratings_to_recheck == set()

    async def test_a_rebuild_during_the_history_read_keeps_the_answer(self):
        # The 35 s rediscovery replaces the device object while the recorder
        # read is waiting: the answer must land on the object that is live.
        reg, devs = _old_store_reg({"d": 1400.0}, {"d": None})
        fresh = _live(reg._initial_rated_power("d", "sensor.p"))

        async def slow_read(sensor):
            devs["d"] = fresh            # the rebuild swapped the object
            return 198.0

        reg._history_held_power = slow_read
        await reg._seed_and_apply_ratings()
        assert fresh.rated_power == 198.0

    async def test_a_settled_rating_only_moves_up_again(self):
        devs = {"d": _live(198.0)}
        reg = _reg(devs)
        reg._rated_power_overrides["d"] = 198.0
        reg._history_held_power = AsyncMock(return_value=150.0)
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power == 198.0
        reg._history_held_power.assert_not_awaited()
