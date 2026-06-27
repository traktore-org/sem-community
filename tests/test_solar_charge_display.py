"""Cosmetic per-charger display: 'ready' not 'charging' when a commanded
car isn't actually drawing (power-based, debounced) — the 'offers 9A to a
satisfied car' observation. Pure helper test."""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.decide import (
    solar_charge_display_override,
)
from custom_components.solar_energy_management.coordinator.charger_types import ChargerIntent
from custom_components.solar_energy_management.consts.states import ChargingState


def test_drawing_keeps_normal_charging_display():
    assert solar_charge_display_override(ChargerIntent.CHARGE_AT_AMPS, drawing=True,
                                         no_draw_elapsed_s=999) is None
    assert solar_charge_display_override(ChargerIntent.CHARGE_MAX, drawing=True,
                                         no_draw_elapsed_s=999) is None


def test_not_drawing_within_grace_keeps_charging_display():
    # ramp-up lag: a car can take 30-60 s to start; don't flip to idle yet
    assert solar_charge_display_override(ChargerIntent.CHARGE_AT_AMPS, drawing=False,
                                         no_draw_elapsed_s=30, grace_s=90) is None


def test_not_drawing_past_grace_shows_ready():
    assert solar_charge_display_override(ChargerIntent.CHARGE_AT_AMPS, drawing=False,
                                         no_draw_elapsed_s=120, grace_s=90) == ChargingState.SOLAR_IDLE
    assert solar_charge_display_override(ChargerIntent.CHARGE_MAX, drawing=False,
                                         no_draw_elapsed_s=120, grace_s=90) == ChargingState.SOLAR_IDLE


def test_non_charge_intents_never_override():
    for it in (ChargerIntent.IDLE, ChargerIntent.DISABLE):
        assert solar_charge_display_override(it, drawing=False, no_draw_elapsed_s=999) is None
