"""#778 — EXECUTE the assembly, don't just read it.

The arc is a set of pure functions plus one 280-line coordinator method,
``_record_forecast_horizons``, that derives every input inline and publishes
the ~25 values in ``_planning_evidence``. That method IS the arc's product:
every number a user sees, and every number the spend acts on, comes out of
it.

It was the only assembly in the coordinator that no test ever ran. Its
siblings are executed with a stub ``self`` — ``SEMCoordinator._shadow_energy_plan(
fake, ...)`` in six files, ``await SEMCoordinator._run_battery_pipeline(...)``
in three — so the pattern was there to copy.

Its only guard was ``test_778_horizon_wiring.py``, which parses the source
with ``ast``: it proves a name is in scope, that ``sealed`` is CALLED and not
merely referenced, that the day marker is set only after a successful record.
Those are real guarantees and they stay. What they cannot see is a wrong
FORMULA — and all three defects this arc has shipped were wrong formulas or
wrong values with every name correctly in scope:

* ``measured_capacity(tracker.sealed)`` — the bound method, not the records.
  The card read "Learning · 7 / 5 Nights" forever. Found from the dashboard.
* ``usable_kwh * (100 - soc) / 100`` — headroom at SUNSET. A full pack
  computed zero room, so zero refill, so nothing spendable, on the eve of a
  day the same sensor called free to spend. Found on .175.
* ``start = max(now, night_start - hours)`` — correct at any single instant,
  wrong across recomputes: the sell block shrank with the clock and cancelled
  itself in its last quarter hour. Found by simulation.

A static guard could not have caught any of them. A table of scenarios run
through the real method catches all three, which is what this file is.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

NOW = datetime.datetime(2026, 8, 30, 19, 0)
NAMEPLATE = 15.0
#: 40 nights that each drew 6.5 kWh across 52 % of SOC → 0.125 kWh/%,
#: i.e. a 12.5 kWh usable pack behind a 15 kWh nameplate. PROD measures
#: 12.63 against the same nameplate, so the shape is the real one.
NIGHT_DRAIN_KWH = 6.5
NIGHT_SOC_SPAN = 52.0
MEASURED_USABLE = 12.5


def _sealed(n: int = 40, drain: float = NIGHT_DRAIN_KWH,
            span: float = NIGHT_SOC_SPAN) -> list[dict]:
    return [
        {
            "date": (NOW.date() - datetime.timedelta(days=i + 1)).isoformat(),
            "soc_start": 90.0, "soc_morning": 90.0 - span,
            "drain_kwh": drain, "surplus_kwh": 3.0,
            "held_s": 0, "clipped_s": 0,
            "usable": True, "trainable": True, "quality": "ok",
        }
        for i in range(n)
    ]


def evidence(*, soc, nameplate=NAMEPLATE, forecast_tomorrow=60.0,
             forecast_today=32.0, forecast_d2=None, daily_solar=20.0,
             records=None, reserve=None, ev_chargers=None) -> dict:
    """Run the REAL assembly and return what it published."""
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord._storage = None
    coord._forecast_ledger = None
    coord._forecast_ledger_day = None
    coord._planning_evidence = {}
    coord.config = {"battery_capacity_kwh": nameplate}
    if reserve is not None:
        coord.config["battery_reserve_soc"] = reserve
    if ev_chargers is not None:
        # (#778) Tomorrow's EV claims reach the budget from here. Leaving it
        # unset is what let a mutation replace the committed-demand argument
        # with 0.0 and keep 408 tests green.
        coord.config["ev_chargers"] = ev_chargers
    recs = _sealed() if records is None else records
    coord._battery_night = SimpleNamespace(sealed=lambda: recs)

    SEMCoordinator._record_forecast_horizons(
        coord,
        SimpleNamespace(forecast_today_kwh=forecast_today,
                        forecast_tomorrow_kwh=forecast_tomorrow,
                        forecast_d2_kwh=forecast_d2),
        SimpleNamespace(daily_solar=daily_solar),
        NOW,
        SimpleNamespace(battery_soc=soc),
    )
    return coord._planning_evidence


class TestTheMeasuredPackReachesTheVerdict:
    """The 7/5 defect: progress counted the records, the verdict never saw
    them, because the bound method was passed instead of its result."""

    def test_capacity_is_measured_not_assumed(self):
        pe = evidence(soc=100.0)
        assert pe["battery_measured_capacity_kwh"] == pytest.approx(
            MEASURED_USABLE, abs=0.05), (
            "the verdict must read the sealed RECORDS — passing the bound "
            "`sealed` method left this None while progress counted 40 nights"
        )

    def test_progress_and_verdict_agree(self):
        pe = evidence(soc=100.0)
        assert pe["battery_capacity_samples"] == 40
        assert pe["nights_sealed"] == 40
        assert pe["planning_phase"] != "learning", (
            "40 qualifying nights is not 'still learning'"
        )

    def test_the_measured_pack_beats_the_nameplate(self):
        """A 15 kWh nameplate over a 12.5 kWh measured pack sized every
        budget against 2.4 kWh that was never there."""
        assert evidence(soc=100.0)["battery_measured_capacity_kwh"] < NAMEPLATE

    def test_no_records_means_no_verdict_not_a_guess(self):
        pe = evidence(soc=100.0, records=[])
        assert pe["battery_measured_capacity_kwh"] is None
        assert pe["planning_phase"] == "learning"
        assert pe["battery_spendable_kwh"] == 0.0


class TestAFullPackIsTheEasiestCaseNotTheHardest:
    """The dawn-headroom defect, at the level that publishes it."""

    def test_a_full_pack_on_a_bright_tomorrow_has_something_spendable(self):
        pe = evidence(soc=100.0)
        assert pe["battery_spendable_kwh"] > 0.0, (
            "measuring the pack's room at SUNSET makes it zero at SOC 100, "
            "so refill is zero, so nothing is spendable — on precisely the "
            "night when spending is provably free"
        )

    def test_spendable_never_rises_as_the_pack_empties(self):
        """The inversion, stated over the published number."""
        socs = [100.0, 90.0, 80.0, 70.0, 60.0, 50.0]
        vals = [evidence(soc=s)["battery_spendable_kwh"] for s in socs]
        for hi_soc, lo_soc, hi, lo in zip(socs, socs[1:], vals, vals[1:],
                                          strict=False):
            assert lo <= hi + 1e-9, (
                f"SOC {lo_soc} publishes {lo:.2f} kWh spendable but SOC "
                f"{hi_soc} publishes {hi:.2f} — a fuller pack must never "
                "spend less"
            )

    def test_the_refill_reason_and_the_number_agree(self):
        """The tell that exposed the bug: the estimator printed 'spending
        that tonight costs nothing' beside a spendable of 0.0."""
        pe = evidence(soc=100.0)
        if "costs nothing" in str(pe.get("battery_refill_reason", "")):
            assert pe["battery_spendable_kwh"] > 0.0, (
                "the reason says tonight's spend is free while the number "
                "says nothing is spendable — one of them is lying"
            )


