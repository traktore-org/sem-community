"""#699 — the balance set reaches the cards as ONE COHERENT snapshot.

Two layers to this class, and the fix must close both:

1. *Asynchronous publication*: the cards read five separate entities, each
   committing to HA's state machine on its own — a render instant composed
   values from different moments. Fixed by the atomic ``power_snapshot``
   attribute + snapshot-first cards.
2. *Incoherent-by-design cycles*: the #237/#444 home hold deliberately
   substitutes home while grid/EV carry raw skewed reads — the published SET
   violates its own equation for 1-2 cycles (dip tier: up to 5 min). The
   FIRST fix for this class was the held home entity itself; it protected
   home's value but knowingly shipped an inconsistent set (PROD 2026-07-31:
   grid tile 4.8 kW mid-KEBA-burst, EV tile 0, home held — ~5 kW missing
   from the view). The snapshot therefore ships the LAST SELF-CONSISTENT
   set when the cycle is known-incoherent, flagged ``held``, with only SOC
   overlaid fresh (not balance-coupled).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

_ROOT = Path(__file__).resolve().parents[1]
_DIAGRAM = _ROOT / "dashboard" / "card" / "sem-system-diagram-card.js"
_FLOW = _ROOT / "dashboard" / "card" / "src" / "cards" / "sem-flow-card.js"

_SNAP_KEYS = {
    "solar_w", "grid_w", "grid_import_w", "grid_export_w",
    "battery_w", "battery_charge_w", "battery_discharge_w",
    "ev_w", "home_w", "battery_soc", "held",
}


def _coord():
    return SEMCoordinator.__new__(SEMCoordinator)


def _p(*, solar=0.0, grid=0.0, grid_import=0.0, grid_export=0.0,
       battery=0.0, batt_charge=0.0, batt_discharge=0.0, ev=0.0,
       home=0.0, soc=50.0, soc_unavailable=False):
    return SimpleNamespace(
        solar_power=solar, grid_power=grid,
        grid_import_power=grid_import, grid_export_power=grid_export,
        battery_power=battery, battery_charge_power=batt_charge,
        battery_discharge_power=batt_discharge, ev_power=ev,
        home_consumption_power=home, battery_soc=soc,
        battery_soc_unavailable=soc_unavailable,
    )


def _coherent_cycle():
    """solar 3800 + import 4766 + discharge 111 − ev 4460 = home 4217."""
    return _p(solar=3800.0, grid=-4766.0, grid_import=4766.0,
              batt_discharge=111.0, battery=-111.0, ev=4460.0,
              home=4217.0, soc=89.0)


class TestSnapshotCoherence:
    def test_coherent_cycle_passes_through_and_is_cached(self):
        c = _coord()
        c._home_hold_active = False
        snap = c._build_power_snapshot(_coherent_cycle())
        assert set(snap) == _SNAP_KEYS
        assert snap["held"] is False
        assert snap["ev_w"] == 4460.0
        assert c._last_coherent_snapshot["home_w"] == 4217.0

    def test_hold_cycle_ships_the_last_coherent_set(self):
        """The PROD screenshot cycle: grid has the burst, EV doesn't, home
        held — the published set must be the previous coherent one."""
        c = _coord()
        c._home_hold_active = False
        c._build_power_snapshot(_coherent_cycle())          # cache
        # spike-guard cycle: grid 4766 in, ev still 0, home HELD at 4217
        c._home_hold_active = True
        skewed = _p(solar=3800.0, grid=-4766.0, grid_import=4766.0,
                    batt_discharge=111.0, battery=-111.0, ev=0.0,
                    home=4217.0, soc=88.0)
        snap = c._build_power_snapshot(skewed)
        assert snap["held"] is True
        assert snap["ev_w"] == 4460.0        # the coherent set, not the chimera
        assert snap["grid_import_w"] == 4766.0
        # SOC is overlaid FRESH — it is not balance-coupled
        assert snap["battery_soc"] == 88.0

    def test_residual_violation_is_held_even_without_the_flag(self):
        """The negative-balance zero-clamp (hold window exhausted, flag off):
        the set still violates its equation → held."""
        c = _coord()
        c._home_hold_active = False
        c._build_power_snapshot(_coherent_cycle())
        clamped = _p(solar=0.0, grid_import=0.0, batt_discharge=0.0,
                     ev=2000.0, home=0.0, soc=87.0)   # residual 2000 > 150
        snap = c._build_power_snapshot(clamped)
        assert snap["held"] is True
        assert snap["home_w"] == 4217.0

    def test_recovery_replaces_the_cache(self):
        c = _coord()
        c._home_hold_active = False
        c._build_power_snapshot(_coherent_cycle())
        c._home_hold_active = True
        c._build_power_snapshot(_p(home=0.0, ev=2000.0))    # held cycle
        c._home_hold_active = False
        fresh = _p(solar=1000.0, home=1000.0, soc=86.0)
        snap = c._build_power_snapshot(fresh)
        assert snap["held"] is False
        assert c._last_coherent_snapshot["solar_w"] == 1000.0

    def test_cold_start_incoherent_returns_the_raw_set(self):
        """No coherent cache yet — the raw set is the best available."""
        c = _coord()
        c._home_hold_active = True
        snap = c._build_power_snapshot(_p(solar=500.0, home=500.0))
        assert snap["solar_w"] == 500.0
        assert snap["held"] is False

    def test_unavailable_soc_reads_none(self):
        c = _coord()
        c._home_hold_active = False
        p = _coherent_cycle()
        p.battery_soc_unavailable = True
        assert c._build_power_snapshot(p)["battery_soc"] is None


class TestSensorPublishesTheSnapshot:
    def _home_sensor(self):
        from custom_components.solar_energy_management.sensor import SEMSolarSensor
        s = SEMSolarSensor.__new__(SEMSolarSensor)
        s.entity_description = MagicMock()
        s.entity_description.key = "home_consumption_power"
        s.coordinator = MagicMock()
        return s

    def test_snapshot_passes_through_verbatim(self):
        s = self._home_sensor()
        payload = {"solar_w": 1.0, "held": True}
        s.coordinator.data = {"power_snapshot": payload,
                              "home_consumption_power": 500.0}
        assert s.extra_state_attributes["power_snapshot"] is payload

    def test_absent_snapshot_publishes_no_attribute(self):
        s = self._home_sensor()
        s.coordinator.data = {"home_consumption_power": 500.0}
        assert "power_snapshot" not in s.extra_state_attributes

    def test_snapshot_is_unrecorded(self):
        from custom_components.solar_energy_management.sensor import SEMSolarSensor
        assert "power_snapshot" in SEMSolarSensor._unrecorded_attributes


class TestCardsReadTheSnapshot:
    """Source pins: both equation views (the only cards that draw the balance
    as a connected system) prefer the snapshot for every balance value in
    prefix mode, with the per-entity fallback intact."""

    @pytest.mark.parametrize("path", [_DIAGRAM, _FLOW], ids=["diagram", "flow"])
    def test_snapshot_helper_and_usage(self, path):
        src = path.read_text(encoding="utf-8")
        assert "_powerSnapshot()" in src
        assert "power_snapshot" in src
        for token in ("snap.solar_w", "snap.battery_w", "snap.grid_import_w",
                      "snap.grid_export_w", "snap.ev_w", "snap.home_w",
                      "snap.battery_soc"):
            assert token in src, f"{path.name} missing {token}"
        for token in ("_getState('solar_power')", "_getState('ev_power')"):
            assert token in src, f"{path.name} lost the fallback {token}"

    def test_bundle_carries_the_flow_card_change(self):
        bundle = (_ROOT / "dashboard" / "card" / "dist" / "sem-cards.js"
                  ).read_text(encoding="utf-8")
        assert "power_snapshot" in bundle, (
            "dist/sem-cards.js predates the #699 flow-card change — "
            "run `npm run build` in dashboard/card"
        )
