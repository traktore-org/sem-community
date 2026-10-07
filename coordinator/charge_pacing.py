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
import time
from dataclasses import dataclass
from typing import Any, Optional

from ..utils.log_gate import log_on_change

_LOGGER = logging.getLogger(__name__)

#: (#820, 02.10) At most one cap write per this many seconds. The release to
#: full power below the buffer is exempt: it goes at once.
PACING_MIN_WRITE_INTERVAL_S = 300.0
#: (#820) A write is judged refused only when the register has not moved
#: for this long AND for this many cycles — a Modbus read-back is a scan late.
PACING_REFUSE_AFTER_S = 90.0
PACING_REFUSE_AFTER_CYCLES = 3

#: (#820) The margin the solved pace is opened by, in percent. The solver
#: finds the SMALLEST constant cap that lands the pack full in the last
#: remaining slot — zero slack by construction. A real evening that comes in
#: under the model (forecast high, house or EV heavier than modelled) then
#: strands the pack, and the per-cycle re-solve asks for a cap the remaining
#: sun cannot deliver. @ArneGollin1987 measured exactly this on a 2×10 kW
#: install and proposed +10 %. Not user-facing: the option surface only
#: shrinks (#830), and a margin is a property of the solver, not a preference.
PACING_HEADROOM_PCT: float = 10.0


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
    drain_kwh: float = 0.0
    """(#820) kWh the house takes back OUT of the pack in the deficit hours
    before sunset — an afternoon cloud, a midday EV session. The SOC curve
    the user sees always modelled it; the cap did not, so a paced day that
    lost 1 kWh at 15:00 was solved as if it had not. Part of the bill now."""
    headroom_pct: float = 0.0
    """(#820) The fixed margin the solved cap is opened by. The bisection
    lands the pack full in the LAST slot exactly; a real evening that comes
    in 10 % under the model then strands the pack, and the per-cycle
    re-solve raises a cap the remaining sun cannot deliver. Not a knob:
    the option surface only shrinks (#830), and 10 % is what the reporter
    proposed."""


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


