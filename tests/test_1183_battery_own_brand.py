"""#1183 — a second battery was driven as the inverter's battery.

SEM picked each battery's adapter by which inverter integration was loaded,
not by the battery's own entities. In a home with a Huawei (or GoodWe)
inverter, every other battery without a power-strategy select or setpoint of
its own was built as a Huawei battery too, and its charge, sale and stop
commands went to the Huawei inverter.

Pinned here on a real Home Assistant (entity registry, device registry,
loaded config entries) and through the real ``_run_battery_pipeline`` build:

* in a home of two batteries, a battery is a brand battery only when its own
  entities belong to that brand; the other one is generic and sends nothing
  to the brand's inverter (the reported case, and its GoodWe twin);
* a home of one battery is built as before;
* no brand, two brands, or no registry answer: generic;
* a brand pin counts only for a battery whose own entities are that brand's;
* the startup self-heal upgrades the brand's own battery and leaves the
  other one alone;
* the #900 pin Repair and its #933 "still loading" answer ask the same rule.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management.coordinator.battery_adapters import (
    GenericBatteryAdapter,
    GoodWeBatteryAdapter,
    HuaweiBatteryAdapter,
    adapter_for,
    auto_brand,
    pinned_generic_brand,
    pinned_generic_pending,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
    BatteryPower,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)

LUNA_POWER = "sensor.luna_battery_power"          # b1, huawei_solar
LUNA_LIMIT = "number.luna_max_discharge"          # b1, huawei_solar
PACK2_POWER = "sensor.pack2_power"                # b2, another integration
PACK2_LIMIT = "number.pack2_max_discharge"        # b2's own limit
GW_POWER = "sensor.goodwe_battery_power"          # goodwe
GW_MODE = "select.goodwe_work_mode"


def _register(hass, platform, entity_id):
    domain, object_id = entity_id.split(".", 1)
    ent = er.async_get(hass).async_get_or_create(
        domain, platform, f"uid_{object_id}", suggested_object_id=object_id)
    assert ent.entity_id == entity_id
    return ent


def _loaded(hass, domain, state=ConfigEntryState.LOADED):
    if domain == "goodwe":
        # HA ships goodwe: a config entry would be set up for real on
        # teardown. The legacy ``hass.data`` mark is a loaded integration too.
        assert state is ConfigEntryState.LOADED
        hass.data["goodwe"] = {}
        return None
    entry = MockConfigEntry(domain=domain, title=domain)
    entry.add_to_hass(hass)
    entry.mock_state(hass, state)
    return entry


@pytest.fixture
def home(hass):
    """A Huawei inverter with its LUNA (b1) and a second battery (b2) whose
    sensor and limit belong to another integration."""
    huawei = _loaded(hass, "huawei_solar")
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=huawei.entry_id,
        identifiers={("huawei_solar", "HV1/connected_energy_storage")})
    _register(hass, "huawei_solar", LUNA_POWER)
    _register(hass, "huawei_solar", LUNA_LIMIT)
    _register(hass, "modbus", PACK2_POWER)
    _register(hass, "modbus", PACK2_LIMIT)
    return SimpleNamespace(hass=hass, huawei=huawei, device_id=dev.id)


def _ctx(own, *, fleet=2, **extra):
    return {"battery_fleet_size": fleet, "battery_own_entity_ids": tuple(own),
            "battery_max_discharge_power": 5000.0, **extra}


# ─────────────────────────────────────────────────────────────────
# 1. The factory: the brand of the battery, not of the install
# ─────────────────────────────────────────────────────────────────

class TestTheBatteryOwnBrand:
    async def test_the_second_battery_is_generic(self, home):
        """The reported case: b2's own sensor and limit are not Huawei's."""
        a = adapter_for(home.hass, _ctx((PACK2_POWER, PACK2_LIMIT)))
        assert type(a) is GenericBatteryAdapter

    async def test_the_inverter_battery_stays_huawei(self, home):
        a = adapter_for(home.hass, _ctx((LUNA_POWER,)))
        assert type(a) is HuaweiBatteryAdapter
        assert a._inverter_device_id == home.device_id

    async def test_one_own_brand_entity_is_enough(self, home):
        """A template power sensor beside the brand's own limit number."""
        a = adapter_for(home.hass, _ctx((PACK2_POWER, LUNA_LIMIT)))
        assert type(a) is HuaweiBatteryAdapter

    async def test_a_home_of_one_battery_is_built_as_before(self, home):
        assert type(adapter_for(home.hass, {})) is HuaweiBatteryAdapter
        assert type(adapter_for(home.hass, _ctx((PACK2_POWER,), fleet=1))) \
            is HuaweiBatteryAdapter

    async def test_no_own_entities_in_a_fleet_is_generic(self, home):
        assert type(adapter_for(home.hass, _ctx(()))) is GenericBatteryAdapter
        assert type(adapter_for(home.hass, {"battery_fleet_size": 2})) \
            is GenericBatteryAdapter

    async def test_an_entity_the_registry_does_not_know_is_no_brand(self, home):
        a = adapter_for(home.hass, _ctx(("sensor.yaml_template_power",)))
        assert type(a) is GenericBatteryAdapter

    async def test_two_brands_on_one_battery_is_generic(self, home):
        _loaded(home.hass, "goodwe")
        _register(home.hass, "goodwe", GW_POWER)
        a = adapter_for(home.hass, _ctx((LUNA_POWER, GW_POWER)))
        assert type(a) is GenericBatteryAdapter

    async def test_a_brand_not_loaded_yet_is_generic_for_now(self, hass):
        _loaded(hass, "huawei_solar", ConfigEntryState.SETUP_RETRY)
        _register(hass, "huawei_solar", LUNA_POWER)
        assert type(adapter_for(hass, _ctx((LUNA_POWER,)))) is GenericBatteryAdapter
        assert auto_brand(hass, _ctx((LUNA_POWER,))) is None

    async def test_the_goodwe_twin(self, hass):
        _loaded(hass, "goodwe")
        _register(hass, "goodwe", GW_POWER)
        _register(hass, "modbus", PACK2_POWER)
        assert type(adapter_for(hass, _ctx((GW_POWER,)))) is GoodWeBatteryAdapter
        assert type(adapter_for(hass, _ctx((PACK2_POWER,)))) is GenericBatteryAdapter
        assert type(adapter_for(hass, {})) is GoodWeBatteryAdapter

    def test_no_registry_answer_is_no_brand(self):
        """A host that cannot answer is no brand — the loaded integration
        alone never makes a fleet battery the brand's."""
        h = SimpleNamespace(data={"huawei_solar": object()})
        assert type(adapter_for(h, _ctx((LUNA_POWER,)))) is GenericBatteryAdapter
        assert type(adapter_for(h, {})) is HuaweiBatteryAdapter

    async def test_an_own_control_surface_still_wins(self, home):
        """#531 stands: a strategy select keeps a battery generic even
        beside the brand's own entity."""
        a = adapter_for(home.hass, _ctx(
            (LUNA_POWER,), battery_strategy_control_entity="select.x"))
        assert type(a) is GenericBatteryAdapter


