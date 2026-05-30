"""Canonical EV Charge mode names (#277 Phase A).

The five consolidated user-intent modes that replace the four-toggle
soup (``ev_charging_mode`` × ``night_charging`` × ``tariff_optimized``
× ``smart_night_charging``). See
``docs/plans/2026-05-30_ev_charge_mode_consolidation.md`` for the
mapping table and migration semantics.

Lives in ``consts/`` so both ``select.py`` (entity registration) and
``coordinator/coordinator.py`` (read-side helper) can import it
without circular dependencies — the duplicated hardcoded mode-name
tuple flagged by the Phase A reviewer goes away.
"""
from __future__ import annotations

# Order matters: it's the order shown in the HA select UI.
EV_CHARGE_MODES: dict[str, str] = {
    "solar_only": "Solar only",
    "solar_plus_cheap": "Solar + cheapest hours",
    "min_plus_solar": "Min + Solar",
    "always_max": "Always (max)",
    "off": "Off",
}

# The new-install default. Q4 resolved 2026-05-30 — matches today's
# factory defaults (mode=pv + night=on + smart=on + tariff=off).
DEFAULT_EV_CHARGE_MODE: str = "min_plus_solar"
