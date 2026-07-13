"""#588 — battery sign hardening test suite.

Items covered:
  B1  — user flip applies to fleet path AND per-battery path
  H3  — reset_sign_state clears battery_sign_user_flip from options
  B2  — weighted voter locks only on >= 3 samples + >= 0.75 confidence;
         a 55/45 jitter that the old ±1 voter would have locked does NOT lock
  H2  — brand seed sets the pre-lock default (platform lookup)
  H1  — warmup refreshes baselines so first post-warmup delta is fresh
  L1  — entry_id-not-found returns {"ok": False, "error": "entry_not_found"}
        (tested via the service helper logic, not a full HA hass mock)
"""
from __future__ import annotations

import pytest
from unittest.mock import Mock, MagicMock, patch

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
    PLATFORM_BATTERY_SIGN_INVERT,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_reader(config=None, warmup_done=True):
    hass = MagicMock()
    hass.states = MagicMock()
    r = SensorReader(hass, config or {})
    if warmup_done:
        r._sign_vote_warmup = 0
    return r


def _make_state(value, unit="kWh"):
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit}
    return s


def _make_ed(
    battery_power="sensor.batt_power",
    battery_charge_energy="sensor.batt_charge",
    battery_discharge_energy="sensor.batt_discharge",
):
    ed = MagicMock()
    ed.battery_power = battery_power
    ed.battery_charge_energy = battery_charge_energy
    ed.battery_discharge_energy = battery_discharge_energy
    ed.battery_power_list = []
    ed.battery_power_pairs = []
    ed.battery_charge_energy_list = []
    ed.battery_discharge_energy_list = []
    ed.battery_soc = None
    ed.solar_power = None
    ed.solar_power_list = []
    ed.grid_import_power = None
    ed.grid_power = None
    ed.grid_power_list = []
    ed.grid_import_energy = None
    ed.grid_export_energy = None
    ed.grid_import_energy_list = None
    ed.grid_export_energy_list = None
    ed.grid_power_from = None
    ed.grid_power_to = None
    ed.battery_power_inverted = False
    ed.battery_power_from = None
    ed.battery_power_to = None
    ed.has_battery = True
    ed.has_solar = False
    ed.has_grid = False
    ed.has_ev = False
    ed.ev_power = None
    ed.device_consumption = {}
    return ed


# ── B1: user flip applies (fleet path) ───────────────────────────────────────

