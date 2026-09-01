"""#885 matrix — the restored "Solar + battery" charge mode.

Guido, 01.09: *"there should be two: one is cheap and the other one is about
battery assistant."* The battery one is this mode — the legacy ``pv`` /
``self_consumption`` split the #277 consolidation collapsed. Since #277 the
ONLY way to let the pack help the car was ``min_plus_solar``, which also
commits the user to a Min floor and grid backfill; loads kept the distinction
(#620) and chargers lost it.

Design decisions pinned here (posted to #885 with the matrix):
1. ``min_plus_solar`` KEEPS its assist — the new mode is purely additive.
2. ``solar_plus_battery`` is a DAY mode; night = ``solar_only``'s contract
   verbatim (never grids, #346; At-least floor is the only exception, #679).
3. Prerequisite rule, one rule two severities: a mode that CANNOT function is
   disabled in the UI (cheap without a tariff); one that functions PARTIALLY
   informs instead (this mode before the learner graduates).
"""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.solar_energy_management.consts.ev_charge_modes import (
    EV_CHARGE_MODES,
    MODE_NIGHT_ALLOWED,
    MODE_TO_LEGACY_CHARGING_MODE,
    MODE_USES_SMART_NIGHT,
    MODE_USES_TARIFF,
    mode_allows_night_charging,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import (
    MODE_STRATEGIES,
    decide,
)

ROOT = Path(__file__).resolve().parent.parent


def _view(mode="solar_plus_battery", *, connected=True, solar_w=6000.0,
          home_w=500.0, battery_soc=95.0, is_night=False, target_kwh=None,
          night_deliverable_kwh=float("inf")):
    return ChargerView(
        power=ChargerPower(charger_id="keba", power_w=0.0,
                           connected=connected, charging=False),
        energy=ChargerEnergy(charger_id="keba"),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 32},
        fleet=FleetContext(
            solar_w=solar_w, home_w=home_w,
            battery_soc=battery_soc, is_night=is_night,
            battery_assist_max_power_w=4500.0,
            battery_assist_min_surplus_w=1200.0,
        ),
        target_kwh=target_kwh,
        night_deliverable_kwh=night_deliverable_kwh,
    )


class TestTheModeIsRegisteredEverywhere:
    def test_it_sits_between_solar_only_and_cheap(self):
        """Order matters: the dict order IS the UI order, and the matrix
        orders modes by what each one adds."""
        keys = list(EV_CHARGE_MODES)
        assert keys.index("solar_only") + 1 == keys.index("solar_plus_battery")
        assert keys.index("solar_plus_battery") + 1 == keys.index("solar_plus_cheap")

    def test_it_has_a_strategy(self):
        assert "solar_plus_battery" in MODE_STRATEGIES

    def test_every_mode_has_a_strategy_and_vice_versa(self):
        assert set(MODE_STRATEGIES) == set(EV_CHARGE_MODES)

    def test_the_legacy_map_points_at_pv(self):
        """It literally IS the legacy ``pv`` mode restored."""
        assert MODE_TO_LEGACY_CHARGING_MODE["solar_plus_battery"] == "pv"

    def test_it_joins_none_of_the_night_predicates(self):
        """A day-solar mode: no night lane, no tariff, no smart night —
        exactly solar_only's memberships."""
        for group in (MODE_NIGHT_ALLOWED, MODE_USES_TARIFF, MODE_USES_SMART_NIGHT):
            assert "solar_plus_battery" not in group


class TestDayBehaviour:
    def test_zone4_budget_is_surplus_plus_assist_with_the_share_stamped(self):
        d = decide(_view(battery_soc=95.0, solar_w=6000.0, home_w=500.0))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        # surplus 5500 + full assist 4500 = 10000
        assert d.budget_w == 10000.0
        assert d.assist_w > 0.0, "the pack share must be reported (#885)"
        assert d.mode == "solar_plus_battery"

    def test_the_min_floor_never_engages(self):
        """THE distinguishing property vs min_plus_solar. Identical inputs,
        a huge remaining target the night cannot deliver — min_plus_solar
        engages its floor, this mode must not."""
        kw = dict(battery_soc=95.0, solar_w=1300.0, home_w=1000.0,
                  target_kwh=30.0, night_deliverable_kwh=0.0)
        floored = decide(_view("min_plus_solar", **kw))
        ours = decide(_view("solar_plus_battery", **kw))
        assert "Min floor engaged" in floored.reason, "sanity: the twin floors"
        assert "Min floor engaged" not in ours.reason
        assert ours.intent is ChargerIntent.IDLE, (
            "300W of budget is below 6A min and no floor may lift it"
        )

    def test_zone1_idles_on_battery_priority(self):
        d = decide(_view(battery_soc=20.0))
        assert d.intent is ChargerIntent.IDLE
        assert "Zone 1" in d.reason

    def test_zone2_delegates_to_solar_only(self):
        d = decide(_view(battery_soc=50.0, solar_w=6000.0))
        assert d.mode == "solar_plus_battery"
        assert "Zone 2" in d.reason


