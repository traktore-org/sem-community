"""Per-charger energy flow integration tests (v1.6.15).

v1.6.9 added the per-charger POWER attribution surface
``PowerFlows.per_charger``. v1.6.15 adds the matching ENERGY
accumulator surface ``EnergyFlows.per_charger`` plus the integration
inside ``FlowCalculator.integrate_energy_flows``. These tests pin:

1. Single-charger setups remain identical (empty
   ``EnergyFlows.per_charger`` dict, fleet fields unchanged).
2. Multi-charger setups accumulate per-charger kWh that match the
   fleet ``solar_to_ev`` / ``grid_to_ev`` / ``battery_to_ev`` sum
   within float rounding.
3. Day rollover clears both the fleet and the per-charger
   accumulators.
4. Persistence round-trip preserves per-charger state across an HA
   restart mid-day.
5. Pre-v1.6.15 snapshots (no ``per_charger`` key) restore cleanly.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    ChargerFlows,
    EnergyFlows,
    PowerFlows,
)


def _integrate(fc: FlowCalculator, **per_charger_flows) -> EnergyFlows:
    """Integrate a single cycle. ``per_charger_flows`` is
    ``{cid: (solar_w, grid_w, battery_w)}``. Fleet fields are the sums."""
    flows = PowerFlows()
    for cid, (s, g, b) in per_charger_flows.items():
        flows.solar_to_ev += s
        flows.grid_to_ev += g
        flows.battery_to_ev += b
        flows.per_charger[cid] = ChargerFlows(
            solar_to_ev=s, grid_to_ev=g, battery_to_ev=b,
        )
    # Integrate over 1 hour so kWh equals input W / 1000 (easy to assert).
    return fc.integrate_energy_flows(flows, interval_seconds=3600)


class TestSingleChargerBackCompat:
    """Single-charger / no per-charger data: existing fleet behaviour
    is unchanged, and the ``per_charger`` dict on the result stays
    empty so downstream readers that don't know about it keep working."""

    def test_no_per_charger_data_yields_empty_dict(self):
        fc = FlowCalculator()
        flows = PowerFlows()
        flows.solar_to_ev = 4000.0  # 1 charger, fleet view only
        result = fc.integrate_energy_flows(flows, interval_seconds=3600)
        # Fleet integrated correctly.
        assert result.solar_to_ev == pytest.approx(4.0, rel=1e-3)
        # Per-charger dict remains empty.
        assert result.per_charger == {}


class TestMultiChargerSumInvariant:
    """Sum-of-per-charger == fleet within rounding. Mirrors the
    invariant ``calculate_power_flows`` pins at the W level."""

    def test_two_chargers_split_solar(self):
        fc = FlowCalculator()
        # Two chargers, one drawing 2000 W solar, one drawing 3000 W solar.
        # One full hour → 2 kWh and 3 kWh respectively, fleet = 5 kWh.
        result = _integrate(fc, left=(2000.0, 0.0, 0.0), right=(3000.0, 0.0, 0.0))
        assert result.solar_to_ev == pytest.approx(5.0, rel=1e-3)
        assert result.per_charger["left"].solar_to_ev == pytest.approx(2.0)
        assert result.per_charger["right"].solar_to_ev == pytest.approx(3.0)
        # Sum invariant.
        per_charger_sum = sum(
            cef.solar_to_ev for cef in result.per_charger.values()
        )
        assert per_charger_sum == pytest.approx(result.solar_to_ev, abs=0.01)

    def test_mixed_sources_per_charger(self):
        """Charger A pulls from solar; charger B pulls from grid. Per-
        charger sourcing differs; fleet is the sum of both."""
        fc = FlowCalculator()
        result = _integrate(fc, left=(4000.0, 0.0, 0.0), right=(0.0, 4000.0, 0.0))
        assert result.per_charger["left"].solar_to_ev == pytest.approx(4.0)
        assert result.per_charger["left"].grid_to_ev == 0.0
        assert result.per_charger["right"].solar_to_ev == 0.0
        assert result.per_charger["right"].grid_to_ev == pytest.approx(4.0)
        # Fleet sees both.
        assert result.solar_to_ev == pytest.approx(4.0)
        assert result.grid_to_ev == pytest.approx(4.0)


