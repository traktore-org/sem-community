"""#877 — pressing the button with requirements unmet raises a Repair.

Guido, 31.08: *"if a user presses the button and not all requirements are met
it should create a repair"*.

A person who presses **Rebuild from history** is asking a direct question,
and the answer outlives the moment they asked it. A notification is dismissed
and gone; the missing sensor is not. So the two ways the rebuild can come
back short go where unfinished setup lives, each naming the sensor to add.

Two keys, not one — #872 is the lesson that a single repair covering two
faults ends up asserting the wrong one. They differ in what actually
happened and in what it costs:

* **blocked** — no battery-discharge counter, so nothing was rebuilt at all;
* **incomplete** — it rebuilt, but some nights could not account for the
  grid's share, so they under-state the house and the spendable figure reads
  LOW. That is the unsafe direction, which is why it is not merely an FYI.

Same ``issue_id``, so an install that fixes one and then meets the other
REPLACES its card instead of collecting two contradictory ones — and a clean
rebuild clears it.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.coordinator import repair_issues as ri


def _created(mock):
    """(issue_id, translation_key, placeholders) of the last create."""
    assert mock.called, "no repair was raised"
    kw = mock.call_args.kwargs
    return kw.get("issue_id"), kw.get("translation_key"), \
        kw.get("translation_placeholders") or {}


class TestTheBlockedCase:
    def test_it_raises_and_names_the_missing_sensor(self):
        hass = MagicMock()
        with patch.object(ri.ir, "async_create_issue") as m:
            ri.raise_battery_night_backfill_blocked(
                hass, missing="battery discharge energy")
        issue_id, key, ph = _created(m)
        assert key == "battery_night_backfill_blocked"
        assert ph["missing"] == "battery discharge energy", (
            "'requirements not met' is not actionable; the sensor's name is"
        )

    def test_it_offers_a_next_step(self):
        """#831 — a repair that dead-ends teaches people the links are
        decoration."""
        hass = MagicMock()
        with patch.object(ri.ir, "async_create_issue") as m:
            ri.raise_battery_night_backfill_blocked(hass, missing="x")
        assert m.call_args.kwargs.get("learn_more_url")


class TestTheIncompleteCase:
    def test_it_raises_a_different_card(self):
        hass = MagicMock()
        with patch.object(ri.ir, "async_create_issue") as m:
            ri.raise_battery_night_backfill_incomplete(
                hass, missing="grid import energy",
                unbalanced=47, recovered=60)
        issue_id, key, ph = _created(m)
        assert key == "battery_night_backfill_incomplete", (
            "one repair covering two faults asserts the wrong one (#872)"
        )
        assert ph["unbalanced"] == "47" and ph["recovered"] == "60"

    def test_both_cases_share_one_issue_id(self):
        """An install that gains its discharge counter and then meets the
        second fault must REPLACE its card, not collect two."""
        hass = MagicMock()
        with patch.object(ri.ir, "async_create_issue") as m:
            ri.raise_battery_night_backfill_blocked(hass, missing="a")
            first = m.call_args.kwargs["issue_id"]
            ri.raise_battery_night_backfill_incomplete(
                hass, missing="b", unbalanced=1, recovered=2)
            second = m.call_args.kwargs["issue_id"]
        assert first == second


class TestItClears:
    def test_a_clean_rebuild_deletes_the_issue(self):
        hass = MagicMock()
        with patch.object(ri.ir, "async_delete_issue") as m:
            ri.clear_battery_night_backfill(hass)
        assert m.called

    def test_a_repair_never_costs_the_service(self):
        """A registry that raises must not turn a working rebuild into a
        failed one."""
        hass = MagicMock()
        with patch.object(ri.ir, "async_create_issue",
                          side_effect=Exception("registry down")):
            ri.raise_battery_night_backfill_blocked(hass, missing="x")
        with patch.object(ri.ir, "async_delete_issue",
                          side_effect=Exception("registry down")):
            ri.clear_battery_night_backfill(hass)


class TestTheServiceActuallyCallsThem:
    """The functions existing is not the feature; the button reaching them is.

    Guarded structurally because the service handler is a closure registered
    at setup, and the alternative — standing up the whole integration — tests
    HA more than it tests this.
    """

    def _src(self):
        import inspect
        from custom_components import solar_energy_management as sem
        return inspect.getsource(sem._async_register_services)

    def test_the_refusal_path_raises_the_blocked_repair(self):
        src = self._src()
        assert "raise_battery_night_backfill_blocked" in src, (
            "the button still answers a refusal with nothing the user can "
            "come back to"
        )

    def test_the_partial_path_raises_and_the_clean_path_clears(self):
        src = self._src()
        assert "raise_battery_night_backfill_incomplete" in src
        assert "clear_battery_night_backfill" in src, (
            "a repair that never clears is a repair people learn to ignore"
        )

    def test_the_repair_is_told_which_counters_are_missing(self):
        src = self._src()
        assert "missing_counters" in src


class TestBothStoriesAreTranslated:
    def test_every_language_carries_both_cards(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        files = [root / "strings.json"] + sorted(
            (root / "translations").glob("*.json"))
        assert len(files) >= 17
        for f in files:
            issues = json.loads(f.read_text()).get("issues", {})
            for key in ("battery_night_backfill_blocked",
                        "battery_night_backfill_incomplete"):
                e = issues.get(key)
                assert e and e.get("title") and e.get("description"), \
                    f"{f.name} is missing {key}"
                assert "{missing}" in e["description"], f"{f.name}/{key}"
            inc = issues["battery_night_backfill_incomplete"]["description"]
            assert "{unbalanced}" in inc and "{recovered}" in inc, f.name


class TestItOnlyComplainsWhenTheUserCanAct:
    """Live on the rig, 31.08: a 365-day rebuild recovered 275 nights, 41 of
    them without a grid term — and raised a card reading

        missing: 'one or more energy counters', unbalanced: '41'

    on an install where **all four counters are configured**. Two faults in
    one line:

    * it judged the whole HAUL, while `max_nights` had already pruned to 60
      — and all 60 KEPT nights had their grid share. The retained history was
      complete; the complaint was about nights SEM no longer holds.
    * with no counter actually missing it fell back to "one or more energy
      counters", naming a cause it had not established and handing the user
      an instruction that did not apply. That is #872's fault exactly.

    So: judge on what is kept, and raise the card only when a counter is
    genuinely absent. Per-night gaps and counter resets are data attrition,
    not something a person can fix.
    """

    def _src(self):
        import inspect
        from custom_components import solar_energy_management as sem
        return inspect.getsource(sem._async_register_services)

    def test_it_judges_the_kept_history_not_the_whole_haul(self):
        src = self._src()
        assert "kept_without_grid_term" in src, (
            "still counting every recovered night, so a 365-day rebuild "
            "complains about nights it pruned seconds later"
        )

    def test_it_does_not_invent_a_missing_counter(self):
        src = self._src()
        assert "one or more energy counters" not in src, (
            "fell back to naming a cause it had not established — the card "
            "tells the user to add sensors they already have"
        )
        assert '"unknown"' not in src.split("backfill_battery_nights")[-1][:2000]

    def test_the_card_needs_a_genuinely_absent_counter(self):
        src = self._src()
        assert "_unbalanced and _missing" in src, (
            "the card must require BOTH a shortfall and a named missing "
            "counter — a shortfall alone is data attrition, not a setup fault"
        )

    def test_the_no_counter_case_clears_rather_than_complains(self):
        src = self._src()
        # the branch body runs from the elif to the else that follows it
        i = src.index("elif _unbalanced")
        branch = src[i:src.index("\n            else:", i)]
        assert "clear_battery_night_backfill" in branch, (
            "an install whose counters are all present must end with no card"
        )
        assert "raise_battery_night_backfill_incomplete" not in branch
