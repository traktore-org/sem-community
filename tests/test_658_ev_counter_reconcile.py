"""#658 — daily EV energy follows the wallbox counters.

SEM integrates the charger's power sensor every cycle. Energy charged while
SEM is NOT integrating — an HA restart, a core update, a power blip, a session
started from the charger's own app while HA is asleep — is never seen. The
wallbox counted all of it; the user compares the two numbers and files a
report.

The reconciliation was written years ago, then parked with six skipped tests
and this comment in ``coordinator.py``:

    EV energy reconciliation disabled — keba_p30_charging_daily resets at
    midnight but daily_ev resets at sunrise […] SEM's own power integration
    (10s cycles) is reliable enough.

The first half was correct: the counter and the bucket do not share a day
boundary, so comparing their ABSOLUTE values compares two different windows,
and at the deadline rollover it would credit a whole night's charging to a
freshly-reset day. The second half is only true while SEM is running, which is
precisely the case this does not cover.

#658 rebuilds it on counter DELTAS, the same model
``_reconcile_solar_energy`` has used since #556. A delta is boundary-agnostic:
a counter reset is just a reset. The tests below pin both halves — that the
recovery works, and that the boundary case which parked it stays fixed.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from freezegun import freeze_time

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EV_CATEGORY,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.utils.time_manager import TimeManager

COUNTER = "sensor.wallbox_total_energy"
COUNTER_B = "sensor.wallbox_b_total_energy"


def _hass(values: dict) -> Mock:
    """Mock hass whose states track ``values`` LIVE, so a test can move a
    counter between cycles the way real hardware does."""
    hass = Mock()
    hass.data = {}
    hass.config = Mock()
    hass.config.config_dir = "/config"

    def _get(entity_id):
        if entity_id not in values:
            return None
        state = Mock()
        state.state = str(values[entity_id])
        state.attributes = {"unit_of_measurement": "kWh"}
        return state

    hass.states.get = _get
    return hass


def _calc(hass, **config) -> EnergyCalculator:
    cfg = {"update_interval": 10}
    cfg.update(config)
    return EnergyCalculator(cfg, TimeManager(hass))


def _idle_cycle(calc: EnergyCalculator) -> float:
    """One cycle with no EV power — integration contributes nothing, so
    whatever ``daily_ev`` comes back is what reconciliation put there.

    ``_last_update`` is cleared first so the cycle always uses the configured
    interval. These tests compress hours into consecutive statements, and a
    >120 s apparent gap makes ``calculate_energy`` skip the whole cycle
    (accumulator-spike guard) — which would silently skip the reconciliation
    under test. Nothing is weakened: with ``ev_power = 0`` the interval
    contributes no integration either way.
    """
    calc._last_update = None
    power = PowerReadings(ev_power=0.0)
    power.calculate_derived()
    return calc.calculate_energy(power).daily_ev


@pytest.mark.unit
@freeze_time("2026-07-15 12:00:00")
class TestCounterRecovery658:
    def test_the_reconcile_can_actually_fire(self):
        """Bug class 8 at birth: every assertion here would pass vacuously if
        reconciliation never ran, so first prove the switch has two positions.
        The OFF position is not hypothetical — it is what shipped for years."""
        values = {COUNTER: 0.0}
        off = _calc(_hass(values))
        off.configure_ev_counters(_hass(values), [COUNTER], False)
        _idle_cycle(off)
        values[COUNTER] = 9.0
        assert _idle_cycle(off) == 0.0, "disabled reconciliation adopted anyway"

        values[COUNTER] = 0.0
        on = _calc(_hass(values))
        on.configure_ev_counters(_hass(values), [COUNTER], True)
        _idle_cycle(on)
        values[COUNTER] = 9.0
        assert _idle_cycle(on) == 9.0, "enabled reconciliation adopted nothing"

    def test_energy_charged_while_sem_was_down_is_recovered(self):
        """THE issue. SEM integrates 4 kWh, dies, the car keeps charging, the
        counter climbs to 11. On restart the store carries the baselines, so
        the 7 kWh gap is an ADVANCE and not a fresh baseline."""
        values = {COUNTER: 4.0}
        before = _calc(_hass(values))
        before.configure_ev_counters(_hass(values), [COUNTER], True)
        day = before._ev_reset_day(None)
        before._daily_accumulators[f"{EV_CATEGORY}_{day}"] = 4.0
        _idle_cycle(before)  # baseline at 4.0, anchor at 4.0
        saved = before.get_state()

        values[COUNTER] = 11.0  # two hours of charging with SEM off
        after = _calc(_hass(values))
        after.configure_ev_counters(_hass(values), [COUNTER], True)
        after.restore_state(saved)

        assert _idle_cycle(after) == 11.0

    def test_dropping_the_baselines_loses_exactly_that_energy(self):
        """The counter-proof for the persistence above: without the restored
        baselines the same restart re-baselines at 11.0 and the downtime
        energy is gone. This is why ``ev_counter_baselines`` is in
        ``get_state``, and what breaks if someone removes it."""
        values = {COUNTER: 11.0}
        after = _calc(_hass(values))
        after.configure_ev_counters(_hass(values), [COUNTER], True)
        day = after._ev_reset_day(None)
        after._daily_accumulators[f"{EV_CATEGORY}_{day}"] = 4.0

        assert _idle_cycle(after) == 4.0

    def test_baselines_round_trip_through_the_store(self):
        values = {COUNTER: 4.0}
        calc = _calc(_hass(values))
        calc.configure_ev_counters(_hass(values), [COUNTER], True)
        _idle_cycle(calc)

        baselines = calc.get_state()["ev_counter_baselines"]
        assert baselines["base"][COUNTER] == 4.0

        fresh = _calc(_hass(values))
        fresh.restore_state({"ev_counter_baselines": baselines})
        assert fresh._ev_counter_baselines["base"][COUNTER] == 4.0

    def test_the_fleet_bucket_sums_every_charger_counter(self):
        """``ev`` is the FLEET daily total. One charger's counter alone would
        be adopted as if it were the whole fleet — bug class 3, the read not
        matching the scope of what it is read into."""
        values = {COUNTER: 0.0, COUNTER_B: 0.0}
        calc = _calc(_hass(values))
        calc.configure_ev_counters(_hass(values), [COUNTER, COUNTER_B], True)
        _idle_cycle(calc)

        values[COUNTER] = 6.0
        values[COUNTER_B] = 4.0
        assert _idle_cycle(calc) == 10.0

    def test_a_partial_counter_set_never_shrinks_the_day(self):
        """Charger B has no counter configured, but its energy IS in the
        fleet integration. Adoption is upward-only, so B's kWh survive — they
        just can't be recovered across downtime."""
        values = {COUNTER: 0.0}
        calc = _calc(_hass(values))
        calc.configure_ev_counters(_hass(values), [COUNTER], True)
        day = calc._ev_reset_day(None)
        calc._daily_accumulators[f"{EV_CATEGORY}_{day}"] = 12.0  # A + B integrated
        _idle_cycle(calc)

        values[COUNTER] = 3.0  # only A's counter moves
        assert _idle_cycle(calc) >= 12.0

    def test_an_unavailable_counter_is_not_a_zero(self):
        values = {COUNTER: 0.0}
        calc = _calc(_hass(values))
        calc.configure_ev_counters(_hass(values), [COUNTER], True)
        day = calc._ev_reset_day(None)
        calc._daily_accumulators[f"{EV_CATEGORY}_{day}"] = 8.0
        _idle_cycle(calc)

        values[COUNTER] = "unavailable"
        assert _idle_cycle(calc) == 8.0

    def test_a_unit_error_is_rejected_rather_than_adopted(self):
        """A Wh counter mislabelled as kWh is 1000× out — 9 kWh arrives as
        9000, which would hand the user a year's charging in one cycle."""
        values = {COUNTER: 0.0}
        calc = _calc(_hass(values), ev_max_current=32, ev_phases=3, ev_voltage=230)
        calc.configure_ev_counters(_hass(values), [COUNTER], True)
        _idle_cycle(calc)

        values[COUNTER] = 9_000.0  # 9 kWh reported in Wh
        assert _idle_cycle(calc) == 0.0

    def test_the_ceiling_does_not_clip_a_real_flat_out_day(self):
        """It is a unit-error trap, not a policy limit. Two 22 kW chargers
        running all day is ~1 MWh of headroom; a plausible heavy day must
        pass, or the guard would quietly disable itself on big installs."""
        values = {COUNTER: 0.0, COUNTER_B: 0.0}
        calc = _calc(
            _hass(values),
            ev_max_current=32, ev_phases=3, ev_voltage=230,
            ev_chargers=[{"id": "a"}, {"id": "b"}],
        )
        calc.configure_ev_counters(_hass(values), [COUNTER, COUNTER_B], True)
        _idle_cycle(calc)

        values[COUNTER] = 180.0
        values[COUNTER_B] = 180.0
        assert _idle_cycle(calc) == 360.0


