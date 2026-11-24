"""(#1381, charger owner S2) Every stop that skips the contactor's minimum ON
says who made it and at which precedence.

``safety_stop`` was set by four producers (peak emergency, VPP pause, Skip
tonight, the phase guard under a yield) and read as one bit, so the
reconciler could not tell a fuse stop from a user's "Skip tonight", and the
guard's yield override keyed on a reason text. Each producer now stamps
``source`` and ``klass``; ``safety_stop`` keeps its meaning (behaviour
unchanged) and the guard keys on its source.
"""
from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.charger_owner import (
    CommandClass,
    SRC_PHASE_GUARD,
    is_guard_stop,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)
from custom_components.solar_energy_management.coordinator.vpp_dispatch import (
    vpp_pause_override,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _charging():
    return ChargerDecision(charger_id="c", mode="pv",
                           intent=ChargerIntent.CHARGE_AT_AMPS,
                           commanded_amps=10, budget_w=6900.0, reason="sun")


def test_every_safety_stop_producer_names_itself():
    """Static: each ``safety_stop=True`` in production code sits in a call
    that also passes ``source=`` and ``klass=``."""
    missing = []
    for path in [*sorted((ROOT / "coordinator").glob("*.py"))]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kws = {k.arg: k.value for k in node.keywords if k.arg}
            val = kws.get("safety_stop")
            if isinstance(val, ast.Constant) and val.value is True:
                if "source" not in kws or "klass" not in kws:
                    missing.append(f"{path.name}:{node.lineno}")
    assert not missing, f"safety_stop without source/klass: {missing}"


def test_vpp_pause_is_a_safety_claim():
    d = vpp_pause_override(_charging(), paused=True)
    assert d.safety_stop is True
    assert d.source == "vpp_pause" and d.klass == CommandClass.SAFETY


def test_provenance_does_not_move_equality():
    a = _charging()
    from dataclasses import replace
    assert replace(a, source="x", klass=3) == a


def test_only_the_guards_own_stop_is_a_guard_stop():
    from dataclasses import replace
    stop = replace(_charging(), intent=ChargerIntent.DISABLE, commanded_amps=0,
                   source=SRC_PHASE_GUARD, klass=1)
    clamp = replace(_charging(), source=SRC_PHASE_GUARD, klass=1)
    vpp = replace(stop, source="vpp_pause")
    assert is_guard_stop(stop) is True
    assert is_guard_stop(clamp) is False
    assert is_guard_stop(vpp) is False
    assert is_guard_stop(SimpleNamespace()) is False
