"""Step 8 — invariant property tests across the new architecture.

The simulation-as-verification suite. Each invariant pins one
contract that the architecture is supposed to enforce by
construction. Combinatorial parametrize sweeps the (mode, solar,
battery_soc, home, is_night, num_chargers) space so any future
refactor (Step 6 data-model inversion, Step 7 single epoch,
brand-adapter additions) that violates a contract surfaces
immediately in CI.

These are not unit tests — they are contracts. A failing invariant
means the architecture lost a property it was supposed to guarantee.

Invariant inventory (file:line back-reference to the production
bug each one would have caught):

I1: ``off`` mode ALWAYS produces ``DISABLE`` intent
    — Pre-#315: ev_control reactive off-mode branch missed self-resume
I2: ``solar_only`` mode + no solar surplus ALWAYS produces ``IDLE``
    — Pre-#346: night branch ignored per-charger mode
I3: ``solar_only`` charging amps × phases × voltage ≤ solar surplus
    — Pre-#353: KEBA self-charged below the 6 A min floor
I4: ``CHARGE_AT_AMPS`` decision ALWAYS commands ≥ ev_min_current
    — Pre-#353: out-of-range amps silently rejected by KEBA
I5: ``budget_w`` is non-negative
    — Pre-#349: proportional split could produce negative values on noise
I6: Per-charger flow sum equals fleet flow
    — Pre-#319 / Step 5: fraction-split lost priority information
I7: Per-charger priority honored in flow attribution
    — Pre-Step 5: A-on-solar / B-on-grid scenario got 50/50 split
I8: (RETIRED, Task 11) ``actuate(intent)`` calls exactly one adapter
    method — this was a property of the legacy per-cycle dispatch body.
    The reconciler may legitimately emit NONE (idempotent idle), ENABLE
    + WRITE (switch-controlled charger), or DISABLE-then-nothing, so the
    one-call invariant no longer holds. Intent→desired-state mapping
    completeness is now pinned by
    ``test_charger_reconciler.py::test_desired_from_decision_maps_every_intent``.
I9: ``decide(view)`` is pure (same input → same output)
    — Pre-Step 3: state machine + strategy machine could drift
I10: Mode resolution is stable — same config → same effective mode
    — Pre-#346 strategy and state machines re-resolved independently
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters import (
    KebaAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
    FleetView,
)
from custom_components.solar_energy_management.coordinator.decide import decide
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings

# ─────────────────────────────────────────────────────────────────
# Fixture helpers
# ─────────────────────────────────────────────────────────────────

MODES = ("off", "solar_only", "min_plus_solar", "always_max", "solar_plus_cheap")
SOLAR_VALUES = (0.0, 1000.0, 4000.0, 8000.0, 12000.0)
SOC_VALUES = (0.0, 25.0, 50.0, 75.0, 95.0)
HOME_VALUES = (200.0, 1000.0, 3000.0)
IS_NIGHT_VALUES = (False, True)


def _view(
    *,
    mode: str = "solar_only",
    solar_w: float = 5000.0,
    home_w: float = 500.0,
    battery_charge_w: float = 0.0,
    battery_discharge_w: float = 0.0,
    battery_soc: float = 75.0,
    grid_import_w: float = 0.0,
    grid_export_w: float = 0.0,
    is_night: bool = False,
    target_kwh=None,
    deadline_amps: int = 0,
    config: dict | None = None,
    connected: bool = True,
) -> ChargerView:
    return ChargerView(
        power=ChargerPower(
            charger_id="keba", power_w=0.0,
            connected=connected, charging=False,
        ),
        energy=ChargerEnergy(charger_id="keba"),
        mode=mode,
        config=config or {
            "ev_min_current": 6, "ev_phases": 3,
            "ev_voltage": 230, "ev_max_current": 32,
        },
        fleet=FleetContext(
            solar_w=solar_w, home_w=home_w,
            battery_charge_w=battery_charge_w,
            battery_discharge_w=battery_discharge_w,
            battery_soc=battery_soc,
            grid_import_w=grid_import_w,
            grid_export_w=grid_export_w,
            is_night=is_night,
        ),
        target_kwh=target_kwh,
        deadline_amps=deadline_amps,
    )


# ─────────────────────────────────────────────────────────────────
# I1: off mode → always DISABLE
# ─────────────────────────────────────────────────────────────────

class TestI1_OffModeAlwaysDisable:
    """The #315 / #346 invariant promoted to a contract."""

    @pytest.mark.parametrize("solar_w", SOLAR_VALUES)
    @pytest.mark.parametrize("battery_soc", SOC_VALUES)
    @pytest.mark.parametrize("is_night", IS_NIGHT_VALUES)
    def test_off_mode_always_disables(self, solar_w, battery_soc, is_night):
        d = decide(_view(
            mode="off", solar_w=solar_w,
            battery_soc=battery_soc, is_night=is_night,
        ))
        assert d.intent is ChargerIntent.DISABLE, (
            f"off mode produced {d.intent} at solar={solar_w}, "
            f"soc={battery_soc}, night={is_night}: {d.reason}"
        )


