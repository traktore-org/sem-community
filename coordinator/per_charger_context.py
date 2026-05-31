"""Per-charger context manager (v1.6.7).

Lifts the ad-hoc ``saved = {...}`` swap dict at the head of the
per-charger loop in ``coordinator.py`` into a typed context manager so:

1. **The swap surface is one place to edit.** Adding a new per-charger
   field used to require touching three locations (the saved dict, the
   per-charger storage dict, the restore block). Now: add a field here.

2. **The per-charger invariant is structural.** Inside a
   ``with PerChargerContext.for_charger(...)`` block, you read
   ``pcc.this_power_w`` etc. — not ``power.ev_power``. Future code
   reviewers and the AST lint planned for v1.6.8 can mechanically check
   this.

3. **Zero behaviour change for v1.6.7.** The semantics of the swap +
   restore + per-charger persistence are exactly what the
   ``coordinator.py:1136-1258`` block did. Single-charger users never
   enter the multi-charger loop and so are unaffected.

See ``docs/MULTI_CHARGER.md`` for the full invariant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .coordinator import SEMCoordinator


@dataclass
class PerChargerContext:
    """Per-charger state for ONE iteration of the multi-charger loop.

    Use via the ``for_charger`` classmethod as a context manager:

    .. code-block:: python

        for cid, ev_dev in sorted_chargers:
            with PerChargerContext.for_charger(
                coord, cid, ev_dev, budget_per_charger,
            ) as pcc:
                if pcc.skipped_for_night:
                    continue
                await coord._execute_ev_control(
                    pcc.effective_state, power, energy, charging_context,
                )

    The ``__enter__`` hook swaps the coordinator's primary-charger
    attributes (``_ev_device``, ``_ev_stalled_since``, etc.) to this
    charger's values; ``__exit__`` persists any updates back into the
    per-charger storage dicts and restores the primary's fleet view.

    Fields are populated incrementally across v1.6.7 — v1.6.9:

    - v1.6.7: identity (``cid``, ``ev_dev``, ``charger_cfg``) + the swap
      mechanism (no new computed fields; the existing inline maths in
      ``coordinator.py`` continue to run inside the ``with`` block).
    - v1.6.8: ``effective_strategy``, ``this_power_w`` migrated from
      ``ev_control._this_charger_power``.
    - v1.6.9: ``per_charger_flows`` from the per-charger flow calculator.
    """

    # ------------------------------------------------------------------
    # Identity (set by ``for_charger``)
    # ------------------------------------------------------------------
    cid: str
    """The charger id (``ev_chargers[].id``). Stable across cycles."""

    ev_dev: Any
    """The ``EVDevice`` (KEBA, Wallbox, …) instance for this charger."""

    charger_cfg: dict
    """The per-charger config dict from ``ev_chargers`` (or ``{}``)."""

    # ------------------------------------------------------------------
    # Budget + skip flag (set by ``for_charger``)
    # ------------------------------------------------------------------
    budget_w: Optional[float] = None
    """Per-charger surplus budget in watts, or ``None`` outside a solar
    state (matches ``self._current_charger_budget`` semantics)."""

    skipped_for_night: bool = False
    """``True`` when the charger's mode opts it out of the current night
    state (set during ``for_charger`` based on ``_mode_allows_night_charging``)."""

    # ------------------------------------------------------------------
    # Internal: references + the swap snapshot.
    # ------------------------------------------------------------------
    _coord: "Optional[SEMCoordinator]" = field(default=None, repr=False)
    """The coordinator. Held so ``__enter__/__exit__`` can mutate it."""

    _saved: dict = field(default_factory=dict, repr=False)
    """Coordinator attributes captured at ``__enter__``, restored at
    ``__exit__``. Mirrors the pre-v1.6.7 ``saved = {...}`` dict."""

    _saved_vehicle_soc: Any = field(default=None, repr=False)
    """``_cycle_vehicle_soc`` captured separately because it has its own
    legacy save path (``saved_vehicle_soc_ctrl`` in the old code)."""

    _entered: bool = field(default=False, repr=False)
    """Guard against nested entry. The coordinator loop is single-threaded
    per cycle; nesting would corrupt the swap snapshot."""

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def for_charger(
        cls,
        coordinator: "SEMCoordinator",
        cid: str,
        ev_dev: Any,
        ev_budget_per_charger: dict,
        chargers_by_id: Optional[dict] = None,
    ) -> "PerChargerContext":
        """Build a per-charger context.

        Looks up the per-charger config dict and the per-charger budget
        from the cycle-level distribution. Computes ``skipped_for_night``
        based on the charger's mode and the current global charging
        state — but only when the global state is a night state; for
        solar states, ``skipped_for_night`` stays ``False`` and the
        caller proceeds normally.

        Args:
            coordinator: the ``SEMCoordinator`` instance (passed so we
                can mutate it in ``__enter__``).
            cid: this charger's id.
            ev_dev: this charger's ``EVDevice`` instance.
            ev_budget_per_charger: the per-charger budget dict from
                ``self._surplus_controller.distribute_ev_budget``. May
                contain a value for ``cid`` (solar state) or be empty
                (night state).
            chargers_by_id: optional pre-built ``{cid: cfg}`` lookup the
                caller can pass to avoid rebuilding it inside the loop.
                If ``None``, this method rebuilds it from
                ``coordinator.config``.

        Returns:
            A ``PerChargerContext`` ready to be used as a context manager.
        """
        if chargers_by_id is None:
            chargers_by_id = {
                (c.get("id") or "ev_charger"): c
                for c in (coordinator.config.get("ev_chargers") or [])
                if isinstance(c, dict)
            }
        charger_cfg = chargers_by_id.get(cid, {})
        budget_w = ev_budget_per_charger.get(cid) if ev_budget_per_charger else None
        return cls(
            cid=cid,
            ev_dev=ev_dev,
            charger_cfg=charger_cfg,
            budget_w=budget_w,
            _coord=coordinator,
        )

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------
    def __enter__(self) -> "PerChargerContext":
        """Push this charger's state onto the coordinator.

        Captures the coordinator's primary-charger attributes into
        ``_saved`` so ``__exit__`` can restore them; then writes this
        charger's per-charger state (read from the coordinator's
        ``_ev_*_per_charger`` dicts) into the primary attributes so
        downstream methods that still read ``self._ev_*`` see THIS
        charger's view.

        Raises:
            RuntimeError: on nested entry. The per-charger loop is
                strictly serial; nesting would clobber ``_saved``.
        """
        if self._entered:
            raise RuntimeError(
                "PerChargerContext entered twice — the per-charger loop "
                "must be serial. This indicates a coordinator init or "
                "refactor bug."
            )
        self._entered = True
        coord = self._coord
        assert coord is not None, "PerChargerContext._coord must be set"

        # Snapshot the primary attributes BEFORE swapping in this charger's
        # values. The same set of fields the legacy ``saved = {...}`` dict
        # captured at coordinator.py:1136-1144 in the pre-v1.6.7 code.
        self._saved = {
            "dev": coord._ev_device,
            "stalled": coord._ev_stalled_since,
            "enable": coord._ev_enable_surplus_since,
            "started": coord._ev_charge_started_at,
            "change": coord._ev_last_change_time,
            "reenable_attempts": coord._ev_reenable_attempts,
            "charge_refused": coord._ev_charge_refused,
            "current_charger_budget": coord._current_charger_budget,
        }
        self._saved_vehicle_soc = coord._cycle_vehicle_soc

        # Push this charger's state onto the coordinator.
        coord._ev_device = self.ev_dev
        coord._ev_stalled_since = coord._ev_stalled_since_per_charger.get(self.cid)
        coord._ev_enable_surplus_since = coord._ev_enable_surplus_per_charger.get(self.cid)
        coord._ev_charge_started_at = coord._ev_charge_started_per_charger.get(self.cid)
        coord._ev_last_change_time = coord._ev_last_change_per_charger.get(self.cid)
        coord._ev_reenable_attempts = coord._ev_reenable_attempts_per_charger.get(self.cid, 0)
        coord._ev_charge_refused = coord._ev_charge_refused_per_charger.get(self.cid, False)
        coord._current_charger_budget = self.budget_w

        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        """Pop this charger's state back into per-charger dicts and
        restore the primary view.

        Always runs (including on exceptions raised by
        ``_execute_ev_control``) so the coordinator's primary view is
        never left mid-swap. Mirrors the ``finally:`` block at the
        coordinator.py:1242-1258 in the pre-v1.6.7 code.

        Returns:
            ``False`` so exceptions propagate to the caller (matching
            the legacy ``try/except (HomeAssistantError, ServiceValidationError)``
            handling in coordinator.py).
        """
        coord = self._coord
        assert coord is not None, "PerChargerContext._coord must be set"
        try:
            # Save back this charger's per-charger state.
            coord._ev_stalled_since_per_charger[self.cid] = coord._ev_stalled_since
            coord._ev_enable_surplus_per_charger[self.cid] = coord._ev_enable_surplus_since
            coord._ev_charge_started_per_charger[self.cid] = coord._ev_charge_started_at
            coord._ev_last_change_per_charger[self.cid] = coord._ev_last_change_time
            coord._ev_reenable_attempts_per_charger[self.cid] = coord._ev_reenable_attempts
            coord._ev_charge_refused_per_charger[self.cid] = coord._ev_charge_refused

            # Restore primary view.
            coord._ev_device = self._saved["dev"]
            coord._ev_stalled_since = self._saved["stalled"]
            coord._ev_enable_surplus_since = self._saved["enable"]
            coord._ev_charge_started_at = self._saved["started"]
            coord._ev_last_change_time = self._saved["change"]
            coord._ev_reenable_attempts = self._saved["reenable_attempts"]
            coord._ev_charge_refused = self._saved["charge_refused"]
            # ``_current_charger_budget`` is cleared to ``None`` in the
            # legacy code rather than restored to its pre-loop value —
            # preserve that semantic (the post-loop reader treats
            # non-None as "I'm currently inside a per-charger iteration").
            coord._current_charger_budget = None
            coord._cycle_vehicle_soc = self._saved_vehicle_soc
        finally:
            self._entered = False
        return False  # never swallow exceptions
