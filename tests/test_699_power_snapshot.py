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
_CARDS = _ROOT / "dashboard" / "card" / "src" / "cards"
# (#784) The diagram card's snapshot reads used to live in the standalone
# vanilla file at dashboard/card/sem-system-diagram-card.js. That copy never
# rendered — the bundled Lit version won the semDefineCard race — so this pin
# was guarding a file the user never saw. It now points at the shipped card.
_DIAGRAM = _CARDS / "sem-system-diagram-card.js"
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
       home=0.0, soc=50.0, soc_unavailable=False, ev_charging=False):
    return SimpleNamespace(
        solar_power=solar, grid_power=grid,
        grid_import_power=grid_import, grid_export_power=grid_export,
        battery_power=battery, battery_charge_power=batt_charge,
        battery_discharge_power=batt_discharge, ev_power=ev,
        home_consumption_power=home, battery_soc=soc,
        battery_soc_unavailable=soc_unavailable, ev_charging=ev_charging,
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


class TestEvLagAttributionGuard:
    """(#699 follow-up, Guido) A 4 kW step with the EV sensor lagging must
    not land on the home node just because the balance re-closed around it.
    The charging BINARY is the fast disambiguator: charging=on + ev_power~0
    means the equation cannot attribute correctly → keep shipping the last
    coherent set until the sensor catches up (bounded)."""

    def _idle(self):
        return _p(solar=300.0, grid_import=1000.0, home=1300.0, soc=80.0)

    def test_ev_start_absorbed_into_home_stays_held(self):
        """Spike guard expired, home accepted the car's 4.6 kW (residual is
        ~0 again — the residual check alone is blind here). charging=on +
        ev=0 → the misattributed set must NOT ship."""
        c = _coord()
        c._home_hold_active = False
        c._build_power_snapshot(self._idle())            # coherent cache
        misattributed = _p(solar=300.0, grid_import=5600.0, home=5900.0,
                           soc=80.0, ev=0.0, ev_charging=True)
        snap = c._build_power_snapshot(misattributed)
        assert snap["held"] is True
        assert snap["home_w"] == 1300.0                  # the coherent set

    def test_ev_sensor_catchup_ships_fresh_attribution(self):
        c = _coord()
        c._home_hold_active = False
        c._build_power_snapshot(self._idle())
        c._build_power_snapshot(_p(solar=300.0, grid_import=5600.0,
                                   home=5900.0, ev=0.0, ev_charging=True))
        caught_up = _p(solar=300.0, grid_import=5600.0, ev=4600.0,
                       home=1300.0, soc=80.0, ev_charging=True)
        snap = c._build_power_snapshot(caught_up)
        assert snap["held"] is False
        assert snap["ev_w"] == 4600.0
        assert snap["home_w"] == 1300.0

    def test_paused_charge_is_believed_after_the_window(self):
        """charging=on with a genuine 0 W (car paused/balancing) must not
        pin the view forever — past the bound the 0 is believed."""
        c = _coord()
        c._home_hold_active = False
        c._build_power_snapshot(self._idle())
        paused = _p(solar=300.0, grid_import=1000.0, home=1300.0,
                    soc=80.0, ev=0.0, ev_charging=True)
        for _ in range(SEMCoordinator.SNAPSHOT_EV_LAG_MAX_CYCLES):
            snap = c._build_power_snapshot(paused)
            assert snap["held"] is True
        snap = c._build_power_snapshot(paused)           # window exhausted
        assert snap["held"] is False

    def test_healthy_charge_is_never_held(self):
        c = _coord()
        c._home_hold_active = False
        healthy = _p(solar=300.0, grid_import=5600.0, ev=4600.0,
                     home=1300.0, ev_charging=True)
        assert c._build_power_snapshot(healthy)["held"] is False

    def test_counter_resets_when_the_condition_clears(self):
        c = _coord()
        c._home_hold_active = False
        c._build_power_snapshot(self._idle())
        lagging = _p(solar=300.0, grid_import=1000.0, home=1300.0,
                     ev=0.0, ev_charging=True)
        for _ in range(5):
            c._build_power_snapshot(lagging)
        c._build_power_snapshot(self._idle())            # binary off — clears
        assert c._snapshot_ev_lag_count == 0
        snap = c._build_power_snapshot(lagging)          # re-arms from 1
        assert snap["held"] is True


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

    # Each card reads a plain entity through its own accessor: the flow card
    # has _getState, the diagram card has _val. The fallback must survive in
    # whichever one the card uses.
    #
    # The diagram card does NOT take SOC from the snapshot. _build_power_snapshot
    # overlays SOC fresh and deliberately refuses to hold it ("a 5-minute-stale
    # SOC would be worse than an honest one"), while the diagram card carries a
    # 60 s last-known-good hold for the Huawei modbus flicker (#455/#488) that
    # the flow card does not have. The finer instrument wins there. It still
    # reads snap.battery_soc — as the liveness test gating the battery term.
    _BALANCE = ("snap.solar_w", "snap.battery_w", "snap.grid_import_w",
                "snap.grid_export_w", "snap.ev_w", "snap.home_w",
                "snap.battery_soc")

    @pytest.mark.parametrize(
        "path,read",
        [(_DIAGRAM, "_val"), (_FLOW, "_getState")],
        ids=["diagram", "flow"],
    )
    def test_snapshot_helper_and_usage(self, path, read):
        src = path.read_text(encoding="utf-8")
        assert "_powerSnapshot()" in src
        assert "power_snapshot" in src
        for token in self._BALANCE:
            assert token in src, f"{path.name} missing {token}"
        for key in ("solar_power", "ev_power"):
            token = f"{read}('{key}')"
            assert token in src, f"{path.name} lost the fallback {token}"

    def test_diagram_keeps_the_modbus_flicker_hold(self):
        """#699 must not have cost the diagram card its #455/#488 hold.

        The snapshot has no last-known-good for the battery: SOC is overlaid
        fresh and null when the source is down. If the card ever took the
        battery straight off the snapshot it would draw a flickering Huawei
        pack as 0 % / idle, which is what the hold exists to prevent.
        """
        src = _DIAGRAM.read_text(encoding="utf-8")
        assert "_readWithHold('battery_power'" in src
        assert "_readWithHold('battery_soc'" in src

    def test_bundle_carries_the_flow_card_change(self):
        bundle = (_ROOT / "dashboard" / "card" / "dist" / "sem-cards.js"
                  ).read_text(encoding="utf-8")
        assert "power_snapshot" in bundle, (
            "dist/sem-cards.js predates the #699 flow-card change — "
            "run `npm run build` in dashboard/card"
        )
