"""A synthetic flat-price night — a TEST fixture, not a shipping API.

This adapter used to live in ``coordinator/overnight_planner.py`` as
``plan_overnight``, where it had no production caller: the coordinator
builds a real ``LedgerSlot`` list and calls ``build_night_ledger`` +
``pack_night`` directly. Two corpora imported the adapter instead, so a
large body of packer tests was exercising a code path that never ran on
anyone's hardware (#758). Moving it here keeps the scenarios — they are
good scenarios — while making what they assume impossible to mistake for
what SEM does.

What ``pack_flat_night`` fakes, and why each fake is safe HERE and would
be a lie in production:

* **every slot is cheap** (``level_cheap=True``) — so ``needs_cheap_level``
  demands are never gated by the tariff classifier. These tests are about
  the PACKER's ordering and fitting, not about which hours are cheap;
  the classifier has its own corpus (``test_728_*``).
* **no home load** (``home_w=0.0``) — the house draws nothing, so every
  watt under the cap is available to the demands. Real nights subtract
  the forecast house load first.
* **an effectively infinite battery** (``1e9`` kWh unless a budget is
  given, ``floor_kwh=0``, ``max_discharge_w=1e9``) — battery sourcing
  never runs out except where a test explicitly sets a budget.
* **no peak limit** (``peak_limit_w=0.0`` — the packer's "unlimited"),
  with the per-slot cap supplied directly as ``cap_override_w``. Real
  nights derive the cap from the hysteresis-adjusted peak target.

A test that wants any of those to be real must build a ledger the way
the coordinator does, not extend this.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from custom_components.solar_energy_management.coordinator.overnight_planner import (
    LedgerSlot, build_night_ledger, pack_night,
)


@dataclass(frozen=True)
class PriceSlot:
    """One flat market slot with an explicit power cap."""

    start: datetime
    end: datetime
    price: float
    cap_w: float

    @property
    def hours(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 3600.0)


def pack_flat_night(demands, slots, battery_budget_kwh=float("inf")):
    """Pack ``demands`` into flat ``slots`` — see the module docstring."""
    budget = (1e9 if battery_budget_kwh == float("inf")
              else float(battery_budget_kwh))
    ledger = [LedgerSlot(start=s.start, end=s.end, price=s.price,
                         level_cheap=True, home_w=0.0,
                         cap_override_w=float(s.cap_w)) for s in slots]
    ledger = build_night_ledger(
        ledger, soc_kwh=budget, floor_kwh=0.0,
        max_discharge_w=1e9, peak_limit_w=0.0)
    return pack_night(demands, ledger, floor_kwh=0.0,
                      max_discharge_w=1e9, peak_limit_w=0.0)
