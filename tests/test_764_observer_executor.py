"""#764 follow-up — observer mode cuts at the WRITE, not at the decision.

Loads got this right first: management (layer 1) and decision (layer 2) run
live against the real sensors, and the seam in the ACTUATOR logs the command
it WOULD send (``_reconcile_load_observe``). EV and battery did not. The
coordinator skipped the whole block — ``if self._ev_devices and not
self._observer_mode:`` and ``if not self._observer_mode: await
self._run_battery_pipeline(...)`` — so under observer no adapter was built,
``decide()`` / ``decide_battery()`` never ran, and there was nothing to
observe. Live proof on .175 (16.08.2026): two healthy batteries, diagnostics
``adapters = {}`` and ``last_decisions = {}``. ``docs/SIMULATION.md``'s
promise ("you never need observer mode off to test decisions") held for
loads only, and the executor half of #638 had never been simulated at all.

One cut for every family: the actuator branches once, mutates nothing, and
publishes the WOULD decision on the standard #764 surface — the
``would_decisions`` map on the observer switch and the
``solar_energy_management_observer_decision`` bus event.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
    commanded_power_w,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.utils.log_gate import reset_log_gate


@pytest.fixture(autouse=True)
def _gate():
    reset_log_gate()
    yield
    reset_log_gate()


def _sc():
    sc = SurplusController(MagicMock())
    sc.hass.bus.async_fire = MagicMock()
    return sc


def _charger_adapter(phases=3, voltage=230.0, max_a=32.0):
    a = MagicMock()
    a.phases = phases
    a.voltage = voltage
    a.max_current_a = max_a
    return a


def _reconciler():
    r = MagicMock()
    r.reconcile_and_apply = AsyncMock()
    return r


def _cdec(intent=ChargerIntent.CHARGE_AT_AMPS, amps=10,
          reason="night floor — deadline 06:00", mode="min_plus_solar"):
    return ChargerDecision(
        charger_id="keba_x", mode=mode, intent=intent,
        commanded_amps=amps, reason=reason,
    )


def _cpower(w=0.0):
    return ChargerPower(charger_id="keba_x", power_w=w,
                        connected=True, charging=w > 0)


# ─────────────────────── the charger seam ───────────────────────


class TestTheChargerSeamCuts:

    async def test_observer_never_reaches_the_reconciler(self):
        """The reconciler is the only thing that touches the box."""
        rec = _reconciler()
        await actuate(_cdec(), _charger_adapter(), _cpower(), rec,
                      observer=True, controller=_sc())
        rec.reconcile_and_apply.assert_not_called()

    async def test_live_still_reconciles(self):
        rec = _reconciler()
        await actuate(_cdec(), _charger_adapter(), _cpower(), rec,
                      observer=False, controller=_sc())
        rec.reconcile_and_apply.assert_awaited_once()

    async def test_the_default_is_live(self):
        """Every pre-#764 call site keeps actuating — no silent mute."""
        rec = _reconciler()
        await actuate(_cdec(), _charger_adapter(), _cpower(), rec)
        rec.reconcile_and_apply.assert_awaited_once()

    async def test_the_would_command_lands_on_the_standard_surface(self):
        sc = _sc()
        await actuate(_cdec(amps=10), _charger_adapter(), _cpower(),
                      _reconciler(), observer=True, controller=sc)
        m = sc.observer_decisions["ev:keba_x"]
        assert m["kind"] == "charger"
        assert m["action"] == "charge_at_amps"
        assert m["amps"] == 10
        assert m["power_w"] == pytest.approx(6900.0)   # 10 A × 3 × 230 V
        assert m["source"] == "min_plus_solar"
        assert "deadline" in m["reason"]

    async def test_an_idle_would_is_recorded_too(self):
        """"Do nothing" is a decision — a fresh reader must see it."""
        sc = _sc()
        await actuate(_cdec(intent=ChargerIntent.IDLE, amps=0,
                            reason="no surplus"),
                      _charger_adapter(), _cpower(), _reconciler(),
                      observer=True, controller=sc)
        m = sc.observer_decisions["ev:keba_x"]
        assert m["action"] == "idle"
        assert m["power_w"] == 0.0

    async def test_the_event_fires_on_the_edge_only(self):
        sc = _sc()
        for _ in range(5):
            await actuate(_cdec(amps=10), _charger_adapter(), _cpower(),
                          _reconciler(), observer=True, controller=sc)
        assert sc.hass.bus.async_fire.call_count == 1
        await actuate(_cdec(intent=ChargerIntent.IDLE, amps=0,
                            reason="surplus gone"),
                      _charger_adapter(), _cpower(), _reconciler(),
                      observer=True, controller=sc)
        assert sc.hass.bus.async_fire.call_count == 2

    async def test_the_seam_survives_without_a_controller(self):
        """Bare callers (older paths, unit tests) still get the cut."""
        rec = _reconciler()
        await actuate(_cdec(), _charger_adapter(), _cpower(), rec,
                      observer=True)
        rec.reconcile_and_apply.assert_not_called()


