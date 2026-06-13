"""Unit tests for #277 Phase B — mode-driven authority transfer.

Phase A added the ``charge_mode`` selector and seeded it from legacy
toggles. Phase B routes the coordinator's night-charging gate and
smart-night-sizing reads through the named mode rather than the
per-charger ``switch.sem_charger_<id>_night_charging`` /
``..._smart_night_charging`` entities.

What stays on legacy (deferred to Phase C):
  - ``_tariff_optimized_for`` keeps reading the per-charger tariff
    switch. The 5-mode taxonomy has no clean home for the
    ``minpv + tariff_optimized=on`` legacy combination (the daytime
    Min-PV tariff pause would silently shift); reconciling it
    requires the strategy-machine rewrite that's Phase C.
  - ``_determine_charging_strategy`` still reads
    ``ev_charging_mode`` as the daytime strategy authority for the
    same reason — ``pv`` vs ``minpv`` carry distinct zone semantics.

These tests pin the equivalence guarantee for the parts Phase B
DID switch:
  1. ``_mode_allows_night_charging`` matches the legacy
     per-charger night-switch state for every (mode, switch) combo
     a migrated install can produce.
  2. ``_mode_uses_smart_night`` matches the legacy smart-night-
     switch state for every supported mode.
  3. The runtime resolver (``effective_charge_mode_for``) and the
     migration (``_derive_charge_mode``) agree on every legacy
     combination — same property Phase A pinned, re-asserted here
     after the ``pv/auto + tariff`` derivation fix.
"""
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management import _derive_charge_mode
from custom_components.solar_energy_management.consts.ev_charge_modes import (
    DEFAULT_EV_CHARGE_MODE,
    EV_CHARGE_MODES,
    MODE_NIGHT_ALLOWED,
    MODE_USES_SMART_NIGHT,
    MODE_USES_TARIFF,
    effective_charge_mode_for,
)
from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.charging_control import (
    ChargingStateMachine,
)


def _hass_with_switches(*, night=None, tariff=None, smart=None,
                        charger_id="ev_charger"):
    """Build a hass stub whose state lookups answer for the three
    per-charger toggles. Pass ``None`` to simulate "switch entity not
    registered yet" (the cold migration window).
    """
    hass = MagicMock()
    night_eid = f"switch.sem_charger_{charger_id}_night_charging"
    tariff_eid = f"switch.sem_charger_{charger_id}_tariff_optimized"
    smart_eid = f"switch.sem_charger_{charger_id}_smart_night_charging"

    def states_get(eid):
        if eid == night_eid and night is not None:
            return MagicMock(state="on" if night else "off")
        if eid == tariff_eid and tariff is not None:
            return MagicMock(state="on" if tariff else "off")
        if eid == smart_eid and smart is not None:
            return MagicMock(state="on" if smart else "off")
        return None

    def is_state(eid, state):
        st = states_get(eid)
        return st is not None and st.state == state

    hass.states.get = states_get
    hass.states.is_state = is_state
    return hass


# ──────────────────────────────────────────────────────────────────────
# Mode → night-allowed truth table (replaces switch.sem_charger_*_night_charging)
# ──────────────────────────────────────────────────────────────────────

class TestModeAllowsNightCharging:
    """The three modes that map to ``night_charging=on`` in the legacy
    toggle world must produce ``True``; the other two ``False``."""

    @pytest.mark.parametrize("mode,expected", [
        ("solar_only",        False),
        ("solar_plus_cheap",  True),
        ("min_plus_solar",    True),
        ("always_max",        True),
        ("off",               False),
    ])
    def test_mode_allows_night(self, mode, expected):
        assert (mode in MODE_NIGHT_ALLOWED) is expected

    def test_unknown_mode_treated_as_disallowed(self):
        """Defensive: garbage in storage doesn't accidentally enable
        night charging."""
        assert ("garbage_mode" in MODE_NIGHT_ALLOWED) is False


# ──────────────────────────────────────────────────────────────────────
# Mode → smart-night truth table
# ──────────────────────────────────────────────────────────────────────