class TestMultiCycleAccumulation:
    """Across multiple cycles the per-charger accumulator grows like
    the fleet one — pins integration, not snapshotting."""

    def test_two_cycles_accumulate(self):
        fc = FlowCalculator()
        # Two 30-min cycles at 4000 W each → total 4 kWh.
        for _ in range(2):
            flows = PowerFlows()
            flows.solar_to_ev = 4000.0
            flows.per_charger["left"] = ChargerFlows(solar_to_ev=4000.0)
            result = fc.integrate_energy_flows(flows, interval_seconds=1800)
        assert result.solar_to_ev == pytest.approx(4.0, rel=1e-3)
        assert result.per_charger["left"].solar_to_ev == pytest.approx(4.0, rel=1e-3)


class TestDayRollover:
    """Both fleet AND per-charger accumulators clear at local midnight."""

    def test_rollover_clears_per_charger(self):
        fc = FlowCalculator()
        _integrate(fc, left=(4000.0, 0.0, 0.0))
        assert fc._per_charger_accumulators["left"]["solar_to_ev"] > 0

        # Simulate next day.
        with patch(
            "custom_components.solar_energy_management.coordinator.flow_calculator.dt_util.now"
        ) as mocked:
            tomorrow = date.today() + timedelta(days=1)
            mocked.return_value.date.return_value = tomorrow
            mocked.return_value.isoformat.return_value = tomorrow.isoformat()
            flows = PowerFlows()
            flows.solar_to_ev = 1000.0
            flows.per_charger["left"] = ChargerFlows(solar_to_ev=1000.0)
            result = fc.integrate_energy_flows(flows, interval_seconds=3600)
            # Today's slate: 1 kWh, NOT 1+4.
            assert result.solar_to_ev == pytest.approx(1.0, rel=1e-3)
            assert result.per_charger["left"].solar_to_ev == pytest.approx(1.0, rel=1e-3)


class TestPersistenceRoundTrip:
    """``get_flow_accumulator_state`` / ``restore_flow_accumulator_state``
    round-trip preserves per-charger kWh across an HA restart mid-day."""

    def test_snapshot_includes_per_charger_when_populated(self):
        fc = FlowCalculator()
        _integrate(fc, left=(4000.0, 0.0, 0.0), right=(0.0, 4000.0, 0.0))
        snap = fc.get_flow_accumulator_state()
        assert "per_charger" in snap
        assert "left" in snap["per_charger"]
        assert snap["per_charger"]["left"]["solar_to_ev"] == pytest.approx(4.0)
        assert snap["per_charger"]["right"]["grid_to_ev"] == pytest.approx(4.0)

    def test_snapshot_omits_per_charger_when_empty(self):
        """Single-charger / no per-charger data → snapshot stays
        bit-for-bit compatible with the pre-v1.6.15 format."""
        fc = FlowCalculator()
        flows = PowerFlows()
        flows.solar_to_ev = 4000.0
        fc.integrate_energy_flows(flows, interval_seconds=3600)
        snap = fc.get_flow_accumulator_state()
        assert "per_charger" not in snap

    def test_restore_round_trip(self):
        # Source FC: integrate, then snapshot.
        src = FlowCalculator()
        _integrate(src, left=(4000.0, 0.0, 0.0), right=(0.0, 3000.0, 0.0))
        snap = src.get_flow_accumulator_state()

        # Destination FC: restore from the snapshot.
        dst = FlowCalculator()
        dst.restore_flow_accumulator_state(snap)
        # Next cycle adds nothing — the restored accumulator IS the state.
        result = dst.integrate_energy_flows(PowerFlows(), interval_seconds=0)
        assert result.per_charger["left"].solar_to_ev == pytest.approx(4.0)
        assert result.per_charger["right"].grid_to_ev == pytest.approx(3.0)

    def test_restore_legacy_snapshot_without_per_charger(self):
        """Pre-v1.6.15 snapshot (no ``per_charger`` key) — restore
        cleanly, no per-charger state, no exceptions."""
        fc = FlowCalculator()
        legacy_snap = {
            "date": fc._current_date.isoformat(),
            "accumulators": {"solar_to_ev": 4.0, "grid_to_ev": 1.0},
        }
        fc.restore_flow_accumulator_state(legacy_snap)
        assert fc._flow_accumulators["solar_to_ev"] == pytest.approx(4.0)
        assert fc._per_charger_accumulators == {}


