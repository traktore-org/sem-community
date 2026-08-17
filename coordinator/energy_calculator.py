"""Energy calculation module for SEM coordinator."""
from __future__ import annotations

import logging
import re
from collections import deque
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Set

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .types import (
    PowerReadings, EnergyTotals, CostData, PerformanceMetrics,
    PowerFlows, EnergyFlows,
)
from ..utils.time_manager import TimeManager
from .units import energy_state_to_kwh
from .battery_provenance import (
    BatteryProvenance, allocate_fleet_charge, discharge_savings,
)

from ..utils.log_gate import log_on_change

_LOGGER = logging.getLogger(__name__)

# Minimum power thresholds to prevent ghost accumulation
MIN_POWER_THRESHOLD = 10  # Watts

# Maximum integration gap — skip cycle if sensors were unavailable longer
# than this (prevents energy spikes from sensor restarts / integration updates)
MAX_INTEGRATION_GAP_SECONDS = 120  # 2 minutes

# Threshold for hardware reconciliation (kWh)
RECONCILIATION_THRESHOLD = 0.5

# Adoption threshold for a metered category (#628). Much finer than the solar/EV
# 0.5 kWh: those correct a large one-way shortfall, while a grid row is often
# only ~1 kWh all day (#628's reporter: 1.05 kWh import), where a 0.5 kWh dead
# band would leave half the error in place. Below this the integrator keeps the
# row — the point is to stop drift, not to chase noise.
METER_RECONCILIATION_THRESHOLD = 0.05

# Sanity ceiling for one day of a metered category (#628). Solar and EV have
# physical bounds to check against (kWp × 16 h, chargers × amps × 24 h); grid
# and battery do not, so this is a pure unit-error trap — a Wh register read as
# kWh is 1000× out. No residential install imports or exports 1 MWh in a day.
MAX_PLAUSIBLE_DAILY_KWH = 1000.0

# Accumulator category for EV charging energy (#666). A named constant, not a
# literal, because this string is the join between four otherwise-independent
# places (live accumulation, the yearly recorder seeding, the hardware-counter
# reconcile, and every read) and a silent disagreement between any two of them
# is invisible — that is exactly how yearly EV energy came to be permanently
# frozen. The EV day boundary is NOT encoded here: it lives in the day key
# (``_ev_reset_day``), which is where a boundary belongs.
EV_CATEGORY = "ev"
_EV_KEY_PREFIX = f"{EV_CATEGORY}_"
# The pre-#666 name, still found in stored accumulators on upgrade.
_LEGACY_EV_CATEGORY = "ev_daily_sun"
_LEGACY_EV_KEY_PREFIX = f"{_LEGACY_EV_CATEGORY}_"

# (#628) Midnight-keyed mirror of the EV daily bucket, used ONLY by the home
# balance. ``EV_CATEGORY``'s day key rolls at the charge deadline (#279) while
# daily home is a CALENDAR-day quantity, and composing a midnight row out of a
# deadline row is exactly the day-boundary class closed in #703/#704. The mirror
# is DAILY-ONLY — monthly, yearly and lifetime EV stay on the one deadline-keyed
# bucket, so there is still a single EV total in the system. The name
# deliberately does not start with ``ev_``: that prefix means "survives the
# midnight rollover" (``_check_rollover``), and this bucket must roll at midnight.
MIDNIGHT_EV_CATEGORY = "midnight_ev"

# (#769) Per-device ledger keys. Every controlled load gets daily/monthly/
# yearly/lifetime totals on the same footing as EV, keyed by ``device_id``
# from the start because #685 puts additional heat pumps in the one device
# list as ordinary climate devices — there is no "the" heat pump to hardcode.
#
# The prefix is a colon rather than an underscore so a device_id can never
# collide with a plain category ("device:heat_pump" vs "solar"), and so the
# rollover sweep can recognise these keys: like EV, a device's day rolls at
# SUNRISE (#620/#704), not at midnight, so a device key must survive the
# calendar-day prune the way ``ev_`` does.
DEVICE_KEY_PREFIX = "device:"
# Sub-total separator, e.g. ``device:heat_pump#sg3_2026-08-14``.
_SPLIT_SEP = "#"

# (#769) The SG-Ready states that mean SEM ASKED for the consumption. Energy
# booked in these is energy SEM shifted; everything else is energy the device
# would have used on its own. Named here, beside the ledger that sums them,
# rather than in the card that displays them.
SHIFTED_SPLITS = ("sg3", "sg4")

# (#772) The comfort buckets: did a comfort zone's kWh land inside its
# planned ``comfort:{did}`` block or outside it. The value of a pre-cool
# block is the energy it DISPLACES, not the energy it uses — a block that
# banked four hours of coasting and one that ran the AC at 03:00 and again
# at 17:00 book the same in-block kWh, and the difference lives entirely in
# the OUT bucket. The in/out ratio over time is the first honest answer to
# "is banking working here" (#705 Ph3's missing feedback, #755's first
# comfort signal). "No plan" files as OUT, not unlabeled — a night the
# planner never banked belongs in the ratio's denominator.
COMFORT_SPLIT_IN = "comfort_in_block"
COMFORT_SPLIT_OUT = "comfort_out_block"

# (#773) The midnight-keyed mirror of everything SEM can see the devices
# consume. Device ledger rows roll at SUNRISE (#620/#704); the home row rolls
# at MIDNIGHT. ``true_baseload = home − controlled`` across that mismatch
# would mis-book every small-hours kWh — the #703/#704 bug class — so the
# subtrahend is booked a second time at the filing seam, keyed by the
# calendar day, exactly the way ``MIDNIGHT_EV_CATEGORY`` mirrors the EV row.
# ``_EST`` is the slice of the mirror that came from rated×runtime estimates:
# it keeps the baseload DISPLAYABLE but disqualifies the day as a
# measurement (#755 contract 1 — an estimate may never train anything).
CONTROLLED_LOADS_CATEGORY = "controlled_loads"
CONTROLLED_LOADS_EST_CATEGORY = "controlled_loads_est"

# (#773) How many sealed days of baseload history are kept for the drift
# check. Two weeks spans an occupancy cycle (weekday/weekend) twice.
_BASELOAD_HISTORY_DAYS = 14

# (#724) The boundary the FLEET EV total falls back to when its chargers do not
# share a Charge-by deadline. Expressed as an offset so it flows through the
# same ``get_current_meter_day_offset_based`` path (and the same day memo) as a
# real deadline — "00:00" is calendar midnight by construction.
_FLEET_CALENDAR_OFFSET = "00:00"


def _valid_hhmm(value) -> bool:
    """A usable day-boundary offset: ``HH:MM`` on a real clock.

    (#724) The day memo round-trips through the store, where a hand edit or a
    format change can put anything. The time manager does NOT reject junk —
    it falls back to midnight — so validity must be decided here, before the
    memo is allowed to hold a day open.
    """
    if not isinstance(value, str):
        return False
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    return bool(m) and int(m.group(1)) < 24 and int(m.group(2)) < 60

# (#628) A balance term with no counter of its own may still take part in the
# home balance while it is physically ABSENT — an install with no battery
# integrates 0 kWh of battery charge all day, and demanding a BMS counter of it
# would disable the balance for no reason. Above this the term is present and
# unmetered, and the balance stands down rather than inherit its error.
UNMETERED_TERM_EPSILON_KWH = 0.05

