"""#1045 — the measured pack size counted only what the house drew.

RienduPre, 03.10.2026: 2 × Sessy 5 kWh (10 kWh nameplate),
``sensor.sem_battery_measured_capacity_kwh`` = 7.89 kWh, drift −21.1 % over
33 nights. The pack is fine.

kWh per percent is energy over SOC span. The span counts everything that
left the pack — house, car, grid — but the energy was ``drain_kwh``, which is
the house's share only. Every night with EV assist or export read low; the
reporter's car took 12.8 % of its energy from the battery.

The mirror of the same mistake: the span is NET of any charge the pack took
in the same night, while the energy was gross. A night that also charged
read HIGH — the direction that sizes every budget against a pack that is not
there.

``drain_kwh`` itself stays the house's share: the overnight need wants
exactly that, and it is pinned here too.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.battery_night import (
    BatteryNightTracker,
    Sample,
)
from custom_components.solar_energy_management.coordinator.measured_capacity import (
    MAX_NIGHT_CHARGE_SHARE,
    MAX_UNCOUNTED_SHARE_OLD_RECORD,
    MIN_NEED_SAMPLES,
    MIN_SAMPLES,
    capacity_progress,
    expected_overnight_need,
    measured_capacity,
)

PACK_KWH = 10.0


def _rec(date, *, soc_start=90.0, soc_morning=40.0, drain=5.0, assist=0.0,
         export=0.0, charge=0.0, trainable=True):
    """A record as the recorder writes it now."""
    return {"date": date, "soc_start": soc_start, "soc_morning": soc_morning,
            "drain_kwh": drain, "assist_kwh": assist, "export_kwh": export,
            "charge_kwh": charge, "trainable": trainable}


def _old(date, **kw):
    """A record sealed before the recorder counted charge (#800 shape)."""
    r = _rec(date, **kw)
    del r["charge_kwh"]
    return r


def _dates(n):
    return [f"2026-09-{d:02d}" for d in range(1, n + 1)]


@pytest.mark.unit
class TestTheSpanAndTheEnergyCountTheSameThing:

    def test_ev_assist_counts_toward_the_pack_size(self):
        """The reporter's shape: 50 % of a 10 kWh pack is 5 kWh, of which the
        car took 2. Reading the house's 3 kWh alone says 6 kWh."""
        recs = [_rec(d, drain=3.0, assist=2.0) for d in _dates(MIN_SAMPLES)]
        # Not vacuous: the house share alone is exactly the old read.
        assert 3.0 / 50.0 * 100.0 == pytest.approx(6.0)
        m = measured_capacity(recs)
        assert m is not None
        assert m.usable_kwh == pytest.approx(PACK_KWH, abs=0.01)
        assert m.drift_vs(PACK_KWH) == pytest.approx(0.0, abs=0.001)

    def test_battery_export_counts_toward_the_pack_size(self):
        recs = [_rec(d, drain=1.0, export=4.0) for d in _dates(MIN_SAMPLES)]
        m = measured_capacity(recs)
        assert m.usable_kwh == pytest.approx(PACK_KWH, abs=0.01)

    def test_every_outflow_at_once(self):
        recs = [_rec(d, drain=2.0, assist=1.5, export=1.5)
                for d in _dates(MIN_SAMPLES)]
        assert measured_capacity(recs).usable_kwh == pytest.approx(
            PACK_KWH, abs=0.01)

    def test_a_night_only_the_car_drew_is_still_a_measurement(self):
        """The span is real whichever way the energy went."""
        recs = [_rec(d, drain=0.0, assist=5.0) for d in _dates(MIN_SAMPLES)]
        m = measured_capacity(recs)
        assert m is not None
        assert m.usable_kwh == pytest.approx(PACK_KWH, abs=0.01)

    def test_33_nights_mostly_with_assist_no_longer_drift(self):
        """Mixed history, as on the reporter's install, with the assist
        nights in the majority so the median cannot hide them."""
        dates = [f"2026-08-{d:02d}" for d in range(1, 32)] + [
            "2026-09-01", "2026-09-02"]
        recs = []
        for i, d in enumerate(dates):
            if i % 3:
                recs.append(_rec(d, drain=2.5, assist=2.5))
            else:
                recs.append(_rec(d, drain=5.0))
        m = measured_capacity(recs)
        assert m.samples == 33
        assert m.drift_vs(PACK_KWH) == pytest.approx(0.0, abs=0.001)

    def test_null_fields_read_as_an_old_record(self):
        recs = [_rec(d, drain=5.0) for d in _dates(MIN_SAMPLES)]
        for r in recs:
            r.update(assist_kwh=None, export_kwh=None, charge_kwh=None)
        assert measured_capacity(recs).usable_kwh == pytest.approx(
            PACK_KWH, abs=0.01)


@pytest.mark.unit
class TestARecordSealedBeforeTheChargeWasCounted:
    """Old records carry assist and export but not the charge. Adding the
    first two to a night that also charged reads HIGH (review, 03.10)."""

    def test_a_plain_old_night_reads_as_before(self):
        recs = [_old(d, drain=5.0) for d in _dates(MIN_SAMPLES)]
        assert measured_capacity(recs).usable_kwh == pytest.approx(
            PACK_KWH, abs=0.01)

    def test_an_old_night_with_little_assist_keeps_the_house_share(self):
        recs = [_old(d, drain=5.0, assist=0.3) for d in _dates(MIN_SAMPLES)]
        assert 0.3 <= MAX_UNCOUNTED_SHARE_OLD_RECORD * 5.3
        assert measured_capacity(recs).usable_kwh == pytest.approx(
            PACK_KWH, abs=0.01)

    def test_an_old_night_with_much_assist_is_not_used(self):
        """30 % of what left went to the car: the house share alone is
        known to be low, so the night is not evidence."""
        recs = [_old(d, drain=3.5, assist=1.5) for d in _dates(MIN_SAMPLES)]
        assert 1.5 > MAX_UNCOUNTED_SHARE_OLD_RECORD * 5.0
        assert measured_capacity(recs) is None

    def test_an_old_export_night_that_charged_back_is_not_read_big(self):
        """The reviewer's night: 1 kWh house, 7 kWh sold, 4 kWh charged
        back from the grid, 40 % span. Counting the export without the
        charge says 20 kWh on a 10 kWh pack."""
        recs = [_old(d, soc_start=90.0, soc_morning=50.0, drain=1.0,
                     export=7.0) for d in _dates(MIN_SAMPLES + 2)]
        assert measured_capacity(recs) is None
        assert capacity_progress(recs) == 0

    def test_old_assist_nights_do_not_outvote_new_ones(self):
        old = [_old(f"2026-08-{d:02d}", soc_start=90.0, soc_morning=50.0,
                    drain=1.0, export=7.0) for d in range(1, 10)]
        new = [_rec(d, drain=2.0, assist=3.0) for d in _dates(MIN_SAMPLES)]
        m = measured_capacity(old + new)
        assert m.samples == MIN_SAMPLES
        assert m.usable_kwh == pytest.approx(PACK_KWH, abs=0.01)


@pytest.mark.unit
class TestANightThatAlsoCharged:

    def test_a_small_charge_is_taken_off_the_energy(self):
        """5.5 kWh net left a 10 kWh pack: 6 out, 0.5 back in, 55 % span.
        Gross over net would say 10.9 kWh."""
        assert 0.5 <= MAX_NIGHT_CHARGE_SHARE * 6.0
        recs = [_rec(d, soc_start=90.0, soc_morning=35.0, drain=6.0,
                     charge=0.5) for d in _dates(MIN_SAMPLES)]
        assert 6.0 / 55.0 * 100.0 > PACK_KWH + 0.8      # the old read
        assert measured_capacity(recs).usable_kwh == pytest.approx(
            PACK_KWH, abs=0.01)

    def test_a_night_that_charged_in_earnest_is_not_used(self):
        """6 out, 3 back in: the net is a small difference of two lossy
        conversions, not a size."""
        heavy = [_rec(d, soc_start=90.0, soc_morning=60.0, drain=6.0,
                      charge=3.0) for d in _dates(MIN_SAMPLES + 3)]
        assert measured_capacity(heavy) is None
        assert capacity_progress(heavy) == 0

    def test_the_share_is_of_everything_that_left(self):
        """Assist counts toward the outflow the charge is compared with."""
        recs = [_rec(d, soc_start=90.0, soc_morning=35.0, drain=1.0,
                     assist=5.0, charge=0.5) for d in _dates(MIN_SAMPLES)]
        assert measured_capacity(recs).usable_kwh == pytest.approx(
            PACK_KWH, abs=0.01)

    def test_charge_noise_on_a_short_night_is_subtracted(self):
        """1.5 kWh out over a 15 % span, 0.2 kWh of meter noise back in:
        above 10 % of the outflow, under the noise floor — used."""
        recs = [_rec(d, soc_start=60.0, soc_morning=45.0, drain=1.5,
                     charge=0.2) for d in _dates(MIN_SAMPLES)]
        assert 0.2 > MAX_NIGHT_CHARGE_SHARE * 1.5
        m = measured_capacity(recs)
        assert m is not None
        assert m.kwh_per_pct == pytest.approx(1.3 / 15.0, abs=0.0005)

    def test_noise_larger_than_a_tiny_night_is_not_a_negative_size(self):
        recs = [_rec(d, soc_start=60.0, soc_morning=45.0, drain=0.2,
                     charge=0.24) for d in _dates(MIN_SAMPLES)]
        assert measured_capacity(recs) is None

    def test_heavy_nights_do_not_move_the_clean_ones(self):
        clean = [_rec(d, drain=5.0) for d in _dates(MIN_SAMPLES)]
        heavy = [_rec(f"2026-10-{d:02d}", soc_start=90.0, soc_morning=60.0,
                      drain=6.0, charge=3.0) for d in range(1, 10)]
        m = measured_capacity(clean + heavy)
        assert m.samples == MIN_SAMPLES
        assert m.usable_kwh == pytest.approx(PACK_KWH, abs=0.01)


@pytest.mark.unit
class TestTheOvernightNeedStaysTheHousesShare:
    """The reporter's own caveat: ``drain_kwh`` is right for the need."""

    def test_assist_and_export_do_not_raise_the_need(self):
        recs = [_rec(d, drain=3.0, assist=2.0, export=1.0)
                for d in _dates(MIN_NEED_SAMPLES)]
        assert expected_overnight_need(recs) == pytest.approx(3.0)


def _s(home=0.0, ev=0.0, grid=0.0, charge=0.0, soc=60.0):
    return Sample(battery_to_home_w=home, battery_to_ev_w=ev,
                  battery_to_grid_w=grid, battery_charge_w=charge, soc=soc)


@pytest.mark.unit
class TestTheRecorderWritesTheCharge:

    def test_night_charge_is_integrated(self):
        tr = BatteryNightTracker(reserve_soc=10.0)
        tr.start("2026-09-01", outdoor_temp_c=None)
        t = 0.0
        while t <= 3600.0:
            tr.tick(t, True, _s(home=500.0, charge=2000.0))
            t += 60.0
        tr.tick(t, False, _s())
        rec = tr._record()
        assert rec["charge_kwh"] == pytest.approx(2.0, rel=0.02)
        assert rec["drain_kwh"] == pytest.approx(0.5, rel=0.02)

    def test_a_day_charge_is_not_the_nights(self):
        tr = BatteryNightTracker(reserve_soc=10.0)
        tr.start("2026-09-01", outdoor_temp_c=None)
        tr.tick(0.0, True, _s(home=500.0))
        tr.tick(60.0, True, _s(home=500.0))
        tr.tick(120.0, False, _s())                  # morning
        for k in range(3, 63):
            tr.tick(k * 60.0, False, _s(charge=3000.0))
        assert tr._record()["charge_kwh"] == pytest.approx(0.0)

    def test_the_charge_survives_a_restart_mid_night(self):
        tr = BatteryNightTracker(reserve_soc=10.0)
        tr.start("2026-09-01", outdoor_temp_c=None)
        tr.tick(0.0, True, _s(charge=3600.0))
        tr.tick(60.0, True, _s(charge=3600.0))
        state = tr.to_dict()
        assert isinstance(state["charge_j"], float)
        tr2 = BatteryNightTracker(reserve_soc=10.0)
        tr2.from_dict(state)
        tr2.tick(120.0, True, _s(charge=3600.0))
        tr2.tick(180.0, False, _s())
        assert tr2._record()["charge_kwh"] == pytest.approx(0.12, abs=0.002)

    def test_a_night_restored_from_an_old_store_says_unknown(self):
        """The charge before the restart was never counted: None, not 0."""
        tr = BatteryNightTracker(reserve_soc=10.0)
        tr.start("2026-09-01", outdoor_temp_c=None)
        state = tr.to_dict()
        del state["charge_j"]
        del state["charge_known"]
        tr2 = BatteryNightTracker(reserve_soc=10.0)
        tr2.from_dict(state)
        tr2.tick(0.0, True, _s(charge=3600.0))
        tr2.tick(60.0, True, _s(charge=3600.0))
        assert tr2._record()["charge_kwh"] is None
        tr3 = BatteryNightTracker(reserve_soc=10.0)
        tr3.from_dict(tr2.to_dict())                 # and stays unknown
        assert tr3._record()["charge_kwh"] is None
        tr3.start("2026-09-02", outdoor_temp_c=None)  # the next night counts
        assert tr3._record()["charge_kwh"] == 0.0

    def test_a_hole_that_ends_after_dawn_ends_the_span_with_it(self):
        """4 kWh measured over 40 points, then a restart across dawn while
        the pack lost 10 more. The hole's 1 kWh joins the night, so its
        last SOC must too — else 5 kWh over 40 points says 12.5 kWh."""
        tr = BatteryNightTracker(reserve_soc=10.0, capacity_kwh=PACK_KWH)
        tr.start("2026-09-01", outdoor_temp_c=None)
        t, soc = 0.0, 90.0
        for k in range(81):                          # 4 kWh at 3 kW
            if k:
                t += 60.0
                soc -= 3000.0 * 60.0 / 3.6e6 / PACK_KWH * 100.0
            tr.tick(t, True, _s(home=3000.0, soc=soc))
        assert soc == pytest.approx(50.0)
        tr.tick(t + 2400.0, False, _s(soc=40.0))     # the restart, after dawn
        rec = tr._record()
        assert tr.phase == "day"
        assert rec["drain_kwh"] == pytest.approx(5.0, abs=0.01)
        assert rec["soc_morning"] == pytest.approx(40.0)
        m = measured_capacity([dict(rec, date=d)
                               for d in _dates(MIN_SAMPLES)])
        assert m.usable_kwh == pytest.approx(PACK_KWH, abs=0.05)

    def test_a_charge_hidden_in_a_restart_hole_is_counted(self):
        """6 kWh out, a 40-minute outage while the grid put 25 points back,
        then 0.5 kWh out. The hole's charge must reach the record, or the
        night reads 16 kWh on a 10 kWh pack (review, 03.10)."""
        tr = BatteryNightTracker(reserve_soc=10.0, capacity_kwh=PACK_KWH)
        tr.start("2026-09-01", outdoor_temp_c=None)
        t, soc = 0.0, 90.0
        for k in range(121):                         # 2 h at 3 kW
            if k:
                t += 60.0
                soc -= 3000.0 * 60.0 / 3.6e6 / PACK_KWH * 100.0
            tr.tick(t, True, _s(home=3000.0, soc=soc))
        t += 2400.0                                  # the outage
        soc += 25.0
        tr.tick(t, True, _s(home=0.0, soc=soc))
        for _ in range(10):                          # 0.5 kWh more
            t += 60.0
            soc -= 3000.0 * 60.0 / 3.6e6 / PACK_KWH * 100.0
            tr.tick(t, True, _s(home=3000.0, soc=soc))
        tr.tick(t + 60.0, False, _s(soc=soc))
        rec = tr._record()
        assert rec["trainable"]
        assert rec["charge_kwh"] == pytest.approx(2.5, abs=0.01)
        assert measured_capacity([dict(rec, date=d)
                                  for d in _dates(MIN_SAMPLES)]) is None


@pytest.mark.unit
class TestRecorderToReader:
    """Real nights through the real recorder into the real reader."""

    def _seal_nights(self, tr, n, *, ev_w, charge_w=0.0, charge_s=0.0):
        """Each night: 8 h of 300 W house, 1 h of ``ev_w`` car, optionally
        ``charge_w`` into the pack for ``charge_s`` seconds. SOC follows the
        net energy of a 10 kWh pack, as the BMS would report it."""
        t = 0.0
        for i in range(n):
            tr.start(f"2026-09-{i + 1:02d}", outdoor_temp_c=None)
            soc = 90.0
            step = 60.0
            for k in range(int(8 * 3600 / step) + 1):
                # A tick's flows cover the minute BEFORE it (the recorder
                # integrates backwards), so the SOC moves before the tick.
                ev = ev_w if 0 < k <= 60 else 0.0
                ch = charge_w if 0 < k * step <= charge_s else 0.0
                if k:
                    soc -= ((300.0 + ev - ch) * step / 3.6e6
                            / PACK_KWH * 100.0)
                tr.tick(t, True, _s(home=300.0, ev=ev, charge=ch, soc=soc))
                t += step
            tr.tick(t, False, _s(soc=soc))           # morning
            t += 3600.0
            tr.tick(t, True, _s())                   # next dusk seals it
        return tr.sealed()

    def test_assist_nights_measure_the_real_pack(self):
        tr = BatteryNightTracker(reserve_soc=10.0)
        sealed = self._seal_nights(tr, MIN_SAMPLES, ev_w=3000.0)
        assert len(sealed) == MIN_SAMPLES
        assert all(r["trainable"] for r in sealed)
        assert all(r["assist_kwh"] == pytest.approx(3.0, rel=0.02)
                   for r in sealed)
        house_only = sealed[0]["drain_kwh"] / (
            sealed[0]["soc_start"] - sealed[0]["soc_morning"]) * 100.0
        assert house_only < 0.5 * PACK_KWH           # what it used to say
        m = measured_capacity(sealed)
        assert m is not None
        assert m.usable_kwh == pytest.approx(PACK_KWH, abs=0.01)

    def test_a_small_top_up_still_measures_the_real_pack(self):
        tr = BatteryNightTracker(reserve_soc=10.0)
        # 0.4 kWh in against ~5.4 kWh out: under the share, subtracted.
        sealed = self._seal_nights(tr, MIN_SAMPLES, ev_w=3000.0,
                                   charge_w=2400.0, charge_s=600.0)
        assert len(sealed) == MIN_SAMPLES
        assert sealed[0]["charge_kwh"] == pytest.approx(0.4, rel=0.05)
        m = measured_capacity(sealed)
        assert m.usable_kwh == pytest.approx(PACK_KWH, abs=0.01)


@pytest.mark.unit
class TestCoordinatorHandsTheChargeToTheRecorder:

    def test_the_packs_charge_power_reaches_the_record(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        night = {"v": True}
        h = SimpleNamespace()
        h._record_battery_night = SEMCoordinator._record_battery_night.__get__(h)
        h._outdoor_temp_c = lambda: None
        h.config = {"battery_reserve_soc": 20}
        # (#1063 round 2) a battery home says so: the recorder records
        # only a battery SEM can see
        from custom_components.solar_energy_management.coordinator.install_modules import (
            Module, Presence,
        )
        h.setup_presence = {Module.BATTERY: Presence.PRESENT}
        h.time_manager = SimpleNamespace(is_night_mode=lambda: night["v"],
                                         get_night_window=lambda: ("21", "6"))
        h._cycle_forecast = SimpleNamespace(available=False)
        h._storage = MagicMock()
        h._storage.get_battery_night_state.return_value = {}
        h._storage.async_save_energy_throttled = AsyncMock()

        power = SimpleNamespace(
            battery_soc=85.0, battery_soc_unavailable=False,
            grid_export_power=0.0, battery_power_unavailable=False,
            battery_power=1800.0, battery_charge_power=1800.0)
        flows = SimpleNamespace(battery_to_home=0.0, battery_to_ev=0.0,
                                battery_to_grid=0.0)
        asyncio.run(h._record_battery_night(power, flows))
        tr = h._battery_night
        tr._last_ts -= 60.0                          # one cycle ago
        asyncio.run(h._record_battery_night(power, flows))
        assert tr._charge_j == pytest.approx(1800.0 * 60.0, rel=0.05)

        before = tr._charge_j                        # now discharging
        power.battery_power, power.battery_charge_power = -1800.0, 0.0
        tr._last_ts -= 60.0
        asyncio.run(h._record_battery_night(power, flows))
        assert tr._charge_j == before
