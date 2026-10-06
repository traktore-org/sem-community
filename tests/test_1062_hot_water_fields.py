"""#1062 — the hot water settings do what they say, and only those are shown.

lostcontrol (#1059) found two Configuration-tab fields that nothing read:
"Max temperature" ("SEM never activates above this") and "Minimum
temperature" ("below this, SEM force-heats from any source"). #92 had made
the solar target the ceiling on purpose; the two fields came back on the card
in 1.7.2-beta.2 "config-only for now" and were never wired. The value reached
the controller and stopped at a log line and the diagnostics.

Pinned here:
- a running SWITCH boiler stops at its target (the target gate refused only a
  start), through the real surplus pass; a setpoint tank is left to the
  setpoint SEM wrote;
- the Control-tab comfort band reads the boiler's own thermometer when none is
  picked — the card says "device's own thermometer", and without it "Run now
  past" never forced a boiler;
- the two dead fields are gone: no entity, no card row, no published value;
- the guard: every device setting set from the constructor has a reader that
  DECIDES something — not only a log line, ``to_dict`` or a published
  ``*SensorData`` field.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)

ROOT = Path(__file__).resolve().parent.parent


class _Hass:
    """Just enough Home Assistant: a state table, and services that move a
    switch the way the real one would."""

    def __init__(self, unit: str = "°C"):
        self._states: dict = {}
        self.config = SimpleNamespace(units=SimpleNamespace(temperature_unit=unit))
        self.states = MagicMock()
        self.states.get = self._states.get
        self.states.is_state = lambda eid, v: (
            eid in self._states and self._states[eid].state == v)
        self.services = MagicMock()
        self.services.async_call = AsyncMock(side_effect=self._call)
        self.data = {}

    def set(self, entity_id, state, **attributes):
        self._states[entity_id] = SimpleNamespace(
            entity_id=entity_id, state=str(state), attributes=attributes)

    async def _call(self, domain, service, data=None, **_kw):
        eid = (data or {}).get("entity_id")
        if domain in ("homeassistant", "switch", "input_boolean") and eid:
            if service == "turn_on":
                self.set(eid, "on")
            elif service == "turn_off":
                self.set(eid, "off")

    def calls(self, service, entity_id="switch.boiler"):
        return [c for c in self.services.async_call.await_args_list
                if c.args[1] == service
                and (c.args[2] if len(c.args) > 2 else {}).get("entity_id") == entity_id]


def _boiler(hass, *, entity="switch.boiler", sensor="sensor.boiler_temp",
            solar_target=55.0, **kw):
    return HotWaterController(
        hass=hass, entity_id=entity, temperature_entity_id=sensor,
        solar_target_temp=solar_target, rated_power=2000.0, **kw)


# ── a running switch boiler stops at its target ───────────────────────────

class TestSwitchBoilerStopsAtTarget:
    def test_at_the_target_is_the_stop(self):
        hass = _Hass()
        dev = _boiler(hass)
        hass.set("sensor.boiler_temp", "55.0")
        assert dev.stop_condition_met is True
        hass.set("sensor.boiler_temp", "54.9")
        assert dev.stop_condition_met is False

    def test_no_reading_is_not_a_hot_tank(self):
        """A sensor that reads nothing must not stop the boiler: absence of a
        reading is not a reading. (The start gate still refuses a start.)"""
        hass = _Hass()
        dev = _boiler(hass)
        hass.set("sensor.boiler_temp", "unavailable")
        assert dev.stop_condition_met is False
        no_sensor = _boiler(hass, sensor=None)
        assert no_sensor.stop_condition_met is False

    @pytest.mark.parametrize("domain", ["water_heater", "climate"])
    def test_a_setpoint_tank_is_left_to_its_setpoint(self, domain):
        hass = _Hass()
        dev = _boiler(hass, entity=f"{domain}.tank", sensor=None)
        hass.set(f"{domain}.tank", "heat", current_temperature=70.0,
                 temperature=55.0)
        assert dev.stop_condition_met is False

    def test_the_legionella_cycle_is_not_cut_at_the_solar_target(self):
        hass = _Hass()
        dev = _boiler(hass)
        dev._legionella_cycle_active = True
        hass.set("sensor.boiler_temp", "62.0")
        assert dev.stop_condition_met is False

    def test_the_vacation_surplus_dump_stops_at_the_minimum(self):
        hass = _Hass()
        dev = _boiler(hass, min_temperature=40.0)
        dev.vacation = True
        dev.vacation_dhw_surplus = True
        hass.set("sensor.boiler_temp", "41.0")
        assert dev.stop_condition_met is True
        hass.set("sensor.boiler_temp", "39.0")
        assert dev.stop_condition_met is False

    def test_an_external_stop_still_counts(self):
        hass = _Hass()
        dev = _boiler(hass)
        hass.set("sensor.boiler_temp", "30.0")
        dev.stop_entity, dev.stop_at = "sensor.tank_top", 50.0
        hass.set("sensor.tank_top", "51")
        assert dev.stop_condition_met is True


@pytest.mark.asyncio
class TestTheSurplusPassStopsIt:
    """Through the real ``SurplusController.update``: the boiler starts below
    its target on surplus, keeps running below it, and is switched off when
    the water reaches it — with the sun still shining."""

    async def _running(self, hass, dev):
        sc = SurplusController(hass)
        sc.register_device(dev)
        hass.set("switch.boiler", "off")
        hass.set("sensor.boiler_temp", "50.0")
        await sc.update(5000.0)
        assert dev.is_active, "the boiler should start below its target"
        assert hass.calls("turn_on")
        # past the minimum run time
        dev._last_activated = datetime.now() - timedelta(hours=1)
        dev._status.last_activated = dev._last_activated
        return sc

    async def test_below_the_target_it_keeps_running(self):
        hass = _Hass()
        dev = _boiler(hass)
        sc = await self._running(hass, dev)
        hass.set("sensor.boiler_temp", "54.5")
        await sc.update(5000.0)
        assert dev.is_active
        assert not hass.calls("turn_off")

    async def test_at_the_target_it_is_switched_off(self):
        hass = _Hass()
        dev = _boiler(hass)
        sc = await self._running(hass, dev)
        hass.set("sensor.boiler_temp", "55.2")
        await sc.update(5000.0)
        assert hass.calls("turn_off")
        assert not dev.is_active
        # …and it does not start again while the water is still hot.
        dev._last_deactivated = datetime.now() - timedelta(hours=1)
        await sc.update(5000.0)
        assert not dev.is_active

    async def test_a_banked_band_does_not_cut_the_legionella_cycle(self):
        """The band reads the boiler's own sensor now, so it can read
        "banked" above Keep at + Bank by — far below the disinfection target.
        A cycle cut there is never started again: the tank would sit short of
        the target with the cycle flag set for good."""
        hass = _Hass()
        dev = _boiler(hass)
        dev.comfort_target, dev.comfort_offset, dev.comfort_limit = 50.0, 3.0, 36.0
        sc = await self._running(hass, dev)
        dev._legionella_cycle_active = True
        hass.set("sensor.boiler_temp", "58.0")
        assert dev.comfort_state == "banked"
        await sc.update(5000.0)
        assert dev.is_active
        assert not hass.calls("turn_off")

    async def test_the_solar_target_does_not_cut_the_legionella_cycle(self):
        hass = _Hass()
        dev = _boiler(hass)
        sc = await self._running(hass, dev)
        dev._legionella_cycle_active = True
        hass.set("sensor.boiler_temp", "60.0")
        await sc.update(5000.0)
        assert dev.is_active

    async def test_a_stop_entity_still_ends_the_cycle_as_before(self):
        """A stop the USER set is not SEM's to overrule — unchanged."""
        hass = _Hass()
        dev = _boiler(hass)
        sc = await self._running(hass, dev)
        dev._legionella_cycle_active = True
        dev.stop_entity, dev.stop_at = "sensor.tank_top", 70.0
        hass.set("sensor.tank_top", "75")
        hass.set("sensor.boiler_temp", "62.0")
        await sc.update(5000.0)
        assert not dev.is_active

    async def test_it_starts_again_once_the_water_has_cooled(self):
        hass = _Hass()
        dev = _boiler(hass)
        sc = await self._running(hass, dev)
        hass.set("sensor.boiler_temp", "55.2")
        await sc.update(5000.0)
        assert not dev.is_active
        dev._last_deactivated = datetime.now() - timedelta(hours=1)
        hass.set("sensor.boiler_temp", "51.0")
        await sc.update(5000.0)
        assert dev.is_active


