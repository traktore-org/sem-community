"""Unit tests for #277 Phase A — Charge mode selector + migration.

Phase A is purely additive:
  - A new per-charger ``select.sem_charger_<id>_charge_mode`` entity
    persists the user's named intent.
  - ``async_migrate_entry`` v4 → v5 derives the field from existing
    legacy toggle state on first upgrade boot.
  - ``SEMCoordinator._effective_charge_mode_for`` exposes the resolved
    mode (stored value first, derived from legacy toggles second) so
    Phase B has a single read point to switch authority on.
  - The coordinator's strategy machine still reads the legacy toggles —
    behaviour is unchanged from v1.6.2.

These tests pin the four moving pieces:
  1. ``_derive_charge_mode`` — the migration's decision tree
  2. ``SEMPerChargerSelect`` options behaviour (Q1: hide
     ``solar_plus_cheap`` when no dynamic tariff)
  3. The full migration loop in ``async_migrate_entry``
  4. ``_effective_charge_mode_for`` equivalence (stored vs derived)
"""
import json
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from custom_components.solar_energy_management import _derive_charge_mode
from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.select import (
    EV_CHARGE_MODES,
    SEMPerChargerSelect,
)


# ──────────────────────────────────────────────────────────────────────
# _derive_charge_mode — migration decision tree
# ──────────────────────────────────────────────────────────────────────

def _hass_with_switches(*, night=None, tariff=None, charger_id="ev_charger"):
    """Build a hass stub whose ``states.get`` / ``states.is_state`` answer
    only for the per-charger switches we care about. Pass ``None`` to
    simulate "switch entity not registered yet" (cold migration window)."""
    hass = MagicMock()
    night_eid = f"switch.sem_charger_{charger_id}_night_charging"
    tariff_eid = f"switch.sem_charger_{charger_id}_tariff_optimized"

    def states_get(eid):
        if eid == night_eid and night is not None:
            return MagicMock(state="on" if night else "off")
        if eid == tariff_eid and tariff is not None:
            return MagicMock(state="on" if tariff else "off")
        return None

    def is_state(eid, state):
        st = states_get(eid)
        return st is not None and st.state == state

    hass.states.get = states_get
    hass.states.is_state = is_state
    return hass


class TestDeriveChargeMode:
    """Migration's per-charger mode derivation. Five mode outputs ×
    each of the legacy toggle inputs that produces it."""

    def test_now_maps_to_always_max(self):
        cfg = {"id": "ev_charger", "ev_charging_mode": "now"}
        hass = _hass_with_switches(night=True, tariff=False)
        assert _derive_charge_mode(cfg, {}, hass) == "always_max"

    def test_off_maps_to_off(self):
        cfg = {"id": "ev_charger", "ev_charging_mode": "off"}
        hass = _hass_with_switches(night=True, tariff=False)
        assert _derive_charge_mode(cfg, {}, hass) == "off"

    def test_auto_plus_tariff_maps_to_solar_plus_cheap(self):
        """The user's intent when they had Auto + tariff_optimized=on
        was 'use cheapest hours' — name it explicitly."""
        cfg = {"id": "ev_charger", "ev_charging_mode": "auto"}
        hass = _hass_with_switches(night=True, tariff=True)
        assert _derive_charge_mode(cfg, {}, hass) == "solar_plus_cheap"

    def test_pv_without_night_maps_to_solar_only(self):
        """Factory legacy default was mode=pv. With night=off the user
        explicitly opted out of grid top-up → solar_only."""
        cfg = {"id": "ev_charger", "ev_charging_mode": "pv"}
        hass = _hass_with_switches(night=False, tariff=False)
        assert _derive_charge_mode(cfg, {}, hass) == "solar_only"

    def test_auto_without_night_maps_to_solar_only(self):
        cfg = {"id": "ev_charger", "ev_charging_mode": "auto"}
        hass = _hass_with_switches(night=False, tariff=False)
        assert _derive_charge_mode(cfg, {}, hass) == "solar_only"

    def test_self_consumption_without_night_maps_to_solar_only(self):
        """Legacy strategy text that ev_charging_mode briefly used."""
        cfg = {"id": "ev_charger", "ev_charging_mode": "self_consumption"}
        hass = _hass_with_switches(night=False, tariff=False)
        assert _derive_charge_mode(cfg, {}, hass) == "solar_only"

    def test_factory_default_maps_to_min_plus_solar(self):
        """The catch-all default — matches today's factory defaults
        (mode=pv + night=on + smart=on + tariff=off). Q4 decision."""
        cfg = {"id": "ev_charger", "ev_charging_mode": "pv"}
        hass = _hass_with_switches(night=True, tariff=False)
        assert _derive_charge_mode(cfg, {}, hass) == "min_plus_solar"

    def test_minpv_maps_to_min_plus_solar(self):
        """Explicit Min+PV (the legacy entry-point for grid+solar) maps
        cleanly to the same named mode."""
        cfg = {"id": "ev_charger", "ev_charging_mode": "minpv"}
        hass = _hass_with_switches(night=True, tariff=False)
        assert _derive_charge_mode(cfg, {}, hass) == "min_plus_solar"

    def test_missing_night_switch_defaults_to_on(self):
        """Cold migration window: switch entities not yet created.
        Default is factory ON to match new-install behaviour."""
        cfg = {"id": "ev_charger", "ev_charging_mode": "pv"}
        hass = _hass_with_switches(night=None, tariff=None)  # missing
        # No night switch → defaults to ON → catch-all min_plus_solar
        assert _derive_charge_mode(cfg, {}, hass) == "min_plus_solar"

    def test_charger_id_in_switch_lookup(self):
        """Multi-charger: the right per-charger switch is consulted, not
        a hardcoded ``ev_charger`` ID."""
        cfg = {"id": "second_charger", "ev_charging_mode": "auto"}
        hass = _hass_with_switches(
            night=False, tariff=False, charger_id="second_charger",
        )
        assert _derive_charge_mode(cfg, {}, hass) == "solar_only"


