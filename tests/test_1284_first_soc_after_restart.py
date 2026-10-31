"""#1284 — the first battery level after a restart was taken unchecked.

#902 holds a level no battery can reach in one read (more than
``BATTERY_SOC_MAX_STEP_PCT`` from the last level) until it has repeated for
``BATTERY_SOC_STEP_CONFIRM_READS`` reads. That check needs a last level, so
the first read after a start was taken as it came. A pack sends one false
0 % when its link comes back (#902's Huawei trace), and a restart is exactly
that. SEM then saw an empty pack, and held the real level as the jump for
three reads (about 30 s). A plan made then could plan a grid charge it did
not need. One battery always had this; a fleet got it with #1169's 0 % fix.

The rule now: the first level is taken the way a step is, once it has
repeated. Until then the SOC is "never read" (#875), as before any read.

Guard: a level read once is never published as a measurement, from a fresh
reader or from a held level, on every SOC path (SEM's own SOC sensor, the
Energy Dashboard's, a two-battery fleet).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.consts.core import (
    BATTERY_SOC_MAX_STEP_PCT,
    BATTERY_SOC_STEP_CONFIRM_READS,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    battery_unseen,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module,
    Presence,
)
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (  # noqa: E501
    _state,
)
from custom_components.solar_energy_management.tests.test_1169_fleet_soc_dark_or_zero import (  # noqa: E501
    _fleet,
    _one,
    _one_ed,
    _set_all,
    _soc,
)

N = BATTERY_SOC_STEP_CONFIRM_READS


def _fleet_both(value):
    return _fleet(value, value)


#: every door a SOC comes in by: SEM's own sensor, the Energy Dashboard's,
#: and a two-battery fleet whose units read the same
PATHS = [_one, _one_ed, _fleet_both]
NEVER_READ = (0.0, True, False)


def _reads(r, states, values):
    """One read per value; each value is put on every SOC sensor first."""
    seen = []
    for v in values:
        _set_all(states, v)
        seen.append(_soc(r.read_power()))
    return seen


def _published(seen, level):
    """Was ``level`` ever published as a measurement?"""
    return any(s[0] == pytest.approx(level) and s[1:] == (False, True)
               for s in seen)


# ── 1. The report ─────────────────────────────────────────────────────────

class TestAFalse0AfterARestart:
    @pytest.mark.parametrize("path", PATHS)
    def test_is_never_the_level(self, path):
        r, states = path("0.0")
        seen = _reads(r, states, ["0.0"] + ["93"] * (N + 1))
        assert not _published(seen, 0.0), (
            f"the false 0 % after a restart was taken as the level: {seen}")
        assert seen[-1] == (93.0, False, True), seen

    @pytest.mark.parametrize("path", PATHS)
    def test_the_real_level_is_not_held_as_a_jump(self, path):
        """The old code took the 0 % and then held 93 % as an impossible
        jump from it. Now nothing was taken, so 93 % counts the moment it
        has repeated: the false read only cost its own cycle."""
        r, states = path("0.0")
        seen = _reads(r, states, ["0.0"] + ["93"] * N)
        assert seen[:N] == [NEVER_READ] * N, seen
        assert seen[N] == (93.0, False, True), seen

    def test_one_unit_false_0_in_a_fleet(self):
        """The fleet path: one unit's false 0 % beside a 90 % unit averages
        to 45 %, which is no level either."""
        r, states = _fleet(0, 90)
        seen = [_soc(r.read_power())]
        states["sensor.soc1"] = _state(90, "%")
        seen += [_soc(r.read_power()) for _ in range(N)]
        assert not _published(seen, 45.0), seen
        assert seen[-1] == (90.0, False, True), seen


# ── 2. A real level still counts ──────────────────────────────────────────

class TestARealLevelCounts:
    @pytest.mark.parametrize("path", PATHS)
    @pytest.mark.parametrize("level", ["0", "0.0", "37.5", "100"])
    def test_once_it_has_repeated(self, path, level):
        """A real 0 % after a restart is common: it counts on the same read
        as any other level. Before that it is never read, not 0 %."""
        r, _ = path(level)
        seen = [_soc(r.read_power()) for _ in range(N + 1)]
        assert seen[:N - 1] == [NEVER_READ] * (N - 1), seen
        assert seen[N - 1:] == [(float(level), False, True)] * 2, seen

    @pytest.mark.parametrize("path", PATHS)
    def test_a_dark_read_while_it_waits_does_not_start_again(self, path):
        r, states = path("93")
        seen = _reads(r, states, ["93", "unavailable"] + ["93"] * (N - 1))
        assert seen[:-1] == [NEVER_READ] * N, seen
        assert seen[-1] == (93.0, False, True), seen

    @pytest.mark.parametrize("path", PATHS)
    def test_a_pack_that_moves_while_it_waits_still_counts(self, path):
        """Charging at full power moves a pack a few % in 20 s; the wait
        compares with the first level by the step bound, not by equality."""
        r, states = path("50")
        seen = _reads(r, states, ["50", "51", "52"])
        assert seen[-1] == (52.0, False, True), seen

    def test_a_start_logs_no_warning(self, caplog):
        """A normal start is not an impossible jump: no WARNING per restart."""
        from custom_components.solar_energy_management.utils.log_gate import (
            reset_log_gate,
        )
        reset_log_gate()
        r, _ = _one("93")
        with caplog.at_level(logging.INFO):
            for _ in range(N + 1):
                r.read_power()
        noisy = [rec.getMessage() for rec in caplog.records
                 if rec.levelno >= logging.INFO and "SOC" in rec.getMessage()]
        assert noisy == [], noisy


# ── 3. Guard: a level read once is never a measurement ────────────────────

#: (one-read value, the truth around it) — each pair further apart than one
#: read can move a pack
OUTLIERS = [("0.0", "93"), ("0", "60"), ("100", "20"), ("50", "93")]


class TestALevelReadOnceIsNoMeasurement:
    @pytest.mark.parametrize("path", PATHS)
    @pytest.mark.parametrize("outlier,truth", OUTLIERS)
    @pytest.mark.parametrize("start", ["fresh", "held"])
    def test_from_a_start_or_from_a_held_level(self, path, outlier, truth,
                                               start):
        """The same rule with and without a last level: one read of a value
        no pack can reach from the truth is never published, and the truth
        is published by the end. ``fresh`` is a restart, ``held`` the #902
        case the step check always covered."""
        assert abs(float(outlier) - float(truth)) > BATTERY_SOC_MAX_STEP_PCT
        r, states = path(truth)
        if start == "held":
            _reads(r, states, [truth] * N)
            assert _soc(r.read_power()) == (float(truth), False, True)
        seen = _reads(r, states, [outlier] + [truth] * (N + 1))
        assert not _published(seen, float(outlier)), (start, seen)
        assert seen[-1] == (float(truth), False, True), (start, seen)


# ── 4. A level that waits still says there is a battery ───────────────────

class TestAWaitingLevelIsABattery:
    def _coord(self, reader, presence=Presence.UNKNOWN):
        reader.auto_detect_battery_capacity_kwh = lambda: None
        return SimpleNamespace(
            config={}, setup_presence={Module.BATTERY: presence},
            _detected_battery_capacity_kwh=None, _sensor_reader=reader)

    def test_the_first_level_waiting_for_its_repeat(self):
        """The wait changes when the level counts, not whether SEM sees a
        pack: the plan and the pack size must not drop the battery for it."""
        r, _ = _one("60")
        p = r.read_power()
        assert p.battery_soc_known is False
        assert battery_unseen(self._coord(r)) is False

    def test_never_read_is_still_unseen(self):
        """Not vacuous: the same home with nothing read has no battery."""
        r, _ = _one("unavailable")
        r.read_power()
        assert battery_unseen(self._coord(r)) is True

    def test_absent_is_still_absent(self):
        r, _ = _one("60")
        r.read_power()
        assert battery_unseen(self._coord(r, Presence.ABSENT)) is True


# ── 5. The wait has an end ────────────────────────────────────────────────

class TestTheFirstWaitEnds:
    def test_two_averages_that_never_repeat_still_give_a_level(self):
        """Review: units at 90 % and 20 %, unit 2 dark every other read,
        give 55 % and 90 % in turn. Neither repeats, so without an end the
        SOC stayed never read, and the plan never stamped."""
        r, states = _fleet(90, 20)
        seen = []
        for i in range(2 * N):
            states["sensor.soc2"] = _state(20 if i % 2 == 0 else
                                           "unavailable", "%")
            seen.append(_soc(r.read_power()))
        assert seen[:-1] == [NEVER_READ] * (2 * N - 1), seen
        assert seen[-1][1:] == (False, True), seen
        assert seen[-1][0] in (55.0, 90.0), seen

    def test_dark_reads_do_not_count_toward_the_end(self):
        """A SOC sensor still loading after a restart is dark for minutes.
        Only reads with a number count, so a false 0 % when it comes back
        is still refused."""
        r, states = _one("unavailable")
        seen = _reads(r, states, ["unavailable"] * (4 * N) + ["0.0"]
                      + ["93"] * N)
        assert not _published(seen, 0.0), seen
        assert seen[-1] == (93.0, False, True), seen


# ── 6. Readers of the SOC wait with it ────────────────────────────────────

def _cycle_coordinator(soc_state, extra=None):
    """A real coordinator on the #873 rig, at its first turn after a start."""
    from custom_components.solar_energy_management.coordinator.coordinator import (  # noqa: E501
        SEMCoordinator,
    )
    from custom_components.solar_energy_management.tests.test_873_cycle_executes import (  # noqa: E501
        WIRED,
        _hass,
        _sensors,
    )
    coord = SEMCoordinator(_hass(_sensors(0, 0, 0, soc_state)),
                           {**WIRED, **(extra or {})})
    coord.config_entry = None
    return coord


