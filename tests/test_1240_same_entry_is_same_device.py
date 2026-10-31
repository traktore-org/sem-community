"""#1240 — a declared grid pair on the same config entry as the counters is
trusted at once.

DSMR Reader's sensors have no device in Home Assistant. SEM trusts a pair an
integration DECLARES at once only when it sits on the device of the grid
counters. With no device the pair had to match the counters for 15 minutes,
and that check is not saved, so every restart read 0 W grid power for at
least 15 minutes. The power sensors and the counters come from one config
entry, and a row with no device belongs to its entry (the Config card has
said so since #1223). The reader's device test and the card's now share one
answer: ``hardware_detection.registry_unit``. Bug class 90 (an optional
identity), seen from the trust side.

Trust is not widened: a pair on another entry, or on no entry, still has to
match the counters first.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management import hardware_detection as hd
from custom_components.solar_energy_management.coordinator import sensor_reader as sr_mod
from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader


def _state(value, unit="W", device_class="power", state_class="measurement"):
    s = MagicMock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit}
    if device_class:
        s.attributes["device_class"] = device_class
    if state_class:
        s.attributes["state_class"] = state_class
    return s


def kwh(value):
    return _state(value, "kWh", "energy", "total_increasing")


def _ed(imports, exports):
    ed = MagicMock()
    ed.solar_power = None
    ed.solar_power_list = []
    ed.grid_import_power = None
    ed.grid_power_list = []
    ed.grid_power_from = None
    ed.grid_power_to = None
    ed.grid_import_energy = imports[0]
    ed.grid_export_energy = exports[0] if exports else None
    ed.grid_import_energy_list = list(imports)
    ed.grid_export_energy_list = list(exports)
    ed.battery_power = None
    ed.battery_power_list = []
    ed.battery_power_from = None
    ed.battery_power_to = None
    ed.battery_power_inverted = False
    ed.battery_power_pairs = []
    ed.battery_soc = None
    ed.battery_soc_list = []
    ed.battery_charge_energy = None
    ed.battery_discharge_energy = None
    ed.ev_power = None
    ed.has_solar = False
    ed.has_grid = True
    ed.has_battery = False
    ed.has_ev = False
    return ed


def _row(entity_id, platform, key, *, device=None, entry=None):
    e = MagicMock()
    e.entity_id = entity_id
    e.platform = platform
    e.translation_key = key
    e.unique_id = f"{entry or 'x'}-{entity_id.split('.', 1)[1]}"
    e.device_id = device
    e.config_entry_id = entry
    e.disabled_by = None
    return e


class Rig:
    """A fake install: registry rows + states, one reader, the real pipeline.

    ``rows`` is ``[(entity_id, platform, translation_key, device, entry,
    state)]``. The reader's device lookup is the registry's, like HA's."""

    def __init__(self, rows, imports, exports):
        self.states = {r[0]: r[5] for r in rows}
        entries = [_row(r[0], r[1], r[2], device=r[3], entry=r[4]) for r in rows]
        self.registry = MagicMock()
        self.registry.entities = {e.entity_id: e for e in entries}
        self.registry.async_get = lambda eid: self.registry.entities.get(eid)
        hass = MagicMock()
        hass.states.get = lambda eid: self.states.get(eid)

        def _all(domain=None):
            out = []
            for eid, st in self.states.items():
                s = MagicMock()
                s.entity_id = eid
                s.state = st.state
                s.attributes = st.attributes
                if domain is None or eid.startswith(f"{domain}."):
                    out.append(s)
            return out

        hass.states.async_all = _all
        self.reader = SensorReader(hass, {"update_interval": 10})
        self.reader._sign_vote_warmup = 0
        self.reader._energy_dashboard_config = _ed(imports, exports)
        self.reader._get_device_for_entity = (
            lambda eid: getattr(self.registry.entities.get(eid), "device_id", None))

    def read(self):
        with patch.object(sr_mod.er, "async_get", return_value=self.registry), \
                patch.object(sr_mod, "_ri", MagicMock()), \
                patch.object(sr_mod, "is_sem_entity", lambda *a, **k: False):
            return self.reader.read_power()

    @property
    def picks(self):
        d = self.reader._split_grid_discovery
        return d["import"], d["export"], d["confidence"]