# ──────────────────────────────────────────────────────────────────────
# SEMPerChargerSelect — charge_mode options (Q1: hide solar_plus_cheap)
# ──────────────────────────────────────────────────────────────────────

def _build_charge_mode_select(
    *, tariff_mode="static", stored_value="min_plus_solar",
):
    """Construct a SEMPerChargerSelect bypassing CoordinatorEntity init."""
    from homeassistant.components.select import SelectEntityDescription

    sel = SEMPerChargerSelect.__new__(SEMPerChargerSelect)
    sel.coordinator = MagicMock()
    sel.coordinator.config = {
        "tariff_mode": tariff_mode,
        "ev_chargers": [{"id": "ev_charger", "charge_mode": stored_value}],
    }
    sel.entity_description = SelectEntityDescription(
        key="charger_ev_charger_charge_mode",
        options=list(EV_CHARGE_MODES.keys()),
    )
    sel._charger_id = "ev_charger"
    sel._config_key = "charge_mode"
    sel._value = stored_value
    return sel


class TestChargeModeOptions:
    """Q1: ``solar_plus_cheap`` only appears when tariff_mode == 'dynamic'."""

    def test_solar_plus_cheap_hidden_without_dynamic_tariff(self):
        sel = _build_charge_mode_select(tariff_mode="static")
        opts = sel.options
        assert "solar_plus_cheap" not in opts, (
            "solar_plus_cheap must hide when no dynamic tariff (Q1)"
        )
        # All other modes still present
        for m in ("solar_only", "min_plus_solar", "always_max", "off"):
            assert m in opts

    def test_solar_plus_cheap_hidden_with_calendar_tariff(self):
        """calendar tariff is not 'dynamic' — same hide rule."""
        sel = _build_charge_mode_select(tariff_mode="calendar")
        assert "solar_plus_cheap" not in sel.options

    def test_solar_plus_cheap_visible_with_dynamic_tariff(self):
        sel = _build_charge_mode_select(tariff_mode="dynamic")
        opts = sel.options
        assert "solar_plus_cheap" in opts
        assert len(opts) == 5

    def test_valid_value_set_always_full(self):
        """Universe of valid values is always the 5 — only the UI list
        narrows. Persisted ``solar_plus_cheap`` on a now-non-tariff
        install must stay readable so a re-enable of tariff restores
        the mode automatically rather than silently resetting."""
        sel = _build_charge_mode_select(tariff_mode="static")
        assert sel._valid_value_set() == set(EV_CHARGE_MODES.keys())

    def test_current_option_clamps_when_stored_solar_plus_cheap_loses_tariff(self):
        """User had dynamic tariff + ``solar_plus_cheap`` mode, then
        switched to a static tariff. The selector's ``options`` no
        longer includes ``solar_plus_cheap`` (Q1 hide rule); the
        ``current_option`` then clamps to ``options[0]`` (``solar_only``).

        **Critical for Phase B:** ``self._value`` MUST stay
        ``solar_plus_cheap`` in storage — re-enabling the tariff later
        should restore the user's original intent rather than silently
        resetting it. Phase B's coordinator-authority switchover must
        read ``self._value`` (or the persisted ``coordinator.config``
        key), NOT ``current_option``, or it will treat the user as
        having explicitly chosen ``solar_only`` when they didn't.
        """
        sel = _build_charge_mode_select(
            tariff_mode="static", stored_value="solar_plus_cheap",
        )
        # UI options exclude solar_plus_cheap
        assert "solar_plus_cheap" not in sel.options
        # current_option clamps to options[0] (the first remaining mode)
        assert sel.current_option == sel.options[0] == "solar_only"
        # Stored intent preserved — Phase B must read this, not current_option
        assert sel._value == "solar_plus_cheap"