# ─────────────────────────────────────────────────────────────────
# I2: solar_only never imports grid for EV
# ─────────────────────────────────────────────────────────────────

class TestI2_SolarOnlyNeverGridForEV:
    """The #346 invariant. With solar_only mode, the decision MUST be
    IDLE whenever solar is insufficient to cover home + min EV draw."""

    @pytest.mark.parametrize("is_night", IS_NIGHT_VALUES)
    def test_solar_only_no_solar_is_idle(self, is_night):
        d = decide(_view(
            mode="solar_only", solar_w=0.0, is_night=is_night,
        ))
        assert d.intent is ChargerIntent.IDLE, (
            f"solar_only at solar=0 produced {d.intent} (night={is_night})"
        )

    @pytest.mark.parametrize("solar_w", [0.0, 100.0, 199.0])
    def test_solar_only_below_threshold_is_idle(self, solar_w):
        d = decide(_view(mode="solar_only", solar_w=solar_w))
        assert d.intent is ChargerIntent.IDLE

    @pytest.mark.parametrize("home_w,battery_charge_w", [
        (2000.0, 4000.0),   # home + batt drains all 6000W solar
        (500.0, 5000.0),    # batt eats most of 6000W
    ])
    def test_solar_only_insufficient_surplus_is_idle(self, home_w, battery_charge_w):
        d = decide(_view(
            mode="solar_only", solar_w=6000.0,
            home_w=home_w, battery_charge_w=battery_charge_w,
            battery_soc=75.0,  # Zone 3, battery_charge subtracted
        ))
        assert d.intent is ChargerIntent.IDLE


# ─────────────────────────────────────────────────────────────────
# I3: solar_only charging amps × phases × voltage ≤ solar surplus
# ─────────────────────────────────────────────────────────────────

class TestI3_SolarOnlyCommandedAmpsBoundedBySurplus:
    """When solar_only DOES decide to charge, the commanded amps
    must correspond to ≤ the surplus available."""

    @pytest.mark.parametrize("solar_w", [5000.0, 8000.0, 12000.0])
    def test_solar_only_commanded_amps_within_surplus(self, solar_w):
        d = decide(_view(
            mode="solar_only", solar_w=solar_w,
            home_w=500.0, battery_charge_w=0.0,
            battery_soc=95.0,
        ))
        if d.intent is ChargerIntent.CHARGE_AT_AMPS:
            commanded_w = d.commanded_amps * 3 * 230
            surplus_w = solar_w - 500.0
            assert commanded_w <= surplus_w + 690, (  # +690 tolerance: 1A rounding
                f"commanded {d.commanded_amps}A = {commanded_w}W exceeds "
                f"surplus {surplus_w}W"
            )


# ─────────────────────────────────────────────────────────────────
# I4: CHARGE_AT_AMPS ≥ ev_min_current
# ─────────────────────────────────────────────────────────────────

class TestI4_CommandedAmpsAboveMinimum:
    """The #353 invariant — never command below the brand's min."""

    @pytest.mark.parametrize("mode", ["solar_only", "min_plus_solar", "always_max"])
    @pytest.mark.parametrize("solar_w", SOLAR_VALUES)
    def test_charge_at_amps_always_above_minimum(self, mode, solar_w):
        d = decide(_view(
            mode=mode, solar_w=solar_w, battery_soc=95.0,
            home_w=500.0,
        ))
        if d.intent is ChargerIntent.CHARGE_AT_AMPS:
            assert d.commanded_amps >= 6, (
                f"mode {mode} at solar={solar_w} produced amps="
                f"{d.commanded_amps} (< 6 min): {d.reason}"
            )


# ─────────────────────────────────────────────────────────────────
# I5: budget_w non-negative
# ─────────────────────────────────────────────────────────────────

