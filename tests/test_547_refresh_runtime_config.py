"""#547 — knobs cached at controller construction must apply WITHOUT a reload.

``async_update_config`` (and the persist_* no-reload writers) mutate
``self.config`` in place. Knobs read per-cycle off ``self.config`` already
apply live; the few scalars CACHED on a controller at construction need an
explicit push. ``SEMCoordinator.refresh_runtime_config()`` does that push —
attribute assignment / setters, never a rebuild (so legionella timers, cost
accumulators, smoothing windows survive).

These tests call the real method on a lightweight stub (it only touches
``config`` + the controller handles), so no full coordinator construction.
"""
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    StaticTariffProvider,
)
from custom_components.solar_energy_management.tariff.calendar_provider import (
    CalendarTariffProvider,
)


class _Dev:
    """Minimal stand-in for a registered controllable device."""

    def __init__(self, **attrs):
        self.__dict__.update(attrs)


class _SurplusController:
    def __init__(self, devices=None):
        self.regulation_offset = -1.0
        self.max_export_w = -1.0
        self._devices = devices or {}

    def get_device(self, device_id):
        return self._devices.get(device_id)


def _coord(config, *, surplus=None, ev_devices=None, tariff=None, load_manager=None):
    """A stub with just the attributes refresh_runtime_config reads."""
    return SimpleNamespace(
        config=config,
        _surplus_controller=surplus,
        _ev_devices=ev_devices,
        _tariff_provider=tariff,
        _load_manager=load_manager,
    )


