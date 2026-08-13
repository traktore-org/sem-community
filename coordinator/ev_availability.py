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
    has_sensor = bool(
        (charger_cfg or {}).get("ev_connected_sensor")
        or (full_config or {}).get("ev_connected_sensor")
        or (full_config or {}).get("ev_plug_sensor")
    )
    if has_sensor:
        return bool(getattr(power, "ev_connected", False))
    return None


def plan_car_fullness(detector):
    """Tri-state fullness for the night demand collector (#756).

    ``True`` when THIS charger's taper detector says the car is still
    full — anchored at a completed charge with nothing drawn since (the
    same predicate that pins estimated_soc to 100). ``None`` for
    everything else, including no detector and a broken one: only a
    definite yes skips a demand, the ``plan_connectivity`` precedent.

    Why it exists: ``build_night_target_map`` answers ``target − daily``
    off the calendar counter, which rolls at midnight — on N1 the ask for
    a 100 % car jumped to the full 20 kWh at 00:01 and the phantom
    displaced the real loads under the peak cap. The counter knows the
    calendar; the detector knows the car.
    """
    try:
        return True if getattr(detector, "still_full", False) else None
    except Exception:  # noqa: BLE001 — an unreadable detector has no opinion
        return None
