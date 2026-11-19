"""#983 — the battery half of the #548 actuation truth.

The EV side has carried an actuation block since #548: for each charger, what
SEM commanded, what the hardware reads back, and what the reconciler last did.
The battery side had nothing, so every battery-control report cost a round
trip for facts SEM was already holding.

@RienduPre's #983 (surplus exporting while the battery looked unfilled) and
#978 (a power-strategy flip cached as done) both turn on two of those facts —
what the strategy select READS versus what SEM believes it set, and whether
the setpoint write was refused — and neither was in his download.

A module of its own, rather than a closure inside the service, so the shape
can be tested against a fabricated adapter: the cases worth pinning are the
ones nobody can reproduce on demand (a select stuck on ``nom``, an entity that
has vanished, an adapter that raises).
"""
from __future__ import annotations


def battery_actuation_diag(hass, coordinator) -> dict:
    """Per-battery actuation truth — the #548 block's battery half (#983).

    The EV side has had this since #548; the battery side had nothing, so
    every battery-control report cost a round-trip for facts SEM already
    held. @RienduPre's #983 needed exactly two of them — what the power
    strategy READS versus what SEM believes it set, and whether the
    setpoint write was refused — and neither was in the download.

    Per battery: the adapter, the strategy select (entity, live state,
    what SEM believes, the configured values, flips sent and not yet
    seen), the power setpoint (entity, live state, last written and
    attempted, the refusals behind #840's withdrawal), the capability
    verdicts and the last intent + error. Live reads, never raises — a
    battery whose adapter has not been built yet is SAID to be missing
    rather than omitted (#925: absence is a value).
    """
    import time as _time

    out: dict = {}
    adapters = getattr(coordinator, "_battery_adapters", None) or {}

    def _state(eid):
        if not eid:
            return None
        st = hass.states.get(eid)
        return st.state if st is not None else "<missing>"

    def _g(obj, name, default=None):
        return getattr(obj, name, default)

    if not adapters:
        return {"note": "no battery control adapter built yet (no battery "
                        "configured, or the first cycle has not run)"}

    now = _time.monotonic()
    for bid, ad in adapters.items():
        try:
            strat_entity = _g(ad, "_strategy_entity", "") or None
            setpoint = _g(ad, "_force_discharge_entity", "") or None
            sent = dict(_g(ad, "_strategy_sent", None) or {})
            intent = _g(ad, "last_intent", None)
            out[str(bid)] = {
                "adapter": type(ad).__name__,
                "strategy": {
                    "entity": strat_entity,
                    # The two facts #978 turns on: what it READS, and what
                    # SEM believes it set. A disagreement here is the bug.
                    "reads": _state(strat_entity),
                    "sem_believes": _g(ad, "_last_strategy", None),
                    "values": {
                        "active": _g(ad, "_strategy_active", None),
                        "idle": _g(ad, "_strategy_idle", None),
                        "self_consume": _g(ad, "_strategy_self_consume", None),
                        "off": _g(ad, "_strategy_off", None),
                    },
                    "sem_took_control": bool(_g(ad, "_took_control", False)),
                    "restore_to": _g(ad, "_restore_strategy", None),
                    # value → seconds since SEM sent it without seeing it
                    "sent_not_seen": {
                        str(k): round(max(0.0, now - float(v)), 1)
                        for k, v in sent.items()
                    },
                },
                "setpoint": {
                    "entity": setpoint,
                    "reads": _state(setpoint),
                    "sem_believes_w": _g(ad, "_last_force_discharge_w", None),
                    "last_attempt_w": _g(ad, "_last_force_discharge_attempt_w", None),
                    "device_refusals": int(_g(ad, "_force_discharge_failures", 0) or 0),
                    "unit_refusals": int(_g(ad, "_fd_unit_refusals", 0) or 0),
                },
                "discharge_limit": {
                    "entity": _g(ad, "_discharge_control_entity", "") or None,
                    "last_commanded_w": _g(ad, "_last_discharge_limit_w", None),
                },
                "verdicts": {
                    "supports_forced_discharge": bool(
                        _g(ad, "supports_forced_discharge", False)),
                    "supports_forced_charge": bool(
                        _g(ad, "supports_forced_charge", False)),
                    "write_not_taken_strikes": int(
                        _g(ad, "write_not_taken_strikes", 0) or 0),
                    "last_verified_entity": _g(ad, "last_verified_entity", "") or None,
                    "last_unverified": {
                        "entity": _g(ad, "last_unverified_entity", "") or None,
                        "wanted": _g(ad, "last_unverified_wanted", "") or None,
                        "seen": _g(ad, "last_unverified_seen", "") or None,
                    },
                },
                "charge_path": _charge_path(ad, _state),            # (#1377)
                "last_intent": getattr(intent, "value", intent) if intent else None,
                "last_error": _g(ad, "_last_error", None),
            }
        except Exception as exc:  # noqa: BLE001 — one battery never costs the rest
            out[str(bid)] = {"error": str(exc)}
    return out


