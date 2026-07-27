"""#680 — the ``%`` "At least" floor must reach 0, like the kWh floor already does.

Follow-up to #679/#634, and the layer @onkelfu's #627 install actually sits on.

Guido's model (settled): the overnight floor is the *single* night-charge control —
night charge always tops up the gap between surplus and that target, and **floor 0
means no night charge**. No boolean opt-in. So "I don't want overnight charging" has
to be expressible by setting the floor to 0.

It was not, on the ``%`` path: ``ev_target_soc`` was pinned at ``min=50`` on the
per-charger number entity (which the config-card knob mirrors, ``_renderZoneKnob``
reads ``e.attributes.min``) and on all three options-flow steps. The kWh floor
(``daily_ev_target``) already reached 0. The fix lowers the ``%`` *floor* to 0 in
those four places; the ``_max`` solar **ceiling** is lowered to 0 too, so both
handles span 0–100 and the SOC target matches the kWh target (Guido: "the soc
range is 0 to 100%"). The runtime clamps the effective ceiling to ``>= floor``
(``_resolve_target``), so a Max below the Min is harmless, and daytime charging
follows the ceiling — ``At least = 0`` removes only the overnight grid guarantee.

This guard pins both halves: the value 0 is reachable in source (regression to 50
was the bug), and 0 actually reads as "no night charge" at the gate.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from custom_components.solar_energy_management.consts.ev_charge_modes import (
    mode_allows_night_charging,
)

_ROOT = Path(__file__).resolve().parents[1]
_FLOW = (_ROOT / "config_flow.py").read_text()
_NUMBER = (_ROOT / "number.py").read_text()


def _floor_slider_mins() -> list[int]:
    """The ``min=`` of every ``ev_target_soc`` FLOOR slider in the options flow.

    Line-scanned rather than one big regex so the single-line and split-arg
    ``NumberSelectorConfig`` formats both match. ``"ev_target_soc",`` (quote +
    comma right after ``soc``) never matches ``"ev_target_soc_max",``.
    """
    lines = _FLOW.splitlines()
    mins: list[int] = []
    for i, line in enumerate(lines):
        if re.search(r'"ev_target_soc",', line):
            for j in range(i, min(i + 8, len(lines))):
                m = re.search(r"\bmin=(\d+)", lines[j])
                if m:
                    mins.append(int(m.group(1)))
                    break
    return mins


def _ceiling_slider_mins() -> list[int]:
    lines = _FLOW.splitlines()
    mins: list[int] = []
    for i, line in enumerate(lines):
        if re.search(r'"ev_target_soc_max",', line):
            for j in range(i, min(i + 8, len(lines))):
                m = re.search(r"\bmin=(\d+)", lines[j])
                if m:
                    mins.append(int(m.group(1)))
                    break
    return mins


@pytest.mark.unit
class TestZeroIsReachableInSource:
    def test_premise_the_scan_finds_the_floor_sliders(self):
        """Fail loudly if the flow is restructured — otherwise an empty list
        would make the min assertion vacuously pass."""
        assert len(_floor_slider_mins()) >= 3, _floor_slider_mins()

    def test_every_soc_floor_slider_reaches_zero(self):
        bad = [m for m in _floor_slider_mins() if m != 0]
        assert not bad, (
            "the % 'At least' floor slider must reach 0 so 'no overnight charge' "
            f"is expressible (#680); found min={bad} — regressed to the min=50 bug"
        )

    def test_number_entity_target_soc_native_min_is_zero(self):
        m = re.search(
            r'key=f"charger_\{cid\}_target_soc",.*?native_min_value=(\d+)',
            _NUMBER, re.S,
        )
        assert m, "charger target_soc entity description not found"
        assert m.group(1) == "0", (
            "the config-card SOC knob mirrors the entity min; it must be 0 so "
            f"0% is settable on the card (#680); native_min={m.group(1)}"
        )

    def test_the_solar_ceiling_also_reaches_zero(self):
        """Both handles span 0–100 so the % target matches the kWh target
        (Guido). Runtime clamps effective ceiling >= floor (_resolve_target)."""
        mins = _ceiling_slider_mins()
        assert mins and all(m == 0 for m in mins), mins


@pytest.mark.unit
class TestZeroFloorMeansNoNightCharge:
    def _cfg(self, **charger):
        base = {"id": "ev_charger", "charge_mode": "solar_only",
                "ev_target_type": "soc"}
        base.update(charger)
        return {"ev_chargers": [base]}

    def test_soc_floor_zero_stays_out_of_the_night_lane(self):
        cfg = self._cfg(ev_target_soc=0)
        assert mode_allows_night_charging(cfg, cfg["ev_chargers"][0]) is False

    def test_a_real_soc_floor_still_opts_in(self):
        cfg = self._cfg(ev_target_soc=50)
        assert mode_allows_night_charging(cfg, cfg["ev_chargers"][0]) is True

    def test_onkelfu_shape_100pct_floor_still_night_charges_until_set_to_zero(self):
        """onkelfu #627: ``ev_target_soc: 100`` DOES opt in — that is the model
        (floor is the control). The fix is that he can now dial it to 0."""
        opted_in = self._cfg(ev_target_soc=100)
        assert mode_allows_night_charging(opted_in, opted_in["ev_chargers"][0]) is True
        opted_out = self._cfg(ev_target_soc=0)
        assert mode_allows_night_charging(opted_out, opted_out["ev_chargers"][0]) is False
