"""#708 — the SOC-cap repair must be scoped to the charger it names.

Live on beta.9 (Azlinon, two EVSEs, one car): the
``soc_cap_unenforceable`` repair fired for **both** chargers while only
one had a vehicle plugged in, each naming its own target ("can't stop at
85%" / "can't stop at 100%"). The idle box has no car to overshoot.

The cause is the fleet-read class (#616, docs/BUG_CLASSES.md): the gate
reads ``charging_state``, which is the FLEET state, and the per-charger
loop calls the helper once per charger. Nothing in the predicate asks
whether *this* charger has a car on it.

SEM already tracks that — ``_last_ev_connected_per_charger[cid]``,
published as ``binary_sensor.sem_charger_<id>_connected`` and used for
exactly this reason by the virtual-SOC decay (#648). The gate needs the
same term.

The second class of test here is the guard: a registry of every
per-charger repair, checked against the source, so a new one cannot be
added without a decision about its connected-scope.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch


from custom_components.solar_energy_management.coordinator import repair_issues as _ri
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.const import ChargingState


class _Coord:
    """The gate and the target resolver, hosted on the state they read."""

    _maybe_warn_soc_cap = SEMCoordinator._maybe_warn_soc_cap
    _resolve_target = SEMCoordinator._resolve_target
    SOLAR_CHARGING_STATES = SEMCoordinator.SOLAR_CHARGING_STATES

    def __init__(self, connected: dict[str, bool]):
        self.hass = MagicMock()
        self.config = {"ev_target_type": "soc"}
        self._last_ev_connected_per_charger = dict(connected)


# The fleet is solar-charging because ONE car is drawing; that is the
# state every charger in the loop is handed.
FLEET_CHARGING = ChargingState.SOLAR_CHARGING_ACTIVE

CFG_A = {"name": "Large Bay EVSE", "ev_target_type": "soc", "ev_target_soc": 85}
CFG_B = {"name": "Small Bay EVSE", "ev_target_type": "soc", "ev_target_soc": 100}


class TestTheConnectedScope:
    """One car, two boxes — only the box with the car can overshoot."""

    def test_the_charger_with_a_car_still_raises(self):
        coord = _Coord({"large_bay": True, "small_bay": False})
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it:
            coord._maybe_warn_soc_cap("large_bay", CFG_A, None, FLEET_CHARGING)
        raise_it.assert_called_once()
        assert raise_it.call_args.args[1] == "large_bay"

    def test_the_charger_with_no_car_does_not(self):
        """The live report: the idle box raised its own 100% repair."""
        coord = _Coord({"large_bay": True, "small_bay": False})
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it:
            coord._maybe_warn_soc_cap("small_bay", CFG_B, None, FLEET_CHARGING)
        raise_it.assert_not_called()

    def test_the_charger_with_no_car_is_cleared(self):
        """Not merely 'not raised' — an already-open repair must go away
        when the car is unplugged, or it outlives the session that
        raised it."""
        coord = _Coord({"large_bay": True, "small_bay": False})
        with patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
            coord._maybe_warn_soc_cap("small_bay", CFG_B, None, FLEET_CHARGING)
        clear_it.assert_called_once()
        assert clear_it.call_args.args[1] == "small_bay"

    def test_an_unknown_charger_is_treated_as_connected(self):
        """Absent per-charger connection state must not silently disable
        the repair — the pre-#708 behaviour is the safe fallback for a
        charger the connection tracker has not seen yet (first cycle
        after a restart, or a charger with no connected sensor)."""
        coord = _Coord({})
        with patch.object(_ri, "raise_soc_cap_unenforceable") as raise_it:
            coord._maybe_warn_soc_cap("large_bay", CFG_A, None, FLEET_CHARGING)
        raise_it.assert_called_once()

    def test_a_real_soc_reading_still_clears_a_connected_charger(self):
        """The connected term ADDS a condition; it must not swallow the
        original clear path."""
        coord = _Coord({"large_bay": True})
        with patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
            coord._maybe_warn_soc_cap("large_bay", CFG_A, 47.0, FLEET_CHARGING)
        clear_it.assert_called_once()

    def test_a_kwh_target_still_clears(self):
        coord = _Coord({"large_bay": True})
        cfg = {"name": "Large Bay EVSE", "ev_target_type": "kwh"}
        with patch.object(_ri, "clear_soc_cap_unenforceable") as clear_it:
            coord._maybe_warn_soc_cap("large_bay", cfg, None, FLEET_CHARGING)
        clear_it.assert_called_once()


# ── the class guard ──────────────────────────────────────────────────
#
# Every repair keyed by a charger id is a per-charger surface, and every
# per-charger surface is a place the fleet-read class (#616) can land.
# This registry is the decision record: each one is either gated on this
# charger's own connection state, or structurally per-charger because
# its caller only ever holds one charger. A new entry with no decision
# fails the test below.

PER_CHARGER_REPAIRS = {
    "raise_soc_cap_unenforceable": (
        "gated — coordinator._maybe_warn_soc_cap consults "
        "_last_ev_connected_per_charger[cid] (#708)"
    ),
    "raise_charger_stop_unenforceable": (
        "structural — raised by ChargerReconciler._report_stop_unenforceable, "
        "which is instantiated per charger and holds self.charger_id + its "
        "own adapter/power (#627)"
    ),
    "raise_charger_actuation_failed": (
        "structural — raised from devices/base.py on the device object "
        "whose write just failed (#392)"
    ),
    "raise_charger_failsafe_suspected": (
        "structural — raised via ChargerAdapter.report_failsafe_suspected "
        "from the reconciler's apply loop; the reconciler is instantiated "
        "per charger and measured THIS charger's stop→re-enable interval, "
        "and the adapter reads only its own device (#823)"
    ),
    "raise_charger_control_entity_broken": (
        "structural — raised from coordinator._check_charger_control_entities, "
        "which runs INSIDE the per-charger loop and reads only this "
        "charger's own config dict. The issue id carries (charger_id, "
        "entity_id) so two chargers naming the same helper cannot clear "
        "each other's repair (#824)"
    ),
}

REPAIR_ISSUES_PY = (
    Path(__file__).resolve().parent.parent / "coordinator" / "repair_issues.py"
)


def _raisers_keyed_by_device_id() -> set[str]:
    """Every ``raise_*`` in repair_issues.py whose second parameter is
    ``device_id`` — i.e. every repair a charger id keys."""
    tree = ast.parse(REPAIR_ISSUES_PY.read_text())
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("raise_"):
            continue
        args = [a.arg for a in node.args.args]
        if len(args) >= 2 and args[1] == "device_id":
            found.add(node.name)
    return found


class TestThePerChargerRepairRegistry:
    def test_every_charger_keyed_repair_has_a_scope_decision(self):
        """Adding a repair keyed by charger id without deciding how it is
        scoped is how #708 happened. Decide here, in the registry."""
        undecided = _raisers_keyed_by_device_id() - set(PER_CHARGER_REPAIRS)
        assert not undecided, (
            "New per-charger repair(s) with no connected-scope decision: "
            f"{sorted(undecided)}. Add each to PER_CHARGER_REPAIRS with "
            "either 'gated — <where the per-charger term is applied>' or "
            "'structural — <why the caller can only mean one charger>'. "
            "A repair that names one charger must not be raised because "
            "another charger is busy (#616 fleet-read class)."
        )

    def test_the_registry_has_no_stale_entries(self):
        stale = set(PER_CHARGER_REPAIRS) - _raisers_keyed_by_device_id()
        assert not stale, f"Registry names repairs that no longer exist: {sorted(stale)}"

    def test_the_gated_one_actually_reads_the_per_charger_term(self):
        """Source assertion, paired with the behavioural tests above: the
        registry claims _maybe_warn_soc_cap is gated — hold it to that,
        so the entry cannot rot into a comment."""
        src = inspect.getsource(SEMCoordinator._maybe_warn_soc_cap)
        assert "_last_ev_connected_per_charger" in src
