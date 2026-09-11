"""#933 — a Repair its own remedy could not clear.

PROD, 08.09.2026: the #919 Repair "Battery platform pinned to Generic" was
right, the remedy was applied exactly as it says (``battery_charge_platform``
→ auto), the adapter came back as Huawei — and forty minutes later the Repair
was still there.

The check acted only when its verdict CHANGED, against a memo that started
empty. ``pinned_generic_brand`` answers None for "not pinned", the empty memo
answered None too, so the first verdict of every fresh coordinator was
swallowed — and a fresh coordinator is exactly what the remedy produces (the
options write reloads the entry), and what every restart produces. The Repair
is persistent: it outlives every memo that could have cleared it.

The same shape lived beside it: a persistent Repair cleared only when an
in-memory flag says THIS lifetime raised it. Each sibling below is driven the
way the reload drives it — a fresh owner, a Repair its predecessor left, a
healthy first verdict — and must clear it once, and only once. Every verdict
comes from the production code that forms it, never from an injected
attribute.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import homeassistant.util.dt as dt_util
import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    BatteryControlAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_mode_watch import (
    CONFIRM_READS,
    BatteryModeWatch,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.forecast_reader import (
    SOLCAST_ENTITIES,
    ForecastReader,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.features import (
    load_management as lm_mod,
)

RI = "custom_components.solar_energy_management.coordinator.repair_issues"
PIN = RI + ".{}_battery_platform_pinned_generic"


# ── #933 itself ──────────────────────────────────────────────────────────


def _coord(*contexts):
    """A coordinator as the pin check sees it: HA running, the Huawei
    integration loaded, one adapter context per battery."""
    c = SimpleNamespace(hass=SimpleNamespace(is_running=True,
                                             data={"huawei_solar": {}}))
    c._battery_adapter_context = lambda bid, idx, n: dict(contexts[idx])
    return c


PINNED = {"battery_charge_platform": "generic"}
AUTO = {"battery_charge_platform": "auto"}
# #531: a generic battery with its OWN control surface is a real choice
SESSY = {"battery_charge_platform": "generic",
         "battery_strategy_control_entity": "select.sessy_strategy"}


def _cycles(c, ids, n=3):
    for _ in range(n):
        for i, bid in enumerate(ids):
            SEMCoordinator._check_battery_platform_pin(c, bid, i, len(ids))


@pytest.mark.unit
class TestTheRemedyClearsItsOwnRepair:

    def test_the_reloaded_coordinator_clears_it(self):
        """The PROD evening: raised on the pinned install, remedied, and the
        reload the remedy triggers must take the Repair down."""
        with patch(PIN.format("raise")) as raise_:
            _cycles(_coord(PINNED), ["primary"])
        raise_.assert_called_once()
        assert raise_.call_args.kwargs["brand"] == "huawei"

        # set_option → async_reload → a NEW coordinator, memo empty
        with patch(PIN.format("raise")) as raise_, \
                patch(PIN.format("clear")) as clear:
            _cycles(_coord(AUTO), ["primary"], n=5)
        assert clear.call_count == 1, (
            "the first verdict of a fresh coordinator was swallowed — the "
            "Repair outlives the memo that could clear it (#933)")
        raise_.assert_not_called()

    def test_a_still_pinned_install_raises_once_and_never_clears(self):
        with patch(PIN.format("raise")) as raise_, \
                patch(PIN.format("clear")) as clear:
            _cycles(_coord(PINNED), ["primary"], n=5)
        raise_.assert_called_once()
        clear.assert_not_called()


@pytest.mark.unit
class TestOneRepairOneVerdict:
    """The Repair has ONE id for the whole install, so a first-verdict clear
    decided per battery would let a healthy second battery take down the
    first one's Repair — the cure for #933 must not introduce that."""

    @pytest.mark.parametrize("order", [("huawei", "sessy"), ("sessy", "huawei")])
    def test_a_healthy_second_battery_does_not_clear_the_first(self, order):
        ctx = {"huawei": PINNED, "sessy": SESSY}
        c = _coord(*(ctx[b] for b in order))
        with patch(PIN.format("raise")) as raise_, \
                patch(PIN.format("clear")) as clear:
            _cycles(c, list(order))
        raise_.assert_called_once()
        clear.assert_not_called()

    def test_nothing_is_decided_until_every_battery_has_answered(self):
        c = _coord(AUTO, AUTO)
        with patch(PIN.format("clear")) as clear:
            SEMCoordinator._check_battery_platform_pin(c, "a", 0, 2)
            clear.assert_not_called()
            SEMCoordinator._check_battery_platform_pin(c, "b", 1, 2)
            _cycles(c, ["a", "b"])
        clear.assert_called_once()

    def test_it_stays_until_the_last_pinned_battery_is_fixed(self):
        contexts = [PINNED, PINNED]
        c = SimpleNamespace(hass=SimpleNamespace(is_running=True,
                                                 data={"huawei_solar": {}}))
        c._battery_adapter_context = lambda bid, idx, n: dict(contexts[idx])
        with patch(PIN.format("raise")) as raise_, \
                patch(PIN.format("clear")) as clear:
            _cycles(c, ["a", "b"])
            contexts[0] = AUTO
            _cycles(c, ["a", "b"])
            clear.assert_not_called()
            contexts[1] = AUTO
            _cycles(c, ["a", "b"])
        raise_.assert_called_once()
        clear.assert_called_once()


