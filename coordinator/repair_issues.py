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
import re
import urllib.parse
from typing import Optional

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
            learn_more_url=next_step_url("docs", "sensor_unavailable", **_versions(hass)),
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


def _stale_issue_id(entity_id: str) -> str:
    """Stable per-entity issue id for a FROZEN (available-but-stale) sensor."""
    return f"sensor_stale_{entity_id}"


def raise_sensor_stale(
    hass: HomeAssistant,
    entity_id: str,
    *,
    friendly_name: str | None = None,
    minutes_stale: int = 10,
) -> None:
    """File a repair when a fast power ``entity_id`` is 'available' but has not
    updated past the freeze threshold (#589 W3). Idempotent."""
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_stale_issue_id(entity_id),
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="sensor_stale",
            learn_more_url=next_step_url("docs", "sensor_stale", **_versions(hass)),
            translation_placeholders={
                "entity_id": entity_id,
                "friendly_name": friendly_name or entity_id,
                "minutes": str(minutes_stale),
            },
        )
    except Exception as e:  # noqa: BLE001 — never fail the cycle over a repair
        _LOGGER.debug("issue_registry.create (stale) failed for %s: %s", entity_id, e)


def clear_sensor_stale(hass: HomeAssistant, entity_id: str) -> None:
    """Clear the frozen-sensor repair when ``entity_id`` updates again."""
    try:
        ir.async_delete_issue(hass, DOMAIN, _stale_issue_id(entity_id))
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete (stale) failed for %s: %s", entity_id, e)


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
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="charger_actuation_failed",
            data={"copy_context": copy_context(
                "charger_actuation_failed", reason=str(error or ""), brand=str(name or ""), **_versions(hass))},
            learn_more_url=next_step_url(
                "report", "charger_actuation_failed",
                reason=str(error or ""), brand=str(name or ""),
                **_versions(hass)),
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


# ── #831: every repair offers the next step ─────────────────────────────────
# A repair card is the one moment SEM has the user's attention WITH the
# context in hand. Two kinds of repair, two kinds of link — mixing them would
# flood the tracker with user-side misconfigurations:
#   docs   → "your setup needs attention": a TROUBLESHOOTING.md anchor.
#   report → "this looks like SEM's fault": a bug-report form with the
#            context prefilled (GitHub issue forms accept per-field prefill
#            by id). The user reviews and presses the button — or does not.
# Privacy is load-bearing: versions, repair key and reason travel; entity ids
# and diagnostics NEVER do (URLs are proxy-logged and truncate ~8 KB).

_REPO_URL = "https://github.com/traktore-org/sem-community"
_ENTITY_ID_RE = re.compile(
    r"\b(?:sensor|binary_sensor|number|switch|select|button|input_\w+|climate|"
    r"water_heater|light|cover)\.[a-z0-9_]+")

#: docs-side repair key → TROUBLESHOOTING.md anchor. Pinned by
#: tests/test_831_repair_next_step.py — every anchor must resolve to a real
#: heading, the #219 lesson shape.
_DOCS_ANCHORS = {
    "sensor_unavailable": "a-configured-sensor-is-unavailable",
    "sensor_stale": "a-sensor-stopped-updating-stale",
    "no_forecast_integration": "no-solar-forecast-integration-found",
    "no_recorder": "the-recorder-is-not-available",
    "heat_pump_relay_unavailable": "heat-pump-sg-ready-relay-unavailable",
    "hot_water_entity_unavailable": "hot-water-switch-unavailable",
    "hot_water_temperature_sensor_unavailable":
        "hot-water-temperature-sensor-unavailable",
    "heat_pump_partial_sg_ready": "heat-pump-only-one-sg-ready-relay",
    "charger_control_entity_broken": "a-charger-control-entity-is-broken",
    # KEBA has a dedicated deep-dive doc — richer than a troubleshooting
    # section, so the builder serves it whole (a full URL passes through).
    "keba_failsafe_active":
        "https://github.com/traktore-org/sem-community/blob/develop/docs/KEBA_FAILSAFE.md",
    "charger_failsafe_suspected": "your-wallbox-undoes-sems-stop-on-a-timer",
    "battery_force_discharge_unsupported":
        "the-inverter-refuses-forced-discharge",
    "deye_system_work_mode_invalid": "deye-system-work-mode-setup-cannot-be-used",
    "battery_operating_mode_unexpected":
        "the-battery-is-in-a-mode-sem-does-not-expect",
}


