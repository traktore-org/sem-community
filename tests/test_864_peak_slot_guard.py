"""#864 — the peak defence gets its missing PREVENTIVE half.

What went wrong (PROD 29.08, and silently since at least 28.08 when the
month's 6.919 kW peak was set): the load manager triggers SHEDDING when the
15-min average crosses the target — but the moment the average crosses, the
billed peak IS the average. The trigger condition equals the damage
condition; a reactive defence structurally cannot protect the metric it
watches. Every existing test passes because they verify that (correct)
reactive design — nothing regressed, the preventive half simply never
existed. Live proof of the gap: an EV charged at 9.9 kW under a 6.0 kW
target with the state reading `normal` throughout.

The fix follows the bill's own arithmetic. Demand tariffs bill the average
import of a fixed 15-minute clock slot, so each slot has an ENERGY budget
(target_kw x 0.25 h). SEM tracks what the slot has already imported and
bounds the EV offer by what is left over the remaining slot time — before
the offer is written, not after the average notices. Early in a slot a
burst is genuinely fine (the average absorbs it); as the slot fills, the
ceiling tightens. That is the mathematics of the bill, not a proxy for it.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.peak_guard import (
    PeakSlotTracker,
    slot_allowed_import_w,
)


class TestSlotBudgetMath:
    """slot_allowed_import_w(target_kw, imported_kwh, elapsed_s) → W."""

    def test_fresh_slot_allows_target_average(self):
        # Nothing imported, full slot ahead: the allowance IS the target.
        assert slot_allowed_import_w(6.0, 0.0, 0.0) == pytest.approx(6000.0)

    def test_an_early_burst_is_absorbed_not_forbidden(self):
        # 2 min at 9 kW = 0.3 kWh of the 1.5 kWh budget. 13 min remain:
        # (1.5-0.3)/(13/60) h = 5.538 kW — still generous, as the bill is.
        allowed = slot_allowed_import_w(6.0, 0.3, 120.0)
        assert allowed == pytest.approx(1.2 / (13 / 60) * 1000, rel=1e-3)

    def test_the_ceiling_tightens_as_the_slot_fills(self):
        early = slot_allowed_import_w(6.0, 0.5, 300.0)
        late = slot_allowed_import_w(6.0, 1.2, 600.0)
        assert late < early

    def test_budget_spent_means_zero(self):
        assert slot_allowed_import_w(6.0, 1.5, 600.0) == 0.0
        assert slot_allowed_import_w(6.0, 2.0, 600.0) == 0.0

    def test_the_reporters_numbers(self):
        """Last night: 9.9 kW draw, 747 W house, 6.0 target. Whatever the
        slot phase, the allowance can never hand the EV 9.9 kW for a whole
        slot — a full slot at the allowance averages exactly the target."""
        for elapsed in (0.0, 300.0, 600.0):
            imported = 6.0 * (elapsed / 3600.0)  # tracking target so far
            allowed = slot_allowed_import_w(6.0, imported, elapsed)
            remaining_h = (900.0 - elapsed) / 3600.0
            slot_avg = (imported + allowed / 1000.0 * remaining_h) / 0.25
            assert slot_avg == pytest.approx(6.0, rel=1e-6)

    def test_end_of_slot_does_not_explode(self):
        # 30 s left, budget nearly untouched: the naive division allows a
        # huge burst that is mathematically fine for THIS slot but is a
        # step change the offer-steadiness layer should never see.
        allowed = slot_allowed_import_w(6.0, 0.2, 870.0)
        assert allowed <= 6000.0 * 3, "bounded, not infinite"

    def test_no_target_means_no_ceiling(self):
        assert slot_allowed_import_w(0.0, 0.0, 100.0) is None
        assert slot_allowed_import_w(-1.0, 0.0, 100.0) is None


class TestPeakSlotTracker:
    """Clock-aligned accumulation — the slot the UTILITY sees, :00/:15/:30/:45."""

    def test_integrates_import_over_time(self):
        """At the real ~10 s cycle cadence, 5 min at 6 kW is 0.5 kWh."""
        t0 = datetime(2026, 8, 30, 12, 0, 0)
        tr = PeakSlotTracker()
        for i in range(31):                              # 0..300 s in 10 s steps
            tr.update(t0 + timedelta(seconds=10 * i), 6000.0)
        assert tr.imported_kwh == pytest.approx(0.5, rel=1e-3)
        assert tr.elapsed_s == pytest.approx(300.0)

    def test_resets_on_the_clock_boundary_not_a_rolling_window(self):
        t0 = datetime(2026, 8, 30, 12, 10, 0)
        tr = PeakSlotTracker()
        for i in range(37):                              # 12:10:00 → 12:16:00
            tr.update(t0 + timedelta(seconds=10 * i), 9000.0)
        # Only the 60 s after 12:15 belong to the new slot: 9 kW x 60 s.
        assert tr.imported_kwh == pytest.approx(9000.0 * 60 / 3600.0 / 1000.0,
                                                rel=1e-2)
        assert tr.elapsed_s == pytest.approx(60.0, abs=1.0)

    def test_a_long_gap_does_not_backfill_energy(self):
        """A restart or stalled cycle must not integrate a stale sample
        across many minutes — cap the integration step at the cycle scale."""
        t0 = datetime(2026, 8, 30, 12, 0, 0)
        tr = PeakSlotTracker()
        tr.update(t0, 9000.0)
        tr.update(t0 + timedelta(seconds=600), 9000.0)   # 10-min gap
        assert tr.imported_kwh < 9.0 * (600 / 3600.0), (
            "a gap is unknown, not 9 kW throughout"
        )

    def test_export_or_zero_import_accrues_nothing(self):
        t0 = datetime(2026, 8, 30, 12, 0, 0)
        tr = PeakSlotTracker()
        tr.update(t0, 0.0)
        tr.update(t0 + timedelta(seconds=60), -500.0)
        tr.update(t0 + timedelta(seconds=120), 0.0)
        assert tr.imported_kwh == pytest.approx(0.0)


# ── The decide() half: the allowance bounds the OFFER, before the wire ──

from custom_components.solar_energy_management.coordinator.charger_types import (  # noqa: E402
    ChargerIntent,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import decide  # noqa: E402

from .test_decide import _view  # noqa: E402


def _mk(mode, *, allowed_w, grid_import_w=0.0, this_w=0.0, peak_state="normal",
        **kw):
    v = _view(mode, **kw)
    f = v.fleet
    object.__setattr__(f, "peak_slot_allowed_w", allowed_w)
    object.__setattr__(f, "grid_import_w", grid_import_w)
    object.__setattr__(f, "peak_state", peak_state)
    object.__setattr__(v.power, "power_w", this_w)
    return v


@pytest.mark.unit
class TestFleetCarriesTheAllowance:
    def test_default_is_none_meaning_no_ceiling(self):
        assert FleetContext().peak_slot_allowed_w is None


@pytest.mark.unit
class TestTheGuardBoundsTheOffer:
    def test_the_reporters_case_always_max_is_capped(self):
        """29.08: 16 A / 9.9 kW offered with home at 747 W under a 6.0 kW
        target. With a fresh slot the allowance is 6000 W; the house is
        importing 747 W of it, so the EV gets what fits in ~5.25 kW."""
        v = _mk("always_max", allowed_w=6000.0, grid_import_w=747.0)
        d = decide(v)
        assert d.intent == ChargerIntent.CHARGE_AT_AMPS
        # 5253 W over 3x230 V nameplate → 7 A fits, 8 A does not.
        assert d.commanded_amps == 7
        assert "peak slot" in d.reason.lower()

    def test_a_spent_slot_floors_at_min_never_proactive_idle(self):
        """Stopping cars on a transient is the flap this project spent
        months killing — the preventive guard holds the floor and leaves
        the hard stop to #747's reactive EMERGENCY."""
        v = _mk("always_max", allowed_w=0.0, grid_import_w=500.0)
        d = decide(v)
        assert d.intent == ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6
        assert "peak slot" in d.reason.lower()

    def test_no_limit_configured_is_byte_identical(self):
        v = _mk("always_max", allowed_w=None, grid_import_w=5000.0)
        d = decide(v)
        assert d.intent == ChargerIntent.CHARGE_MAX
        assert "peak slot" not in d.reason.lower()

    def test_this_chargers_own_draw_is_not_counted_against_it(self):
        """grid_import INCLUDES the charger's current draw. The allowance
        for its next offer must credit that back, or the guard ratchets
        the offer down cycle over cycle to zero."""
        v = _mk("always_max", allowed_w=6000.0,
                grid_import_w=5747.0, this_w=5000.0)
        d = decide(v)
        # others = 5747-5000 = 747 → EV allowance ~5.25 kW → 7 A, same as
        # the fresh-slot case; without the credit it would be 0/min.
        assert d.commanded_amps == 7

    def test_an_offer_already_inside_the_allowance_is_untouched(self):
        v = _mk("min_plus_solar", allowed_w=6000.0, grid_import_w=0.0,
                solar_w=0.0, is_night=True,
                config={"ev_min_current": 6, "ev_phases": 3,
                        "ev_voltage": 230, "ev_max_current": 32,
                        "tariff_type": "fixed"})
        d = decide(v)
        if d.intent is ChargerIntent.CHARGE_AT_AMPS:
            assert "peak slot" not in d.reason.lower()

    def test_idle_and_disable_are_never_touched(self):
        v = _mk("off", allowed_w=1000.0, grid_import_w=5000.0)
        d = decide(v)
        assert d.intent != ChargerIntent.CHARGE_AT_AMPS
        assert "peak slot" not in d.reason.lower()

    def test_747_emergency_stays_senior(self):
        """The reactive hard stop outranks the preventive floor."""
        v = _mk("always_max", allowed_w=0.0, grid_import_w=9000.0,
                peak_state="emergency")
        d = decide(v)
        assert d.intent == ChargerIntent.IDLE


