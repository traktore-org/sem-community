"""Tests for the #432 heat-pump Repair issues.

Two new repair types in ``coordinator/repair_issues.py``:

  * ``heat_pump_relay_unavailable_<entity_id>`` — per-relay, fires after
    5 min of unavailable / unknown / missing entity, auto-clears on
    recovery. Mirrors the ``sensor_unavailable`` pattern.
  * ``heat_pump_partial_sg_ready`` — fires when exactly one of
    ``(relay1, relay2)`` is set without a climate fallback. Single fix
    per misconfig; auto-clears once the config is valid.

These are the user-visible diagnostic surface that replaces the silent
"controller registered but does nothing" failure mode pre-#432.
"""
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import repair_issues as ri


@pytest.fixture
def hass():
    """A bare hass mock — repair_issues helpers only call into
    homeassistant.helpers.issue_registry, which we patch per test."""
    return MagicMock()


# ── relay unavailable ──────────────────────────────────────────────


def test_raise_heat_pump_relay_unavailable_files_with_slot_and_entity(hass):
    """Filing the repair includes the slot + entity id in the issue id +
    translation placeholders, so the user sees WHICH relay to investigate."""
    with patch.object(ri.ir, "async_create_issue") as create:
        ri.raise_heat_pump_relay_unavailable(
            hass, "relay1", "switch.esp_relay1", minutes_unavailable=10,
        )
    create.assert_called_once()
    kwargs = create.call_args.kwargs
    assert kwargs["issue_id"] == "heat_pump_relay1_unavailable_switch.esp_relay1"
    assert kwargs["translation_key"] == "heat_pump_relay_unavailable"
    placeholders = kwargs["translation_placeholders"]
    assert placeholders["slot"] == "relay1"
    assert placeholders["entity_id"] == "switch.esp_relay1"
    assert placeholders["minutes"] == "10"


def test_raise_relay_unavailable_is_idempotent_across_slots(hass):
    """Each relay slot files its own issue id, so SEM can have both
    relay1 + relay2 outages reported simultaneously."""
    with patch.object(ri.ir, "async_create_issue") as create:
        ri.raise_heat_pump_relay_unavailable(hass, "relay1", "switch.r1")
        ri.raise_heat_pump_relay_unavailable(hass, "relay2", "switch.r2")
    assert create.call_count == 2
    ids = [c.kwargs["issue_id"] for c in create.call_args_list]
    assert ids[0] == "heat_pump_relay1_unavailable_switch.r1"
    assert ids[1] == "heat_pump_relay2_unavailable_switch.r2"


def test_clear_relay_unavailable_targets_the_right_issue_id(hass):
    """Clearing the repair must delete the SAME id we created — otherwise
    the issue persists in Settings → Repairs after the entity recovers."""
    with patch.object(ri.ir, "async_delete_issue") as delete:
        ri.clear_heat_pump_relay_unavailable(hass, "relay1", "switch.r1")
    delete.assert_called_once_with(
        hass, ri.DOMAIN, "heat_pump_relay1_unavailable_switch.r1",
    )


def test_raise_relay_unavailable_swallows_registry_errors(hass):
    """The repair helpers must never crash a coordinator cycle. Any
    issue_registry exception is logged at DEBUG and swallowed."""
    with patch.object(ri.ir, "async_create_issue", side_effect=RuntimeError("boom")):
        # Must not raise.
        ri.raise_heat_pump_relay_unavailable(hass, "relay1", "switch.r1")


# ── partial SG-Ready ────────────────────────────────────────────────


def test_raise_partial_sg_ready_uses_singleton_issue_id(hass):
    """One config = one issue. The id is fixed (not per-relay) so
    flipping which half is missing doesn't spawn a second open issue."""
    with patch.object(ri.ir, "async_create_issue") as create:
        ri.raise_heat_pump_partial_sg_ready(hass)
    create.assert_called_once()
    assert create.call_args.kwargs["issue_id"] == "heat_pump_partial_sg_ready"
    assert create.call_args.kwargs["translation_key"] == "heat_pump_partial_sg_ready"


def test_clear_partial_sg_ready_targets_the_singleton(hass):
    with patch.object(ri.ir, "async_delete_issue") as delete:
        ri.clear_heat_pump_partial_sg_ready(hass)
    delete.assert_called_once_with(
        hass, ri.DOMAIN, "heat_pump_partial_sg_ready",
    )


def test_raise_partial_sg_ready_swallows_registry_errors(hass):
    with patch.object(ri.ir, "async_create_issue", side_effect=RuntimeError("boom")):
        ri.raise_heat_pump_partial_sg_ready(hass)


# ── threshold sanity ───────────────────────────────────────────────


def test_unavailable_threshold_is_five_minutes():
    """The threshold constant is shared with the SensorReader pattern.
    Pin it so a refactor that bumps it doesn't silently change the
    user experience."""
    assert ri.UNAVAILABLE_REPAIR_THRESHOLD_S == 300