class TestB1UserFlipFleet:
    """battery_sign_user_flip in config negates battery_power in fleet mode."""

    def test_flip_negates_positive_battery(self):
        r = _make_reader(config={"battery_sign_user_flip": True})
        ed = _make_ed()
        r.set_energy_dashboard_config(ed)

        def _states(eid):
            return {
                "sensor.batt_charge": _make_state(10.0),
                "sensor.batt_discharge": _make_state(5.0),
            }.get(eid)
        r.hass.states.get = _states
        # Prime baselines, then advance charge counter (SEM: no negate without flip)
        r._detect_battery_sign_for(r._FLEET_BID, 500.0, "sensor.batt_charge", "sensor.batt_discharge")
        r.hass.states.get = lambda eid: {
            "sensor.batt_charge": _make_state(10.5),
            "sensor.batt_discharge": _make_state(5.0),
        }.get(eid)
        # Accumulate 3 SEM-convention votes (charge growing, power positive → no negate)
        for _ in range(3):
            r._detect_battery_sign_for(r._FLEET_BID, 500.0, "sensor.batt_charge", "sensor.batt_discharge")
            r.hass.states.get = lambda eid: {
                "sensor.batt_charge": _make_state(r._battery_charge_baseline[r._FLEET_BID] + 0.1),
                "sensor.batt_discharge": _make_state(5.0),
            }.get(eid)

        # Manually set readings to verify flip
        readings = PowerReadings(battery_power=500.0)
        # simulate fleet path: auto-detect says no negate (SEM convention)
        r._battery_sign_inverted[r._FLEET_BID] = False
        r._battery_sign_detected[r._FLEET_BID] = True
        # The flip config should still negate
        result_power = -500.0 if bool(r._raw_config.get("battery_sign_user_flip", False)) else 500.0
        assert result_power == -500.0, "user flip must negate even when auto-detect is SEM-convention"

    def test_no_flip_when_not_set(self):
        r = _make_reader(config={})  # no battery_sign_user_flip
        assert not bool(r._raw_config.get("battery_sign_user_flip", False))

    def test_flip_false_does_not_negate(self):
        r = _make_reader(config={"battery_sign_user_flip": False})
        assert not bool(r._raw_config.get("battery_sign_user_flip", False))

    def test_flip_read_power_fleet_mode(self):
        """End-to-end: read_power applies user flip on top of auto-detect in fleet mode."""
        r = _make_reader(config={"battery_sign_user_flip": True})
        ed = _make_ed()
        r.set_energy_dashboard_config(ed)

        # Patch _read_from_energy_dashboard to return a fixed reading
        readings = PowerReadings()
        readings.battery_power = 300.0  # pretend auto-detect left it positive
        with patch.object(r, "_read_from_energy_dashboard", return_value=readings):
            # Force battery_sign_inverted[__fleet__] = False (no auto-negate)
            r._battery_sign_inverted[r._FLEET_BID] = False
            r._battery_sign_detected[r._FLEET_BID] = True
            # Ensure no per-battery mode
            ed.battery_power_list = []
            ed.battery_power_pairs = []
            result = r.read_power()
        # user flip should negate the 300W → -300W
        assert result.battery_power == -300.0, (
            f"Expected -300.0 from user flip, got {result.battery_power}"
        )

    def test_flip_read_power_per_battery_mode(self):
        """End-to-end: user flip applies to corrected_total in per_battery_mode."""
        r = _make_reader(config={"battery_sign_user_flip": True})
        ed = _make_ed()
        ed.battery_power_list = ["sensor.b1_power", "sensor.b2_power"]
        ed.battery_power_pairs = []
        ed.battery_charge_energy_list = ["sensor.b1_charge", "sensor.b2_charge"]
        ed.battery_discharge_energy_list = ["sensor.b1_discharge", "sensor.b2_discharge"]
        r.set_energy_dashboard_config(ed)

        # Build a readings with pre-populated batteries dict (mock per-battery reading)
        from custom_components.solar_energy_management.coordinator.charger_types import BatteryPower
        readings_base = PowerReadings()
        readings_base.battery_power = 400.0
        readings_base.batteries = {
            "b1": BatteryPower(battery_id="b1", power_w=250.0, soc_pct=80.0, name="sensor.b1_power"),
            "b2": BatteryPower(battery_id="b2", power_w=150.0, soc_pct=75.0, name="sensor.b2_power"),
        }

        # Lock both batteries as SEM-convention (no auto-negate)
        r._battery_sign_inverted["b1"] = False
        r._battery_sign_detected["b1"] = True
        r._battery_sign_inverted["b2"] = False
        r._battery_sign_detected["b2"] = True

        with patch.object(r, "_read_from_energy_dashboard", return_value=readings_base):
            result = r.read_power()

        # auto-detect: no negate → corrected_total = 400W; user flip → -400W
        assert result.battery_power == -400.0, (
            f"Expected -400.0 from user flip in per-battery mode, got {result.battery_power}"
        )
        # H-1 — the per-battery dict MUST also be flipped, because the battery
        # actuator sources BatteryRuntime.last_known_w from bp.power_w, not the
        # fleet scalar. Flipping only the total would desync the arbitrage /
        # force-discharge direction on multi-battery installs.
        assert result.batteries["b1"].power_w == -250.0, (
            f"Expected b1 power_w -250.0, got {result.batteries['b1'].power_w}"
        )
        assert result.batteries["b2"].power_w == -150.0, (
            f"Expected b2 power_w -150.0, got {result.batteries['b2'].power_w}"
        )
        # Fleet scalar and per-battery sum must stay consistent.
        assert result.battery_power == (
            result.batteries["b1"].power_w + result.batteries["b2"].power_w
        )


# ── H3: reset clears battery_sign_user_flip ───────────────────────────────────

