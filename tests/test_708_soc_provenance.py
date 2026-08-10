"""#708 — the SOC provenance line must survive the sensor it describes.

Azlinon's third item: the charger card's info line ("Car: 63 % (12 min
ago) · est. now ~71 %") vanished at exactly the moment it became the
only honest thing on the card — when his vehicle-SOC sensor dropped out
and the gauge switched to the big "SOC (EST.)" reading.

The two symptoms have one cause, and it is backwards. Both the gauge
promotion and the info line key off the SAME live mirror going null:
``resolveChargerSoc`` promotes the estimate, and the info line's gate
requires a live value it no longer has. So the estimate takes over the
display precisely when its provenance disappears.

Underneath that there is a measurement bug, which is what this file
pins. The age was taken from the SOC entity's ``last_changed``. When an
entity goes unavailable HA writes a NEW state, so ``last_changed`` jumps
to the moment the sensor BROKE. A sensor that has been dead for half an
hour reports "0 min ago" — the interval is real, it is just not the
interval anyone wants. The age of a reading is measured from the reading.

The fix publishes the last usable reading and the instant it was taken
as attributes, so the age is computed from the right end. Deliberately a
TIMESTAMP and not a pre-computed age: an age attribute moves every
minute and would re-arm the #581 recorder churn the rounding at
``types.py`` was added to avoid. A timestamp only moves when a new
reading arrives; the card ticks the clock itself.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)


SOC_ENTITY = "sensor.zoe_state_of_charge"
CID = "large_bay"
CONFIG = {
    "ev_chargers": [{"id": CID, "name": "Large Bay EVSE",
                     "vehicle_soc_entity": SOC_ENTITY}],
    "ev_battery_capacity_kwh": 52,
}


class _Coord:
    """The intel builder, hosted on the state it reads."""

    _build_per_charger_intelligence = SEMCoordinator._build_per_charger_intelligence

    def __init__(self):
        self.hass = MagicMock()
        self.config = dict(CONFIG)
        det = EVTaperDetector({"ev_battery_capacity_kwh": 52})
        self._ev_taper_detectors = {CID: det}
        # Same declaration the real coordinator makes: the last usable
        # reading per charger, remembered so an unavailable sensor cannot
        # erase its own history.
        self._soc_last_seen: dict = {}
        self._states: dict = {}
        self.hass.states.get = self._states.get

    def publish_soc(self, value, age_min: float):
        """Put a live numeric SOC on the bus, last-changed ``age_min`` ago."""
        st = MagicMock()
        st.state = str(value)
        st.last_changed = dt_util.utcnow() - timedelta(minutes=age_min)
        self._states[SOC_ENTITY] = st

    def break_soc(self):
        """The sensor drops out — HA writes a new state NOW, which is what
        made ``last_changed`` measure the wrong interval."""
        st = MagicMock()
        st.state = STATE_UNAVAILABLE
        st.last_changed = dt_util.utcnow()
        self._states[SOC_ENTITY] = st

    def intel(self) -> dict:
        return self._build_per_charger_intelligence()[CID]


@pytest.mark.unit
class TestTheAgeIsMeasuredFromTheReading:

    def test_a_live_reading_reports_its_own_age(self):
        coord = _Coord()
        coord.publish_soc(63, age_min=12)
        intel = coord.intel()
        assert intel["vehicle_soc_last"] == 63.0
        assert intel["vehicle_soc_age_min"] == 12

    def test_an_unavailable_sensor_does_not_erase_its_last_reading(self):
        """THE report: the sensor drops out and the card loses the only
        thing that explained what it was showing."""
        coord = _Coord()
        coord.publish_soc(63, age_min=12)
        coord.intel()
        coord.break_soc()
        intel = coord.intel()

        # The gauge's live mirror correctly goes null — unchanged.
        assert intel["vehicle_soc"] is None
        # The provenance does not.
        assert intel["vehicle_soc_last"] == 63.0

    def test_an_unavailable_sensor_does_not_reset_the_age_to_zero(self):
        """``last_changed`` bumps when the entity breaks, so the pre-fix
        code called a half-hour-dead sensor "0 min ago"."""
        coord = _Coord()
        coord.publish_soc(63, age_min=12)
        coord.intel()
        coord.break_soc()
        assert coord.intel()["vehicle_soc_age_min"] >= 12

    def test_the_age_keeps_growing_while_the_sensor_is_down(self):
        coord = _Coord()
        coord.publish_soc(63, age_min=12)
        coord.intel()
        coord.break_soc()
        # Twenty more minutes pass with the sensor still dead: the memo
        # holds the ORIGINAL last_changed, so the age keeps counting.
        coord._soc_last_seen[CID] = (
            coord._soc_last_seen[CID][0],
            coord._soc_last_seen[CID][1] - timedelta(minutes=20),
        )
        assert coord.intel()["vehicle_soc_age_min"] >= 32

    def test_a_recovered_sensor_re_anchors_the_provenance(self):
        coord = _Coord()
        coord.publish_soc(63, age_min=12)
        coord.intel()
        coord.break_soc()
        coord.intel()
        coord.publish_soc(71, age_min=0)
        intel = coord.intel()
        assert intel["vehicle_soc_last"] == 71.0
        assert intel["vehicle_soc_age_min"] == 0


@pytest.mark.unit
class TestTheInstantIsPublishedNotTheAge:
    """An age attribute moves every minute; a timestamp moves only when a
    reading arrives. The card does the arithmetic (#581 recorder churn)."""

    def test_the_reading_instant_is_published_as_an_iso_timestamp(self):
        coord = _Coord()
        coord.publish_soc(63, age_min=12)
        at = coord.intel()["vehicle_soc_last_at"]
        assert isinstance(at, str)
        parsed = dt_util.parse_datetime(at)
        assert parsed is not None
        drift = abs((dt_util.utcnow() - parsed).total_seconds() / 60 - 12)
        assert drift < 1

    def test_the_instant_does_not_move_while_the_value_stands(self):
        """Two cycles, no new reading — the attribute must be byte-identical
        or every coordinator cycle writes a recorder row."""
        coord = _Coord()
        coord.publish_soc(63, age_min=12)
        first = coord.intel()["vehicle_soc_last_at"]
        second = coord.intel()["vehicle_soc_last_at"]
        assert first == second

    def test_the_instant_does_not_move_while_the_sensor_is_down(self):
        coord = _Coord()
        coord.publish_soc(63, age_min=12)
        first = coord.intel()["vehicle_soc_last_at"]
        coord.break_soc()
        assert coord.intel()["vehicle_soc_last_at"] == first


@pytest.mark.unit
class TestItReachesTheCard:
    """The intel dict is not the card's input — the flattened coordinator
    data and the sensor's attributes are. Both hops were unpinned: #708
    computed ``vehicle_soc_age_min`` for a year and never published it."""

    INTEL = {
        CID: {
            "estimated_soc": 71.0,
            "vehicle_soc": None,
            "minutes_to_full": None,
            "battery_health": 0.0,
            "energy_accounted_soc": 71.4,
            "vehicle_soc_last": 63.0,
            "vehicle_soc_last_at": "2026-08-05T20:48:00+00:00",
            "vehicle_soc_age_min": 12,
            "estimate_stop_active": False,
        }
    }

    def test_the_provenance_is_flattened_into_coordinator_data(self):
        from custom_components.solar_energy_management.coordinator.types import SEMData

        data = SEMData(per_charger_intelligence=self.INTEL).to_dict()
        assert data[f"charger_{CID}_vehicle_soc_last"] == 63.0
        assert data[f"charger_{CID}_vehicle_soc_last_at"] == (
            "2026-08-05T20:48:00+00:00"
        )

    def test_the_estimated_soc_sensor_carries_it_as_attributes(self):
        from custom_components.solar_energy_management.coordinator.types import SEMData
        from custom_components.solar_energy_management.sensor import SEMSolarSensor

        coord = MagicMock()
        coord.data = SEMData(per_charger_intelligence=self.INTEL).to_dict()
        sensor = MagicMock()
        sensor.coordinator = coord
        sensor.entity_description = MagicMock()
        sensor.entity_description.key = f"charger_{CID}_estimated_soc"
        attrs = SEMSolarSensor.extra_state_attributes.fget(sensor)

        assert attrs["vehicle_soc_last"] == 63.0
        assert attrs["vehicle_soc_last_at"] == "2026-08-05T20:48:00+00:00"


@pytest.mark.unit
class TestNoSensorConfigured:

    def test_a_charger_with_no_soc_sensor_publishes_no_provenance(self):
        coord = _Coord()
        coord.config = {"ev_chargers": [{"id": CID, "name": "Large Bay EVSE"}]}
        intel = coord.intel()
        assert intel["vehicle_soc_last"] is None
        assert intel["vehicle_soc_last_at"] is None
        assert intel["vehicle_soc_age_min"] is None

    def test_one_chargers_reading_does_not_leak_onto_another(self):
        """The loop body reuses ``soc_state`` across iterations, and the
        memo is keyed by charger. A fleet where one box has a SOC sensor
        and the other does not must not have the first one's reading
        answer for the second — that is the class that produced Fix 1
        (#616 / docs/BUG_CLASSES.md)."""
        other = "small_bay"
        coord = _Coord()
        coord.config = {
            "ev_chargers": [
                {"id": CID, "name": "Large Bay EVSE",
                 "vehicle_soc_entity": SOC_ENTITY},
                {"id": other, "name": "Small Bay EVSE"},
            ],
            "ev_battery_capacity_kwh": 52,
        }
        coord._ev_taper_detectors[other] = EVTaperDetector(
            {"ev_battery_capacity_kwh": 52}
        )
        coord.publish_soc(63, age_min=12)
        intel = coord._build_per_charger_intelligence()

        assert intel[CID]["vehicle_soc_last"] == 63.0
        assert intel[other]["vehicle_soc_last"] is None
        assert intel[other]["vehicle_soc_last_at"] is None

    def test_a_restart_during_an_outage_admits_it_does_not_know(self):
        """No memo and an unavailable sensor: SEM genuinely cannot date the
        last reading. Say nothing rather than invent a fresh-looking age."""
        coord = _Coord()
        coord.break_soc()
        intel = coord.intel()
        assert intel["vehicle_soc_last"] is None
        assert intel["vehicle_soc_age_min"] is None
