"""#846 — the learner survives a restart, and a cold learner replays
itself from SEM's OWN recorded series.

Guido, 26.08, after the first deploy left PROD's learner empty because the
car had stopped minutes earlier: *"We already learned something from this —
can you backfill prod."* The recorder already held the evidence: SEM's
per-charger ``commanded_current`` (sparse, SEM's own hand — no 63 A "no
limit" sentinel the KEBA's max-current sensor reports at session start)
against the per-charger ``power`` (the same median-of-3 read the live feed
sees). Replaying those two series IS what the learner would have learned
had it been running.

Two gates the live path takes from the cycle are answered from the SHAPE
of history instead:

* steady — a setpoint must have been in force ``STEADY_AFTER_S`` before a
  row can teach (the Zoe settles in ~10 s; live requires two cycles), and
  a run teaches at most one sample per ``SAMPLE_EVERY_S`` — the live cadence;
* not tapering — a row must sit within ``PLATEAU_FRACTION`` of its run's
  p90. A car reducing its own draw at a steady setpoint is evidence about
  the battery, not the car's response, and the live detector's
  ``full_detected`` is not in any recorded series. The recorded
  ``taper_trend`` cannot stand in: on PROD it says "declining" after every
  one of SEM's own ramp-downs, which would exclude every 8 A window.
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.solar_energy_management.coordinator.watts_per_amp import (
    MIN_SAMPLES,
    WattsPerAmpLearner,
)
from custom_components.solar_energy_management.coordinator.wpa_replay import (
    PLATEAU_FRACTION,
    SAMPLE_EVERY_S,
    STEADY_AFTER_S,
    feed_learner,
    run_replay,
    samples_from_history,
)

NOMINAL_3P = 690.0


def _rows(t0, t1, watts, every=5):
    """Power rows every ``every`` s in [t0, t1). ``watts`` may be a callable."""
    out = []
    t = t0
    while t < t1:
        out.append((float(t), float(watts(t) if callable(watts) else watts)))
        t += every
    return out


def prod_day():
    """PROD 26.08 15:34–16:45 UTC, compressed to what matters (t=0 is the
    16 A command). Runs: A 16 A plateau · SEM's 2 A/step ramp-down · B 8 A ·
    idle · C 8 A · D 10 A · E 16 A ending in the car's own taper."""
    setpoints = [(0, 16), (1577, 14), (1588, 12), (1599, 10), (1610, 8),
                 (1761, 0), (1882, 8), (1936, 10), (1996, 16), (3600, 0)]
    powers = []
    powers += _rows(0, 1577, 10020)                       # A
    powers += [(1577, 9920), (1582, 8500), (1588, 8490),  # ramp: each step
               (1593, 7020), (1599, 6950), (1604, 5120)]  #  ~11 s, settling
    powers += [(1610, 5130)] + _rows(1615, 1761, 3320)    # B (first row still falling)
    powers += _rows(1761, 1882, 0)                        # idle
    powers += _rows(1882, 1936, 3140)                     # C
    powers += _rows(1936, 1996, 5120)                     # D
    def taper(t):                                         # E: plateau, then the car
        if t < 2400:                                      #    winds itself down
            return 9900
        if t < 3000:
            return 9900 - (t - 2400) / 600 * 8000
        return 1900
    powers += _rows(1996, 3600, taper)
    powers += _rows(3600, 3700, 0)
    return setpoints, powers


class TestTheShapeRules:
    def test_nothing_teaches_before_the_setpoint_has_settled(self):
        s = samples_from_history([(0, 16)], _rows(0, 200, 10020))
        assert s and min(t for t, _, _ in s) >= STEADY_AFTER_S

    def test_one_sample_per_live_cycle(self):
        s = samples_from_history([(0, 16)], _rows(0, 600, 10020))
        ts = [t for t, _, _ in s]
        assert all(b - a >= SAMPLE_EVERY_S for a, b in zip(ts, ts[1:], strict=False))
        assert len(s) == len(range(STEADY_AFTER_S, 600, SAMPLE_EVERY_S))

    def test_a_ramp_step_shorter_than_the_settle_time_teaches_nothing(self):
        setpoints, powers = prod_day()
        s = samples_from_history(setpoints, powers)
        assert not [x for x in s if x[1] in (14, 12)]      # only ever ramp steps

    def test_idle_rows_never_sample(self):
        s = samples_from_history([(0, 0)], _rows(0, 600, 0))
        assert s == []
        s = samples_from_history([(0, 16)], _rows(0, 600, 0))
        assert s == []

    def test_the_plateau_rule_drops_the_tail_of_a_taper_and_keeps_the_plateau(self):
        setpoints, powers = prod_day()
        s = [x for x in samples_from_history(setpoints, powers) if x[0] >= 1996]
        assert s, "run E must still teach from its plateau"
        assert all(w >= PLATEAU_FRACTION * 9900 for _, _, w in s)
        assert max(t for t, _, _ in s) < 2500          # nothing from the wind-down

    def test_a_run_that_is_all_taper_is_refused_by_the_learner_not_hidden(self):
        """Setpoint issued after the car had already wound down: the shape
        rule cannot tell (no plateau above it) and passes rows at ~2.4 kW;
        the LEARNER's band refuses them and says so."""
        s = samples_from_history([(0, 16)], _rows(0, 400, lambda t: 2500 - t))
        l = WattsPerAmpLearner()
        rep = feed_learner(l, "c1", 3, 230.0, s)
        assert rep["accepted"] == 0 and rep["refused"] == len(s) > 0
        assert l.watts_per_amp("c1", 3, 16) is None

    def test_samples_come_out_in_time_order(self):
        setpoints, powers = prod_day()
        ts = [t for t, _, _ in samples_from_history(setpoints, powers)]
        assert ts == sorted(ts)

    def test_a_setpoint_in_force_before_the_window_still_counts(self):
        """`include_start_time_state`: the first setpoint row may carry a
        timestamp before the first power row."""
        s = samples_from_history([(-5000, 16)], _rows(0, 300, 10020))
        assert len(s) == len(range(0, 300, SAMPLE_EVERY_S))


