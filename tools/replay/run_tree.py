"""(#1083) Replay days with the code of ONE tree; print one JSON line per day.

Run inside a layout where ``custom_components.solar_energy_management`` is
the tree under test (``scripts/sem_replay.py`` builds it)::

    python -m custom_components.solar_energy_management.tools.replay.run_tree DAY.json.gz ...

One day in memory at a time: each day is loaded, replayed, written out
and dropped before the next.
"""
from __future__ import annotations

import gc
import json
import sys
from pathlib import Path

from .engine import replay_day
from .recorded_day import load_day


def main(argv) -> int:
    for p in argv:
        day = load_day(Path(p))
        run = replay_day(day)
        print(json.dumps({
            "date": run.date, "tags": run.tags, "writes": run.writes,
            "notes": run.notes,
            "home": [[round(t), round(s, 1)] for t, s, _r, _d in run.home],
            "forecast": [[round(t), round(h, 3), raw, cor] for t, h, raw, cor in run.forecast],
            "cost": None if run.cost is None else [round(v, 6) for v in run.cost],
        }), flush=True)
        del day, run
        gc.collect()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
