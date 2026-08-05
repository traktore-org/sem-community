"""#723 — a view that must BALANCE may not mix SEM's day boundaries.

#645 settled the producer side: SEM has four deliberate day boundaries
(calendar midnight, EV-deadline #279, sunrise-EV, sunrise-gated load day #620),
they cannot be deduplicated, and ``tests/test_645_day_boundary_registry.py``
forces every site that names a day to declare which one it serves.

That registry says nothing about **consumers**, and that is where the next
instance landed. The Energy tab's Sankey is a conservation diagram — its arrows
are supposed to add up — and it drew six calendar-day figures next to one
EV figure bucketed on the charge deadline. Both are individually correct, both
would pass the #645 registry, and the chart is still wrong: between midnight
and the deadline the EV branch carries last night's charge while every source
it is drawn from has already reset.

The requirement no code expressed: **every quantity inside a balancing view
shares one boundary.** This file expresses it, and derives the boundaries from
production source rather than restating them, so it cannot rot into fiction:

* daily energy sensors — parsed out of ``energy_calculator``'s
  ``energy.daily_X = self._get_daily(<category>, <day-variable>)`` lines, then
  the day-variable is mapped to a boundary;
* flow energy sensors — ``flow_calculator`` names its day off
  ``dt_util.now().date()``, i.e. calendar, and that is asserted here too, so
  moving flows onto another boundary trips this guard rather than silently
  unbalancing the same chart.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent

# A card type whose arrows/segments assert a conservation relationship. Adding
# one here is how a new balancing view gets covered.
BALANCING_CARDS = {
    "custom:sankey-chart":
        "sankey arrows are a conservation relationship — sources must equal sinks",
}

# The day-variable names ``energy_calculator`` buckets with, and which of the
# four #645 boundaries each one is. A new variable fails the derivation below
# rather than being silently treated as calendar.
#
# ``ev_day`` is declared as its WORST case: since #724 a disagreeing
# multi-charger fleet falls back to calendar midnight, but any agreeing fleet
# (including every single-charger install) is deadline-bucketed, and a guard
# over a view must hold for every install shape.
DAY_VAR_BOUNDARY = {
    "today": "calendar",
    "ev_day": "ev-deadline",
}

_DAILY_ASSIGN = re.compile(
    r"energy\.(daily_\w+)\s*=\s*self\._get_daily\(\s*[^,]+,\s*(\w+)\s*\)"
)

# --- the one known offender, and the terms of its exemption -----------------
# The fix needs a calendar-day EV sensor. The accumulator already exists on
# develop (``MIDNIGHT_EV_CATEGORY`` / ``_reconcile_midnight_ev_energy``, added
# by #628 for the home balance) but has no sensor surface — and PR #722 adds
# exactly that surface plus the template swap. Duplicating it here would
# collide with a contributor's open PR, so the instance is exempted and the
# exemption SELF-EXPIRES: the moment a calendar-day EV sensor exists in the
# tree, the test below fails until this entry is removed.
KNOWN_MIXED_ENTITIES = {"sensor.sem_daily_ev_energy"}
CALENDAR_EV_FIELD = "daily_calendar_ev"


def _production_files():
    """Python production sources — everything except tests and tooling."""
    excluded = {"tests", "scripts", "node_modules", ".git"}
    return sorted(
        path.relative_to(REPO)
        for path in REPO.rglob("*.py")
        if path.is_file() and not (set(path.relative_to(REPO).parts[:-1]) & excluded)
    )


def _daily_field_boundaries() -> dict[str, str]:
    """field name → boundary, read out of the production source."""
    src = (REPO / "coordinator" / "energy_calculator.py").read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for field, day_var in _DAILY_ASSIGN.findall(src):
        assert day_var in DAY_VAR_BOUNDARY, (
            f"energy_calculator buckets {field} on the unknown day variable "
            f"{day_var!r}. Add it to DAY_VAR_BOUNDARY with which of SEM's four "
            "boundaries it serves — an undeclared one would be assumed "
            "calendar, which is how #723 happened."
        )
        boundary = DAY_VAR_BOUNDARY[day_var]
        assert found.get(field, boundary) == boundary, (
            f"{field} is bucketed on two different boundaries in the same file"
        )
        found[field] = boundary
    assert found, "no daily assignments parsed — the regex has drifted"
    return found


def _entity_boundary(entity_id: str, fields: dict[str, str]) -> str | None:
    """Boundary behind a SEM energy entity, or None if it isn't one."""
    m = re.fullmatch(r"sensor\.sem_(daily_\w+)_energy", entity_id)
    if m and m.group(1) in fields:
        return fields[m.group(1)]
    if re.fullmatch(r"sensor\.sem_flow_\w+_energy", entity_id):
        return "calendar"   # flow_calculator — pinned by the test below
    return None