def copy_context(key: str, *, reason: str = "", brand: str = "",
                 sem_version: str = "", ha_version: str = "") -> str:
    """The selectable text the RepairsFlow shows (#831) — same fields as the
    report URL, same privacy rule (the caller passes scrubbed reasons)."""
    lines = [f"Repair: {key}"]
    if brand:
        lines.append(f"Hardware: {brand}")
    if sem_version:
        lines.append(f"SEM: {sem_version}")
    if ha_version:
        lines.append(f"Home Assistant: {ha_version}")
    if reason:
        lines.append(f"Detail: {_ENTITY_ID_RE.sub('(entity)', str(reason))}")
    return "\n".join(lines)


def _docs_ref(sem_version: str) -> str:
    """(2.1 audit, item 7) A beta runs from develop; its docs anchors do not
    exist on main until the stable merge. Link the branch the running
    version came from, so a repair's deep link never 404s from a beta."""
    v = str(sem_version or "")
    return "develop" if ("beta" in v or "rc" in v or not v) else "main"


def next_step_url(kind: str, key: str, *, reason: str = "",
                  sem_version: str = "", ha_version: str = "",
                  brand: str = "") -> str:
    """The one builder — no call site hand-rolls a URL (#831).

    ``kind="docs"`` → a TROUBLESHOOTING anchor. ``kind="report"`` → the
    bug-report form, prefilled. Only FREE-TEXT fields are prefilled:
    ``inverter``/``charger`` are dropdowns and a value that does not exactly
    match an option renders empty — the brand rides the description line
    instead, where it survives any option-list rename.
    """
    if kind == "docs":
        anchor = _DOCS_ANCHORS.get(key, "")
        ref = _docs_ref(sem_version)
        if anchor.startswith("http"):
            return anchor.replace("/blob/develop/", f"/blob/{ref}/").replace(
                "/blob/main/", f"/blob/{ref}/")
        return f"{_REPO_URL}/blob/{ref}/docs/TROUBLESHOOTING.md#{anchor}"
    # Entity ids never enter a logged URL — scrub even when a reason string
    # embeds one (they routinely do; that is the card's job, not the URL's).
    clean_reason = _ENTITY_ID_RE.sub("(entity)", str(reason or ""))
    desc = f"Repair: {key}"
    if brand:
        desc += f" — {brand}"
    if clean_reason:
        desc += f" — {clean_reason}"
    q = urllib.parse.urlencode({
        "template": "bug_report.yml",
        "sem-version": sem_version or "",
        "ha-version": ha_version or "",
        "description": desc,
    })
    return f"{_REPO_URL}/issues/new?{q}"


def _versions(hass: HomeAssistant) -> dict:
    """SEM + HA versions for the report prefill, resolved in one place."""
    sem = ""
    try:
        integ = hass.data.get("integrations", {}).get(DOMAIN)
        v = getattr(integ, "version", None)
        sem = v if isinstance(v, str) else ""
    except Exception:  # noqa: BLE001
        sem = ""
    if not sem:
        try:
            v = hass.data.get(DOMAIN, {}).get("_manifest_version")
            sem = v if isinstance(v, str) else ""
        except Exception:  # noqa: BLE001
            sem = ""
    try:
        from homeassistant.const import __version__ as ha_ver
    except Exception:  # noqa: BLE001
        ha_ver = ""
    return {"sem_version": sem, "ha_version": ha_ver if isinstance(ha_ver, str) else ""}


