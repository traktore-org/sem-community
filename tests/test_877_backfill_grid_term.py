"""#877 — a reconstructed night must carry the grid term, or it undoes #874.

#874 taught ``expected_overnight_need`` that a night the grid finished is
censored downward: ``drain_kwh`` is the battery's share alone, so the need is
``drain + night_grid``. On PROD that moved the estimate 5.11 -> 6.28 kWh, with
eleven of thirteen nights censored.

Backfilled records emit no grid term, so once #876 lets the backfill run on a
long-lived install, a year of censored nights would dilute the correct ones
and quietly restore the old under-read.

The naive fix — add the grid-import delta — is worse than nothing: the live
field is HOME-directed with the EV excluded, so a raw import delta books the
car's charging as house need. A 20 kWh charge would dominate the percentile
for as long as the record lives.

What is reconstructable is the balance. At night there is no solar, so

    G + D = H + E + C        =>       H = G + D - E - C

and ``H`` is precisely ``drain + night_grid``. Emitting
``night_grid_kwh = max(0, H - drain)`` makes the pair reproduce ``max(D, H)``
— an upper bound, which is the direction this module already chooses on
purpose for ``drain_kwh``.
"""
from __future__ import annotations

import datetime

from custom_components.solar_energy_management.coordinator.night_backfill import (
    nights_from_statistics,
)


def _series(day: datetime.date, hour_values, *, next_day=False):
    """{datetime: value} on the hour."""
    out = {}
    for h, v in hour_values:
        d = day + datetime.timedelta(days=1) if (next_day and h < 12) else day
        out[datetime.datetime.combine(d, datetime.time(hour=h))] = v
    return out


DAY = datetime.date(2026, 8, 20)


def _counters(*, g_start, g_end, e_start=0.0, e_end=0.0, c_start=0.0, c_end=0.0):
    def pair(a, b):
        s = _series(DAY, [(21, a)])
        s.update(_series(DAY, [(6, b)], next_day=True))
        return s
    return {
        "grid_import": pair(g_start, g_end),
        "ev_energy": pair(e_start, e_end),
        "battery_charge": pair(c_start, c_end),
    }


def _discharge(start, end):
    s = _series(DAY, [(21, start)])
    s.update(_series(DAY, [(6, end)], next_day=True))
    return s


def _run(discharge, counters, **kw):
    return nights_from_statistics(
        discharge, None,
        night_start_hour=21, night_end_hour=6,
        counters=counters, **kw,
    )


class TestTheBalanceCloses:
    def test_a_quiet_night_books_the_grids_share(self):
        """Battery gave 4.0, grid gave 1.5, no car, no charging.
        House took 5.5, so the grid term is 1.5."""
        recs = _run(_discharge(100.0, 104.0),
                    _counters(g_start=200.0, g_end=201.5))
        assert len(recs) == 1
        r = recs[0]
        assert r["drain_kwh"] == 4.0
        assert r["night_grid_kwh"] == 1.5, (
            "a reconstructed night still reports only the battery's share — "
            "the p85 is dragged down by exactly the nights that needed most"
        )
        assert r["drain_kwh"] + r["night_grid_kwh"] == 5.5

    def test_the_car_is_not_counted_as_house_need(self):
        """The whole reason a raw import delta is wrong: the same night with
        20 kWh of car charging must report the same 5.5 kWh house need."""
        recs = _run(_discharge(100.0, 104.0),
                    _counters(g_start=200.0, g_end=221.5,   # +21.5 imported
                              e_start=50.0, e_end=70.0))    # 20.0 to the car
        r = recs[0]
        assert r["drain_kwh"] + r["night_grid_kwh"] == 5.5, (
            f"booked the car's charge as house need "
            f"(got {r['drain_kwh'] + r['night_grid_kwh']})"
        )

    def test_battery_charged_from_grid_is_not_house_need(self):
        recs = _run(_discharge(100.0, 104.0),
                    _counters(g_start=200.0, g_end=204.5,   # +4.5
                              c_start=10.0, c_end=13.0))    # 3.0 into the pack
        r = recs[0]
        assert r["drain_kwh"] + r["night_grid_kwh"] == 5.5

    def test_the_pair_is_never_below_the_measured_drain(self):
        """The counter's total discharge carries EV assist and export, so it
        can exceed the house's share. The module chooses the UPPER bound on
        purpose — a larger need means a larger reserve and less spending."""
        recs = _run(_discharge(100.0, 106.0),          # 6.0 total discharge
                    _counters(g_start=200.0, g_end=200.0,
                              e_start=0.0, e_end=2.0))  # 2.0 went to the car
        r = recs[0]
        assert r["night_grid_kwh"] == 0.0
        assert r["drain_kwh"] + r["night_grid_kwh"] == 6.0


