"""#743 — the curtailment probe: harvesting solar an export-limited
inverter hides.

Some inverters set their export limit to 0 W when the selling price is
negative (the reporter's does it natively; Huawei exposes services for
it). Production then clamps to LOCAL consumption, so SEM's measured
surplus reads 0 while the array could deliver kilowatts more. No amount
of reading fixes that — raising consumption is the only instrument that
shows the hidden power. So the probe IS the measurement:

    idle ──(signature holds 60 s)──► probing ──(production follows)──► harvest
      ▲                                 │(no follow in the window)        │
      └────────────(15 min)──────── cooldown ◄────────────────────────────┘
                                                (export appears / car gone)

- The curtailment SIGNATURE (all must hold): a forecast far above what
  the array delivers, export pinned at ~0, and production ≈ local
  consumption. A merely cloudy day fails the forecast term; a mis-read
  meter fails the production≈consumption term.
- The PROBE grants a floor-sized surplus bonus; the normal decide()
  ladder starts the EV at minimum amps on it. Production must rise to
  follow within the window or the grant is revoked and re-probing
  blocked for the cooldown — a failed probe costs ~2 minutes of
  minimum-amps draw, and the whole feature is opt-in.
- In HARVEST the risen production makes the loop self-sustaining; a
  one-step bonus keeps the ladder climbing toward the forecast, and
  every step is itself a probe: production must follow the previous
  step or the bonus drops (retrying later as the sun climbs). No step
  is ever taken on faith, so a reached potential never drains the
  battery or imports grid beyond one step for one window.

Pure module: no hass, no clock — the coordinator feeds readings and a
monotonic ``now`` once per cycle and threads the returned grant into
``FleetCycleState.curtailment_grant_w`` (one seam, AST-linted).
"""
from __future__ import annotations

from dataclasses import dataclass

# The signature thresholds. Values are deliberately conservative: the
# probe should fire on the reporter's unambiguous shape (5 kW forecast,
# 1 kW delivered, 0 export) and stay silent on ordinary days.
EXPORT_EPS_W = 50.0          # "export pinned at ~0"
SHORTFALL_RATIO = 0.7        # production below 70 % of forecast
CONSUMPTION_TOL_RATIO = 0.20  # production ≈ local consumption, ±20 %
CONSUMPTION_TOL_W = 150.0    # …plus an absolute floor for small houses
SUSPECT_HOLD_S = 60.0        # signature must hold this long
PROBE_MARGIN_W = 200.0       # grant a little above the floor
PROBE_WINDOW_S = 120.0       # production must follow within this
FOLLOW_RATIO = 0.6           # "followed" = ≥60 % of the granted draw
COOLDOWN_S = 900.0           # failed probe blocks re-probing 15 min
STEP_BONUS_W = 690.0         # one ladder step (1 A × 3 × 230 V)
STEP_WINDOW_S = 90.0         # a step must be followed within this
STEP_RETRY_S = 600.0         # plateau: retry a step this often


@dataclass
class ProbeInputs:
    """One cycle's readings, all in watts."""
    enabled: bool
    expected_w: float        # dampened forecast "power now"
    production_w: float      # measured solar production
    export_w: float          # measured grid export (≥ 0)
    home_w: float            # home consumption (excl. EV)
    battery_charge_w: float  # battery charging draw (≥ 0)
    ev_draw_w: float         # this fleet's EV draw
    ev_connected: bool
    ev_wants_solar: bool     # a connected charger in a solar-using mode
    probe_floor_w: float     # the charger's minimum start power
    # Brand sharpening (#743, autodetected export-limit entity):
    # True = the inverter says a ~0 export limit is ACTIVE (skip the
    # noisy production≈consumption term), False = it says no limit is
    # active (never probe — low production is the sky's fault), None =
    # no entity found → the brand-agnostic physics signature decides.
    export_limited: "bool | None" = None


