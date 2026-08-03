"""#647 — the battery perception cross-check must actually run on multi-battery installs.

``_audit_battery_sign_lock`` opened with ``if not
self._battery_sign_detected.get(self._FLEET_BID): return``. ``__fleet__`` is
only ever locked by the legacy single/combined-battery path — per-battery mode
locks ``b1``/``b2``/… — so on precisely the install shape where a per-unit sign
error is possible, the check was a permanent no-op. Class 8 (tautological /
can't-fail check): green health surface, unverified perception.

And had it run, it summed the counters against the summed power, so one unit
signed wrong plus one signed right cancels to ≈0 W and gets skipped as "idle".

Fix: one ``CounterCorrelationAudit`` per battery id, each against its own
``battery_charge_energy_list[idx]`` / ``battery_discharge_energy_list[idx]``.
"""
from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryPower,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


def _state(value):
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": "kWh"}
    return s


def _reader():
    r = SensorReader(MagicMock(), {})
    r._sign_vote_warmup = 0
    return r


def _ed_two_units():
    """A 2-battery Energy Dashboard config, per-battery mode."""
    ed = MagicMock()
    ed.battery_power_list = ["sensor.b1_power", "sensor.b2_power"]
    ed.battery_power_pairs = []
    ed.battery_charge_energy_list = ["sensor.b1_charge", "sensor.b2_charge"]
    ed.battery_discharge_energy_list = ["sensor.b1_discharge", "sensor.b2_discharge"]
    ed.battery_charge_energy = None
    ed.battery_discharge_energy = None
    return ed


def _readings(b1_w, b2_w):
    r = PowerReadings()
    r.batteries = {
        "b1": BatteryPower(battery_id="b1", power_w=b1_w, soc_pct=50.0, name="sensor.b1_power"),
        "b2": BatteryPower(battery_id="b2", power_w=b2_w, soc_pct=50.0, name="sensor.b2_power"),
    }
    r.battery_power = b1_w + b2_w
    return r


def _drive(reader, ed, b1_w, b2_w, counters):
    """One audit cycle. ``counters`` maps entity_id → kWh reading."""
    reader.hass.states.get = lambda eid: (
        _state(counters[eid]) if eid in counters else None
    )
    readings = _readings(b1_w, b2_w)
    reader._audit_battery_sign_lock(readings.battery_power, ed, readings)


