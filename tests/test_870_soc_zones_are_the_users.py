"""(#870) The battery SOC zones are the user's to place.

coppe218: *"Battery size, chemistry, inverter behaviour and the user's
energy strategy can differ significantly between installations... a
configuration such as Priority 20 / Buffer 30 / Auto-start 50 can be
completely intentional."*

It could not be configured. Buffer floored at 50% and Auto-start at 70%,
so both of his lower zones were unreachable. Those minimums were doing two
jobs at once — bounding each value, and implying the ordering
priority ≤ buffer ≤ auto_start — and the second job is what made widening
the first feel dangerous.

The ordering is a relationship between three numbers, not a property of
any one field's range. So it moved to where it is actually used, and the
ranges opened up.
"""

from __future__ import annotations

from custom_components.solar_energy_management.consts.bounds import BOUNDS
from custom_components.solar_energy_management.coordinator.decide import (
    soc_zone,
)

ZONE_KEYS = ("battery_priority_soc", "battery_buffer_soc",
             "battery_auto_start_soc")


class TestTheRangesAreWideEnoughToMeanSomething:

    def test_the_reporters_layout_is_configurable(self):
        """20 / 30 / 50 — the exact layout #870 asked for."""
        for key, want in zip(ZONE_KEYS, (20, 30, 50), strict=True):
            r = BOUNDS[key]
            assert r.min <= want <= r.max, (
                f"{key} cannot be set to {want}% (range {r.min}-{r.max}) — "
                "this is the configuration the issue was filed about")

    def test_all_three_share_one_range(self):
        """Three thresholds over the same quantity that disagreed about
        what a legal percentage is. Any asymmetry here is the old implied
        ordering creeping back into the bounds."""
        ranges = {k: (BOUNDS[k].min, BOUNDS[k].max, BOUNDS[k].step)
                  for k in ZONE_KEYS}
        assert len(set(ranges.values())) == 1, ranges

    def test_the_table_is_the_only_declaration(self):
        """They were declared twice — the number entities and the config
        flow — with the numbers duplicated by hand. Same values then;
        that is exactly how #828's pair started."""
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        # Each key appears in several places — a defaults dict, an option
        # list, and the one place that declares a RANGE. Only the last is
        # this test's business, so look for a literal range near ANY
        # occurrence rather than guessing which occurrence matters.
        literal = re.compile(r"(native_min_value\s*=\s*\d|"
                             r"NumberSelectorConfig\(\s*min\s*=\s*\d)")
        for name in ("number.py", "config_flow.py"):
            src = (root / name).read_text(encoding="utf-8")
            for key in ZONE_KEYS:
                for m in re.finditer(re.escape(key), src):
                    # Stop at the NEXT declaration, or a fixed-size window
                    # reads into the following entity and blames this key
                    # for its neighbour's literal.
                    rest = src[m.start():m.start() + 600]
                    nxt = re.search(r"NumberEntityDescription\(|vol\.Optional\(",
                                    rest[len(key):])
                    window = rest[:len(key) + nxt.start()] if nxt else rest[:300]
                    hit = literal.search(window)
                    assert not hit, (
                        f"{name} declares {key}'s range with a literal "
                        f"({hit.group(0)!r}) instead of reading the one "
                        "bounds table")
                if key in src:
                    assert (f'BOUNDS["{key}"]' in src
                            or f'bounds_selector("{key}"' in src), (
                        f"{name} mentions {key} but never reads its range "
                        "from the table")


class TestAnUnsortedLayoutNeverSkipsAZone:
    """The cascade assumed ascending order. Unsorted it does not merely
    misorder the zones — it DELETES one, which is why the ranges could not
    simply be widened."""

    def test_the_reporters_layout_maps_to_all_four_zones(self):
        # priority 20, buffer 30, auto-start 50
        assert [soc_zone(s, 50, 30, 20) for s in (10, 25, 40, 60)] == [1, 2, 3, 4]

    def test_a_disordered_layout_still_yields_four_ordered_zones(self):
        """auto_start 50 with buffer 80: before #870 a 60% pack answered
        `60 >= 50` and returned zone 4, never reaching the buffer test the
        user set at 80."""
        got = [soc_zone(s, 50, 80, 20) for s in (10, 25, 60, 90)]
        assert got == [1, 2, 3, 4], (
            f"a disordered layout skipped or reordered a zone: {got}")

    def test_the_boundaries_are_the_same_numbers_sorted(self):
        """Not clamped, not defaulted, not silently replaced — sorted. The
        user's three numbers still mean three boundaries."""
        for soc in range(0, 101, 5):
            assert soc_zone(soc, 50, 80, 20) == soc_zone(soc, 80, 50, 20)

    def test_zones_are_monotonic_in_soc(self):
        """However the thresholds are arranged, more charge is never a
        lower zone."""
        for a, b, p in ((50, 80, 20), (90, 70, 30), (5, 100, 50)):
            zones = [soc_zone(s, a, b, p) for s in range(0, 101)]
            assert zones == sorted(zones), (a, b, p, zones)


class TestTheUserIsToldRatherThanQuietlyCorrected:

    def test_out_of_order_raises_a_repair_and_order_clears_it(self):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator.coordinator \
            import SEMCoordinator

        fake = SimpleNamespace(
            hass=SimpleNamespace(is_running=True),
            config={"battery_priority_soc": 20, "battery_buffer_soc": 80,
                    "battery_auto_start_soc": 50},
        )
        import custom_components.solar_energy_management.coordinator \
            .repair_issues as ri
        raised, cleared = [], []
        ri.raise_soc_zones_out_of_order = lambda hass, **kw: raised.append(kw)
        ri.clear_soc_zones_out_of_order = lambda hass: cleared.append(1)

        SEMCoordinator._check_soc_zone_order(fake)
        assert raised, "an out-of-order layout raised no Repair"
        assert raised[-1]["buffer"] == 80

        # ...and it clears when the user fixes it
        fake.config["battery_buffer_soc"] = 30
        SEMCoordinator._check_soc_zone_order(fake)
        assert cleared, "fixing the order did not clear the Repair"

    def test_it_says_nothing_before_home_assistant_is_running(self):
        """(#919's lesson) A question asked before the thing it asks about
        exists answers wrongly and never asks again."""
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator.coordinator \
            import SEMCoordinator
        import custom_components.solar_energy_management.coordinator \
            .repair_issues as ri
        raised = []
        ri.raise_soc_zones_out_of_order = lambda hass, **kw: raised.append(kw)
        fake = SimpleNamespace(
            hass=SimpleNamespace(is_running=False),
            config={"battery_priority_soc": 20, "battery_buffer_soc": 80,
                    "battery_auto_start_soc": 50})
        SEMCoordinator._check_soc_zone_order(fake)
        assert not raised
