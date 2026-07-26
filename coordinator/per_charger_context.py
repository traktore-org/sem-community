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
class PerChargerState:
    """Durable per-charger state (#589 Surface-A migration).

    ONE instance per charger id, held on ``coord._pcc_store[cid]``. The
    per-charger loop's ``PerChargerContext`` holds it **by reference** (``.state``),
    so the ``ev_control`` read sites — via the coordinator's ``_ev_*`` PROPERTIES
    — read and MUTATE the stored object directly. There is no snapshot/restore
    and no write-back, so a field added here CANNOT leak charger[0]'s value into
    charger[1] the way the old primary-scalar swap could when a write-back was
    forgotten (#284/#315/#318 class). Fields are migrated off the swap one at a
    time; each lands here + a coordinator property + a cross-charger isolation
    test.
    """

    stalled_since: Optional[float] = None
    enable_surplus_since: Optional[float] = None
    charge_started_at: Optional[float] = None
    last_change_time: Optional[Any] = None
    reenable_attempts: int = 0
    charge_refused: bool = False
    last_set_amps_ts: Optional[float] = None


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
    # Skip flag (set by ``for_charger``)
    # ------------------------------------------------------------------
    # There was a ``budget_w`` here until #651. Its docstring said it was
    # "the single source for this charger's budget — flows into
    # build_charger_view → decide"; ``build_charger_view`` takes no budget
    # argument and never did. Nothing outside the writer and its own unit
    # tests ever read it. The real per-charger solar allocation is
    # ``decide.self_consumption_surplus_w`` subtracting
    # ``fleet.solar_committed_w``, which the coordinator accumulates from
    # each charger's ACTUAL decision as it walks the priority loop.
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

    vehicle_soc: Optional[float] = None
    """#589 swap retirement — THIS charger's vehicle SOC for the current
    cycle. Seeded in ``__enter__`` from the coordinator's global
    (primary-entity) cycle SOC, then overridden by the loop body when the
    charger has its own ``vehicle_soc_entity``. The coordinator's
    ``_cycle_vehicle_soc`` property resolves to this field while the
    context is active, so the per-charger override can no longer leak
    into the next charger via a forgotten restore (the old
    ``_saved_vehicle_soc`` snapshot path). Cycle-scoped: lives on the
    context, not on the durable ``PerChargerState``."""

    # ------------------------------------------------------------------
    # Internal: references + the swap snapshot.
    # ------------------------------------------------------------------
    _coord: "Optional[SEMCoordinator]" = field(default=None, repr=False)
    """The coordinator. Held so ``__enter__/__exit__`` can mutate it."""

    state: "Optional[PerChargerState]" = field(default=None, repr=False)
    """#589 Surface-A — this charger's DURABLE state object (``_pcc_store[cid]``),
    held by reference. Migrated ``_ev_*`` fields read/write it via coordinator
    properties; no snapshot/write-back, so they can't leak between chargers."""

    _entered: bool = field(default=False, repr=False)
    """Guard against nested entry. The coordinator loop is single-threaded
    per cycle; nesting would clobber ``_current_pcc``. (The ``_saved``
    snapshot dict is GONE — #589 swap retirement; there is nothing left
    to capture or restore.)"""

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def for_charger(
        cls,
        coordinator: "SEMCoordinator",
        cid: str,
        ev_dev: Any,
        chargers_by_id: Optional[dict] = None,
        power: Any = None,
    ) -> "PerChargerContext":
        """Build a per-charger context.

        Looks up the per-charger config dict. Computes ``skipped_for_night``
        based on the charger's mode and the current global charging
        state — but only when the global state is a night state; for
        solar states, ``skipped_for_night`` stays ``False`` and the
        caller proceeds normally.

        Args:
            coordinator: the ``SEMCoordinator`` instance (passed so we
                can mutate it in ``__enter__``).
            cid: this charger's id.
            ev_dev: this charger's ``EVDevice`` instance.
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
        return cls(
            cid=cid,
            ev_dev=ev_dev,
            charger_cfg=charger_cfg,
            charger_name=charger_cfg.get("name") or cid,
            power=power,
            _coord=coordinator,
        )

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------
    def __enter__(self) -> "PerChargerContext":
        """Bind this charger's state — NO primary-scalar swap remains.

        #589 swap retirement complete: every per-charger field lives
        either on the durable ``PerChargerState`` (``_pcc_store[cid]``,
        held by reference) or on this context object. The coordinator's
        ``_ev_*`` / ``_cycle_vehicle_soc`` / ``_ev_device`` reads resolve
        through PROPERTIES that dispatch on ``_current_pcc`` — there is
        nothing to snapshot and nothing to restore, so a forgotten
        write-back (the #284/#315/#318 leak class) is unrepresentable.

        Raises:
            RuntimeError: on nested entry. The per-charger loop is
                strictly serial; nesting would clobber ``_current_pcc``.
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

        # #589 Surface-A — bind this charger's DURABLE state object by reference.
        # Migrated fields (``stalled_since`` …) live here; reads/writes via the
        # coordinator properties mutate this object directly — no swap, no
        # write-back to forget.
        self.state = coord._pcc_store.setdefault(self.cid, PerChargerState())

        # Seed this charger's cycle SOC from the global (primary-entity)
        # value. Must read BEFORE ``_current_pcc`` is bound below: the
        # coordinator property resolves to the pcc field once the pointer
        # is set. Chargers without their own ``vehicle_soc_entity`` keep
        # seeing the global SOC (legacy semantics); the loop body's
        # per-charger override lands on this context only and dies with
        # it — nothing to restore.
        self.vehicle_soc = coord._cycle_vehicle_soc

        # Bind the context pointer. From here on the coordinator's
        # ``_ev_device`` property resolves to ``self.ev_dev``, so the
        # ``_this_charger_power`` precompute below (which reads
        # ``self._ev_device`` indirectly via ``_get_active_charger_config``)
        # sees THIS charger's config — the ordering role the retired
        # ``coord._ev_device = self.ev_dev`` swap used to carry.
        coord._current_pcc = self

        # v1.6.14: precompute this charger's draw via the coordinator's
        # kW-aware helper. Power is optional (legacy unit tests) — without
        # it the helper falls back to ``power.ev_power`` which is 0 for a
        # None power object. The helper's cache branch is a no-op at this
        # point (``this_power_w`` still None) so it direct-computes.
        if self.power is not None and hasattr(coord, "_this_charger_power"):
            try:
                self.this_power_w = coord._this_charger_power(self.ev_dev, self.power)
            except Exception:  # noqa: BLE001
                # Helper failures shouldn't break the loop; fall back to
                # method-local recompute (the legacy path).
                self.this_power_w = None

        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        """Persist the effective state and unbind the context pointer.

        Always runs (including on exceptions raised by
        ``decide`` / ``actuate``) so the coordinator is never left with a
        stale ``_current_pcc``. Per-charger state needs no write-back:
        the durable fields live on ``self.state`` (held by reference in
        ``_pcc_store``), the cycle-scoped fields die with this object,
        and the coordinator properties fall back to the primary defaults
        the moment the pointer clears.

        Returns:
            ``False`` so exceptions propagate to the caller (matching
            the legacy ``try/except (HomeAssistantError, ServiceValidationError)``
            handling in coordinator.py).
        """
        coord = self._coord
        assert coord is not None, "PerChargerContext._coord must be set"
        try:
            # v1.6.14: persist effective state for the post-loop
            # notification dispatcher. The dict on the coordinator
            # remains the storage; pcc is the write path.
            if self.effective_state is not None:
                coord._effective_states_per_charger[self.cid] = (
                    self.effective_state,
                    self.charger_name or self.cid,
                )
        finally:
            # Unbind UNCONDITIONALLY (review: the pointer is now the SOLE
            # per-charger dispatch mechanism — a stale binding would make
            # every property read the wrong charger, so it must clear even
            # if the persist above raises). Out-of-loop reads then fall
            # back to the primary/default view in every property and to
            # direct-compute in _this_charger_power.
            if getattr(coord, "_current_pcc", None) is self:
                coord._current_pcc = None
            self._entered = False
        return False  # never swallow exceptions
