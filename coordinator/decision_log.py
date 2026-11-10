"""(#1084) The decision log — why a device's command changed.

Recording only. Nothing here feeds back into a decision: the actuators
hand the log the command they are about to send (or, under observer mode,
WOULD send) and carry on whatever the log does.

One owner (:class:`DecisionLog`, held by the ``SurplusController`` so the
three actuator seams — chargers, batteries, loads — already have a handle
on it) keeps the last command per device and writes a
:class:`DecisionRecord` only when that command CHANGES: a start, a stop, a
mode change, a charger current step of at least 1 A, or a battery / load
setpoint that moved by a meaningful amount. The same command sent again
every cycle is not news and writes nothing.

Each record is kept in a ring buffer of 200 (diagnostics), fired as the
``solar_energy_management_decision`` event (the logbook describes it,
``logbook.py``), and the newest one per device rides an existing state
sensor as ``last_decision``. Never restored: a restart starts a fresh log.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any, Deque, Dict, List, Mapping, Optional, Tuple

from . import reason_codes as RC

_LOGGER = logging.getLogger(__name__)

EVENT_DECISION = "solar_energy_management_decision"

DECISION_LOG_SIZE = 200

KIND_CHARGER = "charger"
KIND_BATTERY = "battery"
KIND_LOAD = "load"
#: (#1174) the house's grid export limit, written to the inverter (#1090)
KIND_EXPORT = "export"
EXPORT_DEVICE_ID = "grid_export"

#: The smallest value change that counts as a new command, per kind. A
#: charger steps in whole amps (decided: ≥ 1 A). A battery limit is
#: quantised to 250 W steps by the actuator (#900), so one step is one
#: change. A watt-setpoint load wobbles with the surplus; 500 W is a change
#: a person would notice on the meter, the wobble below it is not.
MIN_STEP: Dict[str, float] = {
    KIND_CHARGER: 1.0,
    KIND_BATTERY: 250.0,
    KIND_LOAD: 500.0,
    KIND_EXPORT: 100.0,
}

_UNIT = {KIND_CHARGER: "A", KIND_BATTERY: "W", KIND_LOAD: "W", KIND_EXPORT: "W"}

#: Commands that mean "SEM is not driving this device". A device whose
#: FIRST command is one of these has not changed — it was never started —
#: so the log stays quiet instead of writing a row per device on every boot.
RESTING_VERBS = frozenset({"idle", "off", "normal", "release", "disable",
                           "stop", "park_off",
                           "stop_force_charge", "stop_force_discharge"})

_TEXT_MAX = 120
_NAME_MAX = 60
_INPUT_KEYS = ("import_price", "export_rate", "price_level", "soc",
               "solar_w", "surplus_w", "budget_w", "target_kwh", "target_soc")


def _clean_inputs(inputs: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Keep the record small and JSON-safe: known keys, rounded numbers,
    no ``None`` (a missing input is simply absent)."""
    out: Dict[str, Any] = {}
    if not inputs:
        return out
    for key in _INPUT_KEYS:
        val = inputs.get(key)
        if val is None:
            continue
        if isinstance(val, bool):
            out[key] = val
        elif isinstance(val, (int, float)):
            out[key] = round(float(val), 4 if "price" in key or "rate" in key else 1)
        else:
            out[key] = str(val)[:32]
    return out


def _own_figure(kind: str, inputs: Dict[str, Any]) -> None:
    """(#1331) A charger row keeps the car's budget (``budget_w``), every
    other row the spare sun (``surplus_w``). They are two figures: at night
    the car's budget is grid room, and no row may call it surplus."""
    inputs.pop("surplus_w" if kind == KIND_CHARGER else "budget_w", None)