# (#628) The daily home residual, spelled out. Same identity as
# ``PowerReadings.calculate_derived`` uses in watts, applied to the day's
# reconciled kWh rows instead of to one 10-second sample. EV is NOT here: it is
# subtracted separately from ``MIDNIGHT_EV_CATEGORY``, because it is the only
# term whose own bucket rolls on a different boundary.
_HOME_BALANCE_TERMS = (
    ("solar", 1.0),
    ("grid_import", 1.0),
    ("grid_export", -1.0),
    ("battery_discharge", 1.0),
    ("battery_charge", -1.0),
)


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce a restored scalar, falling back rather than raising (#668)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if value is not None:
            _LOGGER.warning(
                "Discarding non-numeric restored value %r — using %s", value, default
            )
        return default
    return float(value)


# Environmental impact constants
GRID_CO2_KG_PER_KWH = 0.128  # Swiss grid average
CO2_KG_PER_TREE_PER_YEAR = 22  # EPA estimate


class EnergyCalculator:
    """Calculates energy totals from power readings over time."""

    def __init__(self, config: Dict[str, Any], time_manager: TimeManager):
        """Initialize energy calculator."""
        self.config = config
        self._time_manager = time_manager

        # Accumulators for energy integration
        self._daily_accumulators: Dict[str, float] = {}
        self._monthly_accumulators: Dict[str, float] = {}
        self._yearly_accumulators: Dict[str, float] = {}
        self._lifetime_accumulators: Dict[str, float] = {}

        # Cost accumulators (incremental, rate-weighted) — fixes dynamic tariff mid-day recalculation
        self._daily_cost_accumulators: Dict[str, float] = {}
        self._monthly_cost_accumulators: Dict[str, float] = {}
        self._yearly_cost_accumulators: Dict[str, float] = {}

        # Last update time for integration
        self._last_update: Optional[datetime] = None

        # Cost rates
        self._import_rate = config.get("electricity_import_rate", 0.3387)
        self._export_rate = config.get("electricity_export_rate", 0.075)

        # Rate history for 7-day averaging (dynamic tariffs)
        self._rate_history: deque = deque(maxlen=30)

        # (#770) Share of the battery's STORED energy that was bought from
        # the grid. Autarky counts battery discharge as own supply; that is
        # only true for the solar-charged part, and the one-gate planner made
        # grid charging routine. 0.0 until the provenance store says
        # otherwise — an unknown-origin battery keeps the legacy credit
        # rather than being punished for a measurement SEM doesn't have.
        self._battery_grid_origin_share = 0.0

        # (#770) The battery as inventory with a cost basis. Charged tagged
        # by origin, discharged in proportion, pinned to the measured SOC.
        self._battery_provenance = BatteryProvenance()

        # (#660) Clamp engagement — how much each ``max(0, …)`` /
        # ``min(100, …)`` guard below actually REMOVED this cycle.
        #
        # The guards make every downstream range check unfireable: HealthCheck
        # used to verify ``0 ≤ autarky ≤ 100`` on a value clamped to that
        # range three lines after it was computed. Those checks reported
        # "clean" through the whole HA-PROD sign-bug family, and the autarky
        # bug of 2026-06-01 sat inside the range the whole time — the clamped
        # OUTPUT of a guard is definitionally fine;
        # what carries information is whether the clamp had to DO anything.
        # A single engagement is a rounding/transient artefact — a sustained
        # one is the formula being wrong (see ``HealthCheck.check_clamps``).
        self.clamp_engagement: Dict[str, float] = {}

        # Accumulated savings/costs (running totals for accurate ROI)
        self._accumulated_savings: float = 0.0
        self._accumulated_battery_savings: float = 0.0
        self._accumulated_cost: float = 0.0
        self._accumulated_export_revenue: float = 0.0
        self._accumulated_grid_import_kwh: float = 0.0
        self._accumulated_self_consumed_kwh: float = 0.0
        self._accumulated_export_kwh: float = 0.0

        # Hardware EV energy reconciliation (#658) — same baseline/anchor/delta
        # model as the solar counters below, for the same reason: the wallbox
        # counter and SEM's EV day bucket do NOT reset on the same boundary
        # (KEBA resets at midnight, ``ev_day`` rolls at the charge deadline), so
        # comparing absolute values compares different windows. A DELTA is
        # boundary-agnostic — a counter reset is just a reset.
        self._hass: Optional[HomeAssistant] = None
        self._ev_counter_entities: List[str] = []
        self._ev_counter_enabled: bool = False
        self._ev_counter_logged: bool = False
        self._ev_counter_baselines: Dict[str, Any] = {}
        # (#556) Daily-solar reconciliation against hardware production
        # counters — closes the cloud-poll undercount (integrating a power
        # sensor that reports 0/unavailable between polls). Baselines are
        # per-entity counter snapshots for the current day:
        # {"date": "YYYY-MM-DD", "<entity_id>": kwh_at_first_sight}.
        self._solar_counter_entities: List[str] = []
        self._solar_counter_enabled: bool = False
        self._solar_counter_logged: bool = False
        self._solar_counter_baselines: Dict[str, Any] = {}
        # (#628) Metered categories — grid import/export and battery
        # charge/discharge follow the utility/BMS counters the user already
        # declared in HA's Energy Dashboard. Same baseline/anchor/delta model
        # as solar and EV, but BIDIRECTIONAL: see
        # ``_reconcile_metered_energy``. Keyed by category:
        # {"grid_import": ["sensor.p1_import"], ...}.
        self._meter_counter_entities: Dict[str, List[str]] = {}
        # (#628 visibility) Whether each configured category's last
        # reconciliation attempt was counter-backed (None = never tried),
        # plus today's backed/skipped tallies for the diagnostics download.
        # The all-or-nothing skip used to be SILENT — a category with an
        # unreadable counter ran as a pure stopwatch indefinitely, and the
        # first symptom was a numbers-don't-match report weeks later.
        self._backing_state: Dict[str, Optional[bool]] = {}
        self._backing_tally: Dict[str, Dict[str, int]] = {}
        self._backing_tally_date: Optional[str] = None
        self._meter_counter_enabled: bool = False
        self._meter_counter_logged: bool = False
        self._meter_baselines: Dict[str, Dict[str, Any]] = {}
        # (#628) Which categories' daily values are COUNTER-BACKED this cycle —
        # the precondition for ``_reconcile_home_energy``. Rebuilt from scratch
        # every cycle and never persisted: it describes THIS cycle's reads, not
        # accumulated state, and a stale membership would let the home balance
        # run on an integrator nobody checked.
        self._counter_backed: Set[str] = set()
        self._home_balance_logged: bool = False
        # Baselines for the midnight EV mirror — same delta model as
        # ``_ev_counter_baselines``, keyed on the calendar day instead.
        self._midnight_ev_baselines: Dict[str, Any] = {}
        # First calendar day the midnight EV mirror was tracking. The balance
        # refuses to run on that day — see ``_reconcile_home_energy``.
        self._midnight_ev_since: Optional[date] = None
        # (#724) The deadline that opened the running EV day, and the day key
        # it produced. A deadline moved mid-day is deferred to the next
        # rollover rather than re-naming a day already accumulated into —
        # see ``_ev_reset_day``.
        self._ev_day_offset: Optional[str] = None
        self._ev_day_key: Optional[date] = None
        self._lifetime_seeded: bool = False
        self._yearly_seeded: bool = False
        self._yearly_seed_attempts: int = 0
        # Separate flag for the yearly COST backfill so it can correct installs
        # whose ENERGY was already seeded before the cost backfill existed.
        self._yearly_cost_seeded: bool = False
        # Auto-detected from recorder statistics (first solar energy entry)
        self._install_year_decimal: Optional[float] = None
        # (#773) Sealed days of the true-baseload residual, newest last.
        # One row per finished calendar day WITH a home row — a day without
        # one is a gap and is refused, never recorded as zero. Persisted.
        self._baseload_history: deque = deque(maxlen=_BASELOAD_HISTORY_DAYS)

    def _record_clamp(
        self, name: str, raw: float, clamped: float, eps: float,
    ) -> float:
        """Record how much a clamp removed, and return the clamped value.

        Writes (or clears) only its own key, so calculators that run at
        different points in the cycle don't wipe each other's records.
        """
        if abs(raw - clamped) > eps:
            self.clamp_engagement[name] = round(abs(raw - clamped), 3)
        else:
            self.clamp_engagement.pop(name, None)
        return clamped

    def _ev_deadlines(self) -> list[str]:
        """Every configured ``Charge by`` time: per charger, else the global
        default. Empty only pre-setup (no chargers AND no default)."""
        from ..consts.core import DEFAULT_EV_TARGET_TIME

        deadlines = []
        for c in self.config.get("ev_chargers") or []:
            tt = c.get("ev_target_time") or self.config.get("ev_target_time")
            if tt:
                deadlines.append(str(tt))
        if not deadlines:
            global_tt = self.config.get("ev_target_time") or DEFAULT_EV_TARGET_TIME
            if global_tt:
                deadlines.append(str(global_tt))
        return deadlines

    def _seed_ev_day_memo_from_legacy_rule(self) -> None:
        """(#724) Upgrade seam: adopt the new fleet rule at a rollover, not
        mid-day.

        First start on this code finds a store with EV buckets but no day
        memo. Re-deriving the day from the NEW rule right away would re-key a
        disagreeing fleet's running day mid-flight (calendar vs the old
        ``max(deadlines)`` answer) — the daily sensor would jump once at
        upgrade, the exact discontinuity the memo exists to prevent. Seeding
        the memo with the LEGACY rule instead means the running day keeps the
        identity it was accumulated under, and the calendar fallback takes
        over at that day's natural rollover. Agreeing fleets seed a value the
        new rule reproduces anyway, so this is a no-op for them.
        """
        deadlines = self._ev_deadlines()
        if not deadlines:
            return
        legacy = max(deadlines)
        try:
            day = self._time_manager.get_current_meter_day_offset_based(legacy)
        except (ValueError, TypeError):
            return
        self._ev_day_offset = legacy
        self._ev_day_key = day

    def _ev_reset_day(self, now: datetime):
        """Return today's EV-day bucket key, deadline-based (#279 follow-up).

        Mirrors the per-charger reset boundary so the GLOBAL daily_ev_energy
        sensor doesn't wipe at sunrise (~05:30 in summer) and instead rolls
        at the user's actual ``Charge by`` deadline (default 07:00).

        That holds while the fleet AGREES on a deadline. When chargers are on
        different Charge-by times there is no fleet deadline to roll on, and
        the total falls back to calendar midnight — the only boundary every
        charger shares (#724).

        Falls back to the legacy sunrise-based boundary only when no
        chargers + no global default are configured (transition / pre-setup).

        The deadline is a live setting (a ``time.`` entity on the dashboard),
        so it can move while a day is already accumulating. Applying the new
        boundary immediately would RE-NAME that day: at 12:00 a move from
        07:00 to 23:00 flips ``now < offset`` and the bucket key becomes
        yesterday's, so the sensor shows yesterday's total and further
        increments merge into it (#724). A boundary change is legitimate; a
        retroactive one is not. So the offset that OPENED the running day owns
        it, and a changed deadline is adopted at the next rollover of the old
        one. Both halves of that memo persist — a memo about a boundary that
        does not survive a restart across that boundary just reinstates the
        bug on the next reboot (#645 rule 2).
        """
        deadlines = self._ev_deadlines()
        if not deadlines:
            # Pure fallback — pre-#279 behaviour.
            return self._time_manager.get_current_meter_day_sunrise_based()

        # (#724) A FLEET total needs a boundary the whole fleet shares.
        #
        # When every charger agrees — one charger, or several on the same
        # Charge-by time — the deadline day is well-defined and #279 stands
        # untouched: the counter rolls at the user's deadline, not at sunrise.
        #
        # When they disagree there is no such thing as "the deadline day".
        # The old rule (LATEST deadline, so the bucket outlives the slowest
        # charger) bucketed the fleet total on ONE charger's clock while every
        # per-charger counter rolled on its own: a charger on 06:00 rolled at
        # 06:00 while the fleet figure waited until 22:00 for its sibling. A
        # number that describes none of its members cannot be reconciled
        # against anything. Midnight is the only boundary every charger
        # shares, so the fleet total falls back to it — which is also the
        # boundary every other daily energy figure already uses (#723).
        #
        # Per-charger continuity is unaffected: each charger's own counter
        # still rolls on its own deadline, which is where an overnight
        # session's identity actually lives.
        unique = set(deadlines)
        latest = max(deadlines) if len(unique) == 1 else _FLEET_CALENDAR_OFFSET

        # (#724) Hold the running day against a mid-day boundary move. The
        # validity check is load-bearing, not defensive: the real time
        # manager never raises on a junk offset — get_offset_time silently
        # falls back to MIDNIGHT — so an unvalidated corrupt memo would not
        # be discarded, it would quietly hold the day on a boundary nobody
        # configured (review of f9045aa).
        in_effect, running = self._ev_day_offset, self._ev_day_key
        if not _valid_hhmm(in_effect):
            self._ev_day_offset = None
            self._ev_day_key = None
            in_effect, running = None, None
        if in_effect and running is not None and str(in_effect) != latest:
            still_open = self._time_manager.get_current_meter_day_offset_based(
                str(in_effect)
            )
            if still_open == running:
                return running

        day = self._time_manager.get_current_meter_day_offset_based(latest)
        self._ev_day_offset = latest
        self._ev_day_key = day
        return day

    def calculate_energy(
        self, power: PowerReadings,
        power_flows: "Optional[PowerFlows]" = None,
    ) -> EnergyTotals:
        """Calculate energy totals by integrating power over time."""
        now = dt_util.now()
        today = now.date()  # Midnight-based reset — matches HA Energy Dashboard
        # EV: deadline-based reset (#279 follow-up). The per-charger counter
        # already rolls at each charger's Charge-by time; the GLOBAL
        # daily_ev_energy stayed on sunrise-based reset until now, so users
        # saw it wipe ~05:30 in summer even though the deadline was 07:00.
        # User-reported on 2026-05-29 06:28 local: counter showed 0 well
        # before the 07:00 deadline. Fix: use the same deadline-based
        # boundary the per-charger counters use.
        ev_day = self._ev_reset_day(now)
        month_key = f"{today.year}_{today.month}"
        year_key = f"{today.year}"

        # Calculate time delta
        if self._last_update is None:
            # First update - use config interval as safe default
            interval_hours = self.config.get("update_interval", 30) / 3600
        else:
            interval_seconds = (now - self._last_update).total_seconds()
            if interval_seconds < 0:
                # Clock went backwards (NTP correction, etc.) — skip
                self._last_update = now
                return self._build_current_totals(today, month_key, year_key)
            if interval_seconds > MAX_INTEGRATION_GAP_SECONDS:
                _LOGGER.warning(
                    "Energy integration gap: %.0fs > %ds limit — skipping cycle "
                    "to prevent accumulator spike (sensor restart/update?)",
                    interval_seconds, MAX_INTEGRATION_GAP_SECONDS,
                )
                self._last_update = now
                return self._build_current_totals(today, month_key, year_key)
            interval_hours = interval_seconds / 3600

        self._last_update = now

        # Check for day/month/year rollover and reset accumulators
        self._check_rollover(today, month_key, year_key)

        # (#628) This cycle's counter-backing starts empty — each reconciler
        # below records its own category only when it actually read a COMPLETE
        # counter set. ``_reconcile_home_energy`` reads the result.
        self._counter_backed = set()

        # Integrate power to energy
        energy = EnergyTotals()

        # Solar energy
        if power.solar_power >= MIN_POWER_THRESHOLD:
            solar_increment = (power.solar_power * interval_hours) / 1000  # kWh
            self._accumulate("solar", today, month_key, year_key, solar_increment)
        # (#556) hardware-counter reconciliation — upward-only correction
        # for cloud-polled power sensors; must run before the read below.
        self._reconcile_solar_energy(today, month_key, year_key)
        energy.daily_solar = self._get_daily("solar", today)
        energy.monthly_solar = self._get_monthly("solar", month_key)
        energy.yearly_solar = self._get_yearly("solar", year_key)
        energy.lifetime_solar = self._get_lifetime("solar")  # #573

        # Home consumption. The integral runs unconditionally — it is the
        # fallback and the anchor — but the READ moved below every other
        # category (#628): home is a residual of those categories, so it can
        # only be reconciled once they have been.
        if power.home_consumption_power >= MIN_POWER_THRESHOLD:
            home_increment = (power.home_consumption_power * interval_hours) / 1000
            self._accumulate("home", today, month_key, year_key, home_increment)

        # EV charging. The sunrise/deadline reset lives entirely in the DAY KEY
        # (``ev_day``) — the category is plain ``ev`` like every other category.
        # It used to be ``ev_daily_sun``, which smuggled the boundary into the
        # namespace and then lied about its own scope: ``_accumulate`` writes
        # daily, monthly, yearly AND lifetime under the category, so a name
        # containing "daily" was wrong for three of the four. Four independent
        # sites (both yearly reads, the recorder seeding, the reconcile monthly
        # write) had already guessed ``ev``; the accumulator was the outlier,
        # and yearly EV energy was consequently frozen at its startup seed
        # (#666, live-confirmed on PROD: daily 10.77 kWh, yearly 0.0).
        # EV daily keys still survive the midnight rollover — that exclusion now
        # matches on the ``ev_`` prefix (see ``_cleanup_old_accumulators``).
        # FLEET-READ: ``ev`` is the fleet daily total — matches
        # ``sensor.sem_daily_ev_energy``. Per-charger daily energy lives
        # on ``charger_<id>_daily_energy`` populated separately.
        if power.ev_power >= MIN_POWER_THRESHOLD:
            ev_increment = (power.ev_power * interval_hours) / 1000  # FLEET-READ: same fleet integration as the gate above.
            self._accumulate(EV_CATEGORY, ev_day, month_key, year_key, ev_increment)
            # (#628) …and into the CALENDAR-day mirror the home balance
            # subtracts. Written straight to the daily accumulators rather than
            # through ``_accumulate``: the mirror is daily-only by design, so
            # the monthly/yearly/lifetime writes ``_accumulate`` also performs
            # would double-count EV into every longer period.
            mirror_key = f"{MIDNIGHT_EV_CATEGORY}_{today}"
            self._daily_accumulators[mirror_key] = (
                self._daily_accumulators.get(mirror_key, 0.0) + ev_increment
            )
        # (#658) wallbox-counter reconciliation — recovers charging SEM was not
        # running to integrate; must run before the reads below, exactly like
        # its solar sibling.
        self._reconcile_ev_energy(ev_day, month_key, year_key)
        self._reconcile_midnight_ev_energy(today)  # (#628)

        energy.daily_ev = self._get_daily(EV_CATEGORY, ev_day)
        energy.monthly_ev = self._get_monthly(EV_CATEGORY, month_key)
        energy.yearly_ev = self._get_yearly(EV_CATEGORY, year_key)

        # Grid import
        if power.grid_import_power >= MIN_POWER_THRESHOLD:
            import_increment = (power.grid_import_power * interval_hours) / 1000
            self._accumulate("grid_import", today, month_key, year_key, import_increment)
            self._accumulate_cost("cost_import", today, month_key, year_key, import_increment * self._import_rate)
        # (#628) utility-meter reconciliation — bidirectional, so it must run
        # before the reads below exactly like its solar and EV siblings.
        self._reconcile_metered_energy(
            "grid_import", today, month_key, year_key,
            cost_key="cost_import", rate=self._import_rate,
        )
        energy.daily_grid_import = self._get_daily("grid_import", today)
        energy.monthly_grid_import = self._get_monthly("grid_import", month_key)
        energy.yearly_grid_import = self._get_yearly("grid_import", year_key)

        # Grid export
        if power.grid_export_power >= MIN_POWER_THRESHOLD:
            export_increment = (power.grid_export_power * interval_hours) / 1000
            self._accumulate("grid_export", today, month_key, year_key, export_increment)
            self._accumulate_cost("cost_export", today, month_key, year_key, export_increment * self._export_rate)
        self._reconcile_metered_energy(
            "grid_export", today, month_key, year_key,
            cost_key="cost_export", rate=self._export_rate,
        )
        energy.daily_grid_export = self._get_daily("grid_export", today)
        energy.monthly_grid_export = self._get_monthly("grid_export", month_key)
        energy.yearly_grid_export = self._get_yearly("grid_export", year_key)

        # Battery charge
        if power.battery_charge_power >= MIN_POWER_THRESHOLD:
            charge_increment = (power.battery_charge_power * interval_hours) / 1000
            self._accumulate("battery_charge", today, month_key, year_key, charge_increment)
            # (#770) …and again, told apart by origin. The flow layer has
            # always known which part came off the roof; it just never
            # reached the ledger, so a kWh bought in the valley discharged
            # against the full import price and the difference was called
            # savings.
            self._file_battery_charge_origin(
                power, power_flows, charge_increment, today,
            )
        # (#770) Pin the pool to the measured contents ONCE per cycle, after
        # the charge and before the draw. Integrated power drifts; SOC is
        # measured. Doing it only on discharge would leave the published
        # share describing a pool the battery does not hold.
        self._reconcile_provenance_to_soc(power)
        self._reconcile_metered_energy("battery_charge", today, month_key, year_key)
        energy.daily_battery_charge = self._get_daily("battery_charge", today)
        energy.monthly_battery_charge = self._get_monthly("battery_charge", month_key)
        energy.yearly_battery_charge = self._get_yearly("battery_charge", year_key)

        # Battery discharge
        if power.battery_discharge_power >= MIN_POWER_THRESHOLD:
            discharge_increment = (power.battery_discharge_power * interval_hours) / 1000
            self._accumulate("battery_discharge", today, month_key, year_key, discharge_increment)
            # (#770) What this discharge actually saved, not what a discharge
            # of free solar would have saved. Drawn from the pool in
            # proportion; the grid part only earns the SPREAD, because the
            # purchase already sits in the import cost.
            self._accumulate_cost(
                "cost_batt_savings", today, month_key, year_key,
                self._battery_discharge_savings(
                    power, discharge_increment, power_flows),
            )
        self._reconcile_metered_energy(
            "battery_discharge", today, month_key, year_key,
            cost_key="cost_batt_savings",
            # (#770) The counter correction has to value a kWh the same way
            # the live path does, or an install with a BMS counter would
            # quietly get the flat-rate answer back through the side door.
            rate=self._battery_provenance.implied_savings_rate(self._import_rate),
        )
        energy.daily_battery_discharge = self._get_daily("battery_discharge", today)
        energy.monthly_battery_discharge = self._get_monthly("battery_discharge", month_key)
        energy.yearly_battery_discharge = self._get_yearly("battery_discharge", year_key)

        # (#770) The provenance row. The money and the stored-share are
        # published by ``calculate_costs`` and ``calculate_performance``,
        # which own those types; only the two kWh rows are energy.
        _split = self.get_battery_charge_split(today)
        energy.daily_battery_charge_solar = round(_split["solar_today_kwh"], 2)
        energy.daily_battery_charge_grid = round(_split["grid_today_kwh"], 2)
        self.set_battery_grid_origin_share(
            self._battery_provenance.fleet_grid_fraction()
        )

        # Sanity checks — warn and cap if values exceed physical limits.
        # These run BEFORE the home balance (#628 review W1): the caps are the
        # sanity net for the metered rows, and home is derived FROM those rows.
        # Capping after the derivation would let one corrupt BMS counter push a
        # bogus figure into the home row for a cycle before the net caught it.
        battery_capacity = self.config.get("battery_capacity_kwh", 15)
        max_daily_battery = battery_capacity * 3  # 3 full cycles/day is generous limit
        inverter_kwp = self.config.get("system_size_kwp", 10)
        max_daily_solar = inverter_kwp * 16  # 16 peak sun hours is extreme max

        if energy.daily_battery_discharge > max_daily_battery:
            _LOGGER.warning(
                "Battery discharge %.1f kWh exceeds %.0f kWh daily limit (3x %.0f kWh capacity) — capping",
                energy.daily_battery_discharge, max_daily_battery, battery_capacity,
            )
            self._daily_accumulators[f"battery_discharge_{today}"] = max_daily_battery
            energy.daily_battery_discharge = max_daily_battery

        if energy.daily_battery_charge > max_daily_battery:
            _LOGGER.warning(
                "Battery charge %.1f kWh exceeds %.0f kWh daily limit — capping",
                energy.daily_battery_charge, max_daily_battery,
            )
            self._daily_accumulators[f"battery_charge_{today}"] = max_daily_battery
            energy.daily_battery_charge = max_daily_battery

        if energy.daily_solar > max_daily_solar:
            _LOGGER.warning(
                "Solar %.1f kWh exceeds %.0f kWh daily limit (%d kWp × 16h) — capping",
                energy.daily_solar, max_daily_solar, inverter_kwp,
            )
            self._daily_accumulators[f"solar_{today}"] = max_daily_solar
            energy.daily_solar = max_daily_solar

        # Home consumption — LAST (#628). Home is the residual of every row
        # above, so it can only be derived once they have all been reconciled
        # AND capped; its integral ran at the top of the cycle as the fallback
        # and the anchor. Reading it here is the whole point of the move.
        self._reconcile_home_energy(today, month_key, year_key)
        energy.daily_home = self._get_daily("home", today)
        energy.monthly_home = self._get_monthly("home", month_key)
        energy.yearly_home = self._get_yearly("home", year_key)

        # (#773) The audited residual, derived AFTER home because it is one
        # more subtraction from it. The W twin is filled by the coordinator,
        # which owns the live device draws.
        _baseload = self.get_true_baseload(today)
        energy.true_baseload_today = _baseload["today_kwh"]
        energy.controlled_loads_today = _baseload["controlled_today_kwh"]
        energy.true_baseload_measured = _baseload["measured"]

        # Solar self-consumption savings (incremental, rate-weighted for dynamic tariff accuracy)
        # Only tracks savings from solar — battery discharge savings are in cost_batt_savings.
        #
        # v1.7.0: use flow-attributed solar_to_home + solar_to_ev when
        # ``power_flows`` is passed (computed by ``calculate_power_flows``).
        # The legacy subtraction heuristic
        # ``(home + ev) - import - discharge`` undercounts savings whenever
        # the grid is simultaneously charging the battery (cheap-tariff
        # daytime, mixed solar+grid moments) because ``import_incr`` is the
        # raw grid pull — including the grid → battery slice that DIDN'T
        # displace any home consumption. Same bug class as the autarky
        # mis-attribution; see ``calculate_performance`` for the symmetric
        # fix.
        if power_flows is not None:
            solar_self_consumed = (
                ((power_flows.solar_to_home + power_flows.solar_to_ev)
                 * interval_hours) / 1000
            )
        else:
            home_incr = (power.home_consumption_power * interval_hours) / 1000 if power.home_consumption_power >= MIN_POWER_THRESHOLD else 0.0
            # FLEET-READ: legacy fallback path. ``power_flows`` is the
            # preferred input in the v1.7.0+ coordinator pipeline; this
            # branch only fires for the two-arg test fixtures that
            # pre-date the per-cycle ``calculate_power_flows`` call.
            ev_incr = (power.ev_power * interval_hours) / 1000 if power.ev_power >= MIN_POWER_THRESHOLD else 0.0
            import_incr = (power.grid_import_power * interval_hours) / 1000 if power.grid_import_power >= MIN_POWER_THRESHOLD else 0.0
            discharge_incr = (power.battery_discharge_power * interval_hours) / 1000 if power.battery_discharge_power >= MIN_POWER_THRESHOLD else 0.0
            # Solar self-consumed = total consumption minus what came from grid or battery discharge
            solar_self_consumed = max(0.0, (home_incr + ev_incr) - import_incr - discharge_incr)
        if solar_self_consumed > 0.0:
            self._accumulate_cost("cost_savings", today, month_key, year_key, solar_self_consumed * self._import_rate)

        return energy

    def _build_current_totals(self, today: date, month_key: str, year_key: str) -> EnergyTotals:
        """Return current accumulated totals without integrating new power.

        Used when a gap is detected to avoid energy spikes.
        """
        ev_day = self._ev_reset_day(dt_util.now())
        energy = EnergyTotals()
        energy.daily_solar = self._get_daily("solar", today)
        energy.monthly_solar = self._get_monthly("solar", month_key)
        energy.yearly_solar = self._get_yearly("solar", year_key)
        energy.lifetime_solar = self._get_lifetime("solar")  # #573
        energy.daily_home = self._get_daily("home", today)
        energy.monthly_home = self._get_monthly("home", month_key)
        energy.yearly_home = self._get_yearly("home", year_key)
        energy.daily_ev = self._get_daily(EV_CATEGORY, ev_day)
        energy.monthly_ev = self._get_monthly(EV_CATEGORY, month_key)
        energy.yearly_ev = self._get_yearly(EV_CATEGORY, year_key)
        energy.daily_grid_import = self._get_daily("grid_import", today)
        energy.monthly_grid_import = self._get_monthly("grid_import", month_key)
        energy.yearly_grid_import = self._get_yearly("grid_import", year_key)
        energy.daily_grid_export = self._get_daily("grid_export", today)
        energy.monthly_grid_export = self._get_monthly("grid_export", month_key)
        energy.yearly_grid_export = self._get_yearly("grid_export", year_key)
        energy.daily_battery_charge = self._get_daily("battery_charge", today)
        energy.monthly_battery_charge = self._get_monthly("battery_charge", month_key)
        energy.yearly_battery_charge = self._get_yearly("battery_charge", year_key)
        energy.daily_battery_discharge = self._get_daily("battery_discharge", today)
        energy.monthly_battery_discharge = self._get_monthly("battery_discharge", month_key)
        energy.yearly_battery_discharge = self._get_yearly("battery_discharge", year_key)
        # (#770) The provenance row is read back like every other row here. A
        # skipped cycle means "no new energy was integrated", not "the battery
        # is empty and cost nothing" — leaving these at their defaults would
        # flap the sensors to zero for one cycle after every sensor stall.
        # The cost and the stored-share need no equivalent: they are built by
        # ``calculate_costs`` / ``calculate_performance``, which run every
        # cycle and read the same accumulators regardless of the gap.
        _split = self.get_battery_charge_split(today)
        energy.daily_battery_charge_solar = round(_split["solar_today_kwh"], 2)
        energy.daily_battery_charge_grid = round(_split["grid_today_kwh"], 2)
        return energy

    def configure_ev_counters(
        self, hass: HomeAssistant, entity_ids: List[str], enabled: bool
    ) -> None:
        """Enable daily-EV reconciliation against wallbox counters (#658).

        ``entity_ids`` are the charger energy counters — lifetime (KEBA
        ``total_energy``, go-e ``energy_total``) or daily-resetting; both work,
        because only their DELTA is used.

        On a multi-charger install pass EVERY charger's counter: the bucket
        being reconciled is the FLEET daily total, so one charger's counter
        alone would credit its energy to the fleet and then be adopted as if it
        were all of it (bug class 3 — the read must match the scope). A PARTIAL
        set is still safe rather than wrong: adoption is upward-only against a
        fleet integration that already includes every charger, so a missing
        counter simply means that charger's downtime energy can't be recovered.

        Gated by the same ``prefer_hardware_energy`` option as the solar
        counters — it is the same promise ("trust the hardware over my
        integration"), and splitting it into two knobs would give users a way
        to half-answer one question.
        """
        self._hass = hass
        new_entities = [e for e in dict.fromkeys(entity_ids or []) if e]
        if new_entities != self._ev_counter_entities and self._ev_counter_entities:
            # Entity set changed mid-run (charger added/removed): the anchor was
            # calibrated to the old set. Drop the baselines so the next cycle
            # re-anchors on the current daily value instead of attributing a new
            # charger's whole lifetime counter to today.
            self._ev_counter_baselines = {}
            # ...and the calendar-day mirror the home balance subtracts, which
            # tracks the SAME entity set (#628 review W2). Per-entity
            # ``setdefault`` anchoring already makes a new charger harmless, but
            # leaving the mirror behind would silently break that symmetry the
            # day the two stop sharing ``_ev_counter_entities``. Mutate in
            # place — ``_reconcile_ev_bucket`` holds this dict by reference.
            self._midnight_ev_baselines.clear()
        self._ev_counter_entities = new_entities
        self._ev_counter_enabled = bool(enabled) and bool(self._ev_counter_entities)
        if self._ev_counter_enabled and not self._ev_counter_logged:
            self._ev_counter_logged = True
            _LOGGER.info(
                "Daily EV reconciliation against wallbox counters enabled: %s",
                ", ".join(self._ev_counter_entities),
            )

    def configure_solar_counters(
        self, hass: HomeAssistant, entity_ids: List[str], enabled: bool
    ) -> None:
        """Enable daily-solar reconciliation against hardware counters (#556).

        ``entity_ids`` are the inverter production counters (lifetime like
        Fronius ``pv_energy`` / Deye ``TotalActiveProduction``, or daily
        like ``DailyActiveProduction`` — both work, see
        ``_reconcile_solar_energy``). Gated by the ``prefer_hardware_energy``
        config option.
        """
        self._hass = hass
        new_entities = [e for e in (entity_ids or []) if e]
        if new_entities != self._solar_counter_entities and self._solar_counter_entities:
            # Entity set changed mid-run (ED re-read) — the anchor was
            # calibrated to the old set; drop baselines so the next cycle
            # re-anchors on the current daily value.
            self._solar_counter_baselines = {}
        self._solar_counter_entities = new_entities
        self._solar_counter_enabled = bool(enabled) and bool(self._solar_counter_entities)
        if self._solar_counter_enabled and not self._solar_counter_logged:
            self._solar_counter_logged = True
            _LOGGER.info(
                "Daily solar reconciliation against hardware counters enabled: %s",
                ", ".join(self._solar_counter_entities),
            )

    def configure_meter_counters(
        self, hass: HomeAssistant, mapping: Dict[str, List[str]], enabled: bool
    ) -> None:
        """Enable grid/battery reconciliation against hardware counters (#628).

        ``mapping`` is category → counter entity ids, e.g.
        ``{"grid_import": ["sensor.p1_import_t1", "sensor.p1_import_t2"]}``.
        These are exactly the sensors the user already declared in HA's Energy
        Dashboard, which is why the Energy Dashboard and SEM disagreeing on the
        same day is the bug: SEM was integrating power while the dashboard read
        the meter.

        Gated by the same ``prefer_hardware_energy`` option as the solar (#556)
        and EV (#658) counters — one promise, one knob.
        """
        self._hass = hass
        new_map: Dict[str, List[str]] = {}
        for category, entity_ids in (mapping or {}).items():
            cleaned = [e for e in dict.fromkeys(entity_ids or []) if e]
            if cleaned:
                new_map[category] = cleaned
        for category in set(new_map) | set(self._meter_counter_entities):
            if new_map.get(category) != self._meter_counter_entities.get(category):
                # Entity set changed for this category (ED re-read, meter
                # added/removed): its anchor was calibrated to the old set.
                # Drop only that category's baselines — the others are
                # independent and still valid.
                self._meter_baselines.pop(category, None)
        self._meter_counter_entities = new_map
        self._meter_counter_enabled = bool(enabled) and bool(new_map)
        if self._meter_counter_enabled and not self._meter_counter_logged:
            self._meter_counter_logged = True
            _LOGGER.info(
                "Daily grid/battery reconciliation against hardware counters "
                "enabled: %s",
                "; ".join(
                    f"{cat}={', '.join(ents)}" for cat, ents in sorted(new_map.items())
                ),
            )

    async def async_detect_install_date(self, hass: HomeAssistant) -> None:
        """Detect system install date from recorder statistics.

        Queries the statistics table for the earliest solar energy entry.
        The statistics table is never purged, so this finds the true
        first day the system produced energy — more accurate than any
        manual configuration.
        """
        if self._install_year_decimal is not None:
            return

        try:
            from homeassistant.components.recorder import get_instance

            def _query_first_solar_stat():
                """Find earliest solar statistics entry."""
                import sqlite3
                db_url = hass.config.config_dir + "/home-assistant_v2.db"
                conn = sqlite3.connect(db_url)
                cur = conn.cursor()
                cur.execute("""
                    SELECT MIN(s.start_ts)
                    FROM statistics s
                    JOIN statistics_meta sm ON s.metadata_id = sm.id
                    WHERE sm.statistic_id LIKE '%solar%'
                       OR sm.statistic_id LIKE '%inverter%ertrag%'
                       OR sm.statistic_id LIKE '%gesamtenergieertrag%'
                       OR sm.statistic_id LIKE '%pv%energy%'
                """)
                row = cur.fetchone()
                conn.close()
                return row[0] if row and row[0] else None

            first_ts = await get_instance(hass).async_add_executor_job(
                _query_first_solar_stat
            )

            if first_ts:
                first_dt = datetime.fromtimestamp(first_ts)
                self._install_year_decimal = round(
                    first_dt.year + first_dt.month / 12, 2
                )
                _LOGGER.info(
                    "System install date auto-detected from statistics: %s (%.2f)",
                    first_dt.strftime("%Y-%m-%d"),
                    self._install_year_decimal,
                )
            else:
                _LOGGER.debug("No solar statistics found — using current year as fallback")

        except Exception as e:
            _LOGGER.debug("Could not detect install date from statistics: %s", e)

    @staticmethod
    def _energy_state_kwh(state) -> float:
        """Energy-counter state → kWh, honoring unit_of_measurement.

        #551 — hardware lifetime counters are NOT all kWh: Fronius
        Gen24/Verto lifetime energy sensors report **Wh**. Reading them
        raw inflated the lifetime accumulators ×1000 (a 2-day-old install
        showed 21,350 battery cycles and a health score pinned at the
        70% cap). Unknown/missing units keep the previous assume-kWh
        behavior.
        """
        # #641 — this rule was the reference for the shared one; the body now
        # delegates so there is exactly one Wh/MWh table. The method stays as
        # the name the rest of the class (and its tests) call.
        return energy_state_to_kwh(state, default=0.0)

    def seed_lifetime_from_hardware(self, hass: HomeAssistant, ed_config) -> None:
        """Seed lifetime accumulators from hardware energy counters.

        Reads total energy from the HA Energy Dashboard sensors (which
        represent all-time hardware counters) and uses them as the baseline
        for lifetime tracking. Only runs once — skipped if lifetime
        accumulators already have data.
        """
        if self._lifetime_seeded:
            return
        if not ed_config:
            return

        # Read hardware total to compare
        def _read(entity_id):
            if not entity_id:
                return 0.0
            state = hass.states.get(entity_id)
            if state and state.state not in ("unknown", "unavailable", None):
                return self._energy_state_kwh(state)  # #551 unit-aware
            return 0.0

        # Read all hardware counters first
        # (#556) multi-string installs have several solar counters — seed
        # from their SUM, matching what the daily reconciliation tracks
        # (single-counter seeding could later SHRINK lifetime on re-seed).
        solar_list = list(getattr(ed_config, "solar_energy_list", None) or [])
        if solar_list:
            solar = sum(_read(e) for e in solar_list)
        else:
            solar = _read(ed_config.solar_energy)
        grid_import = _read(ed_config.grid_import_energy)
        grid_export = _read(ed_config.grid_export_energy)
        batt_charge = _read(ed_config.battery_charge_energy)
        batt_discharge = _read(ed_config.battery_discharge_energy)

        _LOGGER.debug(
            "Lifetime seed check: hw solar=%.0f import=%.0f export=%.0f "
            "batt_c=%.0f batt_d=%.0f",
            solar, grid_import, grid_export, batt_charge, batt_discharge,
        )

        # ALL key sensors must be available before seeding.
        # Include battery — they can take 30-60s longer to load (#110).
        if solar < 100 or grid_import < 10 or grid_export < 10:
            _LOGGER.debug(
                "Lifetime seed waiting: solar=%.0f import=%.0f export=%.0f "
                "(all must be > threshold)",
                solar, grid_import, grid_export,
            )
            return
        if (batt_charge < 1 or batt_discharge < 1) and (batt_charge + batt_discharge) < 10:
            _LOGGER.debug(
                "Lifetime seed waiting for battery: charge=%.0f discharge=%.0f",
                batt_charge, batt_discharge,
            )
            return

        # Check if ALL sensors are properly seeded (not just solar).
        # Re-seed any sensor that is <50% of the hardware counter —
        # this fixes the race condition where solar loaded first but
        # grid/battery were unavailable during initial seeding (#110).
        current = self._lifetime_accumulators
        needs_seed = False
        checks = [
            ("lifetime_solar", solar),
            ("lifetime_grid_import", grid_import),
            ("lifetime_grid_export", grid_export),
            ("lifetime_battery_charge", batt_charge),
            ("lifetime_battery_discharge", batt_discharge),
        ]
        for key, hw_value in checks:
            stored = current.get(key, 0)
            if hw_value > 100 and stored < hw_value * 0.5:
                _LOGGER.info(
                    "Lifetime re-seed needed: %s stored=%.0f hw=%.0f (%.0f%%)",
                    key, stored, hw_value, (stored / hw_value * 100) if hw_value > 0 else 0,
                )
                needs_seed = True
                break
            # #551 — DOWNWARD self-heal: installs that seeded before the
            # unit-aware read stored Wh values as kWh (×1000). The
            # accumulator can never legitimately dwarf its own hardware
            # counter, so stored >> hw means a corrupted seed — re-seed
            # from the (now unit-corrected) counter.
            if hw_value > 10 and stored > hw_value * 2:
                _LOGGER.info(
                    "Lifetime re-seed (downward, #551 unit fix): %s "
                    "stored=%.0f hw=%.0f", key, stored, hw_value,
                )
                needs_seed = True
                break

        if not needs_seed and current.get("lifetime_solar", 0) > solar * 0.9:
            self._lifetime_seeded = True
            return

        # Seed (or re-seed) all lifetime accumulators from hardware
        self._lifetime_accumulators["lifetime_solar"] = solar
        self._lifetime_accumulators["lifetime_grid_import"] = grid_import
        self._lifetime_accumulators["lifetime_grid_export"] = grid_export
        self._lifetime_accumulators["lifetime_battery_charge"] = batt_charge
        self._lifetime_accumulators["lifetime_battery_discharge"] = batt_discharge
        home = max(0, solar + grid_import + batt_discharge - grid_export - batt_charge)
        self._lifetime_accumulators["lifetime_home"] = home

        # Seed EV from hardware counter (KEBA total energy etc.)
        ev_total = 0.0
        for dev in ed_config.device_consumption:
            energy_sensor = dev.get("stat_consumption", "")
            if any(p in energy_sensor.lower() for p in ["keba", "ev", "charger", "wallbox", "easee"]):
                ev_total = _read(energy_sensor)
                break
        if ev_total > 0:
            self._lifetime_accumulators["lifetime_ev"] = ev_total

        self._lifetime_seeded = True
        _LOGGER.info(
            "Lifetime seeded from hardware: solar=%.0f import=%.0f export=%.0f "
            "batt_charge=%.0f batt_discharge=%.0f home=%.0f ev=%.0f kWh",
            solar, grid_import, grid_export, batt_charge, batt_discharge, home, ev_total,
        )

    async def seed_yearly_from_statistics(self, hass: HomeAssistant, ed_config) -> None:
        """Seed yearly accumulators from HA recorder statistics.

        On first install mid-year, yearly sensors would start at zero.
        This reads cumulative energy stats from the HA recorder for
        Jan 1 to now and seeds the yearly accumulators. Runs once.
        """
        # Yearly COST backfill — runs INDEPENDENTLY of the energy seed (own
        # flag) so it also corrects installs whose ENERGY was seeded BEFORE
        # this cost backfill existed: those had yearly_cost == monthly_cost
        # ("month and year are the same"). Needs the yearly energy present, so
        # it's a no-op until that's seeded; for a fresh install it runs from
        # the success path below instead.
        self._maybe_seed_yearly_cost(str(dt_util.now().year))

        if self._yearly_seeded:
            return
        if not ed_config:
            return

        # Stop retrying after 3 attempts — recorder may not be compatible
        # (e.g. Python 3.14 blocking call detection in HA core)
        self._yearly_seed_attempts += 1
        if self._yearly_seed_attempts > 3:
            self._yearly_seeded = True
            _LOGGER.info(
                "Yearly seeding skipped after %d failed attempts — "
                "yearly accumulators will build up from daily tracking",
                self._yearly_seed_attempts - 1,
            )
            return

        year_key = str(dt_util.now().year)

        # If yearly accumulators already have significant data, skip
        current_total = sum(
            v for k, v in self._yearly_accumulators.items()
            if k.endswith(year_key)
        )
        if current_total > 10:
            self._yearly_seeded = True
            _LOGGER.debug("Yearly accumulators already have %.1f kWh, skipping seed", current_total)
            return

        try:
            from homeassistant.components.recorder.statistics import (
                statistics_during_period,
            )
        except ImportError:
            _LOGGER.debug("Recorder not available for yearly seeding")
            return

        # Build entity → category mapping from Energy Dashboard config
        entity_map = {}
        if ed_config.solar_energy:
            entity_map[ed_config.solar_energy] = "solar"
        if ed_config.grid_import_energy:
            entity_map[ed_config.grid_import_energy] = "grid_import"
        if ed_config.grid_export_energy:
            entity_map[ed_config.grid_export_energy] = "grid_export"
        if ed_config.battery_charge_energy:
            entity_map[ed_config.battery_charge_energy] = "battery_charge"
        if ed_config.battery_discharge_energy:
            entity_map[ed_config.battery_discharge_energy] = "battery_discharge"

        if not entity_map:
            _LOGGER.debug("No energy entities in ED config for yearly seeding")
            return

        # Query statistics from Jan 1 of current year
        now = dt_util.now()
        start_time = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        entity_ids = list(entity_map.keys())

        try:
            stats = await statistics_during_period(
                hass, start_time, None, entity_ids, "hour", None, {"sum"}
            )
        except Exception as e:
            _LOGGER.warning("Failed to query recorder statistics for yearly seeding: %s", e)
            return

        if not stats:
            _LOGGER.debug("No recorder statistics available for yearly seeding")
            return

        # Extract yearly energy: difference between latest and first sum
        seeded = {}
        for entity_id, category in entity_map.items():
            entity_stats = stats.get(entity_id, [])
            if len(entity_stats) < 2:
                seeded[category] = 0.0
                continue
            first_sum = entity_stats[0].get("sum") if entity_stats[0].get("sum") is not None else 0.0
            last_sum = entity_stats[-1].get("sum") if entity_stats[-1].get("sum") is not None else 0.0
            yearly_energy = max(0, last_sum - first_sum)
            seeded[category] = yearly_energy
            self._yearly_accumulators[f"{category}_{year_key}"] = yearly_energy

        # Derive home consumption from energy balance
        solar = seeded.get("solar", 0)
        grid_import = seeded.get("grid_import", 0)
        grid_export = seeded.get("grid_export", 0)
        batt_charge = seeded.get("battery_charge", 0)
        batt_discharge = seeded.get("battery_discharge", 0)
        home = max(0, solar + grid_import + batt_discharge - grid_export - batt_charge)
        self._yearly_accumulators[f"home_{year_key}"] = home
        seeded["home"] = home

        # Seed EV from device consumption (same pattern as lifetime)
        ev_total = 0.0
        if hasattr(ed_config, "device_consumption") and ed_config.device_consumption:
            for dev in ed_config.device_consumption:
                energy_sensor = dev.get("stat_consumption", "")
                if any(p in energy_sensor.lower() for p in ["keba", "ev", "charger", "wallbox", "easee"]):
                    ev_stats = stats.get(energy_sensor, [])
                    if not ev_stats:
                        # Try querying separately
                        try:
                            ev_result = await statistics_during_period(
                                hass, start_time, None, [energy_sensor], "hour", None, {"sum"}
                            )
                            ev_stats = ev_result.get(energy_sensor, [])
                        except Exception:
                            pass
                    if len(ev_stats) >= 2:
                        last_ev = ev_stats[-1].get("sum") if ev_stats[-1].get("sum") is not None else 0
                        first_ev = ev_stats[0].get("sum") if ev_stats[0].get("sum") is not None else 0
                        ev_total = max(0, last_ev - first_ev)
                    break
        if ev_total > 0:
            # #666: through the constant, like every other EV key. This site
            # already spelled it "ev" — it was the *accumulate* call that
            # disagreed, so the seed landed where the reads looked and the
            # sensor was briefly right after each restart before freezing again.
            self._yearly_accumulators[f"{EV_CATEGORY}_{year_key}"] = ev_total
            seeded[EV_CATEGORY] = ev_total

        # Now that the yearly ENERGY is seeded, derive the yearly COST too.
        self._maybe_seed_yearly_cost(year_key)

        self._yearly_seeded = True
        _LOGGER.info(
            "Yearly accumulators seeded from recorder: solar=%.1f import=%.1f export=%.1f "
            "batt_charge=%.1f batt_discharge=%.1f home=%.1f ev=%.1f kWh",
            seeded.get("solar", 0), seeded.get("grid_import", 0), seeded.get("grid_export", 0),
            seeded.get("battery_charge", 0), seeded.get("battery_discharge", 0),
            home, ev_total,
        )

    def _maybe_seed_yearly_cost(self, year_key: str) -> None:
        """Backfill the yearly COST accumulators from the (seeded) yearly
        ENERGY × average rate — once.

        Without this, yearly cost only held the live-accumulated portion (since
        cost tracking started this month) and therefore equalled the MONTHLY
        cost ('month and year are the same'). The recorder has historical
        energy but NOT SEM's historical hourly prices, so the backfill is
        valued at an AVERAGE rate (7-day rolling, falling back to the
        current/config rate) — an ESTIMATE for the pre-tracking period on a
        dynamic tariff; the live portion since install stays exact.

        SET (not add): the seeded energy spans Jan→now, so this is the
        full-year cost up to now and live accumulation continues from here
        (disjoint — no double count), exactly like the energy seed. Idempotent
        (``_yearly_cost_seeded`` flag); a no-op until the yearly energy exists.
        """
        if self._yearly_cost_seeded:
            return
        ya = self._yearly_accumulators
        grid_import = float(ya.get(f"grid_import_{year_key}", 0.0) or 0.0)
        solar = float(ya.get(f"solar_{year_key}", 0.0) or 0.0)
        if grid_import <= 0 and solar <= 0:
            return  # yearly energy not seeded yet — retry on a later call
        grid_export = float(ya.get(f"grid_export_{year_key}", 0.0) or 0.0)
        batt_charge = float(ya.get(f"battery_charge_{year_key}", 0.0) or 0.0)
        batt_discharge = float(ya.get(f"battery_discharge_{year_key}", 0.0) or 0.0)
        imp_rate = self._get_avg_import_rate()
        exp_rate = self._get_avg_export_rate()
        # Avoided-import savings split to mirror the live accumulators and avoid
        # double counting: solar used DIRECTLY (not exported, not stored) +
        # battery discharged to load (stored solar is counted there, not here).
        solar_direct = max(0.0, solar - grid_export - batt_charge)
        ca = self._yearly_cost_accumulators
        ca[f"cost_import_{year_key}"] = round(grid_import * imp_rate, 4)
        ca[f"cost_export_{year_key}"] = round(grid_export * exp_rate, 4)
        ca[f"cost_savings_{year_key}"] = round(solar_direct * imp_rate, 4)
        # (#770) The backfilled discharge is credited at the FULL import rate
        # on purpose. The provenance store only knows what it watched; the
        # pre-tracking year has no origin record at all, and unknown origin
        # keeps the legacy credit rather than being charged for a measurement
        # SEM never took. Live accumulation from here on is split properly.
        ca[f"cost_batt_savings_{year_key}"] = round(batt_discharge * imp_rate, 4)
        self._yearly_cost_seeded = True
        _LOGGER.info(
            "Yearly COST seeded (estimate @ avg import %.4f / export %.4f): "
            "import=%.2f export=%.2f solar_savings=%.2f batt_savings=%.2f CHF",
            imp_rate, exp_rate, grid_import * imp_rate, grid_export * exp_rate,
            solar_direct * imp_rate, batt_discharge * imp_rate,
        )

    def _sun_is_down(self) -> bool:
        """Is the sun below the horizon right now? (#681)

        A solar *production* counter cannot legitimately advance in the dark,
        so movement while the sun is down is never PV. On a DC-coupled hybrid
        the inverter's total-yield counter measures AC OUTPUT — at night that
        is the battery discharging — and crediting it as solar booked 3.06 kWh
        of "production" before sunrise on a live Huawei SUN2000 + LUNA2000
        (26.07.2026: counter +0.01 kWh every ~70 s all night with PV power at
        0 W; 0.51 kWh/h ≈ the 510 W house load the battery was serving).

        A missing or unknown ``sun.sun`` means "do not gate": reconciliation
        keeps its pre-#681 behaviour rather than silently switching itself off
        on an install whose sun entity is absent.

        This gate also covers the whole of an overnight charge, and not by
        luck: ``TimeManager.get_night_window`` reads the SAME ``sun.sun`` and
        clamps the window to ``max(sunset+10min, earliest_start)`` ..
        ``min(sunrise, latest_end)``, so night charging is always a subset of
        darkness. That matters because the counter passes grid power through
        to the car at kW scale — far bigger than the 510 W house load this was
        caught with. Relaxing either clamp to let a session run past sunrise
        would start booking that pass-through as production again; the
        tripwire is ``TestTheNightWindowLiesInsideTheGate``.
        """
        state = self._hass.states.get("sun.sun") if self._hass else None
        return bool(state) and getattr(state, "state", None) == "below_horizon"

    def _reconcile_solar_energy(
        self, today: date, month_key: str, year_key: str
    ) -> None:
        """Track daily solar against hardware production counters (#556).

        Power integration undercounts badly when the solar power sensor is
        cloud-polled and sits at 0/unavailable between polls (Deye Cloud:
        SEM 6.2 kWh vs inverter 18.6 kWh). The inverter's own energy
        counter is the truth, so when counters are configured
        (``prefer_hardware_energy``), daily solar follows them:

        - Per-entity baseline = counter value at first sight today. Counter
          deltas since baseline are credited ON TOP of whatever integration
          had accumulated up to that moment (pre-baseline production stays).
        - Works for lifetime counters (baseline = large number) and daily
          counters (baseline ≈ 0 after midnight) alike.
        - Counter going backwards (inverter reboot / midnight reset of a
          daily counter) → re-baseline that entity; accumulated value keeps.
        - ADOPTION IS UPWARD-ONLY (like EV reconciliation): integration
          remains the floor, so an unavailable/stale/partial counter can
          never shrink the day. The delta propagates to monthly, yearly and
          lifetime so all periods stay consistent.
        - IN DARKNESS THE COUNTER IS NOT CREDITED (#681) — see
          ``_sun_is_down``. Upward-only adoption is what makes this
          mandatory: a hybrid's yield counter over-reports at night (battery
          discharge) and under-reports by day (PV going DC→battery never
          appears as AC yield), and keeping only the maximum ratchets the
          night inflation in instead of letting the two cancel.

        Known limitation: cost savings are computed from live power flows,
        so cost figures for counter-recovered energy remain approximate.
        """
        if not self._solar_counter_enabled or not self._hass:
            return

        today_str = str(today)
        bl = self._solar_counter_baselines
        if bl.get("date") != today_str or "base" not in bl or "last" not in bl:
            # Day rollover (or first run / legacy or damaged shape):
            # fresh baselines for the new day.
            bl = self._solar_counter_baselines = {
                "date": today_str, "base": {}, "last": {},
            }

        daily_key = f"solar_{today}"
        integrated = self._daily_accumulators.get(daily_key, 0.0)

        readings: Dict[str, float] = {}
        for entity_id in self._solar_counter_entities:
            state = self._hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable", None):
                continue
            value = self._energy_state_kwh(state)  # #551 unit-aware
            if value >= 0:
                readings[entity_id] = value

        if not readings:
            return

        # (#628) A COMPLETE counter set makes today's solar row counter-backed,
        # which is what lets it take part in the home balance. Completeness
        # matters here for the same reason it does in
        # ``_reconcile_metered_energy``: on a two-inverter install with one
        # inverter unavailable the row is only partly the hardware's, and the
        # home residual would silently absorb the difference. Marked in
        # darkness too — the counter is not CREDITED at night (#681), but the
        # value it established by sunset still stands and PV is zero.
        if len(readings) == len(self._solar_counter_entities):
            self._counter_backed.add("solar")

        if self._sun_is_down():
            # Darkness: absorb the counter's movement into the baseline
            # instead of crediting it as production (#681). Rolling the
            # baseline forward also swallows a daily counter's midnight reset
            # for free — there is nothing to re-anchor because nothing was
            # adopted, and ``anchor`` stays unset until the first daylight
            # cycle, where it lands on the integrated value at sunrise.
            for entity_id, value in readings.items():
                bl["base"][entity_id] = value
                bl["last"][entity_id] = value
            return

        # A counter that went BACKWARDS since its last reading (inverter
        # reboot, or a daily-type counter resetting) invalidates the whole
        # baseline set: its past contribution is already inside the adopted
        # daily value, so deltas must restart from here. Re-baseline
        # everything and re-anchor on the current daily value — nothing
        # lost, nothing double-counted. (Compared against the LAST reading,
        # not the baseline: after a reset the value is usually still above
        # a lifetime baseline of 0 but below where it just was.)
        reset = any(
            entity_id in bl["last"]
            and value < bl["last"][entity_id] - 0.001
            for entity_id, value in readings.items()
        )
        if reset:
            bl["base"] = {}
            bl.pop("anchor", None)
        for entity_id, value in readings.items():
            bl["base"].setdefault(entity_id, value)
            bl["last"][entity_id] = value
        # The counters track production SINCE their baselines; production
        # before that (SEM down over midnight, counter loaded late) is
        # only known to the integrator — anchor on the daily value at
        # baseline time: target = anchor + counter deltas.
        bl.setdefault("anchor", integrated)

        counter_daily = sum(
            value - bl["base"][entity_id]
            for entity_id, value in readings.items()
        )
        target = bl["anchor"] + counter_daily

        # Sanity cap — same physical bound the integrator uses.
        inverter_kwp = self.config.get("system_size_kwp", 10)
        if target > inverter_kwp * 16:
            _LOGGER.warning(
                "Solar counter reconciliation target %.1f kWh exceeds "
                "%d kWp × 16h — ignoring this cycle (unit mismatch?)",
                target, inverter_kwp,
            )
            return

        delta = target - integrated
        if delta <= RECONCILIATION_THRESHOLD:
            return  # Upward-only; small drift stays with the integrator.

        _LOGGER.info(
            "Solar energy reconciliation: counter=%.2f kWh > integrated=%.2f kWh "
            "— adopting counter value (+%.2f kWh)",
            target, integrated, delta,
        )
        self._daily_accumulators[daily_key] = target
        for accumulators, key in (
            (self._monthly_accumulators, f"solar_{month_key}"),
            (self._yearly_accumulators, f"solar_{year_key}"),
            (self._lifetime_accumulators, "lifetime_solar"),
        ):
            accumulators[key] = accumulators.get(key, 0.0) + delta

    def _reconcile_ev_energy(
        self, ev_day: date, month_key: str, year_key: str
    ) -> None:
        """Daily EV energy follows the wallbox counters (#658).

        SEM integrates the charger power sensor every cycle. When SEM is down
        (HA restart, update, power blip) or the charger is started from its own
        app while HA is asleep, that energy is never integrated — the KEBA app
        says 8 kWh and SEM says 5.5, and the user files a numbers-don't-match
        report. The wallbox's own counter saw all of it.

        Same baseline/anchor/delta model as ``_reconcile_solar_energy``, and
        for a sharper reason: the counter and the bucket do NOT share a day
        boundary. A KEBA daily counter resets at midnight; ``ev_day`` rolls at
        the charge deadline (#279). Between the two — the prime overnight
        charging window — an absolute "hardware > integrated, adopt it"
        comparison compares two different windows, adopts a phantom value and
        double-adds the delta to the month. That is why the original was parked
        with its tests skipped since the day it was written. A DELTA has no such
        problem: a counter reset is just a reset, handled below.

        - Counters may be lifetime or daily-resetting; only deltas are used.
        - Counter going backwards (charger reboot, midnight reset of a daily
          counter) → re-baseline; the accumulated value keeps.
        - ADOPTION IS UPWARD-ONLY: integration remains the floor, so an
          unavailable/stale/partial counter set can never shrink the day. The
          delta propagates to monthly, yearly and lifetime so all periods stay
          consistent (#666: they are written by one call, so they are corrected
          by one call too).
        - The bucket is the FLEET daily total, so ``_ev_counter_entities`` must
          be every charger's counter — see ``configure_ev_counters``.

        Known limitation: EV cost and solar-share are computed from live power
        flows, so those figures for counter-recovered energy stay approximate —
        SEM knows the energy arrived but not what it was made of.
        """
        self._reconcile_ev_bucket(
            EV_CATEGORY, ev_day, self._ev_counter_baselines,
            periods=(
                (self._monthly_accumulators, f"{EV_CATEGORY}_{month_key}"),
                (self._yearly_accumulators, f"{EV_CATEGORY}_{year_key}"),
                (self._lifetime_accumulators, f"lifetime_{EV_CATEGORY}"),
            ),
        )

    def _reconcile_midnight_ev_energy(self, today: date) -> None:
        """Reconcile the CALENDAR-day EV mirror the home balance subtracts (#628).

        Identical model to ``_reconcile_ev_energy`` — same counters, same
        wallboxes, same delta arithmetic — differing in exactly two things, and
        both of them are the point:

        - the day key is the calendar day, not ``_ev_reset_day``; and
        - it is DAILY-ONLY. Monthly, yearly and lifetime EV are owned by the
          deadline-keyed bucket, so there is still one EV total in the system
          and this mirror can never double-count into a longer period.

        It exists because daily home is a calendar-day quantity and its EV term
        has to be one too. Composing a midnight row out of a deadline row is the
        day-boundary bug class closed in #703/#704; a car charging 04:00–06:00
        belongs to the calendar day it charged on, whatever bucket the EV
        counter puts it in.
        """
        self._reconcile_ev_bucket(
            MIDNIGHT_EV_CATEGORY, today, self._midnight_ev_baselines,
        )

    def _reconcile_ev_bucket(
        self,
        category: str,
        day: date,
        baselines: Dict[str, Any],
        periods: tuple = (),
    ) -> None:
        """Shared body of the two EV counter reconciliations (#658, #628).

        One class, two instances: the deadline-keyed fleet bucket and the
        calendar-day mirror the home balance needs. They differ only in their
        day key and in which longer periods they feed, so they are parameters —
        a second hand-written copy of a delta model is how the two drift apart.

        ``baselines`` is mutated IN PLACE (never rebound) so the caller's
        attribute keeps pointing at the live dict across a day rollover.
        """
        if not self._ev_counter_enabled or not self._hass:
            return

        day_str = str(day)
        bl = baselines
        if bl.get("date") != day_str or "base" not in bl or "last" not in bl:
            # Day rollover (or first run / legacy or damaged shape):
            # fresh baselines for the new day.
            bl.clear()
            bl.update({"date": day_str, "base": {}, "last": {}})

        daily_key = f"{category}_{day}"
        integrated = self._daily_accumulators.get(daily_key, 0.0)

        readings: Dict[str, float] = {}
        for entity_id in self._ev_counter_entities:
            state = self._hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable", None):
                continue
            value = self._energy_state_kwh(state)  # #551 unit-aware
            if value >= 0:
                readings[entity_id] = value

        if not readings:
            return

        # A counter that went BACKWARDS since its last reading invalidates the
        # whole baseline set: its past contribution is already inside the
        # adopted daily value, so deltas must restart from here. This is the
        # midnight reset of a daily-type counter, and it is why the boundary
        # mismatch that parked this method is a non-issue under the delta model.
        reset = any(
            entity_id in bl["last"]
            and value < bl["last"][entity_id] - 0.001
            for entity_id, value in readings.items()
        )
        if reset:
            bl["base"] = {}
            bl.pop("anchor", None)
        for entity_id, value in readings.items():
            bl["base"].setdefault(entity_id, value)
            bl["last"][entity_id] = value
        # The counters track charging SINCE their baselines; charging before
        # that (SEM down over the EV-day boundary, charger added late) is only
        # known to the integrator — anchor on the daily value at baseline time:
        # target = anchor + counter deltas.
        bl.setdefault("anchor", integrated)

        counter_daily = sum(
            value - bl["base"][entity_id]
            for entity_id, value in readings.items()
        )
        target = bl["anchor"] + counter_daily

        # Sanity cap — the fleet's own physical ceiling, from the configured
        # charger limits. Catches a counter in the wrong magnitude that
        # ``_energy_state_kwh`` could not classify from its unit string.
        max_daily = self._max_daily_ev_kwh()
        if target > max_daily:
            _LOGGER.warning(
                "EV counter reconciliation target %.1f kWh exceeds the fleet's "
                "%.0f kWh/day ceiling — ignoring this cycle (unit mismatch?)",
                target, max_daily,
            )
            return

        delta = target - integrated
        if delta <= RECONCILIATION_THRESHOLD:
            return  # Upward-only; small drift stays with the integrator.

        _LOGGER.info(
            "%s energy reconciliation: counter=%.2f kWh > integrated=%.2f kWh "
            "— adopting counter value (+%.2f kWh)",
            category, target, integrated, delta,
        )
        self._daily_accumulators[daily_key] = target
        for accumulators, key in periods:
            accumulators[key] = accumulators.get(key, 0.0) + delta

    def _tally_backing(self, category: str, today_str: str, backed: bool) -> None:
        """(#628 visibility) Count and announce counter-backing transitions.

        The all-or-nothing skip is correct but was invisible. One
        transition-gated INFO line per flip (the #762 alternation pattern)
        and per-day tallies for diagnostics — "was export ever reconciled
        on this install?" becomes one look instead of a 19-comment thread.
        A healthy boot (first read complete) stays silent; a counter that
        is dead FROM boot logs, because that is exactly the invisible case.
        """
        if self._backing_tally_date != today_str:
            self._backing_tally_date = today_str
            self._backing_tally = {}
        tally = self._backing_tally.setdefault(
            category, {"backed": 0, "skipped": 0})
        tally["backed" if backed else "skipped"] += 1
        prev = self._backing_state.get(category)
        if prev is backed:
            return
        self._backing_state[category] = backed
        if not backed:
            log_on_change(
                _LOGGER, f"backing:{category}", logging.INFO,
                "%s: no longer counter-backed — a configured counter is "
                "unreadable; the daily row runs on power integration alone "
                "until it returns", category,
            )
        elif prev is False:
            log_on_change(
                _LOGGER, f"backing:{category}", logging.INFO,
                "%s: counter-backed again — reconciliation resumed", category,
            )

    def counter_backing_today(self) -> Dict[str, Dict[str, int]]:
        """(#628 visibility) Today's per-category backed/skipped cycle
        counts, for the diagnostics download."""
        return {k: dict(v) for k, v in self._backing_tally.items()}

    def _reconcile_metered_energy(
        self,
        category: str,
        today: date,
        month_key: str,
        year_key: str,
        cost_key: Optional[str] = None,
        rate: float = 0.0,
    ) -> None:
        """Daily grid/battery energy follows the hardware meters (#628).

        The user declares their P1/utility meter and BMS counters in HA's
        Energy Dashboard; the dashboard reads those counters, SEM integrates
        the matching POWER sensor every cycle. Any sample the power sensor
        misses or mis-signs never comes back — on a Huawei install 3.3 % of
        grid samples were isolated dropouts, and one negative sample books
        real import as export. The counters are the same numbers the user
        compares against, so SEM should read them too.

        Same baseline/anchor/delta model as ``_reconcile_solar_energy``, with
        three deliberate differences:

        - **BIDIRECTIONAL.** Solar and EV adopt upward only, because their
          counters can only ever reveal energy the integrator missed. A grid
          meter can prove the integrator counted energy that never flowed
          (#628: export integrated 3.06 kWh against a meter reading 0.16),
          so a downward correction has to be legal. Safe because every daily
          energy sensor is ``SensorStateClass.TOTAL`` — a decrease is a
          correction, not a statistics reset.
        - **ALL-OR-NOTHING per category.** Upward-only was the safety net that
          let a partial counter set be harmless; without it, a two-tariff
          import meter with one entity unavailable would look like the day
          shrank. So a category reconciles only when EVERY configured counter
          is reporting, otherwise the cycle is skipped and the integrator
          simply keeps running.
        - **NO SUN GATE.** ``_reconcile_solar_energy`` refuses the counter in
          darkness (#681) because an inverter's yield counter measures AC
          yield, which is not PV production. That is bug class 28 — a sensor
          trusted for the slot it is wired into rather than for what it
          measures. It does not apply here: a grid import register measures
          grid import, at every hour, by definition. The gate is a property of
          the solar counter, not of reconciliation.

        Cost accumulators move with the delta at the CURRENT rate — the same
        approximation solar savings already carry, and documented as such.
        """
        if not self._meter_counter_enabled or not self._hass:
            return
        entities = self._meter_counter_entities.get(category) or []
        if not entities:
            return

        today_str = str(today)
        bl = self._meter_baselines.get(category)
        if (
            not isinstance(bl, dict)
            or bl.get("date") != today_str
            or "base" not in bl
            or "last" not in bl
        ):
            bl = self._meter_baselines[category] = {
                "date": today_str, "base": {}, "last": {},
            }

        daily_key = f"{category}_{today}"
        integrated = self._daily_accumulators.get(daily_key, 0.0)

        readings: Dict[str, float] = {}
        for entity_id in entities:
            state = self._hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable", None):
                continue
            value = self._energy_state_kwh(state)  # #551 unit-aware
            if value >= 0:
                readings[entity_id] = value

        if len(readings) != len(entities):
            # Partial read — see ALL-OR-NOTHING above. Do NOT touch the
            # baselines: the missing counter kept counting while it was
            # unavailable, and its delta is still owed once it returns.
            self._tally_backing(category, today_str, backed=False)
            return

        # (#628) Complete read — this category's daily row is the hardware's
        # this cycle, so the home balance may build on it.
        self._counter_backed.add(category)
        self._tally_backing(category, today_str, backed=True)

        # A counter that went BACKWARDS since its last reading (meter reboot,
        # a daily-type register resetting at midnight) invalidates the whole
        # baseline set for this category: its past contribution is already
        # inside the adopted daily value, so deltas restart from here.
        reset = any(
            entity_id in bl["last"] and value < bl["last"][entity_id] - 0.001
            for entity_id, value in readings.items()
        )
        if reset:
            bl["base"] = {}
            bl.pop("anchor", None)
        for entity_id, value in readings.items():
            bl["base"].setdefault(entity_id, value)
            bl["last"][entity_id] = value
        bl.setdefault("anchor", integrated)

        counter_daily = sum(
            value - bl["base"][entity_id] for entity_id, value in readings.items()
        )
        target = max(0.0, bl["anchor"] + counter_daily)

        if target > MAX_PLAUSIBLE_DAILY_KWH:
            _LOGGER.warning(
                "%s counter reconciliation target %.1f kWh exceeds the %.0f "
                "kWh/day sanity ceiling — ignoring this cycle (unit mismatch?)",
                category, target, MAX_PLAUSIBLE_DAILY_KWH,
            )
            return

        delta = target - integrated
        if abs(delta) <= METER_RECONCILIATION_THRESHOLD:
            return  # Small drift stays with the integrator.

        # Corrections run every cycle once adopted, so only a material one is
        # worth an INFO line — the rest would be 10-second log spam.
        log = (
            _LOGGER.info
            if abs(delta) > RECONCILIATION_THRESHOLD
            else _LOGGER.debug
        )
        log(
            "%s energy reconciliation: counter=%.2f kWh vs integrated=%.2f kWh "
            "— adopting counter value (%+.2f kWh)",
            category, target, integrated, delta,
        )
        self._daily_accumulators[daily_key] = target
        for accumulators, key in (
            (self._monthly_accumulators, f"{category}_{month_key}"),
            (self._yearly_accumulators, f"{category}_{year_key}"),
            (self._lifetime_accumulators, f"lifetime_{category}"),
        ):
            # max(0.0) — the delta can now be negative, and a longer period
            # must never be dragged below zero by one day's correction.
            accumulators[key] = max(0.0, accumulators.get(key, 0.0) + delta)

        if cost_key and rate:
            cost_delta = delta * rate
            for accumulators, key in (
                (self._daily_cost_accumulators, f"{cost_key}_{today}"),
                (self._monthly_cost_accumulators, f"{cost_key}_{month_key}"),
                (self._yearly_cost_accumulators, f"{cost_key}_{year_key}"),
            ):
                accumulators[key] = max(0.0, accumulators.get(key, 0.0) + cost_delta)

    def _reconcile_home_energy(
        self, today: date, month_key: str, year_key: str
    ) -> None:
        """Daily home consumption follows the balance, not a stopwatch (#628).

        Home is the one row nothing meters. Every other row has hardware behind
        it; home is by definition what is left when the metered rows are
        subtracted from each other::

            home = solar + import − export + discharge − charge − EV

        SEM has always evaluated that identity INSTANTANEOUSLY — in watts, every
        cycle — and integrated the result. That is where the last #628 column
        goes wrong, and it is not a mistake in any single place: home is a
        SMALL difference of LARGE terms, so it inherits their relative error
        magnified by the ratio between them. Measured on the developer's own
        PROD hardware for 25–31 July 2026, where solar, grid and battery each
        agree with their meters to ≤0.5 %, daily home still landed −8 % to
        +15 % off the meter-derived figure, in both directions. Five registers
        updating asynchronously cannot be sampled into agreement with a day's
        reconciled totals; on 31 July a 1 % skew on 53.8 kWh of solar alone is
        ±0.5 kWh of a 34.8 kWh residual.

        So the daily row stops being sampled and starts being derived — from the
        rows this cycle has already reconciled. That is not a new idea in this
        file: lifetime home (``seed_lifetime_from_hardware``) and yearly home
        (``seed_yearly_from_statistics``) are ALREADY seeded from exactly this
        balance. Only the daily row was still a stopwatch, and only the daily
        row was wrong.

        The invariant this buys is worth stating plainly, because it is stronger
        than "home is more accurate": SEM's seven daily numbers now ADD UP. Home
        is the exact residual of the six rows SEM publishes beside it, each of
        which is independently pinned to the user's own counters. Today they do
        not add up, which is what every numbers-don't-match report is really
        reporting.

        The gate is #628's own rule applied to a residual: derive only when
        every term that is actually flowing is counter-backed THIS cycle;
        otherwise stand down and let the integrator keep the row, exactly as
        before. Standing down is continuous, not a jump — the integrator simply
        resumes from wherever the balance left the accumulator.

        Two terms get special handling:

        - A term with NO counter but no flow either (an install with no battery,
          a day with no export) is not an unverified number, it is the absence
          of a flow, and it may enter the balance as the zero it is. Above
          ``UNMETERED_TERM_EPSILON_KWH`` it is present-and-unmetered and the
          balance stands down.
        - EV stays on the integrator when the wallbox counters are not
          configured. It is the one term where that is defensible: charger power
          is a DIRECT measurement, not a residual, so its error enters home at
          1:1 rather than magnified. It is subtracted from
          ``MIDNIGHT_EV_CATEGORY`` — the calendar-day mirror — because
          ``EV_CATEGORY`` rolls at the charge deadline (#279) and composing a
          midnight row out of a deadline row is the bug class closed in
          #703/#704.
        """
        if not self._meter_counter_enabled or not self._hass:
            return

        # The EV mirror only knows the charging it has watched. On the first
        # cycle after an upgrade it is born mid-day while every other row
        # already holds the whole day, so subtracting it would credit the car's
        # morning charge to the house — a 20 kWh error on exactly the day
        # people look. One calendar day of the old behaviour is the cheapest
        # correct answer; from tomorrow the mirror spans the day.
        if self._midnight_ev_since is None:
            self._midnight_ev_since = today
        if today <= self._midnight_ev_since:
            return

        values: Dict[str, float] = {}
        balance = 0.0
        for category, sign in _HOME_BALANCE_TERMS:
            value = self._daily_accumulators.get(f"{category}_{today}", 0.0)
            values[category] = value
            if (
                category not in self._counter_backed
                and value > UNMETERED_TERM_EPSILON_KWH
            ):
                return  # Present and unmetered — see above.
            balance += sign * value

        values["ev"] = self._daily_accumulators.get(
            f"{MIDNIGHT_EV_CATEGORY}_{today}", 0.0
        )
        raw = balance - values["ev"]
        # The house always draws ≥ 0. The clamp stays (a negative residual is
        # not a negative consumption), but what it REMOVED is recorded: a
        # sustained engagement here means one of the six rows is signed wrong,
        # and that is a finding, not a number to hide (#660).
        target = self._record_clamp("daily_home_balance", raw, max(0.0, raw), 0.01)

        if target > MAX_PLAUSIBLE_DAILY_KWH:
            _LOGGER.warning(
                "Home balance target %.1f kWh exceeds the %.0f kWh/day sanity "
                "ceiling — ignoring this cycle (unit mismatch?)",
                target, MAX_PLAUSIBLE_DAILY_KWH,
            )
            return

        daily_key = f"home_{today}"
        integrated = self._daily_accumulators.get(daily_key, 0.0)
        delta = target - integrated
        if abs(delta) <= METER_RECONCILIATION_THRESHOLD:
            return  # Already there; small drift stays with the integrator.

        if not self._home_balance_logged:
            self._home_balance_logged = True
            _LOGGER.info(
                "Daily home consumption now follows the reconciled energy "
                "balance (#628): solar %.2f + import %.2f − export %.2f + "
                "discharge %.2f − charge %.2f − EV %.2f = %.2f kWh "
                "(was integrating %.2f kWh)",
                values["solar"], values["grid_import"], values["grid_export"],
                values["battery_discharge"], values["battery_charge"],
                values["ev"], target, integrated,
            )
        else:
            _LOGGER.debug(
                "Home balance: %.2f kWh vs integrated %.2f kWh (%+.2f)",
                target, integrated, delta,
            )

        self._daily_accumulators[daily_key] = target
        for accumulators, key in (
            (self._monthly_accumulators, f"home_{month_key}"),
            (self._yearly_accumulators, f"home_{year_key}"),
            (self._lifetime_accumulators, "lifetime_home"),
        ):
            # max(0.0) — the delta is bidirectional, and a longer period must
            # never be dragged below zero by one day's correction.
            accumulators[key] = max(0.0, accumulators.get(key, 0.0) + delta)

    def _max_daily_ev_kwh(self) -> float:
        """Physical ceiling for one day of fleet EV charging.

        ``n_chargers × max_current × phases × voltage × 24 h``. Generous by
        design — this is a unit-error trap (a Wh counter read as kWh is 1000×
        out), not a policy limit, and a charger that legitimately runs flat out
        all day must not trip it.
        """
        cfg = self.config
        chargers = cfg.get("ev_chargers") or []
        n = max(1, len(chargers))
        from ..consts.core import DEFAULT_MAX_CHARGING_CURRENT
        amps = float(
            cfg.get("ev_max_current", DEFAULT_MAX_CHARGING_CURRENT)
            or DEFAULT_MAX_CHARGING_CURRENT
        )
        phases = float(cfg.get("ev_phases", 3) or 3)
        volts = float(cfg.get("ev_voltage", 230) or 230)
        return n * amps * phases * volts * 24 / 1000

    def calculate_costs(self, energy: EnergyTotals) -> CostData:
        """Calculate costs and savings from energy totals.

        Uses incremental cost accumulators so dynamic tariff rate changes mid-day
        do not retroactively recalculate the entire day's cost at the new rate.
        """
        costs = CostData()

        now = dt_util.now()
        today = now.date()
        month_key = f"{today.year}_{today.month}"
        year_key = str(today.year)

        # Daily calculations — from incremental cost accumulators
        costs.daily_costs = self._get_daily_cost("cost_import", today)
        costs.daily_export_revenue = self._get_daily_cost("cost_export", today)
        costs.daily_net_cost = round(costs.daily_costs - costs.daily_export_revenue, 2)
        # (#660) These two floors are what made HealthCheck's "cost is
        # negative" check unfireable on them, and the check was duly removed.
        # They are deliberately NOT instrumented as clamp engagement, unlike
        # the rate clamps below: under a dynamic tariff with a genuinely
        # negative import price (Nord Pool / ENTSO-E intraday go below zero)
        # ``solar_self_consumed × import_rate`` is legitimately negative — the
        # grid would have paid you to consume, so self-consuming saved nothing.
        # The floor engaging there is correct behaviour, not a fault, and
        # recording it would raise a violation every negative-price hour on
        # exactly the installs that need trustworthy diagnostics most. An
        # instrument that fires on a legitimate condition is the noise this
        # issue set out to delete.
        costs.daily_savings = max(0, self._get_daily_cost("cost_savings", today))
        costs.daily_battery_savings = max(
            0, self._get_daily_cost("cost_batt_savings", today)
        )
        # (#770) What today's grid charging of the battery cost, published
        # beside the savings it has to be read against. NOT floored: a
        # negative import price makes a purchase legitimately negative, and
        # clamping it would hide money the user was paid to take.
        costs.daily_battery_grid_cost = round(
            self.get_battery_charge_split(today)["grid_cost_today"], 2
        )
        # #351 M2 — headline total spans both. Pre-fix users comparing
        # daily_savings to import costs saw battery_to_ev portion
        # missing.
        costs.daily_total_savings = round(
            costs.daily_savings + costs.daily_battery_savings, 2,
        )

        # Monthly calculations
        costs.monthly_costs = self._get_monthly_cost("cost_import", month_key)
        costs.monthly_export_revenue = self._get_monthly_cost("cost_export", month_key)
        costs.monthly_net_cost = round(costs.monthly_costs - costs.monthly_export_revenue, 2)
        costs.monthly_savings = max(0, self._get_monthly_cost("cost_savings", month_key))
        costs.monthly_battery_savings = max(0, self._get_monthly_cost("cost_batt_savings", month_key))
        costs.monthly_total_savings = round(
            costs.monthly_savings + costs.monthly_battery_savings, 2,
        )

        # Yearly calculations
        costs.yearly_costs = self._get_yearly_cost("cost_import", year_key)
        costs.yearly_export_revenue = self._get_yearly_cost("cost_export", year_key)
        costs.yearly_net_cost = round(costs.yearly_costs - costs.yearly_export_revenue, 2)
        costs.yearly_savings = max(0, self._get_yearly_cost("cost_savings", year_key))
        costs.yearly_battery_savings = max(0, self._get_yearly_cost("cost_batt_savings", year_key))
        costs.yearly_total_savings = round(
            costs.yearly_savings + costs.yearly_battery_savings, 2,
        )

        # Environmental impact (CO2 avoided by self-consuming solar)
        daily_self_consumed = max(0, energy.daily_solar - energy.daily_grid_export)
        yearly_self_consumed = max(0, energy.yearly_solar - energy.yearly_grid_export)
        lifetime_solar = self._get_lifetime("solar")
        lifetime_export = self._get_lifetime("grid_export")
        lifetime_self_consumed = max(0, lifetime_solar - lifetime_export)

        costs.daily_co2_avoided_kg = round(daily_self_consumed * GRID_CO2_KG_PER_KWH, 2)
        costs.yearly_co2_avoided_kg = round(yearly_self_consumed * GRID_CO2_KG_PER_KWH, 1)
        costs.yearly_trees_equivalent = round(
            costs.yearly_co2_avoided_kg / CO2_KG_PER_TREE_PER_YEAR, 1
        )
        costs.lifetime_co2_avoided_kg = round(lifetime_self_consumed * GRID_CO2_KG_PER_KWH, 1)
        costs.lifetime_trees_equivalent = round(
            costs.lifetime_co2_avoided_kg / CO2_KG_PER_TREE_PER_YEAR, 1
        )

        # ROI calculation — hybrid: accumulated (accurate) + estimated past (avg rate)
        lifetime_grid_import = self._get_lifetime("grid_import")
        lifetime_grid_export = self._get_lifetime("grid_export")

        # Use 7-day avg rate for the estimated (pre-accumulation) portion
        avg_import = self._get_avg_import_rate()
        avg_export = self._get_avg_export_rate()

        # Pre-SEM portion: lifetime minus what we've already accurately accumulated.
        # Battery discharge is deliberately NOT estimated here (#499): the
        # solar-charged share of pre-SEM discharge is already inside
        # ``lifetime_self_consumed`` (solar − export includes solar that was
        # routed through the battery), and the grid-charged share's net
        # arbitrage benefit can't be reconstructed from lifetime counters.
        pre_sem_self_consumed = max(0, lifetime_self_consumed - self._accumulated_self_consumed_kwh)
        pre_sem_export = max(0, lifetime_grid_export - self._accumulated_export_kwh)
        pre_sem_grid_import = max(0, lifetime_grid_import - self._accumulated_grid_import_kwh)

        # Estimated past savings (using smoothed avg rate)
        estimated_past_savings = pre_sem_self_consumed * avg_import
        estimated_past_revenue = pre_sem_export * avg_export

        # Total: accumulated real savings + estimated past. Battery savings
        # are included from the accumulated (flow-attributed) side only —
        # ``cost_savings`` counts direct solar→home/EV, so battery discharge
        # savings are additional, not a double count (#499).
        costs.lifetime_grid_cost = round(
            self._accumulated_cost + pre_sem_grid_import * avg_import, 2
        )
        costs.lifetime_total_savings = round(
            self._accumulated_savings + self._accumulated_battery_savings
            + self._accumulated_export_revenue
            + estimated_past_savings + estimated_past_revenue, 2
        )

        system_cost = self.config.get("system_investment_cost", 0)
        if system_cost > 0:
            costs.roi_percentage = round(
                (costs.lifetime_total_savings / system_cost) * 100, 1
            )
            # Calculate annual savings from lifetime data + system age
            # Auto-detected from recorder statistics (first solar energy entry)
            install_year_decimal = self._install_year_decimal or dt_util.now().year
            now_decimal = dt_util.now().year + (dt_util.now().month / 12)
            age_years = max(0.5, now_decimal - install_year_decimal)
            if costs.lifetime_total_savings > 100:
                costs.roi_annual_savings = round(costs.lifetime_total_savings / age_years, 0)
                remaining = system_cost - costs.lifetime_total_savings
                if remaining > 0 and costs.roi_annual_savings > 0:
                    costs.roi_payback_years = round(age_years + (remaining / costs.roi_annual_savings), 1)
                elif remaining <= 0:
                    costs.roi_payback_years = round(age_years, 1)  # Already paid off

        return costs

    def calculate_performance(
        self, power: PowerReadings, energy: EnergyTotals,
        energy_flows: "Optional[EnergyFlows]" = None,
    ) -> PerformanceMetrics:
        """Calculate performance metrics.

        ``energy_flows`` (v1.7.0+ — optional for back-compat with the
        legacy two-arg call shape) provides flow-attributed daily
        kWh totals. When supplied, the autarky calculation uses
        ``grid_to_home + grid_to_ev`` instead of the raw
        ``daily_grid_import``. The legacy formula treated every kWh
        imported from the grid as a penalty against autarky — but a
        kWh that flowed grid → battery (e.g. overnight cheap-tariff
        charging) doesn't reduce the home's own-supply share. Live
        evidence captured on HA-PROD 2026-06-01: 9.38 kWh grid_import
        with 2.9 kWh going to the battery left autarky pinned at 0 %
        while self_consumption was 98.1 % — clearly the formula was
        mis-attributing the grid → battery slice.
        """
        metrics = PerformanceMetrics()

        # (#660) Both rate clamps live inside conditional branches (no solar
        # yet today, no consumption yet today). If a branch is skipped the
        # record from an earlier cycle would linger and keep incrementing its
        # streak into a violation that nothing is currently producing. Clear
        # first, so a key present after this call means "engaged THIS cycle".
        self.clamp_engagement.pop("self_consumption_rate", None)
        self.clamp_engagement.pop("autarky_rate", None)

        # (#770) How much of what is stored right now was bought. Published
        # beside autarky because it is the correction autarky applies below.
        # None (→ sensor unknown) until the pool has attributed content —
        # a share the pool never measured must not read as "0 % bought".
        _share = self._battery_provenance.fleet_grid_share_measured()
        metrics.battery_stored_grid_share = (
            None if _share is None else round(_share * 100, 1)
        )

        # Self consumption rate = (solar - export) / solar — direction-of-
        # flow-agnostic; whatever solar didn't go to the grid was
        # consumed locally (by home, battery, or EV). No flow attribution
        # needed.
        if energy.daily_solar > 0:
            solar_used = energy.daily_solar - energy.daily_grid_export
            metrics.self_consumption_rate = round(
                (solar_used / energy.daily_solar) * 100, 1
            )
            # (#660) record what the range clamp removed before applying it.
            metrics.self_consumption_rate = self._record_clamp(
                "self_consumption_rate",
                metrics.self_consumption_rate,
                max(0, min(100, metrics.self_consumption_rate)),
                eps=0.1,
            )

        # Autarky rate — share of consumption supplied from "own"
        # sources (solar + battery) vs grid.
        #
        # When ``energy_flows`` is provided we use ONLY flow-attributed
        # values — all calendar-midnight aligned, so no temporal-
        # mismatch bug. Earlier fix used ``daily_home + daily_ev`` for
        # the denominator but ``daily_ev`` resets at SUNRISE (per #279
        # EV-target arc) while ``flow_grid_to_ev`` resets at calendar
        # midnight; pre-sunrise EV charging then appeared in the grid
        # penalty but not in the consumption total, pinning autarky
        # at single digits. HA-PROD 2026-06-01 saw exactly this:
        # ``flow_grid_to_ev = 6.2 kWh`` (pre-sunrise) while
        # ``daily_ev = 0`` (sunrise window started later) → autarky
        # 9 % instead of a realistic ~42 %.
        #
        # New definition (all from ``energy_flows``, calendar-aligned):
        # * own_supply  = solar_to_home + solar_to_ev
        #               + battery_to_home + battery_to_ev
        # * grid_supply = grid_to_home + grid_to_ev
        # * total      = own_supply + grid_supply
        # * autarky    = own_supply / total × 100
        #
        # (#770) That approximation is now retired. SEM DOES track battery
        # provenance, and the grid-charged share of the discharge is grid
        # supply that was merely time-shifted — the house did not make it.
        # ``_battery_grid_origin_share`` is 0.0 until the store knows
        # better, so an install with no grid charging reads exactly as
        # before.
        #
        # Legacy two-arg callers (no energy_flows) keep the v1.6.x
        # behaviour. They share the bug class, but their existing
        # tests pin the old numbers so we don't quietly retcon them.
        if energy_flows is not None:
            battery_supply = (
                getattr(energy_flows, "battery_to_home", 0.0)
                + getattr(energy_flows, "battery_to_ev", 0.0)
            )
            battery_from_grid = battery_supply * self._battery_grid_origin_share
            own_supply = (
                getattr(energy_flows, "solar_to_home", 0.0)
                + getattr(energy_flows, "solar_to_ev", 0.0)
                + (battery_supply - battery_from_grid)
            )
            grid_supply = (
                getattr(energy_flows, "grid_to_home", 0.0)
                + getattr(energy_flows, "grid_to_ev", 0.0)
                + battery_from_grid
            )
            total_consumption = own_supply + grid_supply
            if total_consumption > 0:
                metrics.autarky_rate = round(
                    (own_supply / total_consumption) * 100, 1,
                )
                # (#660) see ``_record_clamp`` — the removed amount is the
                # signal, the clamped value never is.
                metrics.autarky_rate = self._record_clamp(
                    "autarky_rate",
                    metrics.autarky_rate,
                    max(0, min(100, metrics.autarky_rate)),
                    eps=0.1,
                )
        else:
            # Legacy path — kept for v1.6.x compatibility and the
            # two-arg call shape used in pre-v1.7.0 test fixtures.
            total_consumption = energy.daily_home + energy.daily_ev
            if total_consumption > 0:
                own_supply = total_consumption - energy.daily_grid_import
                metrics.autarky_rate = round(
                    (own_supply / total_consumption) * 100, 1,
                )
                # (#660) see ``_record_clamp`` — the removed amount is the
                # signal, the clamped value never is.
                metrics.autarky_rate = self._record_clamp(
                    "autarky_rate",
                    metrics.autarky_rate,
                    max(0, min(100, metrics.autarky_rate)),
                    eps=0.1,
                )

        # (#669) The two "simple efficiency estimates" assigned here were
        # constants, not estimates, and no reader ever existed. Removed with
        # their fields rather than left computing for nobody.
        return metrics

    def _accumulate(
        self, category: str, today: date, month_key: str, year_key: str, increment: float
    ) -> None:
        """Accumulate energy increment for a category."""
        daily_key = f"{category}_{today}"
        monthly_key = f"{category}_{month_key}"
        yearly_key = f"{category}_{year_key}"

        if daily_key not in self._daily_accumulators:
            self._daily_accumulators[daily_key] = 0.0
        if monthly_key not in self._monthly_accumulators:
            self._monthly_accumulators[monthly_key] = 0.0
        if yearly_key not in self._yearly_accumulators:
            self._yearly_accumulators[yearly_key] = 0.0

        self._daily_accumulators[daily_key] += increment
        self._monthly_accumulators[monthly_key] += increment
        self._yearly_accumulators[yearly_key] += increment

        # Lifetime (never resets)
        lifetime_key = f"lifetime_{category}"
        if lifetime_key not in self._lifetime_accumulators:
            self._lifetime_accumulators[lifetime_key] = 0.0
        self._lifetime_accumulators[lifetime_key] += increment

    def _get_daily(self, category: str, today: date) -> float:
        """Get daily accumulated energy."""
        key = f"{category}_{today}"
        return round(self._daily_accumulators.get(key, 0.0), 2)

    def _get_monthly(self, category: str, month_key: str) -> float:
        """Get monthly accumulated energy."""
        key = f"{category}_{month_key}"
        return round(self._monthly_accumulators.get(key, 0.0), 2)

    def _get_yearly(self, category: str, year_key: str) -> float:
        """Get yearly accumulated energy."""
        key = f"{category}_{year_key}"
        return round(self._yearly_accumulators.get(key, 0.0), 2)

    def _get_lifetime(self, category: str) -> float:
        """Get lifetime accumulated energy."""
        key = f"lifetime_{category}"
        return round(self._lifetime_accumulators.get(key, 0.0), 2)

    # ── (#769) the per-device ledger ────────────────────────────────────
    #
    # SEM commands loads and then forgets what they cost. The heat pump is
    # the worst case — on the houses SEM was installed for it is the single
    # largest controllable load, and it was accounted for like an unmonitored
    # kettle: absorbed into the ``home`` residual, which is computed as a
    # leftover and therefore can never complain (#767).
    #
    # #768 gave each device its daily kWh with provenance. This is the other
    # three horizons plus the attribution, riding the SAME accumulators the
    # fleet categories use so persistence, rollover and pruning are the ones
    # already proven rather than a second set that can drift from them.

    @staticmethod
    def _device_category(device_id: str, split: Optional[str] = None) -> str:
        base = f"{DEVICE_KEY_PREFIX}{device_id}"
        return f"{base}{_SPLIT_SEP}{split}" if split else base

    @staticmethod
    def _month_key(day: date) -> str:
        """The calculator's OWN month key — ``2026_8``, not ISO ``2026-08``.

        This is not cosmetic. ``_check_rollover``'s monthly sweep runs on
        every cycle, not only when the month changes, and deletes any key
        that does not end in the caller's month key. A device row written in
        a different format is therefore deleted seconds after it is written
        and the monthly total silently degrades to "whatever the last cycle
        booked". One helper, one format, both sides.
        """
        return f"{day.year}_{day.month}"

    def accumulate_device_energy(
        self,
        device_id: str,
        increment_kwh: float,
        meter_day: date,
        split: Optional[str] = None,
    ) -> None:
        """Book one cycle's device energy into every period.

        ``meter_day`` is the DEVICE's day — the sunrise-based meter day the
        device itself rolls on (#620/#704) — and the month and year keys are
        derived from it. One day definition feeds all four horizons, so the
        totals can't disagree with each other for the six hours between
        midnight and sunrise.

        ``split`` names an attribution bucket (the heat pump's SG-Ready
        state). The bucket is accumulated BESIDE the device total, never
        instead of it: an unsplit device is still fully counted, and the
        buckets of a split device sum to its total.
        """
        if not device_id or not increment_kwh:
            return
        month_key = self._month_key(meter_day)
        year_key = str(meter_day.year)
        self._accumulate(
            self._device_category(device_id), meter_day,
            month_key, year_key, float(increment_kwh),
        )
        if split:
            self._accumulate(
                self._device_category(device_id, split), meter_day,
                month_key, year_key, float(increment_kwh),
            )

    def get_device_energy(self, device_id: str, meter_day: date) -> Dict[str, float]:
        """The device's ledger row: daily / monthly / yearly / lifetime kWh."""
        category = self._device_category(device_id)
        return {
            "daily_kwh": self._get_daily(category, meter_day),
            "monthly_kwh": self._get_monthly(category, self._month_key(meter_day)),
            "yearly_kwh": self._get_yearly(category, str(meter_day.year)),
            "lifetime_kwh": self._get_lifetime(category),
        }

    def get_device_splits(self, device_id: str, meter_day: date) -> Dict[str, float]:
        """Today's kWh per attribution bucket, e.g. ``{"sg2": .., "sg3": ..}``.

        Empty for a device that names no buckets — which is most of them.
        """
        prefix = f"{self._device_category(device_id)}{_SPLIT_SEP}"
        suffix = f"_{meter_day}"
        out: Dict[str, float] = {}
        for key, value in self._daily_accumulators.items():
            if key.startswith(prefix) and key.endswith(suffix):
                out[key[len(prefix):-len(suffix)]] = round(value, 2)
        return out

    def get_device_shifted(
        self, device_id: str, meter_day: date, lifetime: bool = False
    ) -> float:
        """kWh this device consumed BECAUSE SEM asked (SG-Ready boost/force).

        The number the whole issue is about: without it, "SEM ran the heat
        pump on solar" is a claim with no measurement behind it.
        """
        if lifetime:
            return round(sum(
                self._get_lifetime(self._device_category(device_id, s))
                for s in SHIFTED_SPLITS
            ), 2)
        daily = self.get_device_splits(device_id, meter_day)
        return round(sum(daily.get(s, 0.0) for s in SHIFTED_SPLITS), 2)

    def get_comfort_split(
        self, device_id: str, meter_day: date
    ) -> Dict[str, float]:
        """(#772) A zone's comfort energy by plan placement, today + month.

        The two numbers whose ratio answers "is banking working here".
        Today is the live view; the MONTH is where a week's worth
        actually survives — the rollover sweep keeps only today's and
        yesterday's daily keys, so any window longer than that must be
        read from the monthly bucket (pinned in test_772).
        """
        month_key = self._month_key(meter_day)
        out: Dict[str, float] = {}
        for split, name in (
            (COMFORT_SPLIT_IN, "in_block"),
            (COMFORT_SPLIT_OUT, "out_block"),
        ):
            category = self._device_category(device_id, split)
            out[f"{name}_today_kwh"] = self._get_daily(category, meter_day)
            out[f"{name}_month_kwh"] = self._get_monthly(category, month_key)
        return out

    # ── (#773) the residual: home minus everything SEM can see ──────────

    def accumulate_controlled_load(
        self, increment_kwh: float, calendar_day: date, *, estimated: bool
    ) -> None:
        """Book one cycle's device kWh into the MIDNIGHT-keyed mirror.

        Called at the filing seam beside ``accumulate_device_energy`` — the
        same increment, booked a second time under the calendar day, because
        the baseload subtraction runs against the midnight-keyed home row
        and the device's own ledger day rolls at sunrise (see the category
        comment). Daily-only: the residual is a daily diagnostic, not a
        billing figure.

        ``estimated`` marks a rated×runtime booking. The kWh still enters
        the mirror (the subtraction stays displayable); the estimated slice
        is tracked BESIDE it, and any estimated kWh in the day makes the
        day's baseload unmeasured (#755 contract 1).
        """
        if not increment_kwh:
            return
        daily_key = f"{CONTROLLED_LOADS_CATEGORY}_{calendar_day}"
        self._daily_accumulators[daily_key] = (
            self._daily_accumulators.get(daily_key, 0.0) + float(increment_kwh)
        )
        if estimated:
            est_key = f"{CONTROLLED_LOADS_EST_CATEGORY}_{calendar_day}"
            self._daily_accumulators[est_key] = (
                self._daily_accumulators.get(est_key, 0.0)
                + float(increment_kwh)
            )

    @property
    def baseload_history(self) -> list:
        """(#773) Sealed baseload days, oldest first, for the drift check."""
        return list(self._baseload_history)

    def get_true_baseload(self, today: date) -> Dict[str, Any]:
        """(#773) Today's residual so far: home minus the controlled mirror.

        ``today_kwh`` is None — not zero — while no home row exists: before
        the balance (or the integrator) has written one there is nothing to
        subtract from, and ``0 − controlled`` would publish the house as a
        negative-consumption fault (#755 contract 1: silence is not a
        measurement of zero).

        A NEGATIVE value is published as-is. The home row is clamped ≥ 0 for
        good physical reasons; the baseload is a DIAGNOSTIC, and negative is
        its most unambiguous finding — an over-subtraction or a sign error —
        which a ``max(0, ...)`` would hide (the issue's explicit ask).

        ``measured`` is the training gate: True only when no estimated kWh
        entered today's mirror. An estimated day still displays.
        """
        home_key = f"home_{today}"
        controlled = self._daily_accumulators.get(
            f"{CONTROLLED_LOADS_CATEGORY}_{today}", 0.0)
        estimated = self._daily_accumulators.get(
            f"{CONTROLLED_LOADS_EST_CATEGORY}_{today}", 0.0)
        home = self._daily_accumulators.get(home_key)
        return {
            "today_kwh": None if home is None else round(home - controlled, 3),
            "home_today_kwh": home,
            "controlled_today_kwh": round(controlled, 3),
            "estimated_today_kwh": round(estimated, 3),
            "measured": home is not None and estimated == 0.0,
        }

    def _seal_baseload_day(self, day: date) -> None:
        """(#773) Write one finished day into the baseload history.

        Runs from the rollover, BEFORE the daily sweep deletes the rows it
        reads. A day without a home row is a GAP: it is skipped entirely
        rather than sealed as zero — a zero here would poison every median
        the drift check takes for the next two weeks. Idempotent per day
        (a retried rollover must not duplicate the row).

        The per-device day totals ride along so a later breach can name its
        suspect: the term whose own day-over-day move explains the step.
        They are the device-ledger (sunrise-keyed) rows for ``day`` — offset
        from the midnight mirror by the small hours, which is fine for
        naming a mover and would be wrong for arithmetic; the arithmetic
        uses the mirror.
        """
        day_str = str(day)
        if any(r.get("date") == day_str for r in self._baseload_history):
            return
        home = self._daily_accumulators.get(f"home_{day}")
        if home is None:
            return
        controlled = self._daily_accumulators.get(
            f"{CONTROLLED_LOADS_CATEGORY}_{day}", 0.0)
        estimated = self._daily_accumulators.get(
            f"{CONTROLLED_LOADS_EST_CATEGORY}_{day}", 0.0)
        prefix = DEVICE_KEY_PREFIX
        suffix = f"_{day}"
        devices = {
            k[len(prefix):-len(suffix)]: round(v, 3)
            for k, v in self._daily_accumulators.items()
            if k.startswith(prefix) and k.endswith(suffix)
            and _SPLIT_SEP not in k
        }
        self._baseload_history.append({
            "date": day_str,
            "baseload_kwh": round(home - controlled, 3),
            "home_kwh": round(home, 3),
            "controlled_kwh": round(controlled, 3),
            "measured": estimated == 0.0,
            # The SIZE of the estimated portion, not just its presence: the
            # estimate's error is bounded by the estimate itself, so the
            # drift check can accept a day whose estimate is too small to
            # move a verdict. Gating on the boolean alone made one meterless
            # pool pump silence the check forever (.175's first sealed day
            # — and most houses').
            "estimated_kwh": round(estimated, 3),
            "devices": devices,
        })

    # ── (#770) battery charge, by where the energy came from ───────────
    #
    # ``battery_charge`` was one number for two different things: a kWh off
    # the roof and a kWh bought in the cheap valley. Discharging both against
    # the full import price and calling the difference savings was near
    # enough while grid charging was rare — the joint planner made it the
    # norm. Same accumulators as every other category, so persistence,
    # rollover and pruning are the proven ones.

    def accumulate_battery_charge_split(
        self,
        solar_kwh: float,
        grid_kwh: float,
        today: date,
        import_rate: Optional[float] = None,
    ) -> None:
        """File one cycle's battery charge under its origin.

        The two buckets are accumulated BESIDE ``battery_charge``, never
        instead of it, so the split always sums to the total the rest of the
        ledger already agrees on.
        """
        month_key = self._month_key(today)
        year_key = str(today.year)
        solar_kwh = max(0.0, float(solar_kwh or 0.0))
        grid_kwh = max(0.0, float(grid_kwh or 0.0))
        if solar_kwh:
            self._accumulate(
                "battery_charge_solar", today, month_key, year_key, solar_kwh,
            )
        if grid_kwh:
            self._accumulate(
                "battery_charge_grid", today, month_key, year_key, grid_kwh,
            )
            rate = self._import_rate if import_rate is None else float(import_rate)
            self._accumulate_cost(
                "cost_batt_charge_grid", today, month_key, year_key,
                grid_kwh * max(0.0, rate),
            )

    def get_battery_charge_split(self, today: date) -> Dict[str, float]:
        """Today's battery charge by origin, plus the grid part's horizons."""
        month_key = self._month_key(today)
        year_key = str(today.year)
        return {
            "solar_today_kwh": self._get_daily("battery_charge_solar", today),
            "solar_month_kwh": self._get_monthly("battery_charge_solar", month_key),
            "solar_year_kwh": self._get_yearly("battery_charge_solar", year_key),
            "solar_total_kwh": self._get_lifetime("battery_charge_solar"),
            "grid_today_kwh": self._get_daily("battery_charge_grid", today),
            "grid_month_kwh": self._get_monthly("battery_charge_grid", month_key),
            "grid_year_kwh": self._get_yearly("battery_charge_grid", year_key),
            "grid_total_kwh": self._get_lifetime("battery_charge_grid"),
            "grid_cost_today": round(
                self._daily_cost_accumulators.get(
                    f"cost_batt_charge_grid_{today}", 0.0
                ), 4,
            ),
        }

    def _file_battery_charge_origin(
        self,
        power: PowerReadings,
        power_flows: "Optional[PowerFlows]",
        charge_increment: float,
        today: date,
    ) -> None:
        """Split this cycle's charge into solar and grid, and store both.

        The flow layer attributes in WATTS for the whole house; the ledger
        needs kWh for this cycle. Scaling the flow split onto the integrated
        increment keeps the two in step even when the flow attribution and
        the battery power sensor disagree slightly — the split can never sum
        to more than the charge the ledger already booked.

        Where the electrons physically went is unknowable, so the per-battery
        allocation follows how hard each unit was charging (#523 installs);
        one battery, or none with a power sensor, collapses to a fleet pool.
        """
        if power_flows is None or charge_increment <= 0:
            return
        solar_w = max(0.0, float(getattr(power_flows, "solar_to_battery", 0.0) or 0.0))
        grid_w = max(0.0, float(getattr(power_flows, "grid_to_battery", 0.0) or 0.0))
        attributed_w = solar_w + grid_w
        if attributed_w <= 0:
            return

        solar_kwh = charge_increment * (solar_w / attributed_w)
        grid_kwh = charge_increment - solar_kwh

        self.accumulate_battery_charge_split(solar_kwh, grid_kwh, today)

        charging = {
            bid: bp.power_w
            for bid, bp in (getattr(power, "batteries", None) or {}).items()
            if float(getattr(bp, "power_w", 0.0) or 0.0) > 0
        }
        for bid, (b_solar, b_grid) in allocate_fleet_charge(
            charging, solar_kwh, grid_kwh,
        ).items():
            self._battery_provenance.charge(
                bid, b_solar, b_grid, self._import_rate,
            )

    def _battery_discharge_savings(
        self, power: PowerReadings, discharge_increment: float,
        power_flows: "Optional[PowerFlows]" = None,
    ) -> float:
        """What this discharge saved, given where the stored energy came from.

        The pool was already pinned to the measured SOC earlier in the cycle,
        so what it holds here is what the battery holds. Energy SEM never saw
        arrive is ``unknown`` and keeps the legacy full-rate credit — the
        number does not move until SEM actually knows better.

        (#776) Savings are AVOIDED IMPORT, so only the home-delivered share
        of the discharge earns them. The exported share (force_discharge,
        the C6 arbitrage sell) already earns its export revenue at the grid
        meter — crediting it here too paid the same kWh twice. The pool
        draw stays the FULL increment (the energy really left the battery);
        only the money is scaled. No flow attribution — or a cycle where
        none of the discharge was attributed — keeps the legacy full
        credit: silence is not a measurement of "all exported" any more
        than of "all delivered".
        """
        mix = self._battery_provenance.discharge_fleet(discharge_increment)
        savings = discharge_savings(mix, self._import_rate)
        if power_flows is None:
            return savings
        delivered = (
            max(0.0, float(getattr(power_flows, "battery_to_home", 0.0) or 0.0))
            + max(0.0, float(getattr(power_flows, "battery_to_ev", 0.0) or 0.0))
        )
        exported = max(
            0.0, float(getattr(power_flows, "battery_to_grid", 0.0) or 0.0)
        )
        attributed = delivered + exported
        if attributed <= 0:
            return savings
        return savings * (delivered / attributed)

    def _reconcile_provenance_to_soc(self, power: PowerReadings) -> None:
        """Pin the provenance pool to SOC × capacity, when SOC is real."""
        if getattr(power, "battery_soc_unavailable", False):
            return
        capacity = float(self.config.get("battery_capacity_kwh", 0) or 0)
        if capacity <= 0:
            return
        try:
            soc = float(power.fleet_battery_soc)
        except (TypeError, ValueError, AttributeError):
            return
        self._battery_provenance.reconcile_fleet_to_stored(
            capacity * max(0.0, min(100.0, soc)) / 100.0
        )

    def set_battery_grid_origin_share(self, share: float) -> None:
        """Tell autarky how much of the stored energy was bought.

        Comes from :class:`BatteryProvenance` — a measurement of the pool,
        not a guess. Out-of-range values are clamped rather than rejected:
        the caller is SEM, and a broken share must degrade to the legacy
        answer, not crash the metrics.
        """
        try:
            self._battery_grid_origin_share = max(0.0, min(1.0, float(share)))
        except (TypeError, ValueError):
            self._battery_grid_origin_share = 0.0

    def _accumulate_cost(
        self, category: str, today: date, month_key: str, year_key: str, increment: float
    ) -> None:
        """Accumulate a cost increment for a category (no lifetime — ROI uses separate accumulators)."""
        daily_key = f"{category}_{today}"
        monthly_key = f"{category}_{month_key}"
        yearly_key = f"{category}_{year_key}"
        if daily_key not in self._daily_cost_accumulators:
            self._daily_cost_accumulators[daily_key] = 0.0
        if monthly_key not in self._monthly_cost_accumulators:
            self._monthly_cost_accumulators[monthly_key] = 0.0
        if yearly_key not in self._yearly_cost_accumulators:
            self._yearly_cost_accumulators[yearly_key] = 0.0
        self._daily_cost_accumulators[daily_key] += increment
        self._monthly_cost_accumulators[monthly_key] += increment
        self._yearly_cost_accumulators[yearly_key] += increment

    def _get_daily_cost(self, category: str, today: date) -> float:
        """Get daily accumulated cost."""
        return round(self._daily_cost_accumulators.get(f"{category}_{today}", 0.0), 2)

    def _get_monthly_cost(self, category: str, month_key: str) -> float:
        """Get monthly accumulated cost."""
        return round(self._monthly_cost_accumulators.get(f"{category}_{month_key}", 0.0), 2)

    def _get_yearly_cost(self, category: str, year_key: str) -> float:
        """Get yearly accumulated cost."""
        return round(self._yearly_cost_accumulators.get(f"{category}_{year_key}", 0.0), 2)

    def _get_avg_import_rate(self) -> float:
        """7-day average import rate, falling back to current rate."""
        if not self._rate_history:
            return self._import_rate
        recent = list(self._rate_history)[-7:]
        total = sum(r["import_rate"] for r in recent)
        return total / len(recent)

    def _get_avg_export_rate(self) -> float:
        """7-day average export rate, falling back to current rate."""
        if not self._rate_history:
            return self._export_rate
        recent = list(self._rate_history)[-7:]
        total = sum(r["export_rate"] for r in recent)
        return total / len(recent)

    def _snapshot_daily_costs(self, today: date) -> None:
        """Snapshot today's costs into accumulated totals before daily reset.

        Called from _check_rollover when the day changes.
        """
        # Read today's energy values before they get cleaned up
        today_str = str(today)
        daily_grid_import = self._daily_accumulators.get(f"grid_import_{today_str}", 0.0)
        daily_grid_export = self._daily_accumulators.get(f"grid_export_{today_str}", 0.0)
        daily_solar = self._daily_accumulators.get(f"solar_{today_str}", 0.0)
        daily_self_consumed = max(0, daily_solar - daily_grid_export)

        # Use incremental cost accumulators (rate-weighted, accurate for dynamic tariffs)
        daily_cost = self._daily_cost_accumulators.get(f"cost_import_{today_str}", 0.0)
        daily_export_revenue = self._daily_cost_accumulators.get(f"cost_export_{today_str}", 0.0)
        daily_savings = self._daily_cost_accumulators.get(f"cost_savings_{today_str}", 0.0)
        daily_battery_savings = self._daily_cost_accumulators.get(f"cost_batt_savings_{today_str}", 0.0)

        # Accumulate into running totals
        self._accumulated_savings += daily_savings
        self._accumulated_battery_savings += daily_battery_savings
        self._accumulated_cost += daily_cost
        self._accumulated_export_revenue += daily_export_revenue
        self._accumulated_grid_import_kwh += daily_grid_import
        self._accumulated_self_consumed_kwh += daily_self_consumed
        self._accumulated_export_kwh += daily_grid_export

        # Store today's rate for averaging; also record whether snapshot had meaningful data
        # (used by _check_rollover to detect trivial snapshots that should be retried).
        #
        # #499: use the day's VOLUME-WEIGHTED average (cost ÷ kWh) instead of
        # the rate in effect at midnight. For spot tariffs midnight is
        # systematically among the cheapest hours, which biased the 7-day
        # average — and with it the pre-SEM ROI estimate — low. Falls back to
        # the current rate on days without (positive) cost data.
        if daily_grid_import > 0.05 and daily_cost > 0:
            day_import_rate = daily_cost / daily_grid_import
        else:
            day_import_rate = self._import_rate
        if daily_grid_export > 0.05 and daily_export_revenue > 0:
            day_export_rate = daily_export_revenue / daily_grid_export
        else:
            day_export_rate = self._export_rate
        self._rate_history.append({
            "date": today_str,
            "import_rate": round(day_import_rate, 4),
            "export_rate": round(day_export_rate, 4),
            "energy_kwh": round(daily_solar + daily_grid_import, 4),
        })

    def _check_rollover(self, today: date, month_key: str, year_key: str = None) -> None:
        """Check for day/month rollover and cleanup old accumulators.

        EV keys (``ev_*``) are excluded — they use the sunrise/deadline-based
        day and get cleaned up separately (older than yesterday). No other
        accumulator category starts with "ev", so the prefix is unambiguous;
        the categories are solar, home, ev, grid_import, grid_export,
        battery_charge, battery_discharge.

        (#769) Per-device keys (``device:*``) get the same exemption, for the
        same reason and one more: a device's day rolls at SUNRISE, so between
        midnight and dawn its keys are stamped with YESTERDAY and a strict
        calendar sweep would delete the numbers as fast as they are written.
        The monthly and yearly device keys keep the previous period too — the
        trailing boundary is a month-end and a year-end problem as much as a
        nightly one, and losing New Year's small hours out of the yearly total
        is exactly the kind of quiet erosion this arc exists to stop.
        """
        yesterday = today - timedelta(days=1)
        yesterday_str = str(yesterday)
        prev_month_key = self._month_key(today.replace(day=1) - timedelta(days=1))
        prev_year_key = str(today.year - 1)

        def _sunrise_keyed(key: str) -> bool:
            return key.startswith(_EV_KEY_PREFIX) or key.startswith(DEVICE_KEY_PREFIX)

        # Snapshot yesterday's costs before cleaning up (for accumulated ROI)
        has_yesterday_data = any(
            k.endswith(yesterday_str) and not _sunrise_keyed(k)
            for k in self._daily_accumulators
        )
        # A prior snapshot is only considered valid if it captured non-zero energy.
        # If the system restarted around midnight and snapshotted before real data
        # accumulated, allow a re-snapshot when meaningful data is now present. (#225)
        prior_snapshot = next(
            (r for r in self._rate_history if r.get("date") == yesterday_str), None
        )
        already_snapshotted = prior_snapshot is not None and prior_snapshot.get("energy_kwh", 1.0) > 0
        if has_yesterday_data and not already_snapshotted:
            self._snapshot_daily_costs(yesterday)

        # (#773) Seal yesterday's baseload BEFORE the sweep deletes the rows
        # it reads. Idempotent, and a day with no home row is a refused gap.
        self._seal_baseload_day(yesterday)

        # Remove daily accumulators from previous days
        # Skip sunrise-keyed keys (EV + per-device, cleaned separately below)
        keys_to_remove = [
            k for k in self._daily_accumulators.keys()
            if not k.endswith(str(today)) and not _sunrise_keyed(k)
        ]
        # Clean old sunrise-keyed daily keys (keeps today + yesterday)
        keys_to_remove += [
            k for k in self._daily_accumulators.keys()
            if _sunrise_keyed(k)
            and not k.endswith(str(today))
            and not k.endswith(yesterday_str)
        ]
        for key in keys_to_remove:
            del self._daily_accumulators[key]

        # Remove monthly accumulators from previous months
        keys_to_remove = [
            k for k in self._monthly_accumulators.keys()
            if not k.endswith(month_key)
            and not (k.startswith(DEVICE_KEY_PREFIX) and k.endswith(prev_month_key))
        ]
        for key in keys_to_remove:
            del self._monthly_accumulators[key]

        # Remove yearly accumulators from previous years
        if year_key:
            keys_to_remove = [
                k for k in self._yearly_accumulators.keys()
                if not k.endswith(year_key)
                and not (k.startswith(DEVICE_KEY_PREFIX) and k.endswith(prev_year_key))
            ]
            for key in keys_to_remove:
                del self._yearly_accumulators[key]
        # Note: _lifetime_accumulators never get cleaned up (by design)

        # Clean up cost accumulators — mirror the energy accumulator cleanup
        today_str = str(today)
        cost_daily_remove = [
            k for k in self._daily_cost_accumulators
            if not k.endswith(today_str)
        ]
        for key in cost_daily_remove:
            del self._daily_cost_accumulators[key]

        cost_monthly_remove = [
            k for k in self._monthly_cost_accumulators
            if not k.endswith(month_key)
        ]
        for key in cost_monthly_remove:
            del self._monthly_cost_accumulators[key]

        if year_key:
            cost_yearly_remove = [
                k for k in self._yearly_cost_accumulators
                if not k.endswith(year_key)
            ]
            for key in cost_yearly_remove:
                del self._yearly_cost_accumulators[key]

    def get_state(self) -> Dict[str, Any]:
        """Get calculator state for persistence."""
        return {
            "daily_accumulators": self._daily_accumulators.copy(),
            "monthly_accumulators": self._monthly_accumulators.copy(),
            "yearly_accumulators": self._yearly_accumulators.copy(),
            "lifetime_accumulators": self._lifetime_accumulators.copy(),
            "daily_cost_accumulators": self._daily_cost_accumulators.copy(),
            "monthly_cost_accumulators": self._monthly_cost_accumulators.copy(),
            "yearly_cost_accumulators": self._yearly_cost_accumulators.copy(),
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "yearly_seeded": self._yearly_seeded,
            "yearly_cost_seeded": self._yearly_cost_seeded,
            "rate_history": list(self._rate_history),
            "accumulated_savings": self._accumulated_savings,
            "accumulated_battery_savings": self._accumulated_battery_savings,
            "accumulated_cost": self._accumulated_cost,
            "accumulated_export_revenue": self._accumulated_export_revenue,
            "accumulated_grid_import_kwh": self._accumulated_grid_import_kwh,
            "accumulated_self_consumed_kwh": self._accumulated_self_consumed_kwh,
            "accumulated_export_kwh": self._accumulated_export_kwh,
            # (#556) persisting the counter baselines makes the counter
            # delta span SEM downtime — production while SEM was off is
            # credited on the first cycle after restart.
            "solar_counter_baselines": dict(self._solar_counter_baselines),
            # (#658) same reason, and the whole point of the EV case: the
            # energy this reconciliation exists to recover is exactly the
            # energy charged while SEM was NOT running. Drop the baselines on
            # restart and the first cycle re-baselines at the current counter
            # value — the downtime delta is silently discarded.
            "ev_counter_baselines": dict(self._ev_counter_baselines),
            # (#628) same again for the grid/battery meters — a restart in the
            # middle of the day must not forget where today's registers
            # started, or the anchor re-lands on the current daily value and
            # the downtime consumption is lost.
            "meter_baselines": {
                cat: dict(bl) for cat, bl in self._meter_baselines.items()
            },
            # (#628) The calendar-day EV mirror the home balance subtracts.
            # ``midnight_ev_since`` must survive a restart or every restart
            # would look like the upgrade day and suppress the balance forever.
            "midnight_ev_baselines": dict(self._midnight_ev_baselines),
            "midnight_ev_since": (
                self._midnight_ev_since.isoformat()
                if self._midnight_ev_since else None
            ),
            # (#724) Which deadline opened the running EV day. Without this
            # pair a restart re-derives the day from whatever the deadline is
            # NOW, which is exactly the retroactive re-bucket ``_ev_reset_day``
            # defends against — the bug would simply return on the next reboot.
            "ev_day_offset": self._ev_day_offset,
            "ev_day_key": (
                self._ev_day_key.isoformat() if self._ev_day_key else None
            ),
            # (#770) The battery's cost basis. It has to survive a restart or
            # every reboot would hand the pool back as unknown and the
            # savings figure would drift back toward the flat-rate answer
            # exactly when a force-charged night is still sitting in there.
            "battery_provenance": self._battery_provenance.get_state(),
            # (#773) Sealed baseload days. Losing them on restart would
            # re-arm the drift check's "too little history" silence for two
            # weeks after every reboot — the exact window a post-upgrade
            # sensor fault most needs catching in.
            "baseload_history": list(self._baseload_history),
        }

    @staticmethod
    def _migrate_ev_keys(accumulators: Dict[str, float]) -> Dict[str, float]:
        """Rename stored ``ev_daily_sun_*`` accumulator keys to ``ev_*`` (#666).

        Runs on every restore rather than behind a version flag: it is a pure
        prefix rewrite, idempotent, and a no-op once the store is clean — which
        is cheaper and harder to get wrong than a migration counter that has to
        be right exactly once.

        Handles the lifetime shape too, where the category is embedded rather
        than prefixed (``lifetime_ev_daily_sun`` → ``lifetime_ev``).

        On the (impossible-by-construction, but free to be right about)
        collision where both names hold a value for the same period, the two are
        SUMMED rather than one silently winning: both were produced by real
        integration, so dropping either would lose energy the user actually used.
        """
        if not isinstance(accumulators, dict):
            return {}
        if not any(_LEGACY_EV_CATEGORY in k for k in accumulators):
            return accumulators

        migrated: Dict[str, float] = {}
        for key, value in accumulators.items():
            if key.startswith(_LEGACY_EV_KEY_PREFIX):
                new_key = _EV_KEY_PREFIX + key[len(_LEGACY_EV_KEY_PREFIX):]
            elif key == f"lifetime_{_LEGACY_EV_CATEGORY}":
                new_key = f"lifetime_{EV_CATEGORY}"
            else:
                new_key = key
            if new_key in migrated:
                migrated[new_key] += value
            else:
                migrated[new_key] = value
        _LOGGER.info(
            "Migrated %d EV accumulator key(s) from '%s' to '%s' (#666)",
            sum(1 for k in accumulators if _LEGACY_EV_CATEGORY in k),
            _LEGACY_EV_CATEGORY, EV_CATEGORY,
        )
        return migrated

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore calculator state from persistence."""
        if state:
            self._daily_accumulators = self._migrate_ev_keys(
                state.get("daily_accumulators", {}))
            self._monthly_accumulators = self._migrate_ev_keys(
                state.get("monthly_accumulators", {}))
            self._yearly_accumulators = self._migrate_ev_keys(
                state.get("yearly_accumulators", {}))
            self._lifetime_accumulators = self._migrate_ev_keys(
                state.get("lifetime_accumulators", {}))
            self._daily_cost_accumulators = state.get("daily_cost_accumulators", {})
            self._monthly_cost_accumulators = state.get("monthly_cost_accumulators", {})
            self._yearly_cost_accumulators = state.get("yearly_cost_accumulators", {})
            self._yearly_seeded = state.get("yearly_seeded", False)
            self._yearly_cost_seeded = state.get("yearly_cost_seeded", False)
            rate_history = state.get("rate_history", [])
            self._rate_history = deque(
                rate_history if isinstance(rate_history, list) else [], maxlen=30
            )
            # (#668) These are now actually persisted, so a corrupt entry would
            # survive every restart instead of being reset by the drop. The
            # numeric repair in the store only covers the accumulator *dicts*;
            # these are bare scalars, so they are coerced here.
            self._accumulated_savings = _as_float(state.get("accumulated_savings"))
            self._accumulated_battery_savings = _as_float(
                state.get("accumulated_battery_savings"))
            self._accumulated_cost = _as_float(state.get("accumulated_cost"))
            self._accumulated_export_revenue = _as_float(
                state.get("accumulated_export_revenue"))
            self._accumulated_grid_import_kwh = _as_float(
                state.get("accumulated_grid_import_kwh"))
            self._accumulated_self_consumed_kwh = _as_float(
                state.get("accumulated_self_consumed_kwh"))
            self._accumulated_export_kwh = _as_float(state.get("accumulated_export_kwh"))
            baselines = state.get("solar_counter_baselines")
            if isinstance(baselines, dict):
                self._solar_counter_baselines = baselines
            ev_baselines = state.get("ev_counter_baselines")
            if isinstance(ev_baselines, dict):
                self._ev_counter_baselines = ev_baselines
            meter_baselines = state.get("meter_baselines")
            if isinstance(meter_baselines, dict):
                # Per-category shape check — a damaged blob for one category
                # must not poison the others (the reconciler also re-creates
                # any entry whose shape it doesn't recognise).
                self._meter_baselines = {
                    cat: bl for cat, bl in meter_baselines.items()
                    if isinstance(bl, dict)
                }
            midnight_ev = state.get("midnight_ev_baselines")
            if isinstance(midnight_ev, dict):
                self._midnight_ev_baselines = midnight_ev
            since = state.get("midnight_ev_since")
            if since:
                try:
                    self._midnight_ev_since = date.fromisoformat(str(since))
                except ValueError:
                    _LOGGER.warning(
                        "Discarding unparseable midnight_ev_since %r — the home "
                        "balance re-arms for one day", since,
                    )
            ev_day_offset = state.get("ev_day_offset")
            ev_day_key = state.get("ev_day_key")
            if _valid_hhmm(ev_day_offset) and ev_day_key:
                try:
                    self._ev_day_key = date.fromisoformat(str(ev_day_key))
                    self._ev_day_offset = str(ev_day_offset)
                except ValueError:
                    # Re-derive from config on the next cycle. The only cost is
                    # that a deadline moved during the downtime applies at once.
                    _LOGGER.warning(
                        "Discarding unparseable EV day memo %r/%r — the EV day "
                        "re-derives from the current deadline",
                        ev_day_offset, ev_day_key,
                    )
                    self._ev_day_offset = None
                    self._ev_day_key = None
            else:
                # A store WITHOUT the memo is a pre-#724 install mid-upgrade:
                # its running EV day was keyed by the legacy rule, so continue
                # it under that rule and let the new one take over at the next
                # rollover. (A fresh install never reaches restore_state, so
                # this cannot mask a genuinely new setup.)
                self._seed_ev_day_memo_from_legacy_rule()
            # (#770) The battery's cost basis. ``restore_state`` on the store
            # drops junk rather than raising — a corrupt pool has to degrade
            # to "SEM knows nothing yet", which the unknown bucket models.
            self._battery_provenance.restore_state(state.get("battery_provenance"))
            # (#773) Sealed baseload days — junk rows are dropped, not
            # repaired; a dropped day is a gap the drift check refuses.
            baseload = state.get("baseload_history")
            if isinstance(baseload, list):
                self._baseload_history = deque(
                    (r for r in baseload
                     if isinstance(r, dict) and r.get("date")),
                    maxlen=_BASELOAD_HISTORY_DAYS,
                )
            last_update = state.get("last_update")
            if last_update:
                self._last_update = datetime.fromisoformat(last_update)
