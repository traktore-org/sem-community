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
    """What decide_battery reads for battery ``idx`` this cycle."""
    cfg = SEMCoordinator._per_battery_config(coordinator, idx, count)
    mode = str(cfg.get("battery_mode", "auto") or "auto").lower()
    return mode, cfg.get("battery_reserve_soc")


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


@pytest.mark.xfail(strict=True, reason=(
    "Open sibling, not #1071: an UNSET reserve shows 20 % "
    "(DEFAULT_BATTERY_RESERVE_SOC) and decide_battery sells to 0 %."))
@pytest.mark.asyncio
async def test_an_unset_reserve_shows_what_drives_the_battery(hass):
    entry = _entry(hass, {})
    coordinator = _coordinator(hass, entry, ())
    controls = await _controls(hass, entry)
    reserve = _runtime(coordinator, 0, 1)[1]
    assert float(reserve if reserve is not None else 0.0) == (
        controls["battery_reserve_soc"].native_value)


# ── Wiring: one capture, before any platform builds an entity ──────────────

def test_setup_captures_the_battery_controls_before_the_platforms_load():
    tree = ast.parse((ROOT / "__init__.py").read_text())
    setup = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry")
    capture = [n.lineno for n in ast.walk(setup)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Attribute) and t.attr == "battery_control_slugs"
                       for t in n.targets)]
    forward = [n.lineno for n in ast.walk(setup)
               if isinstance(n, ast.Attribute) and n.attr == "async_forward_entry_setups"]
    assert len(capture) == 1, "battery controls must be captured exactly once"
    assert forward and capture[0] < min(forward)


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
