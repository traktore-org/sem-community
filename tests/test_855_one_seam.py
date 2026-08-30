"""#855 — the charger path has ONE hardware seam, and observer cuts AT it.

Guido, 29.08.2026:

> *"the 2nd layer has one communication string to the 3rd layer for ev
> charger, then the rest follows the lead, and the observation should not
> be a matter any more — more a matter of get the work done."*

SEM had already proved the shape for loads. `reconcile_load`'s docstring:

> *"Here — the ONLY execution seam — we LOG the command we WOULD send …
> This is why observer mode needs no separate `observe_only` path — a
> clean layer cut makes it a one-line branch in the actuator."*

Chargers issued commands from ~20 places instead, so observer mode had to
be re-implemented above each of them — and it cut ABOVE the adapter, which
is why the WOULD surface reported the DECISION and never the COMMANDS:

* **#854** — the KEBA "stop" was `set_current` + `set_energy(1.0)` +
  `enable`. A start wearing a stop's name, ~1 kWh into the car on every
  plug-in against a zero ask, and observer said "WOULD IDLE" while the
  enable happened below the cut.
* **#804** — phase switching unexercisable on the rig.
* **#852** — a reporter's Wallbox stop unreproducible on the rig.

`ControllableDevice.send()` is now that seam. These tests keep it single.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHARGER_PATH = [
    ROOT / "devices" / "base.py",
    *sorted((ROOT / "coordinator" / "charger_adapters").glob("*.py")),
    # The per-charger control loop commands hardware too (#804's phase
    # switch). It sits above the device layer and cannot reach the seam,
    # so its one call carries its own observer gate — and is pinned here
    # rather than left as an un-guarded exception to the invariant.
    ROOT / "coordinator" / "ev_control.py",
    # (2.1 audit INFO-1) The heat pump's hardware writes are observer-gated
    # one layer UP — reconcile_load's observer branch returns before any
    # device method runs — and nothing inside the file checks the flag.
    # Scanning it here means a new un-annotated hardware call in that file
    # fails CI instead of silently bypassing observer mode.
    ROOT / "devices" / "heat_pump_controller.py",
    # The reconciler owns convergence and, since the observer gate in
    # actuate() was retired (30.08.2026), it RUNS under observer mode — so
    # a direct hardware call added here would reach a real charger on a rig
    # that believes it is only watching. It has none today; scanning it
    # keeps that true.
    ROOT / "coordinator" / "charger_reconciler.py",
]

# The opt-out, spelled like the codebase's other one (`# FLEET-READ:`): a
# direct call is allowed only where the source SAYS it is observer-gated.
# Delete the gate and the annotation goes with it, and CI fails.
OPT_OUT = "# OBSERVER-GATED:"


def _direct_hardware_calls(path: pathlib.Path):
    """Every `*.services.async_call(...)` in the file, with its function."""
    tree = ast.parse(path.read_text())
    owner = {}
    for scope in ast.walk(tree):
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(scope):
                owner.setdefault(node, scope.name)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "async_call":
            inner = f.value
            if isinstance(inner, ast.Attribute) and inner.attr == "services":
                out.append((owner.get(node, "<module>"), node.lineno))
    return out


def test_only_the_seam_talks_to_hardware():
    """The invariant. A new direct call here is a new blind spot for
    observer mode — the exact shape that hid #854."""
    offenders = []
    for path in CHARGER_PATH:
        lines = path.read_text().splitlines()
        for fn, line in _direct_hardware_calls(path):
            if path.name == "base.py" and fn == "send":
                continue          # the seam itself IS the sanctioned caller
            # The annotation must sit in the contiguous comment block
            # immediately above the call, so it cannot drift away from the
            # thing it excuses.
            i = line - 2                      # the line above the call
            block = []
            while i >= 0 and lines[i].strip().startswith("#"):
                block.append(lines[i])
                i -= 1
            if any(OPT_OUT in b for b in block):
                continue
            offenders.append(f"{path.name}:{line} in {fn}()")
    assert not offenders, (
        "hardware commands issued outside the seam: " + ", ".join(offenders)
        + ". Route them through `await device.send(domain, service, data, "
        "why=...)` — otherwise observer mode cannot see them, which is how "
        "an `enable` hid inside a 'stop' for a month (#854)."
    )


def test_the_seam_exists_and_is_on_the_base_class():
    from custom_components.solar_energy_management.devices.base import (
        ControllableDevice,
    )
    assert callable(getattr(ControllableDevice, "send", None)), (
        "the seam must live on the base device so every device family "
        "inherits it — chargers first, 'then the rest follows the lead'"
    )


@pytest.mark.asyncio
async def test_observer_withholds_the_send_and_names_what_it_withheld():
    """The payoff: the full brand path runs, only the send is withheld,
    and the surface says exactly what would have gone to the box."""
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    d = CurrentControlDevice.__new__(CurrentControlDevice)
    d.name, d.device_id = "EV Charger", "ev_charger"
    d.hass = MagicMock()
    d.hass.services.async_call = AsyncMock()
    d.observer_mode = True
    d.withheld_commands = []

    sent = await d.send("keba", "disable", {}, why="stop")
    assert sent is False
    d.hass.services.async_call.assert_not_awaited(), (
        "observer mode must not reach the hardware"
    )
    assert d.withheld_commands == [
        {"service": "keba.disable", "data": {}, "why": "stop"}
    ], "the withheld command is the observation surface — it must name it"


@pytest.mark.asyncio
async def test_live_mode_sends_exactly_once():
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    d = CurrentControlDevice.__new__(CurrentControlDevice)
    d.name, d.device_id = "EV Charger", "ev_charger"
    d.hass = MagicMock()
    d.hass.services.async_call = AsyncMock()
    d.observer_mode = False
    d.withheld_commands = []

    assert await d.send("keba", "disable", {}, why="stop") is True
    d.hass.services.async_call.assert_awaited_once_with(
        "keba", "disable", {}, blocking=True)
    assert d.withheld_commands == []


@pytest.mark.asyncio
async def test_a_device_nobody_told_still_acts():
    """Fail-safe direction: a device built without __init__ (fixtures,
    legacy paths) has no observer flag and must SEND, not silently
    swallow. A stop that quietly does nothing is the worse failure."""
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    d = CurrentControlDevice.__new__(CurrentControlDevice)
    d.name, d.device_id = "EV", "ev"
    d.hass = MagicMock()
    d.hass.services.async_call = AsyncMock()
    assert await d.send("keba", "disable", {}) is True