class CurtailmentProbe:
    """The state machine. States: off / idle / suspect / probing /
    harvest / cooldown. ``tick`` returns the surplus grant in watts."""

    def __init__(self) -> None:
        self.state = "idle"
        self._suspect_since: float | None = None
        self._probe_started: float | None = None
        self._probe_baseline_w = 0.0
        self._step_baseline_w: float | None = None
        self._step_started: float | None = None
        self._step_plateau_until: float | None = None
        self._cooldown_until = 0.0

    # ── signature ────────────────────────────────────────────────

    @staticmethod
    def _signature(i: ProbeInputs) -> bool:
        if not (i.ev_connected and i.ev_wants_solar):
            return False
        if i.expected_w <= 0:
            return False  # no forecast basis — nothing to suspect
        if i.export_w > EXPORT_EPS_W:
            return False  # power is leaving the house — no limit active
        if i.production_w > SHORTFALL_RATIO * i.expected_w:
            return False  # the array delivers what the sky allows
        if i.expected_w - i.production_w < i.probe_floor_w:
            return False  # not enough hidden room to start a charger
        if i.export_limited is False:
            return False  # the inverter says no limit is active
        if i.export_limited is True:
            return True   # the inverter confirms the limit — that IS the
            # signature; production≈consumption is noisy with battery
            # dynamics and adds nothing the entity didn't already say.
        local = i.home_w + i.battery_charge_w + i.ev_draw_w
        tol = max(CONSUMPTION_TOL_W, CONSUMPTION_TOL_RATIO * i.production_w)
        if abs(i.production_w - local) > tol:
            return False  # curtailment clamps production TO consumption
        return True

    def _room_w(self, i: ProbeInputs) -> float:
        return max(0.0, i.expected_w - i.production_w)

    # ── tick ─────────────────────────────────────────────────────

    def tick(self, i: ProbeInputs, now: float) -> float:
        if not i.enabled:
            self.state = "off"
            self._suspect_since = None
            return 0.0
        if self.state == "off":
            self.state = "idle"

        if self.state == "cooldown":
            if now < self._cooldown_until:
                self._suspect_since = None
                return 0.0
            self.state = "idle"

        if self.state in ("idle", "suspect"):
            if self._signature(i):
                if self._suspect_since is None:
                    self._suspect_since = now
                    self.state = "suspect"
                elif now - self._suspect_since >= SUSPECT_HOLD_S:
                    self.state = "probing"
                    self._probe_started = now
                    self._probe_baseline_w = i.production_w
                    return min(
                        i.probe_floor_w + PROBE_MARGIN_W, self._room_w(i),
                    )
            else:
                self._suspect_since = None
                self.state = "idle"
            return 0.0

        if self.state == "probing":
            followed = (
                i.production_w - self._probe_baseline_w
                >= FOLLOW_RATIO * i.probe_floor_w
            )
            if followed:
                self.state = "harvest"
                self._step_baseline_w = None
                self._step_started = None
                self._step_plateau_until = None
                return self._harvest_grant(i, now)
            if now - (self._probe_started or now) >= PROBE_WINDOW_S:
                # The array never rose — the forecast lied. Revoke; the
                # normal loop stops the charger on the vanished surplus.
                self.state = "cooldown"
                self._cooldown_until = now + COOLDOWN_S
                self._suspect_since = None
                return 0.0
            return min(i.probe_floor_w + PROBE_MARGIN_W, self._room_w(i))

        if self.state == "harvest":
            if i.export_w > EXPORT_EPS_W:
                # The limit lifted — measured surplus is real again.
                self.state = "idle"
                self._suspect_since = None
                return 0.0
            if not (i.ev_connected and i.ev_draw_w > 100.0):
                self.state = "idle"
                self._suspect_since = None
                return 0.0
            return self._harvest_grant(i, now)

        return 0.0

    def _harvest_grant(self, i: ProbeInputs, now: float) -> float:
        """One step of headroom, each step validated like a probe."""
        if self._step_plateau_until is not None:
            if now < self._step_plateau_until:
                return 0.0
            self._step_plateau_until = None
            self._step_baseline_w = None
            self._step_started = None
        if self._step_started is None:
            self._step_started = now
            self._step_baseline_w = i.production_w
            return min(STEP_BONUS_W, self._room_w(i))
        if (
            i.production_w - (self._step_baseline_w or 0.0)
            >= FOLLOW_RATIO * STEP_BONUS_W
        ):
            # Followed — begin the next step from the new baseline.
            self._step_started = now
            self._step_baseline_w = i.production_w
            return min(STEP_BONUS_W, self._room_w(i))
        if now - self._step_started >= STEP_WINDOW_S:
            # Plateau: the array's potential is reached (for now).
            self._step_plateau_until = now + STEP_RETRY_S
            return 0.0
        return min(STEP_BONUS_W, self._room_w(i))
