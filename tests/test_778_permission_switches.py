"""#778 phase 6 — the two battery permissions, reachable on the dashboard.

The standing rule is that every setting is reachable from the SEM dashboard;
an options-flow-only knob does not count. These are switches rather than a
battery mode for one reason: a mode is single-select and cannot express
"may sell to the grid, may not touch the car".

They persist into the NESTED ``battery_permissions`` dict — the same and only
representation the resolver reads. A flat ``battery_may_export`` option key
would have been simpler to write and would have created a second spelling of
one fact, which is the drift class this arc has been closing all week.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.switch import (
    PERMISSION_SWITCHES,
    SWITCH_TYPES,
    SEMSolarSwitch,
)
from custom_components.solar_energy_management.consts.battery_permissions import (
    effective_permissions,
    may_assist_ev,
    may_export,
)


def _switch(key, *, options=None, mode="auto"):
    coord = MagicMock()
    coord.config = {"battery_mode": mode, **(options or {})}
    entry = MagicMock()
    entry.options = dict(options or {})
    entry.data = {}
    coord.config_entry = entry
    coord.device_info = {}
    desc = next(d for d in SWITCH_TYPES if d.key == key)
    sw = SEMSolarSwitch.__new__(SEMSolarSwitch)
    sw.coordinator = coord
    sw.entity_description = desc
    sw.hass = MagicMock()
    sw.hass.config_entries.async_update_entry = MagicMock()
    return sw, coord, entry


class TestTheSwitchesExist:
    def test_both_permissions_are_switch_entities(self):
        keys = {d.key for d in SWITCH_TYPES}
        assert "battery_may_export" in keys
        assert "battery_may_assist_ev" in keys

    def test_the_map_covers_exactly_the_permission_switches(self):
        """The map is the wiring between a switch key and its permission slot.
        A switch added without a slot would silently persist a flat key."""
        assert PERMISSION_SWITCHES == {
            "battery_may_export": "may_export",
            "battery_may_assist_ev": "may_assist_ev",
        }


class TestPersistence:
    def test_turning_on_writes_the_nested_permission(self):
        sw, coord, entry = _switch("battery_may_export")
        sw._persist_flag(True)
        opts = sw.hass.config_entries.async_update_entry.call_args.kwargs["options"]
        assert opts["battery_permissions"]["may_export"] is True

    def test_turning_off_writes_an_explicit_false(self):
        """Explicit False must be distinguishable from UNSET — that is the
        entire point of the tri-state, and the reason turning a switch off
        cannot simply delete the key."""
        sw, coord, entry = _switch("battery_may_assist_ev")
        sw._persist_flag(False)
        opts = sw.hass.config_entries.async_update_entry.call_args.kwargs["options"]
        assert opts["battery_permissions"]["may_assist_ev"] is False

    def test_writing_one_permission_preserves_the_other(self):
        """Live PROD lesson (21.08): an options merge that drops omitted keys
        silently restores them from the old entry. Two permissions in one dict
        is exactly that shape, so it is pinned here."""
        sw, coord, entry = _switch(
            "battery_may_export",
            options={"battery_permissions": {"may_assist_ev": False}},
        )
        sw._persist_flag(True)
        perms = sw.hass.config_entries.async_update_entry.call_args.kwargs[
            "options"]["battery_permissions"]
        assert perms["may_export"] is True
        assert perms["may_assist_ev"] is False, "the other permission was lost"

    def test_no_flat_key_is_ever_written(self):
        """One representation. A flat key here would be read by nobody and
        would look authoritative to the next person editing options."""
        sw, coord, entry = _switch("battery_may_export")
        sw._persist_flag(True)
        opts = sw.hass.config_entries.async_update_entry.call_args.kwargs["options"]
        assert "battery_may_export" not in opts

    def test_the_running_config_is_updated_in_place(self):
        """Same no-reload contract as every other SEM toggle: the coordinator
        must see the new permission on its very next cycle, not after a
        config-entry reload."""
        sw, coord, entry = _switch("battery_may_export")
        sw._persist_flag(False)
        assert coord.config["battery_permissions"]["may_export"] is False


class TestInitialState:
    """A switch shows the EFFECTIVE permission, so an untouched install shows
    what SEM will actually do — not a misleading off."""

    def test_unset_on_auto_reads_on(self):
        perms = effective_permissions("auto", {})
        assert may_export("auto", perms, True) is True
        assert may_assist_ev("auto", perms) is True

    def test_battery_off_reads_off_for_export(self):
        perms = effective_permissions("off", {})
        assert may_export("off", perms, True) is False

    @pytest.mark.parametrize("stored,expected", [({"may_export": False}, False),
                                                 ({"may_export": True}, True)])
    def test_an_explicit_choice_wins(self, stored, expected):
        perms = effective_permissions("auto", stored)
        assert may_export("auto", perms, True) is expected


class TestSeeding:
    """A switch shows what SEM will ACTUALLY do, not a default-off placeholder.

    Both permissions resolve to True on an untouched install — the battery
    already assists the car and already exports today. Seeding the entity to
    False would show two switches in the off position for behaviour that is
    running, which is worse than not shipping the switches at all: a user who
    flips one "on" to enable something that was never off has been misled
    about their own system.
    """

    def _seeded(self, key, *, options=None, mode="auto"):
        sw, coord, entry = _switch(key, options=options, mode=mode)
        return SEMSolarSwitch._seed_state(sw)

    def test_unset_export_follows_the_global_kill_switch(self):
        """This test asserted True and was WRONG — it encoded the bug it was
        meant to guard. The seed read a misspelled key
        (``battery_arbitrage_enabled``), so the .get default always won and the
        switch displayed ON while the decision path was OFF. The kill switch is
        ``battery_grid_arbitrage_enabled`` and it defaults OFF, so an untouched
        install must show this switch OFF — which is also what
        consts/battery_permissions.py says it wants: "selling someone's battery
        to the grid is not a thing to switch on for them"."""
        assert self._seeded("battery_may_export") is False
        assert self._seeded(
            "battery_may_export",
            options={"battery_grid_arbitrage_enabled": True}) is True

    def test_unset_ev_assist_seeds_on(self):
        """The EV permission is NOT gated by the arbitrage switch — energy into
        the car never leaves the house — so an untouched install shows it on,
        which is what SEM already does today."""
        assert self._seeded("battery_may_assist_ev") is True

    def test_an_explicit_false_seeds_off(self):
        assert self._seeded(
            "battery_may_export",
            options={"battery_permissions": {"may_export": False}},
        ) is False

    def test_battery_off_seeds_export_off(self):
        """SEM is hands-off that battery entirely, so the permission cannot
        read as granted."""
        assert self._seeded("battery_may_export", mode="off") is False

    def test_the_master_switch_seeds_off(self):
        """The arc ships inert; the master switch is the deliberate wake."""
        assert self._seeded("forecast_spending_enabled") is False


