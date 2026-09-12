"""#820 — pace the battery's daytime fill to land full at day's end.

@ArneGollin1987's 21 kWh pack is full by ~11:30 and sits there for hours:
bad for longevity, and midday harvest is capped whenever PV alone saturates
the inverter's AC limit while the pack has nothing left to absorb. His
export price is fixed, so this paces on forecast + headroom only — price
never enters.

The math deliberately reuses the model the user already sees:
``provisional_soc_curve`` (day_ledger) predicts the fill under a given
charge-power cap, so the pace is its INVERSION — the smallest constant cap
that still lands the pack at its target by the last slot. One model,
displayed and actuated, never two opinions of the same day.

Every refusal is a named reason, because "no cap" has four different
meanings a user must be able to tell apart on the card.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PacingDecision:
    cap_w: Optional[float]
    """The charge-power cap to write, or None = leave the hardware alone."""
    reason: str
    """Why — a token-bearing sentence; the card renders a token, not this."""
    full_at: Optional[str] = None
    """ISO time the paced fill is predicted to reach target (diagnostic)."""
    code: str = "idle"
    """Stable token for the card (buffer/trust/weak_day/paced/clip/none/
    target/soc_unknown). Cards render the token; the prose is a tooltip."""
    need_kwh: Optional[float] = None
    """(#820 diag) kWh the pack still needs to reach the target."""
    fill_kwh: Optional[float] = None
    """(#820 diag) kWh the day model can put into the pack UNCAPPED — the
    number ``weak_day`` is judged on. Published so a "weak day" verdict on a
    bright forecast can be read instead of guessed (.175, 03.09: 27.8 kWh
    forecast, 5.3 kWh need, verdict weak_day)."""


def _fill_kwh(ledger, cap_w: float) -> float:
    """kWh the pack absorbs over the ledger under a constant cap — the same
    per-slot arithmetic as provisional_soc_curve's charging term."""
    total = 0.0
    for s in ledger:
        leftover = 0.0
        if s.cap_override_w is not None:
            leftover = max(0.0, s.cap_override_w - s.grid_committed_w)
        total += min(leftover, cap_w) * s.hours / 1000.0
    return total


def _full_slot(ledger, cap_w: float, need_kwh: float):
    filled = 0.0
    for i, s in enumerate(ledger):
        leftover = 0.0
        if s.cap_override_w is not None:
            leftover = max(0.0, s.cap_override_w - s.grid_committed_w)
        filled += min(leftover, cap_w) * s.hours / 1000.0
        if filled >= need_kwh:
            return i
    return None


def paced_charge_cap_w(
    *,
    ledger,
    capacity_kwh: float,
    soc_pct: float,
    target_soc_pct: float = 100.0,
    floor_soc_pct: float = 35.0,
    forecast_trusted: bool = False,
    inverter_ac_limit_w: float = 0.0,
    hw_max_charge_w: float = 10000.0,
    end_margin_slots: int = 1,
) -> PacingDecision:
    """The smallest constant charge cap that still fills the pack in time.

    Guards, in the order a person would apply them:

    1. **Buffer first** — below ``floor_soc_pct`` the pack charges ASAP.
       The reporter's own staging: ~30-40 % as fast as the sun allows is
       the safety net against a cloudy afternoon.
    2. **Trust** — an untrusted forecast paces nothing. Greedy's failure
       mode is cosmetic (full at 11:30); a pace built on a forecast that
       disappoints strands the pack half-full at sunset, which is material.
    3. **Feasibility** — if even uncapped charging cannot reach the target,
       any cap only makes it worse: no cap.
    4. **Clipping** — hours where surplus exceeds the inverter's AC limit
       are sun that cannot be exported anyway; the cap opens to at least
       swallow the predicted clip. Captured energy beats an even pace.
    """
    if capacity_kwh <= 0 or not ledger:
        return PacingDecision(None, "pacing idle — no day model", code="none")
    if soc_pct < floor_soc_pct:
        return PacingDecision(
            None, f"filling the safety buffer to {floor_soc_pct:.0f}% "
                  "as fast as the sun allows", code="buffer")
    if not forecast_trusted:
        return PacingDecision(
            None, "forecast trust not earned — pacing on a forecast that "
                  "disappoints strands the pack half-full, so: greedy",
            code="trust")

    need_kwh = max(0.0, (target_soc_pct - soc_pct) / 100.0 * capacity_kwh)
    if need_kwh <= 0.05:
        return PacingDecision(None, "target already reached", code="target",
                              need_kwh=round(need_kwh, 2))

    fill_kwh = _fill_kwh(ledger, hw_max_charge_w)
    if fill_kwh < need_kwh:
        return PacingDecision(
            None, "the day cannot fill the pack even uncapped — a cap "
                  "only makes it worse", code="weak_day",
            need_kwh=round(need_kwh, 2), fill_kwh=round(fill_kwh, 2))

    # Binary-search the smallest cap that still lands the target by the
    # end (with the margin) — the inversion of provisional_soc_curve.
    last_ok = len(ledger) - 1 - max(0, end_margin_slots - 1)
    lo, hi = 0.0, hw_max_charge_w
    for _ in range(24):
        mid = (lo + hi) / 2.0
        slot = _full_slot(ledger, mid, need_kwh)
        if slot is not None and slot <= last_ok:
            hi = mid
        else:
            lo = mid
    cap = hi

    # Clipping guard: any slot whose surplus exceeds the AC limit is energy
    # that cannot leave the roof — open the cap far enough to absorb the
    # worst predicted clip on top of the pace.
    reason = "paced to land full at day's end"
    if inverter_ac_limit_w and inverter_ac_limit_w > 0:
        worst_clip = 0.0
        for s in ledger:
            # Clipping is SOLAR against the AC limit — the inverter clips
            # its output, and the battery is the only place the excess DC
            # can go. Slots that carry solar_w use it; older ledger shapes
            # fall back to the surplus budget, which under-asks by the
            # house draw and errs toward pacing (never toward a stale cap).
            solar = getattr(s, "solar_w", None)
            basis = solar if solar is not None else s.cap_override_w
            if basis is not None:
                worst_clip = max(worst_clip, basis - inverter_ac_limit_w)
        if worst_clip > 0:
            cap = min(hw_max_charge_w, max(cap, worst_clip))
            reason = ("paced, opened for predicted clipping — captured sun "
                      "beats an even pace")

    slot = _full_slot(ledger, cap, need_kwh)
    full_at = ledger[slot].end.isoformat() if slot is not None else None
    return PacingDecision(round(cap, 0), reason, full_at,
                          code="clip" if "clipping" in reason else "paced",
                          need_kwh=round(need_kwh, 2), fill_kwh=round(fill_kwh, 2))


class ChargePacingWriter:
    """Owns the ONE side effect: the user-named max-charge-power number.

    Rules, each load-bearing:
    * the entity's value is CAPTURED on first engage and RESTORED on
      disengage — a stale cap left on an inverter register outlives SEM's
      next restart and throttles the battery for nobody;
    * that capture is PERSISTED, and ADOPTED by the next lifetime (#949).
      An HA restart never unloads the entry — ``async_unload_entry`` says so
      — and the pacer is not in the battery adapters' unload release (#936),
      so the register simply keeps the cap. A fresh writer that re-captured
      would then read SEM's own 400 W and store THAT as the value to restore
      to: the real hardware maximum gone for good, every later restore
      putting the cap back, and SEM reporting healthy throughout. Adoption
      writes nothing of its own — a still-wanted cap dedupes, a finished
      pacing restores the real value;
    * writes dedupe at 100 W (the force-discharge writer's threshold);
    * observer mode never writes — the decision is still published, so the
      rig shows what WOULD happen (the house observer seam). It never adopts
      either: consuming the record of a real engagement is a side effect,
      and an observer has none.

    ``store`` is injected at runtime (the ``DeyeSnapshotStore`` pattern,
    #709) and duck-typed — ``async_load`` / ``async_save`` / ``async_remove``
    — so this module stays free of Home Assistant imports and the tests can
    hand it a dict.
    """

    def __init__(self, store: Any = None) -> None:
        self.engaged: bool = False
        #: the entity the engagement is ON — the unload path needs it after
        #: the coordinator is gone, and the record on disk is async to read
        self.engaged_entity: str = ""
        self.restore_value: float | None = None
        self.last_written_w: float | None = None
        self._store = store
        #: nothing to adopt when nothing was persisted
        self._adopted: bool = store is None

    async def apply(self, hass, entity_id: str, cap_w, *,
                    observer: bool) -> str:
        """Returns a short action token:
        wrote|held|restored|idle|observer|no_limit_entity|limit_unreadable."""
        if not observer:
            await self._adopt(hass, entity_id)
        if not entity_id:
            # (#949) "nothing to pace" and "a cap, and nowhere to put it" are
            # different facts, and they shared the ``idle`` token. A PROD
            # install ran a whole day with the switch on, a computed 403 W
            # cap, a reason reading "paced to land full at day's end" — and
            # the battery at 3 kW, because no charge-limit entity was ever
            # confirmed. The only tell was a null attribute. #925's rule:
            # "I could not act" is its own value.
            return "no_limit_entity" if cap_w is not None else "idle"
        if cap_w is None:
            if self.engaged:
                if observer:
                    # (#949, ruflo REFUTED the first version) Stand down
                    # WITHOUT forgetting. The record on disk is the truth and
                    # this object is its cache: before this, flipping observer
                    # on mid-engagement dropped the in-memory capture, left
                    # the record alone and kept the writer marked adopted — so
                    # the next real cycle re-captured the live register, which
                    # still held SEM's own cap, and persisted THAT as the
                    # hardware maximum. The exact bug this change exists to
                    # kill, through the observer seam and with no restart:
                    # one toggle of a switch the user is invited to use.
                    self.engaged = False
                    self.engaged_entity = ""
                    self.restore_value = None
                    self.last_written_w = None
                    self._adopted = self._store is None
                    return "observer"
                value = self.restore_value
                self.engaged = False
                self.engaged_entity = ""
                self.restore_value = None
                self.last_written_w = None
                if value is None:
                    # Nothing to put back, and no way left to learn it. Keep
                    # the record: erasing it would remove the only trace that
                    # a register is still being held down (#949 review).
                    return "idle"
                await self._forget()
                await hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": entity_id, "value": float(value)},
                    blocking=False)
                return "restored"
            return "idle"
        if observer:
            return "observer"
        if not self.engaged:
            # The capture is the ONLY way back, so a register whose prior
            # value cannot be read is a register SEM must not write. Before
            # this the cap went on anyway and the restore was silently
            # skipped for good (#949 review).
            baseline = _read_number(hass, entity_id)
            if baseline is None:
                return "limit_unreadable"
            self.restore_value = baseline
            self.engaged_entity = str(entity_id)
            self.engaged = True
        if (self.last_written_w is not None
                and abs(cap_w - self.last_written_w) < 100.0):
            return "held"
        self.last_written_w = float(cap_w)
        # Persisted BEFORE the write, and on every write: the record has to
        # describe a register that may already carry the cap, never one that
        # might not. The cap rides along so the next lifetime knows which
        # value on the register is its own.
        await self._remember(entity_id)
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": entity_id, "value": float(cap_w)},
            blocking=False)
        return "wrote"

    # ─── the engagement, across lifetimes (#949) ───────────────────────

    async def _adopt(self, hass, entity_id: str) -> None:
        """Take over the engagement a previous lifetime left on the inverter
        instead of discovering it as though it were the user's own setting.

        Runs once, on the first cycle that could write.
        """
        if self._adopted:
            return
        self._adopted = True
        record = await self._load()
        if not isinstance(record, dict):
            return
        stored = str(record.get("entity_id") or "")
        if not stored:
            return
        restore = _as_float(record.get("restore_value"))
        if stored != str(entity_id or ""):
            # SEM does not pace that entity any more — the user repointed the
            # setting, or cleared it. Hand the register back before letting
            # go of the record, or the cap stays on an entity nobody watches.
            _LOGGER.info(
                "charge pacing: releasing %s — it is no longer the "
                "charge-limit entity (restoring %s)", stored, restore)
            if restore is not None:
                await hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": stored, "value": float(restore)},
                    blocking=False)
            await self._forget()
            return
        self.engaged = True
        self.engaged_entity = stored
        self.restore_value = restore
        self.last_written_w = _as_float(record.get("cap_w"))
        _LOGGER.info(
            "charge pacing: adopted the cap this install was left with — "
            "%s at %s W, restores to %s W",
            stored, self.last_written_w, self.restore_value)

    async def _load(self):
        if self._store is None:
            return None
        try:
            return await self._store.async_load()
        except Exception:  # noqa: BLE001 — a lost record is not a lost cycle
            _LOGGER.debug("charge pacing: engagement record unreadable",
                          exc_info=True)
            return None

    async def _remember(self, entity_id: str) -> None:
        if self._store is None:
            return
        try:
            await self._store.async_save({
                "entity_id": str(entity_id),
                "restore_value": self.restore_value,
                "cap_w": self.last_written_w,
            })
        except Exception:  # noqa: BLE001 — persistence never costs a cycle
            _LOGGER.debug("charge pacing: could not persist the engagement",
                          exc_info=True)

    async def _forget(self) -> None:
        if self._store is None:
            return
        try:
            await self._store.async_remove()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("charge pacing: could not clear the engagement",
                          exc_info=True)


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_number(hass, entity_id: str) -> float | None:
    """The entity's value as a number, or None when it cannot be read at all
    (missing, unavailable, unknown, non-numeric)."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return _as_float(getattr(state, "state", None))


def pending_pacing_release(coordinator) -> tuple | None:
    """(#949) What a still-engaged pacer is holding down, as
    ``(entity_id, restore_value, store)``, or None.

    Read at UNLOAD, where the coordinator is about to go away: a config entry
    that is disabled or removed has no next lifetime to adopt the engagement,
    so the register would keep SEM's cap with nothing left that knows why.
    The battery adapters have had this since #936; the pacer writes a
    user-named ``number`` directly and was not in that path.
    """
    writer = getattr(coordinator, "_charge_pacing_writer", None)
    if writer is None or not getattr(writer, "engaged", False):
        return None
    entity = str(getattr(writer, "engaged_entity", "") or "")
    value = _as_float(getattr(writer, "restore_value", None))
    if not entity or value is None:
        return None
    return (entity, value, getattr(writer, "_store", None))


async def async_release_pacing(hass, held: tuple | None, reason: str) -> str | None:
    """Put the captured maximum back and drop the record. Never raises."""
    if not held:
        return None
    entity, value, store = held
    try:
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": entity, "value": float(value)}, blocking=False)
    except Exception:  # noqa: BLE001 — an unload must not fail on this
        _LOGGER.warning("charge pacing: could not release %s on %s",
                        entity, reason)
        return None
    if store is not None:
        try:
            await store.async_remove()
        except Exception:  # noqa: BLE001
            pass
    return f"charge limit {entity} restored to {value:.0f} W ({reason})"


def today_remaining_slots(*, now, sunrise, sunset, day_kwh, home_w_at,
                          builder, price_at=None, level_cheap_at=None,
                          export_rate: float = 0.0):
    """Today's remaining day, [now, sunset), in the planner's slot shape.

    The PROD campaign (26.08 morning) caught pacing hooked to the tomorrow
    PREVIEW ledger — a night-only artifact. It solved a correct cap on
    tomorrow's books at 23:00 and had nothing to read in the hours it is
    meant to act. This is the daytime source.

    ``day_kwh`` is the FULL day's forecast, not the remaining kWh: the day
    builder distributes the total over the solar curve between sunrise and
    sunset and tiles only [start, end), so the window naturally receives
    the remaining fraction. Passing the remaining kWh as the total would
    hand the window only the curve's fraction of it — under-counting the
    afternoon and pacing too tight.
    """
    if day_kwh is None or day_kwh <= 0:
        return []
    if now < sunrise or now >= sunset:
        return []
    return builder(
        start=now, end=sunset, day_kwh=float(day_kwh),
        sunrise=sunrise, sunset=sunset, home_w_at=home_w_at,
        # (#924) Pacing reads surplus WATTS and never a price, so this
        # changes nothing today. It is threaded because the builder it
        # calls prices with it, and a builder handed no rate prices the
        # sun at zero — the #755 defect, one call site over.
        export_rate=float(export_rate or 0.0),
        **({"price_at": price_at} if price_at else {}),
        **({"level_cheap_at": level_cheap_at} if level_cheap_at else {}),
    )
