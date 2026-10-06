"""(#1025) Battery boost: the house battery into the car for this one charge.

"Tonight, put the battery into the car down to 40 %." A one-off per charger,
started by the ``start_battery_boost`` service (the EV card's button) and
held in memory only — a restart ends it — so it never changes the standing
permission and never outlives the session it was meant for.

While it runs, the boosted charger's assist is consented like the open
morning window (#892), and both deciders take the boost's floor: what the
charger is offered, and what the battery is allowed to give. It ends when the
car unplugs, the charger's mode changes, the pack reaches the floor, or the
permission is switched off — each with its reason. It is refused while the
permission is explicitly off (D5): an explicit "no" outranks a button.

Pure functions; the coordinator holds the one ``BatteryBoost`` and ticks it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

#: (D4) The boost's floor defaults to the morning window's drain floor.
DEFAULT_FLOOR_KEY = "battery_morning_drain_floor_soc"
DEFAULT_FLOOR_SOC = 50.0


@dataclass(frozen=True)
class BatteryBoost:
    charger_id: str
    floor_soc: float
    #: the charger's mode when the boost started: a change ends it
    mode: str
    started: datetime


class BoostRefused(Exception):
    """A boost that may not start. ``key`` is the translation key of the
    sentence the user gets."""

    def __init__(self, key: str, **placeholders: Any) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = {k: str(v) for k, v in placeholders.items()}


def _floor(value: Any, config: Mapping[str, Any]) -> float:
    if value is None or value == "":
        value = config.get(DEFAULT_FLOOR_KEY, DEFAULT_FLOOR_SOC)
        if value is None:
            value = DEFAULT_FLOOR_SOC
    try:
        floor = float(value)
    except (TypeError, ValueError):
        raise BoostRefused("battery_boost_bad_floor", floor=value) from None
    if not 0.0 <= floor <= 100.0 or floor != floor:
        raise BoostRefused("battery_boost_bad_floor", floor=value)
    return floor


def start_boost(charger_id: str, charger_cfg: Mapping[str, Any],
                config: Mapping[str, Any], *, mode: str,
                connected: Optional[bool], now: datetime,
                floor_soc: Any = None) -> BatteryBoost:
    """A boost for ``charger_id``, or :class:`BoostRefused` saying why not.

    ``connected`` is the plan layer's tri-state: only a definite False
    refuses — a charger without a plug sensor can still be boosted, and an
    unplug ends the boost the moment it is seen."""
    from .build_view import _battery_may_assist_ev
    if not _battery_may_assist_ev(config, charger_cfg):
        raise BoostRefused("battery_boost_not_permitted", charger=charger_id)
    if connected is False:
        raise BoostRefused("battery_boost_not_connected", charger=charger_id)
    return BatteryBoost(charger_id=str(charger_id),
                        floor_soc=_floor(floor_soc, config),
                        mode=str(mode), started=now)


def boost_end_reason(boost: BatteryBoost, *, connected: Optional[bool],
                     mode: str, soc: Optional[float],
                     may_assist: bool) -> Optional[str]:
    """Why the boost ends this cycle, or None while it runs. An unknown plug
    is not an unplug, and an unread SOC is not a floor."""
    if connected is False:
        return "unplugged"
    if str(mode) != boost.mode:
        return "mode changed"
    if not may_assist:
        return "permission off"
    if soc is not None and float(soc) <= boost.floor_soc:
        return "battery at its floor"
    return None


def boost_remaining_kwh(soc: Optional[float], floor_soc: float,
                        capacity_kwh: float) -> float:
    """What the boost may still give: (SOC − floor) × measured capacity."""
    if soc is None or capacity_kwh <= 0:
        return 0.0
    return max(0.0, (float(soc) - float(floor_soc)) / 100.0 * float(capacity_kwh))