# ── the comfort band reads the boiler's own thermometer ───────────────────

class TestComfortBandReadsTheBoiler:
    def _band(self, dev, target=50.0, offset=3.0, limit=36.0):
        dev.comfort_target, dev.comfort_offset, dev.comfort_limit = target, offset, limit
        return dev

    def test_run_now_past_forces_from_the_config_tab_sensor(self):
        hass = _Hass()
        dev = self._band(_boiler(hass))
        hass.set("sensor.boiler_temp", "35.0")
        assert dev.comfort_state == "forced"
        assert dev.has_runtime_deficit is True
        hass.set("sensor.boiler_temp", "45.0")
        assert dev.comfort_state == "willing"
        hass.set("sensor.boiler_temp", "53.0")
        assert dev.comfort_state == "banked"
        assert dev.stop_condition_met is True

    def test_a_water_heater_reads_its_own_current_temperature(self):
        hass = _Hass()
        dev = self._band(_boiler(hass, entity="water_heater.tank", sensor=None))
        hass.set("water_heater.tank", "eco", current_temperature=34.0,
                 temperature=50.0)
        assert dev._comfort_reading() == 34.0
        assert dev.comfort_state == "forced"

    def test_fahrenheit_readings_are_compared_in_celsius(self):
        hass = _Hass(unit="°F")
        dev = self._band(_boiler(hass, entity="water_heater.tank", sensor=None),
                         target=122.0, offset=5.4, limit=96.8)  # 50 / 3 / 36 °C
        hass.set("water_heater.tank", "eco", current_temperature=95.0)  # 35 °C
        assert dev._comfort_reading() == pytest.approx(35.0)
        assert dev.comfort_state == "forced"
        hass2 = _Hass()
        dev2 = self._band(_boiler(hass2))
        hass2.set("sensor.boiler_temp", "131", unit_of_measurement="°F")  # 55 °C
        assert dev2._comfort_reading() == pytest.approx(55.0)
        assert dev2.comfort_state == "banked"

    def test_a_picked_thermometer_still_wins(self):
        hass = _Hass()
        dev = self._band(_boiler(hass))
        dev.comfort_entity = "sensor.tank_bottom"
        hass.set("sensor.boiler_temp", "35.0")
        hass.set("sensor.tank_bottom", "45.0")
        assert dev._comfort_reading() == 45.0
        assert dev.comfort_state == "willing"

    def test_vacation_turns_the_band_off(self):
        """#594: no comfort heating while away — no force below the limit, no
        planned banking block, no banked stop."""
        hass = _Hass()
        dev = self._band(_boiler(hass))
        hass.set("sensor.boiler_temp", "35.0")
        assert dev.comfort_state == "forced"
        dev.vacation = True
        assert dev.comfort_state == "disengaged"
        assert dev.has_runtime_deficit is False
        # banked at 53 °C (Keep at 50 + Bank by 3) — but not while away
        hass.set("sensor.boiler_temp", "53.5")
        assert dev.stop_condition_met is False
        dev.vacation = False
        assert dev.stop_condition_met is True

    def test_no_band_set_changes_nothing(self):
        """Zero config: a boiler with a sensor and no Comfort values is
        exactly as before — no force, no stop below the solar target."""
        hass = _Hass()
        dev = _boiler(hass)
        hass.set("sensor.boiler_temp", "20.0")
        assert dev.comfort_state == "disengaged"
        assert dev.has_runtime_deficit is False
        assert dev.stop_condition_met is False


