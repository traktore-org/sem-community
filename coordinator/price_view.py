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

Two QUESTIONS, not two rules (#1372 step 8):

* **"Is hour T at a cheap level?"** — ``cheap_at(t)``, ``at(t)``. The
  planners' question. The provider answers for that hour's own day: it
  refuses a day with one rate and a tariff whose rates are equal (#994).
* **"Is it worth acting now?"** — ``cheap_now()``, ``now()``. The live
  gate's question: the level now, and only while the prices SEM can still
  act on differ (``price_signal.comparative_level``).

They must not be merged: the second looks at the prices from NOW on, so
asked about Monday on a Sunday evening it hides Monday's cheap hours — the
plan could not plan ahead. (``cheap_seen_from_now`` is that mix, kept for
the one caller that has always asked it.)

The sun is NOT part of a price view: a sunny hour is cheap for the packer
(``LedgerSlot.level_cheap``), but the tariff may still be at its peak.

Pure: no hass, no I/O. Give it a provider (and a clock, or pass the time).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Iterable, Optional, Union

from ..tariff.tariff_provider import PriceLevel
from .price_signal import (
    CHEAP_LEVELS, EXPENSIVE_LEVELS, _name, comparative_level, is_cheap, is_cheap_name,
    is_expensive_name, variation_known,
)

__all__ = [
    "PriceState", "PriceAnswer", "PriceView", "answer_for_level", "answer_for_device",
    "day_has_cheaper", "price_no_dearer", "price_blocks_bridge",
    "CHEAP_WORDS", "PEAK_WORDS", "LEVEL_RANK",
]


#: Two prices are "no dearer" when they differ by no more than this
#: (float noise). The planner's own tolerance, moved here unchanged.
_PRICE_EPS = 1e-9


#: (#1372) The level words in price order, cheapest first: what a planner
#: ranks hours by. One list, here, beside the words it orders.
LEVEL_RANK = {"negative": 0, "very_cheap": 1, "cheap": 2, "normal": 3,
              "expensive": 4, "very_expensive": 5}


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


def answer_for_device(device: Any, house_level: Any) -> PriceAnswer:
    """(#1372) The answer a device's gate reads: its own tariff's level when
    it has one (stamped by ``DeviceTariffs.stamp``), else the house level.
    Exactly ``device_tariff.device_price_level``, then ``answer_for_level``."""
    from .device_tariff import device_price_level  # device_tariff imports us
    return answer_for_level(device_price_level(device, house_level))


#: (#994) every real level word that is NOT a cheap one. A flat or
#: no-prices word, None and "" are not in it: unknown is not "dear".
NOT_CHEAP_LEVELS = frozenset(
    lv.value for lv in PriceLevel if lv not in CHEAP_LEVELS)


#: The level words of the cheap and the peak (expensive) bands, for code
#: that groups a stamped curve by band (the plan rows, the sink verdicts).
CHEAP_WORDS = tuple(lv.value for lv in CHEAP_LEVELS)
PEAK_WORDS = tuple(lv.value for lv in EXPENSIVE_LEVELS)


def price_blocks_bridge(level: Any) -> bool:
    """(#524) Would holding the charger through a dip at this level import
    dear grid? Only a REAL not-cheap level says yes; an unknown, flat or
    unpriced level is bridgeable (nothing cheaper to wait for)."""
    return level in NOT_CHEAP_LEVELS


def day_has_cheaper(cheap_flags: Iterable[bool]) -> bool:
    """Is any hour of the horizon cheap? Lazy, so a caller's generator
    stops at the first one. The planner's "one price" is its opposite."""
    return any(cheap_flags)


def price_no_dearer(price: Optional[float], ref: Optional[float]) -> bool:
    """Does ``price`` cost no more than ``ref``? Unknown either way = no."""
    return ref is not None and price is not None and price <= ref + _PRICE_EPS


class PriceView:
    """Every price question about one device (or the house)."""

    def __init__(self, provider: Any, own: Any = None,
                 now: Union[datetime, Callable[[], datetime], None] = None,
                 ) -> None:
        # The device's own tariff answers when it has one; else the house's.
        self._p = own if own is not None else provider
        self._clock = now      # kept for callers that pin a moment

    @classmethod
    def for_device(cls, device: Any, house_provider: Any,
                   device_tariffs: Any = None, now: Any = None,
                   ) -> "PriceView":
        """The view a device reads: its own tariff when it has one and it is
        readable (``DeviceTariffs.plan_tariff``), else the house's."""
        own = None
        if device_tariffs is not None:
            plan = device_tariffs.plan_tariff(device)
            own = None if plan is None else plan.provider
        return cls(house_provider, own=own, now=now)

    # ── time ──────────────────────────────────────────────────────────

    def known_until(self) -> Optional[datetime]:
        """The end of what the provider knows; None = no limit (a fixed tariff)."""
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
        if t is not None:
            # the hour question: the provider's word for that hour
            if _name(raw):
                return answer_for_level(raw)
            # no level: a priced hour with nothing to compare is ONE_PRICE
            return PriceAnswer(PriceState.ONE_PRICE if self._priced(t)
                               else PriceState.UNKNOWN)
        if not _name(raw):
            return PriceAnswer(PriceState.UNKNOWN)
        # the live question: a level only while prices still differ
        level = comparative_level(self._p, None)
        if level is None:
            known = variation_known(self._p)
            return PriceAnswer(PriceState.UNKNOWN if known
                               else PriceState.ONE_PRICE)
        return answer_for_level(level)

    def _priced(self, t: datetime) -> bool:
        """Does the provider have a price for hour ``t``?"""
        reader = getattr(self._p, "get_price_at", None)
        if not callable(reader):
            return False
        try:
            return reader(t) is not None
        except Exception:  # noqa: BLE001 — unpriced
            return False

    def compared_level(self, t: Optional[datetime] = None) -> Any:
        """The provider's level where a comparison stands behind it, else
        None (``price_signal.comparative_level``): what is threaded to the
        engine as the cycle's price level."""
        return comparative_level(self._p, t)

    def level_at_fn(self) -> Optional[Callable[[datetime], Any]]:
        """The provider's raw ``get_price_level_at`` (None = it has none),
        for the planners that take a ``level_at`` callable and judge the
        words through ``answer_for_level`` themselves."""
        return getattr(self._p, "get_price_level_at", None)

    def now(self) -> PriceAnswer:
        """The live question: the state now, for acting now."""
        return self.at(None)

    def cheap_at(self, t: Optional[datetime]) -> bool:
        """The hour question: is hour ``t`` at a cheap level? ``t`` goes to
        the provider as given (also None) — for now, ask ``cheap_now``."""
        if hasattr(self._p, "get_price_level_at"):
            try:
                lvl = self._p.get_price_level_at(t)
            except Exception:  # noqa: BLE001 — no level is not cheap
                return False
            return is_cheap_name(lvl)
        return False

    def cheap_now(self) -> bool:
        """The live question: is it cheap now, while prices still differ?"""
        return is_cheap(self._p, None)

    def cheap_seen_from_now(self, t: Optional[datetime]) -> bool:
        """Hour ``t`` at a cheap level AND prices differing from now on —
        the live rule asked about a later hour. A device's own tariff has
        always been planned with it (``PlanTariff.cheap_at``); it cannot
        see cheap hours that start after a one-price stretch."""
        return is_cheap(self._p, t)

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
        return self.cheap_at(t)

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