@pytest.mark.unit
class TestRefreshRuntimeConfig:
    def test_regulation_offset_and_export_cap_pushed(self):
        sc = _SurplusController()
        coord = _coord({"regulation_offset": 80, "max_export_power": 7000}, surplus=sc)
        SEMCoordinator.refresh_runtime_config(coord)
        assert sc.regulation_offset == 80.0
        assert sc.max_export_w == 7000.0

    def test_heat_pump_tunables_pushed(self):
        hp = _Dev(boost_offset=0, max_setpoint=0, force_on_threshold=0,
                  invert_sg_ready=False, priority=1)
        sc = _SurplusController({"heat_pump": hp})
        coord = _coord({
            "heat_pump_boost_offset": 3.5, "heat_pump_max_setpoint": 60,
            "heat_pump_force_on_threshold": 4000, "heat_pump_invert_sg_ready": True,
            "heat_pump_priority": 7,
        }, surplus=sc)
        SEMCoordinator.refresh_runtime_config(coord)
        assert hp.boost_offset == 3.5
        assert hp.max_setpoint == 60.0
        assert hp.force_on_threshold == 4000.0
        assert hp.invert_sg_ready is True
        assert hp.priority == 7

    def test_hot_water_targets_pushed_timer_preserved(self):
        # The legionella timer state must NOT be reset by the refresh.
        hw = _Dev(max_temperature=0, min_temperature=0, solar_target_temp=0,
                  legionella_target_temp=0, legionella_interval_hours=0, priority=1,
                  hours_since_legionella=99.0, _legionella_cycle_active=True)
        sc = _SurplusController({"hot_water": hw})
        coord = _coord({
            "hot_water_max_temperature": 65, "hot_water_minimum_temperature": 42,
            "hot_water_solar_target": 52, "hot_water_legionella_target": 70,
            "hot_water_legionella_interval_hours": 200, "hot_water_priority": 5,
        }, surplus=sc)
        SEMCoordinator.refresh_runtime_config(coord)
        assert hw.max_temperature == 65.0
        assert hw.solar_target_temp == 52.0
        assert hw.legionella_interval_hours == 200.0
        assert hw.priority == 5
        # Timer state untouched (refresh, not rebuild).
        assert hw.hours_since_legionella == 99.0
        assert hw._legionella_cycle_active is True

    def test_ev_priority_and_currents_pushed_per_charger(self):
        dev = _Dev(priority=1, min_current=6.0, max_current=32.0,
                   phases=3, voltage=230, min_power_threshold=0.0)
        # global ev_surplus_priority + per-charger override for min/max
        cfg = {
            "ev_surplus_priority": 4,
            # ev_shed_priority is RETIRED (#576) — set here to prove it's now
            # ignored: shed order follows the ONE list position instead.
            "ev_chargers": [{"id": "wb", "ev_min_current": 10,
                             "max_charging_current": 16, "ev_shed_priority": 8}],
        }
        lm = SimpleNamespace(_devices={"load_device_wb": {"priority": 1}})
        coord = _coord(cfg, ev_devices={"wb": dev}, load_manager=lm)
        SEMCoordinator.refresh_runtime_config(coord)
        assert dev.priority == 4          # global surplus priority
        assert dev.min_current == 10.0    # per-charger override
        assert dev.max_current == 16.0
        # #576 — shed priority = the list position (dev.priority), NOT the
        # retired ev_shed_priority=8. Latest-to-charge (highest list number)
        # sheds first under the load manager's "higher number sheds first".
        assert lm._devices["load_device_wb"]["priority"] == 4

    def test_min_power_threshold_re_derived(self):
        # HIGH (review): the surplus-activation gate must follow min_current,
        # else a min-current change applies to commanded current but not to
        # whether the charger turns on.
        dev = _Dev(priority=3, min_current=6.0, max_current=32.0,
                   phases=3, voltage=230, min_power_threshold=6 * 3 * 230)
        cfg = {"ev_chargers": [{"id": "wb", "ev_min_current": 10}]}
        coord = _coord(cfg, ev_devices={"wb": dev})
        SEMCoordinator.refresh_runtime_config(coord)
        assert dev.min_current == 10.0
        assert dev.min_power_threshold == 10 * 3 * 230  # 6900, re-derived

    def test_ev_load_priority_alias(self):
        # LOW (review): legacy ev_load_priority alias is the fallback, as at
        # construction (__init__._cfg).
        dev = _Dev(priority=3, min_current=6.0, max_current=32.0,
                   phases=3, voltage=230, min_power_threshold=0.0)
        cfg = {"ev_chargers": [{"id": "wb", "ev_load_priority": 7}]}
        coord = _coord(cfg, ev_devices={"wb": dev})
        SEMCoordinator.refresh_runtime_config(coord)
        assert dev.priority == 7

    def test_static_tariff_rates_pushed(self):
        tp = StaticTariffProvider(peak_rate=0.1, off_peak_rate=0.1, export_rate=0.01)
        coord = _coord({
            "electricity_import_rate": 0.42, "electricity_export_rate": 0.09,
        }, tariff=tp)
        SEMCoordinator.refresh_runtime_config(coord)
        assert tp.peak_rate == 0.42
        assert tp.export_rate == 0.09

    def test_dynamic_tariff_thresholds_pushed(self):
        tp = DynamicTariffProvider(None, cheap_threshold=0.0, expensive_threshold=0.0,
                                   export_rate=0.0, fallback_price=0.0)
        coord = _coord({
            "cheap_price_threshold": 0.12, "expensive_price_threshold": 0.40,
            "electricity_export_rate": 0.08, "electricity_import_rate": 0.31,
        }, tariff=tp)
        SEMCoordinator.refresh_runtime_config(coord)
        assert tp.cheap_threshold == 0.12
        assert tp.expensive_threshold == 0.40
        assert tp.export_rate == 0.08
        assert tp.fallback_price == 0.31

    def test_calendar_tariff_rates_pushed(self):
        tp = CalendarTariffProvider(None, peak_rate=0.1, off_peak_rate=0.1,
                                    export_rate=0.01)
        coord = _coord({
            "electricity_import_rate": 0.38,
            "electricity_off_peak_rate": 0.22,
            "electricity_export_rate": 0.07,
        }, tariff=tp)
        SEMCoordinator.refresh_runtime_config(coord)
        assert tp.peak_rate == 0.38
        assert tp.off_peak_rate == 0.22
        assert tp.export_rate == 0.07

    def test_calendar_rate_unchanged_when_key_absent(self):
        # MEDIUM (review): an absent import-rate key must leave the provider's
        # current value alone (calendar default 0.35 ≠ static default 0.3387).
        tp = CalendarTariffProvider(None, peak_rate=0.35, off_peak_rate=0.30,
                                    export_rate=0.01)
        coord = _coord({"electricity_export_rate": 0.05}, tariff=tp)  # no rate keys
        SEMCoordinator.refresh_runtime_config(coord)
        assert tp.peak_rate == 0.35       # unchanged, NOT nudged to 0.3387
        assert tp.off_peak_rate == 0.30   # unchanged
        assert tp.export_rate == 0.05     # the one key present applied

    def test_no_controllers_is_safe(self):
        # All handles None / absent → must not raise.
        coord = _coord({}, surplus=None, ev_devices=None, tariff=None)
        SEMCoordinator.refresh_runtime_config(coord)  # no exception