# ── the two dead fields are gone ──────────────────────────────────────────

class TestTheDeadFieldsAreGone:
    def test_a_cold_tank_is_not_forced_by_the_minimum(self):
        """The minimum never started heating; with the card row gone, nothing
        may make it look as if it did."""
        hass = _Hass()
        dev = _boiler(hass, min_temperature=40.0)
        hass.set("sensor.boiler_temp", "30.0")
        assert dev.has_runtime_deficit is False
        assert dev.needs_offpeak_activation is False

    def test_no_max_temperature_entity_or_value(self):
        from custom_components.solar_energy_management.number import NUMBER_TYPES
        assert "hot_water_max_temperature" not in {d.key for d in NUMBER_TYPES}
        from custom_components.solar_energy_management.coordinator.types import (
            SEMData,
        )
        assert "hot_water_max_temperature" not in SEMData().to_dict()
        with pytest.raises(TypeError):
            HotWaterController(hass=_Hass(), max_temperature=60.0)

    def test_the_config_card_offers_no_minimum(self):
        """The card's option inventory — the same extraction the #637 routing
        guard classifies — no longer holds the minimum. (The max row was a
        stepper on the number entity, which no longer exists.)"""
        from .test_637_live_options import _card_option_keys
        options = _card_option_keys()
        assert "hot_water_legionella_target" in options  # the extraction works
        assert "hot_water_minimum_temperature" not in options

    def test_the_removed_entity_is_swept_from_the_registry(self):
        """An install that has the entity from an older version loses it on
        the next load: the number platform's stale sweep removes every key
        no description provides."""
        from custom_components.solar_energy_management import number as num
        entry = SimpleNamespace(entry_id="E1")
        stale = SimpleNamespace(domain="number", unique_id="E1_hot_water_max_temperature",
                                entity_id="number.sem_hot_water_max_temperature")
        kept = SimpleNamespace(domain="number", unique_id="E1_hot_water_solar_target",
                               entity_id="number.sem_hot_water_solar_target")
        registry = MagicMock()
        orig_get, orig_entries = num.er.async_get, num.er.async_entries_for_config_entry
        num.er.async_get = lambda _h: registry
        num.er.async_entries_for_config_entry = lambda _r, _e: [stale, kept]
        try:
            num._cleanup_stale_entities(None, entry, num.NUMBER_TYPES, "number")
        finally:
            num.er.async_get, num.er.async_entries_for_config_entry = orig_get, orig_entries
        removed = [c.args[0] for c in registry.async_remove.call_args_list]
        assert removed == ["number.sem_hot_water_max_temperature"]