class TestABrandPin:
    @pytest.mark.parametrize("pin", ["huawei", "HUAWEI"])
    async def test_a_huawei_pin_drives_only_huawei_batteries(self, home, pin):
        b1 = adapter_for(home.hass, _ctx((LUNA_POWER,), battery_charge_platform=pin))
        b2 = adapter_for(home.hass, _ctx((PACK2_POWER, PACK2_LIMIT),
                                         battery_charge_platform=pin))
        assert type(b1) is HuaweiBatteryAdapter
        assert type(b2) is GenericBatteryAdapter

    async def test_a_goodwe_pin_drives_only_goodwe_batteries(self, hass):
        _register(hass, "goodwe", GW_POWER)
        _register(hass, "modbus", PACK2_POWER)
        cfg = {"battery_charge_platform": "goodwe"}
        assert type(adapter_for(hass, _ctx((GW_POWER,), **cfg))) is GoodWeBatteryAdapter
        assert type(adapter_for(hass, _ctx((PACK2_POWER,), **cfg))) is GenericBatteryAdapter

    async def test_a_pin_on_one_battery_is_built_as_before(self, hass):
        assert type(adapter_for(hass, {"battery_charge_platform": "huawei"})) \
            is HuaweiBatteryAdapter
        assert type(adapter_for(hass, {"battery_charge_platform": "goodwe"})) \
            is GoodWeBatteryAdapter