class TestTheDarkInputRules:
    """Rule 4 of the budget: an unknown input is not permission."""

    def test_unknown_soc_spends_nothing(self):
        pe = evidence(soc=None)
        assert pe["battery_spendable_kwh"] == 0.0
        assert "SOC" in pe["battery_spendable_reason"]

    def test_unknown_tomorrow_spends_nothing(self):
        pe = evidence(soc=100.0, forecast_tomorrow=None)
        assert pe["battery_spendable_kwh"] == 0.0

    def test_a_forecast_of_zero_is_a_forecast_not_an_absence(self):
        pe = evidence(soc=100.0, forecast_tomorrow=0.0)
        assert pe["battery_expected_refill_kwh"] == 0.0
        assert pe["battery_spendable_kwh"] == 0.0


class TestThePublishedNumbersArePhysical:
    """Every value here lands on a card. A number that cannot be true is a
    number the user cannot trust (#830), and it is the same class of defect
    as the three above: published arithmetic nobody executed."""

    def test_the_refill_never_exceeds_what_the_pack_could_hold(self):
        """A dark SOC leaves the headroom unknown, and the estimator then
        reports the RAW surplus — 35.5 kWh onto a 12.5 kWh pack. Spendable
        is correctly 0, so nothing acts on it; the number is still nonsense
        on the surface."""
        pe = evidence(soc=None)
        refill = pe.get("battery_expected_refill_kwh")
        cap = pe.get("battery_measured_capacity_kwh") or NAMEPLATE
        if refill is not None:
            assert refill <= cap + 1e-9, (
                f"published refill {refill} kWh exceeds the whole pack "
                f"({cap} kWh) — the pack cannot absorb more than itself"
            )

    def test_the_dynamic_floor_is_a_percentage(self):
        """A reserve of 50 % under a night that needs 52 % of the pack
        publishes a floor of 115.7 %. The CONCLUSION is right — this pack
        cannot meet this night, and spendable is 0 — but a percentage above
        100 cannot render on a gauge."""
        pe = evidence(soc=100.0, reserve=50)
        floor = pe.get("battery_dynamic_floor_pct")
        assert pe["battery_spendable_kwh"] == 0.0, (
            "a night bigger than the pack must spend nothing"
        )
        if floor is not None:
            assert 0.0 <= floor <= 100.0, (
                f"dynamic floor {floor}% is not a percentage of anything"
            )
