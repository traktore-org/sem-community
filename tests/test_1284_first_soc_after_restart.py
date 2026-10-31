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