class TestCommandedPower:
    """The watts a decision commands — the WOULD payload's number, and the
    night budget's commitment when no setpoint was ever written."""

    def test_amps_become_watts(self):
        assert commanded_power_w(
            _cdec(amps=10), phases=3, voltage=230.0, max_current_a=32.0,
        ) == pytest.approx(6900.0)

    def test_charge_max_uses_the_ceiling(self):
        assert commanded_power_w(
            _cdec(intent=ChargerIntent.CHARGE_MAX, amps=0),
            phases=3, voltage=230.0, max_current_a=16.0,
        ) == pytest.approx(11040.0)

    def test_idle_and_disable_command_nothing(self):
        for intent in (ChargerIntent.IDLE, ChargerIntent.DISABLE):
            assert commanded_power_w(
                _cdec(intent=intent, amps=0),
                phases=3, voltage=230.0, max_current_a=32.0,
            ) == 0.0


# ─────────────────────── the battery seam ───────────────────────


def _bdec(intent=BatteryIntent.FORCE_CHARGE, **kw):
    return BatteryDecision(
        battery_id="b1", intent=intent,
        reason=kw.pop("reason", "cheap window 03:00 — deficit 3.0 kWh"),
        **kw,
    )


def _battery_adapter():
    a = MagicMock()
    for name in ("command_off", "command_normal", "command_limit_discharge",
                 "command_force_charge", "command_stop_force_charge",
                 "command_force_discharge", "async_recover_pending"):
        setattr(a, name, AsyncMock())
    return a


class TestTheBatterySeamCuts:

    async def test_observer_never_calls_the_adapter(self):
        ad = _battery_adapter()
        await actuate_battery(_bdec(charge_power_w=3000.0, target_soc=80.0),
                              ad, observer=True, controller=_sc())
        ad.command_force_charge.assert_not_called()

    async def test_live_still_dispatches(self):
        ad = _battery_adapter()
        await actuate_battery(_bdec(intent=BatteryIntent.NORMAL), ad,
                              observer=False, controller=_sc())
        ad.command_normal.assert_awaited_once()

    async def test_the_default_is_live(self):
        ad = _battery_adapter()
        await actuate_battery(_bdec(intent=BatteryIntent.NORMAL), ad)
        ad.command_normal.assert_awaited_once()

    async def test_the_would_decision_lands_on_the_standard_surface(self):
        sc = _sc()
        await actuate_battery(_bdec(charge_power_w=3000.0, target_soc=80.0),
                              _battery_adapter(), observer=True, controller=sc)
        m = sc.observer_decisions["battery:b1"]
        assert m["kind"] == "battery"
        assert m["action"] == "force_charge"
        assert m["power_w"] == pytest.approx(3000.0)
        assert "deficit" in m["reason"]

    async def test_a_discharge_carries_its_own_watts(self):
        sc = _sc()
        await actuate_battery(
            _bdec(intent=BatteryIntent.FORCE_DISCHARGE,
                  discharge_power_w=2500.0, reason="sell block 18:00"),
            _battery_adapter(), observer=True, controller=sc)
        m = sc.observer_decisions["battery:b1"]
        assert m["action"] == "force_discharge"
        assert m["power_w"] == pytest.approx(2500.0)

    async def test_a_limit_carries_the_limit(self):
        sc = _sc()
        await actuate_battery(
            _bdec(intent=BatteryIntent.LIMIT_DISCHARGE,
                  discharge_limit_w=800.0, reason="EV night protection"),
            _battery_adapter(), observer=True, controller=sc)
        assert sc.observer_decisions["battery:b1"]["power_w"] == 800.0

    async def test_the_event_fires_on_the_edge_only(self):
        sc = _sc()
        for w in (3000.0, 3004.0, 2996.0):
            await actuate_battery(_bdec(charge_power_w=w), _battery_adapter(),
                                  observer=True, controller=sc)
        assert sc.hass.bus.async_fire.call_count == 1


# ─────────── the pipeline runs for real under observer ───────────


