"""The one place SEM reads Home Assistant's recorder.

Why one place (#967). A recorder read that is awaited inside
``async_setup_entry`` is charged to Home Assistant's own start-up budget.
When that budget runs out HA cancels the setup task and the integration
does not load **at all** — the user sees one line, *"Setup of config entry
'Solar Energy Management' ... cancelled"*, and nothing else works. The
cancel arrives as ``CancelledError``, which is not an ``Exception``, so
none of the "this must never cost us the setup" handlers on the way up
catch it. @alexmc1510 hit exactly that after adding his charger to the
Energy Dashboard: one more power sensor, one more history query, over the
line.

So every recorder read goes through here, and every read is:

* **started after Home Assistant has** — :func:`run_after_start` is how a
  caller asks for recorder work. Nothing setup awaits can reach it, so the
  read is never charged to the start-up budget.
* **cheap** — the attributes stay in the database (loading them is most of
  the cost of a long window), and the window is never longer than the
  recorder actually keeps.
* **honest about failure** — ``None`` means the recorder could not answer,
  an empty list means it answered and there was nothing there.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, List, Optional

from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)


@callback
def run_after_start(
    hass: HomeAssistant,
    coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    *,
    name: str,
) -> Callable[[], None]:
    """Run recorder work once Home Assistant has started, never sooner.

    Returns the unsubscribe callable. Hand it to ``entry.async_on_unload``
    or cancel it yourself — an entry that goes away before the start event
    otherwise leaves a dead coordinator waiting to do the work.

    An install that is already running — a reload, or a config entry added
    by hand — counts as started, and the work goes on a task immediately.
    That task may well finish before setup returns, which is fine: setup
    does not await it, and there is no start-up budget to overrun outside a
    boot. Unbounded work still belongs on a task, never in the await chain.
    """
    from homeassistant.helpers.start import async_at_started

    @callback
    def _go(_hass: HomeAssistant) -> None:
        # ``eager_start`` would run the first slice of the work right here,
        # and "here" is inside ``async_setup_entry`` on the reload path.
        hass.async_create_task(coro_factory(), name, eager_start=False)

    return async_at_started(hass, _go)


def _window_days(instance: Any, days: int) -> int:
    """Never ask for more days than the recorder keeps.

    ``keep_days`` is what auto-purge deletes past, so it is only a floor on
    the database when auto-purge is ON. An install that purges by hand keeps
    everything, and clamping there would throw away real history.
    """
    try:
        wanted = max(1, int(days))
    except (TypeError, ValueError):
        return 1
    if not getattr(instance, "auto_purge", True):
        return wanted
    try:
        keep = int(getattr(instance, "keep_days", 0) or 0)
    except (TypeError, ValueError):
        return wanted          # a recorder that will not say: take the ask
    if keep <= 0 or keep >= wanted:
        return wanted
    _LOGGER.debug(
        "history window cut from %d to %d days — the recorder keeps %d",
        wanted, keep, keep,
    )
    return keep


def raw_history_days(hass: HomeAssistant, wanted: int) -> int:
    """How many of the last ``wanted`` days the recorder still holds as raw
    states (``wanted`` itself when auto-purge is off). 0 when it will not
    say — then no day counts as held."""
    try:
        from homeassistant.components.recorder import get_instance
        return _window_days(get_instance(hass), wanted)
    except Exception:  # noqa: BLE001 — no recorder
        return 0


async def read_states(
    hass: HomeAssistant,
    entity_id: str,
    days: int,
    *,
    start: Any = None,
    end: Any = None,
) -> Optional[List[Any]]:
    """The states ``entity_id`` reported over the last ``days``, oldest first.

    ``start``/``end`` narrow the read to one stretch inside that window
    (a backfill reads one day, not a week); ``start`` is still never
    earlier than the recorder keeps.

    ``None`` if the recorder could not answer at all — the caller may want
    to say so. ``[]`` if it answered and the entity has no history.

    The state already in force when the window opened comes back too, so a
    sensor that held one value all week still reads as that value.
    """
    from datetime import timedelta
    from functools import partial

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import (
            state_changes_during_period,
        )
        from homeassistant.util import dt as dt_util

        instance = get_instance(hass)
        now = dt_util.utcnow()
        floor = now - timedelta(days=_window_days(instance, days))
        start = floor if start is None else max(start, floor)
        end = now if end is None else min(end, now)
        if start >= end:
            return []
        history = await instance.async_add_executor_job(
            partial(
                state_changes_during_period,
                hass,
                start,
                end,
                str(entity_id),
                # The attribute join is most of the cost of a long window,
                # and no reader here wants the attributes (#967).
                no_attributes=True,
            )
        )
    except Exception as err:  # noqa: BLE001 — no recorder, or a busy one
        _LOGGER.debug("recorder history for %s unavailable: %s", entity_id, err)
        return None
    return list((history or {}).get(str(entity_id)) or [])


async def read_hourly_statistics(
    hass: HomeAssistant,
    start: Any,
    end: Any,
    entity_ids: Any,
    types: Any = frozenset({"change", "mean"}),
) -> Optional[dict]:
    """Hourly long-term statistics for ``entity_ids`` in ``[start, end)``.

    ``{statistic_id: [{"start": ..., "change": ..., "mean": ...}, ...]}``.
    Statistics outlive the recorder's state history (they are never purged),
    which is why a backfill reads them. The query is SYNC database work, so
    it runs on the recorder's executor.

    ``None`` if the recorder could not answer at all; ``{}`` if it answered
    and there was nothing there.
    """
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import (
            statistics_during_period,
        )

        result = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass, start, end, set(entity_ids), "hour", None, set(types),
        )
    except Exception as err:  # noqa: BLE001 — no recorder, or a busy one
        _LOGGER.debug("hourly statistics unavailable: %s", err)
        return None
    if not isinstance(result, dict):
        return None
    return result
