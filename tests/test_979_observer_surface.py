"""#979 — the observer surface tells you what it already knows.

Three faults, one shape (RienduPre, 2.1.0-beta.29, via discussion #958): a
surface that could have named the fault from data it was already holding, and
named something else instead.

1. An idle charger's analytics warned once per flap. ``available`` logged
   WARNING for ANY unavailable SEM entity, with no notion of a state where
   "unavailable" is the right answer — both wallboxes were simply idle, so the
   flow/taper/session keys were absent by design, ~11 sensors per charger.
2. ``Home consumption residual clamped by 2887W`` named the aggregate and not
   one of the six readings it is computed from — all six in hand at the site.
3. ``diag_charger_control`` carried #814's whole detection report as a
   RECORDED attribute. Its size is (entities × scanned charger platforms), so
   on a real install it crossed HA's 16 KB cap and the recorder stored NOTHING
   for that entity — while its own sibling ``control_entities`` had been
   declared ``_unrecorded_attributes`` and cost the cap nothing.

Each oracle here has its vacuity twin: the guard is shown firing on the code
as it was, so a passing run means the guard works, not that it is asleep.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from homeassistant.components.sensor import SensorEntityDescription

from custom_components.solar_energy_management.consts.core import (
    RECORDER_MAX_STATE_ATTRS_BYTES,
)
from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
    home_member_evidence,
    home_member_totals,
    largest_demand_term,
    power_terms,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyTotals,
    PowerFlows,
    PowerReadings,
)
from custom_components.solar_energy_management.sensor import SEMSolarSensor
from custom_components.solar_energy_management.utils.attr_budget import (
    TRIMMED_KEY,
    fit_state_attributes,
    json_size,
)

_ROOT = Path(__file__).resolve().parent.parent

# Every platform that builds entities. The bug was in two of them; the lint
# below is what keeps it out of the other five.
_ENTITY_PLATFORMS = (
    "sensor.py", "switch.py", "binary_sensor.py", "number.py",
    "select.py", "time.py", "button.py",
)

_FAULT_LEVELS = ("warning", "error", "critical", "exception")


def _availability_faults(source: str) -> list[str]:
    """Every fault-level log call inside an ``available`` property."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "available":
            continue
        for call in ast.walk(node):
            if (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in _FAULT_LEVELS
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id.endswith("LOGGER")):
                found.append(f"line {call.lineno}: _LOGGER.{call.func.attr}")
    return found


def _sensor(coordinator, key, **kw):
    return SEMSolarSensor(
        coordinator=coordinator,
        description=SensorEntityDescription(key=key, name=key, **kw),
        entry_id="test_entry_id",
    )


def _readings(**kw) -> PowerReadings:
    p = PowerReadings(**kw)
    p.calculate_derived()
    return p