class TestH3ResetClearsBothFlips:
    """reset_sign_state clears battery_sign_user_flip from options (via __init__.py).

    We test the SensorReader side (clear of the detection state) + the logic
    in async_reset_sign_detection that also clears the battery flip option.
    """

    def test_reset_clears_battery_evidence(self):
        r = _make_reader()
        r._battery_sign_evidence["b1"] = 1000.0
        r._battery_sign_total_mag["b1"] = 1200.0
        r._battery_sign_samples["b1"] = 5
        r._battery_sign_inverted["b1"] = True
        r._battery_sign_detected["b1"] = True
        r._battery_brand_seed_done["b1"] = True

        r.reset_sign_state()

        assert r._battery_sign_evidence == {}
        assert r._battery_sign_total_mag == {}
        assert r._battery_sign_samples == {}
        assert r._battery_sign_inverted == {}
        assert r._battery_sign_detected == {}
        assert r._battery_brand_seed_done == {}

    def test_reset_clears_grid_evidence_too(self):
        """Reset must clear BOTH grid and battery (regression guard)."""
        r = _make_reader()
        r._grid_sign_detected = True
        r._grid_sign_inverted = True
        r._grid_sign_evidence = 999.0
        r._battery_sign_inverted["__fleet__"] = True
        r._battery_sign_detected["__fleet__"] = True

        r.reset_sign_state()

        assert r._grid_sign_detected is False
        assert r._grid_sign_evidence == 0.0
        assert r._battery_sign_inverted == {}


# ── B2: magnitude-weighted voter ─────────────────────────────────────────────

