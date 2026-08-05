"""#638 armed night 1 — two findings from the first plan that steered.

1. **The pack order was REVERSED.** The one list counts 1 = highest
   (``get_devices_sorted``), and the packer also packs lowest-number first —
   the directions already agree. The coordinator negated anyway, so rank 14
   (a guest-room light) packed first and the EV (rank 1) packed dead last:
   the battery headroom went to the towel heaters while the higher-ranked
   Heizband went partial. Pinned here behaviourally AND by a source scan.

2. **Nameplate is not a draw.** The EV floor was sized at
   ``phases × voltage`` (6.9 kW) which never fits under a 6.0 kW peak, so
   the packer yielded a car that then charged at 4.85 kW below the
   threshold all night. ``_ev_watts_per_amp`` learns the real W/A from the
   charger's own draw (single-charger installs; multi falls back to
   nameplate rather than committing the fleet-read class bug).
"""
from datetime import datetime, timedelta
from pathlib import Path
import re

import pytest

from custom_components.solar_energy_management.coordinator.overnight_planner import (
    Demand, PriceSlot, plan_overnight,
)

REPO = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 8, 5, 22, 0)


def _slots(prices, cap_w=10000.0):
    out = []
    for n, p in enumerate(prices):
        s = T0 + timedelta(hours=n)
        out.append(PriceSlot(start=s, end=s + timedelta(hours=1),
                             price=p, cap_w=cap_w))
    return out


def _by_id(plan, did):
    return next(r for r in plan.results if r.demand_id == did)


class TestPackOrderFollowsTheOneList:
    """1 = highest priority packs FIRST — the armed-night-1 regression."""

    def test_battery_headroom_goes_to_the_higher_rank(self):
        # 3 kWh of battery budget; rank 2 asks 3, rank 5 asks 2 — the
        # higher rank (2) must take its full ask, the lower goes partial/
        # yields. Before the fix this came out reversed (the live Heizband/
        # towel-heater split).
        heizband = Demand(id="load:heizband", kind="load", energy_kwh=3.0,
                          max_power_w=1000, min_power_w=1000,
                          priority=2, source="battery")
        towel = Demand(id="load:towel", kind="load", energy_kwh=2.0,
                       max_power_w=1000, min_power_w=1000,
                       priority=5, source="battery")
        plan = plan_overnight([towel, heizband], _slots([0.36] * 8),
                              battery_budget_kwh=3.0)
        assert _by_id(plan, "load:heizband").status == "fits"
        assert _by_id(plan, "load:towel").status in ("partial", "yields")

    def test_ev_rank_1_beats_a_rank_14_load_for_capped_grid_slots(self):
        # One 5 kW-capped slot hour; both want it. EV (rank 1) must win.
        ev = Demand(id="ev:main", kind="ev", energy_kwh=4.0,
                    max_power_w=5000, min_power_w=4800,
                    priority=1, source="grid")
        light = Demand(id="load:light", kind="load", energy_kwh=4.0,
                       max_power_w=4800, min_power_w=4800,
                       priority=14, source="grid")
        plan = plan_overnight([light, ev], _slots([0.36], cap_w=5000))
        assert _by_id(plan, "ev:main").status == "fits"
        assert _by_id(plan, "load:light").status == "yields"

    def test_no_demand_site_negates_the_priority_again(self):
        """Source scan: the negation WAS the bug — ban its shape outright.
        (All three Demand sites used ``priority=-...``; nothing else in the
        coordinator ever did.)"""
        src = (REPO / "coordinator" / "coordinator.py").read_text(
            encoding="utf-8")
        hits = [
            f"line {src.count(chr(10), 0, m.start()) + 1}: {m.group(0)}"
            for m in re.finditer(r"priority\s*=\s*-", src)
        ]
        assert not hits, (
            "a Demand site negates its one-list priority again — the one "
            "list counts 1 = highest and the packer packs lowest-first; "
            "negating REVERSES the user's drag list (armed night 1):\n  "
            + "\n  ".join(hits)
        )


class _Power:
    def __init__(self, ev_power):
        self.ev_power = ev_power


def _coord(chargers, amps=0, ema=None):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {"ev_chargers": chargers}
    c._ev_wpa_ema = dict(ema or {})
    c._last_commanded_amps_fleet = amps
    return c


CFG = {"id": "keba", "ev_phases": 3, "ev_voltage": 230}  # nameplate 690


class TestMeasuredWattsPerAmp:
    def test_a_live_draw_teaches_the_real_ratio(self):
        # The armed-night-1 numbers: 4850 W at 10 A → 485 W/A, not 690.
        c = _coord([CFG], amps=10)
        assert c._ev_watts_per_amp("keba", CFG, _Power(4850.0)) == \
            pytest.approx(485.0)
        assert c._ev_wpa_ema["keba"] == pytest.approx(485.0)

    def test_the_memo_folds_as_an_ema_not_a_last_write(self):
        c = _coord([CFG], amps=10, ema={"keba": 485.0})
        got = c._ev_watts_per_amp("keba", CFG, _Power(5850.0))
        assert got == pytest.approx(0.7 * 485.0 + 0.3 * 585.0)

    def test_idle_charger_returns_the_memo_then_nameplate(self):
        c = _coord([CFG], amps=0, ema={"keba": 485.0})
        assert c._ev_watts_per_amp("keba", CFG, _Power(0.0)) == \
            pytest.approx(485.0)
        c2 = _coord([CFG], amps=0)
        assert c2._ev_watts_per_amp("keba", CFG, _Power(0.0)) == \
            pytest.approx(690.0)

    def test_multi_charger_never_samples_the_fleet_read(self):
        """Two chargers: fleet ev_power is NOT this charger's draw — the
        accessor must not learn from it (docs/MULTI_CHARGER.md class)."""
        c = _coord([CFG, {"id": "second"}], amps=10)
        assert c._ev_watts_per_amp("keba", CFG, _Power(9000.0)) == \
            pytest.approx(690.0)
        assert "keba" not in c._ev_wpa_ema

    def test_the_sample_is_clamped_into_the_physical_range(self):
        c = _coord([CFG], amps=1)
        # 20 kW at 1 A is nonsense — clamp to nameplate.
        assert c._ev_watts_per_amp("keba", CFG, _Power(20000.0)) == \
            pytest.approx(690.0)
        c2 = _coord([CFG], amps=10)
        # 450 W at 10 A → floor of 100 W/A.
        assert c2._ev_watts_per_amp("keba", CFG, _Power(450.0)) == \
            pytest.approx(100.0)

    def test_missing_power_object_is_nameplate(self):
        c = _coord([CFG], amps=10)
        assert c._ev_watts_per_amp("keba", CFG, None) == pytest.approx(690.0)
