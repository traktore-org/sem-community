"""Unit tests for #289 Option A — sub-cycle EV power passthrough.

Pre-fix (≤ v1.6.1): ``sensor.sem_ev_power`` only updated on the
coordinator's 10-second cycle. During EV ramp / drop transients the
dashboard showed a ~5 kW gap vs ``sensor.keba_p30_charging_power`` for
up to one full cycle, because both sensors were sampled on different
schedules.

Post-fix (v1.6.2): the ``ev_power`` sensor *also* subscribes to its
upstream entities via ``async_track_state_change_event``. When any
upstream changes the SEM sensor re-sums and pushes the new value
immediately, with the energy-balance derivation (which stays on cycle
granularity) catching up on the next coordinator tick.

These tests pin both the single-charger and multi-charger paths plus
the cleanup invariant.
"""
from unittest.mock import MagicMock, AsyncMock

import pytest

from custom_components.solar_energy_management.sensor import SEMSolarSensor


def _make_state(value, available=True):
    """Tiny stub mimicking ``hass.states.get(...)`` return shape."""
    st = MagicMock()
    st.state = str(value) if available else "unavailable"
    return st


def _build_sensor_with_upstreams(
    config, state_lookup, key="ev_power",
):
    """Construct a minimal SEMSolarSensor bypassing CoordinatorEntity init.

    state_lookup is a dict ``{entity_id: state_value_or_None}``.
    Both passed through the resolved subscription path so the callback
    sees the configured upstream(s).
    """
    sensor = SEMSolarSensor.__new__(SEMSolarSensor)
    sensor.coordinator = MagicMock()
    sensor.coordinator.config = config
    sensor.entity_description = MagicMock()
    sensor.entity_description.key = key

    # hass.states.get(eid) → state or None
    hass = MagicMock()
    def states_get(eid):
        return state_lookup.get(eid)
    hass.states.get = states_get
    sensor.hass = hass

    # Spies the production code calls
    sensor.async_write_ha_state = MagicMock()
    sensor._unsub_ev_power_track = None
    sensor._attr_native_value = None
    sensor._attr_available = False

    return sensor


# ──────────────────────────────────────────────────────────────────────
# Subscription resolution
# ──────────────────────────────────────────────────────────────────────

class TestSubscriptionResolution:
    """``_subscribe_ev_power_upstreams`` must resolve the right
    upstream(s) for every supported config shape."""

    def test_single_charger_uses_top_level_ev_power_sensor(self, monkeypatch):
        """Legacy single-charger: ``config['ev_power_sensor']`` is the
        one upstream to subscribe to."""
        captured = {}
        def fake_track(hass, entity_ids, callback):
            captured["entity_ids"] = entity_ids
            return MagicMock()  # the unsub callable
        monkeypatch.setattr(
            "custom_components.solar_energy_management.sensor."
            "async_track_state_change_event",
            fake_track,
        )

        sensor = _build_sensor_with_upstreams(
            config={"ev_power_sensor": "sensor.keba_p30_charging_power"},
            state_lookup={},
        )
        sensor._subscribe_ev_power_upstreams()

        assert captured["entity_ids"] == ["sensor.keba_p30_charging_power"]

    def test_multi_charger_subscribes_to_every_charger_sensor(self, monkeypatch):
        """Multi-charger (≥ 2 chargers): subscribe to every charger's
        ``ev_charging_power_sensor`` — the same set ``SensorReader``
        sums on every cycle."""
        captured = {}
        def fake_track(hass, entity_ids, callback):
            captured["entity_ids"] = entity_ids
            return MagicMock()
        monkeypatch.setattr(
            "custom_components.solar_energy_management.sensor."
            "async_track_state_change_event",
            fake_track,
        )

        sensor = _build_sensor_with_upstreams(
            config={
                "ev_chargers": [
                    {"ev_charging_power_sensor": "sensor.wallbox_a_power"},
                    {"ev_charging_power_sensor": "sensor.wallbox_b_power"},
                ],
            },
            state_lookup={},
        )
        sensor._subscribe_ev_power_upstreams()

        assert captured["entity_ids"] == [
            "sensor.wallbox_a_power",
            "sensor.wallbox_b_power",
        ]

    def test_no_upstream_configured_does_not_subscribe(self, monkeypatch):
        """Energy-Dashboard-only / partial configs: nothing to track,
        no subscription created. Don't pay for what isn't wired."""
        called = MagicMock()
        monkeypatch.setattr(
            "custom_components.solar_energy_management.sensor."
            "async_track_state_change_event",
            called,
        )
        sensor = _build_sensor_with_upstreams(config={}, state_lookup={})
        sensor._subscribe_ev_power_upstreams()
        called.assert_not_called()
        assert sensor._unsub_ev_power_track is None

    def test_falls_back_to_per_charger_when_top_level_missing(self, monkeypatch):
        """Single-charger config saved by the wizard under
        ``ev_chargers[0]`` rather than ``ev_power_sensor`` — fall back
        to it before giving up."""
        captured = {}
        def fake_track(hass, entity_ids, callback):
            captured["entity_ids"] = entity_ids
            return MagicMock()
        monkeypatch.setattr(
            "custom_components.solar_energy_management.sensor."
            "async_track_state_change_event",
            fake_track,
        )
        sensor = _build_sensor_with_upstreams(
            config={
                "ev_chargers": [
                    {"ev_charging_power_sensor": "sensor.keba_p30_charging_power"},
                ],
            },
            state_lookup={},
        )
        sensor._subscribe_ev_power_upstreams()
        assert captured["entity_ids"] == ["sensor.keba_p30_charging_power"]


