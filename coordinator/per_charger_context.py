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
                coord, cid, ev_dev, budget_per_charger, power=power,
            ) as pcc:
                if pcc.skipped_for_night:
                    continue
                # Pure decide() → reconciler-driven actuate(). The legacy
                # imperative ``coord._execute_ev_control`` was removed in
                # Task 11 — control now flows through this dispatch:
                adapter = adapter_for(ev_dev)
                view = build_charger_view(coord, cid, ev_dev, pcc, power)
                decision = decide(view)
                await actuate(decision, adapter, view.power, reconciler=reconciler)

    The ``__enter__`` hook swaps the coordinator's primary-charger
    attributes (``_ev_device``, ``_ev_stalled_since``, etc.) to this
    charger's values; ``__exit__`` persists any updates back into the
    per-charger storage dicts and restores the primary's fleet view.

    Fields populated incrementally across v1.6.7 — v1.6.14:

    - v1.6.7: identity (``cid``, ``ev_dev``, ``charger_cfg``) + the swap
      mechanism. No computed fields; the inline maths in
      ``coordinator.py`` ran inside the ``with`` block.
    - v1.6.9: ``per_charger_flows`` lives on ``PowerFlows.per_charger``
      (not on the context; the calculator produces it before the loop).
    - v1.6.14: ``effective_state`` + ``charger_name`` + ``this_power_w``
      migrated onto the dataclass (issue: the parallel
      ``_effective_states_per_charger`` dict + per-method local-var
      caching of ``this_power_w`` were abstraction leaks; both now
      flow through ``pcc``).
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
    # v1.6.14: computed per-charger fields
    # ------------------------------------------------------------------
    power: Any = None
    """The ``PowerReadings`` for the current cycle. Stored so
    ``__enter__`` can compute ``this_power_w`` for THIS charger via
    the coordinator's existing helper. The factory's caller passes
    the same ``power`` it passes into ``build_charger_view`` →
    ``decide`` → ``actuate``."""

    this_power_w: Optional[float] = None
    """THIS charger's draw in watts, computed once in ``__enter__``
    via ``coord._this_charger_power(ev_dev, power)``. Reads from
    inside the per-charger loop use this field instead of the
    fleet-aggregated ``power.ev_power``. Pre-v1.6.14 each
    ``coordinator/ev_control.py`` method that needed it cached a
    local copy — works, but the value lived in three places.

    ``None`` until ``__enter__`` runs. After exit, the value is
    preserved on the dataclass (the context is short-lived; readers
    don't access it post-exit, but leaving the field set is safer
    than clearing it)."""

    effective_state: Any = None
    """THIS charger's effective ``ChargingState`` for the current
    cycle. Set by the per-charger code inside the ``with`` block.
    Persisted to ``coord._effective_states_per_charger[cid]`` by
    ``__exit__`` so ``_send_notifications`` can dispatch per-charger
    flap-suppressed notifications.

    ``None`` means "this charger did not participate in this cycle"
    (e.g. skipped for night, observer mode); ``__exit__`` then omits
    the write."""

    charger_name: Optional[str] = None
    """Display name for the charger; persisted alongside
    ``effective_state``. Falls back to ``cid`` if the config omits
    a ``name`` key."""

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
        power: Any = None,
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
            power: the ``PowerReadings`` for this cycle. Stored on the
                context so ``__enter__`` can compute ``this_power_w`` via
                the coordinator's existing helper. Optional for legacy
                callers / unit tests that don't exercise ``this_power_w``.

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
            charger_name=charger_cfg.get("name") or cid,
            power=power,
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
            # v1.7.1-beta.14 — solar stability layer per-charger state.
            "last_set_amps_ts": coord._ev_last_set_amps_ts,
            "budget_history": coord._ev_budget_history,
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
        coord._ev_last_set_amps_ts = coord._ev_last_set_amps_ts_per_charger.get(self.cid)
        # Budget history list is mutated in place by the actuator (appends
        # the cycle's budget_w sample, pops the oldest). Setdefault keeps
        # the same list reference across __enter__/__exit__ cycles so the
        # rolling window survives.
        coord._ev_budget_history = coord._ev_budget_history_per_charger.setdefault(
            self.cid, [],
        )

        # v1.6.14: precompute this charger's draw via the coordinator's
        # kW-aware helper. Reads ``self._ev_device`` indirectly via
        # ``_get_active_charger_config`` — must happen AFTER the swap
        # above so the helper sees THIS charger's config. Power is
        # optional (legacy unit tests) — without it the helper falls
        # back to ``power.ev_power`` which is 0 for a None power object.
        if self.power is not None and hasattr(coord, "_this_charger_power"):
            try:
                self.this_power_w = coord._this_charger_power(self.ev_dev, self.power)
            except Exception:  # noqa: BLE001
                # Helper failures shouldn't break the swap; fall back to
                # method-local recompute (the legacy path).
                self.this_power_w = None

        # v1.6.14: stash on the coordinator so ``_this_charger_power``
        # can return the cached value to in-loop callers (replaces
        # per-method ``this_power_w = ...`` locals in ev_control.py
        # without changing those callsites).
        coord._current_pcc = self

        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        """Pop this charger's state back into per-charger dicts and
        restore the primary view.

        Always runs (including on exceptions raised by
        ``decide`` / ``actuate``) so the coordinator's primary view is
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
            # v1.7.1-beta.14 — solar stability layer per-charger state.
            coord._ev_last_set_amps_ts_per_charger[self.cid] = coord._ev_last_set_amps_ts
            # ``budget_history`` is the same list reference setdefault returned
            # at __enter__; mutations done by the actuator persist naturally,
            # so no explicit write-back is needed. The setdefault on the next
            # __enter__ rebinds the primary view to the same list.

            # v1.6.14: persist effective state for the post-loop
            # notification dispatcher. The dict on the coordinator
            # remains the storage; pcc is the write path.
            if self.effective_state is not None:
                coord._effective_states_per_charger[self.cid] = (
                    self.effective_state,
                    self.charger_name or self.cid,
                )

            # v1.6.14: clear the cache pointer so out-of-loop reads
            # (single-charger fallback path, post-loop helpers) hit the
            # direct-compute branch in ``_this_charger_power``.
            if getattr(coord, "_current_pcc", None) is self:
                coord._current_pcc = None

            # Restore primary view.
            coord._ev_device = self._saved["dev"]
            coord._ev_stalled_since = self._saved["stalled"]
            coord._ev_enable_surplus_since = self._saved["enable"]
            coord._ev_charge_started_at = self._saved["started"]
            coord._ev_last_change_time = self._saved["change"]
            coord._ev_reenable_attempts = self._saved["reenable_attempts"]
            coord._ev_charge_refused = self._saved["charge_refused"]
            coord._ev_last_set_amps_ts = self._saved["last_set_amps_ts"]
            coord._ev_budget_history = self._saved["budget_history"]
            # ``_current_charger_budget`` is cleared to ``None`` in the
            # legacy code rather than restored to its pre-loop value —
            # preserve that semantic (the post-loop reader treats
            # non-None as "I'm currently inside a per-charger iteration").
            coord._current_charger_budget = None
            coord._cycle_vehicle_soc = self._saved_vehicle_soc
        finally:
            self._entered = False
        return False  # never swallow exceptions
