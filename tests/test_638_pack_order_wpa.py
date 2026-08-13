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
    Demand,
)
# (#758) see synthetic_night.py — a flat-price fixture, not a shipping API.
from custom_components.solar_energy_management.tests.synthetic_night import (
    PriceSlot, pack_flat_night,
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
        plan = pack_flat_night([towel, heizband], _slots([0.36] * 8),
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
        plan = pack_flat_night([light, ev], _slots([0.36], cap_w=5000))
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


class TestStampWaitsForTheBattery:
    """Armed night 1, second stamp: the restart re-stamped 86 s before the
    battery SOC's first reading — the trajectory walked from nothing and
    every battery demand yielded a 63 %-full battery. A silent sensor is
    not an empty battery (#638 finding #3): the trigger must gate on
    ``battery_soc_unavailable`` (0.0 is a VALID reading; ``None`` never
    happens — PowerReadings defaults the float and raises the flag)."""

    def test_the_trigger_gates_on_soc_availability(self):
        src = (REPO / "coordinator" / "coordinator.py").read_text(
            encoding="utf-8")
        i = src.index("_batt_ready = (")
        window = src[i:i + 300]
        assert "battery_soc_unavailable" in window, (
            "the stamp trigger no longer waits for a live battery SOC — "
            "a boot-time stamp walks the trajectory from nothing and "
            "yields every battery demand (armed night 1, 21:53 stamp)"
        )
        assert "battery_capacity_kwh" in window, (
            "battery-less installs must keep stamping without a SOC gate"
        )


class _RecordingStorage:
    """Just enough of SEMStorage: records what the coordinator persists."""

    def __init__(self, state=None):
        self._state = dict(state or {})
        self.writes = []

    def get_ev_wpa_state(self):
        return dict(self._state)

    def set_ev_wpa_state(self, state):
        self._state = dict(state)
        self.writes.append(dict(state))


class TestWattsPerAmpSurvivesARestart:
    """(#638 night 2) The EMA lived in plain memory, so every restart reset
    the packer to nameplate until the car's NEXT charge — and the 23:36
    deploy restart plus a 23:46 re-plan meant the pack sized the floor at
    6.9 kW again, found no slot under the peak, and yielded a car that then
    charged at 4.54 kW. Armed-night-1's nameplate class, restart flavour.
    Same cure as the sign-detection locks (#476 item 5): learned state that
    gates behaviour survives the restart."""

    def test_a_learned_sample_is_persisted(self):
        c = _coord([CFG], amps=10)
        c._storage = _RecordingStorage()
        c._ev_watts_per_amp("keba", CFG, _Power(4850.0))
        assert c._storage.get_ev_wpa_state() == {
            "keba": pytest.approx(485.0)}

    def test_an_idle_cycle_does_not_write_storage(self):
        """The mirror happens on LEARN, not on every read — reads run
        several times per 10 s cycle."""
        c = _coord([CFG], amps=0, ema={"keba": 485.0})
        c._storage = _RecordingStorage()
        c._ev_watts_per_amp("keba", CFG, _Power(0.0))
        assert c._storage.writes == []

    def test_restore_seeds_the_ema(self):
        c = _coord([CFG])
        c._restore_ev_wpa({"keba": 485.0})
        assert c._ev_watts_per_amp("keba", CFG, None) == pytest.approx(485.0)

    def test_restore_drops_garbage_and_keeps_the_rest(self):
        """A corrupt entry must not take the good one down (the #563
        per-entry-repair rule) — and must not poison the pack with a
        nonsense ratio in either direction."""
        c = _coord([CFG])
        c._restore_ev_wpa({
            "keba": 485.0,
            "ghost": "NaN-ish",
            "too_low": 3.0,
            "too_high": 250000.0,
        })
        assert c._ev_wpa_ema == {"keba": pytest.approx(485.0)}

    def test_restore_tolerates_a_missing_or_empty_store(self):
        c = _coord([CFG])
        c._restore_ev_wpa({})
        c._restore_ev_wpa(None)
        assert c._ev_wpa_ema == {}
        assert c._ev_watts_per_amp("keba", CFG, None) == pytest.approx(690.0)

    def test_no_storage_attribute_is_fine(self):
        """The bare harness has no _storage — learning must not require
        one (unit paths, early boot)."""
        c = _coord([CFG], amps=10)
        assert c._ev_watts_per_amp("keba", CFG, _Power(4850.0)) == \
            pytest.approx(485.0)

    def test_the_first_refresh_restores_it(self):
        """Source scan (the ``_batt_ready`` precedent above): the restore
        must be wired into the same first-refresh block that restores the
        sign locks, or it exists but never runs."""
        src = (REPO / "coordinator" / "coordinator.py").read_text(
            encoding="utf-8")
        i = src.index("restore_sign_state")
        window = src[i:i + 1200]
        assert "_restore_ev_wpa" in window, (
            "the W/A EMA is no longer restored at first refresh — a "
            "restart resets the pack to nameplate until the next charge "
            "(#638 night 2: 6.9 kW floor, no slot, yield)"
        )

    def test_storage_round_trip(self):
        from custom_components.solar_energy_management.coordinator.storage import (
            SEMStorage,
        )
        st = SEMStorage.__new__(SEMStorage)
        st._energy_data = {}
        assert st.get_ev_wpa_state() == {}
        st.set_ev_wpa_state({"keba": 485.0})
        assert st.get_ev_wpa_state() == {"keba": 485.0}
        assert st._energy_data["ev_wpa_ema"] == {"keba": 485.0}