@pytest.mark.unit
class TestUnavailableIsNotAFault:
    """(1) An entity with nothing to publish is not a fault report."""

    def test_no_platform_calls_an_unavailable_entity_a_fault(self):
        """The class guard: no ``available`` property may log at fault level.

        One failed coordinator update makes every SEM entity unavailable at
        once, so a per-entity WARNING is ~200 lines describing one event — and
        an idle charger's analytics are not an event at all. Whatever a future
        platform's ``available`` says, it says it at debug.
        """
        offenders = {
            name: _availability_faults((_ROOT / name).read_text())
            for name in _ENTITY_PLATFORMS
            if (_ROOT / name).exists()
        }
        assert not any(offenders.values()), (
            f"availability must not be reported as a fault: "
            f"{ {k: v for k, v in offenders.items() if v} }"
        )

    def test_the_guard_fires_on_the_code_as_it_was(self):
        """Vacuity twin — the #979 source, verbatim, must be caught."""
        was = (
            "class X:\n"
            "    @property\n"
            "    def available(self) -> bool:\n"
            "        if not is_available and not self._logged_unavailable:\n"
            "            _LOGGER.warning('Sensor %s is unavailable', key)\n"
            "        return is_available\n"
        )
        assert _availability_faults(was)

    def test_an_idle_chargers_analytics_say_why_at_debug(self, mock_coordinator, caplog):
        """The reporter's case: key absent because there is no session."""
        mock_coordinator.data = {"solar_power": 1200}
        mock_coordinator.last_update_success = True
        sensor = _sensor(mock_coordinator, "charger_ev_charger_1_flow_solar_to_ev_power")

        with caplog.at_level("DEBUG"):
            assert sensor.available is False

        faults = [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
        assert not faults, [r.getMessage() for r in faults]
        said = " ".join(r.getMessage() for r in caplog.records)
        assert "nothing to compute" in said
        assert "charger_ev_charger_1_flow_solar_to_ev_power" in said

    def test_the_reason_separates_the_three_ways_to_be_unavailable(
            self, mock_coordinator):
        """The surface knows WHY — that is the thing it was throwing away."""
        # (a) nothing published yet
        mock_coordinator.data = {}
        mock_coordinator.last_update_success = True
        s = _sensor(mock_coordinator, "solar_power")
        assert s.available is False
        assert "no cycle yet" in s._unavailable_reason

        # (b) this key is not published this cycle
        mock_coordinator.data = {"grid_power": 0}
        s = _sensor(mock_coordinator, "charger_ev_charger_1_taper_ratio")
        assert s.available is False
        assert "nothing to compute" in s._unavailable_reason

        # (c) the key is there and the source read empty
        mock_coordinator.data = {"solar_power": None}
        s = _sensor(mock_coordinator, "solar_power")
        assert s.available is False
        assert "read empty" in s._unavailable_reason

        # ... and an available sensor carries no reason at all
        mock_coordinator.data = {"solar_power": 1200}
        s = _sensor(mock_coordinator, "solar_power")
        assert s.available is True
        assert s._unavailable_reason is None


@pytest.mark.unit
class TestTheClampNamesItsInputs:
    """(2) A disagreement about the residual names the readings behind it."""

    def _clamped(self) -> PowerReadings:
        # A house whose EV reading is 2887 W while nothing is coming in: the
        # residual goes negative and the clamp removes exactly that.
        return _readings(solar_power=0.0, grid_power=0.0, battery_power=0.0,
                         ev_power=2887.0)

    def test_the_violation_names_all_six_terms_and_a_suspect(self):
        v = HealthCheck().check_power_balance(self._clamped())
        assert v, "a 2887 W clamp must still be a violation"
        msg = v[0]
        for term in ("solar=", "grid_import=", "battery_discharge=",
                     "ev=", "grid_export=", "battery_charge="):
            assert term in msg, f"{term} missing from: {msg}"
        assert "Largest demand term: ev=2887W" in msg

    def test_the_aggregate_is_still_there(self):
        """Naming the terms must not cost the number that started the hunt."""
        assert "clamped by 2887W" in HealthCheck().check_power_balance(
            self._clamped())[0]

    def test_the_largest_demand_term_is_the_largest(self):
        p = _readings(solar_power=0.0, grid_power=0.0, battery_power=4000.0,
                      ev_power=1000.0)
        assert largest_demand_term(p) == "battery_charge=4000W"

    def test_the_balance_branch_names_them_too(self):
        """The sibling two branches down had supply/demand and no terms."""
        p = _readings(solar_power=1000.0, grid_power=0.0, battery_power=0.0,
                      ev_power=0.0)
        # A home value that no longer matches its own inputs (the hold has
        # been substituted after ``calculate_derived``) — the balance branch.
        p.home_consumption_power = 4000.0
        msg = HealthCheck().check_power_balance(p)[0]
        assert "imbalance=" in msg and "solar=1000W" in msg

    def test_the_terms_helper_reports_watts_not_kilowatts(self):
        p = _readings(solar_power=1234.0, grid_power=-500.0, battery_power=0.0)
        assert "solar=1234W" in power_terms(p)
        assert "grid_import=500W" in power_terms(p)

    def test_a_double_counted_string_is_named(self):
        """``check_flows`` had the per-string map and printed only its sum."""
        p = _readings(solar_power=3000.0)
        flows = PowerFlows()
        flows.solar_per_string = {"pv1": 3000.0, "pv2": 3000.0}
        msg = HealthCheck().check_flows(p, flows)[0]
        assert "pv1=3000W" in msg and "pv2=3000W" in msg


@pytest.mark.unit
class TestADoubleCountNamesItsSource:
    """(2b) The bucket names the symptom; the source sensor names the fault."""

    def _device(self, device_id, kwh, **kw):
        return SimpleNamespace(
            device_id=device_id, device_type=None, daily_energy_kwh=kwh, **kw)

    def test_the_member_list_carries_the_sensor_and_its_raw_read(self):
        """RienduPre's ``heat_pump=1906.00kWh`` against a 1.8 kWh home row."""
        devices = [self._device(
            "heat_pump", 1906.0, daily_energy_source="counter",
            energy_entity_id="sensor.heat_pump_total_energy",
            _energy_counter_last_kwh=1906.0, daily_energy_blind_s=0.0)]
        msg = HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_home=1.81),
            per_device_daily=home_member_totals(
                devices, (), {d.device_id: d.daily_energy_kwh for d in devices}),
            per_device_evidence=home_member_evidence(devices),
        )[0]
        assert "heat_pump=1906.00kWh" in msg
        assert "counter sensor.heat_pump_total_energy reads 1906.00kWh" in msg

    def test_without_evidence_the_message_is_what_it_always_was(self):
        """Vacuity twin — the suffix is the new information, not the message."""
        devices = [self._device(
            "heat_pump", 1906.0, daily_energy_source="counter",
            energy_entity_id="sensor.heat_pump_total_energy",
            _energy_counter_last_kwh=1906.0, daily_energy_blind_s=0.0)]
        msg = HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_home=1.81),
            per_device_daily=home_member_totals(
                devices, (), {d.device_id: d.daily_energy_kwh for d in devices}),
        )[0]
        assert "heat_pump=1906.00kWh" in msg
        assert "sensor.heat_pump_total_energy" not in msg

    def test_an_estimated_device_offers_no_evidence_and_is_not_invented(self):
        """``rated`` is an estimate — there is no source sensor to name."""
        devices = [self._device(
            "pool_pump", 3.0, daily_energy_source="rated",
            energy_entity_id=None, power_entity_id=None,
            daily_energy_blind_s=0.0)]
        assert home_member_evidence(devices) == {}

    def test_a_power_sourced_device_names_its_power_sensor(self):
        devices = [self._device(
            "boiler", 4.0, daily_energy_source="power",
            energy_entity_id=None, power_entity_id="sensor.boiler_power",
            daily_energy_blind_s=90.0)]
        assert home_member_evidence(devices) == {
            "boiler": "power sensor.boiler_power, blind 90s today"}


