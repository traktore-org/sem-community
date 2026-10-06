"""Replay a capture into a real Home Assistant test instance, then run SEM's
crawler on it.

A capture (``captures/<name>.json``) is one integration's real output at a
pin — see ``PINS.md``. Replaying it registers the integration's config
entry, its devices, every entity with the metadata the crawler reads
(translation key, unique id, device class, unit, capabilities), the state
Home Assistant held, and the services it registered. The crawler then sees
exactly what it would see on an install running that integration.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

CAPTURES = Path(__file__).resolve().parent / "captures"


def capture_names() -> List[str]:
    return sorted(p.stem for p in CAPTURES.glob("*.json"))


def load_capture(name: str) -> Dict[str, Any]:
    return json.loads((CAPTURES / f"{name}.json").read_text())


async def replay(hass, capture: Dict[str, Any], *,
                 suffix: str = "") -> Dict[str, str]:
    """Register ``capture`` in ``hass``. Returns ``{device key: device id}``.

    ``suffix`` is appended to every object id and unique id, so two captures
    that happen to use the same test names (two Tesla car integrations) can
    live in one instance as two cars."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    domain = capture["domain"]
    entry = MockConfigEntry(domain=domain, title=f"rig {domain}")
    entry.add_to_hass(hass)
    dreg, ereg = dr.async_get(hass), er.async_get(hass)
    device_ids: Dict[str, str] = {}
    for key, meta in capture.get("devices", {}).items():
        ident = tuple((key + suffix).split(":", 1)) if ":" in key else (domain, key + suffix)
        dev = dreg.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={ident},
            name=meta.get("name"), model=meta.get("model"),
            manufacturer=meta.get("manufacturer"))
        device_ids[key] = dev.id
    for row in capture["entities"]:
        eid = row["entity_id"] + suffix
        platform_domain, object_id = eid.split(".", 1)
        disabled = None
        if row.get("disabled_by"):
            disabled = er.RegistryEntryDisabler(row["disabled_by"])
        entry_row = ereg.async_get_or_create(
            platform_domain, domain, row["unique_id"] + suffix,
            suggested_object_id=object_id,
            config_entry=entry,
            device_id=device_ids.get(row.get("device")),
            translation_key=row.get("translation_key"),
            original_device_class=row.get("original_device_class"),
            unit_of_measurement=row.get("unit_of_measurement"),
            capabilities=row.get("capabilities") or None,
            disabled_by=disabled,
            entity_category=(er.EntityCategory(row["entity_category"])
                             if row.get("entity_category") in ("config", "diagnostic")
                             else None),
        )
        if entry_row.entity_id != eid:
            ereg.async_update_entity(entry_row.entity_id, new_entity_id=eid)
        if not disabled:
            hass.states.async_set(eid, row.get("state") or "unknown",
                                  row.get("attributes") or {})
    import voluptuous as vol
    bare = bool(capture.get("services_without_schema"))
    for service, fields in capture.get("services", {}).items():
        if not hass.services.has_service(domain, service):
            if bare:
                # (#1054) The integration registers its services with NO
                # schema: Home Assistant knows their fields only from the
                # integration's services.yaml, through its description cache.
                hass.services.async_register(domain, service, _noop)
                from homeassistant.helpers.service import (
                    SERVICE_DESCRIPTION_CACHE,
                )
                hass.data.setdefault(SERVICE_DESCRIPTION_CACHE, {})[
                    (domain, service)] = {
                        "fields": {f: {} for f in fields}}
                continue
            schema = vol.Schema({vol.Optional(f): object for f in fields},
                                extra=vol.ALLOW_EXTRA)
            hass.services.async_register(domain, service, _noop, schema=schema)
    await hass.async_block_till_done()
    return device_ids


async def _noop(call) -> None:  # the rig never drives anything
    return None


def crawl(hass) -> Dict[str, Any]:
    """SEM's crawler on everything registered: the detection report the
    diagnostics and the config flow read."""
    from custom_components.solar_energy_management.hardware_detection import (
        build_detection_report,
    )
    return build_detection_report(hass)


def summary(report: Dict[str, Any], domain: str) -> Dict[str, Any]:
    """What the crawler concluded about ONE integration, in a stable shape
    for the golden files: chargers with their mapped roles, near misses with
    their offer, vehicles, and roster proposals."""
    import re as _re

    def stable(v):
        """Device ids are random per run: name them, do not print them."""
        if isinstance(v, str) and _re.fullmatch(r"[0-9a-f]{32}", v):
            return "<device id>"
        return v

    def mine(rows):
        return [r for r in rows or []
                if str(r.get("platform") or "").split("_rig")[0] == domain]

    out: Dict[str, Any] = {"chargers": [], "near_misses": [], "vehicles": [],
                           "proposals": [], "meters": []}
    for c in mine(report.get("chargers")):
        out["chargers"].append({
            "control": c.get("control"),
            "mapped": {k: stable(v.get("entity") or v.get("value"))
                       for k, v in sorted((c.get("mapped") or {}).items())},
        })
    out["chargers"].sort(key=lambda r: json.dumps(r, sort_keys=True))
    for n in mine(report.get("near_misses")):
        offer = n.get("suggested_charger") or {}
        out["near_misses"].append({
            "charger_roles": n.get("charger_roles"),
            "missing": n.get("missing"),
            "companions": len(n.get("companions") or []),
            "paired_vehicle": bool(n.get("paired_vehicle")),
            "choose_vehicle": len(n.get("choose_vehicle") or []),
            "entities": len(n.get("entities") or []),
            "proposed_roles": sorted((n.get("proposed_roles") or {}).keys()),
            "offer": {k: stable(v) for k, v in sorted(offer.items())
                      if k not in ("id", "name")},
        })
    out["near_misses"].sort(key=lambda r: json.dumps(r, sort_keys=True))
    for m in mine(report.get("meters")):
        out["meters"].append({k: stable(m[k]) for k in sorted(m)
                              if not isinstance(m[k], (dict, list))
                              and k not in ("device_id",)})
    for v in mine(report.get("vehicles")):
        out["vehicles"].append({k: (stable(v[k]) if not isinstance(v[k], dict)
                                    else {kk: stable(vv) for kk, vv in sorted(v[k].items())})
                                for k in sorted(v) if k not in ("device_id",)})
    for p in report.get("roster_proposals") or []:
        if p.get("domain") == domain or p.get("platform") == domain:
            out["proposals"].append({
                role: [body.get("entity") or body.get("service"), body.get("action")]
                for role, body in sorted((p.get("proposed_roles") or {}).items())
            })
    return out