# ── The security layer covers EVERYTHING SEM commands, not just the EV ──
# (Guido: "peak-management is a security layer and above all — it does not
# matter what mode any device has." The limit lives at the POWER METER, so
# every import SEM creates is bounded by the same slot allowance.)

from custom_components.solar_energy_management.coordinator.peak_guard import (  # noqa: E402
    clamp_import_command,
)


class TestClampImportCommand:
    """The one reusable clamp every non-EV command family shares."""

    def test_no_ceiling_passes_through(self):
        assert clamp_import_command(5000.0, None, 3000.0) == (5000.0, False)

    def test_clamps_to_headroom(self):
        # allowed 2000, others importing 500 → 1500 left for this command.
        assert clamp_import_command(5000.0, 2000.0, 500.0) == (1500.0, True)

    def test_own_draw_is_credited_back(self):
        # import 3000 of which 2500 is this device already charging:
        # others = 500 → headroom 1500, not −1000.
        w, clamped = clamp_import_command(5000.0, 2000.0, 3000.0,
                                          own_grid_draw_w=2500.0)
        assert (w, clamped) == (1500.0, True)

    def test_spent_budget_floors_at_zero(self):
        assert clamp_import_command(5000.0, 0.0, 800.0) == (0.0, True)

    def test_fitting_command_is_untouched(self):
        assert clamp_import_command(1000.0, 6000.0, 500.0) == (1000.0, False)