@pytest.mark.unit
class TestTheRecorderCap:
    """(3) A report that cannot be recorded is not a report."""

    def _report(self, near_misses=40, entities=12) -> dict:
        """A detection report the size real hardware produces."""
        return {
            "generated_at": "2026-09-18T10:00:00+00:00",
            "scanned_platforms": ["keba", "wallbox", "zaptec", "ocpp", "mqtt"],
            "chargers": [],
            "near_misses": [{
                "platform": "mqtt",
                "device_id": f"dev{n}",
                "entities": [{
                    "entity": f"sensor.zigbee2mqtt_bridge_{n}_{i}",
                    "domain": "sensor",
                    "device_class": "power",
                } for i in range(entities)],
                "note": "entities present, no role matched",
                "roster": {"domain": "mqtt", "name": "MQTT", "installs": 91000},
                "proposed_roles": {},
                "suggested_charger": None,
            } for n in range(near_misses)],
        }

    def _recorded(self, attrs, entity) -> dict:
        """What HA measures against the cap: attributes minus the unrecorded
        ones (``recorder.db_schema.shared_attrs_bytes_from_event``)."""
        exempt = set(entity._unrecorded_attributes)
        return {k: v for k, v in attrs.items() if k not in exempt}

    def test_the_report_alone_is_bigger_than_the_cap(self):
        """The premise — without it every assertion below is vacuous."""
        assert json_size(self._report()) > RECORDER_MAX_STATE_ATTRS_BYTES

    def test_the_diag_sensor_stays_recordable_with_a_real_report(
            self, mock_coordinator):
        mock_coordinator.data = {
            "diag_charger_control": "number entity",
            "detection_report": self._report(),
            "charger_a_control_valid": True,
            "charger_a_control_reason": "ok",
        }
        sensor = _sensor(mock_coordinator, "diag_charger_control")
        attrs = sensor.extra_state_attributes
        # The card still gets the whole thing off the live state ...
        assert len(attrs["detection_report"]["near_misses"]) == 40
        # ... and the recorder gets a set it will actually store.
        assert json_size(self._recorded(attrs, sensor)) <= RECORDER_MAX_STATE_ATTRS_BYTES

    def test_the_oracle_fires_if_the_report_is_recorded_again(
            self, mock_coordinator):
        """Vacuity twin — drop the exemption and the entity blows the cap."""
        mock_coordinator.data = {
            "diag_charger_control": "number entity",
            "detection_report": self._report(),
        }
        sensor = _sensor(mock_coordinator, "diag_charger_control")
        attrs = sensor.extra_state_attributes
        as_before = {k: v for k, v in attrs.items()
                     if k not in (sensor._unrecorded_attributes
                                  - {"detection_report"})}
        assert json_size(as_before) > RECORDER_MAX_STATE_ATTRS_BYTES

    def test_the_verdicts_beside_it_survive(self, mock_coordinator):
        """The cap is all-or-nothing: one oversize key used to take the rest.

        ``control_entities`` is itself unrecorded, but the sensor's STATE and
        its small attributes were being dropped with it.
        """
        mock_coordinator.data = {
            "diag_charger_control": "number entity",
            "detection_report": self._report(),
            "charger_a_control_valid": False,
            "charger_a_control_reason": "entity not found",
        }
        sensor = _sensor(mock_coordinator, "diag_charger_control")
        attrs = sensor.extra_state_attributes
        assert attrs["control_entities"]["charger_a_control_reason"] == (
            "entity not found")
        assert TRIMMED_KEY not in attrs, "nothing needed trimming"