# ──────────────────────────────────────────────────────────────────────
# async_migrate_entry v4 → v5
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestMigrateEntryV5:
    """End-to-end migration covering: derivation runs for every charger,
    existing field is preserved, version bumps, legacy toggles untouched."""

    async def _run_migration_at_v4(self, *, options, hass=None):
        """Run async_migrate_entry on a v4 entry and return the new
        options dict it persisted."""
        from custom_components.solar_energy_management import async_migrate_entry

        entry = MagicMock()
        entry.version = 4
        entry.minor_version = 1
        entry.data = {}
        entry.options = options

        if hass is None:
            hass = _hass_with_switches(night=True, tariff=False)
        # Capture what async_update_entry was called with
        captured = {}
        def _update(e, **kwargs):
            captured.update(kwargs)
        hass.config_entries.async_update_entry = MagicMock(side_effect=_update)

        result = await async_migrate_entry(hass, entry)
        assert result is True, "migration must succeed"
        return captured

    async def test_seeds_charge_mode_per_charger(self):
        captured = await self._run_migration_at_v4(options={
            "ev_chargers": [
                {"id": "ev_charger", "ev_charging_mode": "pv"},
                {"id": "second", "ev_charging_mode": "now"},
            ],
        })
        new_chargers = captured["options"]["ev_chargers"]
        assert new_chargers[0]["charge_mode"] == "min_plus_solar"
        assert new_chargers[1]["charge_mode"] == "always_max"

    async def test_preserves_existing_charge_mode(self):
        """A user who already has charge_mode set (e.g. manual edit
        or migration re-run) must NOT have it overwritten."""
        captured = await self._run_migration_at_v4(options={
            "ev_chargers": [
                {"id": "ev_charger", "ev_charging_mode": "pv",
                 "charge_mode": "solar_only"},
            ],
        })
        assert captured["options"]["ev_chargers"][0]["charge_mode"] == "solar_only"

    # ``test_legacy_toggle_state_unchanged`` removed in #277 Phase C —
    # the property it pinned ("Phase A migration must not mutate
    # legacy fields") was a Phase-A-only invariant. Phase C's v6→v7
    # migration explicitly removes the ``ev_charging_mode`` legacy
    # field; preserving it would be a regression on Phase C's
    # contract, so the test is no longer meaningful.

    async def test_bumps_version_to_5(self):
        captured = await self._run_migration_at_v4(options={
            "ev_chargers": [{"id": "ev_charger", "ev_charging_mode": "pv"}],
        })
        assert captured["version"] == 9  # bumped in v8→v9 (#440)  # bumped in v6→v7 (#277 Phase C)  # bumped in v5→v6 (#277 Phase B)

    async def test_no_chargers_no_crash(self):
        """Pre-EV setups (no ev_chargers list) must still migrate."""
        captured = await self._run_migration_at_v4(options={})
        assert captured["version"] == 9  # bumped in v8→v9 (#440)  # bumped in v6→v7 (#277 Phase C)  # bumped in v5→v6 (#277 Phase B)
        # No ev_chargers to seed, so the key may or may not be present —
        # the migration must not invent one.
        assert "ev_chargers" not in captured["options"] or \
            captured["options"]["ev_chargers"] in (None, [])