@pytest.mark.unit
class TestPerBatteryAuditActuallyRuns647:
    def test_the_bug_one_unit_signed_wrong_is_caught(self):
        """b2's power says CHARGING while b2's discharge counter is the one
        rising — five cycles must raise the flag and name b2.

        Pre-fix this produced nothing at all: the fleet gate never opened.
        """
        r = _reader()
        ed = _ed_two_units()
        r._battery_sign_detected["b1"] = True
        r._battery_sign_detected["b2"] = True

        c = {
            "sensor.b1_charge": 10.0, "sensor.b1_discharge": 5.0,
            "sensor.b2_charge": 10.0, "sensor.b2_discharge": 5.0,
        }
        _drive(r, ed, 500.0, 500.0, c)          # prime baselines

        for _ in range(5):
            # b1 charges and its charge counter rises — honest.
            c["sensor.b1_charge"] += 0.05
            # b2 reads +500 W (charging) but its DISCHARGE counter rises.
            c["sensor.b2_discharge"] += 0.05
            _drive(r, ed, 500.0, 500.0, c)

        assert r._battery_sign_contradiction is True
        assert r.battery_sign_contradiction_bids == ["b2"]

    def test_summing_would_have_hidden_it(self):
        """The second half of #647: with one unit charging and the other
        discharging at the same rate, the SUMMED power is ~0 W — under the
        100 W skip. A per-unit audit still sees each unit clearly."""
        r = _reader()
        ed = _ed_two_units()
        r._battery_sign_detected["b1"] = True
        r._battery_sign_detected["b2"] = True

        c = {
            "sensor.b1_charge": 10.0, "sensor.b1_discharge": 5.0,
            "sensor.b2_charge": 10.0, "sensor.b2_discharge": 5.0,
        }
        _drive(r, ed, 2000.0, -2000.0, c)       # fleet total = 0 W
        for _ in range(5):
            c["sensor.b1_charge"] += 0.05       # b1 charging, agrees
            c["sensor.b2_discharge"] += 0.05    # b2 -2000 W discharging, agrees
            _drive(r, ed, 2000.0, -2000.0, c)

        assert r._battery_sign_contradiction is False

        # now flip b2's counter story — same 0 W fleet total, still caught
        for _ in range(5):
            c["sensor.b1_charge"] += 0.05
            c["sensor.b2_charge"] += 0.05       # b2 says discharging, charge rises
            _drive(r, ed, 2000.0, -2000.0, c)

        assert r.battery_sign_contradiction_bids == ["b2"]

    def test_honest_multi_battery_install_stays_quiet(self):
        r = _reader()
        ed = _ed_two_units()
        r._battery_sign_detected["b1"] = True
        r._battery_sign_detected["b2"] = True
        c = {
            "sensor.b1_charge": 10.0, "sensor.b1_discharge": 5.0,
            "sensor.b2_charge": 10.0, "sensor.b2_discharge": 5.0,
        }
        _drive(r, ed, 500.0, -500.0, c)
        for _ in range(8):
            c["sensor.b1_charge"] += 0.05
            c["sensor.b2_discharge"] += 0.05
            _drive(r, ed, 500.0, -500.0, c)
        assert r._battery_sign_contradiction is False
        assert r.battery_sign_contradiction_bids == []

    def test_unlocked_unit_is_not_audited(self):
        """No lock, nothing to contradict — a unit still learning its sign
        must not raise a perception fault."""
        r = _reader()
        ed = _ed_two_units()
        r._battery_sign_detected["b1"] = True      # b2 deliberately unlocked
        c = {
            "sensor.b1_charge": 10.0, "sensor.b1_discharge": 5.0,
            "sensor.b2_charge": 10.0, "sensor.b2_discharge": 5.0,
        }
        _drive(r, ed, 500.0, 500.0, c)
        for _ in range(8):
            c["sensor.b1_charge"] += 0.05
            c["sensor.b2_discharge"] += 0.05       # b2 contradicts, but unlocked
            _drive(r, ed, 500.0, 500.0, c)
        assert r.battery_sign_contradiction_bids == []

    def test_pair_units_are_never_audited(self):
        """Two-sensor pair units (#553) carry a user-declared direction — they
        are never sign-flipped, so they have no lock to contradict. Their bids
        follow the combined units, and iterating battery_power_list must not
        walk into them."""
        r = _reader()
        ed = _ed_two_units()
        ed.battery_power_list = ["sensor.b1_power"]
        ed.battery_charge_energy_list = ["sensor.b1_charge"]
        ed.battery_discharge_energy_list = ["sensor.b1_discharge"]
        ed.battery_power_pairs = [("sensor.b2_charge_p", "sensor.b2_discharge_p")]
        r._battery_sign_detected["b1"] = True
        r._battery_sign_detected["b2"] = True      # would be audited if we looped wrong

        c = {"sensor.b1_charge": 10.0, "sensor.b1_discharge": 5.0}
        _drive(r, ed, 500.0, -500.0, c)
        for _ in range(8):
            c["sensor.b1_charge"] += 0.05
            _drive(r, ed, 500.0, -500.0, c)

        assert r.battery_sign_contradiction_bids == []
        assert "b2" not in r._battery_sign_audits

    def test_missing_counter_for_a_unit_is_skipped_not_crashed(self):
        """A ragged Energy Dashboard config (power list longer than the
        counter lists) must not raise — index the lists defensively."""
        r = _reader()
        ed = _ed_two_units()
        ed.battery_charge_energy_list = ["sensor.b1_charge"]        # b2 missing
        ed.battery_discharge_energy_list = ["sensor.b1_discharge"]
        r._battery_sign_detected["b1"] = True
        r._battery_sign_detected["b2"] = True
        c = {"sensor.b1_charge": 10.0, "sensor.b1_discharge": 5.0}
        for _ in range(3):
            c["sensor.b1_charge"] += 0.05
            _drive(r, ed, 500.0, 500.0, c)
        assert "b2" not in r._battery_sign_audits


