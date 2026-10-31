"""(#1213) The setup check: what SEM found, as plain numbers, and the one
question it asks when it is not sure about the grid meter.

A new user decides here whether SEM is for them. They know whether the house
is buying power or sending it out; they do not know entity IDs. So the
check shows watts, and asks about the grid only when SEM guessed it or found
none.

No direction is claimed here. A meter's sign is the brand's choice, not
HA's: some read + while buying, others + while sending, and
SEM learns which from the energy counters only after install. So setup shows
plain watts, and the question takes its sign from the user's answer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .coordinator.units import power_state_to_watts

# Below this a meter's sign says nothing: a house at rest reads a few watts
# either way.
QUIET_W = 50.0
ASK_GUESSED = "guessed"
ASK_MISSING = "missing"


@dataclass
class SetupCheck:
    solar_w: Optional[float] = None
    grid_entity: Optional[str] = None
    grid_w: Optional[float] = None        # as the sensor reads it; sign unknown
    grid_from: str = "missing"            # dashboard | guessed | pair | missing
    # (#1237) The import / export power sensors SEM's own search found for a
    # meter the dashboard gave counters only. No single entity stands for it.
    grid_pair: Tuple[Optional[str], Optional[str]] = (None, None)
    battery_w: Optional[float] = None     # sum as read; sign unknown
    soc: Optional[float] = None
    other_grid: Optional[str] = None
    other_grid_w: Optional[float] = None
    ask: Optional[str] = None

    @property
    def grid_is_quiet(self) -> bool:
        return self.grid_w is None or abs(self.grid_w) < QUIET_W

    def answers(self) -> Tuple[str, ...]:
        """The answers that mean something for this meter right now.

        The FIRST one is what Home Assistant's form preselects, so it must be
        an answer that writes nothing: a user who presses Submit without
        reading must not turn a sign around.
        """
        if self.grid_is_quiet:
            out = ["keep"]
        else:
            out = ["unknown", "buying", "sending"]
        if self.other_grid:
            out.append("other")
        if self.grid_is_quiet:
            out.append("unknown")
        return tuple(out)


def _watts(hass, entity_id: Optional[str]) -> Optional[float]:
    if not entity_id or hass is None:
        return None
    return power_state_to_watts(hass.states.get(entity_id))


def _sum(values) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


def _find_grid_pair(hass, cfg: Any) -> Tuple[Optional[str], Optional[str]]:
    """(#1237) The grid meter's import / export power sensors, found by the
    SAME search SEM runs once it is up (declared keys, then names, device
    first). Setup must not ask about a meter SEM finds by itself, and a
    sensor picked here would be read as the only one, so the pair would
    never be looked for."""
    if hass is None or not getattr(cfg, "grid_import_energy", None):
        return None, None
    try:
        from .coordinator.sensor_reader import SensorReader
        imp, exp, confidence = SensorReader(
            hass, {})._discover_split_grid_power(cfg)
    except Exception:  # noqa: BLE001 — a search never breaks an install
        return None, None
    # Found means SEM will read it as the grid: a whole pair, trusted at
    # once. A name guess or one half is still checked later, so setup asks.
    if imp and exp and confidence in ("declared", "same-device"):
        return imp, exp
    return None, None


def _percent(hass, entity_id: Optional[str]) -> Optional[float]:
    if not entity_id or hass is None:
        return None
    state = hass.states.get(entity_id)
    try:
        return float(state.state) if state is not None else None
    except (TypeError, ValueError):
        return None


def build_setup_check(hass, cfg: Any,
                      proposals: Optional[Dict[str, Any]] = None) -> SetupCheck:
    """Read what the Energy Dashboard (plus SEM's own guesses) gave."""
    check = SetupCheck()
    derived = getattr(cfg, "derived_power", None) or {}

    solar = list(getattr(cfg, "solar_power_list", None) or [])
    if not solar and getattr(cfg, "solar_power", None):
        solar = [cfg.solar_power]
    check.solar_w = _sum(_watts(hass, e) for e in solar)

    # Grid as the sensor reads it.
    if getattr(cfg, "grid_import_power", None):
        check.grid_entity = cfg.grid_import_power
        check.grid_w = _watts(hass, cfg.grid_import_power)
        check.grid_from = "guessed" if "grid" in derived else "dashboard"
    elif getattr(cfg, "grid_power_from", None) and getattr(cfg, "grid_power_to", None):
        bought = _watts(hass, cfg.grid_power_from)
        sent = _watts(hass, cfg.grid_power_to)
        if bought is not None and sent is not None:
            check.grid_w = bought - sent
        check.grid_from = "dashboard"
    elif not getattr(cfg, "grid_power_list", None):
        # Counters only: the case SEM's reader answers with its pair search.
        # A whole, trusted pair is a found meter.
        imp, exp = _find_grid_pair(hass, cfg)
        if imp or exp:
            check.grid_pair = (imp, exp)
            check.grid_from = "pair"
            bought, sent = _watts(hass, imp), _watts(hass, exp)
            if bought is not None or sent is not None:
                check.grid_w = (bought or 0.0) - (sent or 0.0)

    # Battery as read. Only its size is shown, so the sign does not matter.
    parts = []
    for e in (getattr(cfg, "battery_power_list", None) or
              ([cfg.battery_power] if getattr(cfg, "battery_power", None) else [])):
        parts.append(_watts(hass, e))
    for p_from, p_to in (getattr(cfg, "battery_power_pairs", None) or []):
        out_w, in_w = _watts(hass, p_from), _watts(hass, p_to)
        if out_w is not None and in_w is not None:
            parts.append(out_w - in_w)
    check.battery_w = _sum(parts)
    check.soc = _percent(hass, getattr(cfg, "battery_soc", None))

    hit = (proposals or {}).get("grid_import_power_sensor") or {}
    other = hit.get("entity")
    if other and other != check.grid_entity and check.grid_from != "pair":
        check.other_grid = other
        check.other_grid_w = _watts(hass, other)

    if check.grid_from == "missing":
        check.ask = ASK_MISSING
    elif check.grid_from == "guessed":
        check.ask = ASK_GUESSED
    return check


def answer_updates(check: SetupCheck, answer: Optional[str],
                   picked_grid: Optional[str] = None) -> Dict[str, Any]:
    """Config keys that carry the user's answer. "unknown" changes nothing:
    SEM goes on learning the sign from the energy counters.

    A guessed meter is read already (the dashboard path uses it), so
    confirming it pins nothing: it keeps following the Energy Dashboard. Only
    "use the other meter" names a sensor. The sign answer is about the meter
    the user was shown, so it is dropped when they pick another one.
    """
    if answer == "other" and check.other_grid:
        return {"grid_power_sensor": check.other_grid}
    if answer not in ("buying", "sending") or not check.grid_entity:
        return {}
    if picked_grid and picked_grid != check.grid_entity:
        return {}
    if check.grid_is_quiet:
        return {}
    # SEM's sign is − while buying. A meter that reads + while the user says
    # "buying" must be turned around; the user's answer is the truth,
    # whatever convention the brand chose.
    if (answer == "buying") == (check.grid_w > 0):
        return {"grid_sign_invert": True}
    return {}


def fmt_w(w: Optional[float]) -> str:
    if w is None:
        return "?"
    return f"{abs(round(w)):,}".replace(",", " ") + " W"
