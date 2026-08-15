"""#776 — exported battery energy gets a flow bucket and honest money.

``flow_calculator`` deliberately disallowed the ``(battery_discharge,
grid_export)`` pair — its comment called battery-to-grid arbitrage "out of
scope". That predates #638 C6, which wired plan-gated arbitrage selling,
and ``force_discharge`` mode has exported battery energy from the shipped
UI all along. During any battery export the exported watts were
unattributed (a systematic hole for the length of the sell), and the
savings math booked the RAW discharge increment — an exported kWh earned
avoided-import savings it never delivered to the house while the grid
meter booked the same kWh as export revenue. One kWh, two credits.

The fix: a ``battery_to_grid`` flow field fed by the same greedy priority
allocator (solar keeps its first claim on export — ``solar_to_grid``
remains the slack variable), and a savings base bounded by the
home-delivered share of the discharge. Exported battery kWh earn exactly
their export revenue — once.
"""
import pytest

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyFlows,
    PowerFlows,
    PowerReadings,
)


def _fc():
    from unittest.mock import MagicMock
    fc = FlowCalculator.__new__(FlowCalculator)
    fc.update_interval = MagicMock(total_seconds=lambda: 10.0)
    return fc


def _power(**kw):
    p = PowerReadings(**kw)
    grid = kw.get("grid_power", 0.0)
    batt = kw.get("battery_power", 0.0)
    p.grid_import_power = max(0.0, -grid)
    p.grid_export_power = max(0.0, grid)
    p.battery_charge_power = max(0.0, batt)
    p.battery_discharge_power = max(0.0, -batt)
    return p


# ───────────────────────────────────────────────────────────────────────
# 1. the flow — exported discharge is attributed, not dropped
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheExportedDischargeHasABucket:
    def test_a_night_sell_books_battery_to_grid(self):
        """The arbitrage/force-discharge shape: no sun, the battery
        discharges past the house and the meter exports the rest."""
        flows = _fc().calculate_power_flows(_power(
            solar_power=0.0, battery_power=-3000.0,
            home_consumption_power=500.0, grid_power=2500.0,
        ))
        assert flows.battery_to_home == pytest.approx(500.0)
        assert flows.battery_to_grid == pytest.approx(2500.0)

    def test_the_discharge_is_fully_attributed(self):
        """Before the fix the exported 2.5 kW simply vanished from the
        flow ledger — 'a small honest under-count' per the old comment,
        systematic for the length of a sell after C6."""
        flows = _fc().calculate_power_flows(_power(
            solar_power=0.0, battery_power=-3000.0,
            home_consumption_power=500.0, grid_power=2500.0,
        ))
        attributed = (flows.battery_to_home + flows.battery_to_ev
                      + flows.battery_to_grid)
        assert attributed == pytest.approx(3000.0)

    def test_solar_keeps_first_claim_on_the_export(self):
        """Simultaneous solar surplus and battery export: solar_to_grid
        stays the slack variable and takes the export first; only what
        solar cannot claim is the battery's."""
        flows = _fc().calculate_power_flows(_power(
            solar_power=2000.0, battery_power=-1000.0,
            home_consumption_power=500.0, grid_power=2500.0,
        ))
        assert flows.solar_to_home == pytest.approx(500.0)
        assert flows.solar_to_grid == pytest.approx(1500.0)
        assert flows.battery_to_grid == pytest.approx(1000.0)

    def test_a_self_consumption_day_is_unchanged(self):
        """No export → no battery_to_grid; the existing attribution is
        untouched (the #349 semantics stay pinned by their own suite)."""
        flows = _fc().calculate_power_flows(_power(
            solar_power=0.0, battery_power=-1000.0,
            home_consumption_power=1000.0, grid_power=0.0,
        ))
        assert flows.battery_to_home == pytest.approx(1000.0)
        assert flows.battery_to_grid == pytest.approx(0.0)


# ───────────────────────────────────────────────────────────────────────
# 2. the money — one kWh, one credit
# ───────────────────────────────────────────────────────────────────────