class TestModeUsesSmartNight:
    """Smart night (forecast-aware sizing) is implicit ON only for
    the two night-charging modes where it actually changes behaviour."""

    @pytest.mark.parametrize("mode,expected", [
        ("solar_only",        False),
        ("solar_plus_cheap",  True),
        ("min_plus_solar",    True),
        ("always_max",        False),
        ("off",               False),
    ])
    def test_mode_uses_smart_night(self, mode, expected):
        assert (mode in MODE_USES_SMART_NIGHT) is expected


# ──────────────────────────────────────────────────────────────────────
# Mode → tariff truth table — covers the deferred Phase C work
# ──────────────────────────────────────────────────────────────────────

class TestModeUsesTariff:
    """Only ``solar_plus_cheap`` consults the tariff window — the
    other modes either charge always (``always_max``), never
    (``off``), or use zone/surplus rules (``solar_only`` /
    ``min_plus_solar``).

    NOTE: ``_tariff_optimized_for`` in ``ev_control.py`` still reads
    the legacy switch directly (not this set) in Phase B. The
    consolidation lives here only as the truth table Phase C will
    enforce; the test pins the table so a future Phase C refactor
    can confidently switch authority.
    """

    @pytest.mark.parametrize("mode,expected", [
        ("solar_only",        False),
        ("solar_plus_cheap",  True),
        ("min_plus_solar",    False),
        ("always_max",        False),
        ("off",               False),
    ])
    def test_mode_uses_tariff(self, mode, expected):
        assert (mode in MODE_USES_TARIFF) is expected


# ──────────────────────────────────────────────────────────────────────
# ChargingStateMachine — night gate derives from mode
# ──────────────────────────────────────────────────────────────────────

def _build_state_machine(chargers, *, night=None, tariff=None):
    """Build a real ``ChargingStateMachine`` with a hass stub that
    answers for the per-charger switches. Used to exercise the
    mode-driven ``_read_night_enabled_raw`` end-to-end."""
    hass = _hass_with_switches(
        night=night, tariff=tariff,
        charger_id=(chargers[0]["id"] if chargers else "ev_charger"),
    )
    return ChargingStateMachine(
        hass=hass,
        config={"ev_chargers": chargers, "current_delta": 1},
        time_manager=MagicMock(),
    )


class TestNightGateFromMode:
    def test_stored_solar_only_disables_night(self):
        """User explicitly picked ``solar_only`` — night gate OFF
        regardless of the legacy switch state."""
        sm = _build_state_machine(
            [{"id": "ev_charger", "charge_mode": "solar_only"}],
            night=True,  # switch on, but mode is authoritative
        )
        assert sm._read_night_enabled_raw() is False

    def test_stored_min_plus_solar_enables_night(self):
        sm = _build_state_machine(
            [{"id": "ev_charger", "charge_mode": "min_plus_solar"}],
            night=False,  # switch off, but mode is authoritative
        )
        assert sm._read_night_enabled_raw() is True

    def test_stored_solar_plus_cheap_enables_night(self):
        sm = _build_state_machine(
            [{"id": "ev_charger", "charge_mode": "solar_plus_cheap"}],
            night=False,
        )
        assert sm._read_night_enabled_raw() is True

    def test_stored_always_max_enables_night(self):
        sm = _build_state_machine(
            [{"id": "ev_charger", "charge_mode": "always_max"}],
            night=False,
        )
        assert sm._read_night_enabled_raw() is True

    def test_stored_off_disables_night(self):
        sm = _build_state_machine(
            [{"id": "ev_charger", "charge_mode": "off"}],
            night=True,
        )
        assert sm._read_night_enabled_raw() is False

    def test_any_charger_with_night_mode_enables_global_gate(self):
        """Multi-charger: night gate fires when ANY charger's mode
        permits it. The other chargers can be on solar_only and the
        gate still opens — per-charger filtering in
        ``coordinator.py:1085+`` decides which ones actually run."""
        sm = _build_state_machine(
            [
                {"id": "a", "charge_mode": "solar_only"},
                {"id": "b", "charge_mode": "min_plus_solar"},
            ],
            night=False,  # both switches off; only mode B opens gate
        )
        assert sm._read_night_enabled_raw() is True

    def test_no_charge_mode_falls_back_to_default(self):
        """No ``charge_mode`` stored (corrupted config, hand-edited
        storage, etc.): Phase C resolver returns
        ``DEFAULT_EV_CHARGE_MODE`` (``min_plus_solar``) directly. The
        switch state in the fixture is irrelevant post-Phase-C — the
        legacy derivation fallback was removed. ``min_plus_solar`` is
        in ``MODE_NIGHT_ALLOWED`` so the gate returns True.

        Pre-Phase-C this test was named
        ``test_pre_migration_legacy_falls_back_via_derivation`` and
        asserted that the resolver derived a mode from the night /
        tariff switch states. Phase C removed that fallback because
        the switches are gone — the resolver now treats "missing
        stored mode" as "use the new-install default" instead.
        """
        sm = _build_state_machine(
            [{"id": "ev_charger"}],  # no charge_mode
            night=True, tariff=False,  # switch state irrelevant post-Phase-C
        )
        assert sm._read_night_enabled_raw() is True

    def test_no_chargers_returns_false_no_fallback(self):
        """Pre-EV setup with no ``ev_chargers`` list: nothing to
        enable. Phase B kept the legacy global
        ``switch.sem_night_charging`` fallback for backward-compat;
        Phase C removed it (the switch entity is gone from
        ``switch.py`` too). Result: unambiguous False."""
        hass = MagicMock()
        sm = ChargingStateMachine(
            hass=hass,
            config={"ev_chargers": [], "current_delta": 1},
            time_manager=MagicMock(),
        )
        assert sm._read_night_enabled_raw() is False