class TestNightIsSolarOnlysContract:
    def test_no_floor_means_never_grid(self):
        d = decide(_view(is_night=True, solar_w=0.0))
        assert d.intent is ChargerIntent.IDLE
        assert "never grid-charges" in d.reason

    def test_an_explicit_floor_takes_the_top_up_lane(self):
        d = decide(_view(is_night=True, solar_w=0.0, target_kwh=8.0))
        assert d.mode == "solar_plus_battery"
        assert "never grid-charges" not in d.reason

    def test_the_679_gate_needs_a_per_charger_floor(self):
        """A seeded global default is not an opt-in (#679) — the mode
        inherits solar_only's gate wholesale."""
        assert mode_allows_night_charging(
            {}, {"charge_mode": "solar_plus_battery"}) is False
        assert mode_allows_night_charging(
            {}, {"charge_mode": "solar_plus_battery",
                 "daily_ev_target": 8.0}) is True


class TestStabilityAndSurfaces:
    def test_its_day_decisions_are_flicker_filtered(self):
        from custom_components.solar_energy_management.coordinator.charge_stability import (
            SURPLUS_DAY_MODES,
        )
        assert "solar_plus_battery" in SURPLUS_DAY_MODES

    def test_the_select_lists_every_mode_including_cheap(self):
        """Decision 3: the tariff gate moved from hiding to disabling —
        the options list must carry all modes so the card can grey one."""
        import inspect
        from custom_components.solar_energy_management import select as S
        src = inspect.getsource(S.SEMPerChargerSelect)
        assert "return list(EV_CHARGE_MODES.keys())" in src
        assert "tariff_available" in src, (
            "the card needs the prerequisite flag to disable the cheap mode"
        )

    def test_the_card_knows_the_mode_and_both_prerequisite_rules(self):
        src = (ROOT / "dashboard" / "card" / "src" / "cards"
               / "sem-ev-status-card.js").read_text()
        assert "charge_mode_solar_plus_battery" in src
        assert "modeDisabled" in src and "tariff_available" in src
        assert "charge_mode_battery_learning_info" in src, (
            "Guido, 01.09: while the learner is not done, selecting the "
            "mode must at least inform"
        )


class TestEveryModeIsFullyTranslatedEverywhere:
    """The prepared-but-unwired ratchet. This gap existed because strings
    were prepared and surfaces never wired (and vice versa); a mode key
    missing any of its four card strings renders a blank hint block."""

    def test_dashboard_translations_cover_every_mode_in_every_language(self):
        d = json.loads((ROOT / "dashboard" / "translations.json").read_text())
        missing = []
        for lang, block in d.items():
            if not isinstance(block, dict) or "charge_mode_solar_only" not in block:
                continue
            for mode in EV_CHARGE_MODES:
                if mode == "off":
                    continue  # off has no hint rows by design
                for key in (f"charge_mode_{mode}",
                            f"charge_mode_hint_{mode}_surplus",
                            f"charge_mode_hint_{mode}_overnight",
                            f"charge_mode_hint_{mode}_battery"):
                    if key not in block:
                        missing.append(f"{lang}:{key}")
        assert not missing, f"blank hint blocks waiting to happen: {missing[:12]}"

    def test_entity_state_names_cover_every_mode(self):
        d = json.loads((ROOT / "strings.json").read_text())
        st = d["entity"]["select"]["charge_mode"]["state"]
        assert set(EV_CHARGE_MODES) <= set(st), (
            f"missing entity state names: {set(EV_CHARGE_MODES) - set(st)}"
        )