@pytest.mark.asyncio
class TestTheNightSchedulerWaitsForALevel:
    async def _socs_planned_on(self, soc_state, turns):
        coord = _cycle_coordinator(
            soc_state, {"battery_charge_scheduler_enabled": True})
        sched = coord._battery_charge_scheduler
        sched._in_planning_window = lambda now: True
        planned = []
        real = sched.evaluate

        def _spy(*args, **kwargs):
            planned.append(kwargs.get("current_soc"))
            return real(*args, **kwargs)
        sched.evaluate = _spy
        for _ in range(turns):
            await coord._async_update_data()
        return planned

    async def test_the_first_turns_plan_nothing_from_0(self):
        """Review: the first turn planned the night from the 0.0 of a SOC
        never read ("charge 0 % → 40 %"), then found 63 % above that target
        and charged nothing all night."""
        planned = await self._socs_planned_on(63, N + 1)
        assert planned, "the scheduler never ran: the test proves nothing"
        assert 0.0 not in planned, planned
        assert planned[0] == pytest.approx(63.0), planned

    async def test_a_dark_sensor_plans_nothing(self):
        """The same for a SOC sensor still loading after a restart."""
        planned = await self._socs_planned_on("unavailable", N + 1)
        assert planned == [], planned


@pytest.mark.asyncio
class TestTheLegacyFlagsWaitForALevel:
    async def test_never_read_is_not_too_low(self):
        """Review: the charging context read the 0.0 as "battery too low"
        and paused solar charging with "Bat 0%" on a car's charger."""
        coord = _cycle_coordinator("unavailable")
        data = await coord._async_update_data()
        assert data["battery_too_low"] is False
        assert data["battery_needs_priority"] is False

    async def test_a_low_level_is_still_low(self):
        """Not vacuous: a level that counted, below the priority level."""
        coord = _cycle_coordinator(10)
        for _ in range(N - 1):
            coord._sensor_reader.read_power()
        data = await coord._async_update_data()
        assert data["battery_too_low"] is True