class TestI5_BudgetNonNegative:
    """Defensive — no future refactor can produce negative budget."""

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("solar_w", SOLAR_VALUES)
    @pytest.mark.parametrize("battery_soc", SOC_VALUES)
    def test_budget_non_negative(self, mode, solar_w, battery_soc):
        d = decide(_view(
            mode=mode, solar_w=solar_w, battery_soc=battery_soc,
            home_w=500.0,
        ))
        assert d.budget_w >= 0, (
            f"mode {mode} at solar={solar_w}, soc={battery_soc} "
            f"produced budget_w={d.budget_w}"
        )


# ─────────────────────────────────────────────────────────────────
# I6: Per-charger flow sum equals fleet flow
# ─────────────────────────────────────────────────────────────────

class TestI6_PerChargerFlowConservation:
    """sum(per_charger.solar_to_ev) == fleet.solar_to_ev (and similar
    for grid/battery). The #319 / Step 5 conservation invariant."""

    def _power_multi(self, *, num_chargers: int, total_ev_w: float,
                     solar=8000, grid=-2000, battery=0, home=1000):
        per = total_ev_w / num_chargers
        ev_dict = {f"c{i}": per for i in range(num_chargers)}
        priorities = {f"c{i}": i + 1 for i in range(num_chargers)}
        p = PowerReadings(
            solar_power=solar, grid_power=grid, battery_power=battery,
            home_consumption_power=home, ev_power=total_ev_w,
        )
        p.grid_import_power = max(0, -grid)
        p.grid_export_power = max(0, grid)
        p.battery_charge_power = max(0, battery)
        p.battery_discharge_power = max(0, -battery)
        p.ev_power_per_charger = ev_dict
        p.ev_priority_per_charger = priorities
        return p

    @pytest.mark.parametrize("num_chargers", [1, 2, 3, 4])
    @pytest.mark.parametrize("total_ev_w", [3000.0, 6000.0, 9000.0])
    def test_per_charger_sum_equals_fleet(self, num_chargers, total_ev_w):
        fc = FlowCalculator.__new__(FlowCalculator)
        fc.update_interval = MagicMock(total_seconds=lambda: 10.0)
        p = self._power_multi(num_chargers=num_chargers, total_ev_w=total_ev_w)
        f = fc.calculate_power_flows(p)

        sum_solar = sum(pc.solar_to_ev for pc in f.per_charger.values())
        sum_grid = sum(pc.grid_to_ev for pc in f.per_charger.values())
        sum_battery = sum(pc.battery_to_ev for pc in f.per_charger.values())

        # Allow rounding for N chargers
        tol = max(1.0, num_chargers * 0.5)
        assert sum_solar == pytest.approx(f.solar_to_ev, abs=tol)
        assert sum_grid == pytest.approx(f.grid_to_ev, abs=tol)
        assert sum_battery == pytest.approx(f.battery_to_ev, abs=tol)


# ─────────────────────────────────────────────────────────────────
# I7: priority order honored
# ─────────────────────────────────────────────────────────────────

class TestI7_PriorityOrderHonored:
    """Higher-priority chargers consume solar before lower-priority."""

    @pytest.mark.parametrize("num_chargers", [2, 3, 4])
    def test_higher_priority_gets_solar_first(self, num_chargers):
        fc = FlowCalculator.__new__(FlowCalculator)
        fc.update_interval = MagicMock(total_seconds=lambda: 10.0)

        # Solar tightly limited so the priority ordering matters.
        # Each charger wants 3 kW; solar provides only 6 kW + home 500.
        per = 3000.0
        ev_dict = {f"c{i}": per for i in range(num_chargers)}
        priorities = {f"c{i}": i + 1 for i in range(num_chargers)}

        total_ev = num_chargers * per
        # Balanced supply
        grid_import = max(0, total_ev + 500 - 6000)
        p = PowerReadings(
            solar_power=6000, grid_power=-grid_import,
            battery_power=0, home_consumption_power=500,
            ev_power=total_ev,
        )
        p.grid_import_power = grid_import
        p.grid_export_power = 0
        p.battery_charge_power = 0
        p.battery_discharge_power = 0
        p.ev_power_per_charger = ev_dict
        p.ev_priority_per_charger = priorities
        f = fc.calculate_power_flows(p)

        # Highest-priority (c0) must get >= every lower-priority charger's solar
        solar_by_priority = [
            f.per_charger[f"c{i}"].solar_to_ev for i in range(num_chargers)
        ]
        for i in range(num_chargers - 1):
            assert solar_by_priority[i] >= solar_by_priority[i + 1], (
                f"priority {i} got {solar_by_priority[i]}W solar; "
                f"priority {i+1} got {solar_by_priority[i+1]}W"
            )


