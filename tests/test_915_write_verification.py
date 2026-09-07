"""#915 — did the battery control write TAKE?

A declared key says what a register is CALLED. It cannot say whether the
register accepts a write, expires it after sixty minutes, needs an enable
switch first, or is a global setting the vendor says to leave alone —
@Azlinon named four such on one EG4. That answer exists only after the first
write, and a register that ignores a write raises nothing (#824, from the
other side of the wire). So the generic adapter — the one a roster proposal
lands on — records each write and judges it on the next cycle, in the
entity's own unit, and the coordinator turns three misses into a Repair.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    BatteryControlAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _hass(state=None):
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=state)
    return hass


def _state(value, unit="W", **attrs):
    return SimpleNamespace(state=str(value),
                           attributes={"unit_of_measurement": unit, **attrs})


def _adapter(hass):
    return GenericBatteryAdapter(hass, {
        "battery_discharge_control_entity": "number.limit",
    })


@pytest.mark.unit
class TestTheGenericAdapterJudgesItsOwnWrite:

    def test_nothing_pending_is_no_verdict(self):
        assert _adapter(_hass()).verify_pending_write() is None

    def test_a_write_is_not_judged_before_the_grace(self):
        """Integrations poll; the entity cannot reflect a write instantly."""
        ad = _adapter(_hass(_state(2000)))
        ad._note_pending_write("number.limit", 3000.0)
        assert ad.verify_pending_write() is None

    def test_a_reflected_write_is_true_and_resets_strikes(self):
        ad = _adapter(_hass(_state(3000)))
        ad.write_not_taken_strikes = 2
        ad._note_pending_write("number.limit", 3000.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is True
        assert ad.write_not_taken_strikes == 0
        assert ad.last_unverified_entity == ""

    def test_a_write_the_register_ignored_is_false_and_strikes(self):
        ad = _adapter(_hass(_state(5000)))
        ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is False
        assert ad.write_not_taken_strikes == 1
        assert ad.last_unverified_entity == "number.limit"
        assert ad.last_unverified_wanted == "1200 W"
        assert ad.last_unverified_seen == "5000 W"
        assert "not reflected" in ad.last_error

    def test_kilowatts_are_compared_in_kilowatts(self):
        ad = _adapter(_hass(_state(3.0, unit="kW")))
        ad._note_pending_write("number.limit", 3000.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is True

    def test_a_register_that_clamps_to_its_own_max_is_reflected(self):
        """Asking 6000 of a 5000-max register and reading 5000 is the
        register doing its job, not ignoring the write."""
        ad = _adapter(_hass(_state(5000, max=5000)))
        ad._note_pending_write("number.limit", 6000.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is True

    def test_a_write_is_judged_once(self):
        ad = _adapter(_hass(_state(5000)))
        ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is False
            assert ad.verify_pending_write() is None

    def test_an_entity_that_vanished_counts_as_not_reflected(self):
        ad = _adapter(_hass(None))
        ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is False
        assert ad.last_unverified_seen == "missing"

    def test_other_adapters_are_untouched(self):
        """Deye has its own read-back; Huawei writes through its own path.
        The base default says 'nothing to judge' and carries zero strikes."""
        class Plain(BatteryControlAdapter):
            async def command_normal(self): ...
            async def command_limit_discharge(self, watts): ...
            async def command_force_charge(self, *a, **k): ...
            async def command_stop_force_charge(self): ...
            @property
            def max_charge_power_w(self): return 0.0
            @property
            def max_discharge_power_w(self): return 0.0
            @property
            def supports_forced_charge(self): return False
        ad = Plain(_hass(), {})
        assert ad.verify_pending_write() is None
        assert ad.write_not_taken_strikes == 0


@pytest.mark.unit
class TestThreeMissesBecomeARepairOnce:
    """Same three-strike shape as #824/#840, on the read-back side."""

    def _coord(self):
        c = SimpleNamespace(hass=MagicMock(),
                            BATTERY_WRITE_STRIKES=SEMCoordinator.BATTERY_WRITE_STRIKES)
        return c

    def _adapter(self, strikes, entity="number.limit"):
        return SimpleNamespace(write_not_taken_strikes=strikes,
                               last_unverified_entity=entity,
                               last_unverified_wanted="1200 W",
                               last_unverified_seen="5000 W")

    def test_two_misses_raise_nothing(self):
        c = self._coord()
        with patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".raise_battery_control_write_not_taken") as raise_:
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(2), False)
        raise_.assert_not_called()

    def test_the_third_miss_raises_exactly_once(self):
        c = self._coord()
        with patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".raise_battery_control_write_not_taken") as raise_:
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(3), False)
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(4), False)
        assert raise_.call_count == 1
        kw = raise_.call_args.kwargs
        assert kw["entity_id"] == "number.limit"
        assert kw["wanted"] == "1200 W" and kw["seen"] == "5000 W"

    def test_a_reflected_write_clears_it(self):
        c = self._coord()
        with patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".raise_battery_control_write_not_taken"), \
             patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".clear_battery_control_write_not_taken") as clear:
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(3), False)
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(0, entity=""), True)
        clear.assert_called_once()
        assert clear.call_args.args[1] == "number.limit"
        assert not c._battery_write_repair_raised

    def test_no_verdict_touches_nothing(self):
        c = self._coord()
        with patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".raise_battery_control_write_not_taken") as raise_, \
             patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".clear_battery_control_write_not_taken") as clear:
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(5), None)
        raise_.assert_not_called(); clear.assert_not_called()


