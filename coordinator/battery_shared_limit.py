"""(#1178) One discharge limit entity, more than one battery: one writer.

Two batteries behind one inverter often share its one discharge limit (an
inverter-wide limit, two packs on one inverter, any home with two batteries
and one ``battery_discharge_control_entity``). #691 already counts such
batteries as one consumer of the house budget. But SEM decides each battery
on its own, and each adapter kept its own record of the limit it wrote.
Battery A held 0 W (it may not feed the car); battery B was NORMAL in the
same cycle and wrote the max into the same entity. A's record still said
0 W, so A never wrote again: the pack fed the car, and the discharge limit
sensor showed 0 W.

The rule, per entity and per cycle: ONE battery writes it.

1. a sale (FORCE_DISCHARGE): its hand-back lifts the limit (#1175), and a
   sale beats the car limit by choice (#533);
2. else the lowest LIMIT_DISCHARGE: a battery that may not feed the car is
   kept from it, and a battery that may is not harmed by the hold;
3. else NORMAL or STOP_FORCE_DISCHARGE (both write the max);
4. else OFF (its one hand-back on the way out).

Each battery counts by what its command will really write (``wish_of``): an
Off that has already spoken writes nothing, and a flip the actuator holds on
a blind cycle (#818) counts as the command still in force. Ties go to the
first battery in fleet order. A forced charge and its stop write no limit,
so they never write it for the others. A sale that did not go out this cycle
(``_sale_sent``: no sale entity, a sale withdrawn after refusals, a strategy
select that has not switched, #840, #978) gives the limit to the next
battery in line.

The other batteries still send their own commands (their setpoint, strategy
and forced ops); only their limit write is held back (``_limit_writer``).
They go first and the writer last: a device that must not take a write right
after a stop (``_sent_stop``) gets none from the writer that cycle. After the
cycle each of them takes the writer's record, so its own record is what the
entity holds: the same-limit skip, the sale's hand-back, the sensor and the
actuator's dwell all read the entity, not a value nobody holds any more.

(#1182) The sale power entity (``battery_force_discharge_control_entity``)
has the same shape. Battery A sold and wrote 3000 W; battery B was NORMAL
in the same cycle and wrote 0 W into the same entity (every mode zeroes it,
#523). A's record still said 3000 W, so A never wrote again: A showed a
sale while the entity read 0 W. One writer per entity per cycle here too:

1. a sale (the sale is the reason the entity is there);
2. else a forced charge on a bidirectional setpoint (its negative power);
3. else any other command (they all write 0 W).

Among the 0 W writers a battery ending a sale of its own goes first, so a
stop goes out with its own command (before the shared limit's writer, which
then gets its quiet cycle). Other ties go to the first battery in fleet
order. The others' writes are held back in ``_write_force_discharge``
(``_setpoint_writer``). A writer that did not leave its value in the entity
(``_setpoint_spoke``: a sale withheld for a strategy select, #978, a stop
with nothing to stop, #757, a blind cycle, #818, a refused write, #840)
gives the entity to the next battery in line that held a write back, until
one lands; a sale sent so marks ``_sale_sent`` by its own result. A sale
held back behind a sale that landed went out with it. After the cycle each
takes the writer's record.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Iterable, Optional

from .charger_types import BatteryIntent

_LIMIT = BatteryIntent.LIMIT_DISCHARGE
_SALE = BatteryIntent.FORCE_DISCHARGE

#: Which command writes the shared limit for the others — lower wins.
_RANK = {
    _SALE: 0,
    _LIMIT: 1,
    BatteryIntent.NORMAL: 2,
    BatteryIntent.STOP_FORCE_DISCHARGE: 2,
    BatteryIntent.OFF: 3,
}


def limit_entity(adapter) -> str:
    """The discharge limit entity this adapter writes, or ``""``."""
    return str(getattr(adapter, "_discharge_control_entity", "") or "")


def wish_of(decision, adapter=None, *,
            inputs_degraded: bool = False) -> Optional[tuple]:
    """What this battery's command does to its limit this cycle, as
    ``(rank, intent, limit_w)`` — ``None`` when it writes none."""
    intent = decision.intent
    limit_w = float(decision.discharge_limit_w or 0.0)
    if adapter is not None:
        from .actuate_battery import held_on_blind_cycle
        if held_on_blind_cycle(decision, adapter, inputs_degraded):
            intent = adapter.last_intent
            limit_w = float(adapter.last_discharge_limit_w)
        if (intent is BatteryIntent.OFF
                and getattr(adapter, "last_intent", None) is BatteryIntent.OFF):
            return None                     # Off speaks once
    if intent not in _RANK:
        return None
    return _RANK[intent], intent, (limit_w if intent is _LIMIT else 0.0)


def setpoint_entity(adapter) -> str:
    """(#1182) The sale power entity this adapter's commands write, or
    ``""``."""
    fn = getattr(adapter, "sale_setpoint_entity", None)
    if not callable(fn):
        return ""
    try:
        return str(fn() or "")
    except Exception:  # noqa: BLE001 — a stand-in without the attributes
        return ""


def setpoint_wish_of(decision, adapter, *,
                     inputs_degraded: bool = False) -> Optional[tuple]:
    """(#1182) What this battery's command writes to its sale power entity
    this cycle, as ``(rank, intent, tie)`` — ``None`` when it writes none."""
    from .actuate_battery import held_on_blind_cycle
    if held_on_blind_cycle(decision, adapter, inputs_degraded):
        return None                         # the actuator sends nothing
    intent = decision.intent
    if (intent is BatteryIntent.OFF
            and getattr(adapter, "last_intent", None) is BatteryIntent.OFF):
        return None                         # Off speaks once
    if intent is _SALE:
        if not getattr(adapter, "supports_forced_discharge", False):
            return None                     # the actuator drops it
        return 0, intent, 0.0
    if (intent is BatteryIntent.FORCE_CHARGE
            and getattr(adapter, "_setpoint_bidirectional", False)):
        return 1, intent, 0.0
    # every other command writes 0 W; a battery ending a sale of its own
    # goes first, so its stop goes out with its own command
    retries = getattr(adapter, "_stop_retries", 0)
    owes_stop = bool(getattr(adapter, "last_intent", None) is _SALE
                     or getattr(adapter, "_forcible_discharging", False) is True
                     or (isinstance(retries, int) and retries > 0))
    return 2, intent, (0.0 if owes_stop else 1.0)


def shared_groups(rows: Iterable[tuple]) -> list:
    """``rows``: ``(battery_id, entity_id, wish)`` in fleet order.

    Returns ``[(members, ranked)]``, one per entity that two or more
    batteries write: ``members`` in fleet order, ``ranked`` the batteries
    whose command writes the limit, best first.
    """
    by_entity: dict = {}
    for i, (bid, ent, wish) in enumerate(rows):
        if ent:
            by_entity.setdefault(ent, []).append((i, bid, wish))
    out = []
    for group in by_entity.values():
        if len(group) < 2:
            continue
        ranked = [bid for _, _, _, bid in sorted(
            (w[0], w[2], i, bid) for i, bid, w in group if w is not None)]
        out.append(([bid for _, bid, _ in group], ranked))
    return out


def _set(adapter, attr: str, value) -> None:
    try:
        setattr(adapter, attr, value)
    except Exception:  # noqa: BLE001 — a read-only stub is not a failure
        pass


def follow_writer(adapter, writer) -> None:
    """After the cycle: ``adapter`` did not write its shared limit, so it
    takes ``writer``'s record of it.

    With no limit of SEM's in force (the writer sold, or wrote the max), a
    LIMIT_DISCHARGE this adapter recorded is cleared: left in place it reads
    as a limit in force, and the next hold from it waits out the lowering
    dwell while the pack feeds the car (the #1175 review, one battery over).
    The actuator's dwell state then starts again on its own, as it does for
    any limit that is not in force.

    A limit write of this adapter's own that is still waiting to be judged
    (#915) is the writer's to judge now: it is moved when the writer holds
    that same value and has none of its own, else dropped. The entity holds
    the writer's value, and a verdict on another value would be a false
    "not kept".
    """
    _set(adapter, "_last_discharge_limit_w", writer.last_discharge_limit_w)
    if (getattr(writer, "last_intent", None) is not _LIMIT
            and getattr(adapter, "last_intent", None) is _LIMIT):
        _set(adapter, "_last_intent", None)
    pending = getattr(adapter, "_pending_write", None)
    if pending and pending[0] == limit_entity(adapter):
        if (getattr(writer, "_pending_write", None) is None
                and abs(float(pending[1]) - writer.last_discharge_limit_w) < 1e-6):
            _set(writer, "_pending_write", pending)
        _set(adapter, "_pending_write", None)


def _drop_unsent_hold(adapter) -> None:
    """A LIMIT_DISCHARGE whose write was held back this cycle, with another
    value in the entity, is no limit in force. Left in place, the next cycle
    reads the entity's value as the hold's and waits out the lowering dwell
    before the hold lands (the #1175 review rule, for the writer of a quiet
    cycle and for a battery that kept its own value)."""
    withheld = getattr(adapter, "_limit_withheld", None)
    if (withheld is not None
            and getattr(adapter, "last_intent", None) is _LIMIT
            and abs(adapter.last_discharge_limit_w - withheld[0]) >= 1e-6):
        _set(adapter, "_last_intent", None)


async def _settle_setpoint(ads: dict, ranked: list, record) -> str:
    """(#1182) After the commands: the battery whose write the shared sale
    power entity holds. A writer whose command did not leave its value
    there (it wrote nothing, or the write was refused) gives the entity to
    the next battery in line that held a write back, until one lands.
    ``record`` is the entity's record before the commands: no write landed
    since, and a command may have set its own without one."""
    writer = ranked[0]
    if not getattr(ads[writer], "_setpoint_spoke", False):
        for cand in ranked[1:]:
            ad = ads[cand]
            withheld = getattr(ad, "_setpoint_withheld", None)
            if withheld is None:
                continue
            _set(ad, "_setpoint_writer", None)
            # the same-value skip reads the entity's record, not one this
            # command set without a write (a stop can record 0 W first)
            _set(ad, "_last_force_discharge_w", record)
            if withheld == 0.0:
                ok = await ad._zero_setpoint()   # the #1005 door
                if getattr(ad, "_stop_withheld", False):
                    _set(ad, "_sent_stop", True)
            else:
                ok = await ad._write_force_discharge(withheld)
                if withheld > 0:
                    _set(ad, "_sale_sent", bool(ok))
            writer = cand
            if ok:
                break
    return writer


async def actuate_batteries(
    rows: list,
    send: Callable[..., Awaitable[None]],
    *,
    observer: bool = False,
    inputs_degraded: bool = False,
    sale_writers: Optional[dict] = None,
) -> dict:
    """Send every battery's decision, one writer per shared limit and per
    shared sale power entity (#1182).

    ``rows``: ``(battery_id, adapter, decision)`` in fleet order;
    ``send(decision, adapter)`` sends one (``actuate_battery``). Returns
    ``{battery_id: writer_id}`` for the batteries whose limit another
    battery wrote; ``sale_writers``, when given, is filled the same way for
    the sale power.

    Observer sends nothing, so nothing is shared out. The writer is marked
    on each adapter only while the cycle's commands run: a command sent
    outside the cycle (the unload hand-back, #936) is never held back.
    """
    if observer:
        for _, ad, decision in rows:
            await send(decision, ad)
        return {}
    ads = {bid: ad for bid, ad, _ in rows}
    wishes = {bid: wish_of(d, ad, inputs_degraded=inputs_degraded)
              for bid, ad, d in rows}
    groups = [(m, r) for m, r in shared_groups(
        (bid, limit_entity(ad), wishes[bid]) for bid, ad, _ in rows) if r]
    top = {bid: ranked[0] for members, ranked in groups for bid in members}
    sp_wishes = {bid: setpoint_wish_of(d, ad, inputs_degraded=inputs_degraded)
                 for bid, ad, d in rows}
    sp_groups = [(m, r) for m, r in shared_groups(
        (bid, setpoint_entity(ad), sp_wishes[bid]) for bid, ad, _ in rows) if r]
    sp_top = {bid: ranked[0] for members, ranked in sp_groups
              for bid in members}
    sp_effective = dict(sp_top)
    for bid, writer_id in top.items():
        # (#1138) a hold's one extra send goes with the hold
        if (bid != writer_id and wishes[writer_id][1] is _LIMIT
                and getattr(ads[bid], "_limit_resend_due", False)):
            _set(ads[writer_id], "_limit_resend_due", True)
            _set(ads[writer_id], "_limit_resent_for_w",
                 getattr(ads[bid], "_limit_resent_for_w", None))
            _set(ads[bid], "_limit_resend_due", False)
    writers = set(top.values())
    before = {bid: ad.last_discharge_limit_w for bid, ad in ads.items()}
    sp_before = {bid: getattr(ad, "_last_force_discharge_w", None)
                 for bid, ad in ads.items()}
    stopped: set = set()
    effective = dict(top)
    try:
        for ad in ads.values():
            _set(ad, "_sent_stop", False)
            _set(ad, "_sale_sent", False)
            _set(ad, "_limit_withheld", None)
            _set(ad, "_setpoint_spoke", False)
            _set(ad, "_setpoint_withheld", None)
            _set(ad, "_stop_withheld", False)
        for bid, ad, decision in ([r for r in rows if r[0] not in writers]
                                  + [r for r in rows if r[0] in writers]):
            writer_id = top.get(bid)
            mark = writer_id if writer_id != bid else None
            if writer_id == bid and limit_entity(ad) in stopped:
                mark = bid                    # a quiet cycle: nobody writes
            _set(ad, "_limit_writer", mark)
            sp_writer = sp_top.get(bid)
            _set(ad, "_setpoint_writer", sp_writer if sp_writer != bid else None)
            await send(decision, ad)
            if writer_id is not None and getattr(ad, "_sent_stop", False):
                stopped.add(limit_entity(ad))
        # (#1182) the sale power first: whether a sale went out decides the
        # limit's writer below
        for members, ranked in sp_groups:
            writer = await _settle_setpoint(ads, ranked, sp_before[ranked[0]])
            for bid in members:
                sp_effective[bid] = writer
            if top.get(writer) is not None and getattr(
                    ads[writer], "_sent_stop", False):
                stopped.add(limit_entity(ads[writer]))
        for members, ranked in groups:
            for cand in ranked:
                ad = ads[cand]
                if (wishes[cand][1] is _SALE
                        and not getattr(ad, "_sale_sent", False)
                        and not ad.last_discharge_limit_w > before[cand]):
                    continue                  # a sale that did not go out
                withheld = getattr(ad, "_limit_withheld", None)
                if cand != ranked[0] and withheld is not None:
                    if limit_entity(ad) in stopped:
                        break                 # the device gets a quiet cycle
                    _set(ad, "_limit_writer", None)
                    await ad._apply_discharge_limit(withheld[0], force=withheld[1])
                for bid in members:
                    effective[bid] = cand
                break
    finally:
        for ad in ads.values():
            _set(ad, "_limit_writer", None)
            _set(ad, "_setpoint_writer", None)
        for bid, writer_id in effective.items():
            if bid != writer_id:
                follow_writer(ads[bid], ads[writer_id])
        for ad in ads.values():
            _drop_unsent_hold(ad)
        for bid, writer_id in sp_effective.items():
            if bid != writer_id:
                _set(ads[bid], "_last_force_discharge_w",
                     getattr(ads[writer_id], "_last_force_discharge_w", None))
    if sale_writers is not None:
        sale_writers.update(
            {bid: w for bid, w in sp_effective.items() if bid != w})
    return {bid: w for bid, w in effective.items() if bid != w}