def _clean_params(params: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """(#1174) The numbers a reason's plain sentence names — a few short,
    JSON-safe values, never more than the sentence needs."""
    out: Dict[str, Any] = {}
    for key, val in list((params or {}).items())[:4]:
        if val is None:
            continue
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            out[str(key)[:16]] = round(float(val), 1) if isinstance(val, float) else val
        else:
            out[str(key)[:16]] = str(val)[:16]
    return out


def format_command(kind: str, verb: str, value: Optional[float]) -> str:
    """``charge 8 A`` / ``limit_discharge 1500 W`` / ``off``."""
    if value is None:
        return verb
    return f"{verb} {float(value):g} {_UNIT.get(kind, '')}".rstrip()


@dataclass(frozen=True)
class DecisionRecord:
    """One command change on one device, and why."""

    time: datetime
    device_id: str
    device_kind: str
    old: Optional[str]
    new: str
    reason_code: str
    text: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    observer: bool = False
    name: str = ""
    #: (#1174) the numbers the code's plain sentence names
    params: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "time": self.time.isoformat(),
            "device_id": self.device_id,
            "device_kind": self.device_kind,
            "name": self.name or self.device_id,
            "old": self.old,
            "new": self.new,
            "reason_code": self.reason_code,
            "params": dict(self.params),
            "text": self.text,
            "inputs": dict(self.inputs),
            "observer": self.observer,
        }


class DecisionLog:
    """Ring buffer of :class:`DecisionRecord`, written on command changes."""

    def __init__(self, hass=None, maxlen: int = DECISION_LOG_SIZE) -> None:
        self.hass = hass
        self._records: Deque[DecisionRecord] = deque(maxlen=maxlen)
        # "<kind>:<device_id>" → (verb, value, observer, command string).
        # Keyed by kind too: a load and a battery may share an id.
        self._last: Dict[str, Tuple[str, Optional[float], bool, str]] = {}
        self._last_record: Dict[str, DecisionRecord] = {}
        self._inputs: Dict[str, Any] = {}
        # "<kind>:<device_id>" → display name, for seams that know only an id
        self._names: Dict[str, str] = {}

    # ── per-cycle context ────────────────────────────────────────────
    def set_inputs(self, inputs: Optional[Mapping[str, Any]]) -> None:
        """What the cycle knew — stamped once by the coordinator, copied
        into every record this cycle writes."""
        self._inputs = _clean_inputs(inputs)

    def set_input(self, key: str, value: Any) -> None:
        """(#1331) Refresh one input later in the cycle, for the rows after."""
        self._inputs.update(_clean_inputs({key: value}))
        if value is None:
            self._inputs.pop(key, None)

    def set_names(self, names: Optional[Mapping[str, str]]) -> None:
        """Display names by ``"<kind>:<device_id>"`` — stamped by the
        coordinator for devices whose seam knows only an id (batteries).
        A name the seam passes itself wins."""
        self._names = {str(k): str(v) for k, v in (names or {}).items() if v}

    # ── writing ──────────────────────────────────────────────────────
    def _is_change(self, key: str, kind: str, verb: str,
                   value: Optional[float], observer: bool,
                   quiet_first_rest: bool = True) -> bool:
        last = self._last.get(key)
        if last is None:
            return not (quiet_first_rest and verb in RESTING_VERBS)
        l_verb, l_value, l_obs, _ = last
        if verb != l_verb or observer != l_obs:
            return True
        if value is None or l_value is None:
            return (value is None) != (l_value is None)
        return abs(float(value) - float(l_value)) >= MIN_STEP.get(kind, 1.0)

    def record(self, *, device_id: str, kind: str, verb: str,
               value: Optional[float] = None, reason_code: str = "",
               text: str = "", observer: bool = False, name: str = "",
               params: Optional[Mapping[str, Any]] = None,
               inputs: Optional[Mapping[str, Any]] = None,
               now: Optional[datetime] = None,
               quiet_first_rest: bool = True) -> Optional[DecisionRecord]:
        """Note the command about to leave for ``device_id``.

        Returns the new record, or ``None`` when the command did not change.
        ``quiet_first_rest=False`` is for callers whose stop only ever leaves
        for a RUNNING device (a load stop, a shed): there the first "off"
        is a real change, not boot noise.
        Never raises: a log that breaks an actuator would be worse than no
        log at all.
        """
        try:
            device_id = str(device_id)
            verb = str(verb)
            if value is not None:
                value = round(float(value), 1)
            key = f"{kind}:{device_id}"
            if not self._is_change(key, kind, verb, value, observer,
                                   quiet_first_rest):
                if key not in self._last:
                    # a first resting command: no row, but it is the "old"
                    # the next change reads from
                    self._last[key] = (verb, value, bool(observer),
                                       format_command(kind, verb, value))
                return None
            old = self._last.get(key)
            new_cmd = format_command(kind, verb, value)
            self._last[key] = (verb, value, bool(observer), new_cmd)
            if now is None:
                from homeassistant.util import dt as dt_util
                now = dt_util.now()
            merged = dict(self._inputs)
            merged.update(_clean_inputs(inputs))
            _own_figure(kind, merged)
            rec = DecisionRecord(
                time=now,
                device_id=device_id,
                device_kind=kind,
                old=old[3] if old else None,
                new=new_cmd,
                reason_code=str(reason_code or verb),
                text=str(text or "")[:_TEXT_MAX],
                inputs=merged,
                observer=bool(observer),
                name=str(name or self._names.get(key) or device_id)[:_NAME_MAX],
                params=_clean_params(params),
            )
            self._records.append(rec)
            self._last_record[key] = rec
            self._fire(rec)
            return rec
        except Exception:  # noqa: BLE001 — recording never breaks a seam
            _LOGGER.debug("decision log: record failed", exc_info=True)
            return None

    def _fire(self, rec: DecisionRecord) -> None:
        bus = getattr(self.hass, "bus", None)
        if bus is None:
            return
        try:
            bus.async_fire(EVENT_DECISION, rec.as_dict())
        except Exception:  # noqa: BLE001 — the event must never break the seam
            _LOGGER.debug("decision log: event failed", exc_info=True)

    # ── reading ──────────────────────────────────────────────────────
    def last(self, kind: str, device_id: str) -> Optional[Dict[str, Any]]:
        rec = self._last_record.get(f"{kind}:{device_id}")
        return rec.as_dict() if rec is not None else None

    def last_by_kind(self, kind: str) -> Dict[str, Dict[str, Any]]:
        return {rec.device_id: rec.as_dict()
                for rec in self._last_record.values()
                if rec.device_kind == kind}

    def records(self) -> List[Dict[str, Any]]:
        return [r.as_dict() for r in self._records]

    def __len__(self) -> int:
        return len(self._records)


