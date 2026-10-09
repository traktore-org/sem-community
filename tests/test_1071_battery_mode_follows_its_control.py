"""#1071 — the battery mode and reserve that drive a battery are the ones its
control on screen shows.

A battery's mode is stored twice: the scalar ``battery_mode`` (written by the
one global ``select.sem_battery_mode``) and the ``battery_modes`` list
(written by the per-battery ``select.sem_battery_b<N>_mode``). The platforms
chose the control by the battery slugs found at setup; ``_per_battery_config``
chose the store by "is a list slot set?". So on .175 — one battery, a
leftover ``battery_modes: ['auto', 'auto']`` — the global select read
``force_charge`` while SEM ran ``auto``. The reserve number had the same split.

Now one decision (``coordinator.battery_control_slugs``, captured before the
platforms load) picks the controls AND the store the runtime reads.

Real registry + real platform setup (the ``hass`` fixture); the runtime side
is the real ``SEMCoordinator._per_battery_config`` on a test double.
"""
from __future__ import annotations

import ast
import importlib.util
import itertools
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

from custom_components.solar_energy_management import number, select  # noqa: E402
from custom_components.solar_energy_management.const import DOMAIN  # noqa: E402
from custom_components.solar_energy_management.coordinator.coordinator import (  # noqa: E402
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.install_modules import (  # noqa: E402
    Module, Presence,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALL_PRESENT = {m: Presence.PRESENT for m in Module}


def _entry(hass, options):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=dict(options),
                            title="SEM #1071")
    entry.add_to_hass(hass)
    return entry


def _coordinator(hass, entry, slugs):
    """A coordinator double carrying the CAPTURED battery controls. Its
    discovery path is made to answer the opposite, so a platform that ignored
    the capture would build the wrong controls and fail the test."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.config_entry = entry
    coordinator.hass = hass
    coordinator.setup_presence = ALL_PRESENT
    coordinator.config = {**entry.data, **entry.options}
    coordinator.battery_control_slugs = slugs
    coordinator._sensor_reader._energy_dashboard_config.battery_power_list = (
        [] if slugs else ["sensor.b1_power", "sensor.b2_power"])
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return coordinator


async def _controls(hass, entry):
    """{key: entity} for the battery mode selects and reserve numbers the
    REAL platform setup builds."""
    added: list = []
    await select.async_setup_entry(hass, entry, added.extend)
    await number.async_setup_entry(hass, entry, added.extend)
    out = {}
    for ent in added:
        key = ent.entity_description.key
        if key.startswith("battery_") and (
                key.endswith("_mode") or key.endswith("reserve_soc")):
            ent.hass = hass
            ent.async_write_ha_state = lambda: None
            out[key] = ent
    return out


def _runtime(coordinator, idx, count):
    """What decide_battery reads for battery ``idx`` this cycle — the mode
    the way it reads it, the reserve through the same helper."""
    from custom_components.solar_energy_management.consts.battery_modes import (
        reserve_soc_of,
    )
    cfg = SEMCoordinator._per_battery_config(coordinator, idx, count)
    mode = str(cfg.get("battery_mode", "auto") or "auto").lower()
    return mode, reserve_soc_of(cfg)


# ── The .175 case ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_global_select_drives_a_one_battery_install_with_a_leftover_list(hass):
    entry = _entry(hass, {"battery_mode": "auto", "battery_modes": ["auto", "auto"]})
    coordinator = _coordinator(hass, entry, ())
    controls = await _controls(hass, entry)
    assert set(controls) == {"battery_mode", "battery_reserve_soc"}

    await controls["battery_mode"].async_select_option("force_charge")

    assert entry.options["battery_mode"] == "force_charge"
    assert _runtime(coordinator, 0, 1)[0] == "force_charge"


@pytest.mark.asyncio
async def test_the_global_reserve_number_drives_it_too(hass):
    entry = _entry(hass, {"battery_reserve_soc": 20, "battery_reserve_socs": [50, 50]})
    coordinator = _coordinator(hass, entry, ())
    controls = await _controls(hass, entry)

    await controls["battery_reserve_soc"].async_set_native_value(35.0)

    assert _runtime(coordinator, 0, 1)[1] == 35.0


# ── The two places the live count and the controls disagree ────────────────

def test_per_battery_controls_never_read_the_global_key_on_a_one_battery_cycle():
    # A two-battery install whose Energy Dashboard is not read yet (cold
    # start, #274) runs with ONE synthetic battery. Its b1 select still owns
    # it, and a stale global force_discharge must not drive it (#531).
    fake = SimpleNamespace(
        config={"battery_mode": "force_discharge", "battery_modes": ["self_consumption"]},
        battery_control_slugs=("b1", "b2"))
    assert _runtime(fake, 0, 1)[0] == "self_consumption"
    fake.config = {"battery_mode": "force_discharge"}
    assert _runtime(fake, 0, 1)[0] == "auto"


def test_the_global_select_sets_every_battery_when_two_are_live():
    # The platforms built the one global select (the batteries were not
    # known at setup); two batteries are live now. That select is the only
    # mode control on screen, so it sets every battery.
    fake = SimpleNamespace(
        config={"battery_mode": "force_charge", "battery_modes": ["off", "off"]},
        battery_control_slugs=())
    assert _runtime(fake, 0, 2)[0] == "force_charge"
    assert _runtime(fake, 1, 2)[0] == "force_charge"


# ── Oracle: every control shows what drives the batteries it covers ────────

_LISTS = (None, ["force_discharge"], ["self_consumption", None], ["off", "force_charge"])
_SCALARS = (None, "force_charge")


@pytest.mark.asyncio
@pytest.mark.parametrize("slugs", [(), ("b1", "b2")])
@pytest.mark.parametrize("count", [1, 2])
async def test_every_mode_control_shows_what_drives_its_batteries(hass, slugs, count):
    checked = 0
    for modes, scalar in itertools.product(_LISTS, _SCALARS):
        options = {}
        if modes is not None:
            options["battery_modes"] = modes
        if scalar is not None:
            options["battery_mode"] = scalar
        entry = _entry(hass, options)
        coordinator = _coordinator(hass, entry, slugs)
        controls = await _controls(hass, entry)
        if slugs:
            covers = {f"battery_{bid}_mode": [i] for i, bid in enumerate(slugs)
                      if i < count}
        else:
            covers = {"battery_mode": list(range(count))}
        for key, batteries in covers.items():
            shown = controls[key].current_option
            for idx in batteries:
                assert _runtime(coordinator, idx, count)[0] == shown, (
                    f"{key} shows {shown!r} but battery {idx} runs "
                    f"{_runtime(coordinator, idx, count)[0]!r} "
                    f"(slugs={slugs}, count={count}, options={options})")
                checked += 1
    assert checked >= len(_LISTS) * len(_SCALARS)


@pytest.mark.asyncio
@pytest.mark.parametrize("slugs", [(), ("b1", "b2")])
async def test_every_set_reserve_control_shows_what_drives_its_batteries(hass, slugs):
    entry = _entry(hass, {"battery_reserve_soc": 40, "battery_reserve_socs": [30, 45]})
    coordinator = _coordinator(hass, entry, slugs)
    controls = await _controls(hass, entry)
    if slugs:
        covers = {"battery_b1_reserve_soc": [0], "battery_b2_reserve_soc": [1]}
    else:
        covers = {"battery_reserve_soc": [0, 1]}
    for key, batteries in covers.items():
        for idx in batteries:
            assert _runtime(coordinator, idx, 2)[1] == controls[key].native_value


@pytest.mark.asyncio
@pytest.mark.parametrize("slugs", [(), ("b1", "b2")])
async def test_an_unset_reserve_shows_what_drives_the_battery(hass, slugs):
    # The number showed 20 % (DEFAULT_BATTERY_RESERVE_SOC) and a manual sell
    # used 0 %. A leftover list must not decide it on the global number
    # either (the .175 shape: battery_reserve_socs [50, 50]).
    # An explicit 0 is a choice: shown 0, sells to 0 — never "unset".
    explicit_zero = ({"battery_reserve_socs": [30, 0]} if slugs
                     else {"battery_reserve_soc": 0, "battery_reserve_socs": [50, 50]})
    for options in ({}, {"battery_reserve_socs": [50, None]} if slugs
                    else {"battery_reserve_socs": [50, 50]}, explicit_zero):
        entry = _entry(hass, options)
        coordinator = _coordinator(hass, entry, slugs)
        controls = await _controls(hass, entry)
        covers = ({"battery_b2_reserve_soc": [1]} if slugs
                  else {"battery_reserve_soc": [0, 1]})
        for key, batteries in covers.items():
            for idx in batteries:
                reserve = _runtime(coordinator, idx, 2)[1]
                assert float(reserve) == controls[key].native_value, (
                    f"{key} shows {controls[key].native_value} but battery "
                    f"{idx} sells to {reserve} (options={options})")


def test_the_registry_fallback_reads_only_this_entrys_batteries(hass):
    from homeassistant.helpers import entity_registry as er
    from custom_components.solar_energy_management.coordinator.battery_controls import (
        discover_battery_control_slugs,
    )
    other = _entry(hass, {})
    mine = _entry(hass, {})
    reg = er.async_get(hass)
    for bid in ("b1", "b2"):
        reg.async_get_or_create("sensor", DOMAIN, f"sem_battery_{bid}_power",
                                suggested_object_id=f"sem_battery_{bid}_power",
                                config_entry=other)
    coordinator = SimpleNamespace(hass=hass, config_entry=mine, _sensor_reader=None)
    assert discover_battery_control_slugs(coordinator) == ()
    coordinator.config_entry = other
    assert discover_battery_control_slugs(coordinator) == ("b1", "b2")


def _sell_at(soc, cfg):
    from custom_components.solar_energy_management.coordinator.charger_types import (
        BatteryRuntime, BatteryView, FleetContext,
    )
    from custom_components.solar_energy_management.coordinator.decide_battery import (
        decide_battery,
    )
    return decide_battery(BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config={"battery_max_discharge_power": 4000, **cfg},
        fleet=FleetContext(), charging_state="idle", ev_charging=False,
        home_consumption_w=500.0, scheduler_decision=None))


def test_a_manual_sell_stops_at_the_reserve_on_screen():
    from custom_components.solar_energy_management.coordinator.charger_types import (
        BatteryIntent,
    )
    unset = {"battery_mode": "force_discharge"}          # number shows 20 %
    assert _sell_at(15.0, unset).intent != BatteryIntent.FORCE_DISCHARGE
    d = _sell_at(25.0, unset)
    assert d.intent == BatteryIntent.FORCE_DISCHARGE and d.floor_soc == 20.0
    zero = {"battery_mode": "force_discharge", "battery_reserve_soc": 0}
    assert _sell_at(15.0, zero).intent == BatteryIntent.FORCE_DISCHARGE


def test_a_vpp_event_keeps_the_reserve_on_screen():
    stub = SimpleNamespace(_vpp_battery_override={
        "battery_mode": "force_discharge", "battery_reserve_soc": 10.0})
    merged = SEMCoordinator._vpp_apply_battery_override(stub, {"battery_mode": "auto"})
    assert merged["battery_reserve_soc"] == 20.0
    merged = SEMCoordinator._vpp_apply_battery_override(
        stub, {"battery_mode": "auto", "battery_reserve_soc": 0})
    assert merged["battery_reserve_soc"] == 10.0


# ── Wiring: one capture, before any platform builds an entity ──────────────

def test_setup_captures_the_battery_controls_before_the_first_refresh():
    tree = ast.parse((ROOT / "__init__.py").read_text())
    setup = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry")
    capture = [n.lineno for n in ast.walk(setup)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Attribute) and t.attr == "battery_control_slugs"
                       for t in n.targets)]
    ed_read = [n.lineno for n in ast.walk(setup)
               if isinstance(n, ast.Attribute)
               and n.attr == "async_initialize_energy_dashboard"]
    first = [n.lineno for n in ast.walk(setup)
             if isinstance(n, ast.Attribute)
             and n.attr in ("async_config_entry_first_refresh",
                            "async_forward_entry_setups")]
    assert len(capture) == 1, "battery controls must be captured exactly once"
    # The first refresh already commands the batteries (review of #1071).
    assert first and capture[0] < min(first)
    # …and after the Energy Dashboard read, or a multi-battery install's
    # first boot would get the global controls.
    assert ed_read and min(ed_read) < capture[0]


def test_only_the_capture_and_the_platform_fallback_discover():
    # Every other reader takes the captured answer; a second discovery could
    # disagree with the controls on screen.
    callers = set()
    for path in ROOT.rglob("*.py"):
        if {"tests", "node_modules"} & set(path.parts):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if name == "discover_battery_control_slugs":
                    callers.add(path.relative_to(ROOT).as_posix())
    assert callers == {"__init__.py", "select.py"}