# ──────────────────────────────────────────────────────────────────────
# Callback behaviour — single charger
# ──────────────────────────────────────────────────────────────────────

class TestSingleChargerCallback:
    def test_upstream_change_pushes_to_native_value(self):
        sensor = _build_sensor_with_upstreams(
            config={"ev_power_sensor": "sensor.keba_p30_charging_power"},
            state_lookup={"sensor.keba_p30_charging_power": _make_state(4850.0)},
        )
        sensor._ev_power_upstream_entities = ["sensor.keba_p30_charging_power"]

        sensor._handle_ev_power_change(MagicMock())

        assert sensor._attr_native_value == 4850
        assert sensor._attr_available is True
        sensor.async_write_ha_state.assert_called_once()

    def test_unavailable_upstream_does_not_clear_value(self):
        """Brief upstream unavailable blip during EV connect/disconnect:
        keep the last-known value rather than dropping to None, since
        the coordinator's next cycle will reconcile from the actual
        energy balance either way."""
        sensor = _build_sensor_with_upstreams(
            config={"ev_power_sensor": "sensor.keba_p30_charging_power"},
            state_lookup={
                "sensor.keba_p30_charging_power": _make_state(
                    None, available=False
                ),
            },
        )
        sensor._ev_power_upstream_entities = ["sensor.keba_p30_charging_power"]
        sensor._attr_native_value = 4850  # pre-existing value

        sensor._handle_ev_power_change(MagicMock())

        # No flip, no spurious write — the next coordinator cycle will
        # publish whatever the energy balance reconciles.
        assert sensor._attr_native_value == 4850
        sensor.async_write_ha_state.assert_not_called()

    def test_unparseable_upstream_state_skipped_silently(self):
        sensor = _build_sensor_with_upstreams(
            config={"ev_power_sensor": "sensor.x"},
            state_lookup={"sensor.x": _make_state("not-a-number")},
        )
        sensor._ev_power_upstream_entities = ["sensor.x"]
        sensor._attr_native_value = 2000

        sensor._handle_ev_power_change(MagicMock())

        assert sensor._attr_native_value == 2000  # untouched
        sensor.async_write_ha_state.assert_not_called()


# ──────────────────────────────────────────────────────────────────────
# Callback behaviour — multi-charger sum
# ──────────────────────────────────────────────────────────────────────

