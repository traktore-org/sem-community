"""#778 — mode is posture, permission is permission, and nobody's setup changes.

The design argument (Guido, 23.08): the mode enum mixed posture, a permission
and two manual commands, and being single-select it could not express
"self-consumption posture AND allowed to sell". Adding a sixth value for the
second sink would not have composed with the first.

The bar this file holds is the migration one: **an existing install must
behave identically until its owner changes something.** A refactor that
silently starts or stops selling someone's battery is worse than the wart it
replaces.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.consts.battery_permissions import (
    PERMISSION_KEYS,
    effective_permissions,
    may_assist_ev,
    may_export,
    migrate_mode,
)


@pytest.mark.unit
class TestNobodysSetupChanges:

    def test_auto_still_follows_the_global_switch(self):
        """The regression SEM's own #523 tests caught. `auto` has always
        followed the global toggle; a permission defaulting to False would
        have silently stopped selling for every install on `auto`. UNSET means
        "no opinion — keep the legacy rule", which is why this is tri-state."""
        assert may_export("auto", None, global_enabled=True) is True
        assert may_export("auto", None, global_enabled=False) is False

    def test_ev_assist_stays_on_when_unset(self):
        """The battery already helps the car today when the #537 surplus gate
        passes. Defaulting this off would silently remove a working feature."""
        assert may_assist_ev("auto", None) is True

    def test_legacy_allow_arbitrage_keeps_selling(self):
        mode, overrides = migrate_mode("allow_arbitrage")
        assert mode == "auto"
        assert overrides["may_export"] is True
        assert may_export(mode, overrides, global_enabled=True) is True

    def test_legacy_self_consumption_keeps_never_selling(self):
        mode, overrides = migrate_mode("self_consumption")
        assert mode == "self_consumption"
        assert may_export(mode, overrides, global_enabled=True) is False

    def test_an_unknown_legacy_value_does_not_error(self):
        """v1.7.3 kept the retired value recognised rather than rejected; the
        same care applies to anything else a config might hold."""
        mode, overrides = migrate_mode("something_unexpected")
        assert mode == "something_unexpected"
        assert isinstance(overrides, dict)


@pytest.mark.unit
class TestTheCombinationThatWasImpossibleBefore:

    def test_self_consumption_posture_may_now_be_permitted_to_sell(self):
        """The exact case the enum could not express."""
        assert may_export("self_consumption", {"may_export": True},
                          global_enabled=True) is True

    def test_and_may_still_be_forbidden(self):
        assert may_export("self_consumption", {"may_export": False},
                          global_enabled=True) is False

    def test_both_permissions_compose(self):
        perms = {"may_export": True, "may_assist_ev": True}
        assert may_export("auto", perms, global_enabled=True) is True
        assert may_assist_ev("auto", perms) is True

    def test_the_control_gap_is_now_expressible(self):
        """'The house may use my battery, the car may not' — impossible to say
        before, because the only lever was a surplus threshold."""
        perms = {"may_assist_ev": False}
        assert may_assist_ev("auto", perms) is False


@pytest.mark.unit
class TestTheHardGatesStillHold:

    def test_off_means_off_for_everything(self):
        """`off` is SEM being hands-off this battery entirely."""
        perms = {"may_export": True, "may_assist_ev": True}
        assert may_export("off", perms, global_enabled=True) is False
        assert may_assist_ev("off", perms) is False

    def test_the_global_kill_switch_still_governs_selling(self):
        assert may_export("auto", {"may_export": True},
                          global_enabled=False) is False

    def test_the_kill_switch_does_not_govern_the_car(self):
        """Energy going into the car never leaves the house, so the
        grid-arbitrage switch has no business gating it."""
        assert may_assist_ev("auto", {"may_assist_ev": True}) is True


@pytest.mark.unit
class TestEffectivePermissions:

    def test_a_users_explicit_choice_beats_the_migration(self):
        """Someone who has already set the permission is not overruled by what
        their legacy mode used to imply."""
        eff = effective_permissions("allow_arbitrage", {"may_export": False})
        assert eff["may_export"] is False

    def test_migration_fills_only_what_is_unset(self):
        eff = effective_permissions("allow_arbitrage", {})
        assert eff["may_export"] is True

    def test_an_untouched_install_has_no_opinions(self):
        """Every permission UNSET — so every resolver falls back to the legacy
        behaviour and nothing about the install changes."""
        eff = effective_permissions("auto", None)
        assert set(eff) == set(PERMISSION_KEYS)
        assert all(v is None for v in eff.values())