@pytest.mark.unit
class TestBoundaryMismatch658:
    """The reason this was parked. Both cases below are the ones an ABSOLUTE
    counter-vs-bucket comparison gets wrong."""

    def test_the_deadline_rollover_does_not_inherit_the_counter(self):
        """A night's charging sits in a midnight-based counter; the EV day
        rolls at the 07:00 deadline. The parked implementation would have
        adopted the counter's full overnight value into the fresh day —
        "making SEM think the target is already reached". Under deltas the new
        day re-baselines and starts where it should: at zero."""
        values = {COUNTER: 0.0}
        with freeze_time("2026-07-15 23:00:00") as clock:
            calc = _calc(_hass(values), ev_target_time="07:00")
            calc.configure_ev_counters(_hass(values), [COUNTER], True)
            _idle_cycle(calc)

            clock.move_to("2026-07-16 02:00:00")
            values[COUNTER] = 20.0  # charged overnight, same EV day
            assert _idle_cycle(calc) == 20.0
            night_day = calc._ev_reset_day(None)

            clock.move_to("2026-07-16 08:00:00")  # past the deadline
            new_day = calc._ev_reset_day(None)
            assert new_day != night_day, "EV day did not roll — test is vacuous"
            assert _idle_cycle(calc) == 0.0

    def test_a_midnight_counter_reset_is_not_negative_energy(self):
        """A daily-resetting counter drops to 0 at midnight. Treated as a
        delta that would be −20 kWh; treated as what it is, the baseline
        simply restarts and the day keeps every kWh it earned."""
        values = {COUNTER: 0.0}
        with freeze_time("2026-07-15 22:00:00") as clock:
            calc = _calc(_hass(values), ev_target_time="07:00")
            calc.configure_ev_counters(_hass(values), [COUNTER], True)
            _idle_cycle(calc)
            values[COUNTER] = 20.0
            assert _idle_cycle(calc) == 20.0

            clock.move_to("2026-07-16 00:05:00")
            values[COUNTER] = 0.0  # the charger's own midnight reset
            assert _idle_cycle(calc) == 20.0

            values[COUNTER] = 5.0  # charging continues past midnight
            assert _idle_cycle(calc) == 25.0