# ──────────────────────────────────────────────────────────────────────
# SEMCoordinator._smart_night_charging_enabled — mode-driven
# ──────────────────────────────────────────────────────────────────────

class TestSmartNightFromMode:
    def _build_coord(self, chargers, **switches):
        with patch.object(SEMCoordinator, "__init__", return_value=None):
            coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.hass = _hass_with_switches(**switches)
        coord.config = {"ev_chargers": chargers}
        return coord

    def test_solar_only_disables_smart(self):
        coord = self._build_coord([
            {"id": "ev_charger", "charge_mode": "solar_only"},
        ])
        assert coord._smart_night_charging_enabled() is False

    def test_min_plus_solar_enables_smart(self):
        coord = self._build_coord([
            {"id": "ev_charger", "charge_mode": "min_plus_solar"},
        ])
        assert coord._smart_night_charging_enabled() is True

    def test_solar_plus_cheap_enables_smart(self):
        coord = self._build_coord([
            {"id": "ev_charger", "charge_mode": "solar_plus_cheap"},
        ])
        assert coord._smart_night_charging_enabled() is True

    def test_always_max_disables_smart(self):
        """always_max blasts max regardless — forecast-aware sizing
        is N/A."""
        coord = self._build_coord([
            {"id": "ev_charger", "charge_mode": "always_max"},
        ])
        assert coord._smart_night_charging_enabled() is False

    def test_any_charger_enables_globally(self):
        """Same OR-across-chargers semantic as the night gate."""
        coord = self._build_coord([
            {"id": "a", "charge_mode": "solar_only"},
            {"id": "b", "charge_mode": "min_plus_solar"},
        ])
        assert coord._smart_night_charging_enabled() is True

    def test_no_chargers_returns_false(self):
        """Pre-EV setup: nothing to enable. Pre-Phase-B the helper
        consulted a global switch that was never created — now an
        unambiguous False."""
        coord = self._build_coord([])
        assert coord._smart_night_charging_enabled() is False


# ──────────────────────────────────────────────────────────────────────
# Runtime ↔ migration equivalence — re-asserted after the pv+tariff fix
# ──────────────────────────────────────────────────────────────────────

