"""#829 × #778 — the retention purge can never eat the planning evidence.

Guido's question, and the right one to ask: the budget needs five nights and
seven settled forecast days, and we shipped a service that deletes SEM history.
If those two ever met, the evidence would be purged before it could ever be
complete, and the budget would sit at "learning" forever without anyone
understanding why.

They cannot meet, for three independent reasons — and this file pins all three,
because "safe by accident" is one refactor away from unsafe:

1. the evidence does not live in the recorder at all. Sealed nights and the
   forecast ledger are in SEM's own ``.storage`` document; the purge calls
   ``recorder.purge_entities``, which cannot reach it;
2. the purge list is derived from "has no ``state_class``", and every planning
   sensor is a MEASUREMENT — so they are excluded even from row deletion;
3. nothing in the #778 chain reads history back. The evidence is accumulated
   forward, cycle by cycle, and persisted.
"""

from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator.retention import (
    purgeable_entities,
)

_PKG = Path(__file__).resolve().parent.parent

#: Every sensor the #778 budget publishes its evidence through.
PLANNING_SENSORS = [
    "sensor.sem_battery_spendable_kwh",
    "sensor.sem_battery_dynamic_floor_pct",
    "sensor.sem_battery_measured_capacity_kwh",
    "sensor.sem_battery_capacity_drift_pct",
    "sensor.sem_forecast_trust_d1",
    "sensor.sem_forecast_trust_d2",
]


class TestThePurgeListExcludesThem:
    def test_no_planning_sensor_is_purgeable(self):
        """They all carry state_class=measurement, so the derived list drops
        them. Asserted through the real function, not by re-reading the rule."""
        entities = [(eid, "measurement") for eid in PLANNING_SENSORS]
        assert purgeable_entities(entities) == []

    def test_the_guard_is_the_state_class_and_nothing_else(self):
        """Inverse pin: strip the state_class and they DO become purgeable.
        Without this, the test above would pass just as happily against a
        function that returned [] for everything."""
        entities = [(eid, None) for eid in PLANNING_SENSORS]
        assert sorted(purgeable_entities(entities)) == sorted(PLANNING_SENSORS)


class TestTheEvidenceIsNotInTheRecorder:
    def test_no_planning_module_reads_history(self):
        """A single history read would put the evidence back within reach of
        the purge — and worse, of the user's own recorder retention, which SEM
        does not control at all."""
        modules = [
            "coordinator/battery_night.py",
            "coordinator/forecast_ledger.py",
            "coordinator/measured_capacity.py",
            "coordinator/spendable_budget.py",
            "coordinator/refill_estimate.py",
            "coordinator/planning_phase.py",
        ]
        offenders = []
        for rel in modules:
            src = (_PKG / rel).read_text(encoding="utf-8")
            # Comments mentioning the recorder are fine; imports and calls are not.
            for line in src.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"'):
                    continue
                if ("recorder" in stripped and "import" in stripped) or \
                   "get_significant_states" in stripped or \
                   "history.state_changes" in stripped:
                    offenders.append(f"{rel}: {stripped}")
        assert not offenders, (
            "a #778 module reads recorder history — the evidence would then be "
            f"subject to purging and to the user's own retention: {offenders}")

    def test_nights_and_ledger_persist_through_sem_storage(self):
        src = (_PKG / "coordinator" / "storage.py").read_text(encoding="utf-8")
        assert "battery_nights" in src
        assert "def set_battery_night_state" in src
        assert "forecast_ledger" in src


class TestTheSampleGatesAreMeaningful:
    """The counts the evidence must reach, pinned so a future edit that lowers
    them has to say so out loud."""

    def test_the_gates_are_what_the_card_promises(self):
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            MIN_NEED_SAMPLES,
        )
        from custom_components.solar_energy_management.coordinator.forecast_ledger import (
            MIN_SAMPLES_FOR_TRUST,
        )
        assert MIN_NEED_SAMPLES == 5
        assert MIN_SAMPLES_FOR_TRUST == 7
