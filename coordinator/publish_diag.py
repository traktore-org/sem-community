"""Diagnostics-summary assembly for the System tab (#625 phase 3).

Extracted from the coordinator's update cycle: pure READ-ONLY assembly of
the ``diag_*`` / ``layer_mismatch`` keys published on ``coordinator.data``.
Nothing here actuates or mutates — it summarises state the cycle already
computed, so it is unit-testable with a mocked coordinator.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

_LOGGER = logging.getLogger(__name__)


def format_battery_sign_diag(inverted: dict, detected: dict) -> str:
    """Serialise the per-bid battery-sign state to a SCALAR string for the
    ``diag_battery_sign`` sensor (#588 M-2).

    HA sensor state must be a scalar — a raw dict is an invalid state and
    renders as ``[object Object]`` in the config card. Mirrors the plain-string
    ``diag_grid_sign``. Single battery → bare value; multi-battery →
    ``"b1: negated, b2: normal (learning)"``.
    """
    if not inverted:
        return "learning"

    def _fmt(bid):
        return ("negated" if inverted.get(bid) else "normal") + (
            "" if detected.get(bid) else " (learning)"
        )

    if len(inverted) == 1:
        return _fmt(next(iter(inverted)))
    return ", ".join(f"{bid}: {_fmt(bid)}" for bid in sorted(inverted))


def build_diagnostics(coord) -> Dict[str, Any]:
    """The System-tab diagnostics summary (#625, extracted).

    Reads (never writes) the coordinator's cycle state:
    grid mode/sign (#461), battery sign (#588), the layered-trace health
    signal (#590), charger count/control method, ED config summary (#250).
    """
    out: Dict[str, Any] = {}
    reader = coord._sensor_reader
    out["diag_version"] = coord._get_version()

    _disc = getattr(reader, "_split_grid_discovery", None) or {}
    if (coord.config.get("grid_import_power_entity")
            or coord.config.get("grid_export_power_entity")):
        out["diag_grid_mode"] = "manual"
        # #461 follow-up: observe-only audit verdict — True when the manual
        # import/export assignment has contradicted the Energy Dashboard
        # counters for 5+ cycles (swapped fields).
        out["diag_grid_manual_mismatch"] = bool(
            getattr(reader, "_manual_grid_mismatch", False)
        )
    elif _disc.get("import"):
        out["diag_grid_mode"] = (
            "split" if _disc.get("confidence") == "same-device" else "split-lowconf"
        )
    else:
        out["diag_grid_mode"] = "combined"
    out["diag_grid_sign"] = "negated" if reader._grid_sign_inverted else "normal"

    # #588 — battery sign summary per bid (mirrors diag_grid_sign).
    out["diag_battery_sign"] = format_battery_sign_diag(
        getattr(reader, "_battery_sign_inverted", {}),
        getattr(reader, "_battery_sign_detected", {}),
    )

    # #590 — the layered-trace health signal, surfaced as ONE queryable
    # binary sensor (binary_sensor.sem_layer_mismatch). ON when a control OR
    # perception layer-boundary fault has PERSISTED; the ``perception:<signal>``
    # subsystem tag names a sign contradiction.
    _health = coord.trace_health()
    out["layer_mismatch"] = not bool(_health.get("ok", True))
    out["layer_mismatch_subsystem"] = _health.get("subsystem")
    out["layer_mismatch_cycles"] = int(_health.get("cycles", 0) or 0)

    out["diag_charger_count"] = len(coord._ev_devices)
    out["diag_charger_control"] = "number" if any(
        getattr(d, "current_entity_id", None) for d in coord._ev_devices.values()
    ) else "service" if coord._ev_devices else "none"
    out["diag_battery_capacity"] = coord.config.get("battery_capacity_kwh", 0)
    out["diag_update_interval"] = coord.update_interval.total_seconds()
    out["diag_observer_mode"] = coord._observer_mode
    out["diag_sensors_unavailable"] = sum(
        1 for _ in reader._sensor_unavailable
    )
    out["diag_health_violations"] = coord._health_check.total_violations

    # (#653) Appliance schedules. Absent on installs that never called the
    # ``schedule_appliance`` service — which is why this is conditional
    # rather than a permanent empty block. ``get_schedule_summary`` had no
    # reader at all before this: the #426 transition telemetry it carries was
    # being recorded into a dict nothing ever looked at.
    _scheduler = getattr(coord, "_appliance_scheduler", None)
    if _scheduler is not None:
        out["diag_appliance_schedules"] = _scheduler.get_schedule_summary()

    # Energy Dashboard config summary — surfaces whether power AND energy are
    # configured per source, and where power came from (#250 self-diagnosis).
    out["diag_ed_config"] = coord._build_ed_config_summary()
    return out
