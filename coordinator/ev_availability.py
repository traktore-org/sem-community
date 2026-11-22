"""Operational EV availability gates.

Legacy flat sensors may survive a failed per-charger migration. They are useful
for discovery, but must never activate charging logic without a registered
CurrentControlDevice.
"""
from __future__ import annotations

from typing import Any, Mapping


def operational_ev_connected(devices: Mapping[str, Any] | None, sensor_connected: bool) -> bool:
    """Return connected only when a controllable charger is registered."""
    return bool(devices) and bool(sensor_connected)


def confirm_connection(prev_confirmed: bool, raw: bool, streak: int,
                       in_warmup: bool,
                       threshold: int = 3) -> tuple[bool, int]:
    """The cycle's answer to "is this car connected?", and the streak.

    A connect is immediate; a disconnect is earned. A UDP-polled charger
    drops its plug sensor for a cycle with the car still on the cable (the
    blip family #35/#595/#753), and a sensor whose integration has not
    loaded yet publishes False without meaning it (#753: a restart's
    warm-up 'unplug' finalized a 6 kWh session). Neither is an unplug, so
    a disconnect counts only after ``threshold`` consecutive raw NOs,
    never inside the boot warm-up.

    Pure: the caller owns the state. Used once per cycle per charger by
    ``SEMCoordinator._confirm_ev_connection`` — the ONE place the raw plug
    reading is read, so every consumer downstream sees one answer.
    """
    if raw:
        return True, 0
    if not prev_confirmed:
        return False, 0
    streak += 1
    if in_warmup or streak < threshold:
        return True, streak
    return False, 0


def operational_night_target(devices: Mapping[str, Any] | None, target_kwh: float) -> float:
    """Suppress plans when no charger device can execute them."""
    return float(target_kwh) if devices else 0.0


def plan_connectivity(cid, charger_cfg, full_config, power):
    """Three-state connectivity for the night demand collector (#638 night 3).

    ``True``/``False`` when a CONFIGURED plug sensor answers; ``None`` when
    there is nothing to ask — the caller plans on ``None`` (fail-visible,
    the mode-gate precedent). The distinction is load-bearing: the sensor
    reader publishes ``ev_connected=False`` from an empty sensor id on
    installs with no plug sensor at all, and reading that as "no car" would
    starve every sensor-less install's night plan.

    Precedence mirrors the #584 notification gate: this charger's own map
    entry first, then the fleet flag — but the fleet flag only counts when
    some plug sensor exists to have produced it (this charger's nested
    ``ev_connected_sensor`` or the legacy flat keys).
    """
    if power is None:
        return None
    pc_map = getattr(power, "ev_connected_per_charger", None) or {}
    if cid in pc_map:
        return bool(pc_map[cid])
    if has_plug_sensor(charger_cfg, full_config):
        return bool(getattr(power, "ev_connected", False))
    return None


def plug_sensor_entity(charger_cfg, full_config):
    """The entity that says whether a car is plugged in at THIS charger, or
    None (#1153, #1412).

    This charger's nested ``ev_connected_sensor``, or the legacy flat keys.
    (#1150) The flat keys count only with one charger: with more they
    answer for the fleet, not for this charger (class 147). The ONE reader
    of where the plug sensor is: ``has_plug_sensor`` asks whether there is
    one, the phase tick asks whether it answers right now — an older
    single-charger install names it in the main settings only, and a
    reader of the nested key alone took its dropout for an unplug.
    """
    own = (charger_cfg or {}).get("ev_connected_sensor")
    if own:
        return own
    if not fleet_flag_is_own(full_config):
        return None
    return ((full_config or {}).get("ev_connected_sensor")
            or (full_config or {}).get("ev_plug_sensor") or None)


def has_plug_sensor(charger_cfg, full_config) -> bool:
    """Can SEM ask this charger whether a car is plugged in? (#1153)

    Without a plug sensor (``plug_sensor_entity``) the car shows only
    through the charger's draw (the physics defence, #285+1), so "not
    connected" is no answer: ``plan_connectivity`` reads it as ``None`` and
    ``build_charger_view`` as ``plug_known=False``. One test for both, so
    the plan and the control loop cannot disagree about which chargers can
    say.
    """
    return bool(plug_sensor_entity(charger_cfg, full_config))