# ──────────────────────────────────────────────────────────────────────
# SEMCoordinator._effective_charge_mode_for — read-side helper
# ──────────────────────────────────────────────────────────────────────

class TestEffectiveChargeMode:
    """The single read-point Phase B will switch authority on. Stored
    value wins when present; legacy derivation when absent."""

    def _build_coord(self, *, hass=None, config=None):
        with patch.object(SEMCoordinator, "__init__", return_value=None):
            coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.hass = hass or _hass_with_switches(night=True, tariff=False)
        coord.config = config or {}
        return coord

    def test_stored_mode_wins(self):
        """When charger_cfg['charge_mode'] is set, return it verbatim."""
        coord = self._build_coord()
        cfg = {"id": "ev_charger", "charge_mode": "solar_only",
               "ev_charging_mode": "minpv"}  # legacy says different
        assert coord._effective_charge_mode_for(cfg) == "solar_only"

    def test_missing_stored_returns_default(self):
        """Post-#277 Phase C the legacy-toggle derivation fallback was
        removed (the legacy switches are gone). When ``charge_mode`` is
        missing the resolver returns the new-install default —
        previously it derived from the legacy toggles. Migration is
        mandatory on every config-entry load, so in real installs the
        field is always present.
        """
        coord = self._build_coord()
        cfg = {"id": "ev_charger"}  # no charge_mode, no legacy toggles
        assert coord._effective_charge_mode_for(cfg) == "min_plus_solar"

    def test_unknown_stored_value_falls_back_to_default(self):
        """Defensive: a stored value outside the 5 known modes (someone
        edited storage by hand) returns the new-install default. Pre-
        Phase-C this fell back to the legacy derivation; post-C the
        derivation is gone."""
        coord = self._build_coord()
        cfg = {"id": "ev_charger", "charge_mode": "garbage_value"}
        assert coord._effective_charge_mode_for(cfg) == "min_plus_solar"

    def test_non_dict_charger_cfg_returns_default(self):
        """Defensive: corrupt config (None / list / str) returns the
        new-install default rather than crashing the cycle."""
        coord = self._build_coord()
        assert coord._effective_charge_mode_for(None) == "min_plus_solar"
        assert coord._effective_charge_mode_for("nope") == "min_plus_solar"

    # ``test_equivalence_across_all_legacy_combinations`` was removed in
    # #277 Phase C — the legacy-toggle derivation fallback no longer
    # exists at runtime (the resolver returns the new-install default
    # when ``charge_mode`` is missing). The migration's own derivation
    # (``_derive_charge_mode``) still exists and is covered by
    # ``TestDeriveChargeMode`` above; the runtime-vs-migration
    # equivalence property is no longer meaningful because they don't
    # share a runtime path anymore.


# ──────────────────────────────────────────────────────────────────────
# Translation keys exist for every mode in every language
# ──────────────────────────────────────────────────────────────────────

class TestTranslationsComplete:
    """Each of the 15 supported languages must define a label for the
    Charge mode entity AND a state translation for every mode in
    ``EV_CHARGE_MODES``. Catches a half-applied translation patch."""

    LANGUAGES = (
        "en", "de", "nl", "fr", "es", "it", "pt", "pl",
        "sv", "cs", "da", "fi", "hu", "ro", "no",
    )

    def test_every_language_has_charge_mode_block(self):
        from pathlib import Path
        base = Path(__file__).resolve().parent.parent / "translations"
        for lang in self.LANGUAGES:
            d = json.loads((base / f"{lang}.json").read_text())
            block = d.get("entity", {}).get("select", {}).get("charge_mode")
            assert block is not None, f"{lang}.json missing charge_mode block"
            assert "name" in block, f"{lang}.json charge_mode missing 'name'"
            states = block.get("state", {})
            for mode in EV_CHARGE_MODES.keys():
                assert mode in states, (
                    f"{lang}.json charge_mode missing state for '{mode}'"
                )
                assert states[mode], (
                    f"{lang}.json charge_mode.state.{mode} is empty"
                )
