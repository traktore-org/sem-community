"""#661 — a split sensor pair that contradicts itself, caught where the
evidence still exists.

The shape being closed: ``health_check`` carried a mutual-exclusivity check on
``grid_import_power``/``grid_export_power`` (and the battery pair). Those four
fields are not inputs — ``PowerReadings.calculate_derived`` re-derives all of
them from ONE signed scalar with ``max(0, ±x)``, so "both above 10 W" is
unrepresentable by construction. The check could not fail in production; its
test passed only by hand-building a ``PowerReadings`` and skipping the
derivation. (Bug class 8: the can't-fail check that reads as coverage.)

The audit now runs at the netting site, on the raw pair.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
)
from custom_components.solar_energy_management.coordinator.sign_audit import (
    SplitSensorExclusivityAudit,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


@pytest.mark.unit
class TestTheOldCheckWasUnfirable661:
    """Pins WHY the check moved, so nobody re-adds it downstream."""

    @pytest.mark.parametrize(
        "grid_power", [-3000.0, 3000.0, 0.0, -10.0, 10.0],
    )
    def test_netting_makes_both_sides_active_unrepresentable_for_grid(self, grid_power):
        p = PowerReadings(grid_power=grid_power)
        p.calculate_derived()
        assert not (p.grid_import_power > 10 and p.grid_export_power > 10)

    @pytest.mark.parametrize(
        "battery_power", [-2500.0, 2500.0, 0.0, -10.0, 10.0],
    )
    def test_netting_makes_both_sides_active_unrepresentable_for_battery(self, battery_power):
        p = PowerReadings(battery_power=battery_power)
        p.calculate_derived()
        assert not (p.battery_charge_power > 10 and p.battery_discharge_power > 10)

    def test_health_check_no_longer_claims_to_check_exclusivity(self):
        """A contradictory pair, hand-built exactly the way the old test did.

        HealthCheck must not report it — not because the state is fine, but
        because HealthCheck has no way to know: by the time it sees these
        fields the netting has already happened. Reporting from here would be
        the can't-fail check again.
        """
        p = PowerReadings(
            solar_power=0.0, ev_power=0.0,
            grid_power=0.0, battery_power=0.0,
        )
        p.calculate_derived()
        # Force the impossible state the derivation just refused to produce.
        p.grid_import_power = 3000.0
        p.grid_export_power = 3000.0
        p.battery_charge_power = 2000.0
        p.battery_discharge_power = 2000.0

        violations = HealthCheck().check_power_balance(p, home_hold_active=True)
        assert not any("both active" in v for v in violations)


@pytest.mark.unit
class TestSplitPairAudit661:
    def test_a_clean_import_only_house_never_flags(self):
        a = SplitSensorExclusivityAudit()
        for _ in range(50):
            assert a.update(3000.0, 0.0) is None
        assert not a.flagged

    def test_five_contradicting_cycles_warn_once(self):
        a = SplitSensorExclusivityAudit()
        verdicts = [a.update(3000.0, 2800.0) for _ in range(8)]
        assert verdicts[:4] == [None, None, None, None]
        assert verdicts[4] == "warn"
        # Warn-once: the flag stays raised but does not re-warn every cycle.
        assert verdicts[5:] == [None, None, None]
        assert a.flagged is True

    def test_four_cycles_is_not_enough(self):
        """A single transient overlap (meter reporting lag on a fast swing)
        must not accuse the user's config."""
        a = SplitSensorExclusivityAudit()
        for _ in range(4):
            assert a.update(3000.0, 2800.0) is None
        assert not a.flagged

    def test_agreement_resets_the_vote_count(self):
        a = SplitSensorExclusivityAudit()
        for _ in range(4):
            a.update(3000.0, 2800.0)
        a.update(3000.0, 0.0)          # exclusive again
        assert a.votes == 0
        for _ in range(4):
            assert a.update(3000.0, 2800.0) is None
        assert not a.flagged

    def test_a_quiet_house_does_not_reset_the_votes(self):
        """Both sides near zero is not evidence of correctness — a night-time
        lull between two contradicting daytime cycles must not launder the
        accumulated votes, or a pair that only contradicts under load would
        never reach threshold."""
        a = SplitSensorExclusivityAudit()
        for _ in range(4):
            a.update(3000.0, 2800.0)
        assert a.update(0.0, 0.0) is None
        assert a.votes == 4
        assert a.update(3000.0, 2800.0) == "warn"

    def test_clear_is_reported_once_when_the_pair_recovers(self):
        a = SplitSensorExclusivityAudit()
        for _ in range(5):
            a.update(3000.0, 2800.0)
        assert a.flagged
        assert a.update(0.0, 3000.0) == "clear"
        assert not a.flagged
        assert a.update(0.0, 3000.0) is None

    def test_the_10w_floor_ignores_standby_bleed(self):
        """An export meter idling at 4 W while the house imports is standby
        noise, not a contradiction."""
        a = SplitSensorExclusivityAudit()
        for _ in range(20):
            assert a.update(3000.0, 4.0) is None
        assert not a.flagged

    def test_a_noisy_idle_sensor_above_the_floor_is_still_not_a_contradiction(self):
        """15 W of bleed on the idle side of a 3 kW import is 0.5% — real
        meters do this. Warning on it would recreate the #461 spurious-violation
        spam, and a detector nobody trusts is not a detector."""
        a = SplitSensorExclusivityAudit()
        for _ in range(20):
            assert a.update(3000.0, 15.0) is None
        assert not a.flagged

    def test_a_meaningful_share_on_both_sides_still_flags(self):
        """300 W against 3 kW is 10% — well past bleed, and the netted 2700 W
        understates the real import by a tenth."""
        a = SplitSensorExclusivityAudit()
        verdicts = [a.update(3000.0, 300.0) for _ in range(5)]
        assert verdicts[4] == "warn"

    def test_it_keeps_the_last_pair_for_the_diagnostic(self):
        a = SplitSensorExclusivityAudit()
        a.update(1234.0, 567.0)
        assert (a.last_a, a.last_b) == (1234.0, 567.0)

    def test_a_second_episode_is_reported_at_a_lower_key(self):
        """A pair that contradicts, recovers, then contradicts again must not
        go silent — that is the class-8 shape this whole issue is about. The
        WARNING stays once-per-lifetime (a genuinely miswired pair contradicts
        continuously and does not need it every cycle); later episodes come
        back as ``"reflag"``, which the adapter logs at INFO."""
        a = SplitSensorExclusivityAudit()
        for _ in range(5):
            a.update(3000.0, 2800.0)
        assert a.episodes == 1
        assert a.update(3000.0, 0.0) == "clear"

        verdicts = [a.update(3000.0, 2800.0) for _ in range(5)]
        assert verdicts[4] == "reflag"
        assert a.episodes == 2
        assert a.flagged is True

    def test_an_episode_costs_five_cycles_so_reflag_cannot_spam(self):
        """The bound on the INFO line: it takes a full re-accumulation to earn
        another one, so even a flapping pair cannot emit more than one line per
        six cycles."""
        a = SplitSensorExclusivityAudit()
        for _ in range(5):
            a.update(3000.0, 2800.0)
        a.update(3000.0, 0.0)
        assert [a.update(3000.0, 2800.0) for _ in range(4)] == [None] * 4


