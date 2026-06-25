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
from typing import Any, Optional

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


def _actuation_issue_id(device_id: str) -> str:
    return f"charger_actuation_failed_{device_id}"


def raise_charger_actuation_failed(
    hass: HomeAssistant,
    device_id: str,
    *,
    name: str,
    error: str,
) -> None:
    """File a repair when a charger rejects set-current commands repeatedly.

    #462 follow-up: a misconfigured control surface (e.g.
    ``number.set_value`` configured as the charger service, a renamed
    entity after an upstream integration update) made EVERY command fail
    with only per-cycle ERROR log lines as evidence. The user experience
    was "SEM doesn't react" with nothing actionable in the UI. Raised by
    ``CurrentControlDevice`` after 3 consecutive failures; cleared on the
    next successful write.
    """
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_actuation_issue_id(device_id),
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="charger_actuation_failed",
            translation_placeholders={
                "name": name,
                "error": error,
            },
        )
    except Exception as e:  # noqa: BLE001 — never fail the cycle over a repair
        _LOGGER.debug("issue_registry.create failed for %s: %s", device_id, e)


def clear_charger_actuation_failed(hass: HomeAssistant, device_id: str) -> None:
    """Clear the actuation repair after a successful write."""
    try:
        ir.async_delete_issue(hass, DOMAIN, _actuation_issue_id(device_id))
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete failed for %s: %s", device_id, e)


def _soc_cap_issue_id(device_id: str) -> str:
    return f"soc_cap_unenforceable_{device_id}"


def raise_soc_cap_unenforceable(
    hass: HomeAssistant,
    device_id: str,
    *,
    name: str,
    target_soc: float,
) -> None:
    """File a repair when an SOC-% charge target can't be enforced (#526).

    A charger set to a ``%`` target needs a readable vehicle SOC to stop at
    the cap. When the car isn't reporting SOC (asleep / no real sensor — the
    dashboard may still show an *estimated* SOC, which SEM deliberately
    ignores for the cap), SEM keeps charging until the car tapers. That
    surprised RienduPre ("car charged past 80%"). Surface it as a persistent,
    actionable repair instead of silently overshooting. Cleared the moment a
    real SOC reading returns (or the target is no longer SOC-based).
    """
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_soc_cap_issue_id(device_id),
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="soc_cap_unenforceable",
            translation_placeholders={
                "name": name,
                "target": f"{target_soc:.0f}",
            },
        )
    except Exception as e:  # noqa: BLE001 — never fail the cycle over a repair
        _LOGGER.debug("issue_registry.create failed for %s: %s", device_id, e)


def clear_soc_cap_unenforceable(hass: HomeAssistant, device_id: str) -> None:
    """Clear the SOC-cap repair once a real SOC reading is back."""
    try:
        ir.async_delete_issue(hass, DOMAIN, _soc_cap_issue_id(device_id))
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete failed for %s: %s", device_id, e)


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


# ---------------------------------------------------------------------------
# Heat pump misconfiguration (#432)
# ---------------------------------------------------------------------------


def _heat_pump_relay_issue_id(slot: str, entity_id: str) -> str:
    """Stable per-relay issue id. ``slot`` is ``"relay1"`` or ``"relay2"``."""
    return f"heat_pump_{slot}_unavailable_{entity_id}"


def raise_heat_pump_relay_unavailable(
    hass: HomeAssistant,
    slot: str,
    entity_id: str,
    *,
    minutes_unavailable: int = 5,
) -> None:
    """File a repair when a configured SG-Ready relay entity
    (``heat_pump_relay1_entity`` / ``heat_pump_relay2_entity``) has been
    ``unavailable`` / ``unknown`` / missing past the threshold.

    Surfaces the case where the user wired up ESP relays / Shelly
    switches and SEM cannot actually toggle them — silent failure pre-
    #432 (the heat pump controller registers happily, then no-ops on
    every command). The user sees one entry per relay in
    Settings → System → Repairs telling them which entity to fix.
    """
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_heat_pump_relay_issue_id(slot, entity_id),
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="heat_pump_relay_unavailable",
            translation_placeholders={
                "slot": slot,
                "entity_id": entity_id,
                "minutes": str(minutes_unavailable),
            },
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug(
            "issue_registry.create heat_pump_relay_unavailable failed for %s/%s: %s",
            slot, entity_id, e,
        )


