"""#762 — a log line is a transition, not a heartbeat.

Measured on the .175 rig (13.08, half a day at DEBUG): a STEADY system
repeated the same six decision lines ~8,000 times — `decide_battery →
normal` 1423×, `Charging strategy: idle` 1792×, `Scheduled delayed
save` 1930× — which shrank the host's ~2-minute log ring until the N1
night's evidence was gone by morning, and drowns the excerpt HA's
native "Enable debug logging" toggle hands the user on disable.

`log_on_change` is the shared gate: it emits only when the FORMATTED
message for a key differs from the last one emitted for that key. An
unchanged decision is silent; every change logs; a flap logs each edge,
because the edges are the signal. The cache is keyed by
(logger name, key) so two batteries with identical text don't mask
each other, and it deliberately records nothing while the level is
disabled — otherwise enabling debug later (the HA toggle flow) would
suppress the first line as "unchanged" when the user never saw it.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Tuple

_LAST: Dict[Tuple[str, str], str] = {}
_DIGITS = re.compile(r"-?\d+(?:[.,]\d+)?")


def log_on_change(
    logger: logging.Logger, key: str, level: int, fmt: str, *args: Any,
) -> None:
    """Emit ``fmt % args`` at ``level`` only when it changed for ``key``.

    "Changed" is judged on the DIGIT-STRIPPED message: decision reasons
    carry live measurements (``limit 594 W`` → ``602 W`` → ``590 W``)
    that wobble every cycle without the decision changing, and a gate
    that treats the wobble as news is no gate at all. The emitted line
    still shows the live numbers as of the transition; per-cycle values
    belong in diagnostics, not in the log. A site where the number IS
    the event puts the number in ``key``.
    """
    if not logger.isEnabledFor(level):
        return
    try:
        msg = fmt % args if args else fmt
    except (TypeError, ValueError):
        # A malformed format string must never take the cycle down —
        # degrade to the unformatted text plus its arguments.
        msg = f"{fmt} {args!r}"
    cache_key = (logger.name, key)
    dedup = _DIGITS.sub("#", msg)
    if _LAST.get(cache_key) == dedup:
        return
    _LAST[cache_key] = dedup
    logger.log(level, "%s", msg)


def reset_log_gate() -> None:
    """Forget all last-emitted messages (tests; never called in prod)."""
    _LAST.clear()