def raise_battery_operating_mode_unexpected(hass: HomeAssistant, entity_id: str,
                                            *, mode: str, expected: str) -> None:
    """(#845) The inverter's operating-policy selector is in a mode SEM's
    model does not expect. Observe-only: not fixable in-app, because a
    deliberate ``fully_fed_to_grid`` is a legitimate choice SEM must not
    fight — the Repair names the disagreement and the user decides."""
    try:
        ir.async_create_issue(
            hass, domain=DOMAIN,
            issue_id=f"battery_operating_mode_unexpected_{entity_id}",
            is_fixable=False, is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="battery_operating_mode_unexpected",
            translation_placeholders={
                "entity_id": entity_id, "mode": str(mode),
                "expected": str(expected),
            },
            learn_more_url=next_step_url(
                "docs", "battery_operating_mode_unexpected",
                **_versions(hass)),
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.create failed for %s: %s", entity_id, e)


def clear_battery_operating_mode_unexpected(hass: HomeAssistant, entity_id: str) -> None:
    try:
        ir.async_delete_issue(
            hass, DOMAIN, f"battery_operating_mode_unexpected_{entity_id}")
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete failed for %s: %s", entity_id, e)


def raise_deye_system_work_mode_invalid(hass: HomeAssistant, entity_id: str,
                                        *, reason: str) -> None:
    """(#827, 2.1 audit) A System Work Mode setup SEM cannot use — the reason
    used to land in a private attribute nobody reads."""
    try:
        ir.async_create_issue(
            hass, domain=DOMAIN,
            issue_id=f"deye_system_work_mode_invalid_{entity_id}",
            is_fixable=False, is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="deye_system_work_mode_invalid",
            translation_placeholders={"entity_id": entity_id, "reason": reason},
            learn_more_url=next_step_url("docs", "deye_system_work_mode_invalid",
                                         **_versions(hass)),
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.create failed for %s: %s", entity_id, e)


def clear_deye_system_work_mode_invalid(hass: HomeAssistant, entity_id: str) -> None:
    try:
        ir.async_delete_issue(hass, DOMAIN, f"deye_system_work_mode_invalid_{entity_id}")
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete failed for %s: %s", entity_id, e)


def _failsafe_issue_id(device_id: str) -> str:
    return f"charger_failsafe_suspected_{device_id}"


def raise_charger_failsafe_suspected(
    hass: HomeAssistant, device_id: str, *, name: str, interval_s: float,
) -> None:
    """(#823) The box re-enabled itself on a CONSTANT interval after SEM's
    stop — a charger-side failsafe/controller-timeout fallback. SEM cannot
    write failsafe registers on a generic charger and must not guess register
    numbers; the fix is a one-time change on the box, so this is instruction,
    not war (#763)."""
    try:
        ir.async_create_issue(
            hass, domain=DOMAIN,
            issue_id=_failsafe_issue_id(device_id),
            is_fixable=False, is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="charger_failsafe_suspected",
            learn_more_url=next_step_url("docs", "charger_failsafe_suspected", **_versions(hass)),
            translation_placeholders={
                "name": name, "interval_s": str(int(interval_s)),
            },
        )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.create failed for %s: %s", device_id, e)


def clear_charger_failsafe_suspected(hass: HomeAssistant, device_id: str) -> None:
    try:
        ir.async_delete_issue(hass, DOMAIN, _failsafe_issue_id(device_id))
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete failed for %s: %s", device_id, e)


def _battery_force_discharge_issue_id(entity_id: str) -> str:
    return f"battery_force_discharge_unsupported_{entity_id}"


def raise_battery_force_discharge_unsupported(
    hass: HomeAssistant,
    entity_id: str,
    *,
    error: str,
) -> None:
    """File a repair when the battery refuses the forcible-discharge write.

    (#840) @RienduPre's Growatt exposes the setpoint entity but its firmware
    does not implement the write, so every attempt was rejected — 2,364 log
    lines in nineteen hours. SEM now stops asking after three refusals, but
    stopping quietly would trade one silent failure for another: the user
    configured battery-to-grid export and it would simply never happen.

    #799's lesson applies — a log line is not a surface. Raised once the
    capability is withdrawn; cleared the moment a write succeeds again.
    """
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_battery_force_discharge_issue_id(entity_id),
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="battery_force_discharge_unsupported",
            learn_more_url=next_step_url("docs", "battery_force_discharge_unsupported", **_versions(hass)),
            translation_placeholders={
                "entity_id": entity_id,
                "error": error,
            },
        )
    except Exception as e:  # noqa: BLE001 — never fail the cycle over a repair
        _LOGGER.debug("issue_registry.create failed for %s: %s", entity_id, e)


def clear_battery_force_discharge_unsupported(
    hass: HomeAssistant, entity_id: str,
) -> None:
    """Clear it once the device accepts a setpoint again."""
    try:
        ir.async_delete_issue(
            hass, DOMAIN, _battery_force_discharge_issue_id(entity_id))
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete failed for %s: %s", entity_id, e)


def _stop_unenforceable_issue_id(device_id: str) -> str:
    return f"charger_stop_unenforceable_{device_id}"


def raise_charger_stop_unenforceable(
    hass: HomeAssistant,
    device_id: str,
    *,
    name: str,
    power_w: float,
    entity: str,
) -> None:
    """File a repair when NOTHING SEM can call will stop this charger (#627).

    Distinct from ``charger_actuation_failed``, which means a command was
    sent and rejected. Here no command exists to send: the charger was
    configured with only a current-control ``number.*`` entity whose minimum
    is 6 A, so the 0 A stop is unwritable (#487) and no brand stop mechanism
    is configured either. SEM keeps asking; the car keeps charging.

    That is worth a hard ERROR rather than a log line, because the power has
    to come from somewhere: onkelfu's install pulled 4.1 kW for hours with
    3.5 kW of it out of the house batteries, at night, with the charger set
    to *off*. Cleared as soon as the charger stops drawing.
    """
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_stop_unenforceable_issue_id(device_id),
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="charger_stop_unenforceable",
            data={"copy_context": copy_context(
                "charger_stop_unenforceable", reason=f"stop unenforceable at {power_w:.0f} W", brand=str(name or ""), **_versions(hass))},
            learn_more_url=next_step_url(
                "report", "charger_stop_unenforceable",
                reason=f"stop unenforceable at {power_w:.0f} W", brand=str(name or ""),
                **_versions(hass)),
            translation_placeholders={
                "name": name,
                "power": f"{power_w:.0f}",
                "entity": entity,
            },
        )
    except Exception as e:  # noqa: BLE001 — never fail the cycle over a repair
        _LOGGER.debug("issue_registry.create failed for %s: %s", device_id, e)