@pytest.mark.asyncio
class TestCheapHoursActivationIsGuarded:
    """A cheap-hours grid force must FIT the slot before it starts —
    price says go, the meter's budget says how much."""

    def _controller_and_device(self, allowed_w):
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            SurplusController,
        )
        from unittest.mock import AsyncMock, MagicMock
        from custom_components.solar_energy_management.devices.base import (
            DeviceControlMode,
        )
        hass = MagicMock(); hass.services.async_call = AsyncMock()
        sc = SurplusController(hass)
        d = MagicMock()
        d.device_id, d.name, d.priority = "boiler", "Boiler", 5
        d.min_power_threshold = 3000
        d.is_enabled, d.managed_externally, d.is_active = True, False, False
        d.device_type = MagicMock(value="switch")
        d.activate = AsyncMock(return_value=3000)
        d.adjust_power = AsyncMock(return_value=3000)
        d.get_current_consumption = MagicMock(return_value=0.0)
        d.can_activate = MagicMock(return_value=True)
        d.can_deactivate = MagicMock(return_value=True)
        d.record_activated = MagicMock(); d.record_deactivated = MagicMock()
        d.reset_surplus_timer = MagicMock(); d.status = MagicMock()
        d.control_mode = DeviceControlMode.SURPLUS
        d._sem_owned = False; d._sem_commanded = False
        d.is_deadline_approaching = False
        d._offpeak_forced = False; d._offpeak_forced_date = None
        d._batt_overnight_forced = False; d._batt_overnight_forced_date = None
        d.needs_offpeak_activation = True
        d.remaining_daily_runtime_sec = 3600; d.daily_min_runtime_sec = 3600
        d.daily_targets_met = False; d.daily_max_runtime_reached = False
        d.stop_condition_met = False
        d.top_up_policy = "grid_allowed"
        d.battery_assist_enabled = False; d.battery_eligible_overnight = False
        d.stop_entity = ""; d.stop_at = 0
        sc.register_device(d)
        return sc, d

    async def test_activation_refused_when_it_cannot_fit_the_slot(self):
        sc, d = self._controller_and_device(allowed_w=1000.0)
        await sc.update(0.0, price_level="cheap",
                        peak_slot_allowed_w=1000.0, grid_import_w=200.0)
        d.activate.assert_not_awaited()

    async def test_activation_proceeds_with_headroom(self):
        sc, d = self._controller_and_device(allowed_w=6000.0)
        await sc.update(0.0, price_level="cheap",
                        peak_slot_allowed_w=6000.0, grid_import_w=200.0)
        d.activate.assert_awaited()

    async def test_no_ceiling_behaves_as_before(self):
        sc, d = self._controller_and_device(allowed_w=None)
        await sc.update(0.0, price_level="cheap",
                        peak_slot_allowed_w=None, grid_import_w=5000.0)
        d.activate.assert_awaited()


class TestTheOffSwitch:
    """The guard's own opt-out (Guido, 30.08): one config key, read where
    the allowance is computed, so OFF disarms every consumer at once —
    decide's EV bound, the battery charge clamp, the cheap-hours gate —
    while the reactive shedding stands untouched."""

    def test_the_flow_offers_it_default_on(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "config_flow.py").read_text()
        assert '"peak_slot_guard_enabled": _c("peak_slot_guard_enabled", True)' in src

    def test_the_coordinator_reads_it_at_the_one_place(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            coordinator as cm,
        )
        src = inspect.getsource(cm)
        i = src.index('peak_slot_guard_enabled')
        window = src[i - 400:i + 400]
        assert "_peak_slot_allowed_w" in window or "slot_allowed" in window, (
            "the switch must gate the ALLOWANCE computation — one switch, "
            "every consumer"
        )

    def test_strings_describe_it(self):
        import json, pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        d = json.loads((root / "strings.json").read_text())
        txt = json.dumps(d)
        assert "peak_slot_guard_enabled" in txt