class TestProdsDayThroughTheLearner:
    def test_it_learns_the_zoe_at_8_and_16_from_one_afternoon(self):
        setpoints, powers = prod_day()
        l = WattsPerAmpLearner()
        rep = feed_learner(l, "keba_prod", 3, 230.0,
                           samples_from_history(setpoints, powers))
        assert rep["accepted"] >= 2 * MIN_SAMPLES
        assert l.watts_per_amp("keba_prod", 3, 8) == pytest.approx(415, abs=3)
        assert l.watts_per_amp("keba_prod", 3, 16) == pytest.approx(622, abs=8)

    def test_a_setpoint_seen_only_briefly_stays_unlearned(self):
        setpoints, powers = prod_day()
        l = WattsPerAmpLearner()
        feed_learner(l, "keba_prod", 3, 230.0, samples_from_history(setpoints, powers))
        assert l.watts_per_amp("keba_prod", 3, 10) is None       # run D: 60 s
        # …and is bridged from its measured neighbours instead
        assert 4900 < l.watts_for_amps("keba_prod", 3, 10, NOMINAL_3P) < 5600

    def test_the_replay_and_the_live_feed_agree(self):
        """Same car, same numbers, two paths: the bucket medians must match
        to within the jitter of one sample."""
        from custom_components.solar_energy_management.tests.test_846_measured_wpa import _drive, _prod_coordinator  # noqa: E402
        c = _prod_coordinator()
        _drive(c, amps=8, watts=3320.0, cycles=MIN_SAMPLES + 1)
        live = c._wpa_learner.watts_per_amp("keba_prod", 3, 8)
        setpoints, powers = prod_day()
        l = WattsPerAmpLearner()
        feed_learner(l, "keba_prod", 3, 230.0, samples_from_history(setpoints, powers))
        assert l.watts_per_amp("keba_prod", 3, 8) == pytest.approx(live, abs=3)


class _Hass:
    def __init__(self):
        self.tasks = []

    def async_create_task(self, coro):
        self.tasks.append(coro)
        return coro


def _chargers(**over):
    base = {"id": "keba_prod", "ev_phases": 3, "ev_voltage": 230,
            "ev_phase_switching_enabled": False}
    base.update(over)
    return [base]