@pytest.mark.asyncio
class TestThePacerKeepsItsCapThroughTheStart:
    """Review: a cap from before the start was released on the first turn
    (no SOC yet) and written again once the level counted: a write pair on
    every restart and reload. Now it is kept as through a blink, up to the
    dark-read grace from the start."""

    @staticmethod
    def _store():
        box = {}

        class _Store:
            async def async_load(self):
                return box.get("rec")

            async def async_save(self, rec):
                box["rec"] = rec

            async def async_remove(self):
                box.pop("rec", None)
        return _Store()

    async def _engaged_then_restarted(self, boot_age_s):
        import time

        from custom_components.solar_energy_management.consts.core import (
            SENSOR_DARK_READ_GRACE_S,
        )
        from custom_components.solar_energy_management.coordinator.coordinator import (  # noqa: E501
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.types import (  # noqa: E501
            PowerReadings,
        )
        from custom_components.solar_energy_management.tests.test_934_dark_soc_reads_declare_themselves import (  # noqa: E501
            _pacer,
            _writes,
        )
        assert SENSOR_DARK_READ_GRACE_S > 30
        store = self._store()
        fake, hass = _pacer()
        fake._charge_pacing_store = lambda: store
        live = PowerReadings(battery_soc=40.0, battery_soc_known=True)
        await SEMCoordinator._run_charge_pacing(fake, live)
        assert fake._charge_pacing_state["action"] == "wrote"
        before = len(_writes(hass))
        # The restart: a new writer, the same store and register.
        fake._charge_pacing_writer = None
        fake._boot_monotonic = time.monotonic() - boot_age_s
        never = PowerReadings(battery_soc=0.0, battery_soc_unavailable=True,
                              battery_soc_known=False)
        await SEMCoordinator._run_charge_pacing(fake, never)
        return fake, hass, before, _writes

    async def test_kept_while_the_first_level_waits(self):
        fake, hass, before, _writes = await self._engaged_then_restarted(20.0)
        st = fake._charge_pacing_state
        assert st["action"] == "held"
        assert len(_writes(hass)) == before, _writes(hass)
        # …and the published state says so: the cap on the register, kept
        assert st["cap_w"] is not None and st["cap_w"] > 0, st
        assert "kept" in st["reason"], st

    async def test_released_past_the_grace(self):
        """Not vacuous: a SOC still not read past the grace is an outage,
        and the cap is given back as before."""
        from custom_components.solar_energy_management.consts.core import (
            SENSOR_DARK_READ_GRACE_S,
        )
        fake, hass, before, _writes = await self._engaged_then_restarted(
            SENSOR_DARK_READ_GRACE_S + 30.0)
        assert fake._charge_pacing_state["action"] == "restored"
        assert len(_writes(hass)) == before + 1