@pytest.mark.unit
class TestTheAttributeBudget:
    """The backstop that makes the next forgotten exemption survivable."""

    def test_a_small_set_is_returned_untouched(self):
        attrs = {"a": 1, "b": "two", "c": [1, 2, 3]}
        assert fit_state_attributes(attrs) == attrs

    def test_an_unrecorded_giant_costs_the_cap_nothing(self):
        attrs = {"live_only": ["x" * 100] * 500, "small": 1}
        assert json_size(attrs) > RECORDER_MAX_STATE_ATTRS_BYTES
        out = fit_state_attributes(attrs, {"live_only"})
        assert out == attrs
        assert TRIMMED_KEY not in out

    def test_a_recorded_giant_is_dropped_and_said_so(self):
        attrs = {"huge": ["x" * 100] * 500, "small": 1}
        out = fit_state_attributes(attrs)
        assert "huge" not in out
        assert out["small"] == 1
        assert out[TRIMMED_KEY] == ["huge"]
        assert json_size(out) <= RECORDER_MAX_STATE_ATTRS_BYTES

    def test_the_largest_goes_first(self):
        attrs = {"big": ["x" * 100] * 500, "medium": ["y" * 10] * 50}
        out = fit_state_attributes(attrs)
        assert out[TRIMMED_KEY] == ["big"]
        assert "medium" in out

    def test_scalars_are_never_dropped(self):
        attrs = {"huge": ["x" * 100] * 500, "state": "charging", "n": 7}
        out = fit_state_attributes(attrs)
        assert out["state"] == "charging" and out["n"] == 7

    def test_an_unmeasurable_payload_is_left_alone(self):
        """Refusing to guess is the #660 rule: unmeasured is not oversize."""
        loop: dict = {"n": 1}
        loop["self"] = loop
        assert json_size(loop) is None
        out = fit_state_attributes(loop)
        assert out["n"] == 1
        assert TRIMMED_KEY not in out

    def test_a_test_double_is_sized_not_dropped(self):
        """A MagicMock serialises via ``default=str`` — small, so it stays."""
        attrs = {"weird": MagicMock(), "n": 1}
        out = fit_state_attributes(attrs)
        assert out == attrs and TRIMMED_KEY not in out

    def test_the_plan_budget_and_the_gate_share_one_budget(self):
        """Class 46: the budget is spelled once — and it is the cap MINUS the
        attributes HA lays over ours, unchanged at 15 000 bytes: the plan
        sensor's number also decides what the LIVE state carries
        (``timeline_omitted``), so a rounding rule must not move it
        (challenge record)."""
        import inspect
        from custom_components.solar_energy_management import sensor as sensor_mod
        from custom_components.solar_energy_management.consts.core import (
            RECORDER_ATTR_BUDGET_BYTES,
        )
        assert sensor_mod._PLAN_ATTR_BUDGET_BYTES == RECORDER_ATTR_BUDGET_BYTES == 15000
        assert RECORDER_ATTR_BUDGET_BYTES < RECORDER_MAX_STATE_ATTRS_BYTES
        gate_limit = inspect.signature(fit_state_attributes).parameters["limit"].default
        assert gate_limit == RECORDER_ATTR_BUDGET_BYTES

    def test_the_cap_matches_the_host(self):
        """The constant is HA's, not ours — read it back from the recorder."""
        from homeassistant.components.recorder.db_schema import (
            MAX_STATE_ATTRS_BYTES,
        )
        assert RECORDER_MAX_STATE_ATTRS_BYTES == MAX_STATE_ATTRS_BYTES