class TestDataDict:
    """v1.6.15: ``SEMData.to_dict`` emits per-charger
    keys when ``PowerFlows.per_charger`` / ``EnergyFlows.per_charger``
    are populated. Sensor descriptions in ``sensor.py`` (gated on
    ``len(ev_chargers) > 1``) look up these keys."""

    def test_dict_includes_per_charger_keys(self):
        from custom_components.solar_energy_management.coordinator.types import (
            ChargerEnergyFlows, SEMData,
        )
        d = SEMData()
        d.power_flows.per_charger["left"] = ChargerFlows(
            solar_to_ev=2500.0, grid_to_ev=0.0, battery_to_ev=0.0,
        )
        d.energy_flows.per_charger["left"] = ChargerEnergyFlows(
            solar_to_ev=1.25, grid_to_ev=0.0, battery_to_ev=0.0,
        )
        out = d.to_dict()
        assert out["charger_left_flow_solar_to_ev_power"] == 2500.0
        assert out["charger_left_flow_grid_to_ev_power"] == 0.0
        assert out["charger_left_flow_solar_to_ev_energy"] == 1.25
        # Sanity: fleet keys untouched.
        assert "flow_solar_to_ev_power" in out

    def test_dict_omits_per_charger_keys_when_empty(self):
        from custom_components.solar_energy_management.coordinator.types import (
            SEMData,
        )
        d = SEMData()
        out = d.to_dict()
        # No per_charger keys leak in the single-charger case.
        leaked = [k for k in out if k.startswith("charger_") and "flow" in k]
        assert leaked == []

    def test_dict_multi_charger_emits_all_six_keys_per_charger(self):
        """For each charger present in either power_flows.per_charger
        or energy_flows.per_charger, ``to_dict`` emits 6 keys: 3 power
        + 3 energy. These are the keys ``sensor.py`` looks up."""
        from custom_components.solar_energy_management.coordinator.types import (
            ChargerEnergyFlows, SEMData,
        )
        d = SEMData()
        for cid in ("left", "right"):
            d.power_flows.per_charger[cid] = ChargerFlows(
                solar_to_ev=2500.0, grid_to_ev=500.0, battery_to_ev=1000.0,
            )
            d.energy_flows.per_charger[cid] = ChargerEnergyFlows(
                solar_to_ev=2.5, grid_to_ev=0.5, battery_to_ev=1.0,
            )
        out = d.to_dict()
        for cid in ("left", "right"):
            for suffix in (
                "flow_solar_to_ev_power", "flow_grid_to_ev_power",
                "flow_battery_to_ev_power", "flow_solar_to_ev_energy",
                "flow_grid_to_ev_energy", "flow_battery_to_ev_energy",
            ):
                assert f"charger_{cid}_{suffix}" in out, (
                    f"Missing key for {cid}/{suffix}"
                )


