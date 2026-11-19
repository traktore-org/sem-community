"""(#1362) A battery HELD by a select, not by a discharge limit.

Some inverters have no discharge-limit number; only a mode select with an
option that stops the battery giving (the loads run from the grid and the
battery rests). The user names the select and that option. SEM sets it to
hold the battery for a dearer hour and puts it back to what it showed before.

Asleep until BOTH settings are set, and only when no discharge-limit entity
is set: that number is the better control and keeps its own path.

A select says yes or no, never "500 W": SEM holds only when the decision is
0 W. Any other limit releases the hold, and the adapter says it cannot cap.

The record is ``ForcedChargeRecord`` (#1181), a second file: the same
prior-before-write rule and shared owners per pack, apart from the grid
charge's, so one restore never blocks the other (class 183).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from homeassistant.util import dt as dt_util

from ...utils.log_gate import log_on_change
from ...utils.select_option import listed_option
from .charge_record import ForcedChargeRecord
from .charge_select import SELECT_KEY as CHARGE_SELECT_KEY, read_select

_LOGGER = logging.getLogger(__name__)

HOLD_SELECT_KEY = "battery_hold_select_entity"
HOLD_OPTION_KEY = "battery_hold_select_option"
RECORD_KEY = "battery_hold_record"

#: what a hold that is waiting is answered with: not an error
SETTLING = "settling"

# The numbers below are limits on how hard SEM leans on a select. WHY: a
# mode select is often a cloud call, and some inverters keep a mode in
# flash memory that wears with every write; a limit that moves between 0 W
# and a cover must never turn into one write per cycle.

#: a hold, once set, stays at least this long, and a release waits as long
#: after a hold (Off, unload and a restore after a refusal never wait)
MIN_HOLD_S = 30 * 60.0
#: select writes SEM may make to the hold select in one local day (the
#: count is on disk and starts again at the day roll). A start over it
#: stays in the current option; a put-back is never held back by it: it
#: gives the battery back to the house (#1362).
MAX_WRITES_PER_DAY = 12
#: the select must show the hold option within this long after a write (a
#: cloud integration is slow); then ONE re-send, then the hold is refused
SHOW_WITHIN_S = 60.0
#: a battery that keeps discharging above this while the select shows the
#: hold option, for this long, ignores the hold: it is refused
DISCHARGE_REFUSE_W = 100.0
DISCHARGE_REFUSE_S = 5 * 60.0
#: after a refusal no hold is tried again for this long
REFUSAL_MEMORY_S = 24 * 3600.0


def hold_setup(config: dict) -> Optional[tuple]:
    """``(select entity, hold option)`` when both are set, else None. The
    grid charge's own select is never the hold select: one entity, two
    meanings, one record."""
    config = config or {}
    entity = str(config.get(HOLD_SELECT_KEY) or "").strip()
    option = str(config.get(HOLD_OPTION_KEY) or "").strip()
    if not entity or not option:
        return None
    if entity == str(config.get(CHARGE_SELECT_KEY) or "").strip():
        return None
    return entity, option


class SelectHold:
    """Holds one battery through the hold select and puts it back."""

    #: writes one hold may make: the write and ONE re-send
    WRITES_PER_ATTEMPT = 2
    #: the numbers, as attributes so a test can move them
    MIN_HOLD_S = MIN_HOLD_S
    SHOW_WITHIN_S = SHOW_WITHIN_S
    #: a record older than this is not acted on after a restart
    ORPHAN_MAX_AGE_H = 48.0

    def __init__(self, hass: Any, config: dict) -> None:
        self.hass, self.config = hass, config
        rec = config.get(RECORD_KEY)
        self.record = rec if isinstance(rec, ForcedChargeRecord) else ForcedChargeRecord()
        self.active = False
        #: a hold on this select was refused lately (read from the record)
        self.refused = False
        self._why = ""
        self._writes, self._seen, self._spent = 0, False, None
        self._wrote_at: Optional[float] = None
        self._discharging_since: Optional[float] = None
        self._adopted = False
        #: (#1362) the hold was asked for a grid charge: its put-back never
        #: waits for the minimum hold (that rule stops flip-flop, not a charge)
        self._for_charge = False

    def _battery(self) -> str:
        return str(self.config.get("battery_id", "") or "")

    def _fail(self, why: str) -> str:
        log_on_change(_LOGGER, f"hold_select:{self._battery()}", logging.WARNING,
                      "Battery: hold by select: %s (#1362)", why)
        return why

    def _since_write(self) -> float:
        at = self._wrote_at
        return float("inf") if at is None else time.monotonic() - at

    def _recent(self) -> bool:
        return self._since_write() < self.MIN_HOLD_S

    def forget(self) -> None:
        """The attempt ends: the next hold may write again."""
        self._writes, self._seen, self._spent = 0, False, None
        self._discharging_since = None
        self._for_charge = False

    @staticmethod
    def _day() -> str:
        return dt_util.now().date().isoformat()

    async def _select(self, entity: str, option: str) -> None:
        """The one select write: the option as the select lists it, counted
        for the day. Raises what the service raises."""
        await self.hass.services.async_call(
            "select", "select_option",
            {"entity_id": entity,
             "option": listed_option(self.hass, entity, option)})
        self._wrote_at = time.monotonic()
        await self.record.count_write(entity, self._day())

    async def _capped(self, entity: str) -> Optional[str]:
        """Text when today's writes to this select are used up."""
        if await self.record.writes_on(entity, self._day()) < MAX_WRITES_PER_DAY:
            return None
        return self._fail(f"{entity} has had {MAX_WRITES_PER_DAY} writes from "
                          "SEM today — it stays as it is until tomorrow")

    async def _read_refusal(self, entity: str) -> None:
        at = await self.record.refused_at(entity)
        self.refused = at is not None and (time.time() - at) < REFUSAL_MEMORY_S
        if at is not None and not self.refused:
            await self.record.clear_refusal(entity)

    async def hold(self, pack_w: Optional[float] = None,
                   for_charge: bool = False) -> Optional[str]:
        """None: the battery is held. ``SETTLING``: not yet, no error. Any
        other text: why it is not. ``pack_w`` is this battery's own power
        (SEM's sign: below 0 is discharge), for the check that the inverter
        keeps the hold. Nothing is written when the select cannot be read or
        does not list the option, and a select that shows it is not written."""
        chosen = hold_setup(self.config)
        if chosen is None:
            return "no hold select set"
        entity, option = chosen
        self._for_charge = for_charge
        await self._read_refusal(entity)
        if self.refused:
            await self._release(entity, option, urgent=True)
            return self._fail(
                f"{self._why or entity + ' did not hold the battery lately'}"
                " — no new hold for 24 h")
        state, options = read_select(self.hass, entity)
        if state is None:
            return self._fail(f"{entity} is unavailable — SEM cannot ask it, "
                              "so the battery is not held")
        wanted = listed_option(self.hass, entity, option)
        if wanted not in options:
            return self._fail(f"{entity} does not list '{option}'")
        if state == wanted:
            self._seen = self._seen or self._writes > 0
            return await self._join(entity, pack_w)
        return await self._not_shown(entity, option, wanted, state)

    def shows(self) -> bool:
        """(#1362) The hold select shows the hold option now."""
        chosen = hold_setup(self.config)
        if chosen is None:
            return False
        state, _ = read_select(self.hass, chosen[0])
        return state is not None and state == listed_option(self.hass, *chosen)

    async def _not_shown(self, entity: str, option: str, wanted: str,
                         state: str) -> Optional[str]:
        if self._spent:
            return self._spent
        if self._writes and self._seen:
            return await self._give_up(
                entity, f"{entity} went back to '{state}' by itself — SEM "
                "does not hold it again")
        if self._writes:                        # a write waits to be shown
            if self._since_write() < self.SHOW_WITHIN_S:
                return SETTLING
            if self._writes >= self.WRITES_PER_ATTEMPT:
                return await self._refuse(
                    entity, option, f"{entity} did not show '{wanted}' after "
                    "a second write — the hold is refused")
        elif self._recent() and not self._for_charge:
            return SETTLING
        capped = await self._capped(entity)
        return capped or await self._write(entity, wanted, state)

    async def _join(self, entity: str, pack_w: Optional[float]) -> Optional[str]:
        """The select shows the option. A hold SEM's record names (another
        pack's) gains this pack as an owner; any other is the user's and is
        left alone. A hold of SEM's is watched against the pack's own power."""
        if await self.record.prior_of(entity) is None:
            self.active = False
            return None
        if not await self.record.started(entity, self._battery()):
            return self._fail("SEM could not save its record")
        self.active = True
        return await self._watch(entity, pack_w)

    async def _watch(self, entity: str, pack_w: Optional[float]) -> Optional[str]:
        """A battery that goes on discharging while the select shows the hold
        option is not held: after ``DISCHARGE_REFUSE_S`` the hold is refused.
        No reading keeps the count; a pack under the limit ends it."""
        if pack_w is None:
            return None
        if pack_w >= -DISCHARGE_REFUSE_W:
            self._discharging_since = None
            return None
        now = time.monotonic()
        if self._discharging_since is None:
            self._discharging_since = now
        if now - self._discharging_since < DISCHARGE_REFUSE_S:
            return None
        option = (hold_setup(self.config) or ("", ""))[1]
        return await self._refuse(
            entity, option, f"{entity} shows the hold option but the battery "
            f"still gives {abs(pack_w):.0f} W — the hold is refused")

    async def _refuse(self, entity: str, option: str, why: str) -> str:
        """The inverter does not keep the hold: no new hold for 24 h, and the
        select goes back to what it showed before."""
        await self.record.refuse(entity)
        self.refused, self._why = True, why
        await self._release(entity, option, urgent=True)
        return self._fail(why)

    async def _give_up(self, entity: str, why: str) -> str:
        self._spent = why
        self.active = False
        await self.record.left(entity, self._battery())
        return self._fail(why)

    async def _write(self, entity: str, wanted: str, state: str) -> Optional[str]:
        retry = self._writes > 0
        if not retry:
            await self.record.stopped(entity)   # a name from a hold that ended
            saved = await self.record.started(
                entity, self._battery(), prior=state, option=wanted)
            if not saved:                       # saved BEFORE the write
                return self._fail("SEM could not save its record")
        try:
            await self._select(entity, wanted)
        except Exception as exc:  # noqa: BLE001
            if read_select(self.hass, entity)[0] != wanted:
                await self.record.left(entity, self._battery())
            return self._fail(f"write failed: {exc}")
        self._writes += 1
        self._discharging_since = None
        self.active = True
        return None

    async def release(self, urgent: bool = True) -> Optional[str]:
        """Put the select back to what it showed before SEM's hold, but only
        while it still shows the hold option: a choice made by hand since is
        the user's. A select another pack still holds goes back with the
        last of them. None: nothing is left to put back. Not ``urgent``
        (normal, a partial limit) waits out the minimum hold and the day's
        write limit; Off, an unload and a refusal never wait."""
        chosen = hold_setup(self.config)
        urgent = urgent or self._for_charge     # (#1362) a charge's put-back
        self.forget()
        if chosen is None:
            return None
        entity, option = chosen
        return await self._release(entity, option, urgent)

    async def _release(self, entity: str, option: str, urgent: bool) -> Optional[str]:
        if not await self.record.running(entity, self._battery()):
            self.active = False
            return None
        # (#1362) a put-back gives the battery back to the house: the day's
        # write limit never holds it back, only the writes that take it away
        if not urgent and self._recent():
            return SETTLING
        if await self.record.others(entity, self._battery()):
            await self.record.left(entity, self._battery())
            self.active = False
            return None
        prior = await self.record.prior_of(entity)
        return await self._put_back(entity, option, prior or "")

    async def _put_back(self, entity: str, option: str, prior: str) -> Optional[str]:
        state, options = read_select(self.hass, entity)
        if state is None:
            return self._fail(f"{entity} is unavailable — it is put back "
                              "when it answers")
        if state == listed_option(self.hass, entity, option):
            if prior not in options:
                return self._fail(f"{entity} no longer lists '{prior}' — "
                                  "the battery stays held until you set it")
            try:
                await self._select(entity, prior)
            except Exception as exc:  # noqa: BLE001
                return self._fail(f"put back failed: {exc}")
        await self.record.stopped(entity)
        self.active = False
        return None

    async def adopt(self) -> None:
        """Before the decisions after a restart: a hold SEM's record names
        for this pack, still shown by the select, is active again, so the
        unload hand-back and the next release see it. Reads only; asked
        again until the select can be read."""
        chosen = hold_setup(self.config)
        if self._adopted or chosen is None:
            return
        entity, option = chosen
        if not await self.record.running(entity, self._battery()):
            self._adopted = True
            return
        state, _ = read_select(self.hass, entity)
        if state is None:
            return
        self._adopted = True
        if state == listed_option(self.hass, entity, option):
            self.active = True
        else:
            await self.record.left(entity, self._battery())

    async def restore_orphan(self, observer: bool = False) -> None:
        """A restart with the hold settings cleared: the record still names a
        select this pack turned to the hold option. Put it back once if it
        still shows that option, then drop the name. Observer mode sends
        nothing and keeps the record. Never raises."""
        if getattr(self, "_orphans_settled", False):
            return
        try:
            live = (hold_setup(self.config) or ("",))[0]
            for entity, prior, option in await self.record.select_records(
                    self._battery()):
                if entity != live and not await self._restore_one(
                        entity, prior, option, observer):
                    return                      # asked again next cycle
            self._orphans_settled = True
        except Exception:  # noqa: BLE001 — a record never costs a cycle
            _LOGGER.debug("orphan hold not restored", exc_info=True)

    async def _restore_one(self, entity: str, prior: str, option: str,
                           observer: bool) -> bool:
        """True: this record is settled (restored or nothing to do)."""
        state, options = read_select(self.hass, entity)
        if state is None or observer:
            return False
        age = await self.record.age_h(entity)
        if age is not None and age > self.ORPHAN_MAX_AGE_H:
            _LOGGER.warning("Battery: SEM's hold record for %s is %.0f h old — "
                            "dropped, the select is left as it is (#1362)",
                            entity, age)
            await self.record.stopped(entity)
            return True
        if await self.record.others(entity, self._battery()):
            await self.record.left(entity, self._battery())
            return True
        if option and state == listed_option(self.hass, entity, option):
            if prior not in options:
                self._fail(f"{entity} no longer lists '{prior}'")
                return False
            await self._select(entity, prior)
            _LOGGER.info("Battery: %s put back to '%s' after a restart with "
                         "the hold select unset (#1362)", entity, prior)
        await self.record.stopped(entity)
        return True