@pytest.mark.unit
class TestTheVerdictHasASurface:
    """The failure side is a Repair. The success side had NO surface: PROD's
    first day on the read-back could not show it working, because nothing
    published the verdict. The battery-spendable sensor carries it now."""

    def test_the_battery_sensor_publishes_the_verdict(self):
        from homeassistant.components.sensor import SensorEntityDescription
        from custom_components.solar_energy_management.sensor import SEMSolarSensor
        coord = MagicMock()
        coord.data = {"last_update": "x",
                      "battery_control_write_verified": True,
                      "battery_control_write_strikes": 0}
        coord._sensor_reader = MagicMock()
        s = SEMSolarSensor(coordinator=coord, entry_id="e",
                           description=SensorEntityDescription(
                               key="battery_spendable_kwh", name="x"))
        attrs = s.extra_state_attributes
        assert attrs["write_verified"] is True
        assert attrs["write_strikes"] == 0

    def test_no_verdict_yet_reads_none_not_false(self):
        """None until a changed write has been judged — 'not yet' must not
        look like 'failed'."""
        from homeassistant.components.sensor import SensorEntityDescription
        from custom_components.solar_energy_management.sensor import SEMSolarSensor
        coord = MagicMock()
        coord.data = {"last_update": "x"}
        coord._sensor_reader = MagicMock()
        s = SEMSolarSensor(coordinator=coord, entry_id="e",
                           description=SensorEntityDescription(
                               key="battery_spendable_kwh", name="x"))
        assert s.extra_state_attributes["write_verified"] is None