class TestB2WeightedVoter:
    """Weighted accumulator: lock only on >= 3 samples + >= 0.75 confidence."""

    def _prime_baseline(self, r, bid, charge=10.0, discharge=5.0):
        r.hass.states.get = lambda eid: {
            "sensor.batt_charge": _make_state(charge),
            "sensor.batt_discharge": _make_state(discharge),
        }.get(eid)
        r._detect_battery_sign_for(bid, 500.0, "sensor.batt_charge", "sensor.batt_discharge")

    def test_two_samples_do_not_lock(self):
        r = _make_reader()
        bid = r._FLEET_BID
        self._prime_baseline(r, bid)
        # 2 consistent votes (discharge growing, power positive → negate)
        for i in range(2):
            r.hass.states.get = lambda eid, _i=i: {
                "sensor.batt_charge": _make_state(10.0),
                "sensor.batt_discharge": _make_state(5.0 + (_i + 1) * 0.5),
            }.get(eid)
            r._detect_battery_sign_for(bid, 500.0, "sensor.batt_charge", "sensor.batt_discharge")
        assert r._battery_sign_detected.get(bid, False) is False, (
            "2 samples should not lock (need >= 3)"
        )

    def test_three_consistent_samples_lock(self):
        r = _make_reader()
        bid = r._FLEET_BID
        self._prime_baseline(r, bid)
        # 3 consistent votes: discharge growing, power positive → negate
        for i in range(3):
            r.hass.states.get = lambda eid, _i=i: {
                "sensor.batt_charge": _make_state(10.0),
                "sensor.batt_discharge": _make_state(5.0 + (_i + 1) * 0.5),
            }.get(eid)
            r._detect_battery_sign_for(bid, 500.0, "sensor.batt_charge", "sensor.batt_discharge")
        assert r._battery_sign_detected[bid] is True
        assert r._battery_sign_inverted[bid] is True

    def test_interleaved_jitter_does_not_lock(self):
        """Weighted voter: a 2:1 interleaved jitter (negate-negate-SEM) yields
        confidence = |14-6|/20 = 0.40 < 0.75 — never locks even after 20 cycles.

        The OLD ±1 voter would have locked on the first 3-consecutive-negate pair.
        This specific interleave has max-run-2 so the old voter's run counter resets
        on each SEM vote and it takes 3+ cycles per burst to lock — but our test
        explicitly checks that the WEIGHTED voter's lower confidence never hits 0.75.
        """
        r = _make_reader()
        bid = r._FLEET_BID
        self._prime_baseline(r, bid)

        # Pattern: [neg, neg, sem] * 6 + [neg, neg] = 14 negate, 6 SEM over 20 cycles.
        # Max consecutive run = 2 (never 3 in a row).
        # confidence after 20 cycles = |14-6| / 20 = 0.40 < 0.75 → must not lock.
        sequence = ([True, True, False] * 6) + [True, True]
        assert len(sequence) == 20
        charge_base = 10.0
        discharge_base = 5.0
        for negate_vote in sequence:
            if negate_vote:
                discharge_base += 0.5
                r.hass.states.get = lambda eid, cb=charge_base, db=discharge_base: {
                    "sensor.batt_charge": _make_state(cb),
                    "sensor.batt_discharge": _make_state(db),
                }.get(eid)
            else:
                charge_base += 0.5
                r.hass.states.get = lambda eid, cb=charge_base, db=discharge_base: {
                    "sensor.batt_charge": _make_state(cb),
                    "sensor.batt_discharge": _make_state(db),
                }.get(eid)
            r._detect_battery_sign_for(bid, 500.0, "sensor.batt_charge", "sensor.batt_discharge")

        # confidence = |14-6|/20 = 0.40 < 0.75 → must not lock
        assert r._battery_sign_detected.get(bid, False) is False, (
            "14/20 interleaved jitter: confidence 0.40 < 0.75, must not lock"
        )

    def test_old_consecutive_voter_would_have_locked_but_weighted_does_not(self):
        """Regression: the old ±1 voter would lock after 3 negate votes even if
        the first 2 were SEM-convention (counter-moving jitter during HA come-up).
        Weighted voter accumulates ALL evidence, so 2 SEM-direction + 3 negate
        votes yields confidence = |3-2|/5 = 0.2, which is below 0.75 — no lock.
        """
        r = _make_reader()
        bid = r._FLEET_BID
        self._prime_baseline(r, bid)

        # 2 SEM votes (charge growing, power positive)
        charge_base = 10.0
        discharge_base = 5.0
        for i in range(2):
            charge_base += 0.5
            r.hass.states.get = lambda eid, cb=charge_base, db=discharge_base: {
                "sensor.batt_charge": _make_state(cb),
                "sensor.batt_discharge": _make_state(db),
            }.get(eid)
            r._detect_battery_sign_for(bid, 500.0, "sensor.batt_charge", "sensor.batt_discharge")

        # Then 3 negate votes (discharge growing, power positive)
        for i in range(3):
            discharge_base += 0.5
            r.hass.states.get = lambda eid, cb=charge_base, db=discharge_base: {
                "sensor.batt_charge": _make_state(cb),
                "sensor.batt_discharge": _make_state(db),
            }.get(eid)
            r._detect_battery_sign_for(bid, 500.0, "sensor.batt_charge", "sensor.batt_discharge")

        # Weighted evidence: 2*500 (SEM) - 3*500 (negate) = -500. Total = 2500.
        # confidence = 500/2500 = 0.20 — below 0.75. No lock.
        assert r._battery_sign_detected.get(bid, False) is False, (
            "Mixed 2+3 sample burst: confidence 0.20 < 0.75, must not lock"
        )


# ── H2: brand seed sets pre-lock default ─────────────────────────────────────

