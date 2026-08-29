"""#829 — SEM manages retention for its OWN fire-and-forget entities.

Guido, 22.08: *"an option to have certain retention on sensors — for most of
SEM's sensors the history isn't even important, these are fire and forget."*

Measured on the rig, the split that makes this safe:

    with state_class     179 entities  182,080 rows/24h  hourly stats FOREVER
    no  state_class      129 entities   31,280 rows/24h  no statistics, ever

Home Assistant compiles hourly long-term statistics for every entity carrying
a ``state_class`` and keeps them indefinitely (the rig still holds Oct 2024).
Those must never be purged — that IS the user's energy history. An entity
without a ``state_class`` has no statistics at all, so purging its states can
only remove short-term status noise.

So the feature is safe BY CONSTRUCTION rather than by care: the purge list is
derived from "has no state_class", which means a future statistics-bearing
sensor is automatically EXCLUDED instead of automatically swept up.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.retention import (
    RETENTION_OFF,
    purgeable_entities,
    retention_is_due,
)


def _e(entity_id, state_class=None):
    return (entity_id, state_class)


@pytest.mark.unit
class TestOnlyEntitiesWithoutStatisticsArePurgeable:

    def test_a_status_sensor_is_purgeable(self):
        assert purgeable_entities([_e("sensor.sem_charging_state")]) == [
            "sensor.sem_charging_state"]

    def test_a_measurement_sensor_is_never_purgeable(self):
        """It has statistics — purging would destroy real history."""
        assert purgeable_entities([_e("sensor.sem_solar_power", "measurement")]) == []

    def test_a_total_sensor_is_never_purgeable(self):
        assert purgeable_entities([_e("sensor.sem_daily_solar_energy", "total")]) == []
        assert purgeable_entities(
            [_e("sensor.sem_lifetime_yield", "total_increasing")]) == []

    def test_a_future_statistics_sensor_is_excluded_automatically(self):
        """The property that makes this safe: the list is derived, not
        maintained. A new sensor that carries statistics opts ITSELF out."""
        fleet = [_e("sensor.sem_brand_new_thing", "measurement"),
                 _e("sensor.sem_brand_new_status")]
        assert purgeable_entities(fleet) == ["sensor.sem_brand_new_status"]

    def test_entities_sem_does_not_own_are_never_touched(self):
        """Even a stats-less foreign entity stays untouched — SEM purges only
        what it created."""
        fleet = [_e("sensor.living_room_motion"), _e("sensor.shelly_uptime"),
                 _e("sensor.sem_grid_status")]
        assert purgeable_entities(fleet) == ["sensor.sem_grid_status"]

    def test_an_empty_state_class_counts_as_none(self):
        assert purgeable_entities([_e("sensor.sem_x", "")]) == ["sensor.sem_x"]

    def test_the_list_is_deterministic(self):
        fleet = [_e("sensor.sem_b"), _e("sensor.sem_a"), _e("sensor.sem_c")]
        assert purgeable_entities(fleet) == [
            "sensor.sem_a", "sensor.sem_b", "sensor.sem_c"]

    def test_all_domains_sem_owns_are_covered(self):
        """The observer-mode SWITCH writes 3,376 rows/day carrying a decision
        payload — a switch's history should be when it was switched."""
        fleet = [_e("switch.sem_observer_mode"), _e("binary_sensor.sem_layer_mismatch"),
                 _e("number.sem_charger_x_target", None)]
        assert "switch.sem_observer_mode" in purgeable_entities(fleet)
        assert "binary_sensor.sem_layer_mismatch" in purgeable_entities(fleet)


@pytest.mark.unit
class TestItIsOffUntilAsked:

    def test_zero_means_off(self):
        assert RETENTION_OFF == 0
        assert retention_is_due(RETENTION_OFF, last_run_day=None, today="2026-08-22") is False

    def test_first_run_is_due(self):
        assert retention_is_due(3, last_run_day=None, today="2026-08-22") is True

    def test_once_a_day_only(self):
        assert retention_is_due(3, last_run_day="2026-08-22", today="2026-08-22") is False
        assert retention_is_due(3, last_run_day="2026-08-21", today="2026-08-22") is True

    def test_a_nonsense_value_is_treated_as_off(self):
        for bad in (None, -1, "x"):
            assert retention_is_due(bad, last_run_day=None, today="2026-08-22") is False


@pytest.mark.unit
class TestRunPurgeActsOnlyOnWhatItMay:
    """The runner both the button and the daily job call — so neither can
    invent its own list."""

    class _FakeState:
        def __init__(self, entity_id, state_class=None):
            self.entity_id = entity_id
            self.attributes = {"state_class": state_class} if state_class else {}

    class _FakeHass:
        def __init__(self, states):
            self._states = states
            self.calls = []
            outer = self
            class _States:
                def async_all(self_inner): return outer._states
            class _Services:
                async def async_call(self_inner, domain, service, data, blocking=False):
                    outer.calls.append((domain, service, data))
            self.states = _States()
            self.services = _Services()

    @pytest.mark.asyncio
    async def test_it_purges_only_the_statistics_less_sem_entities(self):
        from custom_components.solar_energy_management.coordinator import retention as R
        hass = self._FakeHass([
            self._FakeState("sensor.sem_charging_state"),
            self._FakeState("sensor.sem_solar_power", "measurement"),
            self._FakeState("sensor.foreign_thing"),
            self._FakeState("switch.sem_observer_mode"),
        ])
        purged = await R.run_purge(hass, 3)
        assert purged == ["sensor.sem_charging_state", "switch.sem_observer_mode"]
        assert len(hass.calls) == 1
        domain, service, data = hass.calls[0]
        assert (domain, service) == ("recorder", "purge_entities")
        assert data["keep_days"] == 3
        assert "sensor.sem_solar_power" not in data["entity_id"]
        assert "sensor.foreign_thing" not in data["entity_id"]

    @pytest.mark.asyncio
    async def test_off_calls_nothing_at_all(self):
        from custom_components.solar_energy_management.coordinator import retention as R
        hass = self._FakeHass([self._FakeState("sensor.sem_charging_state")])
        assert await R.run_purge(hass, 0) == []
        assert hass.calls == []
