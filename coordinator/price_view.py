"""(#1372) One place decides what a cheap hour is.

Before this module, six places asked a tariff "is this hour cheap?" and each
read a different part of its answer: the plan's hour list read the raw level
(``day_ledger.tariff_cheap_at``), the live gate read the compared level
(``price_signal.is_cheap``), the plan card read the rate word, the tank
counted quarter hours on a private price list. Two of those answered
differently for the same hour (#994, #1310) and each fix was local.

``PriceView`` is the one question and the one answer. An hour is one of four
states: CHEAP, DEAR, ONE_PRICE (the prices do not differ, so "cheap" means
nothing) or UNKNOWN (nobody can say). Only CHEAP is cheap; UNKNOWN is never
the cheap bucket (#925).

Steps 1-5 of #1372 are a pure refactor, so TWO rules still exist and are
kept bit for bit until the engine moves to one:

* ``rule="plan"`` — what ``tariff_cheap_at`` returned: the provider's raw
  level for the hour, cheap when its word is a cheap one.
* ``rule="gate"`` — what the live gate reads: ``price_signal.is_cheap``, a
  level only where a comparison stands behind it.

The sun is NOT part of a price view: a sunny hour is cheap for the packer
(``LedgerSlot.level_cheap``), but the tariff may still be at its peak.

Pure: no hass, no I/O. Give it a provider (and a clock, or pass the time).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Iterable, Optional, Union

from homeassistant.util import dt as dt_util

from .price_signal import (
    _name, comparative_level, is_cheap, is_cheap_name,
    is_expensive_name, variation_known,
)

__all__ = [
    "PriceState", "PriceAnswer", "PriceView", "answer_for_level",
    "day_has_cheaper", "price_no_dearer", "RULE_PLAN", "RULE_GATE",
]

RULE_PLAN = "plan"
RULE_GATE = "gate"

#: Two prices are "no dearer" when they differ by no more than this
#: (float noise). The planner's own tolerance, moved here unchanged.
_PRICE_EPS = 1e-9


class PriceState(str, Enum):
    CHEAP = "cheap"
    DEAR = "dear"
    ONE_PRICE = "one_price"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PriceAnswer:
    """What the tariff says about one hour. ``peak`` marks a DEAR hour in
    the expensive bands, for callers that want the top of the curve."""
    state: PriceState
    peak: bool = False

    @property
    def is_cheap(self) -> bool:
        return self.state is PriceState.CHEAP


def answer_for_level(level: Any) -> PriceAnswer:
    """The answer for a level SEM already resolved (a stamped string).

    For callers that hold a level word, not a provider: the hints and the
    energy assistant. None / empty is UNKNOWN, never cheap.
    """
    if not _name(level):
        return PriceAnswer(PriceState.UNKNOWN)
    if is_cheap_name(level):
        return PriceAnswer(PriceState.CHEAP)
    return PriceAnswer(PriceState.DEAR, peak=is_expensive_name(level))


def day_has_cheaper(cheap_flags: Iterable[bool]) -> bool:
    """Is any hour of the horizon cheap? Lazy, so a caller's generator
    stops at the first one. The planner's "one price" is its opposite."""
    return any(cheap_flags)


def price_no_dearer(price: Optional[float], ref: Optional[float]) -> bool:
    """Does ``price`` cost no more than ``ref``? Unknown either way = no."""
    return ref is not None and price is not None and price <= ref + _PRICE_EPS


