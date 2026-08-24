"""Cross-brand charger STATUS-enum classifier (#548, generalised).

The Wallbox fix (#548) made the firmware status enum — not the
cloud-lagged power reading — authoritative for "is it actually
charging?" and "can SEM control the contactor?". The same problem
applies to every cloud-polled brand (Easee ~60 s, Zaptec ~60–600 s,
Ohme ~30 s, go-e ~20 s, OCPP ~60 s meter cadence). Rather than a
bespoke adapter per brand, this module is the SINGLE place that maps
each brand's status strings to a control-relevant class. ``GenericAdapter``
reads it (over the already-configured ``charging_status_entity``,
plumbed from ``ev_charging_sensor``) so every brand benefits at once.

Design rules:
  * **Exact, lower-cased whole-string match** — never substring. Several
    brands have idle states that *contain* "charging" ("charging finished,
    vehicle still connected" (go-e), "wait vehicle charging" (Alfen),
    "stop_charging" (Easee)); a substring test would misread them as
    charging. Exact match is the only safe option.
  * **Unknown → caller falls back to the power heuristic.** Anything not
    listed here returns ``"unknown"`` so the adapter keeps its existing
    power-based behaviour. This makes the whole mechanism strictly
    additive: a brand/string we don't recognise behaves exactly as before.
  * **No collisions.** A string classified ``charging`` for one brand is
    never ``not_charging`` for another (verified across the brand sets
    below). ``"charging"`` is universally charging; ``"available"`` /
    ``"connected"`` / ``"paused"`` / ``"finished"`` are universally not.

Each string is sourced from the brand's actual HA integration (cited).
"""
from __future__ import annotations

# ── CHARGING — the contactor is delivering power ──────────────────────
_CHARGING = frozenset({
    # generic binary "is charging" sensor (ev_charging_sensor = binary_sensor)
    "on",
    # Wallbox (HA core wallbox/const.py ChargerStatus)
    "charging", "discharging",
    # Easee (nordicopen/easee_hass EASEE_STATUS) — start_charging is the
    # transient into charging
    "start_charging",
    # Zaptec (custom-components/zaptec, operation mode lower-cased)
    "connected_charging",
    # Alfen (leeyuentuen/alfen_wallbox STATUS_DICT)
    "charging normal", "charging simplified", "solar charging",
    "partial solar charging", "charging power on",
    # OCPP / go-e / Ohme all use the bare "charging" above.
})

# ── NOT_CHARGING — plugged/ready/paused/finished, no power flowing ─────
_NOT_CHARGING = frozenset({
    "off",
    # Wallbox
    "paused", "ready", "waiting", "waiting for car demand", "connected",
    "disconnected", "no car connected",
    # Easee — note de_authorizing is the session ENDING (RFID pulled), not a
    # control lock, so it belongs here, not in _LOCKED.
    "awaiting_start", "completed", "ready_to_charge", "stop_charging",
    "de_authorizing", "awaiting_load_balancing", "paused_due_to_equalizer",
    # Zaptec
    "connected_requesting", "connected_finished",
    # go-e (cathiele car_status strings)
    "charger ready, no vehicle", "waiting for vehicle",
    "charging finished, vehicle still connected",
    # Ohme (models.py ChargerStatus)
    "plugged_in", "plugged in", "finished", "unplugged",
    # OCPP 1.6 ChargePointStatus (lower-cased, both spellings of suspended)
    "available", "preparing", "suspendedev", "suspended_ev",
    "suspendedevse", "suspended_evse", "finishing", "reserved",
    # Alfen ("off" already listed above for the binary case)
    "authorizing", "authorized", "cable connected", "ev connected",
    "not charging", "charging non charging", "preparing charging",
    "wait vehicle charging", "solar charging wait", "finish wait vehicle",
    "finish wait disconnect", "charge point ready, waiting for power",
    "suspended over-current", "suspended hf switching",
    "suspended ev disconnected", "load balancing limited",
    "load balancing forced off",
})