class TestThePinRepairAsksTheSameRule:
    async def test_pinned_generic_names_only_the_brand_battery(self, home):
        pin = {"battery_charge_platform": "generic"}
        assert pinned_generic_brand(home.hass, _ctx((LUNA_POWER,), **pin)) == "huawei"
        assert pinned_generic_brand(home.hass, _ctx((PACK2_POWER,), **pin)) is None
        assert pinned_generic_brand(home.hass, pin) == "huawei"

    async def test_still_loading_is_asked_of_the_battery_own_brand(self, hass):
        _loaded(hass, "huawei_solar", ConfigEntryState.SETUP_RETRY)
        _register(hass, "huawei_solar", LUNA_POWER)
        _register(hass, "modbus", PACK2_POWER)
        pin = {"battery_charge_platform": "generic"}
        assert pinned_generic_pending(hass, _ctx((LUNA_POWER,), **pin)) is True
        assert pinned_generic_pending(hass, _ctx((PACK2_POWER,), **pin)) is False
        assert pinned_generic_pending(hass, pin) is True


# ─────────────────────────────────────────────────────────────────
# 2. Each battery's own entities, from the coordinator
# ─────────────────────────────────────────────────────────────────

def _ed():
    return EnergyDashboardConfig(
        battery_power_list=[LUNA_POWER, PACK2_POWER],
        battery_power_pairs=[("sensor.pack3_discharge", "sensor.pack3_charge")],
        battery_unit_counters={
            LUNA_POWER: ("sensor.luna_charge_kwh", "sensor.luna_discharge_kwh"),
            PACK2_POWER: ("sensor.pack2_in_kwh", None),
        })


def _coord_stub(hass, config, ed=None):
    stub = MagicMock()
    stub.hass = hass
    stub.config = dict(config)
    stub.config_entry = None
    stub.battery_control_slugs = ("b1", "b2")
    stub._energy_dashboard_config = ed if ed is not None else _ed()
    for name in ("_battery_adapter_context", "_per_battery_config",
                 "_battery_own_entities", "_charge_target_hold",
                 "_forced_charge_record"):
        setattr(stub, name, getattr(SEMCoordinator, name).__get__(stub))
    return stub


class TestOwnEntities:
    def test_each_battery_gets_its_own(self):
        stub = _coord_stub(None, {
            "battery_discharge_control_entities": [LUNA_LIMIT, PACK2_LIMIT],
            "battery_discharge_control_entity": "number.shared_limit",
        })
        assert stub._battery_own_entities(0) == (
            LUNA_POWER, "sensor.luna_charge_kwh", "sensor.luna_discharge_kwh",
            LUNA_LIMIT)
        assert stub._battery_own_entities(1) == (
            PACK2_POWER, "sensor.pack2_in_kwh", PACK2_LIMIT)

    def test_a_pair_brings_both_sensors(self):
        stub = _coord_stub(None, {})
        assert stub._battery_own_entities(2) == (
            "sensor.pack3_charge", "sensor.pack3_discharge")

    def test_never_the_shared_key_nor_a_sibling_slot(self):
        stub = _coord_stub(None, {
            "battery_discharge_control_entities": [LUNA_LIMIT, ""],
            "battery_discharge_control_entity": LUNA_LIMIT,
        })
        assert LUNA_LIMIT not in stub._battery_own_entities(1)

    def test_no_dashboard_is_no_unit(self):
        stub = _coord_stub(None, {}, ed=SimpleNamespace())
        assert stub._battery_own_entities(0) == ()

    async def test_the_context_carries_them_in_a_fleet_only(self, hass):
        stub = _coord_stub(hass, {})
        ctx = stub._battery_adapter_context("b2", 1, 2)
        assert ctx["battery_fleet_size"] == 2
        assert ctx["battery_own_entity_ids"][0] == PACK2_POWER
        one = stub._battery_adapter_context("primary", 0, 1)
        assert one["battery_fleet_size"] == 1
        assert "battery_own_entity_ids" not in one


# ─────────────────────────────────────────────────────────────────
# 3. Through the real battery pipeline
# ─────────────────────────────────────────────────────────────────