class TestEdgeCases:
    """Real-world transients: chargers appearing mid-day, disappearing,
    or the accumulator persistently surfacing kWh after the EV unplugs."""

    def test_charger_appears_mid_day_starts_at_zero(self):
        """Cycle 1: only ``left``. Cycle 2: ``right`` joins. The accumulator
        for ``right`` starts at 0 and integrates the cycle's draw — it
        doesn't backfill any imaginary earlier draw."""
        fc = FlowCalculator()
        # Cycle 1: only left, 1 h at 4000 W → 4 kWh.
        _integrate(fc, left=(4000.0, 0.0, 0.0))
        assert fc._per_charger_accumulators["left"]["solar_to_ev"] == pytest.approx(4.0)
        assert "right" not in fc._per_charger_accumulators
        # Cycle 2: right appears (1 h at 1000 W solar). Left also draws.
        result = _integrate(fc, left=(4000.0, 0.0, 0.0), right=(1000.0, 0.0, 0.0))
        assert result.per_charger["left"].solar_to_ev == pytest.approx(8.0, rel=1e-2)
        assert result.per_charger["right"].solar_to_ev == pytest.approx(1.0, rel=1e-2)

    def test_charger_idle_in_cycle_still_surfaces_accumulator(self):
        """After accumulating kWh for ``left``, a cycle where the
        ``power_flows.per_charger`` map omits ``left`` (car unplugged)
        must NOT drop ``left`` from the result — the kWh stays
        visible until the day rollover."""
        fc = FlowCalculator()
        _integrate(fc, left=(4000.0, 0.0, 0.0))
        # Cycle 2: only right, no left in power_flows.
        result = _integrate(fc, right=(1000.0, 0.0, 0.0))
        assert "left" in result.per_charger
        assert result.per_charger["left"].solar_to_ev == pytest.approx(4.0, rel=1e-2)

    def test_zero_interval_no_accumulation(self):
        """``interval_seconds=0`` (e.g. immediately after restore) →
        no accumulation, but the existing accumulator state IS
        emitted."""
        fc = FlowCalculator()
        _integrate(fc, left=(4000.0, 0.0, 0.0))
        before = fc._per_charger_accumulators["left"]["solar_to_ev"]
        flows = PowerFlows()
        flows.per_charger["left"] = ChargerFlows(solar_to_ev=4000.0)
        result = fc.integrate_energy_flows(flows, interval_seconds=0)
        after = fc._per_charger_accumulators["left"]["solar_to_ev"]
        assert after == pytest.approx(before)
        # Result still mirrors the accumulator.
        assert result.per_charger["left"].solar_to_ev == pytest.approx(before, rel=1e-2)


class TestBadSnapshotDefence:
    """The restore path should accept legacy + valid snapshots and
    ignore malformed ones rather than crashing. Pin the per-charger
    counterpart to the existing legacy_snap test."""

    def test_restore_non_dict_per_charger_silently_skipped(self):
        fc = FlowCalculator()
        snap = {
            "date": fc._current_date.isoformat(),
            "accumulators": {"solar_to_ev": 4.0},
            "per_charger": "not-a-dict",  # type-bad
        }
        # Must not raise.
        fc.restore_flow_accumulator_state(snap)
        assert fc._flow_accumulators["solar_to_ev"] == pytest.approx(4.0)
        assert fc._per_charger_accumulators == {}

    def test_restore_per_charger_with_non_dict_entry(self):
        fc = FlowCalculator()
        snap = {
            "date": fc._current_date.isoformat(),
            "accumulators": {"solar_to_ev": 4.0},
            "per_charger": {"left": "not-a-dict-either"},
        }
        fc.restore_flow_accumulator_state(snap)
        # ``left`` silently skipped — no entry in accumulators.
        assert "left" not in fc._per_charger_accumulators

    def test_restore_per_charger_with_non_numeric_values(self):
        """Same defence as the fleet path: non-numeric values are
        silently skipped per-key rather than failing the whole
        restore."""
        fc = FlowCalculator()
        snap = {
            "date": fc._current_date.isoformat(),
            "accumulators": {},
            "per_charger": {
                "left": {"solar_to_ev": 2.5, "grid_to_ev": "bad", "battery_to_ev": None},
            },
        }
        fc.restore_flow_accumulator_state(snap)
        assert fc._per_charger_accumulators["left"]["solar_to_ev"] == pytest.approx(2.5)
        assert "grid_to_ev" not in fc._per_charger_accumulators["left"]
        assert "battery_to_ev" not in fc._per_charger_accumulators["left"]


