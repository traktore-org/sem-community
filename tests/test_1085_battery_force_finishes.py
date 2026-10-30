"""#1085 — a one-off battery ``force`` ends like Force charge does (#1131,
#1164): at the target SOC, then the override is cleared. Before, the finish
check read only the user's mode, so a forced battery charged (and bought
grid power) until the override ran out."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.consts.core import (
    BATTERY_SOC_STEP_CONFIRM_READS as READS,
)
from custom_components.solar_energy_management.coordinator import plan_override as po
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryRuntime,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _coord(action, user_mode="auto"):
    now = dt_util.now()
    c = MagicMock()
    c.config_entry = SimpleNamespace()
    c.battery_control_slugs = ()
    c._manual_done_streaks = {}
    c._manual_charge_stalls = {}
    c._battery_adapters = {}
    c._observer_mode = True
    c._storage = MagicMock()
    c._plan_overrides = po.set_override(
        {}, "primary", action, now + timedelta(hours=4), now)
    c._per_battery_config = lambda i, n=1: {"battery_mode": user_mode}
    c._charge_end_soc = lambda cfg: None
    return c


def _cycles(c, soc, reads):
    items = [("primary", BatteryRuntime(battery_id="primary", last_known_soc=soc))]
    for _ in range(reads):
        SEMCoordinator._finish_manual_battery_modes(c, items, {"primary": True}, 1)


def test_a_forced_battery_that_is_not_full_keeps_its_override():
    c = _coord("force")
    _cycles(c, 80.0, READS + 2)
    assert "primary" in c._plan_overrides


def test_a_forced_battery_at_100_ends_the_override_after_a_few_reads():
    c = _coord("force")
    _cycles(c, 100.0, READS - 1)
    assert "primary" in c._plan_overrides, "one blink must not end it"
    _cycles(c, 100.0, 1)
    assert "primary" not in c._plan_overrides
    c._storage.set_plan_overrides.assert_called()


def test_a_skip_override_is_not_ended_by_a_full_battery():
    c = _coord("skip")
    _cycles(c, 100.0, READS + 2)
    assert "primary" in c._plan_overrides


def test_a_battery_the_user_turned_off_is_never_forced_or_finished_by_it():
    c = _coord("force", user_mode="off")
    _cycles(c, 100.0, READS + 2)
    assert "primary" in c._plan_overrides
