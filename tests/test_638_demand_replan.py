"""#638 — the night re-plans when the ASK changes, and only then.

The issue specified the re-plan triggers as "price update, floor change,
unplug, big deviation"; only unplug shipped. Armed night 1 made the gap
user-visible: the EV target went 3.5 → 6.0 kWh at 22:19, execution followed
the new floor within a cycle (fail-open), and the ledger kept describing a
night that no longer existed.

``_overnight_demand_signature`` folds every demand-shaping input into one
comparable value. These tests pin the two properties that matter:

* a REAL change (target, deadline, mode, a load's deficit appearing, the
  price curve) produces a different signature → the stamp trigger re-plans;
* jitter (a running load's deficit shrinking, sub-cent price noise, cycle
  after identical cycle) produces the SAME signature → one plan per night
  stays one plan per night.
"""
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _power(connected=True, per_charger=None):
    return SimpleNamespace(
        ev_connected=connected,
        ev_connected_per_charger=per_charger,
    )


class _Tariff:
    def __init__(self, prices=()):
        self._prices = [SimpleNamespace(price=p) for p in prices]

    def get_tariff_data(self):
        return SimpleNamespace(upcoming_prices=self._prices)


def _dev(did, deficit_h, has=True):
    return SimpleNamespace(
        device_id=did,
        has_runtime_deficit=has,
        daily_min_runtime_sec=int(deficit_h * 3600) + 3600,
        _daily_runtime_accumulated_sec=3600,
    )


def _coord(chargers=None, devices=(), prices=()):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {"ev_chargers": chargers if chargers is not None else [
        {"id": "keba", "daily_ev_target": 3.5,
         "ev_target_time": "07:00", "charge_mode": "min_plus_solar"},
    ]}
    c._surplus_controller = SimpleNamespace(
        get_devices_sorted=lambda: list(devices))
    c._tariff_provider = _Tariff(prices)
    return c


class TestARealChangeReplans:
    def test_target_change_changes_the_signature(self):
        c = _coord()
        before = c._overnight_demand_signature(_power())
        c.config["ev_chargers"][0]["daily_ev_target"] = 6.0
        assert c._overnight_demand_signature(_power()) != before

    def test_deadline_and_mode_changes_change_the_signature(self):
        c = _coord()
        base = c._overnight_demand_signature(_power())
        c.config["ev_chargers"][0]["ev_target_time"] = "06:00"
        moved = c._overnight_demand_signature(_power())
        assert moved != base
        c.config["ev_chargers"][0]["charge_mode"] = "solar_only"
        assert c._overnight_demand_signature(_power()) != moved

    def test_unplug_still_replans(self):
        c = _coord()
        assert (c._overnight_demand_signature(_power(connected=True))
                != c._overnight_demand_signature(_power(connected=False)))

    def test_a_stop_condition_clearing_changes_the_signature(self):
        """#760: a banked comfort band is a hard stop the collector now
        mirrors — so the stop CLEARING mid-night (the room cooled below
        target−offset) must re-plan, or the demand it re-admits stays
        invisible until an unrelated trigger fires."""
        dev = _dev("heizband", 2.0)
        dev.stop_condition_met = True
        c = _coord(devices=[dev])
        before = c._overnight_demand_signature(_power())
        dev.stop_condition_met = False
        assert c._overnight_demand_signature(_power()) != before

    def test_a_new_load_deficit_changes_the_signature(self):
        quiet = _coord(devices=())
        asking = _coord(devices=(_dev("heizband", 2.0),))
        assert (quiet._overnight_demand_signature(_power())
                != asking._overnight_demand_signature(_power()))

    def test_a_price_update_changes_the_signature(self):
        flat = _coord(prices=(0.36,) * 8)
        published = _coord(prices=(0.36, 0.36, 0.12, 0.12, 0.36, 0.36, 0.36, 0.36))
        assert (flat._overnight_demand_signature(_power())
                != published._overnight_demand_signature(_power()))


class TestJitterDoesNot:
    def test_identical_cycles_are_identical(self):
        c = _coord(devices=(_dev("heizband", 2.0),), prices=(0.36,) * 8)
        assert (c._overnight_demand_signature(_power())
                == c._overnight_demand_signature(_power()))

    def test_a_running_loads_shrinking_deficit_is_not_a_demand_change(self):
        """The deficit shrinks every cycle while a device runs — the 6-minute
        rounding must absorb that, or the night re-plans continuously."""
        c = _coord(devices=(_dev("heizband", 2.0),))
        before = c._overnight_demand_signature(_power())
        # 90 seconds of running: deficit 2.0 h → 1.975 h — same 0.1 h bucket.
        c._surplus_controller.get_devices_sorted()[0]\
            ._daily_runtime_accumulated_sec += 90
        assert c._overnight_demand_signature(_power()) == before

    def test_sub_cent_price_noise_is_not_a_demand_change(self):
        a = _coord(prices=(0.361,) * 8)
        b = _coord(prices=(0.3649,) * 8)
        assert (a._overnight_demand_signature(_power())
                == b._overnight_demand_signature(_power()))

    def test_no_tariff_and_a_broken_provider_are_both_valid_shapes(self):
        c = _coord(prices=())
        sig = c._overnight_demand_signature(_power())
        assert ("price", ()) in sig
        c._tariff_provider = None  # provider gone entirely
        assert ("price", ()) in c._overnight_demand_signature(_power())

    def test_a_broken_device_never_takes_the_signature_down(self):
        bad = SimpleNamespace(device_id="x", has_runtime_deficit=True)
        c = _coord(devices=(bad,))  # missing runtime attrs → skipped
        assert isinstance(c._overnight_demand_signature(_power()), tuple)


