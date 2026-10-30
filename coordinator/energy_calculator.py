"""Energy calculation module for SEM coordinator."""
from __future__ import annotations

import calendar
import copy
import inspect
import logging
import math
import re
import time
import uuid
from collections import deque
from types import SimpleNamespace
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import DEFAULT_ELECTRICITY_IMPORT_RATE, DOMAIN
from ..consts.core import SENSOR_DARK_READ_GRACE_S

from .types import (
    PowerReadings, EnergyTotals, CostData, PerformanceMetrics,
    PowerFlows, EnergyFlows, shown_w,
)
from .flow_calculator import FlowCalculator
from ..utils.time_manager import TimeManager
from .units import energy_state_to_kwh
from .sensor_reader import EV_ACTIVE_CHARGE_FLOOR_W
from .repair_issues import UNAVAILABLE_REPAIR_THRESHOLD_S
from ..ha_energy_reader import ENERGY_COUNTER_CATEGORIES, energy_counters
from .battery_provenance import (
    BatteryProvenance, allocate_fleet_charge, discharge_savings,
)

from ..utils.log_gate import log_on_change
from ..utils.helpers import (
    BATTERY_SALE_SENSOR_KEY, battery_export_part, solar_export,
)

_LOGGER = logging.getLogger(__name__)

# Minimum power thresholds to prevent ghost accumulation
MIN_POWER_THRESHOLD = 10  # Watts

# Maximum integration gap — skip cycle if sensors were unavailable longer
# than this (prevents energy spikes from sensor restarts / integration updates)
MAX_INTEGRATION_GAP_SECONDS = 120  # 2 minutes
# (#1187) How long a step across an outage waits for the counters that
# bound its night part. After a power cut an integration can retry its
# setup for minutes; the wait starts once Home Assistant runs.
SOLAR_GAP_WAIT_S = 1800
# (#1187) The counters whose movement bounds what a solar counter can show
# in the dark: the batteries' output, and the grid power #681 says passes
# through a hybrid to a car charging at night.
SOLAR_GAP_BOUND_CATEGORIES = ("battery_discharge", "grid_import")

# Threshold for hardware reconciliation (kWh)
RECONCILIATION_THRESHOLD = 0.5

# (#1049) A drop of an EV counter by at most the larger of these is a dip
# that comes back (a box falling back to an older stored value on a reboot);
# booked as a reset it would count the climb back as charging (bug class 43),
# so the last reading holds. A larger drop is a reset — a daily counter at
# midnight, a session counter at the next plug-in, a new box.
EV_COUNTER_DIP_KWH = 0.1
EV_COUNTER_DIP_SHARE = 0.01

# (#1101) The most one box can draw: 3 × 63 A × 230 V, the largest AC supply a
# home box is wired for. A trap for a counter step no box could have drawn,
# not a rating (bug classes 40, 43) — a box set up larger keeps its own.
EV_COUNTER_BOX_MAX_KW = 44.0
# (#1101) A live power read under the floor can still be one phase of three
# (#1035): the time it covers may have held up to this many times that draw.
EV_COUNTER_TRICKLE_FACTOR = 3.0
# (#1101) What SEM saw a box draw and its counter has not shown yet is kept
# until the box has been seen idle this long: a late counter may report it in
# several steps after the stop. A power read above the meter leaves a rest
# that is not energy, so it may not wait for ever.
EV_COUNTER_LATE_REPORT_H = 2.0
# (#1161) What a day's EV row keeps of the day before until its first
# anchor: enough to say what that day booked above its counters.
_EV_CLOSING_KEYS = ("row", "anchor", "base", "last", "drawn_at", "owed",
                    "carried")

# Adoption threshold for a metered category (#628). Much finer than the solar/EV
# 0.5 kWh: those correct a large one-way shortfall, while a grid row is often
# only ~1 kWh all day (#628's reporter: 1.05 kWh import), where a 0.5 kWh dead
# band would leave half the error in place. Below this the integrator keeps the
# row — the point is to stop drift, not to chase noise.
METER_RECONCILIATION_THRESHOLD = 0.05

# (#1177) The power inputs the daily rows integrate: the input, the flag that
# says every read of it was dark this cycle (``SensorReader``, #818), and the
# fields the integral books from it. A dark read is the reader's 0 W, right
# for steering and wrong for an integral (bug class 58): on PROD the modbus
# inverter was dark 26 % of a noon hour, the solar row lost that share, and
# home — the balance of the metered rows — went down.
_INTEGRAL_INPUTS = (
    ("solar", "solar_power_unavailable", ("solar_power",)),
    ("grid", "grid_power_unavailable",
     ("grid_import_power", "grid_export_power")),
    ("battery", "battery_power_all_unavailable",
     ("battery_charge_power", "battery_discharge_power")),
)
#: (#1177) the flows the battery's books are split by (charge origin, #770;
#: the delivered share of a discharge, #776)
_BATTERY_FLOW_FIELDS = ("solar_to_battery", "grid_to_battery",
                        "battery_to_home", "battery_to_ev", "battery_to_grid")

# Sanity ceiling for one day of a metered category (#628). Solar, battery and
# EV have physical bounds to check against (kWp × 16 h, 3 × the battery size,
# chargers × amps × 24 h — see ``_daily_ceiling``); grid does not, so this is a
# pure unit-error trap — a Wh register read as kWh is 1000× out. No
# residential install imports or exports 1 MWh in a day.
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

# (#1046) Where the car's kWh came from, on the EV day. The car's solar share
# is printed beside ``daily_ev`` ("Today 5 kWh · Solar Share 100 %"), so its
# flows must cover the same hours: the flow layer's own totals roll at
# midnight, and a night charge before the Charge-by time would sit in the
# share and not in "Today". The ``ev_`` prefix keeps these rows through the
# midnight sweep, like the EV row. DAILY-ONLY, like the midnight mirror.
EV_DAY_FLOW_CATEGORIES = (
    ("solar_to_ev", "ev_flow_solar"),
    ("grid_to_ev", "ev_flow_grid"),
    ("battery_to_ev", "ev_flow_battery"),
)

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

# (#794) SEM's own monthly COST sensors, cost category → sensor key. The
# recorder keeps these as long-term statistics even after the in-memory
# monthly accumulators are pruned to the current month, so past months of
# cost are MEASURED — at the prices actually in force — not estimable-only.
# unique_id is f"sem_{key}" (sensor.py builds it that way); always resolved
# through the entity registry, never by hardcoded entity_id — users rename
# entities.
# (#794) Rounding slack when comparing the yearly accumulator against the sum
# of its recorded months — both are money rounded at different points, so an
# exact `<` would lift on noise.
_YEARLY_COST_FLOOR_TOLERANCE = 0.01

_MONTHLY_COST_STAT_KEYS = {
    "cost_import": "monthly_costs",
    "cost_export": "monthly_export_revenue",
    "cost_savings": "monthly_savings",
    "cost_batt_savings": "monthly_battery_savings",
}

# (#794) The energy series each cost category's estimate is derived from.
# A category with no recorded months AND none of its basis series in the
# recorder has nothing to say — the seed keeps the live-accumulated value
# for it rather than overwriting real money with a zero.
_COST_ESTIMATE_BASIS = {
    "cost_import": ("grid_import",),
    "cost_export": ("grid_export",),
    "cost_savings": ("solar",),
    "cost_batt_savings": ("battery_discharge",),
}

# (#724) The boundary the FLEET EV total falls back to when its chargers do not
# share a Charge-by deadline. Expressed as an offset so it flows through the
# same ``get_current_meter_day_offset_based`` path (and the same day memo) as a
# real deadline — "00:00" is calendar midnight by construction.
_FLEET_CALENDAR_OFFSET = "00:00"



