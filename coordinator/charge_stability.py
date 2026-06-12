"""Surplus charge stability — evcc-style enable/disable delays.

The v1.7 ``decide() → actuate()`` pipeline replaced the legacy
``_execute_ev_control`` solar path and silently dropped its stability
layer (v1.7.1-beta.14): the **enable delay** (surplus must persist
before the contactor closes) and the **disable delay** (deficit must
persist before it opens, holding minimum current meanwhile). The
``ev_enable_delay_seconds`` / ``ev_disable_delay_seconds`` config keys
kept existing but nothing read them on the new path — the only
surviving guard was the 2-cycle IDLE debounce in ``actuate``.

RienduPre's #461 beta.10 logs show the consequence: solar hovering
around the 6 A minimum started the charger on every spike and stopped
it seconds later (±4.5 kW demand swings within consecutive cycles,
contactor cycling every ~20 s).

This module reintroduces the two delays as a stateful filter between
``decide()`` and ``actuate()``. Timing semantics follow evcc's pv
enable/disable timers (https://github.com/evcc-io/evcc — loadpoint
``enable.delay`` / ``disable.delay``):

* **enable**: a CHARGE decision on a non-charging EV passes only after
  it has held continuously for ``ev_enable_delay_seconds``.
* **disable**: an IDLE decision against a charging EV holds the
  charger at minimum current until the deficit has persisted for
  ``ev_disable_delay_seconds``.

The disable semantics deliberately *improve on* the legacy path, which
measured from session START (a minimum-run-time): once a session was
older than the window, a single-cycle cloud dip stopped it instantly.
evcc measures **deficit persistence**, which protects the contactor
for the whole session — that is the behaviour we adopt.

Scope: daytime surplus modes only (``solar_only`` / ``min_plus_solar``
/ ``solar_plus_cheap``). Night floors, ``always_max``, OFF/DISABLE
and disconnected EVs pass through untouched — stopping for safety or
user intent must never be delayed.
"""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Dict, Optional, TYPE_CHECKING

from .charger_types import ChargerDecision, ChargerIntent, ChargerView
from .decide import effective_min_amps

if TYPE_CHECKING:  # pragma: no cover
    from .charger_adapters.base import ChargerAdapter

_LOGGER = logging.getLogger(__name__)

# Modes whose DAY decisions are surplus-driven and therefore flicker
# with the solar signal. Night decisions (floors, cheap windows) and
# always_max are deliberate, not flicker — they bypass the filter.
SURPLUS_DAY_MODES = frozenset({"solar_only", "min_plus_solar", "solar_plus_cheap"})

DEFAULT_ENABLE_DELAY_S = 60
DEFAULT_DISABLE_DELAY_S = 300

_CHARGE_INTENTS = (ChargerIntent.CHARGE_AT_AMPS, ChargerIntent.CHARGE_MAX)


class ChargeStability:
    """Per-charger enable/disable delay state.

    One instance lives on the coordinator; state is keyed by
    charger id so multi-charger fleets get independent timers
    (pinned by ``test_multi_charger_control`` for the legacy path —
    same contract here).
    """

    def __init__(self) -> None:
        self._surplus_since: Dict[str, float] = {}
        self._deficit_since: Dict[str, float] = {}

    def _reset(self, cid: str) -> None:
        self._surplus_since.pop(cid, None)
        self._deficit_since.pop(cid, None)

    def filter(
        self,
        decision: ChargerDecision,
        view: ChargerView,
        adapter: "ChargerAdapter",
        *,
        enable_delay_s: float = DEFAULT_ENABLE_DELAY_S,
        disable_delay_s: float = DEFAULT_DISABLE_DELAY_S,
        now_ts: Optional[float] = None,
    ) -> ChargerDecision:
        """Apply enable/disable delays to a surplus-mode day decision.

        Returns the decision unchanged when out of scope; otherwise a
        possibly-overridden decision whose reason names the active
        delay so the strategy sensor explains the hold (the #461
        "state says idle but EV draws 4.5 kW" confusion class).
        """
        cid = decision.charger_id
        now = now_ts if now_ts is not None else time.monotonic()

        # Out of scope → transparent. DISABLE (user off / self-resume
        # guard) and disconnects also clear the timers: the next
        # session starts a fresh enable window.
        if (
            view.mode not in SURPLUS_DAY_MODES
            or view.fleet.is_night
            or not view.power.connected
            or decision.intent is ChargerIntent.DISABLE
        ):
            self._reset(cid)
            return decision

        # "Charging" = the adapter last commanded a charge OR the EV is
        # measurably drawing (covers coordinator restarts mid-session,
        # where last_intent is None but power is real).
        charging = (
            getattr(adapter, "last_intent", None) in _CHARGE_INTENTS
            or adapter.actual_charging(view.power)
        )

        if decision.intent in _CHARGE_INTENTS:
            self._deficit_since.pop(cid, None)
            if charging:
                # Mid-session current adjustments pass through — the
                # delays gate start/stop transitions, not ramping.
                self._surplus_since.pop(cid, None)
                return decision
            since = self._surplus_since.setdefault(cid, now)
            held = now - since
            if held >= max(0.0, float(enable_delay_s)):
                self._surplus_since.pop(cid, None)
                return decision
            return replace(
                decision,
                intent=ChargerIntent.IDLE,
                commanded_amps=0,
                reason=(
                    f"stability: surplus must hold {enable_delay_s:.0f}s "
                    f"before start ({held:.0f}s elapsed) — {decision.reason}"
                ),
            )

        if decision.intent is ChargerIntent.IDLE:
            self._surplus_since.pop(cid, None)
            if not charging:
                self._deficit_since.pop(cid, None)
                return decision
            since = self._deficit_since.setdefault(cid, now)
            held = now - since
            if held >= max(0.0, float(disable_delay_s)):
                self._deficit_since.pop(cid, None)
                return decision
            min_amps = max(
                effective_min_amps(
                    view.config if isinstance(view.config, dict) else {}, 6,
                ),
                int(getattr(adapter, "min_current_a", 6) or 6),
            )
            return replace(
                decision,
                intent=ChargerIntent.CHARGE_AT_AMPS,
                commanded_amps=min_amps,
                reason=(
                    f"stability: deficit {held:.0f}s/{disable_delay_s:.0f}s — "
                    f"holding {min_amps}A before stop — {decision.reason}"
                ),
            )

        return decision
