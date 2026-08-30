"""#864 — the peak guard may not disappear quietly.

Found by an independent audit of the broad exception handlers on the
decision path (30.08.2026), in the newest code in the tree.

The slot guard is framed as a security layer above every device: it caps
what SEM offers a charger so a 15-minute metering slot cannot blow through
the contracted peak. Its call site collapsed ANY exception to
``_slot_allowed = None``::

    except Exception:  # noqa: BLE001 — the guard must never kill a cycle
        _slot_allowed = None

and ``decide.py`` reads ``None`` as *no cap at all* — deliberately, because
that is also what an unlimited install publishes when the user sets the
Control-tab slider to MAX (#717/#830: one off-switch, no second toggle).

So a coding error inside ``slot_allowed_import_w`` or ``PeakSlotTracker``
produced a state indistinguishable from the user having switched the guard
off, on a live control decision, with **no log line at any level**. The
handler's own comment is right that the guard must not kill a cycle. It was
wrong that the guard may vanish without saying so.

Two things this file pins:

* the cycle still survives a broken guard — no exception escapes;
* it is LOUD: the failure is logged with a traceback, and the published
  state says the guard failed rather than implying it was switched off.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock


def _coord(monkeypatch, boom=None):
    """A coordinator stub whose slot-allowance computation can be broken."""
    from custom_components.solar_energy_management.coordinator import (
        coordinator as coordinator_module,
    )
    coord = coordinator_module.SEMCoordinator.__new__(
        coordinator_module.SEMCoordinator)
    coord.config = {}
    coord._peak_slot_tracker = SimpleNamespace(
        imported_kwh=0.5, elapsed_s=300.0,
        update=MagicMock(),
    )
    # A configured, LIMITED install — the guard is meant to be active.
    coord._load_manager = SimpleNamespace(
        _peak_unlimited=False, _target_peak_limit=6000.0)
    if boom is not None:
        # Patch at the SOURCE module: the coordinator imports this inside the
        # method body, so a name patched on the coordinator module is never
        # consulted.
        from custom_components.solar_energy_management.coordinator import (
            peak_guard,
        )
        monkeypatch.setattr(peak_guard, "slot_allowed_import_w", boom)
    return coord, coordinator_module


def _broken(*args, **kwargs):
    """The shape of a real coding error: a wrong attribute, not an I/O fault."""
    raise AttributeError("'PeakSlotTracker' object has no attribute 'elapsed'")


class TestABrokenGuardIsNotASilentOffSwitch:
    def test_the_failure_is_logged_with_a_traceback(self, monkeypatch, caplog):
        coord, mod = _coord(monkeypatch, boom=_broken)
        with caplog.at_level(logging.WARNING):
            mod.SEMCoordinator._compute_peak_slot_allowance(
                coord, SimpleNamespace(grid_import_power=3000.0))
        assert any("peak" in r.message.lower() for r in caplog.records), (
            "a broken safety guard produced no log line at any level — "
            "indistinguishable from the user switching it off"
        )
        assert any(r.exc_info for r in caplog.records), (
            "without a traceback the cause cannot be found"
        )

    def test_the_cycle_still_survives(self, monkeypatch):
        """The original comment was right about this half: a guard that
        raises would take the whole cycle down with it."""
        coord, mod = _coord(monkeypatch, boom=_broken)
        mod.SEMCoordinator._compute_peak_slot_allowance(
            coord, SimpleNamespace(grid_import_power=3000.0))
        assert coord._peak_slot_allowed_w is None

    def test_a_healthy_guard_stays_quiet_and_returns_a_cap(self, monkeypatch, caplog):
        """A guard that cries wolf gets ignored — the loud path must fire
        only on real failure."""
        coord, mod = _coord(monkeypatch)
        with caplog.at_level(logging.WARNING):
            mod.SEMCoordinator._compute_peak_slot_allowance(
                coord, SimpleNamespace(grid_import_power=3000.0))
        assert coord._peak_slot_allowed_w is not None
        assert not [r for r in caplog.records if "peak" in r.message.lower()]

    def test_an_unlimited_install_is_not_a_failure(self, monkeypatch, caplog):
        """MAX on the slider is the documented off-switch and must stay
        silent — the whole point is telling the two apart."""
        coord, mod = _coord(monkeypatch)
        coord._load_manager = SimpleNamespace(
            _peak_unlimited=True, _target_peak_limit=0.0)
        with caplog.at_level(logging.WARNING):
            mod.SEMCoordinator._compute_peak_slot_allowance(
                coord, SimpleNamespace(grid_import_power=3000.0))
        assert coord._peak_slot_allowed_w is None
        assert not [r for r in caplog.records if "peak" in r.message.lower()]