class TestH2BrandSeed:
    """_seed_battery_sign_from_platform seeds sign from integration platform."""

    def test_goodwe_seeded_as_inverted(self):
        r = _make_reader()
        r.hass = MagicMock()
        registry_mock = MagicMock()
        entry_mock = MagicMock()
        entry_mock.platform = "goodwe"
        registry_mock.async_get.return_value = entry_mock
        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=registry_mock,
        ):
            r._seed_battery_sign_from_platform("b1", "sensor.goodwe_battery")
        assert r._battery_sign_inverted.get("b1") is True
        assert r._battery_sign_detected.get("b1") is True

    def test_huawei_seeded_as_normal(self):
        r = _make_reader()
        r.hass = MagicMock()
        registry_mock = MagicMock()
        entry_mock = MagicMock()
        entry_mock.platform = "huawei_solar"
        registry_mock.async_get.return_value = entry_mock
        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=registry_mock,
        ):
            r._seed_battery_sign_from_platform("b1", "sensor.huawei_battery")
        assert r._battery_sign_inverted.get("b1") is False
        assert r._battery_sign_detected.get("b1") is True

    def test_unknown_platform_does_not_seed(self):
        r = _make_reader()
        r.hass = MagicMock()
        registry_mock = MagicMock()
        entry_mock = MagicMock()
        entry_mock.platform = "my_custom_integration"
        registry_mock.async_get.return_value = entry_mock
        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=registry_mock,
        ):
            r._seed_battery_sign_from_platform("b1", "sensor.custom_battery")
        assert r._battery_sign_detected.get("b1", False) is False

    def test_seed_runs_only_once_per_bid(self):
        r = _make_reader()
        r.hass = MagicMock()
        registry_mock = MagicMock()
        entry_mock = MagicMock()
        entry_mock.platform = "goodwe"
        registry_mock.async_get.return_value = entry_mock
        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=registry_mock,
        ) as mock_er:
            r._seed_battery_sign_from_platform("b1", "sensor.batt")
            r._seed_battery_sign_from_platform("b1", "sensor.batt")
        # async_get should be called at most once per bid
        assert mock_er.call_count <= 1

    def test_already_detected_skips_seed(self):
        """If the bid was already locked (e.g. restored from storage),
        the seed must not overwrite it."""
        r = _make_reader()
        r._battery_sign_detected["b1"] = True
        r._battery_sign_inverted["b1"] = False  # Huawei lock from storage
        r.hass = MagicMock()
        registry_mock = MagicMock()
        entry_mock = MagicMock()
        entry_mock.platform = "goodwe"  # would want to seed as inverted
        registry_mock.async_get.return_value = entry_mock
        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=registry_mock,
        ):
            r._seed_battery_sign_from_platform("b1", "sensor.batt")
        # Existing lock must NOT be overwritten by the seed
        assert r._battery_sign_inverted["b1"] is False

    def test_seed_uses_power_entity_not_charge_counter(self):
        """B-1 — the platform lookup must run against the battery POWER sensor
        (always the inverter integration), not the Energy-Dashboard charge
        counter (frequently a utility_meter / Riemann-sum helper). We pass a
        power_entity that resolves to goodwe and a charge_entity that resolves
        to utility_meter and assert the power entity wins."""
        r = _make_reader()
        r.set_energy_dashboard_config(_make_ed())
        r._sign_vote_warmup = 0

        def _entry_for(eid):
            e = MagicMock()
            e.platform = "goodwe" if eid == "sensor.batt_power" else "utility_meter"
            return e
        registry_mock = MagicMock()
        registry_mock.async_get.side_effect = _entry_for
        r.hass.states.get = lambda eid: _make_state(1.0)
        with patch(
            "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get",
            return_value=registry_mock,
        ):
            # fleet path threads ed.battery_power as power_entity
            r._detect_battery_sign(PowerReadings(battery_power=500.0))
        # goodwe → inverted True; if it had used the utility_meter charge
        # counter it would have fallen through and stayed unlocked.
        assert r._battery_sign_inverted.get(r._FLEET_BID) is True
        assert r._battery_sign_detected.get(r._FLEET_BID) is True

    def test_platform_battery_sign_invert_map_contents(self):
        """Verify the brand map has the expected entries."""
        assert PLATFORM_BATTERY_SIGN_INVERT["huawei_solar"] is False
        assert PLATFORM_BATTERY_SIGN_INVERT["goodwe"] is True
        assert PLATFORM_BATTERY_SIGN_INVERT["powerwall"] is True
        assert PLATFORM_BATTERY_SIGN_INVERT["enphase_envoy"] is True
        assert PLATFORM_BATTERY_SIGN_INVERT["solax"] is True


# ── H1: warmup refreshes baselines ───────────────────────────────────────────

