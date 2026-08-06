"""#735 — the two charge-efficiency answers are deliberate, and asymmetric.

``ev_charger_efficiency`` overrides the 92 % AC→DC default. It reaches two of
the three sites that convert metered AC energy into pack energy:

    update_energy       booking the deficit    → honours the override
    on_session_end      first-session bootstrap→ honours the override
    energy_accounted_soc  the stop ceiling     → CONSTANT, by decision

That looked like a plain inconsistency when #735 was filed. It is not, and
this file exists so nobody "fixes" it — including whoever reads the three
call sites next and sees two of them agree.

The ceiling feeds ``effective_soc = max(sensor, ceiling)`` in
``_calculate_remaining_need`` (coordinator.py:6014). Run the direction:

    lower efficiency → lower ceiling → larger remaining need → charge LONGER
    higher efficiency → higher ceiling → smaller need → stop EARLIER

and the two errors are not the same size:

  * Stopping early is **recoverable**. The sensor stays primary; when the
    next real reading lands below target, remaining need goes positive and
    charging resumes (coordinator.py:5742-5743 even un-latches the notify).
  * Stopping late is **not**. The energy is already in the pack. That is the
    whole #708 report — a 30-minute-stale OnStar reading at 11.5 kW ran a
    60 % target to 67 %.

So the ceiling deliberately sits at the optimistic end of the realistic
0.85–0.95 band. Letting a user dial it down to 0.80 would hand them back the
unrecoverable failure mode as a configuration option, which is not a knob
worth shipping. The override still governs everything the user *reads* —
which is what they actually wanted it for.
"""
import ast
import pathlib

import pytest

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    CHARGE_EFFICIENCY,
    EVTaperDetector,
)

from .test_708_soc_lag_ceiling import CAPACITY, _feed_energy


LOW_EFF = 0.80          # single-phase, cold pack, preconditioning running
ANCHOR = 55.0
DELIVERED = 4.0


def _detector(**extra):
    return EVTaperDetector({"ev_battery_capacity_kwh": CAPACITY, **extra})


class TestTheOverrideGovernsWhatTheUserReads:
    def test_the_display_estimate_honours_the_override(self):
        det = _detector(ev_charger_efficiency=LOW_EFF)
        det.get_virtual_soc(ANCHOR)
        det.update_energy(DELIVERED)
        expected = ANCHOR + DELIVERED * LOW_EFF / CAPACITY * 100.0
        assert det.get_virtual_soc(None) == pytest.approx(expected, abs=0.15)

    def test_the_bootstrap_lands_on_target_whatever_the_efficiency(self):
        """Not a tautology — a real property of the bootstrap, worth pinning.

        It assumes the car arrived at ``target − soc_added`` and then gained
        ``soc_added``, so the two terms cancel and the result is *exactly*
        ``target`` for any efficiency, as long as the session did not deliver
        more than the target itself. Efficiency only becomes observable in
        the clamped branch below.

        Recording it because it is a trap: the obvious "does the bootstrap
        honour the override" test is written here, passes, and proves nothing.
        """
        results = []
        for eff in (LOW_EFF, CHARGE_EFFICIENCY, 1.0):
            det = EVTaperDetector({
                "ev_battery_capacity_kwh": 40,
                "ev_target_soc": 80,
                "ev_charger_efficiency": eff,
            })
            det._session_peak_w = 7000.0
            det.on_session_end(10.0)
            results.append((det._estimated_soc, det._energy_since_full))
        assert results == [pytest.approx(r) for r in [(80.0, 8.0)] * 3]

    def test_the_bootstrap_honours_the_override_where_it_can_show(self):
        """The clamped branch: session delivers more than the target itself.

        ``pre_charge_soc`` floors at 0, the cancellation breaks, and the
        efficiency finally reaches the result — 25 kWh into a 40 kWh pack is
        50 % of it at 0.80 but 57.5 % at 0.92.
        """
        def _bootstrap(eff):
            det = EVTaperDetector({
                "ev_battery_capacity_kwh": 40,
                "ev_target_soc": 50,
                "ev_charger_efficiency": eff,
            })
            det._session_peak_w = 7000.0
            det.on_session_end(25.0)
            return det._estimated_soc

        assert _bootstrap(LOW_EFF) == pytest.approx(50.0, abs=0.1)
        assert _bootstrap(CHARGE_EFFICIENCY) == pytest.approx(57.5, abs=0.1)