def _services(hass):
    calls: list = []

    async def _record(call):
        calls.append((call.domain, call.service, dict(call.data)))

    for domain, service in (
        ("huawei_solar", "forcible_charge"),
        ("huawei_solar", "forcible_charge_soc"),
        ("huawei_solar", "forcible_discharge_soc"),
        ("huawei_solar", "stop_forcible_charge"),
        ("number", "set_value"),
        ("select", "select_option"),
        ("switch", "turn_on"),
        ("switch", "turn_off"),
    ):
        hass.services.async_register(domain, service, _record)
    return calls


def _pipeline_stub(home, *, cached=None):
    stub = _coord_stub(home.hass, {
        "battery_discharge_control_entities": ["", PACK2_LIMIT],
        "battery_max_discharge_power": 5000.0,
        # a device id the user typed: every Huawei-built battery reads it
        "inverter_device_id": home.device_id,
    })
    stub.setup_presence = {m: Presence.PRESENT for m in Module}
    stub._observer_mode = False
    stub._battery_charge_scheduler.enabled = False
    stub._vpp_apply_battery_override = lambda pbc: {}
    stub._battery_adapters = dict(cached or {})
    stub._last_battery_decisions = {}
    stub._apply_export_decision = AsyncMock()
    stub._finish_manual_battery_modes = lambda *a, **k: None
    stub._arbitrage_enabled = lambda n: False
    stub._energy_plan_actuation = False
    stub._cycle_fleet_state = None
    stub._check_battery_platform_pin = lambda *a, **k: None
    stub.external_yielding = lambda key: False
    return stub


def _power():
    return SimpleNamespace(
        inputs_degraded=False,
        batteries={b: BatteryPower(battery_id=b, power_w=0.0, soc_pct=60.0,
                                   power_read=True) for b in ("b1", "b2")},
        battery_soc=60.0, battery_power=0.0, battery_soc_known=True,
        battery_soc_unavailable=False, battery_power_unavailable=False,
        battery_power_read=True)


async def _cycle(monkeypatch, stub, wants):
    from custom_components.solar_energy_management.coordinator import (
        decide_battery as db,
    )
    asked = []

    def _decide(view):
        asked.append(view.runtime.battery_id)
        return wants[view.runtime.battery_id]

    monkeypatch.setattr(db, "decide_battery", _decide)
    await SEMCoordinator._run_battery_pipeline(
        stub, _power(), SimpleNamespace(), "idle")
    assert asked == ["b1", "b2"], "the pipeline decided every battery"


def _normal(bid):
    return BatteryDecision(battery_id=bid, intent=BatteryIntent.NORMAL,
                           reason="default discharge")


_B2_COMMANDS = {
    "charge": BatteryDecision(
        battery_id="b2", intent=BatteryIntent.FORCE_CHARGE, target_soc=100.0,
        charge_power_w=3000.0, duration_min=60, reason="charge"),
    "sale": BatteryDecision(
        battery_id="b2", intent=BatteryIntent.FORCE_DISCHARGE,
        discharge_power_w=3000.0, floor_soc=20.0, reason="manual sell"),
}


class TestThroughThePipeline:
    @pytest.mark.parametrize("command", sorted(_B2_COMMANDS))
    async def test_the_second_battery_sends_nothing_to_the_inverter(
            self, home, monkeypatch, command):
        calls = _services(home.hass)
        stub = _pipeline_stub(home)
        await _cycle(monkeypatch, stub,
                     {"b1": _normal("b1"), "b2": _B2_COMMANDS[command]})
        await home.hass.async_block_till_done()
        assert [c for c in calls if c[0] == "huawei_solar"] == []
        assert type(stub._battery_adapters["b1"]) is HuaweiBatteryAdapter
        assert type(stub._battery_adapters["b2"]) is GenericBatteryAdapter

    async def test_the_inverter_battery_still_charges_through_it(
            self, home, monkeypatch):
        calls = _services(home.hass)
        stub = _pipeline_stub(home)
        charge = BatteryDecision(
            battery_id="b1", intent=BatteryIntent.FORCE_CHARGE, target_soc=100.0,
            charge_power_w=3000.0, duration_min=60, reason="charge")
        await _cycle(monkeypatch, stub, {"b1": charge, "b2": _normal("b2")})
        await home.hass.async_block_till_done()
        sent = [c for c in calls if c[0] == "huawei_solar"]
        assert [c[1] for c in sent] == ["forcible_charge_soc"]
        assert sent[0][2]["device_id"] == home.device_id

    async def test_the_self_heal_upgrades_only_the_brand_battery(
            self, home, monkeypatch):
        """Both built generic before huawei_solar loaded: the next cycle
        makes b1 the Huawei battery and leaves b2 generic."""
        _services(home.hass)
        early = {bid: GenericBatteryAdapter(home.hass, {}) for bid in ("b1", "b2")}
        stub = _pipeline_stub(home, cached=early)
        await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _normal("b2")})
        assert type(stub._battery_adapters["b1"]) is HuaweiBatteryAdapter
        assert stub._battery_adapters["b2"] is early["b2"]


