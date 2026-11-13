"""(#1321) Each planned demand says why its runs landed where they did.

The Plan card's "Why this plan" list shows one line per demand. The code is
read off what the packer did; the card only translates it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator.energy_planner import (
    Allocation, LedgerSlot, demand_why,
)

TZ = timezone(timedelta(hours=1))
T0 = datetime(2026, 11, 13, 22, 0, tzinfo=TZ)


def _slot(h, price, sun=False):
    s = LedgerSlot(start=T0 + timedelta(hours=h), end=T0 + timedelta(hours=h + 1), price=price)
    if sun:
        s.cap_override_w = 2000.0
    return s


def _a(h, price, late=False, w=2000.0):
    return Allocation(demand_id="ev:x", start=T0 + timedelta(hours=h),
                      end=T0 + timedelta(hours=h + 1), power_w=w, price=price,
                      reason="", late=late)


LEDGER = [_slot(0, 0.30), _slot(1, 0.10), _slot(2, 0.12), _slot(3, 0.40)]


@pytest.mark.unit
def test_cheapest_hours_carry_the_average_price():
    why = demand_why([_a(1, 0.10), _a(2, 0.12)], LEDGER)
    assert why["code"] == "cheapest_hours"
    assert why["params"]["price"] == pytest.approx(0.11)
    assert why["params"]["from"] == (T0 + timedelta(hours=1)).isoformat()
    assert why["params"]["to"] == (T0 + timedelta(hours=3)).isoformat()


@pytest.mark.unit
@pytest.mark.parametrize("allocs, ledger, source, code", [
    ([_a(0, 0.36)], [_slot(0, 0.36), _slot(1, 0.36)], "grid", "one_rate"),
    ([_a(0, 0.0)], [_slot(0, 0.0, sun=True)], "grid", "on_sun"),
    ([_a(3, 0.40, late=True)], LEDGER, "grid", "before_departure"),
    ([_a(1, None)], [_slot(1, None), _slot(2, 0.2)], "grid", "unpriced_hours"),
    ([_a(1, 0.10)], LEDGER, "battery", "from_battery"),
])
def test_each_reason(allocs, ledger, source, code):
    assert demand_why(allocs, ledger, source)["code"] == code


@pytest.mark.unit
def test_nothing_placed_gives_none():
    assert demand_why([], LEDGER) is None


@pytest.mark.unit
def test_the_plan_rows_carry_it():
    from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
    from .ast_contracts import calls
    assert calls(SEMCoordinator._shadow_energy_plan, "demand_why")


@pytest.mark.unit
def test_every_code_has_a_text_in_every_language():
    import json
    from pathlib import Path
    d = json.loads((Path(__file__).resolve().parent.parent / "dashboard" / "translations.json").read_text())
    for code in ("from_battery", "on_sun", "before_departure", "unpriced_hours", "one_rate", "cheapest_hours"):
        for lang, texts in d.items():
            assert f"plan_why_{code}" in texts, (lang, code)