# ── orphan sweep (v1.7.2-beta.5, #448) ──────────────────────────────


def test_clear_orphan_sweep_removes_repairs_for_unconfigured_entities(hass):
    """Repairs from a PRIOR config must be swept when their entity is
    no longer in ``currently_configured_ids``. RienduPre #448 — user
    reconfigured from comfoair relays to nibe SG-Ready, but the
    comfoair repairs stayed stuck in the registry."""
    # Mock the registry's ``issues`` dict to contain stale + current repairs
    fake_registry = MagicMock()
    fake_registry.issues = {
        (ri.DOMAIN, "heat_pump_relay1_unavailable_switch.zolder_comfoair_a"): MagicMock(),
        (ri.DOMAIN, "heat_pump_relay2_unavailable_switch.zolder_comfoair_b"): MagicMock(),
        (ri.DOMAIN, "heat_pump_relay1_unavailable_switch.bijkeuken_nibe_a"): MagicMock(),
        # An unrelated repair from another integration must be ignored
        ("homeassistant", "some_other_issue"): MagicMock(),
        # A partial-SG-Ready repair from us — singleton, not entity-keyed — left alone
        (ri.DOMAIN, "heat_pump_partial_sg_ready"): MagicMock(),
    }

    with patch.object(ri.ir, "async_get", return_value=fake_registry), \
         patch.object(ri.ir, "async_delete_issue") as delete:
        cleared = ri.clear_orphan_heat_pump_relay_repairs(
            hass,
            currently_configured_ids={
                "switch.bijkeuken_nibe_a",
                "switch.bijkeuken_nibe_b",  # only b is configured but never raised
            },
        )

    # Both stale comfoair repairs cleared; the bijkeuken_nibe_a one
    # stays (still in current config); the cross-domain issue + the
    # partial-SG-Ready singleton are NOT touched.
    assert cleared == 2
    cleared_ids = {call.args[2] for call in delete.call_args_list}
    assert cleared_ids == {
        "heat_pump_relay1_unavailable_switch.zolder_comfoair_a",
        "heat_pump_relay2_unavailable_switch.zolder_comfoair_b",
    }


def test_clear_orphan_sweep_handles_empty_current_config(hass):
    """When no relays are configured (user removed heat pump entirely),
    ALL existing relay repairs must be swept."""
    fake_registry = MagicMock()
    fake_registry.issues = {
        (ri.DOMAIN, "heat_pump_relay1_unavailable_switch.a"): MagicMock(),
        (ri.DOMAIN, "heat_pump_relay2_unavailable_switch.b"): MagicMock(),
    }
    with patch.object(ri.ir, "async_get", return_value=fake_registry), \
         patch.object(ri.ir, "async_delete_issue") as delete:
        cleared = ri.clear_orphan_heat_pump_relay_repairs(
            hass, currently_configured_ids=set(),
        )
    assert cleared == 2
    assert delete.call_count == 2


def test_clear_orphan_sweep_returns_zero_when_no_orphans(hass):
    """Idempotent when there's nothing to clean — no errors, no deletes."""
    fake_registry = MagicMock()
    fake_registry.issues = {
        (ri.DOMAIN, "heat_pump_relay1_unavailable_switch.a"): MagicMock(),
    }
    with patch.object(ri.ir, "async_get", return_value=fake_registry), \
         patch.object(ri.ir, "async_delete_issue") as delete:
        cleared = ri.clear_orphan_heat_pump_relay_repairs(
            hass, currently_configured_ids={"switch.a"},
        )
    assert cleared == 0
    delete.assert_not_called()


def test_clear_orphan_sweep_swallows_registry_errors(hass):
    """Like other repair helpers, must never raise into the coordinator
    cycle — repair tracking is best-effort."""
    with patch.object(ri.ir, "async_get", side_effect=RuntimeError("boom")):
        cleared = ri.clear_orphan_heat_pump_relay_repairs(
            hass, currently_configured_ids={"switch.a"},
        )
    assert cleared == 0


# ── hot water repairs (v1.7.2-beta.7, #454 Phase 2) ─────────────────


def test_raise_hot_water_entity_unavailable_files_with_entity(hass):
    """Filing the boiler-control Repair includes the entity id in the
    issue id + translation placeholders."""
    with patch.object(ri.ir, "async_create_issue") as create:
        ri.raise_hot_water_entity_unavailable(
            hass, "switch.boiler", minutes_unavailable=8,
        )
    create.assert_called_once()
    kwargs = create.call_args.kwargs
    assert kwargs["issue_id"] == "hot_water_entity_unavailable_switch.boiler"
    assert kwargs["translation_key"] == "hot_water_entity_unavailable"
    assert kwargs["translation_placeholders"]["entity_id"] == "switch.boiler"
    assert kwargs["translation_placeholders"]["minutes"] == "8"