# ─────────────────────────────────────────────────────────────────
# 4. One door: the brand of a battery is decided in one place
# ─────────────────────────────────────────────────────────────────

class TestOneDoor:
    """A new reader that asks "is the brand loaded?" for a battery would
    read the install's brand as the battery's again. The package may build
    a brand adapter only in ``adapter_for``, and may ask a brand
    integration's load state only in the helpers that ask the battery's own
    brands first (and in the Huawei adapter, about its own integration)."""

    ALLOWED_LOADED = {
        ("coordinator/battery_adapters/__init__.py", "auto_brand"),
        ("coordinator/battery_adapters/__init__.py", "pinned_generic_pending"),
        ("coordinator/battery_adapters/huawei.py", "_maybe_clear_startup_orphan"),
    }
    BRAND_ADAPTERS = {"HuaweiBatteryAdapter", "GoodWeBatteryAdapter"}

    @staticmethod
    def _calls():
        import ast
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(("tests/", "scripts/", "tools/")):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call):
                        f = node.func
                        name = getattr(f, "id", None) or getattr(f, "attr", None)
                        yield rel, fn.name, name

    def test_brand_adapters_are_built_in_adapter_for_only(self):
        seen = [(rel, fn) for rel, fn, name in self._calls()
                if name in self.BRAND_ADAPTERS]
        assert seen, "the walker found no brand adapter build"
        assert {fn for _rel, fn in seen} == {"adapter_for"}, seen

    def test_the_load_state_is_asked_where_the_own_brand_is_asked(self):
        seen = {(rel, fn) for rel, fn, name in self._calls()
                if name == "_integration_loaded"}
        assert seen, "the walker found no load-state question"
        assert seen <= self.ALLOWED_LOADED, seen - self.ALLOWED_LOADED


# ─────────────────────────────────────────────────────────────────
# 5. The export cut still goes to the inverter's battery (review)
# ─────────────────────────────────────────────────────────────────

class TestTheExportPick:
    """Before #1183 a non-Huawei b1 was built as Huawei and so could cut the
    inverter's export. Now it is generic, and the generic adapter overrides
    the export verb with nothing to write: listed first, it took every cut
    and refused it. The pick asks ``export_control_wired``."""

    def _fake(self, ads):
        return SimpleNamespace(_battery_adapters=ads,
                               _primary_battery_adapter=lambda: next(iter(ads.values())))

    async def test_a_generic_battery_listed_first_does_not_take_the_cut(self, home):
        ads = {"b1": adapter_for(home.hass, _ctx((PACK2_POWER,))),
               "b2": adapter_for(home.hass, _ctx((LUNA_POWER,)))}
        assert type(ads["b1"]) is GenericBatteryAdapter
        assert SEMCoordinator._export_control_adapter(self._fake(ads)) is ads["b2"]

    async def test_a_generic_battery_with_its_own_export_number_can(self, home):
        ads = {"b1": adapter_for(home.hass, _ctx(
                   (PACK2_POWER,), export_limit_entity="number.export_cap")),
               "b2": adapter_for(home.hass, _ctx((LUNA_POWER,)))}
        assert SEMCoordinator._export_control_adapter(self._fake(ads)) is ads["b1"]

    def test_who_can_cut(self):
        h = MagicMock()
        assert GenericBatteryAdapter(h, {}).export_control_wired() is False
        assert GenericBatteryAdapter(h, {
            "export_limit_entity": "sensor.export_cap"}).export_control_wired() is False
        assert GenericBatteryAdapter(h, {
            "export_limit_entity": "number.export_cap"}).export_control_wired() is True
        assert HuaweiBatteryAdapter(h, {
            "inverter_device_id": "d"}).export_control_wired() is True
        assert GoodWeBatteryAdapter(h, {}).export_control_wired() is False