@pytest.mark.unit
class TestTheDefaultStateReachesAVerdict:
    """(06.09 audit) ``command_normal`` writes the max every cycle. The
    same-value skip returned True, that re-noted the pending write, the
    grace timer re-armed every cycle and no verdict could EVER come — the
    read-back was inert in the default state, which is why PROD read None
    all day. Only a write that went out is noted, and an identical pending
    write is never re-armed."""

    def _adapter_with_stuck_register(self, stuck_at="0"):
        hass = MagicMock()
        hass.states = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state=stuck_at, attributes={"unit_of_measurement": "W", "max": 5000}))
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()
        ad = GenericBatteryAdapter(hass, {
            "battery_discharge_control_entity": "number.limit",
            "battery_max_discharge_power": 5000})
        ad._write_force_discharge = AsyncMock()
        ad._set_strategy = AsyncMock()
        return ad

    @pytest.mark.asyncio
    async def test_a_register_that_ignores_the_write_is_judged_within_cycles(self):
        ad = self._adapter_with_stuck_register()
        verdicts = []
        t = [1000.0]
        with patch("time.monotonic", side_effect=lambda: t[0]):
            for _ in range(10):
                await ad.command_normal()        # writes 5000 (register stays 0)
                verdicts.append(ad.verify_pending_write())
                t[0] += 10.0                     # one coordinator cycle
        assert False in verdicts, verdicts
        assert ad.write_not_taken_strikes >= 1

    @pytest.mark.asyncio
    async def test_the_same_value_skip_is_not_a_write(self):
        from custom_components.solar_energy_management.coordinator.power_control import (
            async_write_power_setpoint_verbose,
        )
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="5000", attributes={"unit_of_measurement": "W"}))
        hass.services.async_call = AsyncMock()
        ok, wrote = await async_write_power_setpoint_verbose(
            hass, "number.limit", 5000.0, context="t")
        assert (ok, wrote) == (True, False)
        hass.services.async_call.assert_not_called()

    def test_an_identical_pending_write_does_not_rearm(self):
        ad = self._adapter_with_stuck_register()
        with patch("time.monotonic", return_value=100.0):
            ad._note_pending_write("number.limit", 5000.0)
        with patch("time.monotonic", return_value=105.0):
            ad._note_pending_write("number.limit", 5000.0)   # must NOT reset
        assert ad._pending_write[2] == 100.0



@pytest.mark.unit
class TestTheVerdictWaitsForAReportNotAClock:
    """(06.09 audit) Huawei's adapter documents a 30-60 s poll lag: the HA
    entity shows the stale commanded value until huawei_solar next polls.
    A fixed 8 s grace judged a correct write "not reflected". The verdict
    waits until the entity has been REPORTED since the write, and gives up
    only on an integration silent for three minutes."""

    def _adapter(self, state_value, reported_at):
        import datetime as dt
        hass = MagicMock()
        st = SimpleNamespace(state=str(state_value),
                             attributes={"unit_of_measurement": "W"},
                             last_reported=dt.datetime.fromtimestamp(
                                 reported_at, tz=dt.timezone.utc))
        hass.states.get = MagicMock(return_value=st)
        return GenericBatteryAdapter(hass, {"battery_discharge_control_entity": "number.limit"})

    def test_stale_value_before_the_integration_reports_is_not_a_miss(self):
        # write at wall 1000; the entity was last reported at 990 (before)
        ad = self._adapter(5000, reported_at=990.0)
        with patch("time.monotonic", return_value=100.0), patch("time.time", return_value=1000.0):
            ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=120.0):   # 20 s later, still unreported
            assert ad.verify_pending_write() is None
        assert ad.write_not_taken_strikes == 0

    def test_once_reported_the_value_is_judged(self):
        ad = self._adapter(1200, reported_at=1030.0)          # reported AFTER the write
        with patch("time.monotonic", return_value=100.0), patch("time.time", return_value=1000.0):
            ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=140.0):
            assert ad.verify_pending_write() is True

    def test_a_report_after_the_write_that_still_shows_the_old_value_is_a_miss(self):
        ad = self._adapter(5000, reported_at=1030.0)
        with patch("time.monotonic", return_value=100.0), patch("time.time", return_value=1000.0):
            ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=140.0):
            assert ad.verify_pending_write() is False

    def test_an_integration_silent_for_three_minutes_is_judged_anyway(self):
        ad = self._adapter(5000, reported_at=990.0)
        with patch("time.monotonic", return_value=100.0), patch("time.time", return_value=1000.0):
            ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=100.0 + ad._WRITE_REPORT_WAIT_S + 1):
            assert ad.verify_pending_write() is False

    def test_a_state_without_timestamps_keeps_the_old_grace(self):
        """Test doubles and helper entities may carry no timestamps: the
        8 s grace alone then decides, exactly as before."""
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="1200", attributes={"unit_of_measurement": "W"}))
        ad = GenericBatteryAdapter(hass, {"battery_discharge_control_entity": "number.limit"})
        with patch("time.monotonic", return_value=100.0):
            ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=110.0):
            assert ad.verify_pending_write() is True
