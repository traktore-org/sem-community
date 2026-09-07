"""(#925 audit, then seen live on .175) The spendable budget must not read
an unread SOC as 0 %.

`PowerReadings.battery_soc` is 0.0 by dataclass default and never None —
`battery_soc_unavailable` is the only way to know whether it was read. The
budget's SOC read was ungated, so a dark sensor computed the entire
overnight budget against a literal 0 % pack.

Observed on `.175`, 07.09, while verifying this branch:

    sensor.sem_battery_soc            = unavailable
    sensor.sem_battery_spendable_kwh  = 0.0
      dynamic_floor_pct: 86.3
      why: "nothing spendable — tonight's own load needs all 0.0 kWh stored"

A confident floor percentage and a sentence about 0.0 kWh stored, from a
pack whose charge nobody had measured. It fails SAFE numerically — the
reserve always exceeds a stored zero — so this is a trust defect, not a
spending one. Both `dawn_headroom_kwh()` and `spendable_budget()` carry an
honest "SOC unknown" branch that could never be reached.
"""

from __future__ import annotations

from types import SimpleNamespace


def _soc_for_budget(power):
    """The read as the coordinator now performs it."""
    return (None if getattr(power, "battery_soc_unavailable", False)
            else getattr(power, "battery_soc", None))


class TestTheBudgetAsksWhetherTheSocWasRead:

    def test_a_dark_soc_is_unknown_not_zero(self):
        p = SimpleNamespace(battery_soc=0.0, battery_soc_unavailable=True)
        assert _soc_for_budget(p) is None, (
            "the dataclass default 0.0 reached the budget as a reading — "
            "the honest 'SOC unknown' branch can never run")

    def test_a_real_zero_is_still_zero(self):
        """A genuinely flat pack is a measurement and must reach the budget."""
        p = SimpleNamespace(battery_soc=0.0, battery_soc_unavailable=False)
        assert _soc_for_budget(p) == 0.0

    def test_a_normal_reading_passes_through(self):
        p = SimpleNamespace(battery_soc=63.5, battery_soc_unavailable=False)
        assert _soc_for_budget(p) == 63.5

    def test_a_reader_without_the_twin_flag_is_trusted(self):
        """Older/partial readings that never set the flag keep working."""
        p = SimpleNamespace(battery_soc=41.0)
        assert _soc_for_budget(p) == 41.0


class TestTheRefusalBranchIsNowReachable:
    """`spendable_budget` has always carried an honest "unknown battery SOC"
    branch. With the coordinator handing it a dataclass default of 0.0, that
    branch could never run — the budget computed against a literal 0 % pack
    and published a measured-sounding sentence instead.

    (`dawn_headroom_kwh` returning `cap` for an unknown SOC is deliberate
    and documented — the pack cannot absorb more than itself, and the
    refusal is meant to happen HERE, on the dark input, not on the refill.
    This is the test that the design's other half actually holds.)"""

    def _budget(self, soc):
        import inspect
        from custom_components.solar_energy_management.coordinator \
            .spendable_budget import spendable_budget
        sig = inspect.signature(spendable_budget)
        kw = {p.name: 12.0 for p in sig.parameters.values()
              if p.default is inspect.Parameter.empty}
        kw["soc_pct"] = soc
        return spendable_budget(**kw)

    def test_a_dark_soc_says_so(self):
        b = self._budget(None)
        assert b.spendable_kwh == 0.0
        assert "unknown" in b.reason.lower() and "soc" in b.reason.lower(), (
            f"a dark SOC produced {b.reason!r} — the honest refusal branch "
            "is still unreachable")
        assert b.floor_pct is None, (
            "a floor percentage was computed from an SOC nobody read")

    def test_a_measured_empty_pack_reads_differently(self):
        """The two must not look alike — that was the whole defect, seen on
        .175 with the SOC sensor unavailable and the card reading
        'needs all 0.0 kWh stored'."""
        dark = self._budget(None)
        empty = self._budget(0.0)
        assert dark.reason != empty.reason
        assert empty.floor_pct is not None
