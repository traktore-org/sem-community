"""#818 — a cycle whose inputs went dark must not MOVE the charger.

Found on HA-PROD (21.08). The Huawei modbus integration blips 8-15 % of the
time, and ``_read_sensor`` returns 0.0 for an unavailable source, so ~50
times a day SEM computed a surplus decision from "solar 0 W, grid 0 W,
battery 0 W" — a confident lie that the sun had stopped.

The obvious fix — hold the last good value inside the reader — is the WRONG
seam, and the issue history says so:

  * #741 a stability HOLD froze 8 A below the configured 10 A floor; the
    Zoe cut out and sat stuck for 15 minutes. A hold must never preserve a
    value that violates a guarantee.
  * #758/#755 ``battery_draw`` reported ``measured=True`` off a dead sensor.
    Contract: silence is never a measurement of zero — and a held value is
    not a measurement either.
  * #774 a stale estimate outranked a live 8.7 kW draw.
  * #699 values of different vintages composed an incoherent balance.
  * The DISPLAY is already handled: ``sem-system-diagram-card.js``
    ``_readWithHold`` holds for 60 s and then shows a stale marker
    (#237/#444/#455).

So SEM does not invent a number. It declines to decide: on a degraded
cycle the existing command stands, which is already clamped, already
committed, and already the thing the car is following.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charge_stability import (
    ChargeStability,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)


class _Adapter:
    """Same shape as test_461's FakeAdapter — the filter asks it what the
    hardware is actually doing."""

    def __init__(self, last_intent=None, min_current_a=6, max_current_a=16):
        self.last_intent = last_intent
        self.min_current_a = min_current_a
        self.max_current_a = max_current_a

    def actual_charging(self, power):
        return power.power_w > 500.0


def _view(mode="solar_only", *, inputs_degraded=False, connected=True,
          power_w=4000.0, solar_w=3000.0, cid="wb"):
    return ChargerView(
        power=ChargerPower(charger_id=cid, power_w=power_w,
                           connected=connected, charging=power_w > 500),
        energy=ChargerEnergy(charger_id=cid),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=FleetContext(is_night=False, solar_w=solar_w, min_solar_w=200.0,
                           battery_soc=90.0, buffer_soc=70.0,
                           inputs_degraded=inputs_degraded),
    )


def _charge(cid="wb", amps=10):
    return ChargerDecision(
        charger_id=cid, mode="solar_only",
        intent=ChargerIntent.CHARGE_AT_AMPS,
        commanded_amps=amps, budget_w=4500.0,
        reason="solar_only: surplus ok",
    )


def _disable(cid="wb"):
    return ChargerDecision(
        charger_id=cid, mode="solar_only", intent=ChargerIntent.DISABLE,
        commanded_amps=0, budget_w=0.0, reason="user off",
    )


@pytest.mark.unit
class TestDegradedCycleHoldsTheCommand:

    def _settle(self, st, amps=10, t=0.0):
        """Get a committed command on the books the ordinary way."""
        for i in range(6):
            st.filter(_charge(amps=amps), _view(), _Adapter(),
                      min_change_interval_s=0.0, now_ts=t + i)
        return st._last_amps.get("wb")

    def test_degraded_cycle_keeps_the_committed_amps(self):
        st = ChargeStability()
        settled = self._settle(st, amps=10)
        assert settled == 10

        # Sources go dark: the surplus maths now says "no sun, drop to 6".
        out = st.filter(_charge(amps=6), _view(inputs_degraded=True, solar_w=0.0),
                        _Adapter(), min_change_interval_s=0.0, now_ts=100.0)
        assert out.commanded_amps == 10, "a dark cycle moved the charger"

    def test_the_hold_says_why(self):
        st = ChargeStability()
        self._settle(st, amps=10)
        out = st.filter(_charge(amps=6), _view(inputs_degraded=True, solar_w=0.0),
                        _Adapter(), min_change_interval_s=0.0, now_ts=100.0)
        assert "degraded" in out.reason.lower() or "unavailable" in out.reason.lower()

    def test_a_healthy_cycle_is_untouched(self):
        """Regression pin: this guard must be invisible when the sensors are
        fine. A single 6 among five 10s is smoothed away by the pre-existing
        median layer — that is the old behaviour and it must survive — so
        what is pinned here is that the #818 guard is not the one acting,
        and that a sustained change still gets through."""
        st = ChargeStability()
        self._settle(st, amps=10)

        out = st.filter(_charge(amps=6), _view(solar_w=1000.0), _Adapter(),
                        min_change_interval_s=0.0, now_ts=100.0)
        assert "degraded" not in out.reason.lower()

        for i in range(6):
            out = st.filter(_charge(amps=6), _view(solar_w=1000.0), _Adapter(),
                            min_change_interval_s=0.0, now_ts=101.0 + i)
        assert out.commanded_amps == 6, "a healthy, sustained change must land"

    def test_degraded_never_holds_below_the_floor(self):
        """#741's lesson, pinned against the new code: whatever is held, the
        configured minimum still wins."""
        st = ChargeStability()
        self._settle(st, amps=10)
        st._last_amps["wb"] = 4          # a below-floor value, however it got there
        out = st.filter(_charge(amps=6), _view(inputs_degraded=True, solar_w=0.0),
                        _Adapter(), min_change_interval_s=0.0, now_ts=100.0)
        assert out.commanded_amps >= 6

    def test_a_stop_is_never_frozen(self):
        """Safety must not wait for the sensors to come back."""
        st = ChargeStability()
        self._settle(st, amps=10)
        out = st.filter(_disable(), _view(inputs_degraded=True, solar_w=0.0),
                        _Adapter(), min_change_interval_s=0.0, now_ts=100.0)
        assert out.intent is ChargerIntent.DISABLE

    def test_a_disconnect_is_never_frozen(self):
        st = ChargeStability()
        self._settle(st, amps=10)
        out = st.filter(_charge(amps=6),
                        _view(inputs_degraded=True, connected=False, power_w=0.0),
                        _Adapter(), min_change_interval_s=0.0, now_ts=100.0)
        assert out.commanded_amps == 6, "an unplugged charger has nothing to hold"

    def test_always_max_is_out_of_scope(self):
        """PROD's mode. It never reads solar or grid, so a dark cycle cannot
        move it and this guard must not touch it."""
        st = ChargeStability()
        out = st.filter(_charge(amps=16), _view(mode="always_max",
                                                inputs_degraded=True, solar_w=0.0),
                        _Adapter(), min_change_interval_s=0.0, now_ts=100.0)
        assert out.commanded_amps == 16

    def test_nothing_committed_yet_passes_through(self):
        """No prior command means there is nothing to hold — and we must not
        invent one. Starting a charge needs positive evidence."""
        st = ChargeStability()
        out = st.filter(_charge(amps=6), _view(inputs_degraded=True, solar_w=0.0),
                        _Adapter(), min_change_interval_s=0.0, now_ts=100.0)
        assert out.commanded_amps in (0, 6)


@pytest.mark.unit
class TestTheFlagIsActuallyRaised:
    """The guard above is worthless if nothing ever sets the flag — an inert
    half is how #804 Phase A shipped as a slice. These pin the wiring:
    reader -> PowerReadings -> FleetContext."""

    def _reader(self):
        from unittest.mock import MagicMock

        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        hass = MagicMock()
        hass.states = MagicMock()
        return SensorReader(hass, {})

    def test_an_unavailable_solar_read_is_recorded(self):
        r = self._reader()
        r.hass.states.get = lambda eid: None
        assert r._read_sensor("sensor.inverter", "solar") == 0.0
        assert r._input_dark.get("solar")

    def test_an_unavailable_grid_read_is_recorded(self):
        r = self._reader()
        r.hass.states.get = lambda eid: None
        r._read_sensor("sensor.meter", "grid")
        assert r._input_dark.get("grid")

    def test_a_non_steering_input_is_not_recorded(self):
        """Only the inputs the surplus maths steers on. A missing daily-energy
        counter is a different problem and must not freeze the charger."""
        r = self._reader()
        r.hass.states.get = lambda eid: None
        r._read_sensor("sensor.counter", "daily_solar")
        assert r._input_dark == {}

    def test_the_fleet_context_carries_it(self):
        from unittest.mock import MagicMock

        from custom_components.solar_energy_management.coordinator.build_view import (
            build_charger_view,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            FleetCycleState,
        )

        def _view_for(**flags):
            power = MagicMock()
            power.solar_power = 3000.0
            power.home_consumption_power = 500.0
            power.battery_soc = 50.0
            power.ev_power_per_charger = {}
            power.ev_connected_per_charger = {}
            power.ev_charging_per_charger = {}
            # (#551 mock fidelity) A bare MagicMock attribute is TRUTHY,
            # which would make every one of these read "degraded" and the
            # test pass for the wrong reason. Pin all of them.
            power.inputs_degraded = bool(flags)
            power.solar_power_unavailable = flags.get("solar", False)
            power.grid_power_unavailable = flags.get("grid", False)
            power.battery_power_unavailable = flags.get("battery", False)
            return build_charger_view(
                FleetCycleState(power=power, config={}, is_night=False,
                                tariff_level=None, forecast_remaining_kwh=0.0),
                charger_id="wb", charger_cfg={"id": "wb"},
                mode="solar_only", daily_ev_kwh=0.0,
            )

        assert _view_for().fleet.inputs_degraded is False
        assert _view_for(solar=True).fleet.inputs_degraded is True
        assert _view_for(grid=True).fleet.inputs_degraded is True
        assert _view_for(battery=True).fleet.inputs_degraded is True


@pytest.mark.unit
class TestTwoQuestionsTwoAnswers:
    """One dark inverter among three must degrade the DECISION without
    blanking a total that is mostly real."""

    def _reader(self):
        from unittest.mock import MagicMock

        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        hass = MagicMock()
        hass.states = MagicMock()
        r = SensorReader(hass, {})
        r._input_reads = {}
        r._input_dark = {}
        return r

    def _live(self, value=500.0):
        from unittest.mock import Mock

        import homeassistant.util.dt as dt_util
        s = Mock()
        s.state = str(value)
        s.attributes = {"unit_of_measurement": "W"}
        s.last_updated = s.last_reported = dt_util.utcnow()
        return s

    def test_one_dark_inverter_does_not_blank_the_total(self):
        r = self._reader()
        live = self._live(500.0)
        r.hass.states.get = lambda eid: None if eid == "sensor.pv3" else live
        for eid in ("sensor.pv1", "sensor.pv2", "sensor.pv3"):
            r._read_sensor(eid, "solar")

        assert r._all_dark("solar") is False, "1 of 3 dark blanked the whole total"
        assert any(r._input_dark.values()), "the decision was not told it is partial"

    def test_every_source_dark_leaves_nothing_to_publish(self):
        r = self._reader()
        r.hass.states.get = lambda eid: None
        for eid in ("sensor.pv1", "sensor.pv2"):
            r._read_sensor(eid, "solar")
        assert r._all_dark("solar") is True

    def test_a_healthy_read_is_not_dark(self):
        r = self._reader()
        r.hass.states.get = lambda eid: self._live(500.0)
        r._read_sensor("sensor.pv1", "solar")
        assert r._all_dark("solar") is False
        assert not any(r._input_dark.values())


@pytest.mark.unit
class TestTheEntitySaysUnavailable:
    """A fabricated 0 W also books a false zero into HA's long-term
    statistics. ``battery_soc`` has always published ``None`` in this
    situation; the power readings now say the same thing."""

    def _data(self, **flags):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
            SEMData,
        )
        power = PowerReadings()
        power.solar_power = 583.0
        power.grid_power = -1388.0
        power.battery_power = -1033.0
        power.home_consumption_power = 2636.0
        for k, v in flags.items():
            setattr(power, k, v)
        return SEMData(power=power).to_dict()

    def test_a_healthy_cycle_publishes_numbers(self):
        d = self._data()
        assert d["solar_power"] == 583.0
        assert d["grid_power"] == -1388.0
        assert d["battery_power"] == -1033.0

    def test_a_fully_dark_solar_publishes_nothing(self):
        d = self._data(solar_power_unavailable=True)
        assert d["solar_power"] is None
        assert d["grid_power"] == -1388.0, "only the dark input goes quiet"

    def test_a_fully_dark_grid_takes_its_derived_twin_with_it(self):
        d = self._data(grid_power_unavailable=True)
        assert d["grid_power"] is None
        assert d["grid_active_power"] is None, (
            "the K-Flow twin is the same reading negated — it cannot be more "
            "certain than its source"
        )

    def test_home_is_never_blanked(self):
        """CLAUDE.md is explicit: home_consumption_power must never report
        unknown. Its own #237/#444 hold owns that case."""
        d = self._data(solar_power_unavailable=True, grid_power_unavailable=True,
                       battery_power_all_unavailable=True)
        assert d["home_consumption_power"] == 2636.0