# ── the guard: a device setting must reach a decision ─────────────────────

_LOGIC_ROOTS = ("coordinator", "features", "devices", "tariff", "utils", "consts")
_LOG_NAMES = {"_LOGGER", "LOGGER", "logger", "_log"}
_LOG_HELPERS = {"log_on_change"}  # utils/log_gate.py — a log line too
_DISPLAY_FUNCS = {"to_dict", "__init__", "__repr__"}

# A constructor value with no decision reader, kept on purpose. Each needs a
# reason; "it is shown somewhere" is not one.
_ALLOWED = {
    # No setting writes it: every SetpointDevice is built with the default,
    # and nothing on any screen claims a minimum setpoint does anything.
    "min_setpoint": "constructor default only — no surface promises it",
}


def _device_settings() -> dict:
    """attr → 'file:Class' for every ``self.<attr> = <uses a parameter>`` in
    a device class's ``__init__``."""
    out: dict = {}
    for path in (ROOT / "devices").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for fn in cls.body:
                if not (isinstance(fn, ast.FunctionDef) and fn.name == "__init__"):
                    continue
                params = {a.arg for a in fn.args.args + fn.args.kwonlyargs} - {"self"}
                for st in ast.walk(fn):
                    if isinstance(st, ast.Assign):
                        targets = st.targets
                    elif isinstance(st, ast.AnnAssign) and st.value is not None:
                        targets = [st.target]
                    else:
                        continue
                    used = {n.id for n in ast.walk(st.value) if isinstance(n, ast.Name)}
                    if not used & params:
                        continue
                    flat = []
                    for tg in targets:
                        flat.extend(tg.elts if isinstance(tg, ast.Tuple) else [tg])
                    for tg in flat:
                        if (isinstance(tg, ast.Attribute) and isinstance(tg.value, ast.Name)
                                and tg.value.id == "self" and not tg.attr.startswith("__")):
                            out.setdefault(tg.attr, f"{path.name}:{cls.name}")
    return out