@pytest.mark.unit
class TestTheSocZoneCheckIsNotAnInstance:
    """Its memo also starts at None, but its verdict is a bool — never None
    — so the first verdict always acts. Pinned so it stays that way."""

    def test_a_fresh_coordinator_with_ordered_zones_clears_once(self):
        fake = SimpleNamespace(
            hass=SimpleNamespace(is_running=True),
            config={"battery_priority_soc": 20, "battery_buffer_soc": 50,
                    "battery_auto_start_soc": 80})
        with patch(RI + ".clear_soc_zones_out_of_order") as clear, \
                patch(RI + ".raise_soc_zones_out_of_order") as raise_:
            for _ in range(3):
                SEMCoordinator._check_soc_zone_order(fake)
        clear.assert_called_once()
        raise_.assert_not_called()


# ── the siblings: a persistent Repair, a lifetime-scoped memo ────────────


@pytest.mark.unit
class TestTheChargerControlEntityRepair:
    """#824: a Repair raised before the restart — or before the reload that
    fixing the helper caused — is not in this coordinator's raised-set."""

    CFG = {"name": "Wallbox", "ev_current_control_entity": "number.wb_current",
           "ev_start_stop_entity": "switch.wb_enable"}

    def _coord(self, raised=()):
        states = {"number.wb_current": SimpleNamespace(state="16"),
                  "switch.wb_enable": SimpleNamespace(state="on")}
        hass = MagicMock()
        hass.states.get = lambda eid: states.get(eid)
        return SimpleNamespace(
            hass=hass,
            _CONTROL_CAPABILITIES=SEMCoordinator._CONTROL_CAPABILITIES,
            _control_broken_since={}, _control_repair_raised=set(raised))

    def test_a_fresh_coordinator_clears_each_valid_entity_once(self):
        c = self._coord()
        with patch(RI + ".clear_charger_control_entity_broken") as clear:
            for _ in range(3):
                SEMCoordinator._check_charger_control_entities(c, "wb", self.CFG, {})
        assert sorted(k.args[2] for k in clear.call_args_list) == [
            "number.wb_current", "switch.wb_enable"]

    def test_one_raised_this_lifetime_is_cleared_once_not_twice(self):
        c = self._coord(raised=[("wb", "number.wb_current")])
        with patch(RI + ".clear_charger_control_entity_broken") as clear:
            for _ in range(3):
                SEMCoordinator._check_charger_control_entities(c, "wb", self.CFG, {})
        assert [k.args[2] for k in clear.call_args_list].count(
            "number.wb_current") == 1
        assert not c._control_repair_raised