def _drain_kwh(ledger) -> float:
    """(#820) kWh the house will draw OUT of the pack before the ledger ends.

    ``build_day_slots`` shapes a DEFICIT hour (solar below the house) as a
    slot with no ``cap_override_w`` and the net draw in ``home_w``; the
    battery covers that draw, so it is energy the pace has to earn back.
    ``provisional_soc_curve`` has always walked it; the cap solver summed
    surplus only and read those hours as zero. Ledgers without ``home_w``
    (older shapes, test fixtures) read as a day with no drain.
    """
    total = 0.0
    for s in ledger:
        if getattr(s, "cap_override_w", None) is not None:
            continue
        total += max(0.0, float(getattr(s, "home_w", 0.0) or 0.0)) * s.hours / 1000.0
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

    # (#820) The whole bill: what the pack still needs PLUS what the house
    # will take back out of it in the deficit hours before sunset. The SOC
    # curve always modelled that drain; the cap was solved without it, so a
    # paced day that lost a kWh to an afternoon cloud was solved as if it
    # had not — and the evening "could not reach the pacing watts".
    drain_kwh = min(_drain_kwh(ledger), max(0.0, capacity_kwh - need_kwh))
    need_kwh += drain_kwh

    fill_kwh = _fill_kwh(ledger, hw_max_charge_w)
    if fill_kwh < need_kwh:
        return PacingDecision(
            None, "the day cannot fill the pack even uncapped — a cap "
                  "only makes it worse", code="weak_day",
            need_kwh=round(need_kwh, 2), fill_kwh=round(fill_kwh, 2),
            drain_kwh=round(drain_kwh, 2))

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
    # (#820) The margin. The bisection lands the pack full in the LAST slot
    # exactly; open the cap by PACING_HEADROOM_PCT so an evening that comes
    # in under the model still lands it, never past the hardware.
    cap = min(hw_max_charge_w, cap * (1.0 + PACING_HEADROOM_PCT / 100.0))

    # Clipping guard: any slot whose surplus exceeds the AC limit is energy
    # that cannot leave the roof — open the cap far enough to absorb the
    # worst predicted clip on top of the pace.
    reason = (f"paced to land full at day's end, {PACING_HEADROOM_PCT:.0f} % "
              "in hand for an evening under the model")
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
                          need_kwh=round(need_kwh, 2), fill_kwh=round(fill_kwh, 2),
                          drain_kwh=round(drain_kwh, 2),
                          headroom_pct=PACING_HEADROOM_PCT)


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
    * (#820, 01.10) the REGISTER is the truth, not SEM's memory of what it
      sent: every cap is clamped to the entity's own min/max/step and unit
      (Home Assistant refuses an out-of-range ``number.set_value``, and a
      non-blocking call never hears it), the repeat check compares with
      what the register holds (100 W, or one step if coarser), and a
      write the register never takes is reported as ``write_refused`` —
      once, never re-sent every cycle (#538), and only while the register
      is away from the cap SEM wants now (a verdict is about one write);
    * a release gives the pack the larger of the captured value and the
      hardware maximum, clamped to the register: below the buffer means
      full power, and a capture of SEM's own cap is never taken for the
      user's setting;
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
        #: (#820) did the register ever show ``last_written_w``? Until it
        #: does, a mismatch is a write that may still be on the bus.
        self._confirmed: bool = False
        #: (#820) cycles the register has not shown an unconfirmed write
        self._unconfirmed_cycles: int = 0
        #: (#820) the last cap SEM put on the register, kept across a
        #: release — a register still holding it is SEM's, not the user's
        self._own_cap_w: float | None = None
        #: (#820, 02.10) the register just before the last write, when it
        #: was sent, and what it read once it took the write
        self._pre_write_w: float | None = None
        self._write_at: float | None = None
        self._accepted_w: float | None = None
        #: None = pending, True = taken, False = refused
        self._taken: bool | None = None
        #: (#820, 02.10) ``(register_w, written_w)`` when the register took
        #: the write but settled on another value (a unit scale in the
        #: integration, or the inverter's own limit); None otherwise
        self.applied_differs: tuple[float, float] | None = None
        #: (#820) the previous in-band read, for the settle check
        self._last_in_band_w: float | None = None
        #: (#820, review 3) the record must be re-saved: a verdict changed
        self._record_dirty: bool = False
        #: (#820, review 3) the first reading after adoption still has to
        #: prove the register — a cap from disk is not a cap on the wire
        self._adopt_check: bool = False
        self._clock = time.monotonic
        self._store = store
        #: nothing to adopt when nothing was persisted
        self._adopted: bool = store is None

    def _release_state(self) -> None:
        """Pacing no longer holds the register."""
        self.engaged = False
        self.engaged_entity = ""
        self.restore_value = None
        self.last_written_w = None
        self._confirmed = False
        self._unconfirmed_cycles = 0
        self._pre_write_w = None
        self._write_at = None
        self._accepted_w = None
        self._taken = None
        self.applied_differs = None
        self._last_in_band_w = None
        self._adopt_check = False

    async def apply(self, hass, entity_id: str, cap_w, *,
                    observer: bool, hw_max_w: float | None = None) -> str:
        """Returns a short action token: wrote|held|write_refused|restored|
        idle|observer|no_limit_entity|limit_unreadable.

        ``hw_max_w`` is the battery's full charge power: what a release
        gives back when the captured value is lower (#820)."""
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
                # (#820) Below the buffer is full power. Arne's register read
                # 1560 W when pacing engaged, so 1560 was "the value to put
                # back" and the pack never got its maximum. Give back the
                # larger of the capture and the hardware maximum, clamped
                # to what the register can take.
                candidates = [v for v in (self.restore_value, hw_max_w)
                              if v is not None and v > 0]
                if not candidates:
                    # Nothing to put back, and no way left to learn it. Keep
                    # the record: erasing it would remove the only trace that
                    # a register is still being held down (#949 review).
                    self._release_state()
                    return "idle"
                prepared = _fit(hass, entity_id, max(candidates))
                if prepared is None:
                    # The register cannot be read right now (a Modbus blip).
                    # Stay engaged so the next cycle tries the release again
                    # and unload still knows a cap is held (#820 review).
                    return "limit_unreadable"
                self._release_state()
                native, _watts = prepared
                await self._forget()
                await hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": entity_id, "value": native},
                    blocking=False)
                return "restored"
            return "idle"
        if observer:
            return "observer"
        prepared = _fit(hass, entity_id, float(cap_w), ceiling=True)
        if prepared is None:
            # Not a power register SEM can scale to (or unreadable): the
            # capture would be wrong and the write would be refused.
            return "limit_unreadable"
        native, target_w = prepared
        register_w = _read_watts(hass, entity_id)
        if register_w is None:
            return "limit_unreadable"
        if not self.engaged:
            # The capture is the ONLY way back, so a register whose prior
            # value cannot be read is a register SEM must not write (#949
            # review). (#820) A register still holding SEM's own last cap is
            # not the user's setting: capture nothing, and the release falls
            # back to the hardware maximum.
            own = self._own_cap_w
            self.restore_value = (
                None if own is not None and abs(register_w - own) < 1.0
                else register_w)
            self.engaged_entity = str(entity_id)
            self.engaged = True
        step_w = _step_w(hass, entity_id)
        # (#820, 02.10) The deadband: a cap is rewritten only for a real
        # difference — more than one step, 100 W or 5 % of the cap. Arne's
        # cap jittered 1150↔1158 and SEM rewrote the register every few
        # seconds.
        deadband = max(step_w, 100.0, 0.05 * target_w)
        now = self._clock()
        if self.last_written_w is None:
            if abs(register_w - target_w) <= deadband:
                return "held"
            return await self._write(hass, entity_id, native, target_w,
                                     register_w, now)
        verdict = self._judge(entity_id, register_w, step_w, deadband, now)
        if self._record_dirty:
            # the accepted value and the settled difference ride the record,
            # so the next lifetime adopts a PROVEN register (review 3)
            self._record_dirty = False
            await self._remember(entity_id)
        first_after_adoption = self._adopt_check
        self._adopt_check = False
        # (#820, 06.10, bug class 83) The register already holds the cap SEM
        # wants NOW — inside the same deadband every write is gated on.
        at_wish = abs(register_w - target_w) <= deadband
        if verdict == "pending":
            if first_after_adoption:
                restore = self.restore_value
                if at_wish and (restore is None
                                or abs(register_w - restore) >= 1.0):
                    # The cap from disk is not on the register, but what
                    # SEM wants is: nothing to write. Writing it anyway
                    # sent the register its own value, which can never
                    # read as taken (review, 06.10). Never when it holds
                    # the value to put back (an inverter rebooted to the
                    # user's setting): saved as SEM's cap, the #949 own-cap
                    # rule would erase it from the record (review 3, 06.10).
                    await self._take_register(entity_id, register_w)
                    return "held"
                # (review 3) The first reading after adoption is out of the
                # band. If it also left the value the register had settled
                # at, someone moved it while SEM was away (down, or
                # observing): one rewrite, and the interval does not apply.
                acc = self._accepted_w
                if acc is None or abs(register_w - acc) > deadband:
                    return await self._write(hass, entity_id, native,
                                             target_w, register_w, now)
            return "held"
        if at_wish:
            # A verdict is about ONE write, ``last_written_w``; the action
            # says what pacing is doing. Arne's register sat at 1700 W, the
            # cap SEM wanted, while the card said "the inverter refused the
            # limit" — about an older write that was lost. The verdict
            # itself stays: the 02.10 rule (a refused cap is not sent
            # again) is keyed to it, and the register being at the wish
            # says nothing about whether it takes writes.
            return "held"
        # (#820, 02.10, decision) SEM rewrites when (a) the NEW cap differs
        # from the last SENT cap by more than the deadband — a refused cap
        # included — or (b) the register has moved away from the value it
        # settled at (Arne's 1449) by more than the deadband: someone else
        # changed it. It does NOT rewrite merely because the register sits
        # at its accepted value and that is not the cap — the inverter
        # applied its own number, and that is not a refusal.
        wish_changed = abs(target_w - self.last_written_w) > deadband
        moved_by_someone = (
            self._taken is True and self._accepted_w is not None
            and abs(register_w - self._accepted_w) > deadband)
        settled = "held" if self._taken else "write_refused"
        if not (wish_changed or moved_by_someone):
            return settled
        if (self._write_at is not None
                and now - self._write_at < PACING_MIN_WRITE_INTERVAL_S):
            return settled
        return await self._write(hass, entity_id, native, target_w,
                                 register_w, now)

    def _judge(self, entity_id: str, register_w: float, step_w: float,
               deadband: float, now: float) -> str:
        """(#820, 02.10) Did the register take the last write?

        TAKEN only when the register is IN THE BAND — within one step, 10 %
        of what SEM sent or 100 W, whichever is widest (Arne: wrote 1550 W,
        reads 1449 W; the inverter applied its own number, and that is not
        a refusal) — AND has CHANGED since the write. The rewrite rule in
        ``apply`` keeps a taken-but-different value from being rewritten
        every interval. A reading equal to the pre-write value is "no
        change yet": a Modbus register that has not been scanned since the
        write (review pass 2: 4600 read back twice after a 5000 write was
        judged taken, then "took the write as 4600 W" — before the hardware
        did anything). It only ages the pending window. A register that
        moved but is not in the band is PENDING too (a drift of the
        device's own has no link to SEM's write). REFUSED when the window
        (3 cycles and 90 s) ends and it never entered the band. A late
        entry into the band is taken from then on."""
        sent = self.last_written_w
        pre = self._pre_write_w
        changed = pre is None or abs(register_w - pre) >= 1.0
        band = max(step_w, 0.10 * sent, 100.0)
        in_band = abs(register_w - sent) <= band
        if in_band and changed:
            if self._taken is not True:
                self._taken = True
                self._accepted_w = register_w
                self._record_dirty = True
                self._confirm(entity_id)
            self._settle(entity_id, register_w, sent, step_w)
            return "taken"
        self._last_in_band_w = None
        if self._taken is True:
            return "taken"
        if self._taken is False:
            return "refused"
        self._unconfirmed_cycles += 1
        waited = (self._write_at is None
                  or now - self._write_at >= PACING_REFUSE_AFTER_S)
        if self._unconfirmed_cycles < PACING_REFUSE_AFTER_CYCLES or not waited:
            return "pending"
        self._taken = False
        log_on_change(
            _LOGGER, f"charge_pacing:refused:{entity_id}", logging.WARNING,
            "charge pacing: %s refused the cap — SEM wrote %.0f W, the "
            "register still reads %.0f W. Check the entity's range and "
            "that the inverter accepts writes.",
            entity_id, sent, register_w)
        return "refused"

    def _settle(self, entity_id: str, register_w: float, sent: float,
                step_w: float) -> None:
        """``applied_differs`` only when the register SETTLED inside the
        band — the same value on two consecutive reads, both different from
        the pre-write value (the caller guarantees that) — more than a step
        from what was sent (Arne: wrote 1550 W, reads 1449 W). Said once;
        visible in Diagnose."""
        if self.applied_differs is not None:
            return
        prev = self._last_in_band_w
        self._last_in_band_w = register_w
        if prev is None or abs(prev - register_w) >= 1.0:
            return
        if abs(register_w - sent) > max(step_w, 1.0):
            self.applied_differs = (register_w, sent)
            self._record_dirty = True
            log_on_change(
                _LOGGER, f"charge_pacing:applied:{entity_id}",
                logging.WARNING,
                "charge pacing: %s took the write as %.0f W, not %.0f W "
                "— check the integration's unit and the inverter's own "
                "limit", entity_id, register_w, sent)

    async def _write(self, hass, entity_id: str, native: float,
                     target_w: float, register_w: float, now: float) -> str:
        self.last_written_w = target_w
        self._own_cap_w = target_w
        self._confirmed = False
        self._unconfirmed_cycles = 0
        self._pre_write_w = register_w
        self._write_at = now
        self._accepted_w = None
        self._taken = None
        self.applied_differs = None
        self._last_in_band_w = None
        self._adopt_check = False
        # Persisted BEFORE the write, and on every write: the record has to
        # describe a register that may already carry the cap, never one that
        # might not. The cap rides along so the next lifetime knows which
        # value on the register is its own.
        await self._remember(entity_id)
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": entity_id, "value": native},
            blocking=False)
        return "wrote"

    async def _take_register(self, entity_id: str, register_w: float) -> None:
        """(#820, 06.10, bug class 83) First cycle after adoption: the cap
        from disk is not on the register, but the register holds a value
        inside the deadband of the cap SEM wants now. That value becomes
        SEM's cap, as if written and seen taken; no write goes out.

        Only here, where no write of this lifetime was judged: writing the
        register its own value can never read as taken (it does not
        change), so a healthy inverter was "refusing" 90 s later. A cap
        REFUSED in this lifetime is never retired this way — the 02.10
        rule that it is not sent again is keyed to that verdict."""
        self.last_written_w = register_w
        self._own_cap_w = register_w
        self._pre_write_w = None
        self._accepted_w = register_w
        self._taken = True
        self.applied_differs = None
        self._last_in_band_w = None
        self._confirm(entity_id)
        await self._remember(entity_id)

    def _confirm(self, entity_id: str) -> None:
        """The register shows SEM's cap: a refusal, if one was logged, is
        over. The gate logs the change once."""
        if not self._confirmed and self._unconfirmed_cycles >= 2:
            log_on_change(
                _LOGGER, f"charge_pacing:refused:{entity_id}", logging.INFO,
                "charge pacing: %s now holds the cap", entity_id)
        self._confirmed = True
        self._unconfirmed_cycles = 0

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
            prepared = _fit(hass, stored, restore) if restore is not None else None
            if prepared is not None:
                await hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": stored, "value": prepared[0]},
                    blocking=False)
            await self._forget()
            return
        self.engaged = True
        self.engaged_entity = stored
        self.restore_value = restore
        self.last_written_w = _as_float(record.get("cap_w"))
        self._own_cap_w = self.last_written_w
        # (#820, review 3) A cap from disk is not a cap on the wire: the
        # register may have been moved while SEM was down or observing.
        # Taken is UNKNOWN until the first reading proves in-band against
        # the persisted cap (no pre-write value, so in-band is the whole
        # proof); the value the register had settled at, and the settled
        # difference, come back from the record so the first reading can
        # also be judged "moved by someone".
        self._taken = None
        self._accepted_w = _as_float(record.get("accepted_w"))
        _ad = record.get("applied_differs")
        self.applied_differs = (
            (float(_ad[0]), float(_ad[1]))
            if isinstance(_ad, (list, tuple)) and len(_ad) == 2
            and _as_float(_ad[0]) is not None and _as_float(_ad[1]) is not None
            else None)
        self._pre_write_w = None
        self._write_at = None
        self._unconfirmed_cycles = 0
        self._adopt_check = self.last_written_w is not None
        # (#820) a record whose "value to restore" is SEM's own cap (a
        # capture from before #949) is no value to restore at all
        if (restore is not None and self.last_written_w is not None
                and abs(restore - self.last_written_w) < 1.0):
            self.restore_value = None
            # (#820 review 5) the correction must reach the disk, or an
            # unload that reads the record hands SEM's own cap back
            await self._remember(stored)
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
                # (#820, review 3) what the register settled at, and the
                # settled difference — so adoption trusts a proven value
                "accepted_w": self._accepted_w,
                "applied_differs": (list(self.applied_differs)
                                    if self.applied_differs else None),
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