def _cards(node, out):
    if isinstance(node, dict):
        if isinstance(node.get("type"), str) and node["type"] in BALANCING_CARDS:
            out.append(node)
        for value in node.values():
            _cards(value, out)
    elif isinstance(node, list):
        for value in node:
            _cards(value, out)
    return out


def _balancing_cards():
    template = yaml.safe_load(
        (REPO / "dashboard" / "sem_dashboard_template.yaml").read_text(
            encoding="utf-8"
        )
    )
    return _cards(template, [])


@pytest.mark.unit
class TestBalancingViewsUseOneBoundary723:

    def test_the_template_still_has_a_balancing_view(self):
        """A guard over zero inputs is not a guard (BUG_CLASSES class 8)."""
        assert _balancing_cards(), (
            "no balancing card found in the dashboard template — either the "
            "Sankey was removed (then remove this guard) or the card type "
            "changed (then update BALANCING_CARDS)."
        )

    def test_every_balancing_view_draws_a_single_day_boundary(self):
        fields = _daily_field_boundaries()
        for card in _balancing_cards():
            entities = sorted(set(
                re.findall(r"sensor\.sem_[a-z0-9_]+", yaml.safe_dump(card))
            ))
            by_boundary: dict[str, list[str]] = {}
            for entity in entities:
                if entity in KNOWN_MIXED_ENTITIES:
                    continue
                boundary = _entity_boundary(entity, fields)
                if boundary:
                    by_boundary.setdefault(boundary, []).append(entity)
            assert len(by_boundary) <= 1, (
                f"{card['type']} — {BALANCING_CARDS[card['type']]} — mixes day "
                "boundaries, so its arrows cannot add up:\n"
                + "\n".join(
                    f"  {b}: {', '.join(e)}" for b, e in sorted(by_boundary.items())
                )
                + "\n\nEvery quantity in one balancing view must share a "
                  "boundary. Feed it the mirror accumulated on the view's own "
                  "boundary instead of the one the producer happens to use."
            )

    def test_the_known_exemption_expires_once_the_fix_lands(self):
        """The allowlist may not outlive the thing that justified it.

        The exemption exists only while there is nothing correct to point the
        Sankey at. The moment a calendar-day EV sensor surface exists (PR #722
        adds one) while a balancing card STILL references the exempted
        deadline-day entity, the fix is half-landed and this fails until the
        template is swapped. A PR that lands the sensor and the swap together
        — which is what #722 does — passes cleanly; the stale allowlist entry
        is then pruned by us, not forced into a contributor's PR.
        """
        if not KNOWN_MIXED_ENTITIES:
            return
        src = (REPO / "sensor.py").read_text(encoding="utf-8")
        if CALENDAR_EV_FIELD not in src:
            return  # nothing correct to point at yet — exemption stands
        still_referenced = {
            entity
            for card in _balancing_cards()
            for entity in re.findall(r"sensor\.sem_[a-z0-9_]+", yaml.safe_dump(card))
            if entity in KNOWN_MIXED_ENTITIES
        }
        assert not still_referenced, (
            f"{CALENDAR_EV_FIELD} now has a sensor surface but "
            f"{sorted(still_referenced)} still feed a balancing view — finish "
            "the swap: point the Sankey's EV nodes at the calendar-day sensor "
            "and empty KNOWN_MIXED_ENTITIES."
        )

    def test_the_guard_would_actually_catch_the_original_bug(self):
        """Refute-the-guard: with the exemption lifted, the live template must
        fail. A guard that passes on the known-bad input is decoration.

        Skips (rather than fails) once the template no longer references the
        exempted entity — at that point the instance is fixed, the main test
        covers correctness, and the leftover chore is pruning the allowlist
        (asserted above), not re-proving a bug that no longer exists.
        """
        fields = _daily_field_boundaries()
        card = _balancing_cards()[0]
        entities = set(re.findall(r"sensor\.sem_[a-z0-9_]+", yaml.safe_dump(card)))
        if not entities & KNOWN_MIXED_ENTITIES:
            pytest.skip("instance fixed — the exempted entity left the view")
        boundaries = {
            b for b in (_entity_boundary(e, fields) for e in entities) if b
        }
        assert boundaries == {"calendar", "ev-deadline"}, (
            f"expected the un-exempted Sankey to still mix boundaries, got "
            f"{boundaries or 'none'} — if the instance is fixed, remove the "
            "exemption (see the test above)."
        )