@pytest.mark.unit
class TestTheBatteryWriteRepair:
    """#915: the verdict comes from the real generic adapter — a reflected
    write names the entity it proved, so its predecessor's Repair can go."""

    def _reflected(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="3000", attributes={"unit_of_measurement": "W"}))
        ad = GenericBatteryAdapter(hass, {
            "battery_discharge_control_entity": "number.limit"})
        ad._note_pending_write("number.limit", 3000.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is True
        return ad

    def test_the_first_reflected_write_clears_a_predecessors_repair(self):
        ad = self._reflected()
        c = SimpleNamespace(hass=MagicMock(),
                            BATTERY_WRITE_STRIKES=SEMCoordinator.BATTERY_WRITE_STRIKES)
        with patch(RI + ".clear_battery_control_write_not_taken") as clear, \
                patch(RI + ".raise_battery_control_write_not_taken") as raise_:
            for _ in range(3):
                SEMCoordinator._raise_or_clear_battery_write_repair(c, ad, True)
        clear.assert_called_once()
        assert clear.call_args.args[1] == "number.limit"
        raise_.assert_not_called()

    def test_a_write_that_did_not_take_proves_nothing(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="5000", attributes={"unit_of_measurement": "W"}))
        ad = GenericBatteryAdapter(hass, {
            "battery_discharge_control_entity": "number.limit"})
        ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is False
        assert not ad.last_verified_entity


def _reading(value, *, reported_at=None, unit="W"):
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit, "friendly_name": "X"}
    at = reported_at or dt_util.utcnow()
    s.last_updated = at
    s.last_reported = at
    return s


@pytest.mark.unit
class TestTheSensorRepairs:

    def _reader(self, state):
        hass = MagicMock()
        hass.states.get = lambda eid: state()
        r = SensorReader(hass, {})
        r._sign_vote_warmup = 0
        return r

    def test_the_first_healthy_read_clears_a_predecessors_unavailable_repair(self):
        r = self._reader(lambda: _reading(42.0))
        with patch(RI + ".clear_sensor_unavailable") as clear:
            for _ in range(3):
                assert r._read_sensor("sensor.meter", "test") == 42.0
        clear.assert_called_once()
        assert clear.call_args.args[1] == "sensor.meter"

    def test_a_report_seen_by_this_lifetime_clears_a_predecessors_stale_repair(self):
        t0 = dt_util.utcnow()
        at = {"t": t0 - timedelta(seconds=30)}
        r = self._reader(lambda: _reading(1000, reported_at=at["t"]))
        with patch(RI + ".clear_sensor_stale") as clear:
            r._read_sensor("sensor.grid", "grid")
            clear.assert_not_called()          # first sight proves nothing
            at["t"] = t0 - timedelta(seconds=5)  # the integration reports
            for _ in range(3):
                r._read_sensor("sensor.grid", "grid")
        clear.assert_called_once()
        assert clear.call_args.args[1] == "sensor.grid"

    def test_a_restored_value_that_never_reports_is_not_evidence(self):
        """After a restart a frozen sensor's restored state LOOKS fresh for
        ten minutes. A timestamp this lifetime never saw move is not proof
        the stall ended, so the predecessor's Repair stays."""
        at = dt_util.utcnow() - timedelta(seconds=20)
        r = self._reader(lambda: _reading(1000, reported_at=at))
        with patch(RI + ".clear_sensor_stale") as clear:
            for _ in range(5):
                r._read_sensor("sensor.grid", "grid")
        clear.assert_not_called()