class PriceView:
    """Every price question about one device (or the house), one rule."""

    def __init__(self, provider: Any, own: Any = None,
                 now: Union[datetime, Callable[[], datetime], None] = None,
                 rule: str = RULE_GATE) -> None:
        # The device's own tariff answers when it has one; else the house's.
        self._p = own if own is not None else provider
        self._clock = now
        self.rule = rule

    @classmethod
    def for_device(cls, device: Any, house_provider: Any,
                   device_tariffs: Any = None, now: Any = None,
                   rule: str = RULE_GATE) -> "PriceView":
        """The view a device reads: its own tariff when it has one and it is
        readable (``DeviceTariffs.plan_tariff``), else the house's."""
        own = None
        if device_tariffs is not None:
            plan = device_tariffs.plan_tariff(device)
            own = None if plan is None else plan.provider
        return cls(house_provider, own=own, now=now, rule=rule)

    # ── time ──────────────────────────────────────────────────────────

    def _moment(self) -> datetime:
        clock = self._clock
        if callable(clock):
            return clock()
        return clock if clock is not None else dt_util.now()

    def known_until(self) -> Optional[datetime]:
        """The end of what the provider knows; None = no limit (a rule)."""
        reader = getattr(self._p, "known_until", None)
        if not callable(reader):
            return None
        try:
            return reader()
        except Exception:  # noqa: BLE001 — a provider that cannot say has no limit
            return None

    # ── the question ──────────────────────────────────────────────────

    def _raw_level(self, when: Optional[datetime]) -> Any:
        """The provider's raw level at ``when`` (None = now); exceptions
        and a provider with no level word are no level."""
        p = self._p
        try:
            if when is None:
                return p.get_price_level()
            return p.get_price_level_at(when)
        except Exception:  # noqa: BLE001 — no level is not cheap
            return None

    def at(self, t: Optional[datetime] = None) -> PriceAnswer:
        """The hour's state. Past ``known_until`` it is UNKNOWN."""
        if self._p is None:
            return PriceAnswer(PriceState.UNKNOWN)
        if t is not None:
            end = self.known_until()
            try:
                if end is not None and t >= end:
                    return PriceAnswer(PriceState.UNKNOWN)
            except TypeError:  # naive vs aware: ask the provider
                pass
        raw = self._raw_level(t)
        if not _name(raw):
            return PriceAnswer(PriceState.UNKNOWN)
        if self.rule == RULE_GATE:
            level = comparative_level(self._p, t)
            if level is None:
                # the provider spoke but nothing compares: one price,
                # unless it is a word nobody knows
                known = variation_known(self._p)
                return PriceAnswer(PriceState.UNKNOWN if known
                                   else PriceState.ONE_PRICE)
            raw = level
        return answer_for_level(raw)

    def now(self) -> PriceAnswer:
        """The state now; the gate asks the provider's live level."""
        if self.rule == RULE_GATE and self._clock is None:
            return self.at(None)
        return self.at(self._moment())

    def cheap_at(self, t: Optional[datetime]) -> bool:
        """The exact bool today's callers get for hour ``t``."""
        if self.rule == RULE_GATE:
            return is_cheap(self._p, t)
        if hasattr(self._p, "get_price_level_at"):
            try:
                lvl = self._p.get_price_level_at(t)
            except Exception:  # noqa: BLE001 — no level is not cheap
                return False
            return is_cheap_name(lvl)
        return False

    def rate_cheap_at(self, t: datetime) -> bool:
        """(#1310) Display: is the hour at the tariff's cheap RATE? Shown
        on the plan card's band, the tomorrow preview and Assist. A provider
        with no rate word answers with the plan's level."""
        if hasattr(self._p, "get_rate_level_at"):
            try:
                lvl = self._p.get_rate_level_at(t)
            except Exception:  # noqa: BLE001 — no level is not cheap
                return False
            return is_cheap_name(lvl)
        return PriceView(self._p, rule=RULE_PLAN).cheap_at(t)

    def rate_cheap_fn(self) -> Optional[Callable[[datetime], bool]]:
        """A builder's ``rate_cheap_at``, or None when the rate word IS the
        price level (a dynamic tariff): the slot then reuses the gate's
        answer instead of asking the same level ~400 times."""
        own = getattr(type(self._p), "get_rate_level_at", None)
        if own is None or getattr(own, "same_as_price_level", False):
            return None
        return self.rate_cheap_at

    # ── comparing hours ───────────────────────────────────────────────

    def day_has_cheaper(self, hours: Iterable[datetime]) -> bool:
        """Is any of ``hours`` cheap?"""
        return day_has_cheaper(self.cheap_at(t) for t in hours)

    def cheap_hours(self, a: datetime, b: datetime, step_min: int = 15,
                    tolerance_h: float = 0.0) -> Optional[float]:
        """Cheap hours in ``[a, b)`` counted every ``step_min`` minutes; None
        when the span is not fully known (the forecast ends before ``b``).

        ``tolerance_h`` lets the forecast end that long before ``b``: the
        Legionella count has always read a curve ending up to an hour early
        as complete (#1372, kept as it was).
        """
        end = self.known_until()
        if end is not None and end < b - timedelta(hours=tolerance_h):
            return None
        step = timedelta(minutes=step_min)
        steps = (b - a) // step
        return (step_min / 60.0) * sum(
            1 for i in range(steps) if self.cheap_at(a + i * step))