@pytest.mark.unit
class TestStorageRoundTrip658:
    """``EnergyCalculator.get_state()`` emits; ``SEMStorage`` re-lists.

    The storage layer does not persist what the calculator returns — it copies
    a hand-maintained set of keys in ``import_energy_calculator_state`` and
    hands back a hand-maintained set in ``export_energy_calculator_state``. A
    key the calculator emits but storage forgets is dropped in silence: the
    calculator's ``state.get(key, default)`` on the way back in is
    indistinguishable from a fresh install. #351 M1 already paid for this once
    (the cost accumulators reset ``daily_savings`` to 0 mid-day after every
    restart), and #658's baselines would have been the next: they round-trip
    perfectly through the calculator and vanish through the store, taking the
    downtime recovery with them.

    So this is a ratchet, not a list: every key ``get_state()`` emits must
    survive the store, unless it is named below as knowingly dropped.
    """

    # Knowingly dropped — see #668. These are LIFETIME running totals summed
    # at each day rollover, and the store persists none of them, so they
    # restart at 0.0 on every HA restart. It does not show as a zero: the
    # lifetime-savings maths substitutes an average-rate ESTIMATE for the
    # missing rate-weighted real figure, which is why nobody has reported it.
    # Shrink-only: fixing one means deleting it from here, never adding.
    KNOWN_DROPPED = {
        "accumulated_savings",
        "accumulated_battery_savings",
        "accumulated_cost",
        "accumulated_export_revenue",
        "accumulated_grid_import_kwh",
        "accumulated_self_consumed_kwh",
        "accumulated_export_kwh",
        "rate_history",
        "yearly_cost_seeded",
    }

    @staticmethod
    def _storage_keys():
        from custom_components.solar_energy_management.coordinator import storage
        source = SimpleNamespace(
            _daily_data={}, _energy_data={},
        )
        exported = storage.SEMStorage.export_energy_calculator_state(source)
        return set(exported)

    def test_every_emitted_key_survives_the_store(self):
        emitted = set(_calc(_hass({})).get_state())
        dropped = emitted - self._storage_keys() - self.KNOWN_DROPPED
        assert not dropped, (
            f"{sorted(dropped)} are written by EnergyCalculator.get_state() but "
            "not carried by SEMStorage.export_energy_calculator_state() — they "
            "will read back as their default after every restart, with no error "
            "and no log line. Add them to the store (both directions), or to "
            "KNOWN_DROPPED with an issue number if the loss is deliberate."
        )

    def test_the_ev_baselines_specifically_survive(self):
        assert "ev_counter_baselines" in self._storage_keys()

    def test_the_import_side_carries_them_too(self):
        """Export and import are separate hand-maintained lists — a key can be
        exported and never imported, which reads as a permanently empty value."""
        from custom_components.solar_energy_management.coordinator import storage
        sink = SimpleNamespace(_daily_data={}, _energy_data={})
        storage.SEMStorage.import_energy_calculator_state(
            sink, {"ev_counter_baselines": {"date": "2026-07-15"}},
        )
        assert sink._daily_data["ev_counter_baselines"] == {"date": "2026-07-15"}

    def test_the_drop_list_only_shrinks(self):
        """Anti-rot: if a listed key starts round-tripping, delete it from
        KNOWN_DROPPED rather than leaving a stale exemption behind."""
        still_dropped = self.KNOWN_DROPPED & self._storage_keys()
        assert not still_dropped, (
            f"{sorted(still_dropped)} now survive the store — remove them from "
            "KNOWN_DROPPED."
        )