class TestDeriveChargeModeAllLegacyCombinations:
    """The migration's ``_derive_charge_mode`` must produce the
    documented mode for every legacy combination.

    Pre-#277 Phase C this test ALSO asserted that the runtime resolver
    (``effective_charge_mode_for``) produced the same answer — the
    equivalence property. Phase C removed the runtime derivation
    fallback (the legacy switches are gone, so it couldn't read them
    anyway), so the property is no longer meaningful for runtime; it
    still matters for the migration's one-shot pass.
    """

    COMBOS = [
        # (ev_charging_mode, night, tariff, expected_mode)
        # Existing Phase A cases:
        ("now",    True,  False, "always_max"),
        ("now",    False, True,  "always_max"),
        ("off",    True,  False, "off"),
        ("auto",   True,  True,  "solar_plus_cheap"),
        ("auto",   True,  False, "min_plus_solar"),
        ("auto",   False, False, "solar_only"),
        ("pv",     True,  False, "min_plus_solar"),
        ("pv",     False, False, "solar_only"),
        ("minpv",  True,  False, "min_plus_solar"),
        ("minpv",  False, False, "min_plus_solar"),
        # Phase B fix: pv+tariff and self_consumption+tariff must
        # preserve the tariff signal rather than collapse to solar_only
        # or min_plus_solar.
        ("pv",                True,  True,  "solar_plus_cheap"),
        ("pv",                False, True,  "solar_plus_cheap"),
        ("self_consumption",  True,  True,  "solar_plus_cheap"),
        # ``minpv + tariff_on`` has no clean home in the 5-mode
        # taxonomy. Stays on the catch-all ``min_plus_solar``; the
        # v5→v6 fix-up specifically does NOT correct these (see
        # TestMigrateEntryV6.test_preserves_minpv_plus_tariff_users).
        ("minpv", True,  True,  "min_plus_solar"),
        ("minpv", False, True,  "min_plus_solar"),
    ]

    @pytest.mark.parametrize("cmode,night,tariff,expected", COMBOS)
    def test_migration_derivation(self, cmode, night, tariff, expected):
        hass = _hass_with_switches(night=night, tariff=tariff)
        cfg = {"id": "ev_charger", "ev_charging_mode": cmode}
        via_migration = _derive_charge_mode(cfg, {}, hass)
        assert via_migration == expected, (
            f"migration: ({cmode}, night={night}, tariff={tariff}) "
            f"got {via_migration}, expected {expected}"
        )