class TestReconstructableOrAbsent:
    def test_no_counters_means_no_grid_term(self):
        """Never guessed. A record without the evidence says nothing."""
        recs = nights_from_statistics(
            _discharge(100.0, 104.0), None,
            night_start_hour=21, night_end_hour=6)
        assert recs and "night_grid_kwh" not in recs[0]

    def test_a_missing_counter_means_no_grid_term(self):
        c = _counters(g_start=200.0, g_end=201.5)
        c.pop("battery_charge")
        recs = _run(_discharge(100.0, 104.0), c)
        assert "night_grid_kwh" not in recs[0]

    def test_an_install_with_no_ev_contributes_zero_not_unknown(self):
        c = _counters(g_start=200.0, g_end=201.5)
        c.pop("ev_energy")
        recs = _run(_discharge(100.0, 104.0), c, has_ev=False)
        assert recs[0]["night_grid_kwh"] == 1.5, (
            "an install with no car has E=0 by construction — treating it as "
            "unknown throws away a term we know exactly"
        )

    def test_a_counter_that_went_backwards_voids_the_term(self):
        """A reset makes the delta a plausible-looking fiction — the same
        reason _decreased_within already refuses a drain."""
        c = _counters(g_start=200.0, g_end=201.5)
        mid = datetime.datetime.combine(DAY, datetime.time(hour=23))
        c["grid_import"][mid] = 0.0          # meter replaced overnight
        recs = _run(_discharge(100.0, 104.0), c)
        assert "night_grid_kwh" not in recs[0]

    def test_the_drain_itself_is_unchanged_by_all_this(self):
        """The grid term is additive evidence; it must not move the number
        the capacity reader and distinct_nights already rank on."""
        plain = nights_from_statistics(
            _discharge(100.0, 104.0), None,
            night_start_hour=21, night_end_hour=6)[0]
        withc = _run(_discharge(100.0, 104.0),
                     _counters(g_start=200.0, g_end=201.5))[0]
        assert plain["drain_kwh"] == withc["drain_kwh"]
        assert plain["trainable"] == withc["trainable"]
        assert withc["source"] == "backfill"


class TestTheNoEvCaseIsReachable:
    """The `has_ev=False` branch must be reachable on the installs #877
    exists for, or it is decoration.

    #876 migrates the five COUNTER keys and deliberately not the dashboard's
    ``has_*`` flags — those are live steering inputs the coordinator resolves
    itself. So on a migrated install ``config.get("has_ev")`` is ABSENT, and
    a default of True turns "this house has no car" into "the EV leg is
    unknown", which costs the grid term on every reconstructed night. The
    branch would then only ever fire on installs created after the flags were
    written — the ones that never needed the backfill.

    SEM already has a canonical test for this, at __init__.py:314:

        has_ev = bool(config.get("ev_chargers")
                      or config.get("ev_charging_power_sensor"))

    It reads what the USER configured rather than what a dashboard reader
    happened to record, so it answers correctly on a migrated entry. One
    question, one test, everywhere.
    """

    def _run_service_shaped(self, config):
        """Mirror run_backfill's own resolution without a recorder."""
        from custom_components.solar_energy_management.coordinator import (
            night_backfill as nb,
        )
        import inspect
        src = inspect.getsource(nb.run_backfill)
        return src

    def test_the_ev_test_does_not_rest_on_a_flag_migration_omits(self):
        src = self._run_service_shaped({})
        assert 'config.get("has_ev"' not in src, (
            "has_ev is not carried by the #876 migration, so on exactly the "
            "old installs this feature is for it is absent and defaults to "
            "True — the no-EV branch never fires and every reconstructed "
            "night loses its grid term"
        )
        assert 'ev_chargers' in src and 'ev_charging_power_sensor' in src, (
            "use SEM's canonical has-EV test (__init__.py:314) — what the "
            "user configured, not what a dashboard reader recorded"
        )
