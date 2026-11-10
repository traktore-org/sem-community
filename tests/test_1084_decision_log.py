"""#1084 — the decision log: when a device's command changes, say why.

Recording only. The three actuator seams (``actuate`` for chargers,
``actuate_battery`` for batteries, the ``_activate_owned`` /
``_deactivate_owned`` / ``_adjust_owned`` choke points for loads) hand the
log the command they send — or under observer mode WOULD send — and the log
writes a row only when that command changed: a start, a stop, a mode
change, a current step of at least 1 A, a setpoint move that matters.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.actuate import actuate
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
    ChargerDecision,
    ChargerIntent,
    ChargerPower,
)
from custom_components.solar_energy_management.coordinator import (
    surplus_controller as sc_mod,
)
from custom_components.solar_energy_management.coordinator.decision_log import (
    DECISION_LOG_SIZE,
    EVENT_DECISION,
    KIND_BATTERY,
    KIND_CHARGER,
    KIND_LOAD,
    DecisionLog,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    LoadIntent,
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import (
    ControllableDevice,
    DeviceControlMode,
)
from custom_components.solar_energy_management.logbook import (
    async_describe_events,
    describe_decision,
)
from custom_components.solar_energy_management.sensor import _decision_attributes
from custom_components.solar_energy_management.utils.log_gate import reset_log_gate

T0 = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
CHARGER = "keba_x"


@pytest.fixture(autouse=True)
def _gate():
    reset_log_gate()
    yield
    reset_log_gate()


def _log():
    hass = MagicMock()
    hass.bus.async_fire = MagicMock()
    return DecisionLog(hass)


def _sc():
    sc = SurplusController(MagicMock())
    sc.hass.bus.async_fire = MagicMock()
    return sc


def _decision_events(bus_fire):
    return [c for c in bus_fire.call_args_list if c.args[0] == EVENT_DECISION]


def _rec(log, verb, value=None, kind=KIND_CHARGER, observer=False, did=CHARGER):
    return log.record(device_id=did, kind=kind, verb=verb, value=value,
                      reason_code="test", text="why", observer=observer, now=T0)


# ─────────────────────── the log itself ───────────────────────


class TestOnlyChangesAreRecorded:

    def test_the_same_command_twice_is_one_row(self):
        log = _log()
        assert _rec(log, "charge", 8) is not None
        assert _rec(log, "charge", 8) is None
        assert len(log) == 1

    def test_a_one_amp_step_is_a_change(self):
        log = _log()
        _rec(log, "charge", 8)
        rec = _rec(log, "charge", 9)
        assert rec is not None
        assert (rec.old, rec.new) == ("charge 8 A", "charge 9 A")

    def test_less_than_one_amp_is_not(self):
        log = _log()
        _rec(log, "charge", 8)
        assert _rec(log, "charge", 8.4) is None

    def test_start_stop_and_mode_change_each_record(self):
        log = _log()
        _rec(log, "charge", 8)
        _rec(log, "idle")
        _rec(log, "charge_max")
        _rec(log, "disable")
        assert [r["new"] for r in log.records()] == [
            "charge 8 A", "idle", "charge_max", "disable"]

    def test_a_first_resting_command_is_not_news(self):
        """Every charger is idle after a boot; that is no change."""
        log = _log()
        assert _rec(log, "idle") is None
        assert len(log) == 0
        assert _rec(log, "charge", 6).old == "idle"

    def test_battery_setpoint_wobble_below_a_step_is_quiet(self):
        log = _log()
        _rec(log, "limit_discharge", 1500, kind=KIND_BATTERY, did="b1")
        assert _rec(log, "limit_discharge", 1600, kind=KIND_BATTERY, did="b1") is None
        assert _rec(log, "limit_discharge", 1750, kind=KIND_BATTERY, did="b1") is not None

    def test_load_setpoint_wobble_is_quiet(self):
        log = _log()
        _rec(log, "on", 1200, kind=KIND_LOAD, did="heater")
        assert _rec(log, "on", 1500, kind=KIND_LOAD, did="heater") is None
        assert _rec(log, "on", 1800, kind=KIND_LOAD, did="heater") is not None

    def test_kinds_do_not_share_a_last_command(self):
        log = _log()
        _rec(log, "on", kind=KIND_LOAD, did="b1")
        assert _rec(log, "force_charge", 3000, kind=KIND_BATTERY, did="b1") is not None


class TestTheRecord:

    def test_ring_holds_200(self):
        log = _log()
        for i in range(DECISION_LOG_SIZE + 50):
            _rec(log, "charge", 6 + (i % 2))
        assert len(log) == DECISION_LOG_SIZE
        assert len(log.records()) == DECISION_LOG_SIZE

    def test_observer_flag_rides_the_record(self):
        log = _log()
        rec = _rec(log, "charge", 10, observer=True)
        assert rec.observer is True
        assert log.records()[-1]["observer"] is True

    def test_leaving_observer_mode_is_a_change(self):
        """The first real send after observing is news even when it is the
        command the observer already named."""
        log = _log()
        _rec(log, "charge", 10, observer=True)
        assert _rec(log, "charge", 10, observer=False) is not None

    def test_inputs_are_merged_cleaned_and_never_crash(self):
        log = _log()
        log.set_inputs({"import_price": 0.31234567, "export_rate": None,
                        "price_level": "cheap", "soc": 54.26, "junk": object()})
        rec = log.record(device_id=CHARGER, kind=KIND_CHARGER, verb="charge",
                         value=8, inputs={"surplus_w": 4321.04}, now=T0)
        assert rec.inputs == {"import_price": 0.3123, "price_level": "cheap",
                              "soc": 54.3, "surplus_w": 4321.0}
        log.set_inputs(None)
        assert log.record(device_id=CHARGER, kind=KIND_CHARGER, verb="idle",
                          now=T0).inputs == {}

    def test_bad_values_never_raise(self):
        log = _log()
        assert log.record(device_id=CHARGER, kind=KIND_CHARGER, verb="charge",
                          value="not a number", now=T0) is None

    def test_the_event_fires_with_the_record(self):
        log = _log()
        _rec(log, "charge", 8)
        _rec(log, "charge", 8)
        fired = _decision_events(log.hass.bus.async_fire)
        assert len(fired) == 1
        data = fired[0].args[1]
        assert data["new"] == "charge 8 A"
        assert data["time"] == T0.isoformat()
        json.dumps(data)

    def test_no_hass_no_event_no_crash(self):
        log = DecisionLog(None)
        assert _rec(log, "charge", 8) is not None

    def test_long_text_is_cut(self):
        log = _log()
        rec = log.record(device_id=CHARGER, kind=KIND_CHARGER, verb="charge",
                         value=8, text="x" * 500, now=T0)
        assert len(rec.text) == 120


# ─────────────────────── the charger seam ───────────────────────


def _cdec(intent=ChargerIntent.CHARGE_AT_AMPS, amps=10, mode="solar_only",
          reason="surplus 4200 W"):
    return ChargerDecision(charger_id=CHARGER, mode=mode, intent=intent,
                           commanded_amps=amps, reason=reason)


def _adapter():
    """A charger whose writes land: ``command_current`` moves the setpoint
    the reconciler reads back, as the real device does."""
    dev = MagicMock()
    dev._current_setpoint = 0
    dev.observer_mode = False
    dev.contactor_surface = False
    dev.can_stop_charging = MagicMock(return_value=True)
    a = MagicMock()
    a._device = dev
    a.phases, a.voltage, a.max_current_a = 3, 230.0, 32
    a.actual_charging = MagicMock(return_value=True)
    a.is_self_charging = MagicMock(return_value=False)
    a.enable_state = MagicMock(return_value=(None, True))

    async def _write(amps):
        dev._current_setpoint = amps
    a.command_current = AsyncMock(side_effect=_write)
    for m in ("command_disable", "command_park_off", "arm_failsafe",
              "ensure_enabled"):
        setattr(a, m, AsyncMock())
    return a


_POWER = ChargerPower(charger_id=CHARGER, power_w=6900.0, connected=True,
                      charging=True)


def _real_reconciler():
    from custom_components.solar_energy_management.coordinator.charger_reconciler import (
        ChargerReconciler,
    )
    return ChargerReconciler(charger_id=CHARGER, heartbeat_s=3600.0)


def _mock_reconciler():
    r = MagicMock()
    r.reconcile_and_apply = AsyncMock()
    return r


class TestTheChargerSeam:
    """The row is written where the write leaves — the reconciler's apply
    loop — so a write it holds back makes none."""

    async def test_a_sent_change_records_once(self):
        sc, ad, rec = _sc(), _adapter(), _real_reconciler()
        for _ in range(3):
            await actuate(_cdec(amps=10), ad, _POWER, rec, controller=sc)
        await actuate(_cdec(amps=11), ad, _POWER, rec, controller=sc)
        rows = sc.decision_log.records()
        assert [r["new"] for r in rows] == ["charge 10 A", "charge 11 A"]
        assert rows[0]["reason_code"] == "solar_only_charge_at_amps"
        assert rows[0]["text"] == "surplus 4200 W"
        assert rows[0]["observer"] is False
        assert [c.args[0] for c in ad.command_current.await_args_list][-1] == 11

    async def test_a_held_back_write_records_nothing(self):
        """The idle grace holds the setpoint through a solar flicker: SEM
        decided IDLE, nothing left for the box, so nothing is logged."""
        sc, ad, rec = _sc(), _adapter(), _real_reconciler()
        await actuate(_cdec(amps=10), ad, _POWER, rec, controller=sc)
        writes = ad.command_current.await_count
        await actuate(_cdec(intent=ChargerIntent.IDLE, amps=0,
                            reason="no surplus"), ad, _POWER, rec, controller=sc)
        assert ad.command_current.await_count == writes   # held, not sent
        ad.command_disable.assert_not_awaited()
        assert [r["new"] for r in sc.decision_log.records()] == ["charge 10 A"]

    async def test_a_bad_value_in_the_log_never_stops_the_write(self):
        """(#1084 review) The log is recording only: a value it cannot
        read must not raise into the write it describes."""
        from custom_components.solar_energy_management.coordinator.charger_reconciler import (
            Action, ActionKind,
        )
        sc, ad, rec = _sc(), _adapter(), _real_reconciler()
        rec.decision_log = sc.decision_log
        rec._log_write(Action(ActionKind.WRITE_CURRENT, float("nan")), ad,
                       _cdec(amps=10))
        assert len(sc.decision_log) == 0

    async def test_a_decision_alone_records_nothing(self):
        """A reconciler that sends nothing (here: a mock) leaves no row."""
        sc = _sc()
        await actuate(_cdec(amps=10), _adapter(), _POWER, _mock_reconciler(),
                      controller=sc)
        assert len(sc.decision_log) == 0

    async def test_observer_records_the_would_write(self):
        sc, ad, rec = _sc(), _adapter(), _real_reconciler()
        await actuate(_cdec(amps=10), ad, _POWER, rec, observer=True,
                      controller=sc)
        rows = sc.decision_log.records()
        assert len(rows) == 1
        assert rows[0]["new"] == "charge 10 A" and rows[0]["observer"] is True

    async def test_bare_caller_without_a_controller_still_works(self):
        rec = _mock_reconciler()
        await actuate(_cdec(), _adapter(), _POWER, rec)
        rec.reconcile_and_apply.assert_awaited_once()


# ─────────────────────── the battery seam ───────────────────────


def _battery_adapter():
    a = MagicMock()
    a.supports_forced_charge = True
    a.supports_forced_discharge = True
    a.last_intent = None
    a.last_discharge_limit_w = -1.0
    a._capped_charge_w = None
    a._room_stopped = False
    for m in ("command_off", "command_normal", "command_limit_discharge",
              "command_force_charge", "command_stop_force_charge",
              "command_force_discharge", "command_stop_force_discharge"):
        setattr(a, m, AsyncMock(return_value=True))
    return a


def _bdec(intent, **kw):
    return BatteryDecision(battery_id="b1", intent=intent, reason="cheap night", **kw)


class TestTheBatterySeam:

    async def test_one_row_per_change(self):
        sc = _sc()
        ad = _battery_adapter()
        fc = _bdec(BatteryIntent.FORCE_CHARGE, target_soc=80.0,
                   charge_power_w=3000.0, duration_min=60)
        for _ in range(3):
            await actuate_battery(fc, ad, controller=sc)
        await actuate_battery(_bdec(BatteryIntent.STOP_FORCE_CHARGE), ad,
                              controller=sc)
        rows = sc.decision_log.records()
        assert [r["new"] for r in rows] == [
            "force_charge 3000 W", "stop_force_charge"]
        assert rows[0]["inputs"]["target_soc"] == 80.0
        assert ad.command_force_charge.await_count == 3   # behaviour untouched

    async def test_a_held_blind_cycle_records_nothing(self):
        """The #818 hold sends nothing, so nothing changed."""
        sc = _sc()
        ad = _battery_adapter()
        ad.last_intent = BatteryIntent.NORMAL
        await actuate_battery(
            _bdec(BatteryIntent.LIMIT_DISCHARGE, discharge_limit_w=900.0), ad,
            controller=sc, inputs_degraded=True)
        assert len(sc.decision_log) == 0
        ad.command_limit_discharge.assert_not_awaited()

    async def test_observer_records_flagged(self):
        sc = _sc()
        ad = _battery_adapter()
        await actuate_battery(
            _bdec(BatteryIntent.LIMIT_DISCHARGE, discharge_limit_w=900.0), ad,
            observer=True, controller=sc)
        rows = sc.decision_log.records()
        assert rows[0]["new"] == "limit_discharge 1000 W"
        assert rows[0]["observer"] is True
        ad.command_limit_discharge.assert_not_awaited()


# ─────────────────────── the load seam ───────────────────────


class _FakeLoad:
    def __init__(self):
        self.device_id = "towel"
        self.name = "Towel heater"
        self.priority = 5
        self.rated_power = 600.0
        self.control_mode = DeviceControlMode.SURPLUS
        self._active = False
        self._sem_owned = False
        self._sem_commanded = False
        self._observed_off_since = None
        self._last_activated = None
        self._last_deactivated = None

    @property
    def is_active(self):
        return self._active

    def get_current_consumption(self):
        return self.rated_power if self._active else 0.0

    async def activate(self, watts):
        self._active = True
        return self.rated_power

    async def deactivate(self):
        self._active = False

    async def adjust_power(self, watts):
        return self.get_current_consumption()

    record_activated = ControllableDevice.record_activated
    record_deactivated = ControllableDevice.record_deactivated


class TestTheLoadSeam:

    async def test_start_and_stop_record_once_each(self):
        sc = _sc()
        dev = _FakeLoad()
        dev._controller = sc      # what register_device sets
        await sc_mod._activate_owned(dev, 600.0, reason_code="surplus",
                                     text="enough sun to start")
        await sc_mod._adjust_owned(dev, 650.0)          # a switch: no change
        await sc_mod._deactivate_owned(dev, reason_code="surplus_short",
                                       text="not enough sun")
        rows = sc.decision_log.records()
        assert [(r["old"], r["new"], r["reason_code"]) for r in rows] == [
            (None, "on", "surplus"), ("on", "off", "surplus_short")]
        assert rows[0]["name"] == "Towel heater"

    async def test_an_unregistered_device_is_not_a_crash(self):
        dev = _FakeLoad()
        assert await sc_mod._activate_owned(dev, 600.0) == 600.0

    async def test_observer_load_records_flagged_and_hold_is_quiet(self):
        sc = _sc()
        dev = MagicMock()
        dev.device_id, dev.name = "heizband", "Heizband"
        dev.get_current_consumption = MagicMock(return_value=0.0)
        idle = LoadIntent(False, 0.0, None, "no source")
        sc_mod._reconcile_load_observe(dev, idle, False, controller=sc)
        assert len(sc.decision_log) == 0
        on = LoadIntent(True, 800.0, "solar", "surplus 900 W")
        sc_mod._reconcile_load_observe(dev, on, False, controller=sc)
        sc_mod._reconcile_load_observe(dev, on, False, controller=sc)
        rows = sc.decision_log.records()
        assert len(rows) == 1
        assert rows[0]["observer"] is True and rows[0]["reason_code"] == "solar"


# ─────────────────────── the surfaces ───────────────────────


class TestLogbook:

    def test_line_reads_old_to_new_with_the_reason(self):
        out = describe_decision({"name": "Towel heater", "old": "off",
                                 "new": "on", "text": "enough sun to start"})
        assert out == {"name": "Towel heater",
                       "message": "off → on — enough sun to start"}

    def test_observer_and_first_command(self):
        out = describe_decision({"device_id": CHARGER, "old": None,
                                 "new": "charge 8 A", "observer": True})
        assert out["name"] == CHARGER
        assert out["message"] == "none → charge 8 A (observer: not sent)"

    def test_registers_the_decision_event(self):
        seen = {}

        def _register(domain, event, fn):
            seen[(domain, event)] = fn

        async_describe_events(MagicMock(), _register)
        fn = seen[("solar_energy_management", EVENT_DECISION)]
        out = fn(SimpleNamespace(data={"name": "x", "old": "a", "new": "b"}))
        assert out["message"] == "a → b"


class TestDiagnostics:

    async def test_the_download_carries_the_ring(self, tmp_path):
        from custom_components.solar_energy_management.diagnostics import (
            async_get_config_entry_diagnostics,
        )
        hass = MagicMock()
        hass.config.config_dir = str(tmp_path)

        async def _executor(func, *a, **kw):
            return func(*a, **kw)
        hass.async_add_executor_job = _executor
        entry = MagicMock()
        entry.entry_id, entry.version = "e1084", 1
        entry.data, entry.options = {}, {}
        coord = MagicMock()
        coord.last_update_success = True
        coord.update_interval = timedelta(seconds=10)
        coord._observer_mode = False
        coord._load_manager = None
        coord._energy_dashboard_config = None
        coord.data = {}
        coord.decision_log = _log()
        _rec(coord.decision_log, "charge", 8)
        entry.runtime_data = coord
        hass.data = {"solar_energy_management": {entry.entry_id: coord}}
        out = await async_get_config_entry_diagnostics(hass, entry)
        assert [r["new"] for r in out["decision_log"]] == ["charge 8 A"]
        json.dumps(out["decision_log"])

    async def test_no_log_is_an_empty_list(self, tmp_path):
        from custom_components.solar_energy_management.diagnostics import (
            _decision_log_records,
        )
        assert _decision_log_records(MagicMock()) == []


class TestSensorAttributes:

    def _coord(self):
        log = _log()
        _rec(log, "charge", 8)
        _rec(log, "force_charge", 3000, kind=KIND_BATTERY, did="b1")
        _rec(log, "on", kind=KIND_LOAD, did="towel")
        return SimpleNamespace(
            decision_log=log,
            data={f"charger_{CHARGER}_strategy": "surplus 4200 W",
                  f"charger_{CHARGER}_charging_state": "solar_charging_active"})

    def test_charging_state_carries_per_charger_decision_and_strategy(self):
        attrs = _decision_attributes(self._coord(), "charging_state")
        assert attrs["per_charger_last_decision"][CHARGER]["new"] == "charge 8 A"
        assert attrs["per_charger_strategy"] == {CHARGER: "surplus 4200 W"}

    def test_battery_and_load_sensors(self):
        c = self._coord()
        assert _decision_attributes(c, "battery_b1_status")[
            "last_decision"]["new"] == "force_charge 3000 W"
        assert "b1" in _decision_attributes(c, "battery_status")[
            "per_battery_last_decision"]
        assert "towel" in _decision_attributes(c, "load_management_status")[
            "per_device_last_decision"]

    def test_other_sensors_get_nothing(self):
        c = self._coord()
        assert _decision_attributes(c, "battery_priority_status") == {}
        assert _decision_attributes(c, "solar_power") == {}
        assert _decision_attributes(SimpleNamespace(), "charging_state") == {}

    def test_one_record_stays_small(self):
        """The recorder caps a state's attributes at 16 KB; one record with
        a full input set stays well under a kilobyte."""
        log = _log()
        log.set_inputs({"import_price": 0.31, "export_rate": 0.08,
                        "price_level": "expensive", "soc": 54.0,
                        "surplus_w": 4200.0, "target_kwh": 12.5})
        log.record(device_id=CHARGER, kind=KIND_CHARGER, verb="charge",
                   value=16, text="y" * 500, now=T0)
        assert len(json.dumps(log.last(KIND_CHARGER, CHARGER))) < 1000


# ─────────────────── the two load paths beside the walk ───────────────────


class TestVacationStop:
    """The vacation stop goes through the logged stop choke point
    (#1335: layer 1 decides it, ``reconcile_load`` makes it)."""

    async def test_vacation_stop_records_once(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        class _Coord:
            _compute_vacation_active = SEMCoordinator._compute_vacation_active
            _apply_vacation_mode = SEMCoordinator._apply_vacation_mode

            def _sync_vacation_mode_from_switch(self):
                pass

        sc = _sc()
        hp = _FakeLoad()
        hp.device_id, hp.name = "heat_pump", "Heat pump"
        hp._active = True
        hp._controller = sc
        hp.can_deactivate = lambda: True
        hp.reset_surplus_timer = lambda: None
        c = _Coord()
        c.config, c._observer_mode = {}, False
        c._vacation_switch_on, c._vacation_active = True, False
        c._surplus_controller = SimpleNamespace(_devices={"heat_pump": hp})
        await c._apply_vacation_mode()
        assert hp.is_active                     # (#1335) the flag only…
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            compute_load_intent, reconcile_load,
        )
        intent = compute_load_intent(hp, remaining_surplus_w=5000.0)
        await reconcile_load(hp, intent)        # …layer 1 stops it, layer 3 logs
        await c._apply_vacation_mode()
        await reconcile_load(hp, compute_load_intent(hp, remaining_surplus_w=5000.0))
        assert not hp.is_active
        rows = sc.decision_log.records()
        assert [(r["device_id"], r["new"], r["reason_code"]) for r in rows] == [
            ("heat_pump", "off", "vacation")]


def _load_manager(mock_hass):
    from unittest.mock import patch

    from custom_components.solar_energy_management.load_management import (
        LoadManagementCoordinator,
    )
    entry = MagicMock()
    entry.options = {"load_management_enabled": True, "target_peak_limit": 5.0}
    entry.entry_id = "e1084"
    with patch(
        "custom_components.solar_energy_management.features.load_management.LoadDeviceDiscovery"
    ), patch(
        "custom_components.solar_energy_management.features.load_management.Store"
    ) as MockStore:
        MockStore.return_value = MagicMock(
            async_load=AsyncMock(return_value=None), async_save=AsyncMock())
        lm = LoadManagementCoordinator(mock_hass, entry)
    lm._observer_mode = False
    lm.hass.services.async_call = AsyncMock()
    lm.hass.states.get = MagicMock(return_value=SimpleNamespace(
        state="on", attributes={}))
    lm._devices["boiler"] = {
        "friendly_name": "Boiler", "power_entity": "sensor.boiler_power",
        "power_rating": 2000.0, "is_available": True, "priority": 5,
        "is_critical": False, "is_controllable": True,
        "device_type": "individual_device", "control_mode": "peak_only",
        "surplus_managed": False,
        "control": {"type": "switch", "entity": "switch.boiler"},
    }
    lm.decision_log = _log()
    return lm


class TestPeakShed:

    async def test_shed_and_restore_each_record_once(self, mock_hass):
        lm = _load_manager(mock_hass)
        assert await lm._shed_device("boiler", "EMERGENCY") is True
        lm._can_restore_device = MagicMock(return_value=True)
        await lm._restore_device("boiler")
        rows = lm.decision_log.records()
        assert [(r["new"], r["reason_code"]) for r in rows] == [
            ("off", "peak_shed"), ("restore", "peak_restore")]
        assert rows[0]["name"] == "Boiler"
        assert rows[0]["observer"] is False

    async def test_a_refused_shed_records_nothing(self, mock_hass):
        lm = _load_manager(mock_hass)
        lm._can_shed_device = MagicMock(return_value=False)   # anti-flicker
        assert await lm._shed_device("boiler", "EMERGENCY") is False
        assert len(lm.decision_log) == 0

    async def test_a_phase_shed_names_the_phase(self, mock_hass):
        lm = _load_manager(mock_hass)
        assert await lm._shed_device("boiler", "PHASE") is True
        assert lm.decision_log.records()[0]["reason_code"] == "phase_shed"

    async def test_observer_records_the_withheld_shed(self, mock_hass):
        lm = _load_manager(mock_hass)
        lm._observer_mode = True
        lm._log_shed("boiler", "EMERGENCY", shed=True, observer=True)
        rows = lm.decision_log.records()
        assert rows[0]["observer"] is True and rows[0]["new"] == "off"
        lm.hass.services.async_call.assert_not_awaited()