# ── the three seams' adapters ────────────────────────────────────────
# Each actuator calls ONE of these at its single dispatch point (chargers:
# the reconciler's apply loop, where a write really leaves). They turn
# the actuator's own decision type into a command + a stable reason code.

def log_of(controller) -> Optional[DecisionLog]:
    """The log the ``SurplusController`` owns, or ``None`` for bare callers."""
    log = getattr(controller, "decision_log", None)
    return log if isinstance(log, DecisionLog) else None


def _params_of(decision) -> Optional[Mapping[str, Any]]:
    params = getattr(decision, "reason_params", None)
    return params if isinstance(params, Mapping) else None


def record_charger(log: Optional[DecisionLog], decision, *, verb: str,
                   value: Optional[float] = None,
                   observer: bool = False, name: str = "") -> Optional[DecisionRecord]:
    """A charger write at the reconciler's apply loop. ``verb`` / ``value``
    are what was SENT (or withheld under observer); the reason comes from
    the :class:`ChargerDecision` that asked for it."""
    if not isinstance(log, DecisionLog):
        return None
    intent = getattr(getattr(decision, "intent", None), "value", "idle")
    # (#1174) the code the decision set where it was made; the composed
    # one below only for a decision that carries none
    code = str(getattr(decision, "reason_code", "") or "")
    if not code and getattr(decision, "peak_paused", False):
        code = "peak_paused"
    elif not code and getattr(decision, "capped_by_limit", False):
        code = "limit_capped"
    elif not code:
        code = f"{getattr(decision, 'mode', '') or 'mode'}_{intent}"
    return log.record(
        device_id=str(getattr(decision, "charger_id", "")), kind=KIND_CHARGER,
        verb=verb, value=value, reason_code=code,
        text=str(getattr(decision, "reason", "") or ""), observer=observer,
        name=name, params=_params_of(decision))