# ──────────────────────────────────────────────────────────────────────────
# Pipeline: the audit has to fire through the real read_power() chain, not
# just in isolation. This is the #129 lesson — unit tests pass individually
# while the assembled pipeline never runs the code.
# ──────────────────────────────────────────────────────────────────────────

from custom_components.solar_energy_management.tests.test_split_grid_integration import (  # noqa: E402
    _make_energy_dashboard_config,
    _make_reader_with_states,
    _state,
)
from unittest.mock import MagicMock  # noqa: E402


def _growatt_split_reader(import_w, export_w):
    """Pattern E (split grid, no combined sensor) — the install family the
    original check was written for.

    Returns ``(reader, states)``; the states dict is the one the reader reads
    through, so mutating a state's ``.state`` changes what the NEXT
    ``read_power()`` sees — which is how a real install recovers.
    """
    ed = _make_energy_dashboard_config(
        solar_power="sensor.growatt_solar_power",
        grid_import_power=None,
        grid_import_energy="sensor.mix_import_from_grid_today",
        grid_export_energy="sensor.mix_export_to_grid_today",
        battery_power=None,
    )
    states = {
        "sensor.growatt_solar_power": _state(3000),
        "sensor.mix_import_from_grid": _state(import_w, device_class="power"),
        "sensor.mix_export_to_grid": _state(export_w, device_class="power"),
        "sensor.mix_import_from_grid_today": _state(10, "kWh"),
        "sensor.mix_export_to_grid_today": _state(20, "kWh"),
    }
    return _make_reader_with_states(MagicMock(), states, ed), states


def _two_sensor_battery_reader(charge_w, discharge_w):
    """#551 "Two sensors" battery power_config, ONE battery (Fronius Verto).

    This is the branch a single-battery install takes — the multi-battery
    ``battery_power_pairs`` loop never runs — and it nets identically, so it
    needs the same audit. Pinned through the pipeline because the unit test
    could not have caught the branch being missed.
    """
    ed = _make_energy_dashboard_config(
        solar_power="sensor.verto_solar_power",
        grid_import_power="sensor.verto_grid_power",
        battery_power=None,
    )
    ed.battery_power_from = "sensor.verto_battery_discharge"
    ed.battery_power_to = "sensor.verto_battery_charge"
    ed.has_battery = True
    states = {
        "sensor.verto_solar_power": _state(3000),
        "sensor.verto_grid_power": _state(0, device_class="power"),
        "sensor.verto_battery_charge": _state(charge_w, device_class="power"),
        "sensor.verto_battery_discharge": _state(discharge_w, device_class="power"),
        "sensor.grid_import_total": _state(10, "kWh"),
        "sensor.grid_export_total": _state(20, "kWh"),
    }
    return _make_reader_with_states(MagicMock(), states, ed), states