@pytest.mark.unit
class TestCounterCollection658:
    """``_collect_ev_counter_entities`` — which entities the fleet is made of.

    (That the coordinator CALLS ``configure_ev_counters`` at all is guarded by
    ``test_653_orphan_methods``: the method's predecessor sat in that
    allowlist as confirmed-dead precisely because nothing called it.)
    """

    @staticmethod
    def _collect(config, ed=None):
        return SEMCoordinator._collect_ev_counter_entities(
            SimpleNamespace(config=config, _energy_dashboard_config=ed)
        )

    def test_every_charger_contributes_its_own_counter(self):
        assert self._collect({"ev_chargers": [
            {"id": "a", "ev_total_energy_sensor": COUNTER},
            {"id": "b", "ev_total_energy_sensor": COUNTER_B},
        ]}) == [COUNTER, COUNTER_B]

    def test_the_top_level_counter_belongs_to_the_primary_only(self):
        """#639's convention: a legacy config carries one top-level counter,
        auto-filled from the primary charger. Lending it to a sibling is the
        cross-contamination that fix removed."""
        assert self._collect({
            "ev_total_energy_sensor": COUNTER,
            "ev_chargers": [{"id": "a"}, {"id": "b"}],
        }) == [COUNTER]

    def test_id_less_legacy_entries_do_not_all_claim_the_primary_counter(self):
        """Primary is decided by POSITION. Deciding it by ``id`` would make
        every id-less sibling match ``chargers[0]["id"] is None`` and inherit
        the same counter — the fleet sum would then triple-count it."""
        assert self._collect({
            "ev_total_energy_sensor": COUNTER,
            "ev_chargers": [{}, {}, {}],
        }) == [COUNTER]

    def test_a_daily_counter_is_a_fallback_and_never_a_second_source(self):
        """A charger's lifetime and daily counters report the same kWh.
        Summing both deltas would double-count every session."""
        assert self._collect({
            "ev_chargers": [{"id": "a", "ev_total_energy_sensor": COUNTER}],
            "ev_daily_energy_sensor": "sensor.wallbox_daily",
        }) == [COUNTER]
        assert self._collect({
            "ev_daily_energy_sensor": "sensor.wallbox_daily",
        }) == ["sensor.wallbox_daily"]

    def test_the_energy_dashboard_counter_is_the_last_resort(self):
        assert self._collect(
            {}, ed=SimpleNamespace(ev_energy="sensor.ed_ev_energy"),
        ) == ["sensor.ed_ev_energy"]

    def test_nothing_configured_is_an_empty_list_not_a_crash(self):
        assert self._collect({}) == []
        assert self._collect({"ev_chargers": [{"id": "a"}]}) == []

    def test_an_empty_set_leaves_reconciliation_disabled(self):
        calc = _calc(_hass({}))
        calc.configure_ev_counters(_hass({}), [], True)
        assert calc._ev_counter_enabled is False
