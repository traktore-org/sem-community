"""HA Repairs (issue_registry) helpers for SEM.

Thin wrappers over ``homeassistant.helpers.issue_registry``. Used as
the graceful-unavailability channel instead of log-spamming when
something is wrong with the user's setup. Each helper is idempotent —
calling ``raise_*`` multiple times only files one issue; ``clear_*``
on a non-existent issue is a no-op.

Translation keys live in ``strings.json`` under ``issues.<key>``;
add a matching entry when adding a new helper here.

Issues filed today:

  * ``sensor_unavailable_<entity_id>`` — a tracked sensor has been
    in ``unavailable`` / ``unknown`` for more than
    ``UNAVAILABLE_REPAIR_THRESHOLD_S`` seconds. Auto-clears on first
    successful read. The user sees one entry per sensor in
    Settings → System → Repairs.
  * ``no_forecast_integration`` — SEM looked for a Forecast.Solar /
    Solcast / OpenWeatherMap forecast entity at setup AND failed
    N retries during the first hours, so it never logged a
    one-shot info — now a Repair instead.
  * ``no_recorder`` — recorder integration not available, so
    ``async_seed_from_history`` cannot bootstrap EV / forecast
    history. Filed at setup, cleared if recorder appears later.

The legacy log-channel feedback ("the solar_energy_management
component should handle unavailability gracefully instead of
spamming", 2026-06-06) drove this work.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How long a sensor must be in ``unavailable`` / ``unknown`` before
# we surface it as a Repair. Below this, we treat the gap as a
# transient flap (e.g. Huawei modbus over WiFi bouncing every
# 10-30 s) and stay silent — log channel was already demoted in
# v1.7.1-beta.9.
UNAVAILABLE_REPAIR_THRESHOLD_S: int = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Per-sensor unavailability
# ---------------------------------------------------------------------------


def _sensor_issue_id(entity_id: str) -> str:
    """Stable per-entity issue id."""
    return f"sensor_unavailable_{entity_id}"


def raise_sensor_unavailable(
    hass: HomeAssistant,
    entity_id: str,
    *,
    friendly_name: str | None = None,
    minutes_unavailable: int = 5,
) -> None:
    """File a repair when ``entity_id`` has been unavailable past the
    threshold. Idempotent — HA's issue_registry handles dedup."""
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_sensor_issue_id(entity_id),
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="sensor_unavailable",
            translation_placeholders={
                "entity_id": entity_id,
                "friendly_name": friendly_name or entity_id,
                "minutes": str(minutes_unavailable),
            },
        )
    except Exception as e:  # noqa: BLE001 — never fail the cycle over a repair
        _LOGGER.debug("issue_registry.create failed for %s: %s", entity_id, e)


def clear_sensor_unavailable(hass: HomeAssistant, entity_id: str) -> None:
    """Clear the repair when ``entity_id`` recovers. No-op when no
    issue is filed."""
    try:
        ir.async_delete_issue(hass, DOMAIN, _sensor_issue_id(entity_id))
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete failed for %s: %s", entity_id, e)


# ---------------------------------------------------------------------------
# Setup-time integration checks (once per setup)
# ---------------------------------------------------------------------------


def raise_no_forecast_integration(hass: HomeAssistant) -> None:
    """File a repair when SEM has been running without a usable
    solar-forecast integration for long enough that the user
    presumably forgot to install one (vs first-boot configuring)."""
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id="no_forecast_integration",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="no_forecast_integration",
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.create no_forecast failed: %s", e)


def clear_no_forecast_integration(hass: HomeAssistant) -> None:
    try:
        ir.async_delete_issue(hass, DOMAIN, "no_forecast_integration")
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete no_forecast failed: %s", e)


def raise_no_recorder(hass: HomeAssistant) -> None:
    """File a repair when the recorder integration is unavailable —
    SEM can't bootstrap EV / forecast history from past states."""
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id="no_recorder",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="no_recorder",
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.create no_recorder failed: %s", e)


def clear_no_recorder(hass: HomeAssistant) -> None:
    try:
        ir.async_delete_issue(hass, DOMAIN, "no_recorder")
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete no_recorder failed: %s", e)
