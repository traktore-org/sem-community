"""#1341 — a load can be given its own name in SEM.

A load's name came from the Energy dashboard (then the sensor, then the
entity id) and was read at startup only: there was no way to name a load in
SEM. The name the user types is a goal like the comfort band — saved through
``update_device_config``, stored with the goals, applied by the registry. It
is for display only: the id, the settings and the running device stay as
they are.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    LOAD_NAME_MAX,
    UnifiedDeviceRegistry,
    clean_load_name,
)

from .test_744_light_import_filter import LIGHT_ENTRIES, _registry

BOILER = "energy_dashboard_boiler"
ROWS = [{"energy_sensor": "sensor.boiler_energy", "power_sensor": None,
         "name": "Boiler", "is_ev": False}]


def _reg(monkeypatch, goals=None):
    """A registry with one switchable Energy-dashboard load, the boiler."""
    reg, lm = _registry(monkeypatch, ROWS, LIGHT_ENTRIES)
    reg._discovery.discover_control_for_energy_device = MagicMock(
        return_value={"type": "switch", "entity": "switch.boiler",
                      "discovery_method": "same_device"})
    if goals:
        reg._device_goals[BOILER] = dict(goals)
    return reg, lm


def _names(reg, lm):
    live = reg._surplus_controller.get_device(BOILER)
    return ([d.name for d in reg.devices], live.name,
            lm._devices[BOILER]["friendly_name"])


@pytest.mark.unit
class TestTheNameIsCleaned:
    @pytest.mark.parametrize("typed, stored", [
        ("  Pool pump  ", "Pool pump"),
        ("Pool\n\tpump", "Pool pump"),
        ("Pool\x00pump", "Pool pump"),
        ("", ""), ("   ", ""), (None, ""),
        (42, "42"),
    ])
    def test_one_line_of_plain_text(self, typed, stored):
        assert clean_load_name(typed) == stored

    def test_a_long_name_is_cut(self):
        assert clean_load_name("x" * 200) == "x" * LOAD_NAME_MAX
        assert len(clean_load_name("ab " * 100)) <= LOAD_NAME_MAX

    def test_markup_stays_text(self):
        """Nothing is interpreted: the card shows it as text."""
        assert clean_load_name("<b>Pool</b>") == "<b>Pool</b>"


@pytest.mark.unit
class TestTheOwnNameWins:
    async def test_without_a_name_the_energy_dashboard_names_it(self, monkeypatch):
        reg, lm = _reg(monkeypatch)
        await reg.async_refresh_devices()
        assert _names(reg, lm) == (["Boiler"], "Boiler", "Boiler")

    async def test_a_stored_name_is_there_after_a_restart(self, monkeypatch):
        """The goals come back from storage before the first refresh."""
        reg, lm = _reg(monkeypatch, {"name": "Pool pump"})
        await reg.async_refresh_devices()
        assert _names(reg, lm) == (["Pool pump"], "Pool pump", "Pool pump")

    async def test_the_re_discovery_keeps_it(self, monkeypatch):
        reg, lm = _reg(monkeypatch, {"name": "Pool pump"})
        await reg.async_refresh_devices()
        await reg.async_refresh_devices()
        assert _names(reg, lm) == (["Pool pump"], "Pool pump", "Pool pump")
        assert reg.automatic_name(BOILER) == "Boiler"

    async def test_typing_a_name_renames_every_row_at_once(self, monkeypatch):
        reg, lm = _reg(monkeypatch)
        await reg.async_refresh_devices()
        await reg.async_update_device_goal(BOILER, "name", "  Pool   pump ")
        assert _names(reg, lm) == (["Pool pump"], "Pool pump", "Pool pump")
        assert reg._device_goals[BOILER]["name"] == "Pool pump"
        reg._save_storage.assert_awaited()

    async def test_clearing_it_brings_the_automatic_name_back(self, monkeypatch):
        reg, lm = _reg(monkeypatch, {"name": "Pool pump"})
        await reg.async_refresh_devices()
        await reg.async_update_device_goal(BOILER, "name", "")
        assert _names(reg, lm) == (["Boiler"], "Boiler", "Boiler")
        await reg.async_refresh_devices()
        assert _names(reg, lm) == (["Boiler"], "Boiler", "Boiler")


@pytest.mark.unit
class TestOnlyTheNameChanges:
    async def test_the_id_the_settings_and_the_running_device_stay(self, monkeypatch):
        reg, lm = _reg(monkeypatch, {"daily_min_runtime_min": 45,
                                     "top_up_policy": "cheap_hours"})
        await reg.async_refresh_devices()
        live = reg._surplus_controller.get_device(BOILER)
        row = lm._devices[BOILER]
        before = (live.device_id, live.daily_min_runtime_sec, live.top_up_policy,
                  live.entity_id, live.priority, row["energy_entity"])

        await reg.async_update_device_goal(BOILER, "name", "Pool pump")

        assert reg._surplus_controller.get_device(BOILER) is live, "it was rebuilt"
        assert lm._devices[BOILER] is row
        assert [d.device_id for d in reg.devices] == [BOILER]
        assert (live.device_id, live.daily_min_runtime_sec, live.top_up_policy,
                live.entity_id, live.priority, row["energy_entity"]) == before
        assert reg._device_goals[BOILER]["daily_min_runtime_min"] == 45

    async def test_another_goal_does_not_touch_the_name(self, monkeypatch):
        reg, lm = _reg(monkeypatch, {"name": "Pool pump"})
        await reg.async_refresh_devices()
        await reg.async_update_device_goal(BOILER, "daily_min_runtime_min", 30)
        assert _names(reg, lm) == (["Pool pump"], "Pool pump", "Pool pump")

    def test_the_name_is_a_goal_not_an_option(self):
        assert "name" in UnifiedDeviceRegistry.GOAL_PROPERTIES


@pytest.mark.unit
class TestALoadThatIsNotFromTheEnergyDashboard:
    """The boiler and the heat pump of the Configuration tab, and a load a
    service registered, are named by ``_apply_goals`` on the live device."""

    def _reg(self, goals):
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._device_goals = {"hot_water": dict(goals)}
        reg._auto_names = {}
        return reg

    def _tank(self):
        return SimpleNamespace(device_id="hot_water", name="Hot water")

    def test_it_takes_the_own_name(self):
        reg, tank = self._reg({"name": "Boiler cellar"}), self._tank()
        reg._apply_goals(tank)
        assert tank.name == "Boiler cellar"
        assert reg.automatic_name("hot_water") == "Hot water"

    def test_a_rebuilt_device_takes_it_again(self):
        reg = self._reg({"name": "Boiler cellar"})
        reg._apply_goals(self._tank())
        again = self._tank()
        reg._apply_goals(again)
        assert again.name == "Boiler cellar"

    def test_cleared_it_reads_its_automatic_name(self):
        reg, tank = self._reg({"name": "Boiler cellar"}), self._tank()
        reg._apply_goals(tank)
        reg._device_goals["hot_water"]["name"] = ""
        reg._apply_goals(tank)
        assert tank.name == "Hot water"

    def test_no_name_goal_leaves_the_name_alone(self):
        reg, tank = self._reg({"daily_min_runtime_min": 10}), self._tank()
        reg._apply_goals(tank)
        assert tank.name == "Hot water"


@pytest.mark.unit
class TestTheEditorReadsBothNames:
    async def test_the_payload_carries_the_own_and_the_automatic_name(self, monkeypatch):
        reg, _ = _reg(monkeypatch, {"name": "Pool pump"})
        await reg.async_refresh_devices()
        goals = reg._goal_payload(BOILER)["goals"]
        assert goals["name"] == "Pool pump"
        assert goals["automatic_name"] == "Boiler"

    async def test_without_an_own_name_the_field_is_empty(self, monkeypatch):
        reg, _ = _reg(monkeypatch)
        await reg.async_refresh_devices()
        goals = reg._goal_payload(BOILER)["goals"]
        assert goals["name"] == "" and goals["automatic_name"] == "Boiler"


@pytest.mark.unit
class TestTheServiceTakesIt:
    def test_update_device_config_routes_the_name_to_the_goal_store(self):
        """Both service lists name the property: the handler's routing tuple
        and the schema's allowed values."""
        import ast
        from pathlib import Path

        tree = ast.parse((Path(__file__).resolve().parent.parent
                          / "__init__.py").read_text(encoding="utf-8"))
        holders = [n for n in ast.walk(tree)
                   if isinstance(n, (ast.Tuple, ast.List))
                   and {"hvac_mode", "behind_operator_relay"} <= {
                       getattr(e, "value", None) for e in n.elts}]
        assert len(holders) >= 2
        assert all("name" in {getattr(e, "value", None) for e in h.elts}
                   for h in holders)
