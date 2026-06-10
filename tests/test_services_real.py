"""Real-HA integration tests for SEM's ``set_option`` service.

This is the test that would have caught v1.7.3-beta.1's number-entity
staleness bug. The pure-helper contract tests in
``test_set_option_smart_merge.py`` covered the smart-merge math and
the structural-key gate in isolation; what they could NOT see was the
entity lifecycle — that a number entity caches ``_attr_native_value``
at ``__init__`` time and only refreshes on integration reload. Skipping
the reload also skipped the refresh; the persisted options matched the
new value but the displayed entity stayed at the old one.

These tests run inside a real ``HomeAssistant`` instance (via the
``hass`` fixture from ``pytest-homeassistant-custom-component``) and
assert on ``sem_real_hass.states.get(...)`` — the user-visible contract — not on
internal coordinator state. They are the tier-2 gate the
``[live-test-before-deploy]`` memory exists to demand: any future
``set_option`` / ``set_value`` / per-charger select rewrite must keep
all of these green.

Each test follows the canonical HA Platinum-tier pattern:

1. Pre-create the sensors SEM expects to read from (so coordinator
   first-refresh doesn't bail).
2. ``entry.add_to_hass(hass)`` + ``async_setup`` + ``async_block_till_done``.
3. Call the service via ``sem_real_hass.services.async_call(..., blocking=True)``.
4. ``await sem_real_hass.async_block_till_done()`` to flush coordinator side-effects.
5. Assert on ``sem_real_hass.states.get(entity_id).state`` — never on
   ``coordinator.config`` or ``entry.options``, because those don't
   match what the user sees.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.const import DOMAIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_sem_input_sensors(sem_real_hass) -> None:
    """Seed the input sensors SEM reads at first refresh.

    SEM's coordinator pulls from grid / battery / solar / EV sensors on
    every cycle; if they don't exist the setup fails with
    ConfigEntryNotReady. The fixture's data dict references these by
    name so the seed values just need to be parseable floats / strings.
    Test-specific sensor needs (e.g. multi-charger seeds the second
    Wallbox's entities too) layer on top in their own fixtures.
    """
    sem_real_hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "W"})
    sem_real_hass.states.async_set("sensor.test_battery_power", "0", {"unit_of_measurement": "W"})
    sem_real_hass.states.async_set("sensor.test_battery_soc", "50", {"unit_of_measurement": "%"})
    sem_real_hass.states.async_set("sensor.test_solar_power", "0", {"unit_of_measurement": "W"})
    sem_real_hass.states.async_set("sensor.test_ev_total_energy", "0", {"unit_of_measurement": "kWh"})
    sem_real_hass.states.async_set("sensor.test_ev_charging_power", "0", {"unit_of_measurement": "W"})
    sem_real_hass.states.async_set("binary_sensor.test_ev_connected", "off")
    sem_real_hass.states.async_set("binary_sensor.test_ev_charging", "off")
    sem_real_hass.states.async_set("number.test_charger_current", "0", {"unit_of_measurement": "A"})


async def _setup_sem(sem_real_hass, entry) -> None:
    """Register + set up the SEM integration on ``hass``.

    Returns when setup is fully settled (all platforms forwarded,
    coordinator first-refreshed, services registered).
    """
    entry.add_to_hass(sem_real_hass)
    assert await sem_real_hass.config_entries.async_setup(entry.entry_id), (
        "SEM setup failed — check that all required input sensors are seeded "
        "via _seed_sem_input_sensors() before calling _setup_sem()."
    )
    await sem_real_hass.async_block_till_done()


# ---------------------------------------------------------------------------
# v1.7.3-beta.1 regression — entity refreshes when set_option writes a tunable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_option_tunable_refreshes_number_entity(
    sem_real_hass, sem_config_entry,
) -> None:
    """``set_option`` must update the number entity's displayed state.

    The v1.7.3-beta.1 regression: ``set_option`` persisted the new
    value to ``entry.options`` but the number entity stayed at its old
    state because the skip-reload optimization also skipped the
    entity refresh.

    With the v1.7.3-beta.2 hotfix (route tunables through
    ``number.set_value``), the entity's own write path runs and
    ``_attr_native_value`` updates synchronously. This test asserts
    the user-visible state actually changed.
    """
    _seed_sem_input_sensors(sem_real_hass)
    await _setup_sem(sem_real_hass, sem_config_entry)

    # Read the initial state to know what we're changing from.
    initial = sem_real_hass.states.get("number.sem_cheap_price_threshold")
    assert initial is not None, "number.sem_cheap_price_threshold should exist post-setup"
    new_value = round(float(initial.state) + 0.07, 2)

    # Drive the service call through the registry — same path the
    # Config card uses in production.
    await sem_real_hass.services.async_call(
        DOMAIN, "set_option",
        {"options": {"cheap_price_threshold": new_value}},
        blocking=True,
    )
    await sem_real_hass.async_block_till_done()

    after = sem_real_hass.states.get("number.sem_cheap_price_threshold")
    assert after is not None
    assert float(after.state) == new_value, (
        f"Beta.1 regression: number entity stuck at {after.state} after "
        f"set_option wrote {new_value}. Entity refresh broken — the user "
        f"sees stale data even though entry.options has the new value."
    )


@pytest.mark.asyncio
async def test_set_option_tunable_does_not_trigger_reload(
    sem_real_hass, sem_config_entry,
) -> None:
    """``set_option`` on a tunable key should NOT reload the integration.

    The whole point of the v1.7.3-beta.1/beta.2 fix is to KEEP the
    coordinator state alive across tunable changes — without that,
    every Config-card tweak destroys the SensorReader's split-grid
    discovery state (root cause for #461) and the per-charger context
    across the multi-charger loop (root cause for #462 / #464).

    We assert "no reload" by checking the coordinator instance is the
    SAME object before and after. A reload destroys and recreates
    runtime_data, so identity comparison catches the regression.
    """
    _seed_sem_input_sensors(sem_real_hass)
    await _setup_sem(sem_real_hass, sem_config_entry)

    coordinator_before = sem_config_entry.runtime_data
    assert coordinator_before is not None

    await sem_real_hass.services.async_call(
        DOMAIN, "set_option",
        {"options": {"cheap_price_threshold": 0.42}},
        blocking=True,
    )
    await sem_real_hass.async_block_till_done()

    coordinator_after = sem_config_entry.runtime_data
    assert coordinator_after is coordinator_before, (
        "Tunable set_option triggered a coordinator reload — destroys "
        "split-grid discovery state, per-charger context, and the v1.7.1 "
        "behavior #467/#468 restored. Don't add tunable keys to "
        "_SET_OPTION_STRUCTURAL_KEYS without a strong reason."
    )


# ---------------------------------------------------------------------------
# Smart-merge contract — set_option(ev_chargers=...) preserves siblings (#467)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_option_ev_chargers_partial_submit_preserves_sibling(
    sem_real_hass, sem_multi_wallbox_config_entry,
) -> None:
    """A partial ``set_option`` on ``ev_chargers`` must not drop sibling chargers.

    Reproduces the #464 cross-talk: in v1.7.2 the Config card could
    send a one-charger ``ev_chargers`` payload and the naïve shallow
    merge dropped the other charger from persisted state. The smart-
    merge in #467 keys on ``id`` so a partial submit updates the
    matching charger while keeping siblings untouched.

    Runs against the dual-Wallbox fixture (RienduPre's setup shape).
    """
    _seed_sem_input_sensors(sem_real_hass)
    # Multi-Wallbox needs its second charger's sensors too.
    sem_real_hass.states.async_set("sensor.test_wb_left_charging_power", "0", {"unit_of_measurement": "W"})
    sem_real_hass.states.async_set("sensor.test_wb_right_charging_power", "0", {"unit_of_measurement": "W"})
    sem_real_hass.states.async_set("number.test_wb_left_max_current", "0", {"unit_of_measurement": "A"})
    sem_real_hass.states.async_set("number.test_wb_right_max_current", "0", {"unit_of_measurement": "A"})
    sem_real_hass.states.async_set("binary_sensor.test_wb_left_cable_connected", "off")
    sem_real_hass.states.async_set("binary_sensor.test_wb_right_cable_connected", "off")
    sem_real_hass.states.async_set("sensor.test_wb_left_status", "idle")
    sem_real_hass.states.async_set("sensor.test_wb_right_status", "idle")

    await _setup_sem(sem_real_hass, sem_multi_wallbox_config_entry)

    # Partial submit: only charger 1 in the payload, with one field changed.
    await sem_real_hass.services.async_call(
        DOMAIN, "set_option",
        {"options": {"ev_chargers": [{"id": "ev_charger", "ev_target_soc": 85}]}},
        blocking=True,
    )
    await sem_real_hass.async_block_till_done()

    persisted = sem_multi_wallbox_config_entry.options.get("ev_chargers")
    assert persisted is not None, "ev_chargers must be persisted to options"
    by_id = {c["id"]: c for c in persisted}

    # Sibling preserved
    assert "ev_charger_1" in by_id, (
        "#464 regression: sibling charger (ev_charger_1) dropped after "
        "partial ev_chargers submit. Smart-merge by id is broken."
    )
    # Sibling's mode unchanged
    assert by_id["ev_charger_1"]["charge_mode"] == "solar_plus_cheap"
    # Modified charger has the new value
    assert by_id["ev_charger"]["ev_target_soc"] == 85
    # Modified charger's untouched fields preserved
    assert by_id["ev_charger"]["charge_mode"] == "always_max"


# ---------------------------------------------------------------------------
# Per-charger fallback contract — entry.data wins when options is missing (#469)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_charger_select_falls_back_to_entry_data(
    sem_real_hass, sem_multi_wallbox_config_entry,
) -> None:
    """A per-charger select write must fall back to ``entry.data.ev_chargers``
    when ``entry.options.ev_chargers`` is missing.

    Reproduces #469: a fresh install has ev_chargers in entry.data but
    not entry.options. If the per-charger select setter reads only
    entry.options, it iterates an empty list, no charger matches, and
    the write silently no-ops AND clobbers entry.options.ev_chargers
    with an empty list — which on next reload overrides entry.data's
    chargers via the standard merge.

    This test puts entry.options in the pre-#469 state (no ev_chargers
    key), flips a per-charger select, and asserts (a) the change took
    effect and (b) both chargers are still discoverable afterward.
    """
    _seed_sem_input_sensors(sem_real_hass)
    for eid in (
        "sensor.test_wb_left_charging_power", "sensor.test_wb_right_charging_power",
        "number.test_wb_left_max_current", "number.test_wb_right_max_current",
    ):
        sem_real_hass.states.async_set(eid, "0", {"unit_of_measurement": "W"})
    for eid in (
        "binary_sensor.test_wb_left_cable_connected",
        "binary_sensor.test_wb_right_cable_connected",
    ):
        sem_real_hass.states.async_set(eid, "off")
    for eid in ("sensor.test_wb_left_status", "sensor.test_wb_right_status"):
        sem_real_hass.states.async_set(eid, "idle")

    # Fresh-install state: ev_chargers in data, NOT in options.
    assert "ev_chargers" not in sem_multi_wallbox_config_entry.options
    assert "ev_chargers" in sem_multi_wallbox_config_entry.data

    await _setup_sem(sem_real_hass, sem_multi_wallbox_config_entry)

    # Flip charger 2's mode via its per-charger select.
    await sem_real_hass.services.async_call(
        "select", "select_option",
        {
            "entity_id": "select.sem_charger_ev_charger_1_charge_mode",
            "option": "off",
        },
        blocking=True,
    )
    await sem_real_hass.async_block_till_done()

    # (a) charger 2's mode updated in persisted state
    persisted = sem_multi_wallbox_config_entry.options.get("ev_chargers") or []
    by_id = {c["id"]: c for c in persisted if isinstance(c, dict)}
    assert by_id.get("ev_charger_1", {}).get("charge_mode") == "off", (
        "#469 regression: per-charger select write silently no-op'd "
        "because entry.options.ev_chargers was missing and the setter "
        "didn't fall back to entry.data.ev_chargers."
    )
    # (b) sibling charger preserved — NOT clobbered to empty
    assert "ev_charger" in by_id, (
        "#469 regression: sibling charger (ev_charger) dropped from "
        "entry.options.ev_chargers because the setter wrote [] back when "
        "it couldn't find the key in options."
    )


# ---------------------------------------------------------------------------
# Poisoned-storage heal (#462/#464 follow-up) — setup repairs a partial
# options.ev_chargers list left behind by v1.7.2..v1.7.3-beta.3 builds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_heals_poisoned_options_ev_chargers(
    sem_real_hass, sem_multi_wallbox_config_entry,
) -> None:
    """Setup must repair a PARTIAL ``options.ev_chargers`` list.

    The writer fixes (#467/#468/#469 + beta.4) stopped new corruption,
    but an install that went through the broken builds can already have
    options.ev_chargers = [charger 1 only] in storage (e.g. via the
    pre-#469 ``[]`` clobber followed by the auto-discovery reseed). The
    ``{**data, **options}`` merge then hides charger 2 forever: it never
    registers, and per-charger writes targeting its id silently no-op —
    the persistent "charger 2 does nothing" report on #462/#464.

    This test seeds exactly that storage shape, boots SEM, and asserts:
    (a) the options list is healed to contain both chargers, with the
    options-side field winning for the charger that was present;
    (b) charger 2 registered (its per-charger select exists);
    (c) a charger-2 mode flip lands in persisted options.
    """
    _seed_sem_input_sensors(sem_real_hass)
    for eid in (
        "sensor.test_wb_left_charging_power", "sensor.test_wb_right_charging_power",
        "number.test_wb_left_max_current", "number.test_wb_right_max_current",
    ):
        sem_real_hass.states.async_set(eid, "0", {"unit_of_measurement": "W"})
    for eid in (
        "binary_sensor.test_wb_left_cable_connected",
        "binary_sensor.test_wb_right_cable_connected",
    ):
        sem_real_hass.states.async_set(eid, "off")
    for eid in ("sensor.test_wb_left_status", "sensor.test_wb_right_status"):
        sem_real_hass.states.async_set(eid, "idle")

    entry = sem_multi_wallbox_config_entry
    entry.add_to_hass(sem_real_hass)
    # Poisoned shape: options has charger 1 ONLY (with a diverged mode),
    # data still has both chargers. Mirrors the auto-discovery reseed
    # aftermath seen on RienduPre's install.
    sem_real_hass.config_entries.async_update_entry(
        entry,
        options={
            "ev_chargers": [
                {
                    "id": "ev_charger",
                    "name": "Laadpaal Links",
                    "charge_mode": "always_max",
                },
            ],
        },
    )

    assert await sem_real_hass.config_entries.async_setup(entry.entry_id)
    await sem_real_hass.async_block_till_done()

    # (a) storage healed: both chargers back, options-side mode preserved
    healed = entry.options.get("ev_chargers") or []
    by_id = {c["id"]: c for c in healed if isinstance(c, dict)}
    assert set(by_id) == {"ev_charger", "ev_charger_1"}, (
        "setup-time heal did not restore the data-side sibling into "
        "options.ev_chargers — partial options list still shadows entry.data."
    )
    assert by_id["ev_charger"]["charge_mode"] == "always_max"
    assert by_id["ev_charger_1"]["charge_mode"] == "solar_plus_cheap"

    # (b) charger 2 actually registered — its per-charger select exists
    assert sem_real_hass.states.get(
        "select.sem_charger_ev_charger_1_charge_mode"
    ) is not None, (
        "charger 2 did not register its per-charger entities — the merged "
        "config at setup still came up without it."
    )

    # (c) a charger-2 write lands
    await sem_real_hass.services.async_call(
        "select", "select_option",
        {
            "entity_id": "select.sem_charger_ev_charger_1_charge_mode",
            "option": "off",
        },
        blocking=True,
    )
    await sem_real_hass.async_block_till_done()
    persisted = {
        c["id"]: c
        for c in (entry.options.get("ev_chargers") or [])
        if isinstance(c, dict)
    }
    assert persisted["ev_charger_1"]["charge_mode"] == "off"


# ---------------------------------------------------------------------------
# Diagnose recent_logs from the in-memory ring buffer (Supervisor installs
# have no flat log file — the #461/#462 triage ran blind on recent_logs)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnose_recent_logs_come_from_ring_buffer(
    sem_real_hass, sem_config_entry,
) -> None:
    """The diagnose payload's ``recent_logs`` must carry real SEM log lines
    captured by the ring buffer — independent of whether a flat
    ``home-assistant.log`` exists on disk (it doesn't on Supervisor)."""
    import logging as _logging

    _seed_sem_input_sensors(sem_real_hass)
    await _setup_sem(sem_real_hass, sem_config_entry)

    marker = "ring-buffer-framework-test-marker"
    _logging.getLogger(
        "custom_components.solar_energy_management.coordinator"
    ).info("%s", marker)

    response = await sem_real_hass.services.async_call(
        "solar_energy_management", "diagnose",
        {"section": "overview"},
        blocking=True,
        return_response=True,
    )
    logs = response["payload"]["recent_logs"]
    assert any(marker in line for line in logs), (
        "recent_logs did not include the in-memory buffer's records — "
        "Supervisor installs would still get the journald placeholder."
    )
    # Version comes from the cached manifest read (warmed off-loop at setup)
    assert response["payload"]["version"] not in ("unknown", "0.0.0")
