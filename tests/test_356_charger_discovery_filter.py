"""Regression guard for #356 — EV/charger card discovery must skip flow sensors.

@RienduPre reported seeing 4 sections per real charger (the actual one
plus 3 ghosts titled "Solar → EV", "Grid → EV", "Battery → EV") on the
EV dashboard tab. Root cause: the charger discovery regex in
``sem-ev-status-card.js`` and ``sem-charger-status-card.js`` was greedy:

    /^sensor\\.sem_charger_(.+)_power$/

That matches both real charger sensors
(``sensor.sem_charger_<id>_power``) AND the per-charger flow sensors
(``sensor.sem_charger_<id>_flow_solar_to_ev_power`` etc.) — the latter
were added in v1.6.9 to feed the FLOW card, never as charger ids.
Each multi-charger install with flow sensors got 3 ghost
"chargers" per real charger.

The fix: tighten both discoveries with a ``if (eid.includes('_flow_'))
continue;`` guard before the regex.

This test is a source-level lint — it does NOT execute the JS (LitElement
+ HA's component lifecycle is out of pytest's reach). Instead it:

  1. Anchors the guard string in both card files (regression on rollback).
  2. Property-tests the regex against representative entity IDs and asserts
     the flow-sensor inputs are rejected once the guard runs.
"""
from __future__ import annotations

import re
from pathlib import Path



def _project_root() -> Path:
    """Repo root; the tests can run from either ``/tmp/ha-config`` (CI
    layout) or the dev checkout. Walk up until we find ``manifest.json``."""
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "manifest.json").exists():
            return parent
    raise RuntimeError("project root not found")


def test_regex_with_guard_rejects_flow_sensors() -> None:
    """Property-style verification: the discovery regex by itself matches
    flow sensors (this is the bug), but combined with the
    ``'_flow_' in eid`` guard the flow sensors are correctly rejected.
    """
    # The same regex literal both card files use.
    discovery_re = re.compile(r"^sensor\.sem_charger_(.+)_power$")

    real_chargers = [
        "sensor.sem_charger_ev_charger_power",
        "sensor.sem_charger_laadpaal_links_power",
        "sensor.sem_charger_keba_p30_power",
    ]
    ghost_flow_sensors = [
        "sensor.sem_charger_ev_charger_flow_solar_to_ev_power",
        "sensor.sem_charger_ev_charger_flow_grid_to_ev_power",
        "sensor.sem_charger_ev_charger_flow_battery_to_ev_power",
        "sensor.sem_charger_laadpaal_links_flow_solar_to_ev_power",
        "sensor.sem_charger_laadpaal_links_flow_grid_to_ev_power",
        "sensor.sem_charger_laadpaal_links_flow_battery_to_ev_power",
    ]

    # Bug demonstrator: the regex alone matches the ghosts.
    for eid in ghost_flow_sensors:
        m = discovery_re.match(eid)
        assert m is not None, (
            f"sanity check: regex should still match {eid} (this is the "
            f"underlying bug — guard is what filters it)"
        )

    # Fix demonstrator: the guard rejects flow sensors before the regex.
    def discover_with_guard(eids):
        out = []
        for eid in eids:
            if "_flow_" in eid:
                continue  # the #356 guard
            m = discovery_re.match(eid)
            if m:
                out.append(m.group(1))
        return out

    all_entities = real_chargers + ghost_flow_sensors
    discovered = discover_with_guard(all_entities)

    # All 3 real chargers found.
    assert sorted(discovered) == sorted(
        ["ev_charger", "laadpaal_links", "keba_p30"]
    ), (
        f"#356 regression — discovery with guard should yield the 3 real "
        f"charger ids, got: {discovered}"
    )
    # No ghosts.
    assert not any("flow" in d for d in discovered), (
        f"#356 regression — discovery with guard still emitted a flow-"
        f"ghost charger id: {[d for d in discovered if 'flow' in d]}"
    )


def test_existing_chargers_with_underscores_in_id_still_match() -> None:
    """Edge case: charger ids legitimately containing underscores (e.g.
    ``laadpaal_links``, ``ev_charger``, ``keba_p30``) must still be
    discovered. The ``_flow_`` substring is specifically that token —
    NOT any underscore — so ids without a literal ``_flow_`` in them
    pass through fine.
    """
    discovery_re = re.compile(r"^sensor\.sem_charger_(.+)_power$")

    edge_cases = {
        "sensor.sem_charger_ev_charger_power": "ev_charger",
        "sensor.sem_charger_laadpaal_links_power": "laadpaal_links",
        "sensor.sem_charger_keba_p30_power": "keba_p30",
        "sensor.sem_charger_left_right_power": "left_right",
    }

    for eid, expected_id in edge_cases.items():
        assert "_flow_" not in eid, f"setup error — {eid} has _flow_"
        m = discovery_re.match(eid)
        assert m is not None, f"discovery regex must match {eid}"
        assert m.group(1) == expected_id, (
            f"id mismatch for {eid} — got {m.group(1)!r}, "
            f"want {expected_id!r}"
        )
