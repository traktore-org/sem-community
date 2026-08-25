"""DeyeBatteryAdapter — Deye hybrid inverters.

Deye exposes forced grid charging through a per-program "time slice"
model rather than a single service call: a grid-charge switch that
enables the feature, a charge-current number (max grid-charge current in
amperes), a battery-voltage sensor (for power conversion), and up to
six programmable time slices each with a start time, an SOC target and a
charge-enable select.

This Deye contract slice ships:

- the :class:`DeyeBatteryAdapter` with explicit observer/actuation gates,
  persistent pre-write snapshots, read-back and fail-closed rollback.
- a fail-closed, state-validated capability computation
  (:meth:`DeyeBatteryAdapter.capability` / ``supports_forced_charge``)
  that only reports forced-charge available when every entity is present,
  correctly shaped and fresh.
- an immutable, serialisable :class:`DeyeCapability` result.

Config shape (documented):

    battery_charge_platform: deye          # REQUIRED — no auto-detect
    deye_grid_charge_switch: switch.deye_grid_charge
    deye_charge_current_entity: number.deye_charge_current   # unit A
    deye_battery_voltage_entity: sensor.deye_battery_voltage
    deye_battery_voltage_max_age_s: 30     # default 30
    deye_max_charge_current_a: 25          # optional safe ceiling
    deye_bms_max_charge_current_a: 30      # optional BMS max
    deye_max_discharge_power: 5000         # safe discharge config (or 0)
    deye_program_control: true             # require 6 complete slices
    deye_work_mode_control: true           # optional, explicit only
    deye_work_mode_entity: select.deye_energy_pattern
    deye_work_mode_load_first_option: Load First
    deye_work_mode_battery_first_option: Battery First
    deye_force_charge_work_mode: battery_first
    deye_program_groups:                   # list of 6 dicts (preferred)
      - time: time.deye_slice_1_time       # HA writable time.* entity
        soc: number.deye_slice_1_soc
        charge: select.deye_slice_1_charge
      # ... 6 entries
    # Numbered-key alternative (either style resolves to the same 6 slots):
    #   deye_program_1_time / deye_program_1_soc / deye_program_1_charge
    #   ...
    deye_observer_mode: true                # default true; False required to write
    deye_actuation_enabled: false           # exact boolean True required to write
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import math
from dataclasses import asdict, dataclass
from datetime import datetime, time
from typing import Any, Optional
from uuid import uuid4

from homeassistant.util import dt as dt_util

from ..charger_types import BatteryIntent
from .base import BatteryControlAdapter
from .deye_schedule import (
    DeyeScheduleError,
    compile_deye_charge_window,
    validate_deye_boundaries,
)

_LOGGER = logging.getLogger(__name__)

_NUMERIC_DOMAINS = ("number", "input_number")
_SELECT_DOMAINS = ("select", "input_select")
_SLOT_KEYS = ("time", "soc", "charge")
_DEFAULT_VOLTAGE_MAX_AGE_S = 30.0
_MIN_BATTERY_VOLTAGE_V = 40.0
_DEFAULT_PROGRAM_COUNT = 6


@dataclass(frozen=True)
class DeyeCapability:
    """Immutable, serialisable snapshot of what Deye forced-charge can do now.

    ``available`` is the single gate for ``supports_forced_charge``; every
    other field lets a caller render diagnostics without re-reading states.
    """

    available: bool
    reason: str
    max_charge_current_a: float
    battery_voltage_age_s: float
    snapshot_supported: bool
    readback_supported: bool
    restore_supported: bool


@dataclass(frozen=True)
class DeyeControlSnapshot:
    """Serializable pre-write state for one battery control session."""

    schema_version: int
    config_entry_id: str
    battery_id: str
    session_id: str
    created_at: float
    entity_mapping: tuple[tuple[str, str], ...]
    grid_charge_enabled: bool
    charge_current_a: float
    program_times: tuple[str, ...]
    program_socs: tuple[float, ...]
    program_charging: tuple[str, ...]
    work_mode: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entity_mapping"] = [list(item) for item in self.entity_mapping]
        data["program_times"] = list(self.program_times)
        data["program_socs"] = list(self.program_socs)
        data["program_charging"] = list(self.program_charging)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeyeControlSnapshot":
        if type(data.get("grid_charge_enabled")) is not bool:
            raise ValueError("grid_charge_enabled must be a boolean")
        if not isinstance(data.get("work_mode"), str):
            raise ValueError("work_mode must be a string")
        return cls(
            schema_version=int(data["schema_version"]),
            config_entry_id=str(data["config_entry_id"]),
            battery_id=str(data["battery_id"]),
            session_id=str(data["session_id"]),
            created_at=float(data["created_at"]),
            entity_mapping=tuple(
                (str(key), str(value)) for key, value in data["entity_mapping"]
            ),
            grid_charge_enabled=bool(data["grid_charge_enabled"]),
            charge_current_a=float(data["charge_current_a"]),
            program_times=tuple(str(value) for value in data["program_times"]),
            program_socs=tuple(float(value) for value in data["program_socs"]),
            program_charging=tuple(
                str(value) for value in data["program_charging"]
            ),
            work_mode=data["work_mode"],
        )


class DeyeBatteryAdapter(BatteryControlAdapter):
    """Fail-closed Deye battery control with transactional restoration."""

    def __init__(self, hass, config: dict) -> None:
        super().__init__(hass, config)
        self._grid_charge_switch = self._clean_string(
            config.get("deye_grid_charge_switch"),
        )
        self._charge_current_entity = self._clean_string(
            config.get("deye_charge_current_entity"),
        )
        self._voltage_entity = self._clean_string(
            config.get("deye_battery_voltage_entity"),
        )
        self._work_mode_control = config.get("deye_work_mode_control", False) is True
        self._work_mode_entity = self._clean_string(
            config.get("deye_work_mode_entity"),
        )
        self._work_mode_options = {
            "load_first": self._clean_string(
                config.get("deye_work_mode_load_first_option"),
            ),
            "battery_first": self._clean_string(
                config.get("deye_work_mode_battery_first_option"),
            ),
        }
        self._force_charge_work_mode = self._clean_string(
            config.get("deye_force_charge_work_mode"),
        ).lower()
        # (#827) System Work Mode — a DIFFERENT register from the
        # Battery-First/Load-First selector above: the export-policy
        # selector (Selling First / Zero Export To Load / Zero Export To
        # CT). Its own 3-option dict and validator, never a widening of the
        # 2-option one — that one is validated "exactly two, distinct".
        self._system_work_mode_control = (
            config.get("deye_system_work_mode_control", False) is True)
        self._system_work_mode_entity = self._clean_string(
            config.get("deye_system_work_mode_entity"),
        )
        self._system_work_mode_options = {
            "selling_first": self._clean_string(
                config.get("deye_system_work_mode_selling_option"),
            ),
            "zero_export_to_load": self._clean_string(
                config.get("deye_system_work_mode_zero_load_option"),
            ),
            "zero_export_to_ct": self._clean_string(
                config.get("deye_system_work_mode_zero_ct_option"),
            ),
        }
        # The mode the inverter held before SEM's spend, restored on stop.
        # Instance-scoped: a restart mid-spend loses it, and the stop then
        # falls back to Zero Export To Load — the SAFE direction (no export)
        # rather than leaving the pack selling.
        self._system_mode_prior: str | None = None
        now_provider = config.get("deye_now_provider")
        self._now_provider = now_provider if callable(now_provider) else dt_util.now
        self._voltage_max_age_raw = config.get(
            "deye_battery_voltage_max_age_s", _DEFAULT_VOLTAGE_MAX_AGE_S,
        )
        self._voltage_max_age_s = self._finite_gt0(self._voltage_max_age_raw)
        # Effective max grid-charge current = min(entity max, safe ceiling,
        # optional BMS max). The entity max always participates (validated);
        # the two config terms only participate when explicitly configured.
        self._safe_max_current_raw = config.get("deye_max_charge_current_a")
        self._safe_max_current: Optional[float] = self._finite_gt0(
            self._safe_max_current_raw,
        )
        self._bms_max_current_raw = config.get("deye_bms_max_charge_current_a")
        self._bms_max_current: Optional[float] = self._finite_gt0(
            self._bms_max_current_raw,
        )
        # Discharge power comes from safe finite config only (never states).
        self._max_discharge_w = self._finite_geq0(
            config.get("deye_max_discharge_power"), default=0.0,
        )
        self._program_control = config.get("deye_program_control", False) is True
        self._config_entry_id = self._clean_string(config.get("config_entry_id"))
        self._battery_id = self._clean_string(config.get("battery_id"))
        self._snapshot_store = config.get("deye_snapshot_store")
        self._snapshot_max_age_s = self._finite_gt0(
            config.get("deye_snapshot_max_age_s", 300),
        )
        # Only exact booleans can open write gates.  In particular, strings
        # such as "false" must never become truthy actuation permissions.
        self._observer_mode = config.get("deye_observer_mode", True) is not False
        self._actuation_enabled = config.get("deye_actuation_enabled", False) is True
        self._snapshot: Optional[DeyeControlSnapshot] = None
        self._snapshot_load_failed = False
        self._session_first_write_at: Optional[float] = None
        try:
            self._readback_attempts = int(config.get("deye_readback_attempts", 3))
            # Default 2 s between verify reads: Deye registers travel a
            # Modbus TCP/serial hop and HA's entity state reflects them on
            # the NEXT poll, not synchronously. A 0 s verify races that
            # poll, reads back the pre-write value, and rolls back a write
            # that actually succeeded — latching the adapter unsafe on
            # perfectly healthy hardware.
            self._readback_delay_s = float(config.get("deye_readback_delay_s", 2.0))
        except (TypeError, ValueError):
            self._readback_attempts = 0
            self._readback_delay_s = -1.0
        unsafe_raw = config.get(
            "deye_unsafe_latched",
            getattr(self._snapshot_store, "unsafe", False),
        )
        self._unsafe_latched = unsafe_raw is not False
        implemented = bool(
            self._snapshot_store is not None
            and callable(getattr(self._snapshot_store, "async_save", None))
            and callable(getattr(self._snapshot_store, "async_load", None))
            and callable(getattr(self._snapshot_store, "async_clear", None))
            and callable(getattr(self._snapshot_store, "async_set_unsafe", None))
        )
        self._snapshot_supported = implemented
        self._readback_supported = implemented
        self._restore_supported = implemented

    # ─── Config helpers ────────────────────────────────────────

    @staticmethod
    def _clean_string(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _finite_gt0(value):
        """Return ``float(value)`` if it is finite and > 0, else None."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) and v > 0 else None

    @staticmethod
    def _finite_geq0(value, default):
        """Return ``float(value)`` if finite and >= 0, else ``default``."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        return v if math.isfinite(v) and v >= 0 else default

    def _get_state(self, entity_id: str):
        """Return the HA state for ``entity_id`` or None (fail-closed)."""
        if not entity_id:
            return None
        try:
            return self._hass.states.get(entity_id)
        except Exception:  # noqa: BLE001 — never let a flaky read crash
            return None

    def _state_age_s(self, state, now: datetime) -> Optional[float]:
        """Age of a state in seconds (None if no timestamp -> treat as stale)."""
        ts = getattr(state, "last_updated", None) or getattr(
            state, "last_changed", None
        )
        if ts is None:
            return None
        try:
            age = (now - ts).total_seconds()
        except (TypeError, ValueError):
            return None
        return age if age >= 0 else None

    @staticmethod
    def _state_is_usable(state) -> bool:
        """Reject Home Assistant sentinel states everywhere, fail-closed."""
        raw = getattr(state, "state", None)
        return not (
            raw is None
            or (isinstance(raw, str) and raw.strip().lower() in {
                "", "unknown", "unavailable", "none", "nan", "inf", "-inf",
            })
        )

    def _program_slots(self):
        """Return the 6 program slots as a list of ``{time, soc, charge}``.

        Resolves from the documented list shape (``deye_program_groups``)
        or the numbered-key fallback (``deye_program_<n>_{time,soc,charge}``,
        1-indexed). A slot is only complete when all three keys are present.
        Missing/partial slots come back as ``None`` entries.
        """
        slots = []
        groups = self._config.get("deye_program_groups")
        if isinstance(groups, list) and groups:
            for g in groups:
                if not isinstance(g, dict):
                    slots.append(None)
                    continue
                slot = {k: self._clean_string(g.get(k)) for k in _SLOT_KEYS}
                slots.append(slot if all(slot.values()) else None)
            return slots
        # Numbered-key fallback.
        for i in range(1, _DEFAULT_PROGRAM_COUNT + 1):
            slot = {
                k: self._clean_string(self._config.get(f"deye_program_{i}_{k}"))
                for k in _SLOT_KEYS
            }
            slots.append(slot if all(slot.values()) else None)
        return slots

    def _program_time_values(self) -> tuple[str, ...]:
        """Read all six program boundaries without guessing or reordering."""
        slots = self._program_slots()
        if len(slots) != _DEFAULT_PROGRAM_COUNT or any(slot is None for slot in slots):
            raise DeyeScheduleError("Deye schedule requires six complete slots")
        values: list[str] = []
        for slot in slots:
            assert slot is not None
            state = self._get_state(slot["time"])
            if state is None or not self._state_is_usable(state):
                raise DeyeScheduleError("Deye program boundary state is unavailable")
            values.append(self._normalise_time(state.state))
        validate_deye_boundaries(values)
        return tuple(values)

    def _validate_work_mode(self) -> str:
        """Return an error for any ambiguous Work Mode mapping/state."""
        if not self._work_mode_control:
            return ""
        if self._work_mode_entity.split(".", 1)[0] != "select":
            return "Deye Work Mode entity must be select.*"
        state = self._get_state(self._work_mode_entity)
        if state is None or not self._state_is_usable(state):
            return "Deye Work Mode state is unavailable"
        options = getattr(state, "attributes", {}).get("options", [])
        load_first = self._work_mode_options["load_first"]
        battery_first = self._work_mode_options["battery_first"]
        if not load_first or not battery_first or load_first == battery_first:
            return "Deye Work Mode mappings must be explicit and distinct"
        if load_first not in options or battery_first not in options:
            return "Deye Work Mode mappings are not offered select options"
        if state.state not in options:
            return "Deye Work Mode state is not an offered option"
        if self._force_charge_work_mode not in self._work_mode_options:
            return "Deye force-charge Work Mode must be load_first or battery_first"
        return ""

    def _validate_system_work_mode(self) -> str:
        """(#827) Return an error for any ambiguous System Work Mode setup."""
        if not self._system_work_mode_control:
            return ""
        if self._system_work_mode_entity.split(".", 1)[0] != "select":
            return "Deye System Work Mode entity must be select.*"
        state = self._get_state(self._system_work_mode_entity)
        if state is None or not self._state_is_usable(state):
            return "Deye System Work Mode state is unavailable"
        options = getattr(state, "attributes", {}).get("options", [])
        labels = list(self._system_work_mode_options.values())
        if any(not v for v in labels) or len(set(labels)) != 3:
            return "Deye System Work Mode mappings must be explicit and distinct"
        missing = [v for v in labels if v not in options]
        if missing:
            return (f"Deye System Work Mode option not offered by the "
                    f"entity: {missing[0]}")
        if state.state not in options:
            return "Deye System Work Mode state is not an offered option"
        return ""

    @staticmethod
    def discharge_rate_caveat() -> str:
        """(#827) Selling First sells at the INVERTER's own rate — SEM's
        watts figure is advisory on this brand. Saying so beats pretending."""
        return ("discharge rate is set by the inverter in Selling First — "
                "SEM selects the mode, the inverter chooses the power")

    async def command_force_discharge(self, watts: float,
                                      floor_soc=None) -> bool:
        """(#827) The brand's FIRST discharge surface: flip the export
        policy to Selling First. ``watts`` is advisory here — see
        discharge_rate_caveat — and the prior mode is captured for the
        stop's restore."""
        if not self._system_work_mode_control:
            return False
        if self._observer_mode or self._actuation_enabled is not True:
            return False
        err = self._validate_system_work_mode()
        if err:
            self._last_error = err
            return False
        state = self._get_state(self._system_work_mode_entity)
        current = getattr(state, "state", None)
        selling = self._system_work_mode_options["selling_first"]
        if current and current != selling:
            self._system_mode_prior = str(current)
        ok = await self._write_and_verify(
            self._system_work_mode_entity, selling, "select")
        return bool(ok)

    async def command_stop_force_discharge(self) -> bool:
        """(#827) Restore the pre-spend mode. With no captured prior (a
        restart mid-spend), fall back to Zero Export To Load — the SAFE
        direction: a Deye left in Selling First sells the whole pack."""
        if not self._system_work_mode_control:
            return False
        if self._observer_mode or self._actuation_enabled is not True:
            return False
        target = self._system_mode_prior or \
            self._system_work_mode_options["zero_export_to_load"]
        self._system_mode_prior = None
        ok = await self._write_and_verify(
            self._system_work_mode_entity, target, "select")
        return bool(ok)

    # ─── Capability ────────────────────────────────────────────

    def capability(self) -> DeyeCapability:
        """Fail-closed forced-charge capability from current states/config.

        Returns :class:`DeyeCapability` with ``available=False`` and a
        clear ``reason`` for the first problem found. A single missing,
        mis-shaped, stale or non-finite entity flips the whole result off.
        """
        now = dt_util.utcnow()
        reason = ""

        # 1. Grid-charge switch must be a switch.* entity.
        st_switch = self._get_state(self._grid_charge_switch)
        if st_switch is None:
            reason = "grid-charge switch entity missing/not configured"
            return self._unavailable(reason)
        sw_domain = (self._grid_charge_switch or "").split(".", 1)[0]
        if sw_domain != "switch":
            reason = (
                f"grid-charge switch must be switch.* domain, got "
                f"{self._grid_charge_switch!r}"
            )
            return self._unavailable(reason)
        if not self._state_is_usable(st_switch):
            return self._unavailable("grid-charge switch state unavailable")
        if self._normalise_switch(st_switch.state) is None:
            return self._unavailable("grid-charge switch state must be on or off")

        # 2. Charge-current entity: number/input_number, unit A, sane range.
        st_current = self._get_state(self._charge_current_entity)
        if st_current is None:
            reason = "charge-current entity missing/not configured"
            return self._unavailable(reason)
        cur_domain = (self._charge_current_entity or "").split(".", 1)[0]
        if cur_domain not in _NUMERIC_DOMAINS:
            reason = (
                f"charge-current entity must be number/input_number domain, "
                f"got {self._charge_current_entity!r}"
            )
            return self._unavailable(reason)
        if not self._state_is_usable(st_current):
            return self._unavailable("charge-current state unavailable")
        cur_attrs = getattr(st_current, "attributes", None) or {}
        if cur_attrs.get("unit_of_measurement") != "A":
            reason = "charge-current entity must have unit A"
            return self._unavailable(reason)
        cur_min = cur_attrs.get("min")
        cur_max = cur_attrs.get("max")
        if not (isinstance(cur_min, (int, float)) and isinstance(cur_max, (int, float))):
            reason = "charge-current entity missing numeric min/max"
            return self._unavailable(reason)
        if not (math.isfinite(float(cur_min)) and math.isfinite(float(cur_max))):
            reason = "charge-current entity min/max must be finite"
            return self._unavailable(reason)
        if not (0.0 <= float(cur_min) <= float(cur_max)):
            reason = "charge-current entity range must satisfy 0 <= min <= max"
            return self._unavailable(reason)
        current_value = self._parse_number(st_current.state)
        if (
            current_value is None
            or not math.isfinite(current_value)
            or not float(cur_min) <= current_value <= float(cur_max)
        ):
            return self._unavailable("charge-current state must be finite and within range")
        if self._voltage_max_age_s is None:
            return self._unavailable("battery-voltage max age must be finite and > 0")

        # 3. Voltage entity: positive, finite numeric state, fresh.
        st_voltage = self._get_state(self._voltage_entity)
        if st_voltage is None:
            reason = "battery-voltage entity missing/not configured"
            return self._unavailable(reason)
        if not self._state_is_usable(st_voltage):
            return self._unavailable("battery-voltage state unavailable")
        voltage = self._finite_gt0(self._parse_number(getattr(st_voltage, "state", None)))
        if voltage is None or voltage < _MIN_BATTERY_VOLTAGE_V:
            reason = "battery-voltage state must be finite and at least 40 V"
            return self._unavailable(reason)
        age = self._state_age_s(st_voltage, now)
        if age is None:
            reason = "battery-voltage state has no usable timestamp (stale)"
            return self._unavailable(reason)
        if age > self._voltage_max_age_s:
            reason = (
                f"battery-voltage state is stale ({age:.0f}s > "
                f"{self._voltage_max_age_s:.0f}s max age)"
            )
            return self._unavailable(reason)

        # 4. Effective max charge current = min(entity max, safe, BMS).
        if self._safe_max_current is None:
            return self._unavailable(
                "configured safe max charge current must be finite and > 0"
            )
        if (
            self._bms_max_current_raw is not None
            and self._bms_max_current is None
        ):
            return self._unavailable("BMS max charge current must be finite and > 0")
        entity_max = float(cur_max)
        terms = [entity_max, self._safe_max_current]
        if self._bms_max_current is not None:
            terms.append(self._bms_max_current)
        effective_current = min(terms)
        if not (math.isfinite(effective_current) and effective_current > 0):
            reason = "effective max charge current must be finite and > 0"
            return self._unavailable(reason)

        # 5. Program control: require all 6 complete + valid slots.
        if self._program_control:
            slots = self._program_slots()
            if len(slots) != _DEFAULT_PROGRAM_COUNT:
                reason = (
                    f"program control requires {_DEFAULT_PROGRAM_COUNT} "
                    f"slots, got {len(slots)}"
                )
                return self._unavailable(reason)
            for idx, slot in enumerate(slots, start=1):
                if slot is None:
                    reason = f"program slot {idx} incomplete (time/soc/charge)"
                    return self._unavailable(reason)
                slot_reason = self._validate_slot(slot, idx)
                if slot_reason:
                    return self._unavailable(slot_reason)
            try:
                self._program_time_values()
            except DeyeScheduleError as err:
                return self._unavailable(str(err))

        work_mode_reason = self._validate_work_mode()
        if work_mode_reason:
            return self._unavailable(work_mode_reason)
        system_mode_reason = self._validate_system_work_mode()
        if system_mode_reason:
            return self._unavailable(system_mode_reason)

        return DeyeCapability(
            available=True,
            reason="ok",
            max_charge_current_a=effective_current,
            battery_voltage_age_s=age,
            snapshot_supported=self._snapshot_supported,
            readback_supported=self._readback_supported,
            restore_supported=self._restore_supported,
        )

    @staticmethod
    def _parse_number(raw):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _validate_slot(self, slot: dict, idx: int) -> str:
        """Validate one program slot; return a reason string or ''."""
        # SOC entity: number/input_number, unit %, min<=0 and max>=100.
        soc_eid = slot.get("soc", "")
        st_soc = self._get_state(soc_eid)
        if st_soc is None:
            return f"program slot {idx} SOC entity missing ({soc_eid!r})"
        if not self._state_is_usable(st_soc):
            return f"program slot {idx} SOC state unavailable"
        soc_domain = soc_eid.split(".", 1)[0]
        if soc_domain not in _NUMERIC_DOMAINS:
            return f"program slot {idx} SOC must be number/input_number"
        soc_attrs = getattr(st_soc, "attributes", None) or {}
        if soc_attrs.get("unit_of_measurement") != "%":
            return f"program slot {idx} SOC must have unit %"
        soc_min = soc_attrs.get("min")
        soc_max = soc_attrs.get("max")
        if not (isinstance(soc_min, (int, float)) and isinstance(soc_max, (int, float))):
            return f"program slot {idx} SOC missing numeric min/max"
        if not (math.isfinite(float(soc_min)) and math.isfinite(float(soc_max))):
            return f"program slot {idx} SOC min/max must be finite"
        soc_value = self._parse_number(st_soc.state)
        if (
            soc_value is None
            or not math.isfinite(soc_value)
            or not 0 <= soc_value <= 100
        ):
            return f"program slot {idx} SOC state must be finite and within 0-100"
        if not (float(soc_min) <= 0.0 and float(soc_max) >= 100.0):
            return (
                f"program slot {idx} SOC range must satisfy min<=0 and "
                f"max>=100"
            )

        # Charging select: options must include Disabled and Grid.
        charge_eid = slot.get("charge", "")
        st_charge = self._get_state(charge_eid)
        if st_charge is None:
            return f"program slot {idx} charging select missing ({charge_eid!r})"
        if not self._state_is_usable(st_charge):
            return f"program slot {idx} charging select state unavailable"
        charge_domain = charge_eid.split(".", 1)[0]
        if charge_domain not in _SELECT_DOMAINS:
            return f"program slot {idx} charging select must be select/input_select"
        charge_attrs = getattr(st_charge, "attributes", None) or {}
        options = charge_attrs.get("options") or []
        if "Disabled" not in options or "Grid" not in options:
            return (
                f"program slot {idx} charging select must offer Disabled "
                f"and Grid options"
            )
        if str(st_charge.state) not in options:
            return f"program slot {idx} charging select state is not an offered option"

        # Time entity must be HA's writable time domain.
        time_eid = slot.get("time", "")
        st_time = self._get_state(time_eid)
        if st_time is None:
            return f"program slot {idx} time entity missing ({time_eid!r})"
        if time_eid.split(".", 1)[0] != "time":
            return f"program slot {idx} time entity must be time.*"
        if not self._state_is_usable(st_time):
            return f"program slot {idx} time state unavailable"
        try:
            time.fromisoformat(self._normalise_time(st_time.state))
        except ValueError:
            return f"program slot {idx} time state is invalid"
        return ""

    def _unavailable(self, reason: str) -> DeyeCapability:
        return DeyeCapability(
            available=False,
            reason=reason,
            max_charge_current_a=0.0,
            battery_voltage_age_s=0.0,
            snapshot_supported=self._snapshot_supported,
            readback_supported=self._readback_supported,
            restore_supported=self._restore_supported,
        )

    # ─── Transactional snapshot/read-back/restore ──────────────

    @property
    def unsafe_latched(self) -> bool:
        return self._unsafe_latched

    # Deliberately no public reset here.  A later control-plane slice must
    # provide an audited operator action; the adapter never clears the latch
    # implicitly.

    def _entity_mapping(self) -> tuple[tuple[str, str], ...]:
        mapping = [
            ("grid_charge_switch", self._grid_charge_switch),
            ("charge_current", self._charge_current_entity),
            ("battery_voltage", self._voltage_entity),
        ]
        if self._work_mode_control:
            mapping.append(("work_mode", self._work_mode_entity))
        for index, slot in enumerate(self._program_slots(), start=1):
            if slot:
                mapping.extend(
                    (f"program_{index}_{key}", slot[key]) for key in _SLOT_KEYS
                )
        return tuple(mapping)

    @staticmethod
    def _normalise_time(value: Any) -> str:
        text = str(value).strip()
        parts = text.split(":")
        if len(parts) == 2:
            text += ":00"
        return text

    @staticmethod
    def _normalise_switch(value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text == "on":
            return True
        if text == "off":
            return False
        return None

    async def _store_call(self, method: str, *args):
        if self._snapshot_store is None:
            raise RuntimeError("Deye snapshot store is not configured")
        fn = getattr(self._snapshot_store, method, None)
        if fn is None:
            raise RuntimeError(f"Deye snapshot store lacks {method}")
        result = fn(*args)
        return await result if inspect.isawaitable(result) else result

    async def _store_unsafe(self, value: bool) -> None:
        if self._snapshot_store is None:
            return
        fn = getattr(self._snapshot_store, "async_set_unsafe", None)
        if fn is None:
            return
        try:
            result = fn(value)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Deye: failed to persist unsafe latch")

    async def _load_snapshot(self) -> Optional[DeyeControlSnapshot]:
        if self._snapshot is not None:
            self._snapshot_load_failed = False
            return self._snapshot
        self._snapshot_load_failed = False
        if self._snapshot_store is None:
            # No store configured is a CONFIGURATION, not a failure: there
            # is nothing to load and nothing pending. Treating it as a load
            # failure would latch the adapter unsafe on the first
            # command_normal of every store-less install.
            return None
        try:
            raw = await self._store_call("async_load")
            if raw:
                self._snapshot = DeyeControlSnapshot.from_dict(raw)
        except Exception as err:  # noqa: BLE001
            self._snapshot_load_failed = True
            self._last_error = f"snapshot load failed: {err}"
            return None
        return self._snapshot

    async def _clear_snapshot(self) -> bool:
        try:
            await self._store_call("async_clear")
        except Exception as err:  # noqa: BLE001
            self._last_error = f"snapshot clear failed: {err}"
            return False
        self._snapshot = None
        self._session_first_write_at = None
        return True

    def _snapshot_scope_valid(
        self, snapshot: DeyeControlSnapshot, *, require_fresh: bool,
    ) -> tuple[bool, str]:
        if snapshot.schema_version != 2:
            return False, "snapshot schema mismatch"
        if (
            not snapshot.session_id
            or not math.isfinite(snapshot.created_at)
            or len(snapshot.program_times) != 6
            or len(snapshot.program_socs) != 6
            or len(snapshot.program_charging) != 6
            or not math.isfinite(snapshot.charge_current_a)
        ):
            return False, "snapshot structure is invalid"
        current_state = self._get_state(self._charge_current_entity)
        current_min = self._parse_number(
            getattr(current_state, "attributes", {}).get("min")
            if current_state is not None else None
        )
        current_max = self._parse_number(
            getattr(current_state, "attributes", {}).get("max")
            if current_state is not None else None
        )
        if (
            current_min is None
            or current_max is None
            or not math.isfinite(current_min)
            or not math.isfinite(current_max)
            or not 0 <= current_min <= current_max
            or not current_min <= snapshot.charge_current_a <= current_max
        ):
            return False, "snapshot charge current is outside entity range"
        slots = self._program_slots()
        if len(slots) != 6 or any(slot is None for slot in slots):
            return False, "snapshot requires six complete program slots"
        for index, slot in enumerate(slots):
            assert slot is not None
            soc = snapshot.program_socs[index]
            if not math.isfinite(soc) or not 0 <= soc <= 100:
                return False, "snapshot program SOC is invalid"
            charge_state = self._get_state(slot["charge"])
            options = getattr(charge_state, "attributes", {}).get("options", [])
            if snapshot.program_charging[index] not in options:
                return False, "snapshot program charging source is invalid"
        try:
            validate_deye_boundaries(snapshot.program_times)
        except DeyeScheduleError:
            return False, "snapshot program times are invalid"
        if self._work_mode_control:
            mode_state = self._get_state(self._work_mode_entity)
            mode_options = getattr(mode_state, "attributes", {}).get("options", [])
            if not snapshot.work_mode or snapshot.work_mode not in mode_options:
                return False, "snapshot Work Mode is invalid"
        elif snapshot.work_mode:
            return False, "snapshot unexpectedly contains Work Mode"
        if not self._config_entry_id or not self._battery_id:
            return False, "config entry and battery scope are required"
        if snapshot.config_entry_id != self._config_entry_id:
            return False, "snapshot config-entry scope mismatch"
        if snapshot.battery_id != self._battery_id:
            return False, "snapshot battery scope mismatch"
        if snapshot.entity_mapping != self._entity_mapping():
            return False, "snapshot entity mapping mismatch"
        now_ts = dt_util.utcnow().timestamp()
        if snapshot.created_at > now_ts:
            return False, "snapshot timestamp is in the future"
        if require_fresh:
            if self._snapshot_max_age_s is None:
                return False, "snapshot max age must be finite and > 0"
            if now_ts - snapshot.created_at > self._snapshot_max_age_s:
                return False, "snapshot is stale"
        if (
            self._session_first_write_at is not None
            and snapshot.created_at > self._session_first_write_at
        ):
            return False, "snapshot was not created before first write"
        return True, "ok"

    async def _take_snapshot(self, session_id: str) -> Optional[DeyeControlSnapshot]:
        capability = self.capability()
        slots = self._program_slots()
        if not capability.available:
            self._last_error = capability.reason
            return None
        if not self._program_control or len(slots) != 6 or any(s is None for s in slots):
            self._last_error = "snapshot requires six complete Deye program slots"
            return None
        switch_state = self._get_state(self._grid_charge_switch)
        current_state = self._get_state(self._charge_current_entity)
        enabled = self._normalise_switch(getattr(switch_state, "state", None))
        current = self._parse_number(getattr(current_state, "state", None))
        if enabled is None or current is None or not math.isfinite(current):
            self._last_error = "snapshot contains invalid switch/current state"
            return None
        times: list[str] = []
        socs: list[float] = []
        charging: list[str] = []
        for slot in slots:
            assert slot is not None
            time_state = self._get_state(slot["time"])
            soc_state = self._get_state(slot["soc"])
            charge_state = self._get_state(slot["charge"])
            if not all(
                self._state_is_usable(state)
                for state in (time_state, soc_state, charge_state)
            ):
                self._last_error = "snapshot program state unavailable"
                return None
            soc = self._parse_number(getattr(soc_state, "state", None))
            if soc is None or not math.isfinite(soc):
                self._last_error = "snapshot program SOC is invalid"
                return None
            times.append(self._normalise_time(time_state.state))
            socs.append(soc)
            charging.append(str(charge_state.state))
        work_mode = ""
        if self._work_mode_control:
            work_mode_state = self._get_state(self._work_mode_entity)
            if work_mode_state is None or not self._state_is_usable(work_mode_state):
                self._last_error = "snapshot Work Mode state unavailable"
                return None
            work_mode = str(work_mode_state.state)
        snapshot = DeyeControlSnapshot(
            schema_version=2,
            config_entry_id=self._config_entry_id,
            battery_id=self._battery_id,
            session_id=session_id,
            created_at=dt_util.utcnow().timestamp(),
            entity_mapping=self._entity_mapping(),
            grid_charge_enabled=enabled,
            charge_current_a=current,
            program_times=tuple(times),
            program_socs=tuple(socs),
            program_charging=tuple(charging),
            work_mode=work_mode,
        )
        valid, reason = self._snapshot_scope_valid(snapshot, require_fresh=True)
        if not valid:
            self._last_error = reason
            return None
        try:
            await self._store_call("async_save", snapshot.to_dict())
            persisted_raw = await self._store_call("async_load")
            persisted = DeyeControlSnapshot.from_dict(persisted_raw)
        except Exception as err:  # noqa: BLE001
            self._last_error = f"snapshot persistence failed: {err}"
            return None
        if persisted != snapshot:
            self._last_error = "snapshot persistence read-back mismatch"
            return None
        self._snapshot = snapshot
        return snapshot

    def _read_matches(self, entity_id: str, expected: Any, kind: str) -> bool:
        state = self._get_state(entity_id)
        if state is None or not self._state_is_usable(state):
            return False
        actual = state.state
        if kind == "number":
            parsed = self._parse_number(actual)
            return (
                parsed is not None
                and math.isfinite(parsed)
                and math.isclose(parsed, float(expected), abs_tol=1e-6)
            )
        if kind == "switch":
            return self._normalise_switch(actual) is bool(expected)
        if kind == "time":
            return self._normalise_time(actual) == self._normalise_time(expected)
        return str(actual) == str(expected)

    async def _write_and_verify(
        self, entity_id: str, value: Any, kind: str,
    ) -> bool:
        domain = entity_id.split(".", 1)[0]
        if kind == "switch":
            service = "turn_on" if bool(value) else "turn_off"
            data = {"entity_id": entity_id}
        elif kind == "select":
            service = "select_option"
            data = {"entity_id": entity_id, "option": value}
        elif kind == "time":
            service = "set_value"
            data = {"entity_id": entity_id, "time": self._normalise_time(value)}
        else:
            service = "set_value"
            data = {"entity_id": entity_id, "value": float(value)}
        try:
            if self._session_first_write_at is None:
                self._session_first_write_at = dt_util.utcnow().timestamp()
            await self._hass.services.async_call(
                domain, service, data, blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            self._last_error = f"write failed for {entity_id}: {err}"
            return False
        attempts = self._readback_attempts
        delay = self._readback_delay_s
        for attempt in range(attempts):
            if self._read_matches(entity_id, value, kind):
                return True
            if attempt + 1 < attempts:
                await asyncio.sleep(delay)
        self._last_error = f"read-back mismatch for {entity_id}"
        return False

    async def _restore_snapshot(self, snapshot: DeyeControlSnapshot) -> bool:
        valid, reason = self._snapshot_scope_valid(snapshot, require_fresh=False)
        if not valid:
            self._last_error = reason
            return False
        slots = self._program_slots()
        safe_zero = await self._write_and_verify(
            self._charge_current_entity, 0.0, "number",
        )
        safe_off = await self._write_and_verify(
            self._grid_charge_switch, False, "switch",
        )
        if not (safe_zero and safe_off):
            self._unsafe_latched = True
            await self._store_unsafe(True)
            self._last_error = self._last_error or (
                "Deye rollback could not establish zero-current/switch-off state"
            )
            return False
        ok = True
        for index, slot in enumerate(slots):
            assert slot is not None
            ok = await self._write_and_verify(
                slot["time"], snapshot.program_times[index], "time",
            ) and ok
            ok = await self._write_and_verify(
                slot["soc"], snapshot.program_socs[index], "number",
            ) and ok
            ok = await self._write_and_verify(
                slot["charge"], snapshot.program_charging[index], "select",
            ) and ok
        if self._work_mode_control:
            ok = await self._write_and_verify(
                self._work_mode_entity, snapshot.work_mode, "select",
            ) and ok
        ok = await self._write_and_verify(
            self._charge_current_entity, snapshot.charge_current_a, "number",
        ) and ok
        ok = await self._write_and_verify(
            self._grid_charge_switch, snapshot.grid_charge_enabled, "switch",
        ) and ok
        if not ok:
            self._unsafe_latched = True
            await self._store_unsafe(True)
            self._last_error = self._last_error or "Deye rollback read-back failed"
            return False
        return await self._clear_snapshot()

    async def _rollback_after_failure(
        self, snapshot: DeyeControlSnapshot, original_error: str,
    ) -> None:
        restored = await self._restore_snapshot(snapshot)
        if restored:
            self._last_error = f"{original_error}; rollback verified"
        else:
            self._unsafe_latched = True
            await self._store_unsafe(True)
            self._last_error = f"{original_error}; rollback FAILED — unsafe latched"

    # ─── BatteryControlAdapter capability surface ─────────────

    @property
    def max_charge_power_w(self) -> float:
        """Validated current × validated voltage when available, else 0."""
        cap = self.capability()
        if not cap.available:
            return 0.0
        st_voltage = self._get_state(self._voltage_entity)
        voltage = self._finite_gt0(
            self._parse_number(getattr(st_voltage, "state", None))
        )
        if voltage is None:
            return 0.0
        return cap.max_charge_current_a * voltage

    @property
    def max_discharge_power_w(self) -> float:
        """Safe finite discharge config, else 0 (never a state read)."""
        return self._max_discharge_w

    @property
    def supports_forced_charge(self) -> bool:
        """True only behind all hardware, transaction and operator gates."""
        capability = self.capability()
        return bool(
            capability.available
            and capability.snapshot_supported
            and capability.readback_supported
            and capability.restore_supported
            and self._config_entry_id
            and self._battery_id
            and self._program_control
            and self._readback_attempts > 0
            and math.isfinite(self._readback_delay_s)
            and self._readback_delay_s >= 0
            and self._actuation_enabled
            and not self._observer_mode
            and not self._unsafe_latched
        )

    # ─── Commands ──────────────────────────────────────────────

    async def async_recover_pending(self) -> bool:
        """Load the persisted unsafe latch and recover a pending snapshot.

        Called once by the coordinator before the adapter's first actuation.
        Any latch/store failure is fail-closed and leaves active control blocked.
        A persisted unsafe latch is never acknowledged or reset automatically.
        """
        load_latch = getattr(self._snapshot_store, "async_load_latch", None)
        if not callable(load_latch):
            self._unsafe_latched = True
            self._last_error = "Deye unsafe latch store is unavailable"
            await self._store_unsafe(True)
            return False
        try:
            loaded = load_latch()
            if inspect.isawaitable(loaded):
                loaded = await loaded
        except Exception as err:  # noqa: BLE001
            self._unsafe_latched = True
            self._last_error = f"Deye unsafe latch load failed: {err}"
            await self._store_unsafe(True)
            return False
        if type(loaded) is not bool:
            self._unsafe_latched = True
            self._last_error = "Deye unsafe latch payload is invalid"
            await self._store_unsafe(True)
            return False
        self._unsafe_latched = loaded
        if loaded:
            self._last_error = "Deye unsafe latch is set"
            return False
        await self.command_normal()
        return not self._unsafe_latched and not self._snapshot_load_failed

    async def command_normal(self) -> None:
        snapshot = await self._load_snapshot()
        if snapshot is None:
            if self._snapshot_load_failed:
                self._unsafe_latched = True
                await self._store_unsafe(True)
                return
            if self._unsafe_latched:
                self._last_error = "Deye unsafe latch is set"
                return
            self._last_error = None
            self._last_intent = BatteryIntent.NORMAL
            return
        # Restore WRITES 18 registers. The same gates that protect
        # command_force_charge protect the restore path: a persisted
        # snapshot from an earlier actuation-enabled session must not be
        # replayed to the inverter on an observer-mode startup (#702 —
        # the exact class this adapter's contract promises to close).
        # The snapshot is held, not cleared: it replays once the user
        # re-opens the gates.
        if self._observer_mode or not self._actuation_enabled:
            self._last_error = (
                "pending Deye snapshot held: restore requires actuation "
                "enabled and observer mode off"
            )
            return
        restored = await self._restore_snapshot(snapshot)
        if restored:
            if self._unsafe_latched:
                self._last_error = "Deye snapshot restored; unsafe latch remains set"
                return
            self._last_error = None
            self._last_intent = BatteryIntent.NORMAL
        elif not self._unsafe_latched:
            self._unsafe_latched = True
            await self._store_unsafe(True)

    async def command_limit_discharge(self, watts: float) -> None:
        # Deye discharge limiting is intentionally outside this first
        # contract. The intent still records what the coordinator asked
        # for — last_intent tracks the accepted command stream, last_error
        # carries the honesty (sibling adapters' convention).
        self._last_intent = BatteryIntent.LIMIT_DISCHARGE
        self._last_error = "Deye discharge limiting is not implemented"

    async def command_force_charge(
        self, target_soc: float, charge_power_w: float, duration_min: int,
    ) -> None:
        if not self.supports_forced_charge:
            capability = self.capability()
            if self._unsafe_latched:
                reason = "unsafe latch is set"
            elif self._observer_mode:
                reason = "observer mode is active"
            elif not self._actuation_enabled:
                reason = "actuation is not explicitly enabled"
            else:
                reason = capability.reason
            self._last_error = f"Deye force charge blocked: {reason}"
            return
        if any(
            isinstance(value, bool)
            for value in (target_soc, charge_power_w, duration_min)
        ):
            self._last_error = "Deye force charge parameters are invalid"
            return
        try:
            target = float(target_soc)
            requested_power = float(charge_power_w)
            duration = int(duration_min)
        except (TypeError, ValueError, OverflowError):
            self._last_error = "Deye force charge parameters are invalid"
            return
        if not (
            math.isfinite(target)
            and 0 <= target <= 100
            and math.isfinite(requested_power)
            and requested_power > 0
            and duration > 0
        ):
            self._last_error = "Deye force charge parameters are out of range"
            return
        try:
            schedule_now = self._now_provider()
            if not isinstance(schedule_now, datetime):
                raise DeyeScheduleError("current time provider did not return datetime")
            schedule_plan = compile_deye_charge_window(
                self._program_time_values(),
                schedule_now,
                duration,
                target,
            )
        except DeyeScheduleError as err:
            self._last_error = f"Deye schedule compile failed: {err}"
            return
        existing = await self._load_snapshot()
        if self._snapshot_load_failed:
            self._unsafe_latched = True
            await self._store_unsafe(True)
            return
        if existing is not None:
            # The coordinator re-issues FORCE_CHARGE every cycle for the
            # duration of a session (~30 s cadence, like every sibling
            # adapter). A snapshot belonging to the session THIS adapter
            # instance opened is the active session — re-issue is a no-op
            # success, not an error, or last_error flags a healthy session
            # on every cycle. Changed parameters are NOT re-applied
            # mid-session; the inverter holds the compiled plan. A snapshot
            # this instance did NOT open (restart recovery) still refuses:
            # it must replay through command_normal first.
            if self._last_intent is BatteryIntent.FORCE_CHARGE:
                self._last_error = None
                return
            self._last_error = "pending Deye snapshot must be restored before a new session"
            return
        snapshot = await self._take_snapshot(str(uuid4()))
        if snapshot is None:
            return
        valid, reason = self._snapshot_scope_valid(snapshot, require_fresh=True)
        if not valid:
            self._last_error = reason
            return
        voltage_state = self._get_state(self._voltage_entity)
        voltage = self._finite_gt0(
            self._parse_number(getattr(voltage_state, "state", None))
        )
        capability = self.capability()
        if voltage is None or not capability.available:
            await self._rollback_after_failure(snapshot, "voltage/capability changed")
            return
        requested_current = math.floor(requested_power / voltage)
        current = min(float(requested_current), capability.max_charge_current_a)
        if not math.isfinite(current) or current <= 0:
            await self._rollback_after_failure(snapshot, "calculated charge current is zero")
            return
        operations: list[tuple[str, Any, str]] = [
            (self._charge_current_entity, current, "number"),
        ]
        slots = self._program_slots()
        for slot_index in schedule_plan.slot_indices:
            slot = slots[slot_index - 1]
            assert slot is not None
            operations.extend(
                (
                    (slot["soc"], schedule_plan.reserve_soc, "number"),
                    (slot["charge"], schedule_plan.charging_source, "select"),
                )
            )
        if self._work_mode_control:
            operations.append(
                (
                    self._work_mode_entity,
                    self._work_mode_options[self._force_charge_work_mode],
                    "select",
                )
            )
        operations.append((self._grid_charge_switch, True, "switch"))
        for entity_id, value, kind in operations:
            if not await self._write_and_verify(entity_id, value, kind):
                error = self._last_error or f"Deye write failed for {entity_id}"
                await self._rollback_after_failure(snapshot, error)
                return
        valid, reason = self._snapshot_scope_valid(snapshot, require_fresh=False)
        if not valid:
            await self._rollback_after_failure(snapshot, reason)
            return
        self._last_error = None
        self._last_intent = BatteryIntent.FORCE_CHARGE

    async def command_stop_force_charge(self) -> None:
        # (#757) The restore below is a Store read plus a hardware write.
        # Once it has landed there is nothing left to restore, so a
        # repeat is pure cost. The intent is only ever set on a
        # successful restore, so an unsafe latch or a held write never
        # trips this guard — those paths retry, as they must.
        if self._force_charge_already_stopped():
            return
        snapshot = await self._load_snapshot()
        if snapshot is None:
            if self._snapshot_load_failed:
                self._unsafe_latched = True
                await self._store_unsafe(True)
                return
            if self._unsafe_latched:
                self._last_error = "Deye unsafe latch is set"
                return
            self._last_error = None
            self._last_intent = BatteryIntent.STOP_FORCE_CHARGE
            return
        # Same write gate as command_normal — restore is a hardware write.
        if self._observer_mode or not self._actuation_enabled:
            self._last_error = (
                "pending Deye snapshot held: restore requires actuation "
                "enabled and observer mode off"
            )
            return
        restored = await self._restore_snapshot(snapshot)
        if restored:
            if self._unsafe_latched:
                self._last_error = "Deye snapshot restored; unsafe latch remains set"
                return
            self._last_error = None
            self._last_intent = BatteryIntent.STOP_FORCE_CHARGE
        elif not self._unsafe_latched:
            self._unsafe_latched = True
            await self._store_unsafe(True)