class TestTheExportPermissionActuallyGates:
    """The switch must change a decision, not just a stored boolean.

    Caught by ``test_knob_wiring`` — the guard that exists precisely because a
    knob wired to nothing is worse than an absent one: the user flips "Battery
    may sell to the grid" OFF, watches SEM keep selling, and has been told a
    lie by their own dashboard. ``decide_battery`` called
    ``arbitrage_allowed_for_mode(mode, global_arb)`` with no permissions
    argument, so the whole axis was inert on the export side.
    """

    def _view(self, *, permissions, mode="auto"):
        v = MagicMock()
        v.battery_permissions = permissions
        v.battery_mode = mode
        return v

    def test_the_resolver_refuses_when_export_is_forbidden(self):
        from custom_components.solar_energy_management.consts.battery_modes import (
            arbitrage_allowed_for_mode,
        )
        assert arbitrage_allowed_for_mode(
            "auto", True, {"may_export": False}) is False

    def test_the_resolver_allows_when_export_is_granted(self):
        from custom_components.solar_energy_management.consts.battery_modes import (
            arbitrage_allowed_for_mode,
        )
        assert arbitrage_allowed_for_mode(
            "auto", True, {"may_export": True}) is True

    def test_decide_battery_passes_the_permissions_through(self):
        """The seam the guard flagged. Asserted on the source because the
        failure mode is an OMITTED argument — a call that works, returns a
        sensible-looking boolean, and silently ignores the user."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "coordinator" / "decide_battery.py").read_text(encoding="utf-8")
        assert "arbitrage_allowed_for_mode(mode, global_arb)" not in src, (
            "decide_battery still resolves arbitrage without the permission "
            "axis — the 'Battery may sell to the grid' switch would be inert")
        assert "arbitrage_allowed_for_mode(" in src


class TestTheRestoreStoreCannotOverrideAPermission:
    """(#777, one class of switch later) A permission's truth is its dict.

    Caught by reading the LIVE switch after deploying, not by any test: it
    showed ON while the kill switch defaults OFF. ``_apply_restored_state``
    treats every key outside ``_PERSISTED_DEFAULTS`` as restore-first —

        if key not in self._PERSISTED_DEFAULTS:
            if last_state is not None:
                self._is_on = last_state.state == "on"
            return

    — so the restore store overwrote the resolved permission unconditionally,
    and yesterday's misspelled-key bug (which displayed ON) had already written
    ON into that store. The bug would have outlived its own fix.

    A permission cannot be restored, because absence is MEANINGFUL: no entry in
    ``battery_permissions`` means UNSET, which resolves through the legacy rule
    for the mode. A restore ghost has nothing to say about that — it can only
    contradict it. This is the same lesson #777 learned for observer mode: the
    restore store outlives the config entry, so anything whose meaning depends
    on absence must never read it.
    """

    class _Restored:
        def __init__(self, state):
            self.state = state

    def test_a_stale_on_does_not_grant_export(self):
        sw, coord, entry = _switch("battery_may_export")
        sw._is_on = False
        sw._apply_restored_state(self._Restored("on"))
        assert sw._is_on is False, (
            "a ghost in the restore store granted permission to sell the "
            "user's battery to the grid")

    def test_a_stale_off_does_not_revoke_assist(self):
        """Symmetrical: the ghost must not take a permission away either."""
        sw, coord, entry = _switch("battery_may_assist_ev")
        sw._is_on = True
        sw._apply_restored_state(self._Restored("off"))
        assert sw._is_on is True

    def test_an_explicit_choice_still_wins_over_the_ghost(self):
        sw, coord, entry = _switch(
            "battery_may_export",
            options={"battery_permissions": {"may_export": True},
                     "battery_grid_arbitrage_enabled": True})
        sw._apply_restored_state(self._Restored("off"))
        assert sw._is_on is True

    def test_ordinary_switches_still_restore(self):
        """The restore path exists for a reason — a legacy install upgrading
        with no config record. Only permissions opt out of it."""
        sw, coord, entry = _switch("observer_mode")
        sw._is_on = False
        sw._apply_restored_state(self._Restored("on"))
        assert sw._is_on is True