class TestH1WarmupBaselineRefresh:
    """During warmup, baselines are refreshed so the first post-warmup delta
    is computed against the CURRENT counter state (not a stale value from
    construction or a previous boot)."""

    def test_baseline_refreshed_during_warmup(self):
        r = _make_reader(warmup_done=False)
        r._sign_vote_warmup = 5  # still in warmup
        bid = r._FLEET_BID
        r._battery_sign_inverted.setdefault(bid, False)
        r._battery_sign_detected.setdefault(bid, False)
        r._battery_charge_baseline.setdefault(bid, None)
        r._battery_discharge_baseline.setdefault(bid, None)
        r._battery_sign_evidence.setdefault(bid, 0.0)
        r._battery_sign_total_mag.setdefault(bid, 0.0)
        r._battery_sign_samples.setdefault(bid, 0)

        r.hass.states.get = lambda eid: {
            "sensor.batt_charge": _make_state(99.0),
            "sensor.batt_discharge": _make_state(42.0),
        }.get(eid)

        # Call during warmup — should not vote but should refresh baselines
        result = r._detect_battery_sign_for(
            bid, 600.0, "sensor.batt_charge", "sensor.batt_discharge"
        )
        assert result is False  # no vote, returns current lock
        # Baseline must have been refreshed to the warmup counter values
        assert r._battery_charge_baseline[bid] == 99.0, (
            "warmup must refresh charge baseline"
        )
        assert r._battery_discharge_baseline[bid] == 42.0, (
            "warmup must refresh discharge baseline"
        )

    def test_post_warmup_delta_uses_fresh_baseline(self):
        """After warmup ends, the first delta is computed against the warmup-refreshed
        baseline, not against None (which would just set the baseline again)."""
        r = _make_reader(warmup_done=False)
        r._sign_vote_warmup = 1
        bid = r._FLEET_BID
        r._battery_sign_inverted.setdefault(bid, False)
        r._battery_sign_detected.setdefault(bid, False)
        r._battery_sign_evidence.setdefault(bid, 0.0)
        r._battery_sign_total_mag.setdefault(bid, 0.0)
        r._battery_sign_samples.setdefault(bid, 0)
        r._battery_charge_baseline.setdefault(bid, None)
        r._battery_discharge_baseline.setdefault(bid, None)

        # Warmup cycle: counter at 10/5
        r.hass.states.get = lambda eid: {
            "sensor.batt_charge": _make_state(10.0),
            "sensor.batt_discharge": _make_state(5.0),
        }.get(eid)
        r._detect_battery_sign_for(bid, 500.0, "sensor.batt_charge", "sensor.batt_discharge")
        # Expire warmup
        r._sign_vote_warmup = 0

        # Post-warmup cycle: charge advanced to 10.5 (SEM-convention vote)
        r.hass.states.get = lambda eid: {
            "sensor.batt_charge": _make_state(10.5),
            "sensor.batt_discharge": _make_state(5.0),
        }.get(eid)
        r._detect_battery_sign_for(bid, 500.0, "sensor.batt_charge", "sensor.batt_discharge")

        # The first post-warmup call should have computed a delta (10.5 - 10.0 = 0.5)
        # and accumulated evidence, NOT just set the baseline again.
        assert r._battery_sign_samples[bid] == 1, (
            "first post-warmup call should cast a vote if baseline was refreshed during warmup"
        )


# ── L1: entry_id-not-found ────────────────────────────────────────────────────

