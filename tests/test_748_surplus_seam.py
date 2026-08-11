"""#748 seam — the charger-duplicate fold must reach the SURPLUS controller.

#748 closed the fold at the display layer (#700's ``get_devices_for_sensor``)
and at the LoadManagement data layer (``_sync_to_load_manager`` +
``_prune_charger_duplicate_lm_rows``). But the registry syncs to **two**
systems, and the second one — ``SurplusController`` — has no charger-identity
fold anywhere in ``_sync_to_surplus_controller``.

That matters twice over:

* the daytime surplus loop drives every device in ``get_devices_sorted()``, so
  a duplicate row whose control entity is the charger's start/stop switch lets
  load management reach for the charger behind the EV controller's back —
  the exact hazard flagged to @jappish84 on #628; and
* the #638 overnight planner packs its load demands from the same roster, so
  the one physical charger can be planned twice — once as ``ev:<cid>``, once
  as ``load:energy_dashboard_*`` — double-booking its energy in the night
  ledger.

BUG_CLASSES class 12 again, and the same shape as the bug #748 fixed: the fold
was applied where the row is *read* rather than where it is *registered*.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDevice,
    UnifiedDeviceRegistry,
)


# The one physical charger, as configured by the reporter on #628.
CHARGER_ROW = {
    "id": "ev_charger",
    "name": "Ny laddare 1",
    "power_entity": "sensor.garo_laddbox_power",
    "current_entity": "number.garo_laddbox_current_limit",
    "start_stop_entity": "switch.garo_laddbox",
    "control_entity": "number.garo_laddbox_current_limit",
}


class _FakeLoadManager:
    def __init__(self):
        self._devices = {}
        self._save_device_configuration = AsyncMock()


def _billaddare() -> UnifiedDevice:
    """The ED individual device manually mapped to the charger's stop switch.

    Its own power/energy sensors are NOT charger entities — which is exactly
    why #700's power-only identity set missed it. Only its *control* entity
    gives it away.
    """
    return UnifiedDevice(
        energy_sensor="sensor.garo_laddbox_session",
        power_sensor=None,
        name="Billaddare",
        priority=5,
        control={"type": "switch", "entity": "switch.garo_laddbox"},
        has_manual_mapping=True,
    )


def _dishwasher() -> UnifiedDevice:
    return UnifiedDevice(
        energy_sensor="sensor.dishwasher_energy",
        power_sensor="sensor.dishwasher_power",
        name="Dishwasher",
        priority=6,
        control={"type": "switch", "entity": "switch.dishwasher"},
    )


def _reg(surplus, ed_devices, charger_rows=None):
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    r = UnifiedDeviceRegistry(hass, surplus, _FakeLoadManager(), MagicMock())
    r._has_battery = False
    r._devices = list(ed_devices)
    # Direct-string identity only; the registry-device fallback needs a real
    # entity registry and can only ever ADD matches (same choice as #748's
    # own tests).
    r._same_registry_device_as_charger = lambda e: False
    r.set_ev_chargers([CHARGER_ROW] if charger_rows is None else charger_rows)
    return r


@pytest.mark.unit
class TestSurplusControllerFold:
    def test_charger_duplicate_is_not_registered(self):
        """An ED row controlling the charger's stop switch must never become a
        surplus device — that switch belongs to the EV controller."""
        sc = SurplusController(MagicMock())
        dup = _billaddare()
        _reg(sc, [dup, _dishwasher()])._sync_to_surplus_controller()
        assert dup.device_id not in sc._devices
        assert "energy_dashboard_dishwasher" in sc._devices

    def test_stale_duplicate_is_dropped_on_resync(self):
        """A duplicate registered BEFORE the charger was configured (the
        reporter's order of operations) must disappear on the next sync, not
        merely stop being re-added."""
        sc = SurplusController(MagicMock())
        dup = _billaddare()
        # Registered while no charger existed…
        _reg(sc, [dup], charger_rows=[])._sync_to_surplus_controller()
        assert dup.device_id in sc._devices
        # …then the user configures the charger.
        _reg(sc, [dup])._sync_to_surplus_controller()
        assert dup.device_id not in sc._devices

    def test_no_chargers_configured_folds_nothing(self):
        sc = SurplusController(MagicMock())
        dup = _billaddare()
        _reg(sc, [dup], charger_rows=[])._sync_to_surplus_controller()
        assert dup.device_id in sc._devices


@pytest.mark.unit
class TestStartupWindow:
    """The registry syncs at ``async_initialize``, but the charger roster is
    handed over by the coordinator's own cycle — so on the first sync after a
    restart there are no chargers yet and the fold has nothing to match. The
    duplicate would then be live and controllable until the 35 s re-discovery.

    Closing it at the moment the fact becomes KNOWN — the roster arriving —
    is the whole fix: ``set_ev_chargers`` is where SEM first learns which
    entities belong to a charger."""

    def test_roster_arriving_drops_an_already_registered_duplicate(self):
        sc = SurplusController(MagicMock())
        dup = _billaddare()
        # Startup: no chargers known yet → the duplicate registers.
        reg = _reg(sc, [dup], charger_rows=[])
        reg._sync_to_surplus_controller()
        assert dup.device_id in sc._devices
        # First coordinator cycle hands over the charger roster.
        reg.set_ev_chargers([CHARGER_ROW])
        assert dup.device_id not in sc._devices

    def test_unrelated_device_survives_the_roster_arriving(self):
        sc = SurplusController(MagicMock())
        dish = _dishwasher()
        reg = _reg(sc, [dish], charger_rows=[])
        reg._sync_to_surplus_controller()
        reg.set_ev_chargers([CHARGER_ROW])
        assert dish.device_id in sc._devices

    def test_same_roster_every_cycle_is_a_no_op(self):
        """``set_ev_chargers`` is called EVERY 10 s cycle. It must not rescan
        the surplus roster 8640 times a day for a roster that never changed."""
        sc = SurplusController(MagicMock())
        reg = _reg(sc, [_dishwasher()], charger_rows=[])
        reg._sync_to_surplus_controller()
        reg.set_ev_chargers([CHARGER_ROW])
        sc.unregister_device = MagicMock()
        for _ in range(5):
            reg.set_ev_chargers([CHARGER_ROW])
        sc.unregister_device.assert_not_called()


@pytest.mark.unit
class TestPlannerRoster:
    """The #638 planner packs ``get_devices_sorted()``. Whatever survives the
    fold above is what it sees — assert at that surface, because that is the
    one the planner actually reads."""

    def test_planner_roster_carries_no_charger_duplicate(self):
        sc = SurplusController(MagicMock())
        dup = _billaddare()
        _reg(sc, [dup, _dishwasher()])._sync_to_surplus_controller()
        ids = {d.device_id for d in sc.get_devices_sorted()}
        assert dup.device_id not in ids
        assert "energy_dashboard_dishwasher" in ids