class TestMultiChargerCallback:
    def test_sum_across_all_upstreams_on_change(self):
        """Multi-charger: re-sum from hass.states.get() exactly like
        ``SensorReader._read_ev_power`` does. Test the canonical case
        of @RienduPre's Wallbox Pulsar pair (#284)."""
        sensor = _build_sensor_with_upstreams(
            config={
                "ev_chargers": [
                    {"ev_charging_power_sensor": "sensor.wallbox_a_power"},
                    {"ev_charging_power_sensor": "sensor.wallbox_b_power"},
                ],
            },
            state_lookup={
                "sensor.wallbox_a_power": _make_state(4140.0),
                "sensor.wallbox_b_power": _make_state(7200.0),
            },
        )
        sensor._ev_power_upstream_entities = [
            "sensor.wallbox_a_power", "sensor.wallbox_b_power",
        ]

        sensor._handle_ev_power_change(MagicMock())

        assert sensor._attr_native_value == 11340  # 4140 + 7200
        assert sensor._attr_available is True
        sensor.async_write_ha_state.assert_called_once()

    def test_partial_unavailable_sums_the_valid_ones(self):
        """One Wallbox momentarily unavailable, the other still
        reporting — publish the partial sum (matches SensorReader
        which also treats unavailable as 0 for the sum)."""
        sensor = _build_sensor_with_upstreams(
            config={
                "ev_chargers": [
                    {"ev_charging_power_sensor": "sensor.wallbox_a_power"},
                    {"ev_charging_power_sensor": "sensor.wallbox_b_power"},
                ],
            },
            state_lookup={
                "sensor.wallbox_a_power": _make_state(4140.0),
                "sensor.wallbox_b_power": _make_state(
                    None, available=False
                ),
            },
        )
        sensor._ev_power_upstream_entities = [
            "sensor.wallbox_a_power", "sensor.wallbox_b_power",
        ]

        sensor._handle_ev_power_change(MagicMock())

        # 4140 + (skipped unavailable) = 4140
        assert sensor._attr_native_value == 4140
        sensor.async_write_ha_state.assert_called_once()


# ──────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────

class TestCleanup:
    @pytest.mark.asyncio
    async def test_will_remove_from_hass_unsubscribes(self):
        """Removing the entity must call the unsub returned by
        ``async_track_state_change_event`` — otherwise we leak a
        callback per entity-add cycle."""
        sensor = SEMSolarSensor.__new__(SEMSolarSensor)
        sensor.entity_description = MagicMock()
        sensor.entity_description.state_class = None  # not TOTAL
        unsub = MagicMock()
        sensor._unsub_ev_power_track = unsub
        # Stub the super() call chain
        sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
        # Patch the CoordinatorEntity parent's method via direct call
        # (the production override is what we're testing).
        from unittest.mock import patch
        with patch(
            "custom_components.solar_energy_management.sensor."
            "CoordinatorEntity.async_will_remove_from_hass",
            AsyncMock(),
        ):
            await SEMSolarSensor.async_will_remove_from_hass(sensor)

        unsub.assert_called_once()
        assert sensor._unsub_ev_power_track is None

    @pytest.mark.asyncio
    async def test_will_remove_from_hass_safe_when_never_subscribed(self):
        """The subscription is opt-in (only ``ev_power``, only when an
        upstream is wired). Removing other sensors must not raise on
        the un-set attribute."""
        sensor = SEMSolarSensor.__new__(SEMSolarSensor)
        sensor.entity_description = MagicMock()
        sensor.entity_description.state_class = None
        sensor._unsub_ev_power_track = None  # never subscribed
        sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
        from unittest.mock import patch
        with patch(
            "custom_components.solar_energy_management.sensor."
            "CoordinatorEntity.async_will_remove_from_hass",
            AsyncMock(),
        ):
            # Must not raise.
            await SEMSolarSensor.async_will_remove_from_hass(sensor)
