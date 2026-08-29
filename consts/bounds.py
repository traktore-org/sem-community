"""#828 — every tunable's range, declared ONCE.

Bug class 50 ("a field narrower than the thing it describes") produced four
reported bugs — #717 peak sliders on an 80 kW service, #746 every EVSE
ceilinged at 32 A, #813 options pages rejecting values SEM itself stored,
#826 a Deye write ceiling capped below its own BMS ceiling — plus two more
the audit found before any user did. One structure caused all six: a range
written twice, once for the options form and once for the runtime entity,
with nothing deriving one from the other. Agreement was a coincidence
maintained by attention; drift was the default.

So the range lives here, and both surfaces are BUILT from it:

    config_flow.py   ->  bounds_selector("daily_ev_target")
    number.py        ->  BOUNDS["daily_ev_target"].min / .max / .step

A field cannot drift from itself. ``tests/test_828_one_bounds_table.py``
keeps it that way, and its shrink-only allowlist makes the remaining
migration finish instead of stalling.

``at_most`` / ``at_least`` give the OTHER half of the class a home: two
fields that constrain each other (SEM's write ceiling ≤ the BMS ceiling;
the emergency peak above the target peak). That relationship previously
existed only in someone's head, which is why #826 and #813's second half
were both found by users rather than by us.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Range:
    """One tunable's range, for every surface that offers it."""

    min: float
    max: float
    step: float = 1
    unit: str = ""
    at_most: Optional[str] = None
    """This field must be settable at least as high as that field — SEM's
    ceiling can never be lower than the ceiling it sits under (#826)."""
    at_least: Optional[str] = None

    def selector_kwargs(self, mode="box") -> dict:
        """Kwargs for ``selector.NumberSelectorConfig``.

        ``mode`` stays with the CALL SITE on purpose. The table owns the
        correctness contract — min, max, step, unit — because that is what
        drifts and what refuses a user's value. Presentation is not that:
        ``battery_capacity_kwh`` is legitimately a slider on one page and a
        box on another, and folding that in would make this refactor change
        somebody's UI while claiming to change nothing.
        """
        out = {"min": self.min, "max": self.max, "step": self.step,
               "mode": mode}
        if self.unit:
            out["unit_of_measurement"] = self.unit
        return out


BOUNDS: dict[str, Range] = {
    # ── EV targets (#746, #813) ──────────────────────────────────────
    # 0-200 kWh: a 100 kWh cap could not re-save a stored 200 (#813).
    "daily_ev_target": Range(0, 200, step=0.5, unit="kWh"),
    "daily_ev_target_max": Range(0, 200, step=0.5, unit="kWh"),
    "ev_battery_capacity_kwh": Range(10, 120, step=5, unit="kWh"),
    # ── charge pacing (#820, 2.1 audit item 6) ──────────────────────
    # The inverter's AC output limit; 0 = not set (clipping guard off).
    "inverter_ac_limit_w": Range(0, 100000, step=100, unit="W"),
    "ev_kwh_per_100km": Range(8, 50, step=0.5, unit="kWh/100km"),

    # ── Home battery ─────────────────────────────────────────────────
    # Two pages declared this with different minimums AND steps (min 5/step 1
    # vs min 1/step 0.5): a 3 kWh pack saved on one was refused by the other,
    # and 7.5 was not representable on one of them. Found by the #828 audit,
    # never reported. One row, one answer.
    "battery_capacity_kwh": Range(1, 100, step=0.5, unit="kWh"),

    # ── heat pumps (#685) ────────────────────────────────────────────
    "heat_pump_rated_power": Range(100, 30000, step=100, unit="W"),
    "heat_pump_force_on_threshold": Range(0, 30000, step=100, unit="W"),

    # ── Deye forced grid charging (#826) ─────────────────────────────
    # The pair that started this: SEM's write ceiling is bounded BY the BMS
    # ceiling (the adapter takes min(entity, this, BMS)), so it can never
    # sensibly be the LOWER of the two. ``at_most`` states that, and the test
    # enforces it — the relationship is no longer only in a comment.
    "deye_max_charge_current_a": Range(
        1, 200, step=1, unit="A", at_most="deye_bms_max_charge_current_a"),
    "deye_bms_max_charge_current_a": Range(0, 200, step=1, unit="A"),
}


def bounds_selector(key: str, mode="box"):
    """Build the options-flow number selector for ``key`` from the table.

    Used instead of a literal ``NumberSelectorConfig(min=…, max=…)`` so a
    form can never disagree with the entity that writes the same value.
    """
    from homeassistant.helpers import selector  # local: keep this module pure

    return selector.NumberSelector(
        selector.NumberSelectorConfig(**BOUNDS[key].selector_kwargs(mode))
    )