# ── LOCKED — app/cloud/schedule/auth controlled: SEM cannot drive the
# contactor. actual_charging → False; enable_state → uncontrollable so
# the reconciler surfaces "can't stop/start" instead of fighting it. ──
_LOCKED = frozenset({
    # Wallbox
    "scheduled", "waiting in queue by eco-smart",
    "waiting in queue by power sharing", "waiting in queue by power boost",
    "locked", "locked, car connected",
    # Easee (RFID / smart-charge schedule / authorisation)
    "awaiting_authorization", "awaiting_smart_start",
    "awaiting_scheduled_start", "authenticating",
    # Ohme (requires the Approve-charge button)
    "pending_approval",
    # NOTE: OCPP's "Unavailable" status is intentionally NOT here — it
    # collides with HA's generic entity-offline state "unavailable", which
    # the adapter must treat as "sensor unreadable → power fallback". The
    # OCPP out-of-service case degrades to the power heuristic (safe; OCPP
    # is local/low-lag and reports ~0 W when unavailable anyway).
    # Alfen — status sensor reports "In Operative" (STATUS_DICT 34); the
    # operation-mode select uses "In-operative". Cover both spellings.
    "in operative", "in-operative", "in_operative",
})


# ── CABLE ABSENT — recognised states that mean NO car is plugged in ────
# Cable presence is its OWN axis, not a corollary of the three classes
# above: ``_NOT_CHARGING`` deliberately holds both cable-present idle
# states (``paused``, ``ready``, ``connected``) and cable-absent ones
# (``unplugged``, ``available``, ``waiting for vehicle``). Inferring
# "plugged" from "not disconnected" would therefore read an empty bay as
# occupied on OCPP, go-e and Ohme — so the absent states are enumerated
# explicitly and everything else recognised counts as cable present.
_CABLE_ABSENT = frozenset({
    "off",
    # Wallbox
    "disconnected", "no car connected",
    # Ohme
    "unplugged",
    # OCPP 1.6 — "Available" is the connector with no EV attached
    "available",
    # go-e
    "charger ready, no vehicle", "waiting for vehicle",
    # Alfen
    "suspended ev disconnected", "finish wait disconnect",
})


def is_cable_present(raw: "str | None") -> "bool | None":
    """Is a car plugged in, according to this charger's status string?

    Returns ``True`` / ``False`` for a recognised status, or ``None`` when
    the string is unrecognised so the caller can fall back to its own
    heuristic — the same strictly-additive contract as
    :func:`classify_charger_status`.

    #833: the connection reader used to carry its own tuple of brand
    strings, which drifted from the sets above and lost ``paused`` and
    ``locked`` — a Wallbox sitting idle-but-plugged read as "no car" and
    SEM never started a session (discussion #821). Plug detection now
    derives from the same vocabulary as everything else, so the two
    cannot disagree again.
    """
    if classify_charger_status(raw) == "unknown":
        return None
    return str(raw).strip().lower() not in _CABLE_ABSENT


def classify_charger_status(raw: "str | None") -> str:
    """Map a charger status-sensor state to a control class.

    Returns one of:
      * ``"charging"``     — delivering power (authoritative over a lagging
        power reading).
      * ``"not_charging"`` — plugged/ready/paused/finished, no power.
      * ``"locked"``       — app/cloud/schedule/auth controlled; SEM can't
        drive the contactor.
      * ``"unknown"``      — unrecognised / error / numeric / blank; the
        caller should fall back to its power-based heuristic.
    """
    if raw is None:
        return "unknown"
    s = str(raw).strip().lower()
    if not s:
        return "unknown"
    if s in _CHARGING:
        return "charging"
    if s in _NOT_CHARGING:
        return "not_charging"
    if s in _LOCKED:
        return "locked"
    return "unknown"
