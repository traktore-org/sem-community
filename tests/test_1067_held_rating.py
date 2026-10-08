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
Ratings saved under the old rule are checked once more against history, and
until then held as a guess, so the first held level replaces them either way.
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
        dev._status.state = DeviceState.IDLE
        dev.update_daily_runtime(datetime.now().date())
        assert dev._held_power._since is None

    def test_a_rebuild_keeps_the_hold(self):
        # The registry re-registers a FRESH object on every rediscovery; a
        # hold that reset each time would never reach the hold time.
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
    async def _held(self, states, unit):
        reg = _reg()
        reg.hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="0", attributes={"unit_of_measurement": unit}))
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

    async def test_history_moves_the_old_peak_down(self):
        devs = {"d": _live(1400.0)}          # built from the saved 1.4 kW
        reg = _reg(devs)
        reg._rated_power_overrides["d"] = 1400.0
        reg._ratings_to_recheck = {"d"}
        reg._history_held_power = AsyncMock(return_value=198.0)
        assert await reg._seed_and_apply_ratings() is True
        assert reg._rated_power_overrides["d"] == 198.0
        assert devs["d"].rated_power == 198.0
        assert devs["d"].min_power_threshold == 198.0
        assert devs["d"].rated_power_measured is True
        assert reg._ratings_to_recheck == set()

    async def test_without_history_the_old_number_is_held_as_a_guess(self):
        devs = {"d": _live(1400.0)}
        reg = _reg(devs)
        reg._rated_power_overrides["d"] = 1400.0
        reg._ratings_to_recheck = {"d"}
        reg._history_held_power = AsyncMock(return_value=0.0)
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power == 1400.0
        assert devs["d"].rated_power_measured is False
        assert reg._ratings_to_recheck == {"d"}
        # the next rebuild, history already tried: still a guess
        devs["d"].rated_power_measured = True
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power_measured is False

    async def test_setup_without_the_recorder_holds_it_as_a_guess_too(self):
        devs = {"d": _live(1400.0)}
        reg = _reg(devs)
        reg._history_seeds_enabled = False
        reg._rated_power_overrides["d"] = 1400.0
        reg._ratings_to_recheck = {"d"}
        reg._history_held_power = AsyncMock(return_value=198.0)
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power_measured is False
        await reg.async_seed_ratings_from_history()
        assert devs["d"].rated_power == 198.0
        assert devs["d"].rated_power_measured is True
        assert reg._rated_power_overrides["d"] == 198.0

    def test_the_first_held_level_live_is_saved_downward(self):
        dev = _dehumidifier(rated=1400.0)
        dev.rated_power_measured = False      # marked by the re-check
        _feed(dev, _start_then_run(5 * 60))
        assert dev.rated_power == RUNNING_W
        reg = _reg({"d": dev})
        reg._rated_power_overrides["d"] = 1400.0
        reg._ratings_to_recheck = {"d"}
        assert reg._capture_calibrated_ratings() is True
        assert reg._rated_power_overrides["d"] == RUNNING_W
        assert reg._ratings_to_recheck == set()

    def test_a_guess_is_not_saved(self):
        reg = _reg({"d": _live(1400.0, measured=False)})
        reg._rated_power_overrides["d"] = 1400.0
        reg._ratings_to_recheck = {"d"}
        assert reg._capture_calibrated_ratings() is False
        assert reg._ratings_to_recheck == {"d"}

    async def test_a_rating_the_device_was_given_is_not_lowered(self):
        # A heat pump built with its own 2000 W; the old store raised it to a
        # 2500 W peak. History settles the store, the device keeps its 2000.
        devs = {"hp": _live(2000.0)}
        reg = _reg(devs)
        reg._rated_power_overrides["hp"] = 2500.0
        reg._ratings_to_recheck = {"hp"}
        reg._history_held_power = AsyncMock(return_value=1800.0)
        await reg._seed_and_apply_ratings()
        assert reg._rated_power_overrides["hp"] == 1800.0
        assert devs["hp"].rated_power == 2000.0
        assert devs["hp"].rated_power_measured is True

    async def test_a_settled_rating_only_moves_up_again(self):
        devs = {"d": _live(198.0)}
        reg = _reg(devs)
        reg._rated_power_overrides["d"] = 198.0
        reg._history_held_power = AsyncMock(return_value=150.0)
        await reg._seed_and_apply_ratings()
        assert devs["d"].rated_power == 198.0
        reg._history_held_power.assert_not_awaited()