def _scale(hass, entity_id: str) -> float | None:
    from .power_control import native_power_scale
    scale = native_power_scale(hass, entity_id)
    return scale if scale is not None and scale > 0 else None


def _read_watts(hass, entity_id: str) -> float | None:
    """The register's value in watts, or None when it cannot be read."""
    value = _read_number(hass, entity_id)
    scale = _scale(hass, entity_id)
    if value is None or scale is None:
        return None
    return value * scale


def _step_w(hass, entity_id: str) -> float:
    state = hass.states.get(entity_id)
    attrs = getattr(state, "attributes", None) if state is not None else None
    scale = _scale(hass, entity_id)
    if not isinstance(attrs, dict) or scale is None:
        return 0.0
    step = _as_float(attrs.get("step"))
    return step * scale if step and step > 0 else 0.0


def _fit(hass, entity_id: str, watts: float, *, ceiling: bool = False):
    """(#820) ``(native value, watts)`` the register can take, or None.

    Scaled to the entity's unit and clamped to its range by the ONE shared
    clamp (``power_control.clamp_to_entity_range``, #523). A cap is a
    ceiling, so it rounds DOWN to the step."""
    from .power_control import clamp_to_entity_range
    scale = _scale(hass, entity_id)
    if scale is None:
        return None
    state = hass.states.get(entity_id)
    attrs = getattr(state, "attributes", None) if state is not None else None
    fitted = clamp_to_entity_range(attrs, float(watts), scale,
                                   round_down_to_step=ceiling)
    return round(fitted / scale, 6), fitted


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
    if not entity:
        return None
    # (#820 review 5) "engaged, nothing to restore" is its own answer —
    # ``(entity, None, store)`` — so the disk is read only when the writer
    # is genuinely not engaged, never to override a corrected memory.
    value = _as_float(getattr(writer, "restore_value", None))
    return (entity, value, getattr(writer, "_store", None))


