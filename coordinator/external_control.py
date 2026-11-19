"""(#1079) A device that another party steers: SEM yields, or says so.

Some homes let a supplier or grid operator steer the car or the battery. When
that party and SEM both write to the same device, they undo each other every
cycle. Per device the user picks one of three modes:

* ``none``    — today's behaviour. The default everywhere.
* ``yield``   — while the user's indicator entity says the other party is in
  control, SEM writes nothing to that device. It never stops or starts the
  device itself: it only holds its hands still. The device's measured draw
  stays in the home's accounting, so every other device plans around it.
  With no indicator picked, SEM yields all the time (#1391).
* ``observe`` — SEM keeps control, and a Repair tells the user when it sees
  writes it did not make.

Two things this module is careful about, both found by reviewing the other
2.2 changes:

* A restart must not look like external control. An indicator that reads
  unknown or unavailable changes nothing: the first look after a start begins
  as "not steered", and a known state is kept through a gap.
* An instantaneous flag is not "off". A steering flag that flickers for a
  moment stays active until it has read off for ``HOLD_S`` seconds.

Pure logic; the coordinator reads the entity states and calls ``update``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

MODE_NONE = "none"
MODE_YIELD = "yield"
MODE_OBSERVE = "observe"
MODES = (MODE_NONE, MODE_YIELD, MODE_OBSERVE)

#: How long a steering indicator must read OFF before SEM takes the device
#: back. Long enough to ride out a flag that blinks between two commands.
HOLD_S: float = 300.0

#: Cycles in a row that SEM's own command did not hold before it counts as "a
#: write we did not make" (the reconciler's stop-not-taking streak, a battery
#: limit the register did not keep).
SUSPECT_STRIKES: int = 3

_UNREADABLE = frozenset({"unknown", "unavailable", "", "none_state"})
#: Values of a select or text entity that mean "nobody is steering".
_OFF_WORDS = frozenset({
    "off", "false", "no", "0", "none", "idle", "inactive", "normal",
    "disabled", "standby", "not_active", "stopped",
})


def normalise_mode(value: Any) -> str:
    """A stored mode, or ``none`` for anything that is not one."""
    mode = str(value or "").strip().lower()
    return mode if mode in MODES else MODE_NONE


def read_indicator(hass: Any, entity_id: str) -> Optional[bool]:
    """True: steering. False: not steering. None: could not read it.

    A switch, a binary sensor or an input boolean says on or off. A select
    or a sensor is steering unless its value is one of the "off" words. An
    entity that is missing, unknown or unavailable answers None, never False:
    "could not ask" is not "nobody is steering" (#925).
    """
    if not entity_id or hass is None:
        return None
    st = hass.states.get(entity_id)
    if st is None:
        return None
    raw = str(getattr(st, "state", "") or "").strip().lower()
    if raw in _UNREADABLE:
        return None
    return raw not in _OFF_WORDS


def friendly_name(hass: Any, entity_id: str) -> str:
    """The indicator's own name, for the line the user reads."""
    st = hass.states.get(entity_id) if hass is not None and entity_id else None
    name = (getattr(st, "attributes", None) or {}).get("friendly_name")
    return str(name or entity_id or "")


@dataclass
class Spec:
    """What the user set for one device."""
    mode: str = MODE_NONE
    entity: str = ""
    label: str = ""


@dataclass
class _Track:
    active: bool = False
    since: Optional[datetime] = None
    last_on_mono: float = 0.0
    suspect: bool = False
    suspect_since: Optional[datetime] = None


class ExternalControlBook:
    """The per-device state: who steers what, since when."""

    def __init__(self) -> None:
        self._specs: Dict[str, Spec] = {}
        self._tracks: Dict[str, _Track] = {}

    def update(self, hass: Any, specs: Dict[str, Spec], now_mono: float,
               now_wall: datetime,
               suspects: Optional[Dict[str, bool]] = None) -> None:
        """One look at every device. ``suspects`` says which devices saw a
        write SEM did not make this cycle."""
        suspects = suspects or {}
        self._specs = {k: s for k, s in specs.items() if s.mode != MODE_NONE}
        # a device set back to none forgets its state: no stale "steered"
        for key in list(self._tracks):
            if key not in self._specs:
                del self._tracks[key]
        for key, spec in self._specs.items():
            tr = self._tracks.setdefault(key, _Track())
            if spec.entity.strip():
                reading = read_indicator(hass, spec.entity)
            else:
                # (#1391) No signal picked. In yield mode the user said
                # another party steers this device and named nothing that
                # says when, so it is steered all the time: an empty field
                # is not a signal that says "off". Observe needs no signal.
                reading = True if spec.mode == MODE_YIELD else None
            if reading is True:
                if not tr.active:
                    tr.active, tr.since = True, now_wall
                tr.last_on_mono = now_mono
            elif reading is False:
                if tr.active and now_mono - tr.last_on_mono >= HOLD_S:
                    tr.active, tr.since = False, None
            # reading None: keep what we knew. A fresh start knows nothing,
            # so it starts as "not steered".
            if suspects.get(key):
                if not tr.suspect:
                    tr.suspect, tr.suspect_since = True, now_wall
            else:
                tr.suspect, tr.suspect_since = False, None

    def yielding(self, key: str) -> bool:
        """SEM must write nothing to this device now."""
        spec = self._specs.get(key)
        tr = self._tracks.get(key)
        return bool(spec and tr and spec.mode == MODE_YIELD and tr.active)

    def raising(self, key: str) -> bool:
        """The ``observe`` mode has seen a write it did not make."""
        spec = self._specs.get(key)
        tr = self._tracks.get(key)
        return bool(spec and tr and spec.mode == MODE_OBSERVE and tr.suspect)

    def rows(self) -> List[Dict[str, Any]]:
        """One row per device that has a mode, for the diagnose surface."""
        out: List[Dict[str, Any]] = []
        for key, spec in self._specs.items():
            tr = self._tracks.get(key) or _Track()
            out.append({
                "device": key,
                "mode": spec.mode,
                "indicator": spec.entity,
                "controller": spec.label,
                "steered": tr.active,
                "since": tr.since.isoformat() if tr.since else None,
                "yielding": self.yielding(key),
                "unmade_write_seen": tr.suspect,
            })
        return out

    def line(self, key: str, name: str) -> str:
        """The sentence a person reads."""
        spec = self._specs.get(key)
        tr = self._tracks.get(key)
        if spec is None or tr is None:
            return ""
        who = spec.label or spec.entity or "another party"
        if tr.active and tr.since is not None:
            at = tr.since.strftime("%H:%M")
            tail = "SEM yielding" if spec.mode == MODE_YIELD else "SEM still driving"
            return f"{name}: controlled by {who} since {at} — {tail}"
        if tr.suspect:
            return f"{name}: SEM sees writes it did not make"
        return ""


def yielded_charger_decision(decision: Any) -> Any:
    """(#1391) The decision of a charger SEM yields to another party.

    SEM sends nothing to it, so its own wish must not be shown or counted
    as an act: no "SEM starts charging" line on the card, no start ladder
    that later reads as a car that declined, and no amps or watts of SEM's
    that other chargers and loads plan around (the coordinator counts the
    charger's real draw instead). An IDLE at 0 A, not a release: the phase
    guard still turns an IDLE into its own stop when a phase is over its
    limit (#1381), and that stop is the one write that goes out. A charger
    set to Off keeps its RELEASE: Off never gets that stop (#898).
    """
    from . import reason_codes as RC
    from .charger_types import ChargerIntent, rewrite
    if decision.intent is ChargerIntent.RELEASE:
        # Off is already hands-off (#898), and the phase guard leaves a
        # RELEASE alone; an IDLE would hand it a stop Off never gets.
        return decision
    return rewrite(
        decision,
        intent=ChargerIntent.IDLE,
        commanded_amps=0,
        budget_w=0.0,
        redirect_w=0.0,
        assist_w=0.0,
        peak_paused=False,
        capped_by_limit=False,
        reason="yields to another party (the charger's setting) — SEM "
               f"holds its commands; SEM's own plan: {decision.intent.value}, "
               f"{decision.reason}",
        reason_code=RC.CHARGER_YIELDED,
        reason_params={},
    )