class TestSensorDescriptions:
    """v1.6.15 wires per-charger flow descriptions in ``sensor.py``
    gated on ``len(ev_chargers) > 1``. Reproducing the gate in a
    unit test pins the user-visible entity surface."""

    def test_single_charger_no_per_charger_flow_descriptions(self):
        """One charger configured → no per-charger flow sensors
        (the fleet ``sensor.sem_flow_*_to_ev_*`` entities are
        authoritative)."""
        ev_chargers = [{"id": "left", "name": "Wallbox Left"}]
        descriptions = self._build_per_charger_descriptions(ev_chargers)
        flow_keys = [d.key for d in descriptions if "flow_" in d.key]
        assert flow_keys == []

    def test_multi_charger_emits_six_flow_descriptions_per_charger(self):
        """Two chargers → 12 flow descriptions: 3 power + 3 energy × 2."""
        ev_chargers = [
            {"id": "left", "name": "Wallbox Left"},
            {"id": "right", "name": "Wallbox Right"},
        ]
        descriptions = self._build_per_charger_descriptions(ev_chargers)
        flow_keys = sorted(d.key for d in descriptions if "flow_" in d.key)
        assert flow_keys == [
            "charger_left_flow_battery_to_ev_energy",
            "charger_left_flow_battery_to_ev_power",
            "charger_left_flow_grid_to_ev_energy",
            "charger_left_flow_grid_to_ev_power",
            "charger_left_flow_solar_to_ev_energy",
            "charger_left_flow_solar_to_ev_power",
            "charger_right_flow_battery_to_ev_energy",
            "charger_right_flow_battery_to_ev_power",
            "charger_right_flow_grid_to_ev_energy",
            "charger_right_flow_grid_to_ev_power",
            "charger_right_flow_solar_to_ev_energy",
            "charger_right_flow_solar_to_ev_power",
        ]

    @staticmethod
    def _build_per_charger_descriptions(ev_chargers):
        """Mirror the gating logic in ``sensor.py:async_setup_entry``
        for the v1.6.15 flow descriptions. Kept in-test so the unit
        check is independent of the broader setup pipeline (importing
        the real ``async_setup_entry`` would pull in HA's full entity
        registry, well outside this test's scope)."""
        from homeassistant.components.sensor import (
            SensorDeviceClass, SensorEntityDescription, SensorStateClass,
        )
        from homeassistant.const import UnitOfEnergy, UnitOfPower
        out = []
        if len(ev_chargers) > 1:
            for c in ev_chargers:
                cid = c.get("id", "ev_charger")
                cname = c.get("name", "EV Charger")
                for src in ("solar", "grid", "battery"):
                    out.append(SensorEntityDescription(
                        key=f"charger_{cid}_flow_{src}_to_ev_power",
                        name=f"{cname} {src.title()} → EV Power",
                        device_class=SensorDeviceClass.POWER,
                        state_class=SensorStateClass.MEASUREMENT,
                        native_unit_of_measurement=UnitOfPower.WATT,
                        suggested_display_precision=0,
                    ))
                    out.append(SensorEntityDescription(
                        key=f"charger_{cid}_flow_{src}_to_ev_energy",
                        name=f"{cname} {src.title()} → EV Energy",
                        device_class=SensorDeviceClass.ENERGY,
                        state_class=SensorStateClass.TOTAL,
                        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                        suggested_display_precision=2,
                    ))
        return out