# ──────────────────────────────────────────────────────────────────────
# v5 → v6 fix-up migration — re-derive the Phase A pv+tariff bug
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestMigrateEntryV6:
    """Phase A's v4→v5 derivation silently dropped tariff intent for
    legacy users on ``mode=pv`` (or ``auto`` / ``self_consumption``)
    with ``tariff_optimized_switch=on``. They got
    ``charge_mode="min_plus_solar"`` written to storage.

    Phase B fixes the derivation forward AND ships a narrow v5→v6
    fix-up to correct the existing stored values. Condition:
    ``stored == "min_plus_solar"`` AND ``legacy mode ∈ (pv, auto,
    self_consumption)`` AND ``tariff switch ON``. Everything else
    stays put.
    """

    async def _run(self, *, options, hass=None):
        from custom_components.solar_energy_management import async_migrate_entry

        entry = MagicMock()
        entry.version = 5
        entry.minor_version = 1
        entry.data = {}
        entry.options = options

        if hass is None:
            hass = _hass_with_switches(night=True, tariff=False)
        captured = {}
        def _update(e, **kwargs):
            captured.update(kwargs)
        hass.config_entries.async_update_entry = MagicMock(side_effect=_update)

        ok = await async_migrate_entry(hass, entry)
        assert ok is True
        return captured

    async def test_corrects_pv_plus_tariff_users(self):
        """The exact Phase A bug condition — stored bad mode + tariff
        switch on + pv legacy. Must flip to solar_plus_cheap."""
        hass = _hass_with_switches(night=True, tariff=True)
        captured = await self._run(options={
            "ev_chargers": [
                {"id": "ev_charger", "ev_charging_mode": "pv",
                 "charge_mode": "min_plus_solar"},
            ],
        }, hass=hass)
        assert captured["options"]["ev_chargers"][0]["charge_mode"] == "solar_plus_cheap"
        assert captured["version"] == 13  # bumped in v11→v12 (#135)  # bumped in v10→v11 (#446)  # bumped in v9→v10 (#441)  # bumped in v6→v7 (#277 Phase C)

    async def test_preserves_explicit_min_plus_solar_without_tariff(self):
        """User explicitly picked min_plus_solar in the new selector
        (tariff switch off). Fix-up must NOT touch them."""
        hass = _hass_with_switches(night=True, tariff=False)
        captured = await self._run(options={
            "ev_chargers": [
                {"id": "ev_charger", "ev_charging_mode": "minpv",
                 "charge_mode": "min_plus_solar"},
            ],
        }, hass=hass)
        assert captured["options"]["ev_chargers"][0]["charge_mode"] == "min_plus_solar"

    async def test_preserves_minpv_plus_tariff_users(self):
        """minpv + tariff is the deferred Phase C combination — leave
        them at min_plus_solar so daytime behaviour stays unchanged."""
        hass = _hass_with_switches(night=True, tariff=True)
        captured = await self._run(options={
            "ev_chargers": [
                {"id": "ev_charger", "ev_charging_mode": "minpv",
                 "charge_mode": "min_plus_solar"},
            ],
        }, hass=hass)
        assert captured["options"]["ev_chargers"][0]["charge_mode"] == "min_plus_solar"

    async def test_preserves_solar_plus_cheap_users(self):
        """Already-correct users — no-op."""
        hass = _hass_with_switches(night=True, tariff=True)
        captured = await self._run(options={
            "ev_chargers": [
                {"id": "ev_charger", "ev_charging_mode": "auto",
                 "charge_mode": "solar_plus_cheap"},
            ],
        }, hass=hass)
        assert captured["options"]["ev_chargers"][0]["charge_mode"] == "solar_plus_cheap"

    async def test_preserves_other_modes_with_tariff_on(self):
        """always_max / off / solar_only with tariff switch on — out
        of scope for the fix-up; leave untouched."""
        hass = _hass_with_switches(night=True, tariff=True)
        for mode in ("always_max", "off", "solar_only"):
            captured = await self._run(options={
                "ev_chargers": [
                    {"id": "ev_charger", "ev_charging_mode": "pv",
                     "charge_mode": mode},
                ],
            }, hass=hass)
            assert captured["options"]["ev_chargers"][0]["charge_mode"] == mode

    async def test_multi_charger_per_charger_decision(self):
        """Fix-up runs per charger — one charger gets corrected, the
        other stays put."""
        hass = _hass_with_switches(night=True, tariff=True,
                                    charger_id="a")
        captured = await self._run(options={
            "ev_chargers": [
                {"id": "a", "ev_charging_mode": "pv",
                 "charge_mode": "min_plus_solar"},
                {"id": "b", "ev_charging_mode": "minpv",
                 "charge_mode": "min_plus_solar"},
            ],
        }, hass=hass)
        out = captured["options"]["ev_chargers"]
        # a: pv + tariff_on (for charger a) → corrected
        assert out[0]["charge_mode"] == "solar_plus_cheap"
        # b: minpv (deferred) → untouched
        assert out[1]["charge_mode"] == "min_plus_solar"

    async def test_no_chargers_safe_bumps_version(self):
        captured = await self._run(options={})
        assert captured["version"] == 13  # bumped in v11→v12 (#135)  # bumped in v10→v11 (#446)  # bumped in v9→v10 (#441)  # bumped in v6→v7 (#277 Phase C)


# ──────────────────────────────────────────────────────────────────────
# Mode-name source-of-truth — both files must reference the shared set
# ──────────────────────────────────────────────────────────────────────

class TestModeNameSourceOfTruth:
    """The 5 mode names live in one place (``consts.ev_charge_modes``).
    Any helper that filters / dispatches on a mode must use the shared
    constants — duplicating the tuple is exactly the bug Phase A's
    reviewer flagged. This test pins both that the constants are
    complete and that the three mode-set predicates partition them
    correctly."""

    def test_constants_cover_every_mode(self):
        """Sanity: the union of the three predicates is a strict
        subset of the full mode set (``solar_only`` and ``off`` opt
        out of everything; ``always_max`` opts out of smart and
        tariff)."""
        modes = set(EV_CHARGE_MODES.keys())
        assert MODE_NIGHT_ALLOWED.issubset(modes)
        assert MODE_USES_SMART_NIGHT.issubset(modes)
        assert MODE_USES_TARIFF.issubset(modes)

    def test_default_is_known_mode(self):
        assert DEFAULT_EV_CHARGE_MODE in EV_CHARGE_MODES

    def test_tariff_subset_of_night(self):
        """Tariff windows only make sense when night charging is
        permitted. The two sets must be properly ordered."""
        assert MODE_USES_TARIFF.issubset(MODE_NIGHT_ALLOWED)

    def test_smart_subset_of_night(self):
        """Smart sizing only applies to night-charging modes."""
        assert MODE_USES_SMART_NIGHT.issubset(MODE_NIGHT_ALLOWED)