class _Adapter(BatteryControlAdapter):
    async def command_normal(self): return True
    async def command_force_charge(self, watts): return True
    async def command_limit_discharge(self, watts): return True
    async def command_stop(self): return True
    async def command_stop_force_charge(self): return True

    @property
    def supports_forced_charge(self): return True

    @property
    def max_charge_power_w(self): return 5000.0

    @property
    def max_discharge_power_w(self): return 5000.0


@pytest.mark.unit
class TestTheForceDischargeRepair:
    """#840: the refusal count lives on the adapter, and a reload builds a
    new one at zero — so 'recovered from refusals' never fires."""

    async def test_the_first_accepted_write_clears_a_predecessors_repair(self):
        hass = MagicMock()
        hass.states.get.return_value = MagicMock(attributes={})
        hass.services.async_call = AsyncMock(return_value=True)
        a = _Adapter(hass, {"battery_force_discharge_control_entity":
                            "number.growatt_power_setpoint"})
        with patch(RI + ".clear_battery_force_discharge_unsupported") as clear:
            await a._write_force_discharge(0.0)
            await a._write_force_discharge(1500.0)
            await a._write_force_discharge(0.0)
        clear.assert_called_once()
        assert clear.call_args.args[1] == "number.growatt_power_setpoint"

    async def test_a_refused_write_proves_nothing(self):
        hass = MagicMock()
        hass.states.get.return_value = MagicMock(attributes={})
        hass.services.async_call = AsyncMock(side_effect=Exception("Not supported"))
        a = _Adapter(hass, {"battery_force_discharge_control_entity":
                            "number.growatt_power_setpoint"})
        with patch(RI + ".clear_battery_force_discharge_unsupported") as clear:
            await a._write_force_discharge(1500.0)
        clear.assert_not_called()


@pytest.mark.unit
class TestTheNoForecastRepair:

    def test_the_first_detection_clears_a_predecessors_repair(self, mock_hass):
        mock_hass.states.get = lambda eid: (
            SimpleNamespace(state="25.5", attributes={})
            if eid == SOLCAST_ENTITIES["forecast_today"] else None)
        reader = ForecastReader(mock_hass)
        with patch(RI + ".clear_no_forecast_integration") as clear:
            for _ in range(3):
                assert reader.detect_source() == "solcast"
        clear.assert_called_once()


@pytest.fixture
def shedder(mock_hass):
    entry = MagicMock()
    entry.options = {"load_management_enabled": True, "target_peak_limit": 5.0,
                     "warning_peak_level": 4.5, "emergency_peak_level": 6.0,
                     "peak_hysteresis": 0.3}
    entry.entry_id = "test_entry"
    with patch.object(lm_mod, "LoadDeviceDiscovery") as disc_cls, \
            patch.object(lm_mod, "Store"):
        disc = MagicMock()
        disc.turn_off_device = AsyncMock(return_value=True)
        disc.turn_on_device = AsyncMock(return_value=True)
        disc_cls.return_value = disc
        lm = lm_mod.LoadManagementCoordinator(mock_hass, entry)
        lm._device_discovery = disc
        live = {}
        disc.get_device_current_state = MagicMock(
            side_effect=lambda info: live.get(info.get("switch_entity"),
                                              {"is_on": False, "current_power": 0}))
        for did, prio, watts in (("pool_pump", 9, 2000), ("dryer", 8, 1500)):
            lm._devices[did] = {
                "switch_entity": f"switch.{did}", "friendly_name": did,
                "power_rating": watts, "is_available": True, "priority": prio,
                "is_critical": False, "is_controllable": True}
            live[f"switch.{did}"] = {"is_on": True, "current_power": watts,
                                     "power_known": True}
        on = MagicMock()
        on.state = "on"
        mock_hass.states.get = MagicMock(return_value=on)
        yield lm


