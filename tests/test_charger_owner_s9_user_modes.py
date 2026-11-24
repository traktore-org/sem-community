"""(#1381 charger owner S9) Four modes the user sees, one stored strategy.

The user picks Sun, Sun + tariff, Now or Off, plus one switch: "May the
battery help the car?". The pair maps onto exactly one of the six stored
strategies the engine has always run, so an install reads the same strategy
before and after the update — every stored value round-trips unchanged.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management import _merge_ev_chargers_by_id
from custom_components.solar_energy_management.consts.ev_charge_modes import (
    BATTERY_HELP_KEY,
    DEFAULT_EV_CHARGE_MODE,
    EV_CHARGE_MODES,
    USER_MODES,
    apply_user_mode_write,
    battery_help_of,
    effective_charge_mode_for,
    strategy_for,
    user_mode_of,
)

SUN_STRATEGIES = ("solar_only", "solar_plus_battery", "solar_plus_cheap", "min_plus_solar")


@pytest.mark.parametrize("stored", sorted(EV_CHARGE_MODES))
def test_every_stored_strategy_round_trips_through_the_user_pair(stored):
    """Neutral by construction: the mode and the switch the user sees for a
    stored strategy map back to that same strategy."""
    cfg = {"charge_mode": stored}
    assert strategy_for(user_mode_of(stored), battery_help_of(cfg)) == stored


def test_the_four_modes_and_their_strategies():
    assert list(USER_MODES) == ["sun", "sun_tariff", "now", "off"]
    assert strategy_for("sun", False) == "solar_only"
    assert strategy_for("sun", True) == "solar_plus_battery"
    assert strategy_for("sun_tariff", False) == "solar_plus_cheap"
    assert strategy_for("sun_tariff", True) == "min_plus_solar"
    assert strategy_for("now", True) == "always_max"
    assert strategy_for("off", False) == "off"


def test_min_plus_solar_is_sun_tariff_with_battery_help():
    """Owner's rule: Min + Solar users become Sun + tariff and keep the
    day Min floor — the same stored strategy, so the same commands."""
    cfg = {"charge_mode": "min_plus_solar"}
    assert user_mode_of("min_plus_solar") == "sun_tariff"
    assert battery_help_of(cfg) is True


def test_battery_help_default_comes_from_the_current_mode():
    """Owner's rule: nothing changes — the switch reads what the stored
    strategy already did."""
    assert battery_help_of({"charge_mode": "solar_only"}) is False
    assert battery_help_of({"charge_mode": "solar_plus_battery"}) is True
    assert battery_help_of({"charge_mode": "solar_plus_cheap"}) is False
    assert battery_help_of({"charge_mode": "min_plus_solar"}) is True
    # an unset charger is the install default: Sun + tariff with help
    assert battery_help_of({}) is True
    assert user_mode_of(None) == user_mode_of(DEFAULT_EV_CHARGE_MODE) == "sun_tariff"


def test_a_per_charger_never_shows_the_switch_off():
    """(#885) A charger the battery may never help shows help off."""
    assert battery_help_of({"charge_mode": "min_plus_solar",
                            "ev_battery_may_assist": False}) is False


def test_picking_a_mode_keeps_the_charger_s_help():
    c = {"charge_mode": "min_plus_solar"}
    apply_user_mode_write(c, "charge_mode", "sun")
    assert c["charge_mode"] == "solar_plus_battery"
    apply_user_mode_write(c, "charge_mode", "sun_tariff")
    assert c["charge_mode"] == "min_plus_solar"


def test_now_and_off_remember_the_help_switch():
    c = {"charge_mode": "solar_plus_cheap"}
    apply_user_mode_write(c, "charge_mode", "off")
    assert c["charge_mode"] == "off" and c[BATTERY_HELP_KEY] is False
    apply_user_mode_write(c, "charge_mode", "sun_tariff")
    assert c["charge_mode"] == "solar_plus_cheap"
    c = {"charge_mode": "min_plus_solar"}
    apply_user_mode_write(c, "charge_mode", "now")
    assert c["charge_mode"] == "always_max" and c[BATTERY_HELP_KEY] is True
    apply_user_mode_write(c, "charge_mode", "sun")
    assert c["charge_mode"] == "solar_plus_battery"


def test_the_switch_moves_the_strategy_within_the_mode():
    c = {"charge_mode": "solar_only"}
    apply_user_mode_write(c, BATTERY_HELP_KEY, True)
    assert c["charge_mode"] == "solar_plus_battery"
    apply_user_mode_write(c, BATTERY_HELP_KEY, False)
    assert c["charge_mode"] == "solar_only"
    c = {"charge_mode": "solar_plus_cheap"}
    apply_user_mode_write(c, BATTERY_HELP_KEY, True)
    assert c["charge_mode"] == "min_plus_solar"
    # Now and Off: remembered only, the strategy stays
    c = {"charge_mode": "always_max"}
    apply_user_mode_write(c, BATTERY_HELP_KEY, False)
    assert c["charge_mode"] == "always_max" and c[BATTERY_HELP_KEY] is False


def test_turning_help_on_lifts_a_per_charger_never():
    c = {"charge_mode": "solar_only", "ev_battery_may_assist": False}
    apply_user_mode_write(c, BATTERY_HELP_KEY, True)
    assert c["ev_battery_may_assist"] is True
    assert c["charge_mode"] == "solar_plus_battery"


@pytest.mark.parametrize("old", sorted(EV_CHARGE_MODES))
def test_old_names_are_aliases_stored_as_they_are(old):
    """Automations that still write the six old names keep working."""
    c = {"charge_mode": "solar_only"}
    apply_user_mode_write(c, "charge_mode", old)
    assert c["charge_mode"] == old


def test_a_user_mode_written_by_hand_resolves_to_its_strategy():
    cfg = {"charge_mode": "sun_tariff", BATTERY_HELP_KEY: False}
    assert effective_charge_mode_for(None, {}, cfg) == "solar_plus_cheap"
    cfg = {"charge_mode": "sun"}
    assert effective_charge_mode_for(None, {}, cfg) == "solar_plus_battery"


def test_set_option_merge_maps_a_user_mode_from_the_stored_state():
    existing = [{"id": "a", "charge_mode": "min_plus_solar"},
                {"id": "b", "charge_mode": "solar_only"}]
    out = _merge_ev_chargers_by_id(existing, [{"id": "a", "charge_mode": "sun"}])
    assert out[0]["charge_mode"] == "solar_plus_battery"
    assert out[1]["charge_mode"] == "solar_only"
    out = _merge_ev_chargers_by_id(existing, [{"id": "b", BATTERY_HELP_KEY: True}])
    assert out[1]["charge_mode"] == "solar_plus_battery"


@pytest.mark.parametrize("stored", SUN_STRATEGIES)
def test_the_help_switch_flipped_twice_restores_the_strategy(stored):
    c = {"charge_mode": stored}
    help0 = battery_help_of(c)
    apply_user_mode_write(c, BATTERY_HELP_KEY, not help0)
    apply_user_mode_write(c, BATTERY_HELP_KEY, help0)
    assert c["charge_mode"] == stored
