"""#1238 — a grid import sensor saved alone reads export as 0 W.

The Config card used to save one half of a grid pair. When the Energy
Dashboard has only kWh counters, that half is read alone: export is pinned at
0 W, and a home that sends power to the grid never shows it. Only a log line
said so.

A home that never exports may set the import half alone on purpose, so the
half is not wrong by itself. The export COUNTER decides: when it gains energy
while SEM read no export, power went to the grid that SEM did not see. Then a
Repair says so and names the way out. SEM does not change the user's pick
(whether it may is a product decision). Bug class 84 for the proof: it lives
for one reader lifetime, and the Repair is not persistent.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.coordinator import repair_issues as real_ri
from custom_components.solar_energy_management.coordinator import sensor_reader as sr_mod

from .test_1240_same_entry_is_same_device import Rig, _state, kwh

_ROOT = Path(__file__).resolve().parents[1]
_IMP = "sensor.grid_import_w"
_EXP = "sensor.grid_export_w"
_IN = "sensor.meter_energy_imported"
_OUT = "sensor.meter_energy_exported"
KEY = "half_grid_pair"


class Home:
    """A dashboard with kWh counters only, and a saved import half."""

    def __init__(self, *, half=_IMP, other=None, import_w=800.0, export_kwh=100.0):
        rows = [
            (_IMP, "custom", "k1", "devM", "01JE", _state(import_w, "W")),
            (_EXP, "custom", "k2", "devM", "01JE", _state(0.0, "W")),
            (_IN, "custom", "k3", "devM", "01JE", kwh(500.0)),
            (_OUT, "custom", "k4", "devM", "01JE", kwh(export_kwh)),
        ]
        self.rig = Rig(rows, [_IN], [_OUT])
        self.ri = MagicMock()
        cfg = self.rig.reader._raw_config
        if half:
            cfg["grid_import_power_entity"] = half
        if other:
            cfg["grid_export_power_entity"] = other

    def read(self, *, export_kwh=None, import_w=None):
        if export_kwh is not None:
            self.rig.states[_OUT] = kwh(export_kwh)
        if import_w is not None:
            self.rig.states[_IMP] = _state(import_w, "W")
        with patch.object(sr_mod, "_ri", self.ri):
            with patch.object(sr_mod.er, "async_get", return_value=self.rig.registry), \
                    patch.object(sr_mod, "is_sem_entity", lambda *a, **k: False):
                return self.rig.reader.read_power()


class TestTheExportCounterDecides:
    def test_export_the_half_cannot_see_raises_the_repair(self):
        h = Home()
        h.read()
        h.read(export_kwh=100.5)
        h.ri.raise_half_grid_pair.assert_called_once_with(
            h.rig.reader.hass, import_entity=_IMP, export_entity=_OUT)

    def test_the_grid_still_reads_import_only(self):
        """The pick is the user's: nothing is changed, only said."""
        h = Home()
        h.read()
        power = h.read(export_kwh=105.0)
        assert power.grid_power == pytest.approx(-800.0)

    def test_it_is_said_once(self):
        h = Home()
        h.read()
        for n in range(1, 6):
            h.read(export_kwh=100.0 + n)
        assert h.ri.raise_half_grid_pair.call_count == 1

    def test_a_home_that_never_exports_gets_none(self):
        h = Home()
        for _ in range(10):
            h.read()
        h.ri.raise_half_grid_pair.assert_not_called()

    def test_a_flicker_of_the_counter_is_not_export(self):
        h = Home()
        h.read()
        h.read(export_kwh=100.02)
        h.ri.raise_half_grid_pair.assert_not_called()

    def test_gains_add_up_over_cycles(self):
        h = Home()
        h.read()
        for n in range(1, 7):
            h.read(export_kwh=100.0 + 0.03 * n)
        h.ri.raise_half_grid_pair.assert_called_once()

    def test_a_counter_reset_is_not_export(self):
        h = Home(export_kwh=900.0)
        h.read()
        h.read(export_kwh=0.0)
        h.read(export_kwh=0.02)
        h.ri.raise_half_grid_pair.assert_not_called()

    def test_a_half_that_shows_export_itself_is_not_blind(self):
        """A signed meter saved in the import slot reads export as a
        negative import: SEM does see it."""
        h = Home()
        h.read()
        h.read(export_kwh=101.0, import_w=-1500.0)
        h.ri.raise_half_grid_pair.assert_not_called()


class TestItGoesWhenTheHalfIsNoLongerAlone:
    def test_the_other_half_saved_clears_it(self):
        h = Home()
        h.read()
        h.read(export_kwh=101.0)
        h.rig.reader._raw_config["grid_export_power_entity"] = _EXP
        h.read(export_kwh=102.0)
        h.ri.clear_half_grid_pair.assert_called_once()

    def test_the_half_removed_clears_it(self):
        h = Home()
        h.read()
        h.read(export_kwh=101.0)
        del h.rig.reader._raw_config["grid_import_power_entity"]
        h.read(export_kwh=102.0)
        h.ri.clear_half_grid_pair.assert_called_once()

    def test_nothing_is_cleared_when_nothing_was_raised(self):
        h = Home()
        for _ in range(3):
            h.read()
        h.ri.clear_half_grid_pair.assert_not_called()


class TestOtherHomesAreUnchanged:
    def test_a_whole_manual_pair_raises_nothing(self):
        h = Home(other=_EXP)
        h.read()
        h.read(export_kwh=105.0)
        h.ri.raise_half_grid_pair.assert_not_called()

    def test_a_half_set_aside_for_the_dashboards_sensor_raises_nothing(self):
        """With a dashboard power sensor the half is not read (#1224)."""
        h = Home()
        h.rig.reader._energy_dashboard_config.grid_import_power = _EXP
        h.read()
        h.read(export_kwh=105.0)
        h.ri.raise_half_grid_pair.assert_not_called()

    def test_no_export_counter_means_no_proof(self):
        h = Home()
        h.rig.reader._energy_dashboard_config.grid_export_energy = None
        h.rig.reader._energy_dashboard_config.grid_export_energy_list = []
        h.read()
        h.read(export_kwh=105.0)
        h.ri.raise_half_grid_pair.assert_not_called()


class TestTheRepairItself:
    def test_it_is_filed_with_its_own_text_and_a_docs_step(self, hass):
        real_ri.raise_half_grid_pair(hass, import_entity=_IMP, export_entity=_OUT)
        issue = ir.async_get(hass).async_get_issue(DOMAIN, KEY)
        assert issue is not None
        assert issue.translation_key == KEY
        assert issue.translation_placeholders == {
            "import_entity": _IMP, "export_entity": _OUT}
        assert issue.learn_more_url.endswith("#sem-does-not-see-your-grid-export")
        assert issue.is_persistent is False

    def test_it_can_be_cleared(self, hass):
        real_ri.raise_half_grid_pair(hass, import_entity=_IMP, export_entity=_OUT)
        real_ri.clear_half_grid_pair(hass)
        assert ir.async_get(hass).async_get_issue(DOMAIN, KEY) is None

    def test_its_text_has_the_placeholders_it_is_filed_with(self):
        strings = json.loads((_ROOT / "strings.json").read_text())
        text = strings["issues"][KEY]
        for part in (text["title"], text["description"]):
            assert "{" not in part.replace("{import_entity}", "").replace(
                "{export_entity}", "")
        assert "{import_entity}" in text["description"]
        assert "{export_entity}" in text["description"]
