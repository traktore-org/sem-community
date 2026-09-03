"""#911 — a guessed grid meter is not a measurement, and never a silent one.

@jrx-code (FoxESS, 2.0.0, ~6300 entities): with no grid power entity set,
``_discover_split_grid_power`` adopted a **Nibe heat pump** as the grid IMPORT
meter (it matches the DSMR substring ``power_consumption``) and a
**forecast_solar "+12 h estimated production"** sensor as the EXPORT meter
(``power_production``). SEM then read 10 W of import while the house drew
1466 W. Nothing said so — the pick appears only in the diagnostics download,
and the one visible symptom was a ``sensor_stale`` Repair on the forecast
entity, which stays in the issue registry forever once the pick is gone.

Three closures, in one place:

1. A discovery candidate must be a MEASUREMENT: ``state_class: measurement``.
   Forecast/estimate entities carry none — verified on the reporter's install.
   Forecast-shaped names (``forecast``, ``_next_``, ``estimate``) are excluded
   as a belt over the buckle.
2. An ``any-device`` adoption is a guess, and a guess is said out loud: one
   WARNING naming both picks, and a persistent Repair that tells the user to
   set the two grid power entities. A same-device pair, or an explicit pair,
   clears it.
3. When a pick is dropped, its ``sensor_stale`` Repair is cleared with it —
   never orphaned.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


from .test_split_grid_integration import (
    _make_energy_dashboard_config,
    _make_reader_with_states,
    _state,
)

RI = "custom_components.solar_energy_management.coordinator.sensor_reader._ri"


def _ed():
    return _make_energy_dashboard_config(
        solar_power="sensor.fox_pv_power",
        grid_import_power=None,
        grid_import_energy="sensor.fox_grid_import_energy",
        grid_export_energy="sensor.fox_grid_export_energy",
        battery_power=None,
    )


def _registry(device_of):
    reg = MagicMock()

    def _get(eid):
        e = MagicMock()
        e.device_id = device_of.get(eid)
        e.platform = "forecast_solar" if "power_production_next" in eid else "x"
        return e
    reg.async_get = _get
    return reg


def _reader(states, device_of=None):
    return _make_reader_with_states(MagicMock(), states, _ed()), _registry(device_of or {})


@pytest.mark.unit
class TestAForecastIsNotAMeter:

    def test_an_entity_without_state_class_is_not_a_candidate(self):
        # The reporter's export "meter": device_class power, unit W, no state_class.
        states = {
            "sensor.fox_pv_power": _state(0),
            "sensor.power_production_next_12hours": _state(3200, device_class="power", state_class=None),
            "sensor.fox_grid_import_energy": _state(150, "kWh"),
        }
        reader, reg = _reader(states)
        with patch(f"{RI.rsplit('.', 1)[0]}.er.async_get", return_value=reg):
            imp, exp, conf = reader._discover_split_grid_power(reader._energy_dashboard_config)
        assert exp is None and conf is None

    def test_a_forecast_shaped_name_is_excluded_even_with_a_state_class(self):
        states = {
            "sensor.fox_pv_power": _state(0),
            "sensor.power_production_next_24hours": _state(3200, device_class="power"),
            "sensor.fox_grid_import_energy": _state(150, "kWh"),
        }
        reader, reg = _reader(states)
        with patch(f"{RI.rsplit('.', 1)[0]}.er.async_get", return_value=reg):
            imp, exp, conf = reader._discover_split_grid_power(reader._energy_dashboard_config)
        assert exp is None

    def test_a_real_meter_still_discovers(self):
        states = {
            "sensor.fox_pv_power": _state(0),
            "sensor.p1_power_consumption": _state(1466, device_class="power"),
            "sensor.p1_power_production": _state(0, device_class="power"),
            "sensor.fox_grid_import_energy": _state(150, "kWh"),
        }
        reader, reg = _reader(states, {"sensor.p1_power_consumption": "m", "sensor.p1_power_production": "m",
                                        "sensor.fox_grid_import_energy": "m"})
        with patch(f"{RI.rsplit('.', 1)[0]}.er.async_get", return_value=reg):
            imp, exp, conf = reader._discover_split_grid_power(reader._energy_dashboard_config)
        assert (imp, exp, conf) == ("sensor.p1_power_consumption", "sensor.p1_power_production", "same-device")


@pytest.mark.unit
class TestAGuessIsSaidOutLoud:

    def _states_heat_pump(self):
        return {
            "sensor.fox_pv_power": _state(0),
            "sensor.energy_log_current_power_consumption_32306": _state(10, device_class="power"),
            "sensor.fox_grid_import_energy": _state(150, "kWh"),
            "sensor.fox_grid_export_energy": _state(20, "kWh"),
        }

    def test_an_any_device_adoption_raises_the_repair_and_warns(self, caplog):
        reader, reg = _reader(self._states_heat_pump(), {"sensor.fox_grid_import_energy": "fox"})
        with patch(f"{RI.rsplit('.', 1)[0]}.er.async_get", return_value=reg), \
             patch(RI) as ri:
            reader.read_power()
            assert reader._split_grid_discovery["confidence"] == "any-device"
            ri.raise_split_grid_guessed.assert_called_once()
            kw = ri.raise_split_grid_guessed.call_args.kwargs
            assert kw["import_entity"] == "sensor.energy_log_current_power_consumption_32306"
        assert any("guessed" in r.message.lower() and "any-device" in r.message
                   for r in caplog.records if r.levelname == "WARNING")

    def test_the_repair_is_raised_once_not_every_cycle(self):
        reader, reg = _reader(self._states_heat_pump(), {"sensor.fox_grid_import_energy": "fox"})
        with patch(f"{RI.rsplit('.', 1)[0]}.er.async_get", return_value=reg), \
             patch(RI) as ri:
            for _ in range(5):
                reader.read_power()
            assert ri.raise_split_grid_guessed.call_count == 1

    def test_a_same_device_pair_raises_nothing_and_clears(self):
        states = {
            "sensor.fox_pv_power": _state(0),
            "sensor.p1_power_consumption": _state(1466, device_class="power"),
            "sensor.p1_power_production": _state(0, device_class="power"),
            "sensor.fox_grid_import_energy": _state(150, "kWh"),
        }
        reader, reg = _reader(states, {"sensor.p1_power_consumption": "m", "sensor.p1_power_production": "m",
                                        "sensor.fox_grid_import_energy": "m"})
        with patch(f"{RI.rsplit('.', 1)[0]}.er.async_get", return_value=reg), \
             patch(RI) as ri:
            reader.read_power()
            ri.raise_split_grid_guessed.assert_not_called()
            ri.clear_split_grid_guessed.assert_called()

    def test_a_dropped_pick_takes_its_stale_repair_with_it(self):
        reader, reg = _reader(self._states_heat_pump(), {"sensor.fox_grid_import_energy": "fox"})
        with patch(f"{RI.rsplit('.', 1)[0]}.er.async_get", return_value=reg), \
             patch(RI) as ri:
            reader.read_power()
            # The user sets the meters explicitly: the guess is gone, and so
            # must be any stale Repair filed against it.
            reader.invalidate_split_grid_cache()
            ri.clear_sensor_stale.assert_any_call(
                reader.hass, "sensor.energy_log_current_power_consumption_32306")
            ri.clear_split_grid_guessed.assert_called()


@pytest.mark.unit
class TestTheRepairHasANextStep:
    def test_docs_anchor_exists(self):
        from custom_components.solar_energy_management.coordinator.repair_issues import (
            _DOCS_ANCHORS,
        )
        assert "split_grid_guessed" in _DOCS_ANCHORS