def _calc():
    from unittest.mock import MagicMock
    from custom_components.solar_energy_management.coordinator.energy_calculator import (
        EnergyCalculator,
    )
    c = EnergyCalculator.__new__(EnergyCalculator)
    c.__init__(MagicMock(), {})
    c._import_rate = 0.30
    return c


@pytest.mark.unit
class TestTheMoneyIsBookedOnce:
    def test_an_export_only_discharge_earns_no_savings(self):
        """Everything went to the grid: the export revenue at the meter
        is the whole earning; avoided-import savings on top would pay
        the same kWh twice."""
        c = _calc()
        flows = PowerFlows(battery_to_home=0.0, battery_to_ev=0.0,
                           battery_to_grid=3000.0)
        s = c._battery_discharge_savings(
            _power(battery_power=-3000.0), 0.5, flows)
        assert s == pytest.approx(0.0)

    def test_the_home_delivered_share_scales_the_savings(self):
        c = _calc()
        flows = PowerFlows(battery_to_home=1000.0, battery_to_ev=0.0,
                           battery_to_grid=1000.0)
        half = c._battery_discharge_savings(
            _power(battery_power=-2000.0), 1.0, flows)
        full = c._battery_discharge_savings(
            _power(battery_power=-2000.0), 1.0, None)
        assert full == pytest.approx(0.30)  # 1 kWh × unknown-origin full rate
        assert half == pytest.approx(full / 2)

    def test_no_flow_data_keeps_the_legacy_credit(self):
        """Silence is not a measurement (#755): a cycle without flow
        attribution must not zero the savings — it keeps the legacy
        full-increment base, exactly like the #770 unknown pool."""
        c = _calc()
        s = c._battery_discharge_savings(
            _power(battery_power=-1000.0), 1.0, None)
        assert s == pytest.approx(0.30)

    def test_zero_attribution_keeps_the_legacy_credit(self):
        """Flows present but nothing attributed (sensor-lag cycle) is
        the same silence, not a measured zero."""
        c = _calc()
        s = c._battery_discharge_savings(
            _power(battery_power=-1000.0), 1.0, PowerFlows())
        assert s == pytest.approx(0.30)

    def test_the_booking_site_passes_the_flows(self):
        """The call site in calculate_energy must hand power_flows to the
        savings math — a bound function nobody passes flows to is the
        fix that never runs."""
        import inspect
        from custom_components.solar_energy_management.coordinator.energy_calculator import (
            EnergyCalculator,
        )
        src = inspect.getsource(EnergyCalculator.calculate_energy)
        assert "_battery_discharge_savings(" in src
        assert "_battery_discharge_savings(\n" in src or \
               "power, discharge_increment, power_flows" in src


# ───────────────────────────────────────────────────────────────────────
# 3. the surface — the bucket is readable end to end
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheRowSurfaces776:
    def test_both_flow_types_carry_the_field(self):
        assert "battery_to_grid" in PowerFlows.__dataclass_fields__
        assert "battery_to_grid" in EnergyFlows.__dataclass_fields__

    def test_the_accumulator_integrates_it(self):
        assert "battery_to_grid" in FlowCalculator._ACCUMULATED_ATTRS

    def test_the_keys_are_published(self):
        from custom_components.solar_energy_management.coordinator.types import (
            SEMData,
        )
        data = SEMData()
        data.power_flows = PowerFlows(battery_to_grid=2500.0)
        data.energy_flows = EnergyFlows(battery_to_grid=1.25)
        d = data.to_dict()
        assert d["flow_battery_to_grid_power"] == 2500.0
        assert d["flow_battery_to_grid_energy"] == 1.25

    def test_every_key_has_an_entity(self):
        from custom_components.solar_energy_management import sensor as sensor_mod
        keys = {desc.key for desc in sensor_mod.SENSOR_TYPES}
        assert "flow_battery_to_grid_power" in keys
        assert "flow_battery_to_grid_energy" in keys

    def test_the_out_of_scope_comment_is_gone(self):
        """The comment that declared battery-to-grid out of scope must
        not outlive the code that made it wrong."""
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            flow_calculator,
        )
        src = inspect.getsource(flow_calculator)
        assert "out of scope here" not in src