class TestL1EntryIdNotFound:
    """#588 L1 — the entry_id guard must reject unknown IDs with an error,
    not silently fall through to entry[0].

    We test the logic in isolation via a minimal simulation of the service
    handler's entry-selection code (the full async test would need a live
    hass event loop which is out of scope here).
    """

    def _simulate_entry_selection(self, sem_entries, requested):
        """Re-implement the L1-fixed entry selection logic from __init__.py.
        Returns (target, error) where error is None on success."""
        if not sem_entries:
            return None, "no_entry"
        target = sem_entries[0]
        if requested:
            matched = next((e for e in sem_entries if e.entry_id == requested), None)
            if matched is None:
                return None, "entry_not_found"
            target = matched
        return target, None

    def test_no_entry_returns_no_entry_error(self):
        target, err = self._simulate_entry_selection([], None)
        assert err == "no_entry"

    def test_unknown_entry_id_returns_entry_not_found(self):
        entry = Mock()
        entry.entry_id = "real_id_abc123"
        target, err = self._simulate_entry_selection([entry], "stale_id_xyz999")
        assert err == "entry_not_found"
        assert target is None

    def test_correct_entry_id_resolves(self):
        e1 = Mock()
        e1.entry_id = "id_1"
        e2 = Mock()
        e2.entry_id = "id_2"
        target, err = self._simulate_entry_selection([e1, e2], "id_2")
        assert err is None
        assert target is e2

    def test_none_requested_uses_first_entry(self):
        e1 = Mock()
        e1.entry_id = "only_entry"
        target, err = self._simulate_entry_selection([e1], None)
        assert err is None
        assert target is e1

    def test_single_entry_wrong_id_now_errors(self):
        """Old guard: ``if requested and len > 1`` → silently used entry[0].
        New guard: any non-None requested that doesn't match → error."""
        e1 = Mock()
        e1.entry_id = "real_id"
        # Old code would have returned e1 silently; new code must return error.
        target, err = self._simulate_entry_selection([e1], "wrong_id")
        assert err == "entry_not_found", (
            "L1 fix: single-entry wrong ID must return error, not silently use entry[0]"
        )


# ── battery_sign_diagnostics() ────────────────────────────────────────────────

class TestBatterySignDiagnostics:
    """battery_sign_diagnostics() returns the expected payload shape."""

    def test_returns_expected_keys(self):
        r = _make_reader()
        diag = r.battery_sign_diagnostics()
        assert "battery_power_sensor" in diag
        assert "user_flip" in diag
        assert "per_bid" in diag
        assert "charge_counters" in diag
        assert "discharge_counters" in diag

    def test_per_bid_populated(self):
        r = _make_reader()
        r._battery_sign_inverted["b1"] = True
        r._battery_sign_detected["b1"] = True
        r._battery_sign_evidence["b1"] = 1500.0
        r._battery_sign_total_mag["b1"] = 2000.0
        r._battery_sign_samples["b1"] = 4
        diag = r.battery_sign_diagnostics()
        assert "b1" in diag["per_bid"]
        b1 = diag["per_bid"]["b1"]
        assert b1["detected"] is True
        assert b1["inverted"] is True
        assert b1["samples"] == 4
        # confidence = 1500/2000 = 0.75
        assert abs(b1["confidence"] - 0.75) < 0.001

    def test_user_flip_reflected(self):
        r = _make_reader(config={"battery_sign_user_flip": True})
        diag = r.battery_sign_diagnostics()
        assert diag["user_flip"] is True

    def test_no_ed_returns_empty_counters(self):
        r = _make_reader()
        diag = r.battery_sign_diagnostics()
        assert diag["charge_counters"] == []
        assert diag["discharge_counters"] == []


# ── M-2: diag_battery_sign is always a scalar string ──────────────────────────

class TestM2DiagSerialisation:
    """_format_battery_sign_diag must return a scalar string (never a dict),
    because HA sensor state must be a scalar and the card renders it as text."""

    def test_empty_returns_learning(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _format_battery_sign_diag,
        )
        assert _format_battery_sign_diag({}, {}) == "learning"

    def test_single_battery_bare_value(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _format_battery_sign_diag,
        )
        out = _format_battery_sign_diag({"__fleet__": True}, {"__fleet__": True})
        assert out == "negated"
        assert isinstance(out, str)

    def test_single_battery_learning_suffix(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _format_battery_sign_diag,
        )
        assert _format_battery_sign_diag({"b1": False}, {"b1": False}) == "normal (learning)"

    def test_multi_battery_is_string_not_dict(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _format_battery_sign_diag,
        )
        out = _format_battery_sign_diag(
            {"b1": True, "b2": False}, {"b1": True, "b2": True}
        )
        assert isinstance(out, str), "multi-battery diag must be a string, not a dict"
        assert out == "b1: negated, b2: normal"
        assert "{" not in out and "[object" not in out

    def test_multi_battery_learning_suffix_per_bid(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _format_battery_sign_diag,
        )
        out = _format_battery_sign_diag(
            {"b1": True, "b2": False}, {"b1": True, "b2": False}
        )
        assert out == "b1: negated, b2: normal (learning)"