@pytest.mark.unit
class TestFleetPathUnchanged647:
    """The #589 single/combined-battery contract must survive the refactor."""

    def _ed_fleet(self):
        ed = MagicMock()
        ed.battery_power_list = []
        ed.battery_power_pairs = []
        ed.battery_charge_energy_list = []
        ed.battery_discharge_energy_list = []
        ed.battery_charge_energy = "sensor.batt_charge"
        ed.battery_discharge_energy = "sensor.batt_discharge"
        return ed

    def test_fleet_contradiction_still_flags_under_the_fleet_bid(self):
        r = _reader()
        ed = self._ed_fleet()
        r._battery_sign_detected[r._FLEET_BID] = True
        c = {"sensor.batt_charge": 10.0, "sensor.batt_discharge": 5.0}
        r.hass.states.get = lambda eid: _state(c[eid]) if eid in c else None
        r._audit_battery_sign_lock(500.0, ed)          # prime; no readings arg
        for _ in range(5):
            c["sensor.batt_discharge"] += 0.05          # power says charging
            r._audit_battery_sign_lock(500.0, ed)
        assert r._battery_sign_contradiction is True
        assert r.battery_sign_contradiction_bids == [r._FLEET_BID]
        assert r._battery_sign_contradiction_votes == 5


@pytest.mark.unit
class TestStaleAuditsArePruned647:
    """A flagged audit for a battery that no longer exists can never be
    cleared — no cycle will ever feed it the agreement that would clear it —
    so it would pin the perception fault on forever."""

    def _flag_b2(self, r, ed):
        r._battery_sign_detected["b2"] = True
        c = {"sensor.b2_charge": 10.0, "sensor.b2_discharge": 5.0}
        _drive(r, ed, 0.0, 500.0, c)
        for _ in range(5):
            c["sensor.b2_discharge"] += 0.05
            _drive(r, ed, 0.0, 500.0, c)
        assert r._battery_sign_contradiction is True

    def test_removing_a_battery_drops_its_flag(self):
        r = _reader()
        ed = _ed_two_units()
        self._flag_b2(r, ed)

        shrunk = _ed_two_units()
        shrunk.battery_power_list = ["sensor.b1_power"]
        r.set_energy_dashboard_config(shrunk)

        assert r._battery_sign_contradiction is False
        assert "b2" not in r._battery_sign_audits

    def test_an_unreadable_config_prunes_nothing_rather_than_raising(self):
        """This setter runs on every cycle of the #274 cold-start retry — an
        exception here takes the whole power read down. A config object whose
        battery list isn't a sequence must be survived, not raised on."""
        r = _reader()
        ed = _ed_two_units()
        self._flag_b2(r, ed)

        opaque = Mock()                 # a bare Mock has no __len__
        r.set_energy_dashboard_config(opaque)

        assert r._energy_dashboard_config is opaque
        assert "b2" in r._battery_sign_audits

    def test_a_live_units_votes_survive_the_cold_start_retry(self):
        """``set_energy_dashboard_config`` also runs every cycle during the
        #274 cold-start re-derivation. Clearing there would reset the vote
        count each time and the audit could never reach 5 votes — so this
        must PRUNE, not clear."""
        r = _reader()
        ed = _ed_two_units()
        r._battery_sign_detected["b2"] = True
        c = {"sensor.b2_charge": 10.0, "sensor.b2_discharge": 5.0}
        _drive(r, ed, 0.0, 500.0, c)
        for _ in range(3):
            c["sensor.b2_discharge"] += 0.05
            _drive(r, ed, 0.0, 500.0, c)
            r.set_energy_dashboard_config(ed)      # the retry, same config

        assert r._battery_sign_contradiction_votes == 3


@pytest.mark.unit
class TestResetClearsTheAudits647:
    def test_reset_sign_detection_drops_a_raised_flag(self):
        """The user presses "Reset sign detection" BECAUSE of the warning; the
        flag must not outlive the lock it was auditing."""
        r = _reader()
        ed = _ed_two_units()
        r._battery_sign_detected["b2"] = True
        c = {"sensor.b2_charge": 10.0, "sensor.b2_discharge": 5.0}
        _drive(r, ed, 0.0, 500.0, c)
        for _ in range(5):
            c["sensor.b2_discharge"] += 0.05
            _drive(r, ed, 0.0, 500.0, c)
        assert r._battery_sign_contradiction is True

        r.reset_sign_state()

        assert r._battery_sign_contradiction is False
        assert r.battery_sign_contradiction_bids == []
        assert r._battery_sign_contradiction_votes == 0
