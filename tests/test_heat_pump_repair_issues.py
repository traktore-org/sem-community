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