def _charge_path(ad, read) -> dict:
    """(#1377) How a grid charge reaches the battery: the select and its
    option, the switch, the charge target — each with what it reads now —
    and what SEM last did with them. A battery report showed "commanded
    force_charge, not observed" and none of these, so it could not tell a
    write that never went out from one the battery ignored."""
    try:
        return _charge_path_of(ad, read)
    except Exception as exc:  # noqa: BLE001 — the block never costs the rest
        return {"error": str(exc)}


def _charge_path_of(ad, read) -> dict:
    cfg = getattr(ad, "_config", None) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    ca = getattr(ad, "_charge_adapter", None)
    select = str(cfg.get("battery_charge_select_entity") or "") or None
    switch = str(cfg.get("battery_force_charge_switch") or "") or None
    target = str(cfg.get("battery_target_soc_entity") or "") or None
    return {
        "select": {"entity": select, "reads": read(select),
                   "option": cfg.get("battery_charge_select_option") or None},
        # beside a select the switch is the permit; alone it is the start
        "switch": {"entity": switch, "reads": read(switch),
                   "role": ("permit" if select and switch
                            else "start" if switch else None)},
        "target": {"entity": target, "reads": read(target)},
        "active": bool(getattr(ca, "_active", False)) if ca else None,
        "target_soc": getattr(ca, "_target_soc", None) if ca else None,
        "select_writes": getattr(ca, "_sel_writes", None) if ca else None,
        "permit_writes": getattr(ca, "_permit_writes", None) if ca else None,
        "given_up": getattr(ca, "_sel_spent", None) if ca else None,
        "last": getattr(ad, "_last_charge_message", None),
    }


async def pacing_actuation_diag(hass, coordinator) -> dict:
    """(#820) The charge-pacing actuation truth, for the Diagnose button.

    @ArneGollin1987's charge limit sat at 1560 W for days while SEM's own
    surface said ``cap_w 2443``. The download held the decision but nothing
    about the register, so neither possible cause could be told apart:

    * ``register`` — the limit entity as Home Assistant holds it now: live
      state, unit, min, max and step (a cap off the step or outside the
      range is refused);
    * ``writer`` — what SEM believes: engaged, the value it would put back,
      the last cap it sent, and whether the register ever showed it;
    * ``record`` — the engagement persisted across restarts (#949), whose
      value to put back is the second suspect;
    * ``decision`` — the cap, reason and action the last cycle published.

    Async only to read the persisted record. Never raises.
    """
    try:
        config = getattr(coordinator, "config", None) or {}
        entity = str(config.get("battery_charge_power_limit_entity") or "") or None
        if entity is None:
            register = {"entity": None, "note": "no charge-limit entity is set"}
        else:
            st = hass.states.get(entity)
            if st is None:
                register = {"entity": entity, "state": "<missing>"}
            else:
                attrs = getattr(st, "attributes", None) or {}
                register = {
                    "entity": entity,
                    "state": st.state,
                    "unit": attrs.get("unit_of_measurement"),
                    "min": attrs.get("min"),
                    "max": attrs.get("max"),
                    "step": attrs.get("step"),
                }

        writer = getattr(coordinator, "_charge_pacing_writer", None)
        record = None
        if writer is None:
            writer_out: dict = {"note": "pacing has not run yet"}
        else:
            writer_out = {
                "engaged": bool(getattr(writer, "engaged", False)),
                "engaged_entity": getattr(writer, "engaged_entity", "") or None,
                "restore_value": getattr(writer, "restore_value", None),
                "last_written_w": getattr(writer, "last_written_w", None),
                "own_cap_w": getattr(writer, "_own_cap_w", None),
                "confirmed": bool(getattr(writer, "_confirmed", False)),
                "unconfirmed_cycles": int(
                    getattr(writer, "_unconfirmed_cycles", 0) or 0),
                # (02.10) taken, but as another number — Arne's 1550 → 1449
                "applied_differs": (
                    {"register_w": _ad[0], "written_w": _ad[1]}
                    if (_ad := getattr(writer, "applied_differs", None))
                    else None),
            }
            store = getattr(writer, "_store", None)
            if store is not None:
                try:
                    loaded = await store.async_load()
                    record = dict(loaded) if isinstance(loaded, dict) else None
                except Exception as exc:  # noqa: BLE001
                    record = {"error": str(exc)}

        state = getattr(coordinator, "_charge_pacing_state", None) or {}
        decision = {k: state.get(k) for k in (
            "enabled", "cap_w", "action", "reason", "reason_code", "soc",
            "hw_max_charge_w", "entity")} if state else None

        return {"register": register, "writer": writer_out,
                "record": record, "decision": decision}
    except Exception as exc:  # noqa: BLE001 — the diagnose surface never fails
        return {"error": str(exc)}