class TestRunReplay:
    """The seam: entity resolution and the recorder read are injected."""

    def _read(self, series):
        async def read(hass, entity_id, days):
            return list(series.get(entity_id, []))
        return read

    def _resolve(self, hass, cid, key):
        return f"sensor.sem_charger_{cid}_{key}"

    def test_it_feeds_the_learner_from_both_series(self):
        setpoints, powers = prod_day()
        series = {"sensor.sem_charger_keba_prod_commanded_current": setpoints,
                  "sensor.sem_charger_keba_prod_power": powers}
        l = WattsPerAmpLearner()
        rep = asyncio.run(run_replay(None, l, _chargers(), days=7,
                                     read=self._read(series), resolve=self._resolve))
        r = rep["keba_prod"]
        assert r["days"] == 7 and r["rows"] == len(powers)
        assert r["accepted"] >= 2 * MIN_SAMPLES and r["reason"] is None
        assert l.watts_per_amp("keba_prod", 3, 16) is not None

    def test_no_history_is_said_not_silently_empty(self):
        l = WattsPerAmpLearner()
        rep = asyncio.run(run_replay(None, l, _chargers(), days=7,
                                     read=self._read({}), resolve=self._resolve))
        assert rep["keba_prod"]["reason"] == "no_history"
        assert l.is_cold("keba_prod", 3)

    def test_phase_switching_installs_are_skipped_with_a_reason(self):
        """History cannot say which phase count was in force per row; the
        live path learns per phase there. Honest skip, not a guess."""
        setpoints, powers = prod_day()
        series = {"sensor.sem_charger_keba_prod_commanded_current": setpoints,
                  "sensor.sem_charger_keba_prod_power": powers}
        l = WattsPerAmpLearner()
        rep = asyncio.run(run_replay(None, l, _chargers(ev_phase_switching_enabled=True),
                                     days=7, read=self._read(series), resolve=self._resolve))
        assert rep["keba_prod"]["reason"] == "phase_switching_enabled"
        assert l.is_cold("keba_prod", 3)

    def test_a_warm_charger_is_left_alone(self):
        """Replay is for the COLD start. A learner with live samples has
        newer evidence than the recorder's tail, and must not be rewound."""
        setpoints, powers = prod_day()
        series = {"sensor.sem_charger_keba_prod_commanded_current": setpoints,
                  "sensor.sem_charger_keba_prod_power": powers}
        l = WattsPerAmpLearner()
        for _ in range(MIN_SAMPLES):
            l.record("keba_prod", phases=3, commanded_amps=16, observed_w=9000.0,
                     nominal_wpa=NOMINAL_3P)
        rep = asyncio.run(run_replay(None, l, _chargers(), days=7,
                                     read=self._read(series), resolve=self._resolve))
        assert rep["keba_prod"]["reason"] == "warm"
        assert l.watts_per_amp("keba_prod", 3, 16) == pytest.approx(562.5)

    def test_a_corrected_phase_count_replays_the_same_history(self):
        """PROD 26.08: ev_phases sat at 1 for a day; every replayed sample
        was refused (phase_belief) under 1. Set to 3, the same week of
        history must teach — the refusals under 1 are not "warm"."""
        setpoints, powers = prod_day()
        series = {"sensor.sem_charger_keba_prod_commanded_current": setpoints,
                  "sensor.sem_charger_keba_prod_power": powers}
        l = WattsPerAmpLearner()
        rep1 = asyncio.run(run_replay(None, l, _chargers(ev_phases=1), days=7,
                                      read=self._read(series), resolve=self._resolve))
        assert rep1["keba_prod"]["accepted"] == 0 and rep1["keba_prod"]["refused"] > 0
        # 16 A under "1 phase" reads 2.7 phases' worth → phase_belief; the 8 A
        # rows (1.8x) are too ambiguous to blame the belief → implausible.
        # Every refusal is on the record either way.
        reasons = l.refusal_reasons("keba_prod", 1)
        assert reasons.get("phase_belief", 0) > 0
        assert sum(reasons.values()) == rep1["keba_prod"]["refused"]
        rep3 = asyncio.run(run_replay(None, l, _chargers(ev_phases=3), days=7,
                                      read=self._read(series), resolve=self._resolve))
        assert rep3["keba_prod"]["reason"] is None
        assert l.watts_per_amp("keba_prod", 3, 16) is not None

    def test_a_failing_read_is_a_reason_not_a_crash(self):
        async def boom(hass, entity_id, days):
            raise RuntimeError("recorder not ready")
        l = WattsPerAmpLearner()
        rep = asyncio.run(run_replay(None, l, _chargers(), days=7,
                                     read=boom, resolve=self._resolve))
        assert rep["keba_prod"]["reason"].startswith("read_failed")


class TestItIsPersistedAndReplayedAtBoot:
    def test_storage_keeps_the_learner_state(self):
        from custom_components.solar_energy_management.coordinator.storage import SEMStorage
        st = SEMStorage.__new__(SEMStorage)
        st._energy_data = {}
        assert st.get_wpa_learner_state() == {}
        l = WattsPerAmpLearner()
        for _ in range(MIN_SAMPLES):
            l.record("c1", phases=3, commanded_amps=16, observed_w=10020.0,
                     nominal_wpa=NOMINAL_3P)
        st.set_wpa_learner_state(l.as_state())
        b = WattsPerAmpLearner()
        b.restore(st.get_wpa_learner_state())
        assert b.watts_per_amp("c1", 3, 16) == pytest.approx(626.25)

    def test_the_coordinator_restores_at_boot_and_persists_each_cycle(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        src = inspect.getsource(cm.SEMCoordinator._async_update_data)
        assert "_wpa_learner.restore(self._storage.get_wpa_learner_state())" in src
        assert "set_wpa_learner_state(self._wpa_learner.as_state())" in src
        assert "_schedule_wpa_replay()" in src

    def test_a_cold_learner_schedules_the_replay_once(self):
        from custom_components.solar_energy_management.tests.test_846_measured_wpa import _prod_coordinator  # noqa: E402
        c = _prod_coordinator()
        c.hass = _Hass()
        c._schedule_wpa_replay()
        c._schedule_wpa_replay()
        assert len(c.hass.tasks) == 1
        for t in c.hass.tasks:
            t.close()

    def test_a_warm_learner_schedules_nothing(self):
        from custom_components.solar_energy_management.tests.test_846_measured_wpa import _drive, _prod_coordinator  # noqa: E402
        c = _prod_coordinator()
        c.hass = _Hass()
        _drive(c)
        c._schedule_wpa_replay()
        assert c.hass.tasks == []

    def test_the_report_is_published_beside_the_table(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        src = inspect.getsource(cm.SEMCoordinator._async_update_data)
        assert 'result["ev_watts_per_amp_replay"]' in src