def _finite(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _aware(value: Any) -> Optional[datetime]:
    """(#1187) A stored or published time with its zone; None for any
    other value (no zone, not a time)."""
    if isinstance(value, str):
        try:
            value = dt_util.parse_datetime(value)
        except (TypeError, ValueError):   # ISO in shape, not in its values
            return None
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value
    return None


def _ev_day_after(before: Any, day: str) -> bool:
    """(#1160) ``day`` is the day right after ``before`` (ISO dates)."""
    try:
        return (date.fromisoformat(day)
                - date.fromisoformat(str(before))) == timedelta(days=1)
    except ValueError:
        return False


def _ev_counter_drop(value: float, ref: Optional[float]) -> Optional[str]:
    """(#1049) ``"dip"`` or ``"reset"`` for a reading below ``ref``, else None."""
    if ref is None or value >= ref - 0.001:
        return None
    window = max(EV_COUNTER_DIP_KWH, ref * EV_COUNTER_DIP_SHARE)
    return "dip" if ref - value <= window else "reset"


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


def _as_seed_counters(value: Any) -> Optional[Dict[str, List[str]]]:
    """A stored lifetime seed set (#1043), or None when it is not one.

    None means "no record", which makes the seed check the counters again —
    the safe answer for a damaged entry.
    """
    if not isinstance(value, dict):
        return None
    out: Dict[str, List[str]] = {}
    for category, ids in value.items():
        if not isinstance(category, str) or not isinstance(ids, (list, tuple)):
            return None
        if not all(isinstance(e, str) for e in ids):
            return None
        out[category] = sorted(ids)
    return out


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce a restored scalar, falling back rather than raising (#668)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if value is not None:
            _LOGGER.warning(
                "Discarding non-numeric restored value %r — using %s", value, default
            )
        return default
    return float(value)


def _stat_bucket_year_month(row: Dict[str, Any]) -> Optional[tuple[int, int]]:
    """(year, month) of a recorder statistics row's ``start``, else None (#794).

    The real recorder returns float unix timestamps; test doubles and older
    cores hand back datetimes or ISO strings — all three are one bucket
    identity, so all three parse.
    """
    start = row.get("start")
    if isinstance(start, bool):
        return None
    if isinstance(start, (int, float)):
        try:
            local = dt_util.as_local(dt_util.utc_from_timestamp(float(start)))
        except (ValueError, OverflowError, OSError):
            return None
        return local.year, local.month
    if isinstance(start, datetime):
        # Localize aware datetimes like the float path — a bucket starts at a
        # LOCAL month boundary, so its UTC form reads as the previous month in
        # any zone east of UTC. Naive datetimes are already local (tests).
        if start.tzinfo is not None:
            start = dt_util.as_local(start)
        return start.year, start.month
    if isinstance(start, str):
        parsed = dt_util.parse_datetime(start)
        if parsed is None:
            return None
        if parsed.tzinfo is not None:
            parsed = dt_util.as_local(parsed)
        return parsed.year, parsed.month
    return None


def _sem_stat_entity_id(hass: Optional[HomeAssistant], key: str) -> Optional[str]:
    """(#1216) The entity id of SEM's own sensor ``key``, by its unique id
    (``sem_<key>``) — users rename entities. None when it cannot be found."""
    if hass is None:
        return None
    try:
        from homeassistant.helpers import entity_registry as er
        entity_id = er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"sem_{key}")
    except Exception:  # noqa: BLE001 — registry absent/mocked (tests, early boot)
        return None
    return entity_id if isinstance(entity_id, str) and entity_id else None


# Environmental impact constants
GRID_CO2_KG_PER_KWH = 0.128  # Swiss grid average — the fallback (#1088)
#: (#1088) accumulator category of the live-intensity correction, in kg
CO2_CORRECTION_CATEGORY = "co2_live_correction"
#: (#1191) the battery's part of ``grid_export`` (a sale), booked beside it
GRID_EXPORT_BATTERY_CATEGORY = "grid_export_battery"
#: (#1191 review) rows booked beside a metered row, by that row: when the
#: meter corrects the row, each keeps its share of what was added since the
#: last correction
_ROWS_BESIDE = {"grid_export": (GRID_EXPORT_BATTERY_CATEGORY,)}

# (#1077) The value layer's cost categories: what solar used at home was
# worth over exporting it, what exported kWh fetched before the fee, and the
# feed-in fees. Booked only while a value field is set.
VALUE_SELF_CONSUMPTION = "value_self_consumption"
VALUE_EXPORT = "value_export"
VALUE_FEED_IN_FEE = "value_feed_in_fee"
#: (#812) A device on its own tariff: its grid kWh and what they cost at
#: that tariff, per device id. Keyed on the calendar day like the house's
#: own import cost, so the two daily figures roll together.
DEVICE_TARIFF_KWH = "device_tariff_kwh:"
DEVICE_TARIFF_COST = "device_tariff_cost:"
CO2_KG_PER_TREE_PER_YEAR = 22  # EPA estimate


class EnergyCalculator:
    """Calculates energy totals from power readings over time."""

    def __init__(self, config: Dict[str, Any], time_manager: TimeManager):
        """Initialize energy calculator."""
        self.config = config
        self._time_manager = time_manager

        # Accumulators for energy integration
        self._daily_accumulators: Dict[str, float] = {}
        # (#1088) the grid's live CO2 intensity this cycle (kg/kWh), or None
        # = no usable reading; and the soak flag that lets it count.
        self._grid_co2_kg: Optional[float] = None
        self._co2_live: bool = False
        self._monthly_accumulators: Dict[str, float] = {}
        self._yearly_accumulators: Dict[str, float] = {}
        self._lifetime_accumulators: Dict[str, float] = {}

        # Cost accumulators (incremental, rate-weighted) — fixes dynamic tariff mid-day recalculation
        self._daily_cost_accumulators: Dict[str, float] = {}
        self._monthly_cost_accumulators: Dict[str, float] = {}
        self._yearly_cost_accumulators: Dict[str, float] = {}

        # Last update time for integration
        self._last_update: Optional[datetime] = None
        #: (#1177) input → (its fields' watts, when in UTC) at its last live
        #: read; the inputs held this cycle; the battery's live flow shares
        self._integral_last_live: Dict[str, Tuple[Tuple[float, ...], datetime]] = {}
        self._integral_held: frozenset = frozenset()
        self._integral_live: frozenset = frozenset()
        self._battery_live_flows: Optional[SimpleNamespace] = None
        # (#1203 review) each battery's charge watts at that same live read
        self._battery_live_charging: Dict[str, float] = {}
        # (#1191 review) the battery's part of the export, from the last
        # cycle the grid read live: a held export keeps it (#1177)
        self._grid_live_battery_export_w: float = 0.0
        #: (#1185) The readings and flows this cycle's books split by: a
        #: held input's watts in place of the reader's 0 W. Set by
        #: ``calculate_energy``; the coordinator hands them on to the flow
        #: rows and the session splits. Steering keeps the cycle's own.
        self.book_power: Optional[PowerReadings] = None
        self.book_flows: Optional[PowerFlows] = None

        # Cost rates
        self._import_rate = config.get("electricity_import_rate",
                                       DEFAULT_ELECTRICITY_IMPORT_RATE)
        self._export_rate = config.get("electricity_export_rate", 0.075)

        # Rate history for 7-day averaging (dynamic tariffs)
        self._rate_history: deque = deque(maxlen=30)
        #: (#812) device id → the stamped baseline of a device's own meter
        #: (entity, date, value, time), kept with the energy state so a
        #: restart books the first step after it.
        self.device_meter_last: Dict[str, Dict[str, Any]] = {}
        #: (#1228) device id → an own meter's step over time no cycle booked
        #: (SEM down, a skipped cycle, the meter dark), waiting for the house
        #: rows over the same time: kWh, start, the rows at the start.
        self.device_meter_gaps: Dict[str, Dict[str, Any]] = {}
        #: (#1228) the meter baselines written this cycle; the house rows at
        #: the cycle's end are stamped on them (``_settle_meter_gaps``)
        self._meter_written: Set[str] = set()
        #: (#1228) the own-meter devices staged this cycle: a held step of
        #: any other device is dropped
        self._meter_staged: Set[str] = set()
        #: (#1228) seconds this run has integrated, and the run they belong
        #: to: time SEM did not see is a span's length less what it saw
        self._seen_s = 0.0
        self._run_token = uuid.uuid4().hex
        #: (#812) this cycle's own-tariff devices, staged by the coordinator
        self._device_tariff_cycle: list = []
        #: (#812) the calendar day the last cycle booked under — the day the
        #: per-device cost sensors read, so they need no clock of their own
        self.booking_day: Optional[date] = None

        # (#1077) The value layer's books. ``_export_rate`` above is the
        # export VALUE (net of the per-kWh feed-in fee); these keep the
        # market price and the fee apart so the bill can show both. Off
        # (nothing accumulated) until a value field is set.
        self._value_layer_on: bool = False
        self._export_spot_rate: Optional[float] = None
        self._feed_in_fee_rate: float = 0.0
        self._feed_in_fixed_monthly: float = 0.0

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
        # (#1049) Every charger has a counter of its own, so the counters see
        # all the charging the power integral sees. Only then may the EV rows
        # move down to them — see ``_ev_adoption``.
        self._ev_counter_complete: bool = False
        # (#1049) Per charger id: the same baseline model for that charger's
        # own daily row (``follow_charger_counter``). Persisted.
        self._charger_counter_baselines: Dict[str, Dict[str, Any]] = {}
        # (#1049) Counter → the charger id whose power it counts. Set with
        # ``complete``.
        self._ev_counter_owner: Dict[str, str] = {}
        # (#1157) Counter → every charger id whose charging it counts: its
        # owner alone, or the whole fleet for a fallback counter (legacy daily
        # sensor, Energy Dashboard), or the chargers that name one counter.
        # The step check reads these boxes' power.
        self._ev_counter_boxes: Dict[str, Tuple[str, ...]] = {}
        # (#1159) Counters given the whole fleet because SEM does not know
        # which boxes they count: none of their ``pending`` is owed.
        self._ev_counter_guessed: Set[str] = set()
        # (#1049) Owners drawing charging power this cycle. Runtime only.
        self._ev_owners_drawing: Set[str] = set()
        # (#1049) Per counter: the kWh its box drew since the counter last
        # moved (``pending``), and the reading of that move (``seen``).
        # Persisted — a cloud counter can still owe a session at a restart.
        self._ev_counter_pending: Dict[str, float] = {}
        self._ev_counter_seen: Dict[str, float] = {}
        # (#1101) Per counter: the most kWh its box could have drawn since the
        # counter last moved, in time SEM did not see that box idle — while it
        # charged, while its power read was dark, while SEM was down. A
        # counter missing here has no known history: its next move is booked
        # as it stands. ``watched_at``: the last cycle that kept this up.
        # Persisted with ``pending``. ``foreign``: this cycle's steps that
        # stand for kWh no box drew — counter → (reading before, kWh).
        self._ev_counter_room: Dict[str, float] = {}
        self._ev_watched_at: Optional[datetime] = None
        self._ev_counter_foreign: Dict[str, Tuple[float, float]] = {}
        # (#1101) Per counter: kWh SEM saw its box draw that the counter has
        # not shown yet. Unlike ``pending`` it outlives a move — a late
        # counter can report a session in several steps. ``idle_h``: hours
        # the box has been seen idle since it last charged. Both persisted.
        self._ev_counter_unreported: Dict[str, float] = {}
        self._ev_counter_idle_h: Dict[str, float] = {}
        # (#1101) Per counter: the part of ``room`` from time SEM did not see
        # the box (a dark or foreign power read, SEM down, a skipped cycle),
        # and the hours SEM has watched the box since (``quiet_h``). Both
        # persisted.
        self._ev_counter_unseen_kwh: Dict[str, float] = {}
        self._ev_counter_quiet_h: Dict[str, float] = {}
        # (#1159) Counters whose boxes this cycle read each on their own
        # power sensor, so ``pending`` is their own draw. Runtime only.
        self._ev_counter_own_read: Set[str] = set()
        # (#1161) Per counter: every kWh SEM saw its boxes draw, charging,
        # while it read them on their own (``_ev_counter_owes``). A row
        # takes it at its anchor (``drawn_at``); at the day's end the
        # difference is what that day drew. Persisted with ``pending``.
        self._ev_counter_drawn_total: Dict[str, float] = {}
        # (#556) Daily-solar reconciliation against hardware production
        # counters — closes the cloud-poll undercount (integrating a power
        # sensor that reports 0/unavailable between polls). Baselines are
        # per-entity counter snapshots for the current day:
        # {"date": "YYYY-MM-DD", "<entity_id>": kwh_at_first_sight}.
        self._solar_counter_entities: List[str] = []
        self._solar_counter_enabled: bool = False
        self._solar_counter_logged: bool = False
        self._solar_counter_baselines: Dict[str, Any] = {}
        # (#1187) when SEM began to wait for a battery discharge counter to
        # judge a step across an outage (in memory: a restart waits again)
        self._solar_gap_wait_since: Optional[datetime] = None
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
        # (#1218) The day each category's counter was last refused above its
        # ceiling: one warning a day, not one a cycle.
        self._ceiling_warned: Dict[str, str] = {}
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
        # (#1176) The car day ``daily_ev`` last read from, and the moment it
        # last rolled to a new one — that sensor's ``last_reset``. Both
        # persist; no moment yet (a fresh install, the upgrade's own car
        # day) leaves the sensor on midnight, as it said before.
        self._ev_seen_day: Optional[date] = None
        self._ev_rolled_at: Optional[datetime] = None
        # (#1046) the day key daily_ev was last read from (not persisted:
        # the next cycle sets it before anyone reads it)
        self._daily_ev_day: Optional[date] = None
        # (#1046) The EV day the ``ev_flow_*`` rows were first booked on.
        # That day began before them, so its rows are short. Persisted, or
        # every restart would look like the upgrade day.
        self._ev_flow_since: Optional[date] = None
        self._lifetime_seeded: bool = False
        # (#1043) Which counters, per category, the lifetime seed added up —
        # persisted, so a seed taken from a different set (the first tariff
        # only, before #1043) is known and taken again. None = no record.
        self._lifetime_seed_counters: Optional[Dict[str, List[str]]] = None
        # (#1043) Per counter: when it was first seen without a reading while
        # HA was running. Runtime only — the wait starts again on every start.
        self._lifetime_seed_unready_since: Dict[str, float] = {}
        self._yearly_seeded: bool = False
        self._yearly_seed_attempts: int = 0
        # Separate flag for the yearly COST backfill so it can correct installs
        # whose ENERGY was already seeded before the cost backfill existed.
        self._yearly_cost_seeded: bool = False
        # (#794) The floor re-check is deliberately NOT persisted. Both seed
        # flags above come back True from storage, so on the very installs the
        # floor exists to heal the startup gate would already be closed and the
        # check would never run. Runtime-only means every restart gets one
        # fresh chance; the attempt cap stops it holding the gate open forever
        # when the recorder simply has no cost history to compare against.
        self._yearly_cost_floor_checked: bool = False
        self._yearly_cost_floor_attempts: int = 0
        # Auto-detected from recorder statistics (first solar energy entry)
        self._install_year_decimal: Optional[float] = None
        # (#773) Sealed days of the true-baseload residual, newest last.
        # One row per finished calendar day WITH a home row — a day without
        # one is a gap and is refused, never recorded as zero. Persisted.
        self._baseload_history: deque = deque(maxlen=_BASELOAD_HISTORY_DAYS)
        # (#1044) The first calendar day whose mirror held home members only
        # (SEM's own chargers left out). Persisted, the ``midnight_ev_since``
        # way: a restart must not look like the upgrade day.
        self._home_members_since: Optional[date] = None

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
        """Every charger's ``Charge by`` time (#1023: the one resolver's
        answer); the global one, or 07:00, before any charger exists."""
        from .departure import departure_hhmm

        chargers = self.config.get("ev_chargers") or []
        return ([departure_hhmm(c, self.config) for c in chargers]
                or [departure_hhmm(None, self.config)])

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

    def _integral_watts(self, power: PowerReadings, at: datetime) -> Dict[str, float]:
        """(#1177) The watts this cycle's integrals book, by field.

        A dark input books its last live read for ``SENSOR_DARK_READ_GRACE_S``
        — the window its own entity shows that value — and the reader's 0 W
        after it. The age counts from the live read, so a dark cycle never
        renews it. A live 0 W is a reading and is booked and held as 0.
        ``at`` is UTC: a local clock goes back an hour in autumn, and an age
        below 0 is not known, so it holds nothing.

        Home books the house SEM shows (``home_shown_w``, #1047) while it
        holds one: the raw home is built from a dark input's 0 W. Steering
        never reads these values — they exist for the integrals only.
        ``_integral_held`` / ``_integral_live`` name the inputs held / read
        live this cycle.

        (#1186) An input read from several sensors with one of them dark
        books the figure SEM shows (``shown_w``): each dark unit at its own
        last live read, kept by the reader. That figure is the input's read,
        as its entity's last value is; while a unit is held the input
        counts as held, so the battery's flow shares and the grid's battery
        export come from the last read with every unit live.
        """
        watts: Dict[str, float] = {}
        held, live = set(), set()
        units = getattr(power, "held_w", None)
        units = units if isinstance(units, dict) else {}
        for name, flag, fields in _INTEGRAL_INPUTS:
            read = tuple(float(shown_w(power, f) or 0.0) for f in fields)
            last = self._integral_last_live.get(name)
            if getattr(power, flag, False) is not True:
                self._integral_last_live[name] = (read, at)
                (held if name in units else live).add(name)
            elif (last is not None and 0.0 <= (at - last[1]).total_seconds()
                  <= SENSOR_DARK_READ_GRACE_S):
                read = last[0]
                held.add(name)
            watts.update(zip(fields, read, strict=True))
        self._integral_held = frozenset(held)
        self._integral_live = frozenset(live)
        shown = getattr(power, "home_shown_w", None)
        if not isinstance(shown, (int, float)) or isinstance(shown, bool):
            shown = power.home_consumption_power
        watts["home_consumption_power"] = float(shown or 0.0)
        return watts

    def _book_flows(self, power: PowerReadings,
                    power_flows: "Optional[PowerFlows]",
                    held_w: Dict[str, float]):
        """(#1185) The readings and flows this cycle's books split by.

        The cycle's flows come from the reader's watts, where a dark input
        is 0 W (#818): right for steering, wrong for the books (class 58).
        While an input is held (``_integral_held``), the rows book its held
        watts, so the flows are built again from a copy of the readings
        with the booked watts in — the held input's and the shown house
        (#1047). The daily flows, the solar savings and the splits by source
        then keep a dark input's share for the grace, as the rows do. The
        copy's held units are in its totals, so it holds none of its own.

        With no input held, the cycle's own readings and flows are used as
        they are — also while the house alone is shown held (the #1105
        battery stop): its sources are all live, and a held house beside
        them would leave live import in no flow.
        """
        if power_flows is None or not self._integral_held:
            return power, power_flows
        held = {f: w for f, w in held_w.items()
                if w != float(getattr(power, f, 0.0) or 0.0)}
        if not held:
            return power, power_flows
        readings = copy.copy(power)
        readings.held_w = {}
        for field, watts in held.items():
            setattr(readings, field, watts)
        return readings, FlowCalculator.calculate_power_flows(readings)

    def _battery_flows(self, power_flows: "Optional[PowerFlows]"):
        """(#1177 review) The battery's flow shares for the books.

        A dark battery is 0 W in the flows too. With its watts held, a
        charge split on those flows is lost and a discharge counts as
        delivered in full — a sale from the pack paid twice (#776). So
        while the battery is held, its shares from the same live read go
        with it; a live battery uses this cycle's flows. The shares are
        taken only when the battery is live, the read its watts are held
        from.
        """
        if "battery" in self._integral_held:
            return self._battery_live_flows
        if "battery" in self._integral_live:
            self._battery_live_flows = None if power_flows is None else (
                SimpleNamespace(**{
                    f: float(getattr(power_flows, f, 0.0) or 0.0)
                    for f in _BATTERY_FLOW_FIELDS}))
        return power_flows

    def calculate_energy(
        self, power: PowerReadings,
        power_flows: "Optional[PowerFlows]" = None,
    ) -> EnergyTotals:
        """Calculate energy totals by integrating power over time."""
        self.book_power = self.book_flows = None   # (#1185) this cycle's only
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
        # (#1177) a dark input books its last live read, not 0 W — read
        # first, so a skipped cycle's live read still counts as one
        held_w = self._integral_watts(power, dt_util.utcnow())
        # (#1185) …and every split by source below takes the flows built
        # from the same watts: from here ``power_flows`` is the books' own
        book_power, power_flows = self._book_flows(power, power_flows, held_w)
        self.book_power, self.book_flows = book_power, power_flows
        battery_flows = self._battery_flows(power_flows)
        # (#1191 review) the battery's part of a live meter's export, kept for
        # a dark meter's held export — taken here, before a skipped cycle
        # returns, because its read can be held too
        if "grid" in self._integral_live:
            self._grid_live_battery_export_w = battery_export_part(
                held_w["grid_export_power"],
                getattr(battery_flows, "battery_to_grid", 0.0))

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
        self._seen_s += interval_hours * 3600.0   # (#1228)

        # Check for day/month/year rollover and reset accumulators
        self._check_rollover(today, month_key, year_key)
        self.booking_day = today   # (#812)

        # (#628) This cycle's counter-backing starts empty — each reconciler
        # below records its own category only when it actually read a COMPLETE
        # counter set. ``_reconcile_home_energy`` reads the result.
        self._counter_backed = set()
        self._meter_staged = set()   # (#1228) filled by ``_import_cost``

        # Integrate power to energy
        energy = EnergyTotals()

        # Solar energy
        if held_w["solar_power"] >= MIN_POWER_THRESHOLD:
            solar_increment = (held_w["solar_power"] * interval_hours) / 1000  # kWh
            self._accumulate("solar", today, month_key, year_key, solar_increment)
        # (#556) hardware-counter reconciliation — upward-only correction
        # for cloud-polled power sensors; must run before the read below.
        self._reconcile_solar_energy(today, month_key, year_key, now)
        energy.daily_solar = self._get_daily("solar", today)
        energy.monthly_solar = self._get_monthly("solar", month_key)
        energy.yearly_solar = self._get_yearly("solar", year_key)
        energy.lifetime_solar = self._get_lifetime("solar")  # #573

        # Home consumption. The integral runs unconditionally — it is the
        # fallback and the anchor — but the READ moved below every other
        # category (#628): home is a residual of those categories, so it can
        # only be reconciled once they have been.
        if held_w["home_consumption_power"] >= MIN_POWER_THRESHOLD:
            home_increment = (held_w["home_consumption_power"] * interval_hours) / 1000
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
        # (#1046) the car's flow split, on the same EV day as the row above.
        # Not behind the ev_power gate: the flows are their own measure.
        if power_flows is not None:
            if self._ev_flow_since is None:
                self._ev_flow_since = ev_day
            for attr, category in EV_DAY_FLOW_CATEGORIES:
                watts = max(0.0, float(getattr(power_flows, attr, 0.0) or 0.0))
                if watts > 0.0:
                    key = f"{category}_{ev_day}"
                    self._daily_accumulators[key] = (
                        self._daily_accumulators.get(key, 0.0)
                        + watts * interval_hours / 1000.0
                    )
        # (#658) wallbox-counter reconciliation — recovers charging SEM was not
        # running to integrate; must run before the reads below, exactly like
        # its solar sibling.
        # (#1049) …after noting what each box drew since its counter moved.
        self._track_ev_pending(power, interval_hours, now)
        self._reconcile_ev_energy(ev_day, month_key, year_key)
        self._reconcile_midnight_ev_energy(today)  # (#628)

        energy.daily_ev = self._get_daily(EV_CATEGORY, ev_day)
        self._daily_ev_day = ev_day  # (#1046) the key ev_day_flows reads
        self._note_ev_rollover(ev_day)
        energy.monthly_ev = self._get_monthly(EV_CATEGORY, month_key)
        energy.yearly_ev = self._get_yearly(EV_CATEGORY, year_key)

        # Grid import
        if held_w["grid_import_power"] >= MIN_POWER_THRESHOLD:
            import_increment = (held_w["grid_import_power"] * interval_hours) / 1000
            self._accumulate("grid_import", today, month_key, year_key, import_increment)
            # (#812) split here, in the one booking, when a device is on its
            # own tariff; with none, exactly ``import_increment × rate``
            self._accumulate_cost("cost_import", today, month_key, year_key,
                                  self._import_cost(import_increment, interval_hours,
                                                    book_power, power_flows, today,
                                                    month_key, year_key)
                                  if self._device_tariff_cycle else
                                  import_increment * self._import_rate)
        if self._device_tariff_cycle:
            # (#812) no import this cycle: nothing to split, but the meter
            # baselines advance (their steps came from the sun)
            self._import_cost(0.0, interval_hours, book_power, power_flows,
                              today, month_key, year_key)
        # (#628) utility-meter reconciliation — bidirectional, so it must run
        # before the reads below exactly like its solar and EV siblings.
        self._reconcile_metered_energy(
            "grid_import", today, month_key, year_key,
            cost_key="cost_import", rate=self._import_rate,
        )
        energy.daily_grid_import = self._get_daily("grid_import", today)
        energy.monthly_grid_import = self._get_monthly("grid_import", month_key)
        energy.yearly_grid_import = self._get_yearly("grid_import", year_key)

        # (#1191) The battery's part of this cycle's export, booked beside it.
        # Its flow comes from the read the held watts came from (#1177): a
        # dark pack's held flows, or a dark meter's last live split.
        if "grid" in self._integral_held:
            battery_export_w = min(held_w["grid_export_power"],
                                   self._grid_live_battery_export_w)
        else:
            battery_export_w = battery_export_part(
                held_w["grid_export_power"],
                getattr(battery_flows, "battery_to_grid", 0.0))
        # Grid export
        if held_w["grid_export_power"] >= MIN_POWER_THRESHOLD:
            export_increment = (held_w["grid_export_power"] * interval_hours) / 1000
            self._accumulate("grid_export", today, month_key, year_key, export_increment)
            if battery_export_w > 0:
                self._accumulate(
                    GRID_EXPORT_BATTERY_CATEGORY, today, month_key, year_key,
                    battery_export_w * interval_hours / 1000)
            self._accumulate_cost("cost_export", today, month_key, year_key, export_increment * self._export_rate)
            # (#871, arc #921) The same kWh counted again when the meter was
            # hostile — a separate key, not a sign on the export total, because
            # that total is what a user reads as "what I sent out".
            if float(self._export_rate or 0.0) < 0:
                self._accumulate("grid_export_negative", today, month_key, year_key, export_increment)
                self._accumulate_cost("cost_export_negative", today, month_key, year_key,
                                      export_increment * abs(float(self._export_rate)))
            # (#1077) The bill's two lines: what the kWh fetched on the
            # market, and the per-kWh feed-in fee taken off it.
            if self._value_layer_on:
                spot = (self._export_spot_rate if self._export_spot_rate is not None
                        else float(self._export_rate or 0.0))
                self._accumulate_cost(VALUE_EXPORT, today, month_key, year_key,
                                      export_increment * spot)
                if self._feed_in_fee_rate:
                    self._accumulate_cost(VALUE_FEED_IN_FEE, today, month_key, year_key,
                                          export_increment * self._feed_in_fee_rate)
        # (#1077) A fixed monthly fee is owed by the hour, whatever flows.
        if self._value_layer_on and self._feed_in_fixed_monthly > 0:
            hours_in_month = calendar.monthrange(today.year, today.month)[1] * 24
            self._accumulate_cost(
                VALUE_FEED_IN_FEE, today, month_key, year_key,
                self._feed_in_fixed_monthly * interval_hours / hours_in_month)
        self._reconcile_metered_energy(
            "grid_export", today, month_key, year_key,
            cost_key="cost_export", rate=self._export_rate,
        )
        # (#1088) CO2 avoided at the grid's LIVE intensity. Booked as the
        # DIFFERENCE from the fixed Swiss average, per kWh of solar used in
        # the house this cycle: the published totals stay
        #   self-consumed × 0.128 + this correction
        # so switching it on adds nothing at that moment (no jump in a
        # lifetime total), a restart keeps it (it is an accumulator), and a
        # cycle with no usable reading adds exactly 0 — the fixed value.
        if self._co2_live and self._grid_co2_kg is not None:
            used_w = max(0.0, held_w["solar_power"] - solar_export(
                held_w["grid_export_power"], battery_export_w))
            if used_w >= MIN_POWER_THRESHOLD:
                used_kwh = used_w * interval_hours / 1000
                self._accumulate(
                    CO2_CORRECTION_CATEGORY, today, month_key, year_key,
                    used_kwh * (self._grid_co2_kg - GRID_CO2_KG_PER_KWH))
        energy.daily_grid_export = self._get_daily("grid_export", today)
        energy.daily_grid_export_battery = self._get_daily(GRID_EXPORT_BATTERY_CATEGORY, today)
        energy.monthly_grid_export_battery = self._get_monthly(GRID_EXPORT_BATTERY_CATEGORY, month_key)
        energy.yearly_grid_export_battery = self._get_yearly(GRID_EXPORT_BATTERY_CATEGORY, year_key)
        energy.daily_grid_export_negative = self._get_daily("grid_export_negative", today)
        energy.daily_grid_export_negative_cost = self._get_daily_cost("cost_export_negative", today)
        energy.monthly_grid_export_negative = self._get_monthly("grid_export_negative", month_key)
        energy.yearly_grid_export_negative = self._get_yearly("grid_export_negative", year_key)
        energy.monthly_grid_export_negative_cost = self._get_monthly_cost("cost_export_negative", month_key)
        energy.yearly_grid_export_negative_cost = self._get_yearly_cost("cost_export_negative", year_key)
        energy.monthly_grid_export = self._get_monthly("grid_export", month_key)
        energy.yearly_grid_export = self._get_yearly("grid_export", year_key)

        # Battery charge
        if held_w["battery_charge_power"] >= MIN_POWER_THRESHOLD:
            charge_increment = (held_w["battery_charge_power"] * interval_hours) / 1000
            self._accumulate("battery_charge", today, month_key, year_key, charge_increment)
            # (#770) …and again, told apart by origin. The flow layer has
            # always known which part came off the roof; it just never
            # reached the ledger, so a kWh bought in the valley discharged
            # against the full import price and the difference was called
            # savings.
            self._file_battery_charge_origin(
                power, battery_flows, charge_increment, today,
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
        if held_w["battery_discharge_power"] >= MIN_POWER_THRESHOLD:
            discharge_increment = (held_w["battery_discharge_power"] * interval_hours) / 1000
            self._accumulate("battery_discharge", today, month_key, year_key, discharge_increment)
            # (#770) What this discharge actually saved, not what a discharge
            # of free solar would have saved. Drawn from the pool in
            # proportion; the grid part only earns the SPREAD, because the
            # purchase already sits in the import cost.
            self._accumulate_cost(
                "cost_batt_savings", today, month_key, year_key,
                self._battery_discharge_savings(
                    power, discharge_increment, battery_flows),
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
        # (#1218) A counter's figure never gets here: the corrections refuse
        # one above the same ceiling, because a cap writes the day alone.
        battery_capacity = self.config.get("battery_capacity_kwh", 15)
        max_daily_battery = self._daily_ceiling("battery_charge")
        inverter_kwp = self.config.get("system_size_kwp", 10)
        max_daily_solar = self._daily_ceiling("solar")

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
        # (#1228) an own meter's step over time no cycle booked, against the
        # house rows over the same time — read once every row is final
        self._settle_meter_gaps(today, month_key, year_key, now)
        energy.daily_home = self._get_daily("home", today)
        energy.monthly_home = self._get_monthly("home", month_key)
        energy.yearly_home = self._get_yearly("home", year_key)
        # (#825) The HA-comparable twin travels WITH home, on every
        # path that publishes it — a row assembled in two places is a
        # row that goes stale in one of them.
        energy.daily_total_consumption = self.daily_total_consumption(today)

        # (#773) The audited residual, derived AFTER home because it is one
        # more subtraction from it. The W twin is filled by the coordinator,
        # which owns the live device draws.
        # (#1044) The first day this code books the mirror. Before it, SEM's
        # own chargers were booked too; a day that began before it is not
        # sealed as a home-members-only day (``_seal_baseload_day``).
        if self._home_members_since is None:
            self._home_members_since = today
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
            home_incr = (held_w["home_consumption_power"] * interval_hours) / 1000 if held_w["home_consumption_power"] >= MIN_POWER_THRESHOLD else 0.0
            # FLEET-READ: legacy fallback path. ``power_flows`` is the
            # preferred input in the v1.7.0+ coordinator pipeline; this
            # branch only fires for the two-arg test fixtures that
            # pre-date the per-cycle ``calculate_power_flows`` call.
            ev_incr = (power.ev_power * interval_hours) / 1000 if power.ev_power >= MIN_POWER_THRESHOLD else 0.0
            import_incr = (held_w["grid_import_power"] * interval_hours) / 1000 if held_w["grid_import_power"] >= MIN_POWER_THRESHOLD else 0.0
            discharge_incr = (held_w["battery_discharge_power"] * interval_hours) / 1000 if held_w["battery_discharge_power"] >= MIN_POWER_THRESHOLD else 0.0
            # Solar self-consumed = total consumption minus what came from grid or battery discharge
            solar_self_consumed = max(0.0, (home_incr + ev_incr) - import_incr - discharge_incr)
        if solar_self_consumed > 0.0:
            self._accumulate_cost("cost_savings", today, month_key, year_key, solar_self_consumed * self._import_rate)
            # (#1077) What using it at home was worth over selling it: the
            # spread between the import and the export value, per kWh.
            if self._value_layer_on:
                self._accumulate_cost(
                    VALUE_SELF_CONSUMPTION, today, month_key, year_key,
                    solar_self_consumed * (float(self._import_rate or 0.0)
                                           - float(self._export_rate or 0.0)))

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
        # (#825) The HA-comparable twin travels WITH home, on every
        # path that publishes it — a row assembled in two places is a
        # row that goes stale in one of them.
        energy.daily_total_consumption = self.daily_total_consumption(today)
        energy.daily_ev = self._get_daily(EV_CATEGORY, ev_day)
        self._daily_ev_day = ev_day  # (#1046) the key ev_day_flows reads
        self._note_ev_rollover(ev_day)
        energy.monthly_ev = self._get_monthly(EV_CATEGORY, month_key)
        energy.yearly_ev = self._get_yearly(EV_CATEGORY, year_key)
        energy.daily_grid_import = self._get_daily("grid_import", today)
        energy.monthly_grid_import = self._get_monthly("grid_import", month_key)
        energy.yearly_grid_import = self._get_yearly("grid_import", year_key)
        energy.daily_grid_export = self._get_daily("grid_export", today)
        energy.monthly_grid_export = self._get_monthly("grid_export", month_key)
        energy.yearly_grid_export = self._get_yearly("grid_export", year_key)
        energy.daily_grid_export_battery = self._get_daily(GRID_EXPORT_BATTERY_CATEGORY, today)
        energy.monthly_grid_export_battery = self._get_monthly(GRID_EXPORT_BATTERY_CATEGORY, month_key)
        energy.yearly_grid_export_battery = self._get_yearly(GRID_EXPORT_BATTERY_CATEGORY, year_key)
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
        self, hass: HomeAssistant, entity_ids: List[str], enabled: bool,
        complete: bool = False,
        owners: Optional[Dict[str, str]] = None,
        boxes: Optional[Dict[str, List[str]]] = None,
        guessed: Optional[List[str]] = None,
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

        ``complete`` (#1049): every charger has a counter of its own, so the set
        sees all the charging the power integral sees. Only a complete set may
        pull the EV rows DOWN; a partial one stays upward-only. ``owners`` maps
        each counter to its charger id: until the counter reports what that
        box charged, the rows may not move down. A counter without an owner
        leaves the set partial.

        ``boxes`` (#1157): each counter → every charger id whose charging it
        counts. A counter is checked against the power of these boxes
        (``_track_ev_pending``); one with no boxes is not checked. An owner is
        its counter's one box when ``boxes`` does not name it.

        ``guessed`` (#1159): the counters whose boxes are the whole fleet only
        because SEM does not know which boxes they count. Their ``pending``
        is never owed at an anchor (``_ev_counter_owes``).

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
        owners = {e: str(o) for e, o in (owners or {}).items()
                  if e in self._ev_counter_entities and o}
        self._ev_counter_owner = owners
        counted = {e: tuple(dict.fromkeys(str(c) for c in (cids or []) if c))
                   for e, cids in (boxes or {}).items()
                   if e in self._ev_counter_entities}
        for entity_id, owner in owners.items():
            counted.setdefault(entity_id, (owner,))
        self._ev_counter_boxes = {e: b for e, b in counted.items() if b}
        self._ev_counter_guessed = {e for e in (guessed or [])
                                    if e in self._ev_counter_boxes}
        self._ev_counter_complete = bool(complete) and all(
            e in owners for e in self._ev_counter_entities)
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
    def _energy_state_kwh(state) -> Optional[float]:
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
        # (#1202) None when the state gives no number: read as 0 kWh, "none"
        # or "nan" looked like a counter reset and the next read booked the
        # whole register.
        return energy_state_to_kwh(state)

    def _read_counter_set(
        self, hass: HomeAssistant, entity_ids: List[str], now: float,
    ) -> "tuple[Optional[float], List[str], bool]":
        """Add up one category's hardware counters (#1043).

        Returns ``(kwh, summed, complete)``. A counter is not ready while it
        has no state, reads unknown/unavailable, or reads no number above 0 —
        a counter still loading reads one of those, and adding it as 0 makes
        a sum that looks complete (#1043 seeded 12,396 of 60,601 kWh solar
        that way). ``kwh`` is None while any counter is not ready and its wait
        is not over. The wait starts only once HA runs: before that, every
        entity of an integration still loading has no state (bug class 86).
        After ``UNAVAILABLE_REPAIR_THRESHOLD_S`` the counter is left out, so a
        gone Energy Dashboard row cannot hold the seed for ever, and
        ``complete`` is False: the sum is then only a floor. An external
        statistic id (``source:id``) never has a state and is left out at once.
        """
        running = bool(getattr(hass, "is_running", False))
        unready = self._lifetime_seed_unready_since
        total = 0.0
        summed: List[str] = []
        complete = True
        waiting = False
        for entity_id in entity_ids:
            external = ":" in entity_id
            value = None
            if not external:
                state = hass.states.get(entity_id)
                if state is not None:
                    value = energy_state_to_kwh(state)  # #551 unit-aware
            if value is not None and math.isfinite(value) and value > 0:
                unready.pop(entity_id, None)
                total += value
                summed.append(entity_id)
                continue
            complete = False
            if external:
                continue
            if running and entity_id not in unready:
                unready[entity_id] = now
            since = unready.get(entity_id)
            if since is None or now - since < UNAVAILABLE_REPAIR_THRESHOLD_S:
                waiting = True
        return (None if waiting else total), summed, complete

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

        def _read(entity_id):
            if not entity_id:
                return 0.0
            state = hass.states.get(entity_id)
            if state and state.state not in ("unknown", "unavailable", None):
                value = self._energy_state_kwh(state)  # #551 unit-aware
                # (#1202) no number seeds nothing, as "unavailable" does
                return 0.0 if value is None else value
            return 0.0

        # (#1043) Every category is the SUM of all its Energy Dashboard
        # counters, as HA's dashboard shows it — not the first one. Solar was
        # summed since #556; grid and battery read the first counter only, so
        # a dual-tariff meter seeded tariff 1 alone. A sum is taken only once
        # every counter in it reads, or has been left out after the wait.
        counters = {
            category: energy_counters(ed_config, category)
            for category in ENERGY_COUNTER_CATEGORIES
        }
        now = time.monotonic()
        totals: Dict[str, float] = {}
        seed_set: Dict[str, List[str]] = {}
        complete: Dict[str, bool] = {}
        waiting = False
        for category, entity_ids in counters.items():
            kwh, summed, whole = self._read_counter_set(hass, entity_ids, now)
            seed_set[category] = sorted(summed)
            complete[category] = whole
            if kwh is None:
                waiting = True
            else:
                totals[category] = kwh
        left_out = sorted(
            e for category, ids in counters.items() for e in ids
            if e not in seed_set[category]
        )
        if waiting:
            log_on_change(
                _LOGGER, "lifetime_seed_wait", logging.DEBUG,
                "Lifetime seed waiting for counter(s) with no reading: %s",
                ", ".join(left_out),
            )
            return
        if left_out:
            log_on_change(
                _LOGGER, "lifetime_seed_left_out", logging.INFO,
                "Lifetime seed: Energy Dashboard counter(s) %s gave no reading "
                "— left out; those lifetime totals are only raised, never "
                "lowered", ", ".join(left_out),
            )
        solar = totals["solar"]
        grid_import = totals["grid_import"]
        grid_export = totals["grid_export"]
        batt_charge = totals["battery_charge"]
        batt_discharge = totals["battery_discharge"]

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
        # (#1043) Only a battery counter that gave a reading is waited for: an
        # install without a battery read 0 + 0 here and never seeded at all.
        if (
            (seed_set["battery_charge"] or seed_set["battery_discharge"])
            and (batt_charge < 1 or batt_discharge < 1)
            and (batt_charge + batt_discharge) < 10
        ):
            _LOGGER.debug(
                "Lifetime seed waiting for battery: charge=%.0f discharge=%.0f",
                batt_charge, batt_discharge,
            )
            return

        # Check if ALL sensors are properly seeded (not just solar).
        # Re-seed any sensor that is <50% of the hardware counter —
        # this fixes the race condition where solar loaded first but
        # grid/battery were unavailable during initial seeding (#110).
        # (#1043) That re-seed, the 90 % solar check and a changed counter
        # set only RAISE totals (``_raise_lifetime_to_counters``): a swapped
        # inverter, a removed row or a second charger reads less than the
        # history SEM holds. Only the #551 unit heal sets values outright.
        current = self._lifetime_accumulators
        raise_needed = False
        unit_heal = False
        for category in ENERGY_COUNTER_CATEGORIES:
            key = f"lifetime_{category}"
            hw_value = totals[category]
            stored = current.get(key, 0)
            if hw_value > 100 and stored < hw_value * 0.5:
                _LOGGER.info(
                    "Lifetime re-seed needed: %s stored=%.0f hw=%.0f (%.0f%%)",
                    key, stored, hw_value, (stored / hw_value * 100) if hw_value > 0 else 0,
                )
                raise_needed = True
            # #551 — DOWNWARD self-heal: installs that seeded before the
            # unit-aware read stored Wh values as kWh (×1000). The
            # accumulator can never legitimately dwarf its own hardware
            # counter, so stored >> hw means a corrupted seed — re-seed
            # from the (now unit-corrected) counter. (#1043) Never from a sum
            # with a counter left out: that is a floor, not the counter.
            if complete[category] and hw_value > 10 and stored > hw_value * 2:
                _LOGGER.info(
                    "Lifetime re-seed (downward, #551 unit fix): %s "
                    "stored=%.0f hw=%.0f", key, stored, hw_value,
                )
                unit_heal = True
                break

        if not unit_heal:
            if self._lifetime_seed_counters is None:
                # No record: the seed came from before #1043, which read only
                # the FIRST grid and battery counter — wrong wherever a list
                # is longer.
                set_changed = any(len(ids) > 1 for ids in counters.values())
            else:
                set_changed = self._lifetime_seed_counters != seed_set
            if (
                raise_needed
                or set_changed
                or current.get("lifetime_solar", 0) <= solar * 0.9
            ):
                self._raise_lifetime_to_counters(
                    totals, self._read_ev_seed(ed_config, _read), seed_set,
                )
            self._lifetime_seed_counters = seed_set
            self._lifetime_seeded = True
            return

        # Seed (or re-seed) all lifetime accumulators from hardware. (#1043) A
        # category with a counter left out is a floor, so it only goes up.
        for category in ENERGY_COUNTER_CATEGORIES:
            key = f"lifetime_{category}"
            value = totals[category]
            if not complete[category]:
                value = max(value, current.get(key, 0.0))
            self._lifetime_accumulators[key] = value
        acc = self._lifetime_accumulators
        home = max(0, acc["lifetime_solar"] + acc["lifetime_grid_import"]
                   + acc["lifetime_battery_discharge"] - acc["lifetime_grid_export"]
                   - acc["lifetime_battery_charge"])
        self._lifetime_accumulators["lifetime_home"] = home

        ev_total = self._read_ev_seed(ed_config, _read)
        if ev_total > 0:
            self._lifetime_accumulators["lifetime_ev"] = ev_total

        self._lifetime_seed_counters = seed_set
        self._lifetime_seeded = True
        _LOGGER.info(
            "Lifetime seeded from hardware: solar=%.0f import=%.0f export=%.0f "
            "batt_charge=%.0f batt_discharge=%.0f home=%.0f ev=%.0f kWh",
            acc["lifetime_solar"], acc["lifetime_grid_import"],
            acc["lifetime_grid_export"], acc["lifetime_battery_charge"],
            acc["lifetime_battery_discharge"], home, ev_total,
        )

    @staticmethod
    def _read_ev_seed(ed_config, read) -> float:
        """Seed EV from hardware counter (KEBA total energy etc.)."""
        for dev in getattr(ed_config, "device_consumption", None) or []:
            energy_sensor = dev.get("stat_consumption", "")
            if any(p in energy_sensor.lower() for p in ["keba", "ev", "charger", "wallbox", "easee"]):
                return read(energy_sensor)
        return 0.0

    def _raise_lifetime_to_counters(
        self, totals: Dict[str, float], ev_total: float, seed_set: Dict[str, List[str]],
    ) -> None:
        """Raise each lifetime total its counters prove too low (#1043).

        Only UP: a counter that was replaced or removed reads less than the
        history SEM holds, and that history stays. On a fresh install every
        total is 0, so this is the full seed. ``lifetime_home`` moves by the
        same amounts, with the sign each category has in the energy balance.
        """
        acc = self._lifetime_accumulators
        home_delta = 0.0
        raised = []
        for category in ENERGY_COUNTER_CATEGORIES:
            key = f"lifetime_{category}"
            delta = totals[category] - acc.get(key, 0.0)
            if delta <= 0:
                continue
            acc[key] = totals[category]
            home_delta += -delta if category in ("grid_export", "battery_charge") else delta
            raised.append(f"{category} +{delta:.0f}")
        if ev_total > acc.get("lifetime_ev", 0.0):
            raised.append(f"ev +{ev_total - acc.get('lifetime_ev', 0.0):.0f}")
            acc["lifetime_ev"] = ev_total
        if not raised:
            return
        acc["lifetime_home"] = max(0.0, acc.get("lifetime_home", 0.0) + home_delta)
        _LOGGER.info(
            "Lifetime seeded from hardware — raised to the Energy Dashboard "
            "counters %s: %s kWh", seed_set, ", ".join(raised),
        )

    @property
    def yearly_seed_pending(self) -> bool:
        """Is any part of the yearly backfill still owed? (#794)

        The coordinator's startup gate. It is NOT enough to ask whether the two
        seed flags are set: both are persisted, so an install that seeded badly
        last year comes back with them True and would never call in again —
        and the floor re-check that exists to heal exactly that install would
        never run. The gate therefore stays open until the floor has been
        checked once this run (or given up), which is why that flag is
        runtime-only.
        """
        return not (
            self._yearly_seeded
            and self._yearly_cost_seeded
            and self._yearly_cost_floor_checked
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
        # ("month and year are the same"). Prefers SEM's own recorded monthly
        # cost statistics (#794); the estimate fallback needs the yearly
        # energy present, so that path is a no-op until it's seeded — for a
        # fresh install it runs from the success path below instead.
        await self._maybe_seed_yearly_cost(hass, ed_config, str(dt_util.now().year))

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

        # Category → every Energy Dashboard counter of it (#1043: all tariffs
        # and inverters, not the first one).
        category_counters = {
            category: ids
            for category in ENERGY_COUNTER_CATEGORIES
            if (ids := energy_counters(ed_config, category))
        }

        if not category_counters:
            _LOGGER.debug("No energy entities in ED config for yearly seeding")
            return

        # Query statistics from Jan 1 of current year
        now = dt_util.now()
        start_time = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        entity_ids = list(dict.fromkeys(
            entity_id for ids in category_counters.values() for entity_id in ids
        ))
        # (#1216) the pack's sale from SEM's own sensor, read beside the
        # export: the year's export below comes from the recorder, so the
        # row booked beside it must too, or every sale reads as solar's
        sale_id = _sem_stat_entity_id(hass, BATTERY_SALE_SENSOR_KEY)
        if sale_id and sale_id not in entity_ids:
            entity_ids.append(sale_id)

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

        # Extract yearly energy: difference between latest and first sum,
        # added up over the category's counters (#1043)
        def _span(entity_id: str) -> Optional[float]:
            entity_stats = stats.get(entity_id, [])
            if len(entity_stats) < 2:
                return None
            first_sum = entity_stats[0].get("sum") if entity_stats[0].get("sum") is not None else 0.0
            last_sum = entity_stats[-1].get("sum") if entity_stats[-1].get("sum") is not None else 0.0
            return max(0, last_sum - first_sum)

        seeded = {}
        for category, ids in category_counters.items():
            yearly_energy = 0.0
            has_stats = False
            for entity_id in ids:
                span = _span(entity_id)
                if span is None:
                    continue
                yearly_energy += span
                has_stats = True
            seeded[category] = yearly_energy
            if has_stats:
                self._yearly_accumulators[f"{category}_{year_key}"] = yearly_energy
                if category == "grid_export":
                    # (#1216) the row beside the export follows it: the
                    # recorded sale, never more than the export. With no
                    # history of it the row keeps what SEM saw live.
                    sale_key = f"{GRID_EXPORT_BATTERY_CATEGORY}_{year_key}"
                    sale = _span(sale_id) if sale_id else None
                    if sale is None:
                        sale = self._yearly_accumulators.get(sale_key, 0.0)
                    self._yearly_accumulators[sale_key] = battery_export_part(
                        yearly_energy, sale)

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
        await self._maybe_seed_yearly_cost(hass, ed_config, year_key)

        self._yearly_seeded = True
        _LOGGER.info(
            "Yearly accumulators seeded from recorder: solar=%.1f import=%.1f export=%.1f "
            "batt_charge=%.1f batt_discharge=%.1f home=%.1f ev=%.1f kWh",
            seeded.get("solar", 0), seeded.get("grid_import", 0), seeded.get("grid_export", 0),
            seeded.get("battery_charge", 0), seeded.get("battery_discharge", 0),
            home, ev_total,
        )

    async def _maybe_seed_yearly_cost(
        self, hass: Optional[HomeAssistant], ed_config, year_key: str
    ) -> None:
        """Backfill the yearly COST accumulators — measured months first (#794).

        SEM records its own monthly cost sensors as long-term statistics, so
        for every month the recorder holds a bucket, that month's cost is
        KNOWN, at the prices actually in force. The seed is therefore
        Σ(recorded monthly buckets) per category, with an energy × avg-rate
        estimate ONLY for months that have no cost record at all. This makes
        yearly == Σ monthly by construction — the property the user checks
        when both figures share one screen (live on PROD the old whole-year
        estimate sat 4× below the recorded months and flipped the year's net
        cost sign).

        SET (not add): the seed spans Jan→now (the current month's partial
        bucket included), and live accumulation continues from here — disjoint,
        no double count, exactly like the energy seed. Runs once
        (``_yearly_cost_seeded``); the floor re-check afterwards runs on EVERY
        call regardless of that flag, so a badly seeded install self-heals
        instead of staying wrong until January.

        Degradation: no recorder / no registry entries / query error → the
        pre-#794 energy × avg-rate estimate, logged at debug. Never raises —
        this runs on the coordinator startup path.
        """
        recorded = await self._query_recorded_monthly_costs(hass, year_key)
        if not self._yearly_cost_seeded:
            if recorded:
                await self._seed_yearly_cost_from_recorded(
                    hass, ed_config, year_key, recorded
                )
            else:
                self._seed_yearly_cost_estimate(year_key)
        self._apply_yearly_cost_floor(year_key, recorded)

    async def _seed_yearly_cost_from_recorded(
        self,
        hass: Optional[HomeAssistant],
        ed_config,
        year_key: str,
        recorded: Dict[str, Dict[int, float]],
    ) -> None:
        """Seed the yearly cost from recorded monthly buckets (#794).

        Per category: Σ(recorded months). Months without a bucket fall back to
        that month's energy × avg rate — measured where measured, estimated
        only where nothing was measured. A category with neither recorded
        months nor an estimate basis keeps its live-accumulated value.
        """
        now = dt_util.now()
        months = range(1, now.month + 1) if year_key == str(now.year) else range(1, 13)
        missing = {
            category: [m for m in months if m not in recorded.get(category, {})]
            for category in _MONTHLY_COST_STAT_KEYS
        }
        month_energy = None
        if any(missing.values()):
            month_energy = await self._query_monthly_energy(hass, ed_config, year_key)
        imp_rate = self._get_avg_import_rate()
        exp_rate = self._get_avg_export_rate()
        estimated_months = 0
        seeded: Dict[str, float] = {}
        for category in _MONTHLY_COST_STAT_KEYS:
            rec_months = recorded.get(category, {})
            has_basis = any(
                (month_energy or {}).get(series)
                for series in _COST_ESTIMATE_BASIS[category]
            )
            if not rec_months and not has_basis:
                # Nothing measured and nothing to estimate from — keep the
                # live-accumulated value rather than zeroing real money.
                continue
            total = sum(rec_months.values())
            for m in missing[category]:
                estimate = self._estimate_month_cost(
                    category, m, month_energy, imp_rate, exp_rate
                )
                if estimate:
                    estimated_months += 1
                total += estimate
            seeded[category] = round(total, 4)
            self._yearly_cost_accumulators[f"{category}_{year_key}"] = seeded[category]
        self._yearly_cost_seeded = True
        _LOGGER.info(
            "Yearly COST seeded from recorded monthly statistics: import=%.2f "
            "export=%.2f solar_savings=%.2f batt_savings=%.2f (%d month-value(s) "
            "estimated for months without cost history)",
            seeded.get("cost_import", 0.0), seeded.get("cost_export", 0.0),
            seeded.get("cost_savings", 0.0), seeded.get("cost_batt_savings", 0.0),
            estimated_months,
        )

    def _estimate_month_cost(
        self,
        category: str,
        month: int,
        month_energy: Optional[Dict[str, Dict[int, float]]],
        imp_rate: float,
        exp_rate: float,
    ) -> float:
        """Estimate one pre-cost-tracking month from its energy × avg rate."""
        if not month_energy:
            return 0.0

        def _e(series: str) -> float:
            return float(month_energy.get(series, {}).get(month, 0.0) or 0.0)

        # (#1216) the pack's part of the month's export, where SEM recorded it
        sold = battery_export_part(
            _e("grid_export"), _e(GRID_EXPORT_BATTERY_CATEGORY))
        if category == "cost_import":
            return _e("grid_import") * imp_rate
        if category == "cost_export":
            return _e("grid_export") * exp_rate
        if category == "cost_savings":
            # Only the SOLAR-charged portion of battery charge consumed solar;
            # grid-charged energy must not reduce the solar savings (#794).
            solar_charged = _e("battery_charge") * (
                1.0 - self._battery_grid_origin_share
            )
            # (#1216) only solar's export is taken away from solar
            solar_direct = max(0.0, _e("solar") - solar_export(
                _e("grid_export"), sold) - solar_charged)
            return solar_direct * imp_rate
        if category == "cost_batt_savings":
            # (#770) Full import rate on purpose — the provenance store has no
            # origin record for the pre-tracking past, and unknown origin keeps
            # the legacy credit rather than being charged for a measurement SEM
            # never took. (#776, #1216) A kWh the pack sold earns its export
            # revenue, not an avoided import too.
            return max(0.0, _e("battery_discharge") - sold) * imp_rate
        return 0.0

    def _seed_yearly_cost_estimate(self, year_key: str) -> None:
        """The degradation fallback: yearly ENERGY × average rate — once.

        Kept for installs where SEM's own monthly cost statistics cannot be
        read at all (no recorder, no registry entries, query error). The
        recorder has historical energy but NOT SEM's historical hourly prices,
        so the backfill is valued at an AVERAGE rate (7-day rolling, falling
        back to the current/config rate) — an ESTIMATE for the pre-tracking
        period on a dynamic tariff; the live portion since install stays
        exact. A no-op until the yearly energy exists.
        """
        ya = self._yearly_accumulators
        grid_import = float(ya.get(f"grid_import_{year_key}", 0.0) or 0.0)
        solar = float(ya.get(f"solar_{year_key}", 0.0) or 0.0)
        if grid_import <= 0 and solar <= 0:
            return  # yearly energy not seeded yet — retry on a later call
        grid_export = float(ya.get(f"grid_export_{year_key}", 0.0) or 0.0)
        batt_charge = float(ya.get(f"battery_charge_{year_key}", 0.0) or 0.0)
        batt_discharge = float(ya.get(f"battery_discharge_{year_key}", 0.0) or 0.0)
        # (#1216) the pack's part of the year's export, booked beside it
        sold = battery_export_part(grid_export, float(ya.get(
            f"{GRID_EXPORT_BATTERY_CATEGORY}_{year_key}", 0.0) or 0.0))
        imp_rate = self._get_avg_import_rate()
        exp_rate = self._get_avg_export_rate()
        # Avoided-import savings split to mirror the live accumulators and avoid
        # double counting: solar used DIRECTLY (not exported, not stored) +
        # battery discharged to load (stored solar is counted there, not here).
        # (#794) Only the SOLAR-charged share of the battery charge consumed
        # solar — energy bought from the grid and stored must not reduce the
        # solar savings (grid-charging installs understated the year
        # structurally; the live path has always used the flow-attributed
        # split).
        solar_charged = batt_charge * (1.0 - self._battery_grid_origin_share)
        # (#1216) only solar's export is taken away from solar
        solar_direct = max(
            0.0, solar - solar_export(grid_export, sold) - solar_charged)
        batt_delivered = max(0.0, batt_discharge - sold)
        ca = self._yearly_cost_accumulators
        ca[f"cost_import_{year_key}"] = round(grid_import * imp_rate, 4)
        ca[f"cost_export_{year_key}"] = round(grid_export * exp_rate, 4)
        ca[f"cost_savings_{year_key}"] = round(solar_direct * imp_rate, 4)
        # (#770) The backfilled discharge is credited at the FULL import rate
        # on purpose. The provenance store only knows what it watched; the
        # pre-tracking year has no origin record at all, and unknown origin
        # keeps the legacy credit rather than being charged for a measurement
        # SEM never took. Live accumulation from here on is split properly.
        # (#776, #1216) A kWh the pack sold earns its export revenue only.
        ca[f"cost_batt_savings_{year_key}"] = round(batt_delivered * imp_rate, 4)
        self._yearly_cost_seeded = True
        _LOGGER.info(
            "Yearly COST seeded (estimate @ avg import %.4f / export %.4f): "
            "import=%.2f export=%.2f solar_savings=%.2f batt_savings=%.2f CHF",
            imp_rate, exp_rate, grid_import * imp_rate, grid_export * exp_rate,
            solar_direct * imp_rate, batt_delivered * imp_rate,
        )

    def _apply_yearly_cost_floor(
        self, year_key: str, recorded: Optional[Dict[str, Dict[int, float]]]
    ) -> None:
        """Hold the yearly cost at or above the months actually recorded (#794).

        The invariant: a year can never have cost less than the sum of its own
        recorded months. Σ(months) includes the current month's partial bucket
        and live yearly = seed + accumulation since, so a healthy install
        already sits at or above the floor and this is a no-op — it only ever
        lifts, never caps, because live accumulation is finer-grained than the
        month bucket it is compared against and legitimately runs ahead of it.

        Unlike the seed this runs on EVERY call, regardless of
        ``_yearly_cost_seeded``: the install that needs healing is exactly the
        one whose flag came back True from storage carrying a bad value.
        """
        if not recorded:
            # Nothing measured to compare against. Retry across a few cycles in
            # case the recorder is still warming up, then stop holding the
            # startup gate open — mirrors the energy seed's attempt cap.
            self._yearly_cost_floor_attempts += 1
            if self._yearly_cost_floor_attempts >= 3:
                self._yearly_cost_floor_checked = True
                _LOGGER.debug(
                    "Yearly cost floor: no recorded monthly cost statistics "
                    "after %d attempts — nothing to reconcile against",
                    self._yearly_cost_floor_attempts,
                )
            return

        ca = self._yearly_cost_accumulators
        for category, months in recorded.items():
            floor = sum(months.values())
            key = f"{category}_{year_key}"
            current = float(ca.get(key, 0.0) or 0.0)
            if current < floor - _YEARLY_COST_FLOOR_TOLERANCE:
                ca[key] = round(floor, 4)
                _LOGGER.warning(
                    "Yearly cost floor: %s was %.2f but its %d recorded months "
                    "sum to %.2f — lifted to the measured value (#794)",
                    key, current, len(months), floor,
                )
        self._yearly_cost_floor_checked = True

    async def _query_recorded_monthly_costs(
        self, hass: Optional[HomeAssistant], year_key: str
    ) -> Optional[Dict[str, Dict[int, float]]]:
        """Read SEM's own recorded monthly cost statistics for the year.

        Returns ``{category: {month: value}}`` for every recorded bucket —
        these are monthly-resetting counters, so a bucket's ``state`` (last
        state in the bucket) IS that month's total. ``None`` whenever nothing
        could be read (no registry, no entities, no recorder, query error):
        the caller degrades to the estimate instead of guessing.
        """
        if hass is None:
            return None
        try:
            from homeassistant.helpers import entity_registry as er
            registry = er.async_get(hass)
        except Exception as e:  # noqa: BLE001 — registry absent/mocked (tests, early boot)
            _LOGGER.debug("Yearly cost seed: entity registry unavailable: %s", e)
            return None
        entity_map: Dict[str, str] = {}
        for category, sensor_key in _MONTHLY_COST_STAT_KEYS.items():
            try:
                entity_id = registry.async_get_entity_id(
                    "sensor", DOMAIN, f"sem_{sensor_key}"
                )
            except Exception:  # noqa: BLE001 — treat as unresolvable
                entity_id = None
            if isinstance(entity_id, str) and entity_id:
                entity_map[entity_id] = category
        if not entity_map:
            _LOGGER.debug(
                "Yearly cost seed: no SEM monthly cost sensors in the registry"
            )
            return None
        try:
            target_year = int(year_key)
        except (TypeError, ValueError):
            return None
        now = dt_util.now()
        start = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        stats = await self._recorder_stats(
            hass, start, set(entity_map), "month", {"state"}
        )
        if not stats:
            return None
        recorded: Dict[str, Dict[int, float]] = {}
        for entity_id, category in entity_map.items():
            for row in stats.get(entity_id) or []:
                value = row.get("state")
                if value is None:
                    continue
                bucket = _stat_bucket_year_month(row)
                if bucket is None or bucket[0] != target_year:
                    continue
                try:
                    recorded.setdefault(category, {})[bucket[1]] = float(value)
                except (TypeError, ValueError):
                    continue
        return recorded or None

    async def _query_monthly_energy(
        self, hass: Optional[HomeAssistant], ed_config, year_key: str
    ) -> Optional[Dict[str, Dict[int, float]]]:
        """Per-month energy for the ED entities: ``{series: {month: kWh}}``.

        Same entity roles as the yearly ENERGY seed, month buckets, per-bucket
        ``sum`` delta. Queried from Dec 1 of the previous year so January has
        a baseline; the recorder's sum column starts at 0 at the first
        statistic ever, so a missing predecessor means "history starts here"
        and 0.0 is the right baseline. ``None`` when nothing could be read.
        """
        if hass is None or not ed_config:
            return None
        # (#1043) every counter of a series, each one's month added in
        entity_map: Dict[str, str] = {}
        for series in ENERGY_COUNTER_CATEGORIES:
            for entity_id in energy_counters(ed_config, series):
                entity_map.setdefault(entity_id, series)
        if not entity_map:
            return None
        # (#1216) the pack's sale, from SEM's own sensor: the only history
        # that says who exported. A month before it existed has none, and
        # all its export stays solar's.
        sale_id = _sem_stat_entity_id(hass, BATTERY_SALE_SENSOR_KEY)
        if sale_id:
            entity_map.setdefault(sale_id, GRID_EXPORT_BATTERY_CATEGORY)
        try:
            target_year = int(year_key)
        except (TypeError, ValueError):
            return None
        now = dt_util.now()
        jan1 = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        query_start = (jan1 - timedelta(days=1)).replace(day=1)
        stats = await self._recorder_stats(
            hass, query_start, set(entity_map), "month", {"sum"}
        )
        if not stats:
            return None
        result: Dict[str, Dict[int, float]] = {}
        for entity_id, series in entity_map.items():
            prev_sum: Optional[float] = None
            for row in stats.get(entity_id) or []:
                raw = row.get("sum")
                if raw is None:
                    continue
                try:
                    cumulative = float(raw)
                except (TypeError, ValueError):
                    continue
                bucket = _stat_bucket_year_month(row)
                if bucket is not None and bucket[0] == target_year:
                    baseline = prev_sum if prev_sum is not None else 0.0
                    months = result.setdefault(series, {})
                    months[bucket[1]] = months.get(bucket[1], 0.0) + max(
                        0.0, cumulative - baseline
                    )
                prev_sum = cumulative
        return result or None

    async def _recorder_stats(
        self,
        hass: Optional[HomeAssistant],
        start: datetime,
        entity_ids: Set[str],
        period: str,
        types: Set[str],
    ):
        """``statistics_during_period`` without crashing the caller (#794).

        The real function is SYNC database work, so the recorder's executor is
        the proper home for it; a direct call is kept as fallback for
        environments where no recorder instance exists but the function is
        substituted (tests). Returns the stats dict, or ``None`` on any
        failure.
        """
        try:
            from homeassistant.components.recorder.statistics import (
                statistics_during_period,
            )
        except ImportError:
            _LOGGER.debug("Recorder not available for yearly cost seeding")
            return None
        result = None
        try:
            from homeassistant.components.recorder import get_instance
            job = get_instance(hass).async_add_executor_job(
                statistics_during_period,
                hass, start, None, entity_ids, period, None, types,
            )
            if inspect.isawaitable(job):
                job = await job
            if isinstance(job, dict):
                result = job
        except Exception as e:  # noqa: BLE001 — no instance / incompatible core
            _LOGGER.debug("Recorder executor path unavailable: %s", e)
        if result is None:
            try:
                direct = statistics_during_period(
                    hass, start, None, entity_ids, period, None, types
                )
                if inspect.isawaitable(direct):
                    direct = await direct
                if isinstance(direct, dict):
                    result = direct
            except Exception as e:  # noqa: BLE001 — degrade, don't crash startup
                _LOGGER.debug("Recorder statistics query failed: %s", e)
                return None
        return result

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

    def _sun_turn(self) -> Optional[datetime]:
        """(#1187) The next sunrise or sunset, whichever comes first, as
        ``sun.sun`` says now. None when the sun entity does not say."""
        state = self._hass.states.get("sun.sun") if self._hass else None
        attrs = getattr(state, "attributes", None)
        if not hasattr(attrs, "get"):
            return None
        found = [when for when in (_aware(attrs.get("next_rising")),
                                   _aware(attrs.get("next_setting")))
                 if when is not None]
        return min(found) if found else None

    def _bound_counters(self) -> List[str]:
        """(#1187) Every configured counter of ``SOLAR_GAP_BOUND_CATEGORIES``."""
        return [entity_id for category in SOLAR_GAP_BOUND_CATEGORIES
                for entity_id in self._meter_counter_entities.get(category) or []]

    def _bound_reads(self) -> Optional[Dict[str, float]]:
        """(#1187) Each bound counter's kWh: empty with none set, None while
        one is not read. A counter loading reads no number above 0 (#1043):
        taken as a reading, it would look like a counter that went back."""
        outs: Dict[str, float] = {}
        for entity_id in self._bound_counters():
            state = self._hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable", None):
                return None
            value = self._energy_state_kwh(state)  # #551 unit-aware
            if not (_finite(value) and value > 0):
                return None
            outs[entity_id] = float(value)
        return outs

    def _battery_known(self) -> bool:
        """(#1187) Has this home a battery: a battery counter, or energy SEM
        ever booked into or out of one?"""
        if (self._meter_counter_entities.get("battery_charge")
                or self._meter_counter_entities.get("battery_discharge")):
            return True
        return any(
            _finite(self._lifetime_accumulators.get(f"lifetime_{c}"))
            and self._lifetime_accumulators[f"lifetime_{c}"] > 0
            for c in ("battery_charge", "battery_discharge")
        )

    def _counts_only_while_ha_runs(self, entity_id: str) -> bool:
        """(#1187) A counter Home Assistant computes from a power sensor (a
        Riemann sum, a meter built on a source, SEM's own) does not count
        while HA is down. Flat over an outage, it says nothing of the night.
        A doubt counts as such a counter: the step is then held back."""
        try:
            from homeassistant.helpers import entity_registry as er
            entry = er.async_get(self._hass).async_get(entity_id)
            state = self._hass.states.get(entity_id)
        except Exception:  # noqa: BLE001 — no registry: no proof either
            return True
        if getattr(entry, "platform", None) in ("integration", DOMAIN):
            return True
        attrs = getattr(state, "attributes", None)
        return hasattr(attrs, "get") and any(
            attrs.get(key) for key in ("source", "source_entity"))

    def _solar_gap_wait_over(self, now: datetime) -> bool:
        """(#1187) Has SEM waited ``SOLAR_GAP_WAIT_S`` for a bound counter
        it cannot read? A gone counter must not hold the solar row for the
        rest of the day. The wait starts once HA runs: before that, every
        entity still loading has no state (bug class 86)."""
        from homeassistant.core import CoreState
        # ``is_running`` is true while Home Assistant is still starting too
        if getattr(self._hass, "state", None) is not CoreState.running:
            return False
        if self._solar_gap_wait_since is None:
            self._solar_gap_wait_since = now
        waited = (now - self._solar_gap_wait_since).total_seconds()
        return waited >= SOLAR_GAP_WAIT_S

    def _solar_gap(
        self, bl: Dict[str, Any], readings: Dict[str, float], now: datetime,
    ) -> Set[str]:
        """(#1187) The counters whose step since the last read spans a
        sunrise or a sunset that SEM did not watch.

        The sun gate (#681) judges a step by the sun at the moment it is
        read. One cycle is a few seconds, so that is the step's own hour. A
        step across an outage is not: HA down from 02:30 to 20:00 gave one
        step of 30.38 kWh, read after dark, and the whole day was dropped
        (12.10.2026, PROD). Read in daylight, the night's battery output in
        such a step was booked as solar.

        A step is such a gap when the last read is older than the
        integrator's own gap limit and a sunrise or sunset (``turn``, taken
        at that read) has passed since. Only counters read at that last
        cycle count; one dark since then is judged as before.
        """
        span = bl.get("span")
        if not isinstance(span, dict):
            return set()
        at, turn = _aware(span.get("at")), _aware(span.get("turn"))
        read = span.get("read")
        if at is None or turn is None or not isinstance(read, list):
            return set()
        if (now - at).total_seconds() <= MAX_INTEGRATION_GAP_SECONDS or now < turn:
            return set()
        return {
            entity_id for entity_id in readings
            if entity_id in read and entity_id in bl["last"]
            and entity_id in bl["base"]
        }

    def _hold_back_battery_output(
        self, bl: Dict[str, Any], readings: Dict[str, float],
        gap: Set[str], outs_now: Optional[Dict[str, float]],
    ) -> float:
        """(#1187) Credit a gap step less what could have moved it in the
        dark; return the part credited.

        In the dark a hybrid's counter moves only by what the battery puts
        out through the inverter (#681) and by grid power it passes to a car
        (#681's overnight charge). So the night part of the step is at most
        the batteries' output plus the grid import over the same span. That
        much stays out of the day: the bases move up by it, shared by each
        counter's step. Daytime discharge and import are held back too, so
        the day reads low, never high. No such counter and no battery:
        nothing is held back. All of the step is held back, as the sun gate
        did before, when nothing proves the bound: a battery with no
        discharge counter, a counter that went back, a set that changed, no
        reading before the gap, a counter HA computes, or a wait that ran
        out.
        """
        span = bl["span"]
        steps = {e: max(0.0, readings[e] - bl["last"][e]) for e in gap}
        total = sum(steps.values())
        if total <= 0:
            return 0.0
        before = span.get("outs")
        has_discharge = bool(self._meter_counter_entities.get("battery_discharge"))
        if outs_now is None:
            out = total   # the wait ran out: nothing proves the bound
        elif not has_discharge and self._battery_known():
            out = total
        elif not outs_now:
            out = 0.0
        elif (not isinstance(before, dict) or set(before) != set(outs_now)
              or any(not _finite(before[e]) or outs_now[e] < before[e] - 0.001
                     for e in outs_now)
              or any(self._counts_only_while_ha_runs(e) for e in outs_now)):
            out = total
        else:
            out = sum(outs_now[e] - before[e] for e in outs_now)
        held = min(total, max(0.0, out))
        for entity_id, step in steps.items():
            bl["base"][entity_id] += held * step / total
        _LOGGER.info(
            "Solar counter step since %s, with a sunrise or sunset SEM did "
            "not watch: %.2f kWh, %.2f kWh of it kept out as possible "
            "battery output or grid power (#1187)",
            span.get("at"), total, held,
        )
        return total - held

    def _note_solar_span(
        self, bl: Dict[str, Any], readings: Dict[str, float], now: datetime,
        outs_now: Optional[Dict[str, float]], row: float,
    ) -> None:
        """(#1187) Where the next step starts: when, the sun's next turn,
        what each bound counter read, the day's solar row, and which
        counters were read. A cycle that cannot read the discharge counters
        keeps the older outputs: a bound from further back is larger, never
        too small."""
        span = bl.get("span") if isinstance(bl.get("span"), dict) else {}
        outs = outs_now
        if outs is None:
            outs = span.get("outs")
        turn = self._sun_turn()
        bl["span"] = {
            "at": dt_util.as_utc(now).isoformat(),
            "turn": dt_util.as_utc(turn).isoformat() if turn else None,
            "outs": dict(outs) if isinstance(outs, dict) else None,
            "row": row,
            "read": sorted(readings),
        }

    def _reconcile_solar_energy(
        self, today: date, month_key: str, year_key: str,
        now: Optional[datetime] = None,
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
        - A STEP ACROSS AN OUTAGE IS JUDGED BY ITS SPAN (#1187), not by the
          sun at the read — see ``_solar_gap``. When a sunrise or sunset
          passed while SEM was down, the step is credited less what the
          batteries put out and the grid gave over it
          (``_hold_back_battery_output``).

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
            if value is not None and value >= 0:
                readings[entity_id] = value

        if not readings:
            return

        # (#1187) A step across an outage with a sunrise or sunset inside
        # needs the batteries' output and the grid import over the same span.
        # A bound counter not read yet (a restart brings entities up one by one):
        # wait, baselines untouched, and the row is not counter-backed, or
        # home would be balanced against meter rows that took the gap.
        now = dt_util.as_utc(now) if now else dt_util.utcnow()
        gap = self._solar_gap(bl, readings, now)
        outs_now = self._bound_reads()
        if gap and outs_now is None and not self._solar_gap_wait_over(now):
            return
        self._solar_gap_wait_since = None

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

        dark = self._sun_is_down()
        if dark and not gap:
            # Darkness: absorb the counter's movement into the baseline
            # instead of crediting it as production (#681). Rolling the
            # baseline forward also swallows a daily counter's midnight reset
            # for free — there is nothing to re-anchor because nothing was
            # adopted, and ``anchor`` stays unset until the first daylight
            # cycle, where it lands on the integrated value at sunrise.
            for entity_id, value in readings.items():
                bl["base"][entity_id] = value
                bl["last"][entity_id] = value
            self._note_solar_span(bl, readings, now, outs_now, integrated)
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
            gap = set()   # (#1187) nothing of the gap is known then
        elif gap:
            credited = self._hold_back_battery_output(bl, readings, gap, outs_now)
            # (#1187 review) The step runs from the last read: so does the
            # anchor. Set now, it would hold what the integrator added while
            # SEM waited for a counter, and the step holds that again. With
            # nothing credited the anchor is now, as before.
            row = bl["span"].get("row")
            if ("anchor" not in bl and credited > 0 and _finite(row)
                    and 0 <= row <= integrated):
                bl["anchor"] = row
        for entity_id, value in readings.items():
            if dark and entity_id not in gap:
                bl["base"][entity_id] = value   # (#681) as above
            else:
                bl["base"].setdefault(entity_id, value)
            bl["last"][entity_id] = value
        self._note_solar_span(bl, readings, now, outs_now, integrated)
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

        # Sanity cap — same physical bound the integrator uses
        # (``_daily_ceiling``, #1218).
        inverter_kwp = self.config.get("system_size_kwp", 10)
        if target > self._daily_ceiling("solar"):
            # (#1218) The row is the power sensor's, not the counter's.
            self._counter_backed.discard("solar")
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
          counter) → re-baseline; the accumulated value keeps. A drop within
          ``EV_COUNTER_DIP_KWH`` / ``EV_COUNTER_DIP_SHARE`` is a dip: the last
          reading holds (#1049).
        - ADOPTION IS UPWARD-ONLY while the counter set is partial, a counter
          does not read, or a counter's base is younger than the anchor:
          integration is then the floor, so a missing counter can never
          shrink the day. When every charger has its own counter and all of
          them read, the counters own the row in BOTH directions (#1049): a
          charger power sensor can read high — a Wallbox behind the MQTT
          bridge booked 19.56 kWh against 10.99 on its own meter — and
          upward-only kept every kWh of it. The row moves down only once every
          box has stopped and its counter has reported since
          (``_track_ev_pending``): a counter that reports late, or never,
          cannot pull the row down. The
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
        A third instance, one charger's own row, is ``follow_charger_counter``;
        all three share ``_ev_counter_target`` and ``_ev_adoption``.

        ``baselines`` is mutated IN PLACE (never rebound) so the caller's
        attribute keeps pointing at the live dict across a day rollover.
        """
        if not self._ev_counter_enabled or not self._hass:
            return

        daily_key = f"{category}_{day}"
        integrated = self._daily_accumulators.get(daily_key, 0.0)
        entities = self._ev_counter_entities
        target, all_read = self._ev_counter_target(
            baselines, str(day), entities, integrated,
            self._ev_counter_complete,
        )
        # (#1160) The row as this cycle leaves it, for the next day's anchor.
        baselines["row"] = integrated
        if target is None:
            return

        # Sanity cap — the fleet's own physical ceiling, from the configured
        # charger limits. Catches a counter in the wrong magnitude that
        # ``_energy_state_kwh`` could not classify from its unit string.
        max_daily = self._max_daily_ev_kwh()
        if target > max_daily:
            # (#1092-class) once per day per bucket — the sibling home/
            # solar ceiling check two screens down already debounces this
            # exact shape; this one warned every cycle until a unit
            # mismatch cleared.
            day_str = str(day)
            if self._ceiling_warned.get(category) != day_str:
                self._ceiling_warned[category] = day_str
                _LOGGER.warning(
                    "EV counter reconciliation target %.1f kWh exceeds the fleet's "
                    "%.0f kWh/day ceiling — ignoring this cycle (unit mismatch?)",
                    target, max_daily,
                )
            return

        owned = all_read and self._ev_counter_complete
        adopted = self._ev_adoption(
            category, target, integrated, owned, self._ev_settled(entities),
        )
        if adopted is None:
            return
        delta = adopted - integrated
        self._daily_accumulators[daily_key] = adopted
        baselines["row"] = adopted
        for accumulators, key in periods:
            # max(0.0) — a delta can be negative since #1049, and a longer
            # period must never be dragged below zero by one day's correction.
            accumulators[key] = max(0.0, accumulators.get(key, 0.0) + delta)

    def _ev_counter_target(
        self,
        bl: Dict[str, Any],
        day_str: str,
        entities: List[str],
        integrated: float,
        complete: bool,
    ) -> "tuple[Optional[float], bool]":
        """The day's kWh by the counters: ``anchor + Σ counter deltas``.

        Returns ``(target, all_read)``; ``target`` is None when no counter
        reads. ``all_read``: every counter read this cycle, and the anchor was
        set with this very set, complete, all reading — only then does the
        target cover everything the row holds. Mutates ``bl`` in place.
        """
        maps = [bl.get("base"), bl.get("last"), bl.get("owed", {}),
                bl.get("carried", {}), bl.get("drawn_at", {})]
        if (bl.get("date") != day_str
                or not all(isinstance(m, dict) for m in maps)
                or not all(_finite(v) for m in maps for v in m.values())
                or ("anchor" in bl and not _finite(bl["anchor"]))):
            # (#1161) The day that just closed, as its last cycle left it:
            # the new day's first anchor owes what it booked above its
            # counters (``_ev_carry_at_start``).
            closing = ({k: bl.get(k) for k in _EV_CLOSING_KEYS}
                       if _ev_day_after(bl.get("date"), day_str) else None)
            # Day rollover (or first run / legacy or damaged shape):
            # fresh baselines for the new day.
            bl.clear()
            bl.update({"date": day_str, "base": {}, "last": {}})
            if closing is not None:
                bl["closing"] = closing
        bl.pop("late", None)  # (#1161) a store from #1160
        readings: Dict[str, float] = {}
        for entity_id in entities:
            state = self._hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable", None):
                continue
            value = self._energy_state_kwh(state)  # #551 unit-aware
            if value is not None and value >= 0:
                value = self.ev_counter_judged_kwh(entity_id, value)  # (#1101)
                # (#1049) A dip that comes back holds the last reading — on a
                # fresh day too, where only the pending tracker remembers it.
                ref = bl["last"].get(entity_id,
                                     self._ev_counter_seen.get(entity_id))
                if _ev_counter_drop(value, ref) == "dip":
                    value = ref
                readings[entity_id] = value

        if not readings:
            return None, False

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
        not_drawn: Dict[str, float] = {}
        for entity_id, value in readings.items():
            prior = (bl["last"].get(entity_id)
                     if entity_id in bl["base"] else None)
            bl["base"].setdefault(entity_id, value)
            foreign = self._ev_counter_foreign.get(entity_id)
            if (foreign is not None and prior is not None
                    and prior <= foreign[0] + 0.001):
                # (#1101) This cycle's step stood for kWh no box drew in this
                # window (``_judge_ev_step``): the base moves with it, so the
                # row books none of it. ``prior`` past the step's start: this
                # row has taken the step already.
                not_drawn[entity_id] = min(foreign[1], max(0.0, value - prior))
                bl["base"][entity_id] += not_drawn[entity_id]
            bl["last"][entity_id] = value
        # The counters track charging SINCE their baselines; charging before
        # that (SEM down over the EV-day boundary, charger added late) is only
        # known to the integrator — anchor on the daily value at baseline time:
        # target = anchor + counter deltas.
        if "anchor" not in bl:
            bl["anchor"] = integrated
            # (#1161) The day's first anchor after a start the closing day
            # recorded: it owes the carry, which stands for ``pending``.
            closing = bl.pop("closing", None)
            carry = (self._ev_carry_at_start(closing, readings, integrated)
                     if "drawn_at" not in bl else None)
            # What each counter's boxes had drawn by now: the anchor holds
            # this cycle's draw, and all before it. Only a counter whose
            # boxes are read on their own (``_ev_counter_owes``).
            bl["drawn_at"] = {
                e: self._ev_counter_drawn_total.get(e, 0.0)
                for e in entities if self._ev_counter_owes(e)}
            # (#1049) The set the anchor was taken with — only if it was
            # complete and every counter read. A counter first seen later
            # starts its delta late; a counter set changed since (a restore
            # brings the old blob back) covers other boxes. Either way the
            # target misses kWh the row holds, so it may not pull it down.
            whole = complete and len(readings) == len(entities)
            bl["whole"] = sorted(entities) if whole else None
            # (#1049) What a box drew before the anchor and its counter has
            # not reported yet. That counter's next moves pay it first: it
            # belongs to the row before the anchor, not to this one. Only
            # where ``pending`` is what the counter's own boxes drew
            # (``_ev_counter_owes``, #1157 #1159).
            bl["owed"], bl["carried"] = (
                carry or (self._ev_owed_at_anchor(entities), {}))
        owed = bl.setdefault("owed", {})
        carried = bl.setdefault("carried", {})
        for entity_id, value in readings.items():
            if entity_id not in owed:
                continue
            # A counter can report a late session in several steps: what a
            # step books pays first, oldest first. (#1159) Then what a step
            # judged foreign took out of the row: nothing else did. Kept,
            # what was owed then took the next real charge that day.
            # (#1161) Whatever the box does: the counter decides the total.
            left = owed[entity_id]
            if left <= 0.001:  # paid, or a damaged store
                del owed[entity_id]
                continue
            paid = min(left, max(0.0, value - bl["base"][entity_id]))
            bl["base"][entity_id] += paid
            cut = paid + min(left - paid, not_drawn.get(entity_id, 0.0))
            owed[entity_id] = left - cut
            if entity_id in carried:
                # (#1161) What rolled in from the day before is paid first.
                carried[entity_id] = max(0.0, carried[entity_id] - cut)
            if owed[entity_id] <= 0.001:  # paid, or a damaged store
                del owed[entity_id]
        for entity_id in [e for e, v in carried.items()
                          if e not in owed or v <= 0.001]:
            del carried[entity_id]

        counter_daily = sum(
            value - bl["base"][entity_id]
            for entity_id, value in readings.items()
        )
        return (
            max(0.0, bl["anchor"] + counter_daily),
            len(readings) == len(entities)
            and bl.get("whole") == sorted(entities),
        )

    def _ev_carry_at_start(
        self, closing: Any, readings: Dict[str, float], anchor: float,
    ) -> Optional[Tuple[Dict[str, float], Dict[str, float]]]:
        """(#1161) What a new day's first anchor owes for the day that just
        closed: ``(owed, carried)``, per counter.

        The counter decides the total. While a car charges across the day's
        start, the closing row may stand above its counters: it shows the
        power read, and a row that moves up only, or one the counters own
        while a car charges, cannot move down. Each counter owes what SEM
        saw its boxes draw (``drawn_at``) above what it showed, from the
        closing day's anchor up to this one; no more in all than the two
        rows hold above the counters. The anchor holds the draw of the
        cycles since the closing day's last one, so a counter's move in
        them counts as shown. The new day's moves of that counter pay it,
        never below 0. So the days add up to the counter: a late report is
        booked once, and a power read above the meter stays on the day it
        was read and is taken off the next.

        What the closing day still owed rolls on once more (``carried``)
        and goes at the next start: a counter shows a late report within a
        day; a rest older than that was a power read the counter will never
        show, and it would hide real charging the counter shows later. None
        when the store does not say (from before #1161, SEM down a whole
        day, or damaged): the anchor owes ``pending`` as before.
        """
        if not isinstance(closing, dict):
            return None
        row, old_anchor = closing.get("row"), closing.get("anchor")
        maps = [closing.get(k) for k in ("base", "last", "drawn_at",
                                         "owed", "carried")]
        if not (_finite(row) and row >= 0.0 and _finite(old_anchor)
                and _finite(anchor)
                and all(isinstance(m, dict) for m in maps[:3])
                and all(m is None or isinstance(m, dict) for m in maps[3:])):
            return None
        base, last, drawn_at = maps[:3]
        owed, carried = maps[3] or {}, maps[4] or {}
        if not all(_finite(v) for m in (base, last, drawn_at, owed, carried)
                   for v in m.values()):
            return None
        shown: Dict[str, float] = {}
        for entity_id, start in base.items():
            now = last.get(entity_id, start)
            value = readings.get(entity_id)
            if value is not None and value >= now:
                # Its move since the closing day's last cycle, less what no
                # box drew (#1101). A counter that went back (a daily one
                # resets at midnight) shows what it showed then.
                foreign = self._ev_counter_foreign.get(entity_id)
                now = value - (foreign[1] if foreign is not None else 0.0)
            shown[entity_id] = max(0.0, now - start)
        held = max(0.0, row + max(0.0, anchor)
                   - max(0.0, old_anchor + sum(shown.values())))
        over = {e: max(0.0, self._ev_counter_drawn_total.get(e, 0.0) - v
                       - shown.get(e, 0.0))
                for e, v in drawn_at.items()}
        total = sum(over.values())
        share = 1.0 if total <= held else held / total
        roll = {e: max(0.0, v - max(0.0, carried.get(e, 0.0)))
                for e, v in owed.items()}
        new = {e: over.get(e, 0.0) * share + roll.get(e, 0.0)
               for e in set(over) | set(roll)}
        return ({e: v for e, v in new.items() if v > 0.001},
                {e: v for e, v in roll.items() if v > 0.001})

    def _ev_owed_at_anchor(self, entities: List[str]) -> Dict[str, float]:
        """(#1049 #1159) What each counter owes a row's new anchor: what its
        boxes drew since it last moved (``pending``). Only where that is the
        counter's own boxes' draw (``_ev_counter_owes``)."""
        return {e: v for e in entities if self._ev_counter_owes(e)
                and (v := self._ev_counter_pending.get(e, 0.0)) > 0.0}

    @staticmethod
    def _ev_adoption(
        label: str, target: float, integrated: float, owned: bool,
        settled: bool = False,
    ) -> Optional[float]:
        """The value an EV row takes from its counters, or None (#658, #1049).

        ``owned``: every charger has its own counter and all of them read, so
        the counters own the row: it follows them up as finely as a grid
        meter. Down only once ``settled`` — every box has stopped and its
        counter has reported since — because a counter can publish a value
        minutes old, and while a car charges the row may not fall under what
        the box really drew. Not owned: only a material shortfall is taken.
        """
        if owned and settled and integrated > target + METER_RECONCILIATION_THRESHOLD:
            adopted = target
        elif owned and target > integrated + METER_RECONCILIATION_THRESHOLD:
            adopted = target
        elif target > integrated + RECONCILIATION_THRESHOLD:
            adopted = target
        else:
            return None
        delta = adopted - integrated
        log = (
            _LOGGER.info
            if abs(delta) > RECONCILIATION_THRESHOLD
            else _LOGGER.debug
        )
        log(
            "%s energy reconciliation: counter=%.2f kWh vs integrated=%.2f kWh "
            "— adopting counter value (%+.2f kWh)",
            label, target, integrated, delta,
        )
        return adopted

    def _track_ev_pending(
        self, power: PowerReadings, interval_hours: float,
        now: Optional[datetime] = None,
    ) -> None:
        """(#1049) Per counter: the kWh its box charged since the counter moved.

        That energy is real but not in the counter yet — a cloud counter can
        report minutes or an hour late. While any is owed, or the box is
        charging, the counters may not pull a row down (``_ev_settled``).
        Each counter is charged with ITS box's power (bug class 3); standby
        draw is not charging (``EV_ACTIVE_CHARGE_FLOOR_W``, bug class 36).

        (#1101) …and the most its box could have drawn in time SEM did not
        see it idle (``_ev_counter_room``). A counter that moves by more than
        that stands for kWh no box drew since it last moved — a Wallbox
        register caught up 11.18 kWh in one report, on a box SEM had seen
        idle for six hours. From such a step only what SEM saw the box draw
        is booked (``_ev_counter_foreign``, read by ``_ev_counter_target``).
        What SEM saw drawn and the counter has not shown yet
        (``_ev_counter_unreported``) is part of the reach until the box has
        been seen idle for ``EV_COUNTER_LATE_REPORT_H``.

        (#1101) The same wait spends the unseen part of ``room``: once SEM
        has watched the box that long since it last could not see it, a
        counter has shown what the box drew then. Without it, every restart
        and dark read since the counter last moved stayed in ``room`` at
        44 kW: on a counter flat for a day, a 19.85 kWh catch-up at the next
        plug-in was booked. What SEM saw the box draw stays.

        (#1157) A counter no one box owns — a fallback (legacy daily sensor,
        Energy Dashboard) or one two chargers name — is checked the same way
        against every box it counts (``_ev_counter_boxes``): their draws add
        up, and its room grows as fast as all of them at once. Before, only a
        box's own counter was checked, so a fallback's jump was booked while
        every box read 0 W.

        (#1159) …and which counters read each of their boxes on its own
        power sensor this cycle (``_ev_counter_own_read``): only their
        ``pending`` may be owed at an anchor (``_ev_counter_owes``).

        (#1161) …and every kWh each counter's boxes drew
        (``_ev_counter_drawn_total``): a row reads what its day drew from
        it, to carry what its counter has not shown into the next day.
        """
        self._ev_owners_drawing = set()
        self._ev_counter_foreign = {}
        self._ev_counter_own_read = set()
        if not self._ev_counter_enabled or not self._hass:
            return
        now = now or dt_util.now()
        unseen_h = self._ev_unwatched_hours(now, interval_hours)
        self._ev_watched_at = now
        if unseen_h is None:
            # No record of the last cycle: nothing is known about the time
            # since, so every counter's next move is booked as it stands —
            # until SEM has watched its box for the late-report wait.
            self._ev_counter_room.clear()
            self._ev_counter_unseen_kwh.clear()
            self._ev_counter_quiet_h.clear()
        # More than a second unseen: SEM was down or skipped a cycle.
        gap = unseen_h is not None and unseen_h * 3600.0 > 1.0
        box_kw = self._ev_box_max_kw()
        per_charger = getattr(power, "ev_power_per_charger", None) or {}
        fleet_w = float(power.ev_power or 0.0)  # FLEET-READ: the fallback when a box's own draw is not known.
        for entity_id, boxes in self._ev_counter_boxes.items():
            # (#1157) A counter counts every box in ``boxes``: their draws
            # add up. When one box's own draw is not read (no list, an id-less
            # entry, no power sensor of its own), the counter is charged the
            # fleet's: that only ever holds a row higher.
            own = all(b in per_charger for b in boxes)
            if own:
                self._ev_counter_own_read.add(entity_id)  # (#1159)
            draws = ([float(per_charger.get(b) or 0.0) for b in boxes]
                     if own else [fleet_w])
            # A box that reads below zero (a sign-flipped sensor) does not
            # cancel another box's charge.
            watts = sum(max(0.0, w) for w in draws)
            # Standby is not charging (bug class 36), box by box.
            charging_w = sum(w for w in draws if w > EV_ACTIVE_CHARGE_FLOOR_W)
            if own:
                self._ev_owners_drawing.update(
                    b for b, w in zip(boxes, draws, strict=True)
                    if w > EV_ACTIVE_CHARGE_FLOOR_W)
            elif charging_w > 0.0:
                self._ev_owners_drawing.update(boxes)
            state = self._hass.states.get(entity_id)
            value = None
            if state is not None and state.state not in (
                    "unknown", "unavailable", None):
                value = self._energy_state_kwh(state)
            seen = self._ev_counter_seen.get(entity_id)
            room = self._ev_counter_room.get(entity_id)
            unseen = self._ev_counter_unseen_kwh.get(entity_id, 0.0)
            # As much as every box it counts could draw at once.
            reach_kw = box_kw * len(boxes)
            if room is not None and gap:
                room += reach_kw * unseen_h
                unseen += reach_kw * unseen_h
            this_cycle = max(reach_kw, watts / 1000.0) * interval_hours
            drawn = charging_w * interval_hours / 1000.0
            if drawn > 0.0 and self._ev_counter_owes(entity_id):  # (#1161)
                self._ev_counter_drawn_total[entity_id] = (
                    self._ev_counter_drawn_total.get(entity_id, 0.0) + drawn)
            live = self._ev_box_power_live(boxes, power, per_charger)
            unreported = self._ev_counter_unreported.get(entity_id, 0.0)
            moved = (value is not None and seen is not None
                     and value > seen + 0.001)
            if value is not None and value >= 0 and (
                seen is None
                or moved
                or _ev_counter_drop(value, seen) == "reset"
            ):
                if moved:
                    step = value - seen
                    if room is not None:
                        # What SEM saw drawn and not yet shown may come in
                        # this step too, whenever the box drew it.
                        step -= self._judge_ev_step(
                            entity_id, boxes, seen, value,
                            room + this_cycle + unreported,
                            unreported + max(0.0, watts) * interval_hours / 1000.0,
                            now)
                    unreported = max(0.0, unreported + drawn - step)
                # Moved, reset, or first seen: it holds everything so far.
                self._ev_counter_seen[entity_id] = value
                self._ev_counter_pending[entity_id] = 0.0
                if seen is not None:
                    # A real move starts the watch; a first sight (a store
                    # from before it) leaves the next move as it stands,
                    # unless the late-report wait starts the watch first.
                    room = unseen = 0.0
            else:
                if charging_w > 0.0:
                    self._ev_counter_pending[entity_id] = (
                        self._ev_counter_pending.get(entity_id, 0.0)
                        + drawn
                    )
                unreported += drawn
                # Charging, or a power read that cannot say "idle": the box
                # may have drawn its most. Seen idle: at most a trickle.
                if room is not None and (charging_w > 0.0 or not live):
                    room += this_cycle
                    if not live:
                        unseen += this_cycle
                elif room is not None:
                    room += (EV_COUNTER_TRICKLE_FACTOR * max(0.0, watts)
                             * interval_hours / 1000.0)
            # (#1101) Watched for the late-report wait since SEM last could
            # not see the box: a counter has shown by now what the box drew
            # then, so the unseen part of ``room`` is spent. What SEM saw —
            # a charge, a trickle — stays, and never less than the draw it
            # saw since the counter last moved (``pending``: a record that
            # holds none, or an older store). Unseen time starts the wait
            # again. No record yet: the watch starts.
            quiet_h = self._ev_counter_quiet_h.get(entity_id, 0.0)
            if not live or gap:
                quiet_h = 0.0
            else:
                if quiet_h < EV_COUNTER_LATE_REPORT_H <= quiet_h + interval_hours:
                    room = max(self._ev_counter_pending.get(entity_id, 0.0),
                               (0.0 if room is None else room) - unseen)
                    unseen = 0.0
                quiet_h += interval_hours
            self._ev_counter_quiet_h[entity_id] = quiet_h
            if unseen > 0.0:
                self._ev_counter_unseen_kwh[entity_id] = unseen
            else:
                self._ev_counter_unseen_kwh.pop(entity_id, None)
            if room is not None:
                self._ev_counter_room[entity_id] = room
            # Seen idle long enough: a counter that has not shown the rest by
            # now never will — what is left was a power read above the meter.
            # A dark read or a skipped cycle pauses the count; only charging
            # starts it again.
            idle_h = self._ev_counter_idle_h.get(entity_id, 0.0)
            if charging_w > 0.0:
                idle_h = 0.0
            elif live and not gap:
                idle_h += interval_hours
            self._ev_counter_idle_h[entity_id] = idle_h
            if idle_h >= EV_COUNTER_LATE_REPORT_H:
                unreported = 0.0
            if unreported > 0.0:
                self._ev_counter_unreported[entity_id] = unreported
            else:
                self._ev_counter_unreported.pop(entity_id, None)

    def _judge_ev_step(
        self, entity_id: str, boxes: Tuple[str, ...], before: float,
        value: float, room: float, seen_kwh: float, now: datetime,
    ) -> float:
        """(#1101) Book from a counter step no more than its box could draw.

        ``room``: the most the box could have drawn since the counter last
        moved, unseen by SEM, plus what SEM saw it draw that the counter has
        not shown yet. A step above it (and the dip window) is the counter
        reporting kWh no box drew; only ``seen_kwh`` — what SEM saw the box
        draw and the counter has not shown — is booked from it. Returns the
        kWh not booked.
        """
        step = value - before
        if step <= room + EV_COUNTER_DIP_KWH:
            return 0.0
        foreign = step - seen_kwh
        if foreign <= 0.001:
            return 0.0
        self._ev_counter_foreign[entity_id] = (before, foreign)
        # Once a day per counter: a counter in the wrong unit would say it
        # every cycle.
        log_on_change(
            _LOGGER, f"ev-step:{entity_id}:{now.date()}", logging.WARNING,
            "EV counter %s rose %.2f kWh at once, but %s %s could have "
            "drawn at most %.2f kWh since it last moved — %.2f kWh not booked "
            "(the counter caught up on energy from outside this window)",
            entity_id, step, "charger" if len(boxes) == 1 else "chargers",
            ", ".join(boxes), room, foreign,
        )
        return foreign

    def ev_counter_judged_kwh(
        self, entity_id: Optional[str], value: Optional[float],
    ) -> Optional[float]:
        """(#1101) A tracked counter's reading as far as the step check has
        seen it. A rise it has not judged yet (``calculate_energy`` skipped
        this cycle) waits for the next cycle: booked now, a row could not
        take a judged step back out of it."""
        if (value is None or not self._ev_counter_enabled
                or entity_id not in self._ev_counter_boxes):
            return value
        seen = self._ev_counter_seen.get(entity_id)
        return seen if seen is not None and value > seen + 0.001 else value

    def ev_counter_step_not_drawn(
        self, entity_id: Optional[str],
    ) -> Optional[Tuple[float, float]]:
        """(#1101) This cycle's judged step of ``entity_id``, for readers of
        the same counter outside this class (a session's total): the reading
        before the step and the kWh of it no box drew. None: nothing judged."""
        return self._ev_counter_foreign.get(entity_id) if entity_id else None

    def _ev_unwatched_hours(
        self, now: datetime, interval_hours: float,
    ) -> Optional[float]:
        """(#1101) Hours since the last tracked cycle that this cycle's
        interval does not cover — SEM down, or a skipped cycle. None when
        there is no last cycle to measure from."""
        if self._ev_watched_at is None:
            return None
        try:
            elapsed_h = (now - self._ev_watched_at).total_seconds() / 3600.0
        except TypeError:  # a naive stored time against an aware clock
            return None
        return max(0.0, elapsed_h - interval_hours)

    def _ev_box_max_kw(self) -> float:
        """(#1101) The most one box can draw, in kW — see
        ``EV_COUNTER_BOX_MAX_KW``. One box's share of ``_max_daily_ev_kwh``
        when the boxes are set up larger."""
        chargers = self.config.get("ev_chargers") or []
        configured = self._max_daily_ev_kwh() / max(1, len(chargers)) / 24.0
        return max(EV_COUNTER_BOX_MAX_KW, configured)

    def _ev_box_power_live(
        self, boxes: Tuple[str, ...], power: PowerReadings,
        per_charger: Dict[str, float],
    ) -> bool:
        """(#1101) Did this cycle read each box's OWN power sensor as a
        number? Only then does a read under the floor say the boxes are idle:
        a dark sensor reads 0 W, and so does the fleet's sum for a box that is
        not in it. The one fleet sensor counts for a counter of one box, when
        that is the one counter SEM tracks or the one box with a counter of
        its own (#1101). Never for several boxes (#1157): the Energy
        Dashboard's sensor is its first EV device, and a top-level one may
        be the primary's, so it cannot say the others are idle."""
        lone_owner = tuple(self._ev_counter_owner.values())
        if boxes and all(b in per_charger for b in boxes):
            sensors: Dict[str, Any] = {}
            for c in self.config.get("ev_chargers") or []:
                if isinstance(c, dict):
                    sensors.setdefault(c.get("id"),
                                       c.get("ev_charging_power_sensor"))
            entities = [sensors.get(b) for b in boxes]
        elif not per_charger and len(boxes) == 1 and (
                len(self._ev_counter_boxes) == 1 or boxes == lone_owner):
            entities = [getattr(power, "ev_power_fleet_entity", None)]
        else:
            return False
        return all(entity and self._power_state_live(entity)
                   for entity in entities)

    def _power_state_live(self, entity: str) -> bool:
        """(#1101) The power sensor reads a number."""
        state = self._hass.states.get(entity)
        if state is None or state.state in ("unknown", "unavailable", None, ""):
            return False
        try:
            return math.isfinite(float(state.state))
        except (TypeError, ValueError):
            return False

    def _ev_settled(self, entities: List[str]) -> bool:
        """(#1049) Every box behind these counters has stopped charging, and
        each counter has reported since — nothing it counts is still owed."""
        return not any(
            self._ev_counter_pending.get(e, 0.0) > 0.0
            or any(b in self._ev_owners_drawing
                   for b in self._ev_counter_boxes.get(e, ()))
            for e in entities
        )

    def _ev_counter_owes(self, entity_id: str) -> bool:
        """(#1159) Is this counter's ``pending`` what its own boxes drew, so a
        row may owe it at an anchor? Its boxes must be known: not the whole
        fleet given as a guess (``guessed``). Each box must have been read on
        its own power sensor (``_ev_counter_own_read``); else ``pending``
        holds the fleet's draw (``_track_ev_pending``), which counts other
        boxes and not this one. On a home with one box the fleet read is
        that box's draw."""
        boxes = self._ev_counter_boxes.get(entity_id, ())
        if not boxes or entity_id in self._ev_counter_guessed:
            return False
        if entity_id in self._ev_counter_own_read:
            return True
        chargers = [c for c in self.config.get("ev_chargers") or []
                    if isinstance(c, dict)]
        return len(chargers) <= 1  # one box: the fleet read is its draw

    def follow_charger_counter(
        self,
        cid: str,
        day: str,
        value: float,
        counter: Optional[str],
    ) -> float:
        """(#1049) One charger's daily kWh, held to its OWN counter.

        The fleet rows follow the counters (``_reconcile_ev_bucket``); the
        per-charger rows the coordinator integrates must follow them too, or
        the members would sum above a fleet row that moved down and the
        per-charger card would keep the high read. Same model, one member,
        and only while the fleet's set is complete — on a partial fleet the
        fleet row stays upward-only, and members held to counters alone could
        then sum above it. ``counter`` must be this charger's alone.
        Returns the row's new value; ``value`` when there is nothing to follow.
        """
        if (not self._ev_counter_enabled or not self._hass or not counter
                or not self._ev_counter_complete):
            return value
        bl = self._charger_counter_baselines.setdefault(cid, {})
        if bl.get("counter") != counter:
            # Another counter: its deltas start now, on the row as it stands.
            # Kept, the old anchor would meet the new counter's zero delta and
            # pull the day's earlier charging out of the row.
            bl.clear()
        target, all_read = self._ev_counter_target(
            bl, day, [counter], value, True)
        bl["counter"] = counter
        chargers = self.config.get("ev_chargers") or []
        one_box = self._max_daily_ev_kwh() / max(1, len(chargers))
        adopted = None
        if target is not None and target <= one_box:
            adopted = self._ev_adoption(
                f"charger {cid}", target, value, all_read,
                self._ev_settled([counter]),
            )
        row = value if adopted is None else adopted
        # (#1160) The row as this cycle leaves it, for the next day's anchor.
        bl["row"] = row
        return row

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
                "unreadable or above the day's ceiling; the daily row runs on "
                "power integration alone until it returns", category,
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

        - **BIDIRECTIONAL.** Solar adopts upward only: on a hybrid its counter
          measures AC yield and trails PV production all day (bug class 28).
          A grid meter can prove the integrator counted energy that never
          flowed (#628: export integrated 3.06 kWh against a meter reading
          0.16), so a downward correction has to be legal. EV joined this side
          in #1049, once each box has stopped and its counter reported — see
          ``_ev_adoption``. Safe because every daily
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

        Cost accumulators move with the delta at today's REALIZED average
        rate — ``daily_cost / daily_energy`` for the same category — because
        the drift accumulated across the day, not at the moment it was
        noticed (#795, #416's class). A day with no accumulation yet has no
        realized average and falls back to the instantaneous rate passed in.
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
            if value is not None and value >= 0:
                readings[entity_id] = value

        if len(readings) != len(entities):
            # Partial read — see ALL-OR-NOTHING above. Do NOT touch the
            # baselines: the missing counter kept counting while it was
            # unavailable, and its delta is still owed once it returns.
            self._tally_backing(category, today_str, backed=False)
            return

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
            bl.pop("beside_mark", None)
        for entity_id, value in readings.items():
            bl["base"].setdefault(entity_id, value)
            bl["last"][entity_id] = value
        bl.setdefault("anchor", integrated)
        # (#1191 review) where the beside rows stood when the anchor was set:
        # the first correction is split as what came after it
        if _ROWS_BESIDE.get(category) and not isinstance(bl.get("beside_mark"), dict):
            bl["beside_mark"] = {"row": integrated, "parts": {
                beside: self._daily_accumulators.get(f"{beside}_{today}", 0.0)
                for beside in _ROWS_BESIDE[category]}}

        counter_daily = sum(
            value - bl["base"][entity_id] for entity_id, value in readings.items()
        )
        target = max(0.0, bl["anchor"] + counter_daily)

        # (#1218) The row's own ceiling, the one its cap below holds the day
        # to. Adopted, a target above it moved the month, year and lifetime;
        # the cap then wrote back only the day, and the next cycle added the
        # same step again — and its cost, at a rate the step itself raised.
        ceiling = self._daily_ceiling(category)
        if target > ceiling:
            if self._ceiling_warned.get(category) != today_str:
                self._ceiling_warned[category] = today_str
                _LOGGER.warning(
                    "%s counter reconciliation target %.1f kWh exceeds the "
                    "%.0f kWh/day sanity ceiling — ignoring the counter "
                    "until it is back below (unit mismatch?)",
                    category, target, ceiling,
                )
            # The row is the power sensor's now, not the counter's: the home
            # balance may not build on it.
            self._tally_backing(category, today_str, backed=False)
            return

        # (#628) Complete read — this category's daily row is the hardware's
        # this cycle, so the home balance may build on it.
        self._counter_backed.add(category)
        self._tally_backing(category, today_str, backed=True)

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
        # (#1191 review) A row booked beside this one keeps its share: the
        # flows give the split, the meter the size. Left as integrated, a
        # meter 10 % ahead of a big sale put the gap on solar's export. The
        # correction is split as what was added since the last one was —
        # the morning's sale is not moved by an afternoon's drift.
        mark = bl.get("beside_mark")
        if not isinstance(mark, dict):
            mark = {"row": 0.0, "parts": {}}
        added = integrated - float(mark.get("row") or 0.0)
        parts = {}
        for beside in _ROWS_BESIDE.get(category, ()):
            part = self._daily_accumulators.get(f"{beside}_{today}", 0.0)
            before = float((mark.get("parts") or {}).get(beside) or 0.0)
            share = (min(1.0, max(0.0, (part - before) / added))
                     if added > 0 else 0.0)
            moved = max(-part, min(target - part, delta * share))
            parts[beside] = part + moved
            if not moved:
                continue
            self._daily_accumulators[f"{beside}_{today}"] = part + moved
            for accumulators, key in (
                (self._monthly_accumulators, f"{beside}_{month_key}"),
                (self._yearly_accumulators, f"{beside}_{year_key}"),
                (self._lifetime_accumulators, f"lifetime_{beside}"),
            ):
                accumulators[key] = max(0.0, accumulators.get(key, 0.0) + moved)
        if parts:
            bl["beside_mark"] = {"row": target, "parts": parts}

        if cost_key and rate:
            # (#795) The drift happened across the day; price it at the
            # day's realized average — the mean of what the live path
            # actually booked — not the tariff of this instant. ``integrated``
            # still holds the pre-adoption energy, so the pair matches the
            # pre-correction cost. This also keeps #770's contract at the
            # battery site: the day's realized savings rate IS how the live
            # path valued the day, averaged. Downward corrections give back
            # what was booked, not what a removal costs right now.
            daily_cost = self._daily_cost_accumulators.get(
                f"{cost_key}_{today}", 0.0
            )
            booked = integrated
            if cost_key == "cost_import":
                # (#1228) the house's own average: the kWh an own-tariff
                # device took are at its price, and the counters' extra
                # import is the house's unless a device meter claims it
                taken, taken_cost = self._device_taken(today)
                booked -= taken
                daily_cost -= taken_cost
            if booked > 0.05 and daily_cost > 0:
                rate = daily_cost / booked
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

        # (#1228) the home row is the counters' balance this cycle
        self._counter_backed.add("home")
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

    def _daily_ceiling(self, category: str) -> float:
        """(#1218) The most one day's row of ``category`` may hold.

        One figure for both places that judge it: the cap at the end of
        ``calculate_energy`` and the counter corrections before it. The cap
        writes the day alone; a correction moves the month, year and lifetime
        with it. A correction may therefore never adopt what the cap would
        cut. EV has its own (``_max_daily_ev_kwh``).
        """
        if category in ("battery_charge", "battery_discharge"):
            # 3 full cycles/day is generous limit
            return self.config.get("battery_capacity_kwh", 15) * 3
        if category == "solar":
            # 16 peak sun hours is extreme max
            return self.config.get("system_size_kwp", 10) * 16
        return MAX_PLAUSIBLE_DAILY_KWH

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

        # (#1077) The value layer's books — 0 until a value field is set.
        costs.daily_self_consumption_value = self._get_daily_cost(VALUE_SELF_CONSUMPTION, today)
        costs.yearly_self_consumption_value = self._get_yearly_cost(VALUE_SELF_CONSUMPTION, year_key)
        costs.daily_export_value = self._get_daily_cost(VALUE_EXPORT, today)
        costs.yearly_export_value = self._get_yearly_cost(VALUE_EXPORT, year_key)
        costs.daily_feed_in_fees = self._get_daily_cost(VALUE_FEED_IN_FEE, today)
        costs.yearly_feed_in_fees = self._get_yearly_cost(VALUE_FEED_IN_FEE, year_key)

        # Environmental impact (CO2 avoided by self-consuming solar).
        # (#1191) Only solar's part of the export was ever in the solar total;
        # a battery sale is taken out of the export first.
        daily_self_consumed = max(0, energy.daily_solar - solar_export(
            energy.daily_grid_export, energy.daily_grid_export_battery))
        yearly_self_consumed = max(0, energy.yearly_solar - solar_export(
            energy.yearly_grid_export, energy.yearly_grid_export_battery))
        lifetime_solar = self._get_lifetime("solar")
        lifetime_export = self._get_lifetime("grid_export")
        lifetime_self_consumed = max(0, lifetime_solar - solar_export(
            lifetime_export, self._get_lifetime(GRID_EXPORT_BATTERY_CATEGORY)))

        # (#1088) + the live-intensity correction (0 while the flag is off
        # and before it ever ran). Never below 0: CO2 avoided is a saving.
        daily_co2 = max(0.0, daily_self_consumed * GRID_CO2_KG_PER_KWH
            + self._co2_correction("daily", today))
        costs.daily_co2_avoided_kg = round(daily_co2, 2)
        # (#1221) The two numbers behind it, for the Energy Impact card: the
        # kWh it counts and the kg per kWh it used today (the day's average
        # once the live value counts), at the precision the card shows. While
        # the kWh still shows 0.0, an average says nothing: the rate now.
        costs.daily_co2_solar_used_kwh = round(daily_self_consumed, 1)
        costs.daily_co2_kg_per_kwh = round(
            daily_co2 / daily_self_consumed if costs.daily_co2_solar_used_kwh > 0
            else self.grid_co2_kg_now(), 3)
        costs.yearly_co2_avoided_kg = round(max(0.0, yearly_self_consumed * GRID_CO2_KG_PER_KWH
            + self._co2_correction("yearly", year_key)), 1)
        costs.yearly_trees_equivalent = round(
            costs.yearly_co2_avoided_kg / CO2_KG_PER_TREE_PER_YEAR, 1
        )
        costs.lifetime_co2_avoided_kg = round(max(0.0, lifetime_self_consumed * GRID_CO2_KG_PER_KWH
            + self._co2_correction("lifetime", None)), 1)
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
            # Auto-detected from recorder statistics (first solar energy entry).
            # (#796) The fallback means "installed January 1 of THIS year" —
            # a guess, not a measurement. The figures still compute (a
            # degraded answer beats none, and detection retries every cycle
            # while undetected), but they carry the flag so the sensors can
            # say so instead of presenting a guessed date as fact.
            costs.roi_install_date_estimated = self._install_year_decimal is None
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

        # Self consumption rate = (solar - solar's export) / solar; whatever
        # solar didn't send to the grid was consumed locally (by home,
        # battery, or EV). (#1191) So the battery's part of the export (a
        # sale) is the pack's, not solar's: taken away with it, a sunless
        # morning's sale read below 0 %, the clamp held 0 % and the health
        # check fired.
        if energy.daily_solar > 0:
            solar_used = energy.daily_solar - solar_export(
                energy.daily_grid_export, energy.daily_grid_export_battery)
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

    def daily_total_consumption(self, today: date) -> float:
        """(#825) Everything the house drew today, INCLUDING the car.

        This is the figure HA's Energy Dashboard calls "Home".
        ``daily_home`` deliberately means something else — the house
        WITHOUT the EV — and publishing only that left users comparing
        two different questions and reading the difference as a bug
        (#802, and a month of #628).

        The EV term is the CALENDAR-DAY mirror on purpose:
        ``EV_CATEGORY`` rolls at the charge deadline (#279), and
        composing a midnight row out of a deadline row is the bug class
        closed in #703/#704.
        """
        return round(
            self._daily_accumulators.get(f"home_{today}", 0.0)
            + self._daily_accumulators.get(
                f"{MIDNIGHT_EV_CATEGORY}_{today}", 0.0),
            2,
        )

    def ev_day_flows(self) -> Optional[Tuple[float, float, float]]:
        """(#1046) kWh the flows sent to the car this EV day — solar, grid,
        battery — on the day key ``daily_ev`` was last read from, so the two
        never straddle a rollover. None on the EV day the rows were first
        booked on: it began before them, so they are short."""
        ev_day = getattr(self, "_daily_ev_day", None)
        if ev_day is None:
            ev_day = self._ev_reset_day(dt_util.now())
        since = getattr(self, "_ev_flow_since", None)
        if since is None or ev_day <= since:
            return None
        return tuple(
            self._daily_accumulators.get(f"{category}_{ev_day}", 0.0)
            for _, category in EV_DAY_FLOW_CATEGORIES
        )

    def _note_ev_rollover(self, ev_day: date) -> None:
        """(#1176) Record the moment ``daily_ev`` moves to a new car day —
        whatever rolled it: the Charge-by time, sunrise, a changed setting,
        a restart across the boundary. It falls to 0 right then."""
        seen = getattr(self, "_ev_seen_day", None)
        if seen is not None and ev_day != seen:
            self._ev_rolled_at = dt_util.now()
        self._ev_seen_day = ev_day

    def ev_last_reset(self) -> Optional[datetime]:
        """(#1176) When ``daily_ev`` last fell to 0: the car-day sensor's
        ``last_reset``. None until the first rollover this code saw — the
        sensor then keeps midnight, as before. Moving it mid-day on the
        upgrade would make the recorder count the day's kWh again."""
        return getattr(self, "_ev_rolled_at", None)

    def _get_daily(self, category: str, today: date) -> float:
        """Get daily accumulated energy."""
        key = f"{category}_{today}"
        return round(self._daily_accumulators.get(key, 0.0), 2)

    def _get_monthly(self, category: str, month_key: str) -> float:
        """Get monthly accumulated energy."""
        key = f"{category}_{month_key}"
        return round(self._monthly_accumulators.get(key, 0.0), 2)

    def monthly_total_for(self, category: str, day) -> float:
        """(#867) Accumulated ``category`` energy for the month containing
        ``day`` — the public way to ask about a month that is not today's.

        The rollover sweep deliberately keeps the PREVIOUS month's keys, so
        the month that just ended is still readable for the first days of the
        new one. That is the window the degradation recorder runs in.
        """
        return self._get_monthly(category, self._month_key(day))

    def _get_yearly(self, category: str, year_key: str) -> float:
        """Get yearly accumulated energy."""
        key = f"{category}_{year_key}"
        return round(self._yearly_accumulators.get(key, 0.0), 2)

    def set_value_rates(self, tariff: Any) -> None:
        """(#1077) This cycle's value-layer numbers, from the tariff
        snapshot. Anything unreadable switches the books off for the cycle
        rather than booking a guess."""
        try:
            self._value_layer_on = getattr(tariff, "value_layer_on", False) is True
            spot = getattr(tariff, "current_export_spot_rate", None)
            self._export_spot_rate = None if spot is None else float(spot)
            self._feed_in_fee_rate = float(getattr(tariff, "feed_in_fee_rate", 0.0) or 0.0)
            self._feed_in_fixed_monthly = float(
                getattr(tariff, "feed_in_fixed_monthly", 0.0) or 0.0)
        except (TypeError, ValueError):
            self._value_layer_on = False

    def export_year_to_date_kwh(self, now: Optional[datetime] = None) -> float:
        """(#1077) kWh exported this calendar year (local time).

        The yearly export accumulator: persisted with the others in SEM's
        store, seeded from the recorder for a mid-year install, and keyed by
        the year — so on 1 January it reads 0 without a reset of its own.
        """
        now = now or dt_util.now()
        return self._get_yearly("grid_export", str(now.year))

    def set_grid_co2_intensity(self, kg_per_kwh: Optional[float], live: bool) -> None:
        """(#1088) This cycle's grid CO2 intensity (kg/kWh; None = no usable
        reading) and whether the soak flag lets it count."""
        self._grid_co2_kg = kg_per_kwh
        self._co2_live = bool(live)

    def grid_co2_kg_now(self) -> float:
        """(#1088) The kg/kWh a grid kWh counts at right now: the live
        intensity when the soak flag lets it count and a reading exists,
        else the fixed Swiss average — one rule for every CO2 number."""
        if self._co2_live and self._grid_co2_kg is not None:
            return float(self._grid_co2_kg)
        return GRID_CO2_KG_PER_KWH

    def _co2_correction(self, period: str, key) -> float:
        """(#1088) The accumulated live-intensity correction, unrounded."""
        c = CO2_CORRECTION_CATEGORY
        if period == "daily":
            return self._daily_accumulators.get(f"{c}_{key}", 0.0)
        if period == "yearly":
            return self._yearly_accumulators.get(f"{c}_{key}", 0.0)
        return self._lifetime_accumulators.get(f"lifetime_{c}", 0.0)

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

    def set_device_tariff_cycle(self, entries) -> None:
        """(#812) The own-tariff devices of THIS cycle (``DeviceCycle``),
        staged by the coordinator before ``calculate_energy`` books it."""
        self._device_tariff_cycle = list(entries or ())

    def _import_cost(self, import_kwh: float, interval_hours: float,
                     power, power_flows, today: date,
                     month_key: str, year_key: str) -> float:
        """(#812) The money of THIS cycle's import, split where it is booked.

        Each own-tariff device's use this cycle — its own meter's step, else
        its draw × the cycle time — times the grid's share of the house this
        cycle is its grid kWh: the rest of what it used came from the sun or
        the pack. When the devices' grid kWh add up to more than this
        cycle's import, they share the import in proportion (order does not
        matter). The rest of the import is the house's, at the house rate.

        One booking, one total: nothing is moved later, nothing waits for a
        later cycle, a device kWh is never counted twice. A meter baseline is
        written back HERE, where its step is booked: a cycle that returns
        early leaves the step for the next one.

        (#1228) Not a meter step over more time than a cycle: SEM down, a
        skipped cycle, a meter dark for minutes. This cycle's import and
        share say nothing of that time, so the step is held and booked
        against the house rows over the same time (``_settle_meter_gaps``).
        """
        from .device_tariff import grid_share
        house_rate = float(self._import_rate or 0.0)
        entries, self._device_tariff_cycle = self._device_tariff_cycle, []
        left = max(0.0, float(import_kwh or 0.0))
        share = grid_share(getattr(power_flows, "grid_to_home", 0.0),
                           getattr(power, "home_consumption_power", 0.0))
        wants = []
        self._meter_staged = {e.device_id for e in entries if e.meter}
        for e in entries:
            held = False
            if e.meter and e.baseline is not None:
                held = self._hold_meter_gap(e)
                self.device_meter_last[e.device_id] = dict(e.baseline)
                self._meter_written.add(e.device_id)
            if e.meter:
                used = 0.0 if held else max(0.0, e.meter_kwh)
            else:
                used = max(0.0, e.power_w) * interval_hours / 1000.0
            wants.append(used * share)
        total = sum(wants)
        scale = min(1.0, left / total) if total > 0 else 0.0
        cost = 0.0
        for e, want in zip(entries, wants, strict=True):
            kwh = want * scale
            if kwh <= 0:
                continue
            price = house_rate if e.price is None else float(e.price)
            self._accumulate(f"{DEVICE_TARIFF_KWH}{e.device_id}", today,
                             month_key, year_key, kwh)
            self._accumulate_cost(f"{DEVICE_TARIFF_COST}{e.device_id}", today,
                                  month_key, year_key, kwh * price)
            cost += kwh * price
            left -= kwh
        return cost + max(0.0, left) * house_rate

    def _hold_meter_gap(self, entry) -> bool:
        """(#1228) Hold a meter step that covers more than one cycle.

        True when the step since the device's last booked read spans more
        than ``MAX_INTEGRATION_GAP_SECONDS`` — the limit the integrator
        skips a cycle at. The step waits in ``device_meter_gaps`` with the
        house rows stamped on that read. A second such step before the
        first is settled joins it: one span, from the older start.
        """
        step = max(0.0, float(entry.meter_kwh or 0.0))
        last = self.device_meter_last.get(entry.device_id)
        if step <= 0.0 or not isinstance(last, dict):
            return False
        try:
            span_s = (datetime.fromisoformat(str(entry.baseline["at"]))
                      - datetime.fromisoformat(str(last["at"]))).total_seconds()
        except (KeyError, TypeError, ValueError):
            return False
        if span_s <= MAX_INTEGRATION_GAP_SECONDS:
            return False
        gap = self.device_meter_gaps.get(entry.device_id)
        if isinstance(gap, dict) and _finite(gap.get("kwh")):
            gap["kwh"] = float(gap["kwh"]) + step
            gap["price"] = entry.price
            gap.pop("wait", None)
        else:
            self.device_meter_gaps[entry.device_id] = {
                "kwh": step, "since": str(last["at"]),
                "rows": last.get("rows"), "price": entry.price}
        return True

    def _device_taken(self, today: date) -> Tuple[float, float]:
        """(#1228) The grid kWh and their cost own-tariff devices took of
        the day's import."""
        suffix = f"_{today}"
        return (
            sum(v for k, v in self._daily_accumulators.items()
                if k.startswith(DEVICE_TARIFF_KWH) and k.endswith(suffix)),
            sum(v for k, v in self._daily_cost_accumulators.items()
                if k.startswith(DEVICE_TARIFF_COST) and k.endswith(suffix)),
        )

    def _meter_rows(self, today: date) -> Dict[str, Any]:
        """(#1228) The house rows a meter step's span is read against: the
        day's grid import and its cost, what the house, the batteries and
        the car used, and what own-tariff devices already took of the
        import. With the time this run has integrated."""
        suffix = f"_{today}"
        rows = self._daily_accumulators
        taken, taken_cost = self._device_taken(today)
        return {
            "day": str(today),
            "import": rows.get(f"grid_import{suffix}", 0.0),
            "cost": self._daily_cost_accumulators.get(f"cost_import{suffix}", 0.0),
            "used": sum(rows.get(f"{c}{suffix}", 0.0) for c in (
                "home", "battery_charge", MIDNIGHT_EV_CATEGORY)),
            "taken": taken, "taken_cost": taken_cost,
            "seen": self._seen_s, "run": self._run_token,
            "rise": self._dark_rise(),
        }

    def _settle_meter_gaps(self, today: date, month_key: str, year_key: str,
                           now: datetime) -> None:
        """(#1228) Book each held meter step against the house rows over
        the same span, then stamp this cycle's rows on the new baselines.

        A cycle's import and share say nothing of time no cycle booked. The
        rows do, once they cover it: SEM watched all of the span, or every
        counter and the home balance are read this cycle (the counters kept
        counting while SEM was down). The device's grid kWh are its step ×
        the grid's share of what the house, the batteries and the car used
        over the span, at most the import no device took; steps settled in
        one cycle share that in proportion. They leave the house cost at
        the rate the house booked them.

        Waits up to ``SOLAR_GAP_WAIT_S`` for the counters once HA runs, as
        the solar step does (#1187). Dropped, and said, when the rows cannot
        cover the span: no grid import counter (the house lost that import
        too), PV with no solar counter and the sun up, a new day (the day's
        rows start again), no rows at the start (a store from before), the
        device off its own meter, or the wait is over.
        """
        rows = self._meter_rows(today)
        ready = []
        for did in sorted(self.device_meter_gaps):
            gap = self.device_meter_gaps[did]
            why = (self._meter_gap_unread(gap, rows, now)
                   if did in self._meter_staged
                   else "the device has no own meter now")
            if why == "wait":
                continue
            del self.device_meter_gaps[did]
            if why is None:
                ready.append((did, gap))
            else:
                _LOGGER.info(
                    "Own meter of %s: %.3f kWh over time SEM did not book — "
                    "not priced, %s (#1228)", did, _as_float(gap.get("kwh")), why)
        if ready:
            self._book_meter_gaps(ready, rows, today, month_key, year_key)
        if self._meter_written:
            rows = self._meter_rows(today)
            for did in self._meter_written:
                if isinstance(self.device_meter_last.get(did), dict):
                    self.device_meter_last[did]["rows"] = dict(rows)
            self._meter_written = set()

    def _dark_rise(self) -> Optional[str]:
        """(#1228) While the sun is down, its next rising as ``sun.sun``
        says; the same text at both ends of a span = no sunrise inside."""
        if not self._sun_is_down():
            return None
        attrs = getattr(self._hass.states.get("sun.sun"), "attributes", None)
        rise = attrs.get("next_rising") if hasattr(attrs, "get") else None
        return str(rise) if rise else None

    def _meter_gap_unread(self, gap: Dict[str, Any], rows: Dict[str, Any],
                          now: datetime) -> Optional[str]:
        """(#1228) None = the rows cover the held step's span; "wait" = not
        yet; else why they never will."""
        start = gap.get("rows")
        if not isinstance(start, dict) or not all(
                _finite(start.get(k)) for k in
                ("import", "cost", "used", "taken", "taken_cost", "seen")):
            return "no house rows at its start"
        if start.get("day") != rows["day"]:
            return "a new day began"
        try:
            span_s = (now - datetime.fromisoformat(str(gap["since"]))).total_seconds()
        except (KeyError, TypeError, ValueError):
            return "its start cannot be read"
        seen = (rows["seen"] - float(start["seen"])
                if start.get("run") == rows["run"] else 0.0)
        if span_s - seen <= MAX_INTEGRATION_GAP_SECONDS:
            return None   # SEM integrated the whole span
        if not (self._meter_counter_enabled
                and self._meter_counter_entities.get("grid_import")):
            return "no grid import counter covers the time SEM did not see"
        # PV with no counter: its row says nothing of that time, unless the
        # sun stayed down from the start to now
        if (not self._solar_counter_enabled
                and self._lifetime_accumulators.get("lifetime_solar", 0.0) > 0
                and (start.get("rise") is None
                     or start.get("rise") != self._dark_rise())):
            return "no solar counter covers that time, and the sun may have been up"
        # every counter read this cycle, not only the import: the home
        # balance takes a row still near 0 as no flow, and a battery counter
        # still loading after a restart would read the span as all grid
        needed = set(self._meter_counter_entities) | {"home"}
        if self._solar_counter_enabled:
            needed.add("solar")
        if needed <= self._counter_backed:
            return None
        from homeassistant.core import CoreState
        if getattr(self._hass, "state", None) is not CoreState.running:
            return "wait"   # entities still loading (bug class 86)
        # the clock runs while HA runs: a restart starts it again
        wait = gap.get("wait") if isinstance(gap.get("wait"), dict) else {}
        try:
            if wait.get("run") != self._run_token:
                raise ValueError
            waited = (now - datetime.fromisoformat(str(wait["at"]))).total_seconds()
        except (KeyError, TypeError, ValueError):
            gap["wait"] = {"at": now.isoformat(), "run": self._run_token}
            return "wait"
        if waited < SOLAR_GAP_WAIT_S:
            return "wait"
        return "its counters were not all read in time"

    def _book_meter_gaps(self, ready: List[Tuple[str, Dict[str, Any]]],
                         rows: Dict[str, Any], today: date, month_key: str,
                         year_key: str) -> None:
        """(#1228) The held steps' grid kWh, moved from the house cost to
        each device's own price."""
        plans = []
        for did, gap in ready:
            start = gap["rows"]
            d_import = rows["import"] - float(start["import"])
            d_used = rows["used"] - float(start["used"])
            free = d_import - (rows["taken"] - float(start["taken"]))
            free_cost = ((rows["cost"] - float(start["cost"]))
                         - (rows["taken_cost"] - float(start["taken_cost"])))
            share = max(0.0, min(1.0, d_import / d_used)) if d_used > 0 else 0.0
            want = max(0.0, _as_float(gap.get("kwh"))) * share
            plans.append((did, gap, want, free, free_cost))
        # at most the import no device took; several steps in one cycle
        # share the least such import in proportion
        total = sum(p[2] for p in plans)
        least = min(p[3] for p in plans)
        scale = min(1.0, max(0.0, least) / total) if total > 0 else 0.0
        for did, gap, want, free, free_cost in plans:
            kwh = want * scale
            if kwh <= 0.0:
                _LOGGER.info("Own meter of %s: %.3f kWh over time SEM did not "
                             "book — none of it from the grid (#1228)",
                             did, _as_float(gap.get("kwh")))
                continue
            # what the house paid a kWh of that import; the device's own
            # price as the house prices a gap (#795): its day's average, else
            # its price at the read after the gap, else the house's
            house = free_cost / free
            own_kwh = self._daily_accumulators.get(
                f"{DEVICE_TARIFF_KWH}{did}_{today}", 0.0)
            own_cost = self._daily_cost_accumulators.get(
                f"{DEVICE_TARIFF_COST}{did}_{today}", 0.0)
            if own_kwh > 0.05:
                price = own_cost / own_kwh
            elif _finite(gap.get("price")):
                price = float(gap["price"])
            else:
                price = house
            self._accumulate(f"{DEVICE_TARIFF_KWH}{did}", today, month_key,
                             year_key, kwh)
            self._accumulate_cost(f"{DEVICE_TARIFF_COST}{did}", today,
                                  month_key, year_key, kwh * price)
            self._accumulate_cost("cost_import", today, month_key, year_key,
                                  kwh * (price - house))
            _LOGGER.info("Own meter of %s: %.3f of %.3f kWh over time SEM did "
                         "not book were from the grid, priced at %.4f (#1228)",
                         did, kwh, _as_float(gap.get("kwh")), price)

    def get_device_tariff(self, device_id: str, day: date) -> Dict[str, float]:
        """(#812) Today's grid kWh and cost of a device on its own tariff."""
        return {
            "daily_grid_kwh": self._get_daily(
                f"{DEVICE_TARIFF_KWH}{device_id}", day),
            "daily_cost": self._get_daily_cost(
                f"{DEVICE_TARIFF_COST}{device_id}", day),
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
            # (#829) 10 Wh, the house standard for daily rows — at 1 Wh this ticked
            # every cycle (7,806 rows/day on PROD vs ~2k for daily_home).
            "today_kwh": None if home is None else round(home - controlled, 2),
            "home_today_kwh": home,
            "controlled_today_kwh": round(controlled, 2),
            "estimated_today_kwh": round(estimated, 2),
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
            # (#1044) True when the whole day was booked with SEM's own
            # chargers left out of the mirror. The upgrade day is not: its
            # morning may hold a charger booked under the old rule.
            "home_members_only": (
                self._home_members_since is not None
                and day > self._home_members_since
            ),
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

        charging = self._charging_units(power)
        for bid, (b_solar, b_grid) in allocate_fleet_charge(
            charging, solar_kwh, grid_kwh,
        ).items():
            self._battery_provenance.charge(
                bid, b_solar, b_grid, self._import_rate,
            )

    def _charging_units(self, power: PowerReadings) -> Dict[str, float]:
        """(#1203 review) Each charging battery's watts, for the per-battery
        split. While the battery is held (#1177, #1186) the charge booked is
        the held figure, and a dark unit reads 0 W here: the live units
        would take its charge. So the shares come from the last live read,
        as the flow shares do (``_battery_flows``)."""
        if "battery" in self._integral_held:
            return dict(self._battery_live_charging)
        charging = {
            bid: bp.power_w
            for bid, bp in (getattr(power, "batteries", None) or {}).items()
            if float(getattr(bp, "power_w", 0.0) or 0.0) > 0
        }
        if "battery" in self._integral_live:
            self._battery_live_charging = dict(charging)
        return charging

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

    def ev_battery_cost_rate(self) -> float:
        """What one kWh drawn from the battery costs the EV session (#793).

        The provenance pool's stored grid cost, pro rata — the same pool the
        battery savings already price from. The EV session was the one
        consumer that never asked, recording grid-charged battery energy
        delivered to the car as free.
        """
        return self._battery_provenance.implied_cost_rate()

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
        # (#1191) the same solar part of the export the rate and CO2 use
        daily_self_consumed = max(0, daily_solar - solar_export(
            daily_grid_export, self._daily_accumulators.get(
                f"{GRID_EXPORT_BATTERY_CATEGORY}_{today_str}", 0.0)))

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
        day and get cleaned up separately (older than yesterday). The other
        categories are solar, home, grid_import, grid_export, battery_charge,
        battery_discharge; the only other ``ev_`` rows are the car's flow
        split on the EV day (``EV_DAY_FLOW_CATEGORIES``, #1046), which must
        survive midnight for the same reason.

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
            # (#1043) the counters the lifetime seed added up. Lost, a seed
            # from the first tariff only could not be told from a good one.
            "lifetime_seed_counters": (
                {cat: list(ids) for cat, ids in self._lifetime_seed_counters.items()}
                if self._lifetime_seed_counters is not None else None
            ),
            "yearly_cost_seeded": self._yearly_cost_seeded,
            "rate_history": list(self._rate_history),
            "device_meter_last": dict(self.device_meter_last),   # (#812)
            # (#1228) a step over an outage still waiting for its rows
            "device_meter_gaps": dict(self.device_meter_gaps),
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
            # (#1049) each charger's own row, same reason.
            "charger_counter_baselines": {
                cid: dict(bl)
                for cid, bl in self._charger_counter_baselines.items()
            },
            # (#1049) and what each box drew since its counter last moved:
            # lost, a cloud counter's unreported session would come out of
            # the row at the first cycle after a restart.
            "ev_counter_pending": {
                "pending": dict(self._ev_counter_pending),
                "seen": dict(self._ev_counter_seen),
                # (#1101) and the most each box could have drawn unseen, with
                # the last cycle that kept it: the time SEM is down counts too.
                "room": dict(self._ev_counter_room),
                "unreported": dict(self._ev_counter_unreported),
                "idle_h": dict(self._ev_counter_idle_h),
                "unseen_kwh": dict(self._ev_counter_unseen_kwh),
                "quiet_h": dict(self._ev_counter_quiet_h),
                # (#1161) and every kWh each counter's boxes drew
                "drawn_total": dict(self._ev_counter_drawn_total),
                "watched_at": (self._ev_watched_at.isoformat()
                               if self._ev_watched_at else None),
            },
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
            "ev_seen_day": (
                self._ev_seen_day.isoformat()
                if getattr(self, "_ev_seen_day", None) else None
            ),
            "ev_rolled_at": (
                self._ev_rolled_at.isoformat()
                if getattr(self, "_ev_rolled_at", None) else None
            ),
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
            "home_members_since": (
                self._home_members_since.isoformat()
                if self._home_members_since else None
            ),
            "ev_flow_since": (
                self._ev_flow_since.isoformat()
                if self._ev_flow_since else None
            ),
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
            self._lifetime_seed_counters = _as_seed_counters(
                state.get("lifetime_seed_counters"))
            # (#812) a corrupt entry is dropped, never a reason to fail restore
            _ml = state.get("device_meter_last")
            self.device_meter_last = {
                str(k): dict(v) for k, v in (_ml.items() if isinstance(_ml, dict) else ())
                if isinstance(v, dict) and isinstance(v.get("value"), (int, float))
                and not isinstance(v.get("value"), bool)
                and math.isfinite(float(v["value"]))
                and isinstance(v.get("entity"), str) and isinstance(v.get("date"), str)
                and isinstance(v.get("at"), str)}
            # (#1228) the same: a held step needs its kWh and its start
            _mg = state.get("device_meter_gaps")
            self.device_meter_gaps = {
                str(k): dict(v) for k, v in (_mg.items() if isinstance(_mg, dict) else ())
                if isinstance(v, dict) and _finite(v.get("kwh"))
                and isinstance(v.get("since"), str)}
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
            pending = state.get("ev_counter_pending")
            if isinstance(pending, dict):
                for attr, key in (("_ev_counter_pending", "pending"),
                                  ("_ev_counter_seen", "seen"),
                                  ("_ev_counter_room", "room"),
                                  ("_ev_counter_unreported", "unreported"),
                                  ("_ev_counter_idle_h", "idle_h"),
                                  ("_ev_counter_unseen_kwh", "unseen_kwh"),
                                  ("_ev_counter_quiet_h", "quiet_h"),
                                  ("_ev_counter_drawn_total", "drawn_total")):
                    raw = pending.get(key)
                    if isinstance(raw, dict):
                        setattr(self, attr, {
                            str(e): float(v) for e, v in raw.items()
                            if isinstance(v, (int, float))
                            and not isinstance(v, bool) and math.isfinite(v)
                            and v >= 0
                        })
                if not isinstance(pending.get("unseen_kwh"), dict):
                    # (#1101) A store from before the wait does not tell
                    # what ``room`` holds: all of it waits to be spent.
                    self._ev_counter_unseen_kwh = dict(self._ev_counter_room)
                # (#1101) A time that does not parse, or has no zone, is no
                # record: every counter's next move is booked as it stands.
                watched_at = pending.get("watched_at")
                self._ev_watched_at = None
                if isinstance(watched_at, str):
                    try:
                        parsed = datetime.fromisoformat(watched_at)
                    except ValueError:
                        parsed = None
                    if parsed is not None and parsed.tzinfo is not None:
                        self._ev_watched_at = parsed
            charger_baselines = state.get("charger_counter_baselines")
            if isinstance(charger_baselines, dict):
                # A damaged entry is dropped; that charger re-anchors.
                self._charger_counter_baselines = {
                    str(cid): bl for cid, bl in charger_baselines.items()
                    if isinstance(bl, dict)
                }
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
            # (#1176) a store without them is the upgrade: midnight until
            # the first rollover this code sees.
            try:
                seen = state.get("ev_seen_day")
                self._ev_seen_day = date.fromisoformat(str(seen)) if seen else None
                rolled = state.get("ev_rolled_at")
                self._ev_rolled_at = (
                    datetime.fromisoformat(str(rolled)) if rolled else None)
            except ValueError:
                self._ev_seen_day = None
                self._ev_rolled_at = None
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
            # (#1044) Absent on a store written before the fix: the next
            # update stamps today, so the upgrade day is not sealed clean.
            members_since = state.get("home_members_since")
            if members_since:
                try:
                    self._home_members_since = date.fromisoformat(
                        str(members_since))
                except ValueError:
                    _LOGGER.warning(
                        "Discarding unparseable home_members_since %r — the "
                        "true baseload's day history restarts today",
                        members_since,
                    )
                    self._home_members_since = None
            # (#1046) Absent on a store written before the fix: the next
            # update stamps the running EV day, whose share then reads the
            # calendar flows.
            flow_since = state.get("ev_flow_since")
            if flow_since:
                try:
                    self._ev_flow_since = date.fromisoformat(str(flow_since))
                except ValueError:
                    _LOGGER.warning(
                        "Discarding unparseable ev_flow_since %r — the car's "
                        "solar share reads the calendar flows for one EV day",
                        flow_since,
                    )
                    self._ev_flow_since = None
            last_update = state.get("last_update")
            if last_update:
                self._last_update = datetime.fromisoformat(last_update)
