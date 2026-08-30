"""#872.2 — the load double-count that "doesn't self-resolve" is ours.

RienduPre's install reports the same health-check violation for hours:

    Controlled loads vs home residual: members sum to 3.34kWh against a
    fleet total of 1.81kWh — 1.53kWh over the 0.50kWh band. One physical
    quantity is counted twice (a renamed or removed id whose bucket is
    still published). Members: energy_dashboard_airconditioner=1.12kWh,
    ev_charger=1.10kWh, heat_pump=1.00kWh, …

He checked, and reported back that every member is a real, currently active
device — so the message sent him hunting for a stale id that does not exist.

It is not a stale id. The members are every device in the surplus
controller, EV chargers included, and they are compared against
``daily_home`` — which by SEM's own definition EXCLUDES the EV:

    home = max(0, solar + grid_import + batt_discharge
                  − ev − grid_export − batt_charge)

So any install charging a car reports its charger's energy on one side of a
comparison that removed it from the other. His numbers are exactly that:
drop ``ev_charger=1.10`` and the members sum to 2.24 against 1.81 — inside
the 0.50 kWh band, and the violation never fires.

The check's own call site already knew this — "chargers are members of the
EV day (over-count only — shortfall IS the baseload)" — and then passed
every device anyway.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
)
from custom_components.solar_energy_management.devices.base import DeviceType


def _device(device_id, kwh, device_type=DeviceType.SWITCH):
    return SimpleNamespace(device_id=device_id, daily_energy_kwh=kwh,
                           device_type=device_type)


#: RienduPre's members, to the digit (#872).
HIS_DEVICES = [
    _device("energy_dashboard_airconditioner", 1.12),
    _device("ev_charger", 1.10, DeviceType.CURRENT_CONTROL),
    _device("heat_pump", 1.00),
    _device("energy_dashboard_schuur_apparatuur", 0.04),
    _device("energy_dashboard_computer_apparatuur_marianne_energie", 0.03),
    _device("energy_dashboard_zwembad_warmtepomp", 0.02),
    _device("energy_dashboard_zwembad_pomp", 0.01),
    _device("energy_dashboard_printer_energie", 0.01),
    _device("energy_dashboard_fiets_laadstation", 0.01),
    _device("ev_charger_1", 0.00, DeviceType.CURRENT_CONTROL),
]
HIS_DAILY_HOME = 1.81


def _members(devices):
    """What the coordinator hands the check."""
    from custom_components.solar_energy_management.coordinator.health_check import (
        home_member_totals,
    )
    return home_member_totals(devices)


class TestTheEvIsNotAMemberOfHome:
    def test_a_charger_is_excluded_from_the_home_members(self):
        members = _members(HIS_DEVICES)
        assert "ev_charger" not in members, (
            "the home row subtracts EV energy, so counting a charger as a "
            "member of home compares it against a total it was removed from"
        )
        assert "ev_charger_1" not in members
        assert "heat_pump" in members, "a heat pump IS part of the house"

    def test_his_install_no_longer_reports_a_violation(self):
        """The exact reading from #872, which repeated for hours."""
        v = HealthCheck()._reconcile_partition(
            "Controlled loads vs home residual",
            _members(HIS_DEVICES),
            HIS_DAILY_HOME,
        )
        assert v is None, f"still fires: {v}"

    def test_it_still_fires_on_a_real_over_count(self):
        """The check must keep catching what it exists for — a genuine
        double-count among house loads."""
        doubled = [_device("heat_pump", 3.0), _device("heat_pump_copy", 3.0)]
        v = HealthCheck()._reconcile_partition(
            "Controlled loads vs home residual", _members(doubled), 1.5)
        assert v is not None and "counted twice" in v

    def test_a_device_without_a_type_is_kept(self):
        """Unknown shape means "part of the house" — dropping members on a
        missing attribute would silently disable the check."""
        odd = SimpleNamespace(device_id="mystery", daily_energy_kwh=0.5)
        assert "mystery" in _members([odd])