def _declared_grid_pair_reader(import_w, export_w):
    """#553 user-declared grid two-sensor pair — no discovery, no sign lock;
    it audits on every cycle."""
    ed = _make_energy_dashboard_config(
        solar_power="sensor.declared_solar_power",
        grid_import_power=None,
        battery_power=None,
    )
    ed.grid_power_from = "sensor.declared_grid_import"
    ed.grid_power_to = "sensor.declared_grid_export"
    states = {
        "sensor.declared_solar_power": _state(3000),
        "sensor.declared_grid_import": _state(import_w, device_class="power"),
        "sensor.declared_grid_export": _state(export_w, device_class="power"),
        "sensor.grid_import_total": _state(10, "kWh"),
        "sensor.grid_export_total": _state(20, "kWh"),
    }
    return _make_reader_with_states(MagicMock(), states, ed), states


@pytest.mark.unit
class TestPipeline661:
    def test_a_healthy_split_install_never_flags(self):
        reader, _ = _growatt_split_reader(1500, 0)
        for _ in range(20):
            reader.read_power()
        assert not any(a.flagged for a in reader._split_pair_audits.values())

    def test_crossed_split_sensors_flag_through_read_power(self):
        """The scenario from the issue: overlapping import/export sensors that
        both report during import. SEM nets them to a small wrong scalar and
        ``home_consumption`` absorbs the error via the balance identity — so
        nothing downstream can notice."""
        reader, _ = _growatt_split_reader(3000, 2800)
        for _ in range(5):
            power = reader.read_power()

        # The netting really does hide it: 200 W looks like a quiet house.
        assert power.grid_power == pytest.approx(-200.0)
        power.calculate_derived()
        assert power.grid_export_power == 0.0     # evidence gone

        # But the audit saw the raw pair.
        assert reader._split_pair_audits["grid"].flagged is True

    def test_the_audit_recovers_on_the_same_reader_when_the_pair_is_fixed(self):
        """Recovery the way it actually happens: the SAME long-lived reader
        starts seeing exclusive readings. (Transplanting the audit dict onto a
        fresh reader would prove nothing about the live object.)"""
        reader, states = _growatt_split_reader(3000, 2800)
        for _ in range(5):
            reader.read_power()
        assert reader._split_pair_audits["grid"].flagged

        states["sensor.mix_export_to_grid"].state = "0"
        reader.read_power()
        assert not reader._split_pair_audits["grid"].flagged

    def test_a_declared_grid_pair_is_audited_too(self):
        """#553 path — declared, not discovered."""
        reader, _ = _declared_grid_pair_reader(3000, 2800)
        for _ in range(5):
            reader.read_power()
        assert reader._split_pair_audits["grid"].flagged is True

    def test_a_healthy_declared_grid_pair_never_flags(self):
        reader, _ = _declared_grid_pair_reader(0, 2000)
        for _ in range(20):
            reader.read_power()
        assert not any(a.flagged for a in reader._split_pair_audits.values())

    def test_a_single_two_sensor_battery_is_audited(self):
        """A battery cannot charge and discharge at once. One battery in
        two-sensor mode skips the multi-battery pairs loop entirely, so this
        branch needs its own audit — and its own pipeline test."""
        reader, _ = _two_sensor_battery_reader(2800, 2500)
        for _ in range(5):
            power = reader.read_power()

        # Netted to +300 W: reads as a battery trickle-charging.
        assert power.battery_power == pytest.approx(300.0)
        assert reader._split_pair_audits["b1"].flagged is True

    def test_a_healthy_two_sensor_battery_never_flags(self):
        reader, _ = _two_sensor_battery_reader(0, 2500)
        for _ in range(20):
            reader.read_power()
        assert not any(a.flagged for a in reader._split_pair_audits.values())

    def test_a_pair_that_disappears_does_not_leave_a_stale_fault(self):
        """HA's energy settings can change under a live reader. A battery that
        is removed must not keep reporting a fault in the perception trace for
        hardware that is no longer there."""
        reader, _ = _two_sensor_battery_reader(2800, 2500)
        for _ in range(5):
            reader.read_power()
        assert reader._split_pair_audits["b1"].flagged

        ed = reader._energy_dashboard_config
        ed.battery_power_from = None
        ed.battery_power_to = None
        reader.read_power()
        assert "b1" not in reader._split_pair_audits