def _comfort_ask_dev(did="ac1", kwh=1.5, minute=0):
    from datetime import datetime, timezone
    deadline = datetime(2026, 8, 8, 17, minute, tzinfo=timezone.utc)
    return SimpleNamespace(
        device_id=did, has_runtime_deficit=False,
        comfort_plan_demand=lambda now: {"energy_kwh": kwh,
                                         "deadline": deadline},
    )


class TestComfortAsksReplan:
    """(#638 Phase 3) A band's plannable ask is part of what the day is
    being ASKED for — appearing re-plans; thermometer jitter does not."""

    def test_an_ask_appearing_changes_the_signature(self):
        quiet = _coord()
        asking = _coord(devices=(_comfort_ask_dev(),))
        assert (quiet._overnight_demand_signature(_power())
                != asking._overnight_demand_signature(_power()))

    def test_drift_jitter_rounds_away(self):
        """+0.1 kWh and +10 min stay inside the 0.5 kWh / 30 min steps."""
        a = _coord(devices=(_comfort_ask_dev(kwh=1.5, minute=0),))
        b = _coord(devices=(_comfort_ask_dev(kwh=1.6, minute=10),))
        assert (a._overnight_demand_signature(_power())
                == b._overnight_demand_signature(_power()))

    def test_a_material_change_does_not(self):
        a = _coord(devices=(_comfort_ask_dev(kwh=1.5),))
        b = _coord(devices=(_comfort_ask_dev(kwh=2.5),))
        assert (a._overnight_demand_signature(_power())
                != b._overnight_demand_signature(_power()))


class TestTheSupplySideReplans:
    """(#638, the week picture 2026-08-08) The day's free energy is a
    FORECAST that revises through the morning — Aug 6 was a 34-kWh day a
    dawn stamp would have priced at ~55. The signature watches the DAY
    TOTAL (revised only when the provider re-publishes), never the
    remaining (which burns down every daylight minute and is not an ask
    change)."""

    def _with_forecast(self, today, remaining):
        c = _coord()
        c._forecast_reader = SimpleNamespace(
            forecast_data=SimpleNamespace(
                forecast_today_kwh=today,
                forecast_remaining_today_kwh=remaining))
        return c

    def test_a_provider_revision_replans(self):
        sunny = self._with_forecast(55.0, 40.0)
        clouded = self._with_forecast(34.0, 20.0)
        assert (sunny._overnight_demand_signature(_power())
                != clouded._overnight_demand_signature(_power()))

    def test_the_burn_down_is_not_an_ask_change(self):
        morning = self._with_forecast(55.0, 50.0)
        noon = self._with_forecast(55.0, 20.0)
        assert (morning._overnight_demand_signature(_power())
                == noon._overnight_demand_signature(_power()))

    def test_sub_step_revisions_round_away(self):
        a = self._with_forecast(55.0, 40.0)
        b = self._with_forecast(55.9, 40.0)
        assert (a._overnight_demand_signature(_power())
                == b._overnight_demand_signature(_power()))

    def test_no_forecast_is_a_valid_shape(self):
        c = _coord()
        assert isinstance(c._overnight_demand_signature(_power()), tuple)

    def test_the_n1_bucket_edge_oscillation_is_one_night(self):
        """(#759) Quantizing cannot damp a value that LIVES at a bucket
        edge. N1 (.175, 13.08): the dampened forecast wobbled 66.9↔67.1
        around the 67 boundary, the 2-kWh rounding turned that into
        66↔68, and each flip was a full replan — four restamps in 110 s,
        coverage changing hands every 20 s. Same coordinator, same night,
        sub-hysteresis jitter: ONE signature."""
        c = self._with_forecast(66.9, 40.0)
        first = c._overnight_demand_signature(_power())
        for raw in (67.1, 66.9, 67.3, 66.8, 67.1):
            c._forecast_reader.forecast_data.forecast_today_kwh = raw
            assert c._overnight_demand_signature(_power()) == first, (
                f"forecast jitter to {raw} kWh re-planned the night"
            )

    def test_a_real_revision_on_the_same_coordinator_still_replans(self):
        """The hysteresis must not eat the week picture: a genuine
        provider revision (clouds rolling in) re-plans."""
        c = self._with_forecast(66.9, 40.0)
        first = c._overnight_demand_signature(_power())
        c._forecast_reader.forecast_data.forecast_today_kwh = 60.0
        assert c._overnight_demand_signature(_power()) != first

    def test_a_transient_forecast_outage_keeps_the_anchor(self):
        """A one-cycle unreadable forecast used to flip the term to 0.0
        and back — two replans for one hiccup. Degrade to the last
        anchored value, not to a different night."""
        c = self._with_forecast(66.9, 40.0)
        first = c._overnight_demand_signature(_power())

        class _Boom:
            @property
            def forecast_data(self):
                raise RuntimeError("reader down")
        c._forecast_reader = _Boom()
        assert c._overnight_demand_signature(_power()) == first