@pytest.mark.unit
class TestTheBatteryClampDoesNotFlapEither:
    """LIMIT_DISCHARGE engages when solar surplus sits below the assist
    gate, so a fabricated 0 W engaged it and the recovery released it —
    ~50 modbus write pairs a day, the churn #538 had to make idempotent."""

    def _adapter(self, last_intent=None):
        from unittest.mock import AsyncMock, MagicMock
        a = MagicMock()
        a.last_intent = last_intent
        a.command_off = AsyncMock()
        a.command_normal = AsyncMock()
        a.command_limit_discharge = AsyncMock()
        a.command_force_charge = AsyncMock()
        a.command_force_discharge = AsyncMock()
        return a

    def _decision(self, intent, watts=0.0):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryDecision,
        )
        return BatteryDecision(battery_id="b1", intent=intent,
                               discharge_limit_w=watts,
                               charge_power_w=watts, reason="test")

    async def _run(self, decision, adapter, degraded):
        from custom_components.solar_energy_management.coordinator.actuate_battery import (
            actuate_battery,
        )
        await actuate_battery(decision, adapter, inputs_degraded=degraded)

    @pytest.mark.asyncio
    async def test_a_dark_cycle_does_not_engage_the_clamp(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        a = self._adapter(last_intent=BatteryIntent.NORMAL)
        await self._run(self._decision(BatteryIntent.LIMIT_DISCHARGE, 500.0), a, True)
        a.command_limit_discharge.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_dark_cycle_does_not_release_the_clamp(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        a = self._adapter(last_intent=BatteryIntent.LIMIT_DISCHARGE)
        await self._run(self._decision(BatteryIntent.NORMAL), a, True)
        a.command_normal.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_healthy_cycle_still_clamps(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        a = self._adapter(last_intent=BatteryIntent.NORMAL)
        await self._run(self._decision(BatteryIntent.LIMIT_DISCHARGE, 500.0), a, False)
        a.command_limit_discharge.assert_called()

    @pytest.mark.asyncio
    async def test_the_user_s_own_mode_is_never_frozen(self):
        """OFF is hands-off, chosen by the user — not decided from any power
        number, so a dark cycle has no business holding it back."""
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        a = self._adapter(last_intent=BatteryIntent.NORMAL)
        await self._run(self._decision(BatteryIntent.OFF), a, True)
        a.command_off.assert_called()

    @pytest.mark.asyncio
    async def test_a_scheduled_force_charge_is_never_frozen(self):
        """The plan decides WHEN from the clock and the tariff, not from a
        power reading."""
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent,
        )
        a = self._adapter(last_intent=BatteryIntent.NORMAL)
        await self._run(self._decision(BatteryIntent.FORCE_CHARGE, 3000.0), a, True)
        a.command_force_charge.assert_called()