def _is_display_call(node) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in _LOG_NAMES:
        return True
    name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
    return name.endswith("SensorData") or name in _LOG_HELPERS


def _decision_reads(attrs) -> dict:
    files = [p for r in _LOGIC_ROOTS for p in (ROOT / r).rglob("*.py")]
    files.append(ROOT / "__init__.py")
    reads = {a: [] for a in attrs}
    for path in files:
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        parent = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for node in ast.walk(tree):
            name = None
            if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                    and node.attr in reads):
                name = node.attr
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("getattr", "hasattr") and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in reads):
                name = node.args[1].value
            if name is None:
                continue
            cur, display, func = node, False, None
            while cur in parent:
                cur = parent[cur]
                if _is_display_call(cur):
                    display = True
                    break
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func = cur.name
                    break
            if display or func in _DISPLAY_FUNCS:
                continue
            reads[name].append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return reads


class TestEveryDeviceSettingReachesADecision:
    def test_the_scan_sees_the_settings(self):
        attrs = _device_settings()
        # non-vacuous: the settings this issue is about, and their siblings
        for a in ("solar_target_temp", "legionella_target_temp", "min_temperature",
                  "boost_offset", "max_setpoint", "rated_power"):
            assert a in attrs, a

    def test_a_setting_read_only_for_display_is_caught(self):
        """The rule itself: a read inside a log call, ``to_dict`` or a
        ``*SensorData(...)`` field is not a decision."""
        src = (
            "def to_dict(self):\n    return {'x': self.dead}\n"
            "def tick(self):\n    _LOGGER.info('%s', self.dead)\n"
            "    log_on_change(_LOGGER, 'k', 20, '%s', self.dead)\n"
            "    data = HotWaterSensorData(v=self.dead)\n"
            "    return self.live\n"
        )
        tree = ast.parse(src)
        parent = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        kinds = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("dead", "live"):
                cur, display, func = node, False, None
                while cur in parent:
                    cur = parent[cur]
                    if _is_display_call(cur):
                        display = True
                        break
                    if isinstance(cur, ast.FunctionDef):
                        func = cur.name
                        break
                kinds.setdefault(node.attr, []).append(
                    not display and func not in _DISPLAY_FUNCS)
        assert kinds["dead"] == [False, False, False, False]
        assert kinds["live"] == [True]

    def test_every_setting_has_a_decision_reader(self):
        attrs = _device_settings()
        reads = _decision_reads(attrs)
        dead = sorted(f"{a} ({attrs[a]})" for a, r in reads.items()
                      if not r and a not in _ALLOWED)
        assert not dead, (
            "Device settings that only a log line, to_dict or a published "
            "*SensorData field reads — a field users set and nothing acts on "
            f"(#1062): {dead}. Wire it to a decision, or remove it and its "
            "surface.")

    def test_every_allowance_is_still_needed(self):
        attrs = _device_settings()
        reads = _decision_reads(attrs)
        stale = [a for a in _ALLOWED if a in reads and reads[a]]
        gone = [a for a in _ALLOWED if a not in attrs]
        assert not stale and not gone, (stale, gone)