class TestTheStopCeilingIsDeliberatelyNotConfigurable:
    def test_the_ceiling_ignores_a_lowered_override(self):
        """Pin: a user cannot dial the stop guard back toward overshoot."""
        det = _detector(ev_charger_efficiency=LOW_EFF)
        det.get_virtual_soc(ANCHOR)
        _feed_energy(det, DELIVERED)
        at_constant = ANCHOR + DELIVERED * CHARGE_EFFICIENCY / CAPACITY * 100.0
        assert det.energy_accounted_soc() == pytest.approx(at_constant, abs=0.15)

    def test_the_ceiling_ignores_a_raised_override(self):
        det = _detector(ev_charger_efficiency=0.99)
        det.get_virtual_soc(ANCHOR)
        _feed_energy(det, DELIVERED)
        at_constant = ANCHOR + DELIVERED * CHARGE_EFFICIENCY / CAPACITY * 100.0
        assert det.energy_accounted_soc() == pytest.approx(at_constant, abs=0.15)

    def test_a_lower_override_would_have_charged_longer(self):
        """The reason, made numeric rather than left in a comment.

        If the ceiling honoured 0.80, the same delivered energy would leave
        more 'remaining need' against the same target — i.e. keep charging.
        Against a stale sensor that is exactly the #708 overshoot.
        """
        honoured = ANCHOR + DELIVERED * LOW_EFF / CAPACITY * 100.0
        as_shipped = ANCHOR + DELIVERED * CHARGE_EFFICIENCY / CAPACITY * 100.0
        assert honoured < as_shipped, "premise of the whole decision"

        target = 60.0
        need_if_honoured = max(0.0, (target - honoured) / 100 * CAPACITY)
        need_as_shipped = max(0.0, (target - as_shipped) / 100 * CAPACITY)
        assert need_if_honoured > need_as_shipped

    def test_the_constant_says_so_in_the_source(self):
        """The decision lives in a comment; keep the comment load-bearing.

        Read the whole trailing comment block rather than a fixed slice —
        a character window silently stops covering the text it is meant to
        guard the moment someone adds a line to it.
        """
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "coordinator" / "ev_taper_detector.py").read_text()
        lines = src.splitlines()
        start = next(i for i, ln in enumerate(lines)
                     if ln.startswith("CHARGE_EFFICIENCY = "))
        block = [lines[start]]
        for ln in lines[start + 1:]:
            if not ln.strip().startswith("#"):
                break
            block.append(ln)
        block = "\n".join(block)
        assert "no config knob" in block, (
            "CHARGE_EFFICIENCY's rationale comment was removed or reworded — "
            f"if the decision changed, this test and #735 change with it:\n{block}"
        )


class TestTheTwoBookingSitesAgreeWithEachOther:
    """The half that IS a single-source requirement.

    ``update_energy`` and ``on_session_end`` answer the same question about
    the same session. They may not drift apart — that is how #708's
    cancelling pair survived a year.
    """

    ACCESSOR = "_charge_efficiency"

    def _readers_of(self, needle, kind):
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "coordinator" / "ev_taper_detector.py").read_text()
        readers = set()
        for fn in ast.walk(ast.parse(src)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if kind == "name":
                    if isinstance(node, ast.Name) and node.id == needle:
                        readers.add(fn.name)
                elif isinstance(node, ast.Constant) and node.value == needle:
                    readers.add(fn.name)
        return readers

    def test_only_the_accessor_resolves_the_config_key(self):
        readers = self._readers_of("ev_charger_efficiency", "const")
        assert readers == {self.ACCESSOR}, (
            "the override must be resolved (and validated) in one place. "
            f"Readers: {sorted(readers)}. If you only wanted to LOG the "
            "value, log the accessor's return instead of re-reading the key "
            "— this guard cannot tell the two apart, and the raw value is "
            "the unvalidated one anyway."
        )

    def test_the_ceiling_still_reads_the_bare_constant(self):
        """Deliberate — and pinned, so the exception stays visible."""
        readers = self._readers_of("CHARGE_EFFICIENCY", "name")
        assert readers == {self.ACCESSOR, "energy_accounted_soc"}, (
            "expected exactly two constant readers: the accessor's fallback "
            f"and the deliberately-fixed ceiling. Found: {sorted(readers)}"
        )

    @pytest.mark.parametrize("bad", [
        0, -0.5, "", None, "abc", 3.0, 92,
        float("nan"), float("inf"),
        0.001,      # would stall the estimate for a whole session
        True,       # JSON `true` — float(True) is a valid-looking 1.0
        False,
        [0.9], {"v": 0.9},
    ])
    def test_a_nonsense_override_falls_back_to_the_default(self, bad):
        """A hand-edited storage key is the only way in — assume nothing.

        Zero or negative would freeze or invert the booking; >1 would claim
        the pack absorbed more than the meter measured; 92 is the percentage
        mistake; 0.001 looks like it works while going nowhere.
        """
        det = _detector(ev_charger_efficiency=bad)
        det.get_virtual_soc(ANCHOR)
        det.update_energy(DELIVERED)
        expected = ANCHOR + DELIVERED * CHARGE_EFFICIENCY / CAPACITY * 100.0
        assert det.get_virtual_soc(None) == pytest.approx(expected, abs=0.15)

    @pytest.mark.parametrize("good", [0.5, 0.85, 1.0, "0.88"])
    def test_a_plausible_override_is_accepted(self, good):
        """The band has to stay wide enough to be useful, not just safe.

        Includes the string form: a hand-edited JSON value is as likely to be
        quoted as not, and rejecting `"0.88"` would make the key look broken.
        """
        det = _detector(ev_charger_efficiency=good)
        det.get_virtual_soc(ANCHOR)
        det.update_energy(DELIVERED)
        expected = ANCHOR + DELIVERED * float(good) / CAPACITY * 100.0
        assert det.get_virtual_soc(None) == pytest.approx(expected, abs=0.15)