def test_raise_hot_water_temp_sensor_unavailable_distinct_issue_id(hass):
    """Boiler-entity and temp-sensor repairs MUST have distinct issue
    ids so they can coexist + clear independently."""
    with patch.object(ri.ir, "async_create_issue") as create:
        ri.raise_hot_water_entity_unavailable(hass, "switch.boiler")
        ri.raise_hot_water_temperature_sensor_unavailable(hass, "sensor.water_temp")
    assert create.call_count == 2
    issue_ids = {call.kwargs["issue_id"] for call in create.call_args_list}
    assert issue_ids == {
        "hot_water_entity_unavailable_switch.boiler",
        "hot_water_temperature_sensor_unavailable_sensor.water_temp",
    }


def test_clear_hot_water_entity_unavailable_targets_right_issue_id(hass):
    with patch.object(ri.ir, "async_delete_issue") as delete:
        ri.clear_hot_water_entity_unavailable(hass, "switch.boiler")
    delete.assert_called_once_with(
        hass, ri.DOMAIN, "hot_water_entity_unavailable_switch.boiler",
    )


def test_clear_hot_water_temp_sensor_unavailable_targets_right_issue_id(hass):
    with patch.object(ri.ir, "async_delete_issue") as delete:
        ri.clear_hot_water_temperature_sensor_unavailable(hass, "sensor.water_temp")
    delete.assert_called_once_with(
        hass, ri.DOMAIN, "hot_water_temperature_sensor_unavailable_sensor.water_temp",
    )


def test_raise_hot_water_repairs_swallow_registry_errors(hass):
    """Like all SEM repairs, must never raise into the coordinator cycle."""
    with patch.object(ri.ir, "async_create_issue", side_effect=RuntimeError("boom")):
        ri.raise_hot_water_entity_unavailable(hass, "switch.boiler")
        ri.raise_hot_water_temperature_sensor_unavailable(hass, "sensor.water_temp")
    # No exception raised — that's the test


def test_clear_orphan_hot_water_repairs_removes_unconfigured_entries(hass):
    """When user reconfigures the boiler entity (or removes it), the
    orphan repairs for the OLD entity must auto-clear. Mirror of the
    heat-pump orphan sweep shipped in beta.5."""
    fake_registry = MagicMock()
    fake_registry.issues = {
        (ri.DOMAIN, "hot_water_entity_unavailable_switch.old_boiler"): MagicMock(),
        (ri.DOMAIN, "hot_water_temperature_sensor_unavailable_sensor.old_temp"): MagicMock(),
        (ri.DOMAIN, "hot_water_entity_unavailable_switch.new_boiler"): MagicMock(),
        # Cross-domain + cross-feature repairs must be untouched
        ("homeassistant", "some_other"): MagicMock(),
        (ri.DOMAIN, "heat_pump_relay1_unavailable_switch.something"): MagicMock(),
    }
    with patch.object(ri.ir, "async_get", return_value=fake_registry), \
         patch.object(ri.ir, "async_delete_issue") as delete:
        cleared = ri.clear_orphan_hot_water_repairs(
            hass,
            currently_configured_entity="switch.new_boiler",
            currently_configured_temp_sensor=None,
        )
    # The old boiler + old temp sensor repairs cleared; the new boiler's
    # repair stays (still in config); the cross-domain + heat-pump
    # repairs untouched.
    assert cleared == 2
    cleared_ids = {call.args[2] for call in delete.call_args_list}
    assert cleared_ids == {
        "hot_water_entity_unavailable_switch.old_boiler",
        "hot_water_temperature_sensor_unavailable_sensor.old_temp",
    }


def test_clear_orphan_hot_water_repairs_handles_no_config(hass):
    """When user removes hot water entirely (both entity + temp sensor
    cleared), ALL hot-water repairs must be swept."""
    fake_registry = MagicMock()
    fake_registry.issues = {
        (ri.DOMAIN, "hot_water_entity_unavailable_switch.a"): MagicMock(),
        (ri.DOMAIN, "hot_water_temperature_sensor_unavailable_sensor.b"): MagicMock(),
    }
    with patch.object(ri.ir, "async_get", return_value=fake_registry), \
         patch.object(ri.ir, "async_delete_issue") as delete:
        cleared = ri.clear_orphan_hot_water_repairs(
            hass,
            currently_configured_entity=None,
            currently_configured_temp_sensor=None,
        )
    assert cleared == 2
    # The count alone would pass on a function that counts and deletes
    # nothing — assert the sweep actually reached the registry, as the
    # sibling test above does.
    assert {call.args[2] for call in delete.call_args_list} == {
        "hot_water_entity_unavailable_switch.a",
        "hot_water_temperature_sensor_unavailable_sensor.b",
    }