async def async_pending_pacing_release(coordinator) -> tuple | None:
    """(#820, review 4) What the pacer holds down, read from the RECORD when
    the writer's memory has nothing.

    A writer that saw only observer cycles in its lifetime (HA came up with
    observer on; "flip observer, then uninstall") never adopts the record,
    so ``pending_pacing_release`` finds no engagement and the unload hands
    nothing back — a real prior cap stays on the register forever, the
    #949 failure class reopened. The record on disk is the truth; this
    reads it. Observer cycles themselves stay fully read-only.

    The value put back is the release rule's: the larger of the captured
    value and the battery's full charge power. Never raises.
    """
    config = getattr(coordinator, "config", None) or {}
    try:
        hw_max = _as_float(config.get("battery_max_charge_power_w"))
    except Exception:  # noqa: BLE001
        hw_max = None

    def _value(restore):
        candidates = [v for v in (restore, hw_max) if v is not None and v > 0]
        return max(candidates) if candidates else None

    held = pending_pacing_release(coordinator)
    if held:
        entity, value, store = held
        value = _value(value)
        return (entity, value, store) if value is not None else None
    writer = getattr(coordinator, "_charge_pacing_writer", None)
    store = getattr(writer, "_store", None) if writer is not None else None
    if store is None:
        factory = getattr(coordinator, "_charge_pacing_store", None)
        try:
            store = factory() if callable(factory) else None
        except Exception:  # noqa: BLE001
            store = None
    if store is None:
        return None
    try:
        record = await store.async_load()
    except Exception:  # noqa: BLE001 — a lost record is not a lost unload
        return None
    if not isinstance(record, dict):
        return None
    entity = str(record.get("entity_id") or "")
    restore = _as_float(record.get("restore_value"))
    cap = _as_float(record.get("cap_w"))
    if restore is not None and cap is not None and abs(restore - cap) < 1.0:
        # the #949 own-cap rule, on the disk copy too: a record whose
        # value to restore is SEM's own cap restores nothing but the
        # hardware maximum
        restore = None
    value = _value(restore)
    if not entity or value is None:
        return None
    return (entity, value, store)


async def async_release_pacing(hass, held: tuple | None, reason: str) -> str | None:
    """Put the captured maximum back and drop the record. Never raises."""
    if not held:
        return None
    entity, value, store = held
    if value is None:
        return None  # engaged, nothing to put back: keep the record
    try:
        # (#820) the captured value is in watts; the register takes its own
        # unit and range
        prepared = _fit(hass, entity, float(value))
        if prepared is None:
            # The register cannot be read now (unavailable, no unit). A raw
            # watt value could land 1000x off on a kW register, and a
            # refused write goes unheard. Keep the record: the next
            # lifetime adopts it and releases then (#949, #820 review).
            _LOGGER.warning(
                "charge pacing: %s unreadable on %s — the limit stays held "
                "and is released at the next start", entity, reason)
            return None
        native = prepared[0]
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": entity, "value": native}, blocking=False)
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
