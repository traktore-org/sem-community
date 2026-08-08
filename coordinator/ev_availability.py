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