class TestTheBatteryPipelineRunsUnderObserver:
    """The whole point: decisions happen, writes do not."""

    def _coord(self, *, observer: bool):
        coord = SEMCoordinator(MagicMock(), {
            "battery_capacity_kwh": 15.0,
            "battery_buffer_soc": 20,
        })
        hass = MagicMock()
        hass.services = SimpleNamespace(async_call=AsyncMock(return_value=None))
        coord.hass = hass
        coord.config_entry = SimpleNamespace(entry_id="entry-764")
        coord._observer_mode = observer
        coord._surplus_controller = _sc()
        coord._battery_charge_scheduler._config.enabled = False
        coord.time_manager = SimpleNamespace(is_night_mode=lambda: False)
        return coord

    def _power(self):
        return SimpleNamespace(
            batteries={},
            battery_soc=50.0,
            battery_power=-200.0,
            solar_power=500.0,
            home_consumption_power=300.0,
            ev_charging=False,
            ev_connected=False,
            battery_soc_unavailable=False,
        )

    async def _run(self, coord, adapter):
        with patch(
            "custom_components.solar_energy_management.coordinator."
            "battery_adapters.adapter_for", return_value=adapter,
        ):
            await coord._run_battery_pipeline(
                self._power(), SimpleNamespace(), "idle")

    async def test_the_decision_is_made_and_recorded(self):
        coord = self._coord(observer=True)
        await self._run(coord, _battery_adapter())
        assert "primary" in coord._last_battery_decisions
        assert coord._last_battery_decisions["primary"]["intent"]

    async def test_nothing_is_commanded(self):
        coord = self._coord(observer=True)
        ad = _battery_adapter()
        await self._run(coord, ad)
        for name in ("command_off", "command_normal", "command_limit_discharge",
                     "command_force_charge", "command_stop_force_charge",
                     "command_force_discharge"):
            getattr(ad, name).assert_not_called()

    async def test_startup_recovery_is_not_a_shadow_write(self):
        """#532 orphan-stop recovery writes to the inverter — under
        observer it must not run, even though the adapter is built."""
        coord = self._coord(observer=True)
        ad = _battery_adapter()
        await self._run(coord, ad)
        ad.async_recover_pending.assert_not_called()

    async def test_live_still_recovers_and_commands(self):
        coord = self._coord(observer=False)
        ad = _battery_adapter()
        await self._run(coord, ad)
        ad.async_recover_pending.assert_awaited_once()
        assert any(
            getattr(ad, n).await_count for n in
            ("command_off", "command_normal", "command_limit_discharge",
             "command_force_charge", "command_stop_force_charge",
             "command_force_discharge")
        )

    async def test_the_would_decision_reaches_the_surface(self):
        coord = self._coord(observer=True)
        await self._run(coord, _battery_adapter())
        assert "battery:primary" in coord._surplus_controller.observer_decisions


# ─────────────────────── the wiring pins ───────────────────────


_COORD_DIR = Path(
    inspect.getsourcefile(SEMCoordinator)  # type: ignore[arg-type]
).parent


class TestTheGateMoved:

    def test_the_multi_charger_loop_is_not_gated_on_observer(self):
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert "if self._ev_devices and not self._observer_mode:" not in src
        assert "if self._ev_devices:" in src

    def test_the_legacy_charger_branch_is_not_gated_on_observer(self):
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert "elif self._ev_device and not self._observer_mode:" not in src
        assert "elif self._ev_device:" in src

    def test_the_battery_pipeline_is_not_gated_on_observer(self):
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert not re.search(
            r"if not self\._observer_mode:\s*\n\s*try:\s*\n\s*"
            r"await self\._run_battery_pipeline",
            src,
        )
        assert "await self._run_battery_pipeline(" in src

    def test_setpoints_are_still_zeroed_under_observer(self):
        """#536 — a stale ``commanded_current`` drove HA-TEST's real KEBA
        through an external bridge automation. Observing must publish
        "not commanding", and that is independent of the seam."""
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert re.search(
            r"if self\._observer_mode:\s*\n\s*self\._zero_charger_setpoints\(\)",
            src,
        )

    def test_startup_recovery_is_observer_guarded(self):
        src = inspect.getsource(SEMCoordinator._run_battery_pipeline)
        assert re.search(
            r"if not self\._observer_mode:\s*\n\s*recovered = "
            r"await adapter\.async_recover_pending\(\)",
            src,
        )

    def test_the_night_commitment_survives_the_shadow(self):
        """Nothing writes a setpoint under observer (they are zeroed), so
        the fleet's night budget must read the commitment off the decision
        — otherwise every lower-priority charger sees phantom headroom and
        a two-charger simulation is fiction."""
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert "commanded_power_w(" in src


class TestNoCallSiteCanForget:
    """The seam only holds if every caller passes the flag. Same shape as
    ``tests/test_ev_control_fleet_reads.py``: an AST lint, not a habit."""

    def _calls(self, func_name: str):
        found = []
        for path in sorted(_COORD_DIR.glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == func_name):
                    found.append((path.name, node.lineno,
                                  {k.arg for k in node.keywords}))
        return found

    def test_every_actuate_call_passes_observer(self):
        calls = self._calls("actuate")
        assert calls, "no actuate() call sites found — the lint is blind"
        missing = [(f, ln) for f, ln, kw in calls if "observer" not in kw]
        assert not missing, f"actuate() without observer=: {missing}"

    def test_every_actuate_battery_call_passes_observer(self):
        calls = self._calls("actuate_battery")
        assert calls, "no actuate_battery() call sites found"
        missing = [(f, ln) for f, ln, kw in calls if "observer" not in kw]
        assert not missing, f"actuate_battery() without observer=: {missing}"