@pytest.mark.unit
class TestTheObserverSwitchIsBoundedToo:
    """The sibling platform: observer mode's WOULD map grows with the fleet."""

    def test_the_switch_declares_its_live_only_attributes(self):
        from custom_components.solar_energy_management.switch import SEMSolarSwitch
        assert "would_decisions" in SEMSolarSwitch._unrecorded_attributes
        assert "withheld_commands" in SEMSolarSwitch._unrecorded_attributes

    def test_a_huge_would_map_is_kept_live(self):
        from homeassistant.components.switch import SwitchEntityDescription
        from custom_components.solar_energy_management.switch import SEMSolarSwitch

        coordinator = MagicMock()
        coordinator._surplus_controller.observer_decisions = {
            f"dev{i}": {"would": "on", "why": "x" * 200} for i in range(200)
        }
        coordinator.observer_withheld_commands.return_value = {}
        sw = SEMSolarSwitch(
            coordinator=coordinator,
            description=SwitchEntityDescription(key="observer_mode"),
            entry_id="e",
        )
        sw._is_on = True
        attrs = sw.extra_state_attributes
        # The sim bridge reads the whole map off the live state ...
        assert len(attrs["would_decisions"]) == 200
        assert json_size(attrs) > RECORDER_MAX_STATE_ATTRS_BYTES
        # ... and the recorder is handed nothing it would refuse.
        recorded = {k: v for k, v in attrs.items()
                    if k not in SEMSolarSwitch._unrecorded_attributes}
        assert recorded == {}
        assert TRIMMED_KEY not in attrs