def fleet_flag_is_own(full_config) -> bool:
    """Is the fleet ``ev_connected`` / ``ev_charging`` this charger's? (#1150)

    Only with one charger. With more, the fleet flag is true when ANY
    charger has a car or charges, so a charger without its own sensor
    would read its sibling's car.
    """
    return len((full_config or {}).get("ev_chargers") or []) <= 1


def charger_state(cid, power, full_config, field: str) -> bool:
    """One charger's ``connected`` or ``charging`` (#584, #1150).

    Its own entry in the reader's per-charger map first. Without one, the
    fleet flag — but only when the fleet is this one charger. In a fleet,
    a charger with no sensor of its own answers from its own draw only
    (over the 500 W floor — the physics defence the reader applies to
    every mapped charger); its car is then unknown at rest (#1153), and
    a sibling's car or charge is never its own.
    """
    pc_map = getattr(power, f"ev_{field}_per_charger", None) or {}
    if cid in pc_map:
        return bool(pc_map[cid])
    if fleet_flag_is_own(full_config):
        return bool(getattr(power, f"ev_{field}", False))
    from .sensor_reader import EV_ACTIVE_CHARGE_FLOOR_W

    own_w = (getattr(power, "ev_power_per_charger", None) or {}).get(cid)
    try:
        return own_w is not None and float(own_w) > EV_ACTIVE_CHARGE_FLOOR_W
    except (TypeError, ValueError):
        return False


def plan_car_fullness(detector, drawing_w=None, handshake_w=500.0):
    """Tri-state fullness for the night demand collector (#756).

    ``True`` when THIS charger's taper detector says the car is still
    full — anchored at a completed charge with nothing drawn since (the
    same predicate that pins estimated_soc to 100) — AND the meter does
    not contradict it. ``None`` for everything else, including no
    detector and a broken one: only a definite yes skips a demand, the
    ``plan_connectivity`` precedent.

    Why it exists: ``build_night_target_map`` answers ``target − daily``
    off the calendar counter, which rolls at midnight — on N1 the ask for
    a 100 % car jumped to the full 20 kWh at 00:01 and the phantom
    displaced the real loads under the peak cap. The counter knows the
    calendar; the detector knows the car.

    Why the meter overrules the anchor (N2, .175 15.08): ``still_full``
    is the deficit below full, and charging SUBTRACTS from it, clamped at
    zero. A real charge delivering the last of the deficit therefore
    reads "anchored, nothing missing" for as long as it takes to overdraw
    by ``ANCHOR_REFUTED_KWH`` — ~90 s at 3.9 kW — and in that window the
    plan was told the car was full and restamped the night without it.
    After a TAPER-detected full it is not a window at all: ``update_energy``
    returns early while ``_full_detected`` stands, so the deficit never
    moves and the #774 refutation can never fire — the car reads full for
    as long as the flag lasts, whatever the meter says.

    The detector cannot close either case alone: it sees energy increments,
    not duration, and a genuine trickle is numerically the same rate. Power
    is known here, so here is where the meter gets its say.

    ``handshake_w`` is the charger's own "actually charging" threshold
    (``adapter.handshake_power_w``, #739) — a real sub-handshake trickle
    still reads full, so #756's contract is untouched. Only a NUMBER may
    contradict the anchor: junk on the wire must not un-full a car.
    """
    # (#1011) A standing DECLINED start counts the same way for the plan:
    # a car that refuses current is no sink tonight, whatever its SOC.
    # It is not called full — the estimate and the sensor say "declined"
    # — but the booking it would earn under the peak cap would displace
    # real loads for a phantom, the N1 lesson. The stall→full pin used to
    # deliver this by mislabelling the car; the label is gone, the
    # consequence stays, under its own name. Cleared by a real draw or an
    # unplug (the detector), and the meter check below applies to it too.
    try:
        still_full = bool(getattr(detector, "still_full", False))
        declined = bool(getattr(detector, "declined_start", False))
    except Exception:  # noqa: BLE001 — an unreadable detector has no opinion
        return None
    if not still_full and not declined:
        return None
    if drawing_w is not None:
        try:
            if float(drawing_w) > float(handshake_w):
                return None
        except (TypeError, ValueError):
            pass  # an unreadable meter is not an argument
    return True
