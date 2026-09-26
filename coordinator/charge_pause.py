"""(#980) A timed pause: charge mode Off for a while, then back as it was.

@RienduPre, discussion #958, having just accepted the #898 answer on Off:

    "I now understand and it's a good option. But I still like to have an
    option to stop charging for some time if needed and I don't want to go
    to my Wallbox app for that. If it's possible to add an option like
    that, some sort of pause SEM charging."

The first design of this made SEM *hold* the charger stopped — a new intent
that re-asserted DISABLE every cycle. A review took it apart, and Guido's
answer was better than the fix: **set the mode to Off, and set it back when
the timer is done.**

That is right, and not only simpler. Off is hands-off by construction
(#898/#942): SEM sends one stop for its own session and then nothing, so a
box that restarts itself is left alone. Holding it stopped instead means
re-asserting against a box that disagrees — a stop war, which #763 exists to
end, and whose ceasefire would have silently surrendered up to four hours of
a one-hour pause on exactly the self-restarting Pulsar this was built for.

So a pause is not a new kind of control. It is the mode the user would have
chosen anyway, plus the only part they cannot do themselves: **remembering
to put it back.**

Two facts per charger, both persisted, both absolute:

* ``pause_charging_until`` — WHEN it ends, as a wall-clock instant. A
  duration would have to be re-armed after a restart, silently returning
  minutes already spent.
* ``pause_resume_mode`` — WHAT to go back to. Stored at arming, because by
  the time it expires the only record of what the user was doing is this.

If the user changes the mode themselves while a pause is running, they have
overridden it: the pause stands down and restores nothing. SEM must never
snap a mode back over a deliberate choice.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

#: The per-charger config keys. Two facts, no third.
PAUSE_UNTIL_KEY = "pause_charging_until"
PAUSE_RESUME_MODE_KEY = "pause_resume_mode"

#: What the duration dropdown offers, in minutes, in order. Durations only —
#: there is no "resume now" entry, because there is already a control that
#: means that: the charge-mode select. Picking a mode by hand IS cancelling
#: the pause, and adding a second way to say it would be one more option
#: earning its place by undoing another one (#830).
PAUSE_DURATIONS: "dict[str, int]" = {
    "30_minutes": 30,
    "1_hour": 60,
    "2_hours": 120,
    "4_hours": 240,
    "8_hours": 480,
    "12_hours": 720,
}
DEFAULT_PAUSE_DURATION: str = "1_hour"


def duration_minutes(option: Optional[str]) -> int:
    """Minutes for a dropdown option; 0 (= resume now) for anything else."""
    return int(PAUSE_DURATIONS.get(str(option or ""), 0))


def parse_deadline(value) -> Optional[datetime]:
    """The stored deadline as a datetime, or ``None`` — nothing armed.

    An unparseable value is ``None``: a pause SEM cannot read is a pause it
    must not act on. Here the safe side of not-knowing is RELEASING — the
    charger goes back to its mode — because the alternative is a charger
    held off forever by a corrupt string (#925: three states, and the third
    one has to do something sensible).
    """
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def pause_remaining_s(value, now: datetime) -> Optional[float]:
    """Seconds left on an armed pause, or ``None`` when none is running."""
    deadline = parse_deadline(value)
    if deadline is None or now is None:
        return None
    try:
        left = (deadline - now).total_seconds()
    except TypeError:          # naive vs aware — a value from somewhere else
        return None
    return left if left > 0 else None


def deadline_for_minutes(minutes, now: datetime) -> Optional[str]:
    """The value to store when arming. ``None`` = nothing to arm."""
    try:
        m = float(minutes)
    except (TypeError, ValueError):
        return None
    if m <= 0 or now is None:
        return None
    return (now + timedelta(minutes=m)).isoformat()


def forget_on_mode_write(charger_cfg: dict, key: str, value) -> bool:
    """Drop the record when a write puts the charger in a mode other than off.

    Every config writer applies this right after ``charger_cfg[key] = value``
    — the per-charger writer the select and the button use, and the
    set_option service's merge. A pause IS charge mode off, so a charger
    written into any other mode carries no record, whoever wrote it: the
    card, the service, an automation. This used to live in the select alone;
    a mode set through the service kept the record, the sweep would have
    caught it a cycle later, and an Off chosen inside that cycle revived the
    old deadline (review, 25.09).

    In place. True when a record was dropped. Off keeps a running pause:
    choosing Off during a pause is not "another mode", it is the same one.
    """
    if key != "charge_mode" or value in (None, "") or str(value) == "off":
        return False
    had = bool(charger_cfg.get(PAUSE_UNTIL_KEY)
               or charger_cfg.get(PAUSE_RESUME_MODE_KEY))
    charger_cfg.pop(PAUSE_UNTIL_KEY, None)
    charger_cfg.pop(PAUSE_RESUME_MODE_KEY, None)
    return had


def tick(charger_cfg, now: datetime) -> dict:
    """The per-charger keys to write this cycle. ``{}`` = nothing to do.

    Three outcomes, and the second one is why this is a dict and not a mode:

    * nothing armed, or the pause is still running → ``{}``
    * the user took the knob back — the live mode is no longer ``off``, so
      they cancelled — → clear both facts and write NO mode. Forgetting is
      the whole job here: a stale deadline left lying around would fire the
      next time they chose ``off`` deliberately and overwrite it.
    * it ran out → give the mode back and clear both facts.

    An unreadable deadline (see ``parse_deadline``) lands in the third case
    on purpose: the safe side of not-knowing is giving the charger back.
    """
    cfg = charger_cfg or {}
    until = cfg.get(PAUSE_UNTIL_KEY)
    resume_to = cfg.get(PAUSE_RESUME_MODE_KEY)
    if not until and not resume_to:
        return {}
    cleared = {PAUSE_UNTIL_KEY: None, PAUSE_RESUME_MODE_KEY: None}
    # "Did they cancel?" comes FIRST, before "has it run out?". A pause the
    # user ended by picking a mode is over at that moment, and leaving its
    # record alive until the deadline passes leaves a loaded gun: choose
    # Off again inside that window and the expiry would put the pre-pause
    # mode back over the Off just chosen.
    if str(cfg.get("charge_mode") or "") != "off":
        return cleared
    if until and pause_remaining_s(until, now) is not None:
        return {}                         # still running, still off
    if not resume_to:
        return cleared                    # half a record; nowhere to go back to
    return {"charge_mode": str(resume_to), **cleared}


def press(charger_cfg, option: Optional[str], now: datetime) -> dict:
    """What one press of the Pause button writes. Pure.

    The button means "apply the dropdown": pause for that long, or — pressed
    while one is already running — re-arm for the new duration. Cancelling is
    not here; it is the charge-mode select, because setting the charger back
    to what you want is already the gesture for that.

    Returns the per-charger keys to persist. ``charge_mode`` is present only
    when it changes, so a press that alters nothing writes nothing to it.
    """
    cfg = charger_cfg or {}
    live_mode = str(cfg.get("charge_mode") or "")
    minutes = duration_minutes(option)
    if minutes <= 0 or not live_mode:
        return {}       # an option nobody offers, or no mode to come back to
    deadline = deadline_for_minutes(minutes, now)
    if live_mode != "off":
        return {PAUSE_UNTIL_KEY: deadline, PAUSE_RESUME_MODE_KEY: live_mode,
                "charge_mode": "off"}

    # Already off. Pressed mid-pause this re-arms for the new duration and
    # keeps the mode the record remembers — by now "off" is SEM's own doing,
    # and recording it would strand the charger there for good. The same
    # covers a pause that ran out and is not swept yet. Off BY HAND, with
    # nothing remembered, is not a pause: there is nothing to come back to,
    # and the card would count down to Off, the state it is already in.
    remembered = str(cfg.get(PAUSE_RESUME_MODE_KEY) or "")
    if remembered in ("", "off"):
        return {}
    return {PAUSE_UNTIL_KEY: deadline, PAUSE_RESUME_MODE_KEY: remembered}