@pytest.mark.unit
class TestComputedBalancesUseOneBoundary723:
    """The class isn't only charts. The same mix inside a COMPUTATION already
    cost a user-visible number once: on HA-PROD 2026-06-01 autarky read 9 %
    instead of ~42 % because ``daily_ev`` (deadline/sunrise day) was combined
    with calendar-day flow figures — 6.2 kWh of pre-boundary EV charging sat
    in the grid penalty but not in the consumption total. The fix moved the
    whole calculation onto flow attribution (one boundary); the mixed legacy
    path survives in ``calculate_performance`` for old test fixtures only.
    This pins production out of it."""

    def test_production_always_passes_energy_flows_to_calculate_performance(self):
        """A future caller dropping ``energy_flows`` would silently reinstate
        the 2026-06-01 autarky bug through the legacy two-arg path."""
        offenders = []
        for rel in _production_files():
            text = (REPO / rel).read_text(encoding="utf-8")
            for m in re.finditer(r"\.calculate_performance\(", text):
                window = text[m.end():m.end() + 200]
                if "energy_flows" not in window:
                    line = text.count("\n", 0, m.start()) + 1
                    offenders.append(f"{rel}:{line}")
        assert not offenders, (
            f"calculate_performance called without energy_flows at {offenders} "
            "— the legacy two-arg path computes daily_home + daily_ev across "
            "two different day boundaries (the 2026-06-01 autarky bug)."
        )

    def test_the_flows_guard_sees_the_real_call(self):
        """Zero matches would make the assertion above vacuous (class 8)."""
        calls = [
            rel for rel in _production_files()
            if ".calculate_performance(" in (REPO / rel).read_text(encoding="utf-8")
        ]
        assert calls, "no production caller of calculate_performance found — "\
                      "the guard above is checking nothing; update its pattern"


@pytest.mark.unit
class TestProducerBoundariesAreWhatTheViewGuardAssumes723:

    def test_the_ev_daily_sensor_is_the_deadline_one(self):
        assert _daily_field_boundaries()["daily_ev"] == "ev-deadline"

    def test_the_other_daily_energy_sensors_are_calendar(self):
        fields = _daily_field_boundaries()
        for field in ("daily_home", "daily_solar", "daily_grid_import",
                      "daily_grid_export", "daily_battery_charge",
                      "daily_battery_discharge"):
            assert fields[field] == "calendar", f"{field} moved boundary"

    def test_flow_energy_is_calendar_by_construction(self):
        """``_entity_boundary`` hardcodes calendar for flow sensors; if
        flow_calculator ever stops naming its day off the calendar, that
        assumption silently unbalances the same chart."""
        src = (REPO / "coordinator" / "flow_calculator.py").read_text(
            encoding="utf-8"
        )
        assert re.search(r"_current_date\s*:?\s*date?\s*=\s*dt_util\.now\(\)\.date\(\)",
                         src), (
            "flow_calculator no longer derives its day from the calendar — "
            "update _entity_boundary in this file to match, or the Sankey's "
            "flow arrows silently join the wrong day."
        )