def clear_heat_pump_relay_unavailable(
    hass: HomeAssistant, slot: str, entity_id: str,
) -> None:
    """Clear the relay repair when the entity reports a real state."""
    try:
        ir.async_delete_issue(
            hass, DOMAIN, _heat_pump_relay_issue_id(slot, entity_id),
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug(
            "issue_registry.delete heat_pump_relay_unavailable failed for %s/%s: %s",
            slot, entity_id, e,
        )


# ---------------------------------------------------------------------------
# Hot water misconfiguration (#454)
# ---------------------------------------------------------------------------


def _hot_water_entity_issue_id(entity_id: str) -> str:
    """Stable issue id for the boiler-control entity Repair."""
    return f"hot_water_entity_unavailable_{entity_id}"


def _hot_water_temp_sensor_issue_id(entity_id: str) -> str:
    """Stable issue id for the temperature-sensor Repair."""
    return f"hot_water_temperature_sensor_unavailable_{entity_id}"


def raise_hot_water_entity_unavailable(
    hass: HomeAssistant,
    entity_id: str,
    *,
    minutes_unavailable: int = 5,
) -> None:
    """File a repair when the configured ``hot_water_entity`` (the
    boiler control — switch/water_heater/climate) has been unavailable
    past the threshold.

    Without this, SEM can register the controller fine but every
    surplus-dispatch command no-ops silently — the boiler is never
    actually controlled. Mirrors the heat_pump_relay_unavailable
    pattern (#432)."""
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_hot_water_entity_issue_id(entity_id),
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="hot_water_entity_unavailable",
            translation_placeholders={
                "entity_id": entity_id,
                "minutes": str(minutes_unavailable),
            },
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug(
            "issue_registry.create hot_water_entity_unavailable failed for %s: %s",
            entity_id, e,
        )


def clear_hot_water_entity_unavailable(
    hass: HomeAssistant, entity_id: str,
) -> None:
    """Clear the boiler-control Repair when the entity recovers."""
    try:
        ir.async_delete_issue(
            hass, DOMAIN, _hot_water_entity_issue_id(entity_id),
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug(
            "issue_registry.delete hot_water_entity_unavailable failed for %s: %s",
            entity_id, e,
        )


def raise_hot_water_temperature_sensor_unavailable(
    hass: HomeAssistant,
    entity_id: str,
    *,
    minutes_unavailable: int = 5,
) -> None:
    """File a repair when the configured ``hot_water_temperature_sensor``
    has been unavailable past the threshold.

    Distinct from the boiler-entity repair because the safety semantics
    differ: a broken temp sensor causes ``is_temperature_safe()`` to
    return False (post-#420 fail-safe), which means SEM stops activating
    the boiler entirely. The user needs to KNOW why the boiler stopped
    responding to surplus — this Repair surfaces it."""
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_hot_water_temp_sensor_issue_id(entity_id),
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="hot_water_temperature_sensor_unavailable",
            translation_placeholders={
                "entity_id": entity_id,
                "minutes": str(minutes_unavailable),
            },
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug(
            "issue_registry.create hot_water_temperature_sensor_unavailable failed for %s: %s",
            entity_id, e,
        )


def clear_hot_water_temperature_sensor_unavailable(
    hass: HomeAssistant, entity_id: str,
) -> None:
    """Clear the temp-sensor Repair when the entity recovers."""
    try:
        ir.async_delete_issue(
            hass, DOMAIN, _hot_water_temp_sensor_issue_id(entity_id),
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug(
            "issue_registry.delete hot_water_temperature_sensor_unavailable failed for %s: %s",
            entity_id, e,
        )


def clear_orphan_hot_water_repairs(
    hass: HomeAssistant,
    *,
    currently_configured_entity: Optional[str],
    currently_configured_temp_sensor: Optional[str],
) -> int:
    """Sweep orphan hot-water repairs whose entity_id is no longer in
    config. Same pattern as ``clear_orphan_heat_pump_relay_repairs``:
    user reconfigures the boiler from ``switch.old`` to ``switch.new``,
    new entity works (no new repair), old repair stuck in the registry.

    Returns the count cleared."""
    try:
        registry = ir.async_get(hass)
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.async_get failed during orphan sweep: %s", e)
        return 0

    cleared = 0
    keep_entity = {currently_configured_entity} if currently_configured_entity else set()
    keep_temp = {currently_configured_temp_sensor} if currently_configured_temp_sensor else set()
    try:
        candidates: list[str] = []
        for (domain, issue_id) in list(registry.issues.keys()):
            if domain != DOMAIN:
                continue
            if issue_id.startswith("hot_water_entity_unavailable_"):
                eid = issue_id[len("hot_water_entity_unavailable_"):]
                if eid not in keep_entity:
                    candidates.append(issue_id)
            elif issue_id.startswith("hot_water_temperature_sensor_unavailable_"):
                eid = issue_id[len("hot_water_temperature_sensor_unavailable_"):]
                if eid not in keep_temp:
                    candidates.append(issue_id)
        for issue_id in candidates:
            try:
                ir.async_delete_issue(hass, DOMAIN, issue_id)
                cleared += 1
                _LOGGER.info(
                    "Cleared orphan hot-water repair: %s "
                    "(entity no longer in SEM config)",
                    issue_id,
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug(
                    "issue_registry.delete failed for orphan %s: %s",
                    issue_id, e,
                )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("Orphan hot-water repair sweep failed: %s", e)

    return cleared


def clear_orphan_heat_pump_relay_repairs(
    hass: HomeAssistant,
    *,
    currently_configured_ids: set[str],
) -> int:
    """Sweep the issue registry for ``heat_pump_relayN_unavailable_<entity_id>``
    issues whose ``<entity_id>`` is NOT in the currently-configured set, and
    delete them.

    Fixes the orphan-repair class of bug: user reconfigures from
    ``switch.old_entity_a`` to ``switch.new_entity_b``, the new relays are
    healthy so no new repair fires, but the OLD repair filed against
    ``switch.old_entity_a`` stays in the registry indefinitely because the
    per-cycle clear path only addresses CURRENTLY-configured entities.
    Reported live by RienduPre on #448 (2026-06-08).

    Returns the count of orphan repairs cleared, for log visibility.
    """
    try:
        registry = ir.async_get(hass)
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.async_get failed during orphan-sweep: %s", e)
        return 0

    cleared = 0
    try:
        # ``registry.issues`` is a dict keyed by ``(domain, issue_id)``.
        # We can't iterate-and-mutate, so collect first.
        candidates: list[str] = []
        for (domain, issue_id) in list(registry.issues.keys()):
            if domain != DOMAIN:
                continue
            # Issue ids: heat_pump_relay1_unavailable_<entity_id>
            #            heat_pump_relay2_unavailable_<entity_id>
            for prefix in ("heat_pump_relay1_unavailable_", "heat_pump_relay2_unavailable_"):
                if issue_id.startswith(prefix):
                    eid = issue_id[len(prefix):]
                    if eid not in currently_configured_ids:
                        candidates.append(issue_id)
                    break
        for issue_id in candidates:
            try:
                ir.async_delete_issue(hass, DOMAIN, issue_id)
                cleared += 1
                _LOGGER.info(
                    "Cleared orphan heat-pump relay repair: %s "
                    "(entity no longer in SEM config)",
                    issue_id,
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug(
                    "issue_registry.delete failed for orphan %s: %s",
                    issue_id, e,
                )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("Orphan heat-pump-repair sweep failed: %s", e)

    return cleared


def raise_heat_pump_partial_sg_ready(hass: HomeAssistant) -> None:
    """File a repair when exactly one of the two SG-Ready relays is
    configured AND no climate fallback is set. The SG-Ready protocol
    needs BOTH relays (it encodes the four states as a 2-bit binary).
    A single relay is a config mistake the user almost certainly
    didn't intend.
    """
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id="heat_pump_partial_sg_ready",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="heat_pump_partial_sg_ready",
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug(
            "issue_registry.create heat_pump_partial_sg_ready failed: %s", e,
        )


def clear_heat_pump_partial_sg_ready(hass: HomeAssistant) -> None:
    try:
        ir.async_delete_issue(hass, DOMAIN, "heat_pump_partial_sg_ready")
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug(
            "issue_registry.delete heat_pump_partial_sg_ready failed: %s", e,
        )


# ---------------------------------------------------------------------------
# KEBA failsafe enabled (#546)
# ---------------------------------------------------------------------------

# Where the user is sent to fix it (how + why to disable the KEBA failsafe).
KEBA_FAILSAFE_DOC_URL = (
    "https://github.com/traktore-org/sem-community/blob/main/docs/KEBA_FAILSAFE.md"
)


def raise_keba_failsafe_active(
    hass: HomeAssistant, *, charger_name: str,
) -> None:
    """File a repair when a KEBA charger's failsafe watchdog is enabled (#546).

    The KEBA failsafe drops the offered current to a fallback (6 A) when the
    controller goes quiet; SEM re-asserts the target every cycle, producing the
    6↔9 A flap a steady-needing car can't charge through. evcc (the reference
    implementation) DISABLES the KEBA failsafe for exactly this reason — and so
    does SEM now (it no longer arms it). But the box keeps its OWN failsafe
    until the user turns it off at the charger, which HA's keba.set_failsafe
    service can't do (it rejects timeout 0). So surface an actionable Repair
    that walks them through it. Cleared the moment the failsafe reads off.
    """
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id="keba_failsafe_active",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="keba_failsafe_active",
            translation_placeholders={"name": charger_name},
            learn_more_url=KEBA_FAILSAFE_DOC_URL,
        )
    except Exception as e:  # noqa: BLE001 — never fail the cycle over a repair
        _LOGGER.debug("issue_registry.create keba_failsafe_active failed: %s", e)


def clear_keba_failsafe_active(hass: HomeAssistant) -> None:
    """Clear the KEBA-failsafe Repair once the failsafe reads off."""
    try:
        ir.async_delete_issue(hass, DOMAIN, "keba_failsafe_active")
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete keba_failsafe_active failed: %s", e)


def detect_keba_failsafe_state(hass: HomeAssistant) -> Optional[bool]:
    """Best-effort read of the KEBA failsafe state from the keba integration's
    ``binary_sensor.*failsafe*`` entity.

    Returns True (on / armed), False (off), or None when no such sensor exists
    (can't tell → stay silent). Brand-agnostic by entity-id match so it works
    regardless of the charger's HA name.
    """
    try:
        for state in hass.states.async_all("binary_sensor"):
            if "failsafe" in state.entity_id:
                if state.state == "on":
                    return True
                if state.state == "off":
                    return False
        return None
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("detect_keba_failsafe_state failed: %s", e)
        return None