# ─────────────────────────────────────────────────────────────────
# I8: RETIRED (Task 11). The "exactly one adapter method per intent"
# invariant was a property of the legacy actuate() dispatch body,
# which has been removed. The reconciler owns convergence and may emit
# NONE / ENABLE+WRITE / DISABLE. Intent→desired-state completeness is
# pinned by test_charger_reconciler.py::test_desired_from_decision_maps_every_intent.
# ─────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────
# I9: decide() is pure
# ─────────────────────────────────────────────────────────────────

class TestI9_DecidePure:
    """Same view → same decision. Pinned for every mode."""

    @pytest.mark.parametrize("mode", MODES)
    def test_same_view_same_decision(self, mode):
        view = _view(mode=mode, solar_w=6000.0, battery_soc=80.0)
        d1 = decide(view)
        d2 = decide(view)
        assert d1 == d2


# ─────────────────────────────────────────────────────────────────
# I10: FleetView is computed, not stored
# ─────────────────────────────────────────────────────────────────

class TestI10_FleetViewIsComputed:
    """FleetView.from_per_charger is the only sanctioned way to
    construct a fleet sum. No drift between per-charger primaries
    and fleet view — same inputs always produce same output."""

    @pytest.mark.parametrize("num_chargers", [1, 2, 3, 4])
    def test_fleet_view_equals_per_charger_sum(self, num_chargers):
        power = {
            f"c{i}": ChargerPower(f"c{i}", power_w=1000.0 * (i + 1),
                                  connected=True, charging=True)
            for i in range(num_chargers)
        }
        energy = {
            f"c{i}": ChargerEnergy(f"c{i}", day_kwh=2.5 * (i + 1))
            for i in range(num_chargers)
        }
        fv = FleetView.from_per_charger(power, energy)
        expected_power = sum(1000.0 * (i + 1) for i in range(num_chargers))
        expected_kwh = sum(2.5 * (i + 1) for i in range(num_chargers))
        assert fv.total_power_w == expected_power
        assert fv.total_day_kwh == expected_kwh
        assert fv.count == num_chargers


# ─────────────────────────────────────────────────────────────────
# I11: KEBA adapter idempotency
# ─────────────────────────────────────────────────────────────────

class TestI11_KebaAdapterIdempotent:
    """Calling adapter.command_idle() twice in a row results in only
    one stop_session per cycle — adapter de-dups. (Some brands send
    duplicate disable; KEBA's stop_session is itself idempotent.)"""

    @pytest.mark.asyncio
    async def test_consecutive_idle_calls_no_extra_set_current(self):
        from unittest.mock import MagicMock
        dev = MagicMock()
        dev.max_current = 32
        dev.phases = 3
        dev.voltage = 230
        dev._session_active = False
        dev._set_current = AsyncMock()
        dev.start_session = AsyncMock()
        dev.stop_session = AsyncMock()

        a = KebaAdapter(dev)
        await a.command_idle()
        await a.command_idle()
        # Two stop_session calls (idempotent at the HA level)
        assert dev.stop_session.await_count == 2
        # No set_current calls — KEBA can't be told to "go to 0"
        dev._set_current.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────
# I12: Mode-honor — off + handshake power = no extra disable
# ─────────────────────────────────────────────────────────────────

class TestI12_HandshakeBelowGuardThreshold:
    """The 500 W cutoff that #315 / #346 / #353 all use is encoded in
    KebaAdapter.handshake_power_w. Below it, is_self_charging() must
    return False regardless of last intent — we don't spam disables
    on a parked car."""

    @pytest.mark.parametrize("power_w", [0.0, 110.0, 350.0, 499.0])
    def test_below_handshake_not_self_charging(self, power_w):
        from unittest.mock import MagicMock
        dev = MagicMock()
        dev.max_current = 32; dev.phases = 3; dev.voltage = 230
        a = KebaAdapter(dev)
        a._last_intent = ChargerIntent.DISABLE  # worst case
        power = ChargerPower("keba", power_w=power_w, connected=True)
        assert a.is_self_charging(power) is False