def clear_charger_stop_unenforceable(hass: HomeAssistant, device_id: str) -> None:
    """Clear the #627 repair once the charger is no longer drawing."""
    try:
        ir.async_delete_issue(hass, DOMAIN, _stop_unenforceable_issue_id(device_id))
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

    A charger set to a ``%`` target needs a readable vehicle SOC to stop
    exactly at the cap. When the car isn't reporting SOC (asleep / no real
    sensor — the dashboard may still show an *estimated* SOC, which SEM
    deliberately ignores for the cap), the stop lands approximately: from the
    last real reading of the session SEM counts delivered energy and stops on
    that measured total, so the overshoot is only what the car took since the
    reading. With no reading at all this session (or a restart mid-charge)
    there is nothing to count from and it runs to the car's own taper — the
    case that surprised RienduPre ("car charged past 80%"). Surface it as a
    persistent, actionable repair instead of silently overshooting. Cleared
    the moment a real SOC reading returns (or the target is no longer
    SOC-based).

    (#708) Raised per charger and gated on THIS charger's connection state at
    the call site — see ``coordinator._maybe_warn_soc_cap``.
    """
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_soc_cap_issue_id(device_id),
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="soc_cap_unenforceable",
            data={"copy_context": copy_context(
                "soc_cap_unenforceable", reason=f"SOC cap {target_soc:.0f}% unenforceable", brand=str(name or ""), **_versions(hass))},
            learn_more_url=next_step_url(
                "report", "soc_cap_unenforceable",
                reason=f"SOC cap {target_soc:.0f}% unenforceable", brand=str(name or ""),
                **_versions(hass)),
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
            learn_more_url=next_step_url("docs", "no_forecast_integration", **_versions(hass)),
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
            learn_more_url=next_step_url("docs", "no_recorder", **_versions(hass)),
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
            learn_more_url=next_step_url("docs", "heat_pump_relay_unavailable", **_versions(hass)),
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
            learn_more_url=next_step_url("docs", "hot_water_entity_unavailable", **_versions(hass)),
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
            learn_more_url=next_step_url("docs", "hot_water_temperature_sensor_unavailable", **_versions(hass)),
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
            learn_more_url=next_step_url("docs", "heat_pump_partial_sg_ready", **_versions(hass)),
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
            learn_more_url=next_step_url("docs", "keba_failsafe_active", **_versions(hass)),
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
    failsafe binary sensor (e.g. ``binary_sensor.keba_p30_failsafe_mode``).

    Returns:
      * True  — failsafe is ON (armed).
      * False — failsafe is OFF.
      * None  — no such sensor, or it's ``unavailable``/``unknown`` (KEBA offline).
                "Can't tell" → the caller HOLDS the current Repair state rather
                than clearing it on a transient outage.

    Scoped to entity ids containing BOTH ``keba`` and ``failsafe`` (M3) so an
    unrelated integration's ``*_failsafe`` binary sensor (UPS, inverter battery
    protection) can't trigger a spurious KEBA Repair.
    """
    try:
        for state in hass.states.async_all("binary_sensor"):
            eid = state.entity_id
            if "keba" in eid and "failsafe" in eid:
                if state.state == "on":
                    return True
                if state.state == "off":
                    return False
                # unavailable/unknown → can't tell; keep looking, else None.
        return None
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("detect_keba_failsafe_state failed: %s", e)
        return None


def _control_entity_issue_id(device_id: str, entity_id: str) -> str:
    """Stable per-charger, per-entity issue id."""
    return f"charger_control_entity_broken_{device_id}_{entity_id}"


def raise_charger_control_entity_broken(
    hass: HomeAssistant,
    device_id: str,
    *,
    name: str,
    entity_id: str,
    capability: str,
    reason: str,
) -> None:
    """File a repair when a charger's configured CONTROL entity cannot be
    commanded (#824).

    Distinct from ``charger_actuation_failed`` on purpose. That one fires
    after three writes that RAISED — and the case this exists for produces
    no error at all: @onkelfu's template number carried an unsupported
    ``mode: slider``, so HA never loaded it (``restored: true``) and every
    write SEM made landed nowhere, silently, for days. A dead control
    entity makes SEM look like it is working while the car does whatever
    it likes, which is why this is a pre-flight check rather than error
    handling.

    ``reason`` is one of ``wrong_domain`` / ``missing`` / ``unavailable``.
    """
    try:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id=_control_entity_issue_id(device_id, entity_id),
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="charger_control_entity_broken",
            learn_more_url=next_step_url("docs", "charger_control_entity_broken", **_versions(hass)),
            translation_placeholders={
                "name": name,
                "entity_id": entity_id,
                "capability": capability,
                "reason": reason,
            },
        )
    except Exception as e:  # noqa: BLE001 — never fail the cycle over a repair
        _LOGGER.debug("issue_registry.create failed for %s: %s", entity_id, e)


def clear_charger_control_entity_broken(
    hass: HomeAssistant, device_id: str, entity_id: str,
) -> None:
    """Clear it the moment the entity becomes commandable again."""
    try:
        ir.async_delete_issue(
            hass, DOMAIN, _control_entity_issue_id(device_id, entity_id))
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("issue_registry.delete failed for %s: %s", entity_id, e)
