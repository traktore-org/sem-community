"""One place where a Home Assistant sensor state becomes a number SEM trusts.

#641 — the "sensor state → watts" (and "→ kWh") normalization used to be a
copy-pasted inline block, and every copy had picked its own unit-match rule:
exact-case ``== "kW"``, lowercase ``== "kw"``, strip+lower with synonyms, or no
check at all. That meant the *same physical sensor* could be read at different
magnitudes by different subsystems in the same cycle — the fleet power reader
converting a ``"kw"``-unit charger sensor to 11000 W while the per-charger loop
read it as 11 W, or a kW heat-pump sensor teaching ``calibrate_rated_power`` a
3 W rated power with no error anywhere.

The rule here is the union of the strictest copies:

* strip + case-insensitive, so ``"kW "``, ``"kw"`` and ``"KW"`` all convert
  (template and MQTT sensors are the field reality that motivated #575);
* long-form spellings (``kilowatt``/``kilowatts``) accepted, from
  ``forecast_reader``'s rule;
* Wh **and** MWh on the energy side, from ``energy_calculator._energy_state_kwh``
  (built for #551 — Fronius Gen24 lifetime counters report Wh);
* an unknown or missing unit keeps the historical assume-the-base-unit
  behaviour (W for power, kWh for energy) rather than failing the read.

``tests/test_641_units.py`` fails CI on any new ``unit_of_measurement``
comparison against a power/energy literal outside this module, so a fifth
divergent copy can't be written.
"""
from __future__ import annotations

from typing import Optional

# state strings that are not a reading
_NOT_A_VALUE = (None, "", "unknown", "unavailable", "none")

# unit (stripped + lowercased) → multiplier to reach WATTS.
#
# Known limitation: matching is case-INSENSITIVE, so ``mW`` (milliwatt) and
# ``MW`` (megawatt) collide and both read as megawatts. That is deliberate —
# case-sensitivity is what let a ``"kw"`` template sensor slip past four of the
# five inline copies, and milliwatts are not in HA's power unit registry
# (``UnitOfPower`` is W/kW/MW/GW) nor plausible for solar/EV/battery hardware.
_POWER_TO_W = {
    "": 1.0,            # missing unit → assume the base unit (historical)
    "w": 1.0,
    "watt": 1.0,
    "watts": 1.0,
    "kw": 1000.0,
    "kilowatt": 1000.0,
    "kilowatts": 1000.0,
    "mw": 1_000_000.0,
    "megawatt": 1_000_000.0,
    "megawatts": 1_000_000.0,
    "gw": 1_000_000_000.0,
    "gigawatt": 1_000_000_000.0,
    "gigawatts": 1_000_000_000.0,
}

# unit (stripped + lowercased) → multiplier to reach kWh
_ENERGY_TO_KWH = {
    "": 1.0,            # missing unit → assume kWh (historical, #551)
    "wh": 0.001,
    "watt-hour": 0.001,
    "watt_hour": 0.001,
    "kwh": 1.0,
    "kilowatt-hour": 1.0,
    "kilowatt_hour": 1.0,
    "mwh": 1000.0,
    "megawatt-hour": 1000.0,
    "megawatt_hour": 1000.0,
    "gwh": 1_000_000.0,
}


def normalize_unit(state) -> str:
    """The state's unit, stripped and lowercased. ``""`` when absent."""
    attrs = getattr(state, "attributes", None) or {}
    try:
        unit = attrs.get("unit_of_measurement")
    except (AttributeError, TypeError):
        return ""
    return str(unit or "").strip().lower()


def _convert(state, table, default):
    """Shared body: parse the state, scale it by its unit."""
    raw = getattr(state, "state", None)
    if isinstance(raw, str):
        raw = raw.strip()
    if raw is None or (isinstance(raw, str) and raw.lower() in _NOT_A_VALUE):
        return default
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return default
    # An unrecognised unit is NOT an error — it is very often a correctly-typed
    # sensor with a unit SEM has no opinion about. Fall through at 1.0, which is
    # what every inline copy did.
    return value * table.get(normalize_unit(state), 1.0)


def power_unit_scale(state) -> float:
    """The multiplier :func:`power_state_to_watts` would apply. ``1.0`` for W,
    a missing unit, or an unrecognised one.

    Exposed so a caller can tell "converted" from "passed through" without
    comparing before/after values — ``0.0 kW`` and ``0.0 W`` are both ``0.0``,
    which is exactly the dawn/dusk reading #575 was about.
    """
    return _POWER_TO_W.get(normalize_unit(state), 1.0)


def power_state_to_watts(state, default: Optional[float] = None) -> Optional[float]:
    """A power sensor's state in WATTS, or ``default`` if it isn't readable.

    Accepts an HA ``State`` (or anything with ``.state`` / ``.attributes``).
    ``None`` and the unavailable/unknown sentinels return ``default`` — callers
    that historically returned ``0.0`` should pass ``default=0.0`` so their
    behaviour is unchanged.
    """
    return _convert(state, _POWER_TO_W, default)


def energy_state_to_kwh(state, default: Optional[float] = None) -> Optional[float]:
    """An energy counter's state in kWh, or ``default`` if it isn't readable.

    Wh and MWh counters are real hardware (#551), so an unmarked value is only
    assumed to be kWh when the sensor carries no unit at all.
    """
    return _convert(state, _ENERGY_TO_KWH, default)


def _unit_of(state_or_unit) -> str:
    if isinstance(state_or_unit, str):
        return state_or_unit.strip().lower()
    return normalize_unit(state_or_unit)


def is_energy_unit(state_or_unit) -> bool:
    """True when the unit names an ENERGY counter (Wh/kWh/MWh/GWh).

    Used by config validation to catch an energy counter configured where a
    power sensor belongs (#461) — one of the two places that ask about a unit
    without converting a value. A MISSING unit is not claimed either way: the
    assume-the-base-unit fallback is a conversion convenience, not evidence.
    """
    unit = _unit_of(state_or_unit)
    return bool(unit) and unit in _ENERGY_TO_KWH


def is_power_unit(state_or_unit) -> bool:
    """True when the unit names a POWER sensor (W/kW/MW/GW).

    Used by entity auto-detection to decide whether a candidate *looks* like a
    live power sensor (``ha_energy_reader``'s derive-power scan). Same
    missing-unit rule as :func:`is_energy_unit`.
    """
    unit = _unit_of(state_or_unit)
    return bool(unit) and unit in _POWER_TO_W