def record_battery(log: Optional[DecisionLog], decision, *,
                   value_w: Optional[float] = None,
                   observer: bool = False) -> Optional[DecisionRecord]:
    """A :class:`BatteryDecision` at ``actuate_battery()``. ``value_w`` is the
    watts the intent actually sends (the quantised limit, the charge power)."""
    if not isinstance(log, DecisionLog):
        return None
    intent = getattr(getattr(decision, "intent", None), "value", "normal")
    code = (str(getattr(decision, "reason_code", "") or "")   # (#1174)
            or ("room_capped" if getattr(decision, "room_capped", False)
                else intent))
    return log.record(
        device_id=str(getattr(decision, "battery_id", "")), kind=KIND_BATTERY,
        verb=intent, value=value_w if value_w else None, reason_code=code,
        text=str(getattr(decision, "reason", "") or ""), observer=observer,
        params=_params_of(decision),
        inputs={"target_soc": (getattr(decision, "target_soc", None) or None)
                if intent == "force_charge" else None})


def record_shed(log: Optional[DecisionLog], device_id: str, *, name: str = "",
                shed: bool, reason_code: str, text: str = "",
                observer: bool = False) -> Optional[DecisionRecord]:
    """A peak / phase shed or its restore at the load manager's switch
    point. Its rows are not ``ControllableDevice`` objects, so this takes an
    id. ``restore`` hands the load back to how it was before the shed."""
    if not isinstance(log, DecisionLog):
        return None
    return log.record(
        device_id=str(device_id), kind=KIND_LOAD,
        verb="off" if shed else "restore", reason_code=reason_code,
        text=text, observer=observer, name=str(name or device_id),
        quiet_first_rest=False)


def record_export(log: Optional[DecisionLog], decision, *,
                  observer: bool = False) -> Optional[DecisionRecord]:
    """(#1174) The export limit at the one point it leaves for the inverter
    (``actuate_export``): a cut to ``watts`` or its release. A release only
    ever follows a cut SEM made (the guard's rule), so the first one after a
    restart is a real change, not boot noise."""
    if not isinstance(log, DecisionLog):
        return None
    intent = str(getattr(getattr(decision, "intent", None), "value", "") or "")
    if intent not in ("limit_export", "release_export"):
        return None
    return log.record(
        device_id=EXPORT_DEVICE_ID, kind=KIND_EXPORT, verb=intent,
        value=(float(getattr(decision, "watts", 0.0) or 0.0)
               if intent == "limit_export" else None),
        reason_code=str(getattr(decision, "reason_code", "") or intent),
        text=str(getattr(decision, "reason", "") or ""), observer=observer,
        # no name: the card and the logbook say the kind word in the
        # user's language (``why_kind_export``)
        params=_params_of(decision),
        quiet_first_rest=False)


def _own_inputs(device) -> Optional[Mapping[str, Any]]:
    """(#812) The inputs a device's own tariff stamped, if any."""
    own = getattr(device, "tariff_inputs", None)
    return own if isinstance(own, dict) else None


def record_load(log: Optional[DecisionLog], device, *, on: bool,
                watts: Optional[float] = None, reason_code: str = "",
                text: str = "", observer: bool = False,
                verb: Optional[str] = None
                ) -> Optional[DecisionRecord]:
    """A surplus load's on / off / setpoint at the load choke points.

    (#1323) ``verb`` names a command that is neither: ``step_down`` — the
    load is held below its normal state. Its release is an ``off``."""
    if not isinstance(log, DecisionLog):
        return None
    did = str(getattr(device, "device_id", "") or "")
    # An on/off load has no setpoint to speak of: only a watt-setpoint load
    # carries its watts, so a switch re-sent at a new surplus is no change.
    if on and watts and str(getattr(
            getattr(device, "device_type", None), "value", "")) in (
            "setpoint", "current_control"):
        value = float(watts)
    else:
        value = None
    return log.record(
        device_id=did, kind=KIND_LOAD,
        verb=verb or ("on" if on else "off"),
        value=value,
        reason_code=reason_code or (RC.LOAD_START if on else RC.LOAD_STOP),
        text=text, observer=observer,
        name=str(getattr(device, "name", "") or did),
        # (#812) a device on its own tariff: its price and level, not the
        # house's (stamped each cycle by ``DeviceTariffs.stamp``)
        inputs=_own_inputs(device),
        # a load stop only leaves for a running load: always a change
        quiet_first_rest=False)