_IMP = "sensor.dsmr_reading_electricity_currently_delivered"
_EXP = "sensor.dsmr_reading_electricity_currently_returned"
_IN = "sensor.dsmr_reading_electricity_delivered_1"
_OUT = "sensor.dsmr_reading_electricity_returned_1"


def _dsmr_reader(*, pair_entry, counter_entry, import_kw=1.2, export_kw=0.0):
    """DSMR Reader as HA sets it up: no device on any row."""
    rows = [
        (_IMP, "dsmr_reader", "current_power_usage", None, pair_entry,
         _state(import_kw, "kW")),
        (_EXP, "dsmr_reader", "current_power_return", None, pair_entry,
         _state(export_kw, "kW")),
        (_IN, "dsmr_reader", "low_tariff_usage", None, counter_entry,
         kwh(1234.5)),
        (_OUT, "dsmr_reader", "low_tariff_returned", None, counter_entry,
         kwh(678.9)),
    ]
    return Rig(rows, [_IN], [_OUT])


class TestSameEntryCountsAsSameDevice:
    def test_the_pair_is_trusted_at_once(self):
        rig = _dsmr_reader(pair_entry="01JENTRY", counter_entry="01JENTRY")
        power = rig.read()
        assert rig.picks == (_IMP, _EXP, "declared")
        assert power.grid_power == pytest.approx(-1200.0)

    def test_a_restart_does_not_start_the_check_again(self):
        """The check was never saved; a trusted pair needs none."""
        rig = _dsmr_reader(pair_entry="01JENTRY", counter_entry="01JENTRY")
        rig.read()
        rig.reader.invalidate_split_grid_cache()      # what a restart leaves
        assert rig.read().grid_power == pytest.approx(-1200.0)

    def test_export_reads_at_once_too(self):
        rig = _dsmr_reader(pair_entry="01JENTRY", counter_entry="01JENTRY",
                           import_kw=0.0, export_kw=2.5)
        assert rig.read().grid_power == pytest.approx(2500.0)

    def test_the_reader_and_the_card_give_one_answer(self):
        rows = [_row(_IMP, "dsmr_reader", "current_power_usage", entry="01JE"),
                _row(_IN, "dsmr_reader", "low_tariff_usage", entry="01JE")]
        assert hd.registry_unit(rows[0]) == hd.registry_unit(rows[1])


class TestTrustIsNotWidened:
    def test_another_entry_still_needs_the_check(self):
        rig = _dsmr_reader(pair_entry="01JENTRY", counter_entry="01JOTHER")
        power = rig.read()
        assert rig.picks == (_IMP, _EXP, "declared-elsewhere")
        assert power.grid_power == 0.0            # steers nothing until proven

    def test_no_entry_on_either_side_still_needs_the_check(self):
        rig = _dsmr_reader(pair_entry=None, counter_entry=None)
        assert rig.read().grid_power == 0.0
        assert rig.picks[2] == "declared-elsewhere"

    def test_a_device_never_equals_an_entry(self):
        dev = _row(_IMP, "dsmr_reader", "k", device="dev1", entry="01JE")
        bare = _row(_IN, "dsmr_reader", "k", device=None, entry="01JE")
        assert hd.registry_unit(dev) != hd.registry_unit(bare)

    def test_a_pair_with_one_device_and_one_bare_side_is_not_on_the_meter(self):
        """Affinity is claimed only when every side resolved shares the unit."""
        rows = [
            (_IMP, "dsmr_reader", "current_power_usage", None, "01JE",
             _state(1.2, "kW")),
            (_EXP, "dsmr_reader", "current_power_return", "other-dev", "01JE",
             _state(0.0, "kW")),
            (_IN, "dsmr_reader", "low_tariff_usage", None, "01JE", kwh(1.0)),
            (_OUT, "dsmr_reader", "low_tariff_returned", None, "01JE", kwh(1.0)),
        ]
        rig = Rig(rows, [_IN], [_OUT])
        rig.read()
        assert rig.picks[2] == "declared-elsewhere"
