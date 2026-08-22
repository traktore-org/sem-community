#!/usr/bin/env python3
"""#829 — find values that churn, on a RUNNING instance.

Every instance of this bug class found on 22.08.2026 was invisible to the
test suite and, after ``_unrecorded_attributes`` stabilised the stored blob,
invisible in the database too. The recorder looked quiet while the state
object changed every cycle. All of them were found the same way: sample the
LIVE attributes several times and diff them.

This is that, as a command.

    python3 scripts/audit_live_churn.py --host http://10.10.20.46:8123 \
        --token "$HA_TEST_TOKEN" [--samples 4] [--interval 22] [--prefix sem_]

It reports two things, which are the two halves of the class:

  * **churn** — attribute paths that change on every sample while the entity's
    state does not. A plan re-stamped with ``datetime.now()``, a countdown at
    two decimals, a live watt riding a status entity.
  * **precision** — numeric values carrying more decimals than a human reads.
    A watt is a watt; ``5965.464021148`` is noise wearing a number's clothes.

Neither is automatically a bug: a value that genuinely moves should move. Read
it as "here is what rewrites this entity every cycle — is that information?"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from collections import defaultdict


def fetch(host: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/states",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return {s["entity_id"]: s for s in json.load(r)}


def walk(a, b, path: str, out: dict) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            walk(a.get(k), b.get(k), f"{path}/{k}", out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{i}]", out)
    elif a != b:
        out[path] = (a, b)


def decimals(value) -> int:
    try:
        s = repr(float(value))
    except (TypeError, ValueError):
        return 0
    return len(s.split(".")[-1]) if "." in s and "e" not in s else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--interval", type=int, default=22)
    ap.add_argument("--prefix", default="sem_",
                    help="object-id prefix identifying the integration's entities")
    ap.add_argument("--max-decimals", type=int, default=2)
    a = ap.parse_args()

    snaps = []
    for i in range(a.samples):
        snaps.append(fetch(a.host, a.token))
        print(f"  sample {i + 1}/{a.samples}", file=sys.stderr)
        if i < a.samples - 1:
            time.sleep(a.interval)

    mine = [e for e in snaps[0] if f".{a.prefix}" in e]
    churn: dict[str, dict] = defaultdict(dict)
    state_moved: set[str] = set()

    for eid in mine:
        for x, y in zip(snaps, snaps[1:]):
            if eid not in x or eid not in y:
                continue
            if x[eid]["state"] != y[eid]["state"]:
                state_moved.add(eid)
            walk(x[eid].get("attributes"), y[eid].get("attributes"), "", churn[eid])

    print(f"\nSEM-owned entities sampled: {len(mine)}  "
          f"({a.samples} samples, {a.interval}s apart)\n")

    attr_churn = {e: c for e, c in churn.items() if c}
    print(f"── attribute churn on {len(attr_churn)} entities "
          "(rewrites the entity even when its state is unchanged) ──")
    for eid, paths in sorted(attr_churn.items(),
                             key=lambda kv: -len(kv[1]))[:15]:
        tag = "" if eid in state_moved else "  [state UNCHANGED]"
        print(f"  {eid}{tag}")
        for p, (x, y) in list(paths.items())[:4]:
            print(f"      {p or '(state)'}: {str(x)[:34]} -> {str(y)[:34]}")

    print(f"\n── numeric precision above {a.max_decimals} dp ──")
    flagged = 0
    for eid in mine:
        st = snaps[-1][eid]["state"]
        if decimals(st) > a.max_decimals:
            print(f"  {eid} = {st}")
            flagged += 1
    if not flagged:
        print("  none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