@pytest.mark.unit
class TestTheLoadShedFutileRepair:

    async def test_the_first_reachable_plan_clears_a_predecessors_repair(self, shedder):
        """6 kW at the meter, 3.5 kW sheddable: reachable, not futile."""
        with patch(RI + ".ir.async_delete_issue") as delete:
            for _ in range(3):
                shedder._state = lm_mod.LoadManagementState.EMERGENCY
                shedder._last_grid_import_w = 6000.0
                await shedder._execute_load_management(6.5, 6.5)
        futile = [k for k in delete.call_args_list
                  if k.args[-1] == "load_shed_futile"]
        assert len(futile) == 1


@pytest.mark.unit
class TestTheOperatingModeWatch:
    """#845: non-persistent, but an options reload keeps the issue registry
    and rebuilds the watch — whose first expected reading used to be no
    edge at all."""

    def test_the_first_expected_reading_is_an_edge(self):
        w = BatteryModeWatch({"maximise_self_consumption"})
        w.feed("unavailable")
        assert not w.changed, "no reading is no verdict"
        w.feed("maximise_self_consumption")
        assert w.changed and not w.raised
        assert not w.recovered, "settling is not a recovery (no 'back to' line)"
        w.feed("maximise_self_consumption")
        assert not w.changed

    def test_a_real_recovery_still_says_so(self):
        w = BatteryModeWatch({"maximise_self_consumption"})
        for _ in range(CONFIRM_READS):
            w.feed("fully_fed_to_grid")
        assert w.raised and w.changed
        w.feed("maximise_self_consumption")
        assert w.changed and w.recovered and not w.raised


@pytest.mark.unit
class TestTheSplitGridGuessRepair:
    """#911: the Repair tells the user to set the pair in SEM's options and
    promises "this notice clears on the next read" — but that write reloads
    SEM onto the manual path, which never touched it, and the sweep that does
    clear it hangs off EVENT_HOMEASSISTANT_STARTED, which a reload never
    fires."""

    SR_RI = "custom_components.solar_energy_management.coordinator.sensor_reader._ri"

    def test_the_remedy_clears_it_on_the_reloaded_reader(self):
        from .test_split_grid_integration import (
            _make_energy_dashboard_config, _make_reader_with_states, _state)
        ed = _make_energy_dashboard_config(
            solar_power="sensor.fox_pv_power", grid_import_power=None,
            grid_import_energy="sensor.fox_grid_import_energy",
            grid_export_energy="sensor.fox_grid_export_energy",
            battery_power=None)
        states = {
            "sensor.fox_pv_power": _state(0),
            "sensor.p1_import": _state(1466, device_class="power"),
            "sensor.p1_export": _state(0, device_class="power"),
            "sensor.fox_grid_import_energy": _state(150, "kWh"),
            "sensor.fox_grid_export_energy": _state(20, "kWh"),
        }
        reader = _make_reader_with_states(
            MagicMock(), states, ed,
            extra_config={"grid_import_power_entity": "sensor.p1_import",
                          "grid_export_power_entity": "sensor.p1_export"})
        with patch(self.SR_RI) as ri:
            for _ in range(3):
                reader.read_power()
        assert ri.clear_split_grid_guessed.call_count == 1
        ri.raise_split_grid_guessed.assert_not_called()

    def test_a_live_guess_is_not_cleared_by_it(self):
        from .test_911_split_grid_guess import _reader, _state
        states = {
            "sensor.fox_pv_power": _state(0),
            "sensor.energy_log_current_power_consumption_32306":
                _state(10, device_class="power"),
            "sensor.fox_grid_import_energy": _state(150, "kWh"),
            "sensor.fox_grid_export_energy": _state(20, "kWh"),
        }
        reader, reg = _reader(states, {"sensor.fox_grid_import_energy": "fox"})
        with patch("custom_components.solar_energy_management.coordinator"
                   ".sensor_reader.er.async_get", return_value=reg), \
                patch(self.SR_RI) as ri:
            for _ in range(3):
                reader.read_power()
        ri.raise_split_grid_guessed.assert_called_once()
        ri.clear_split_grid_guessed.assert_not_called()
