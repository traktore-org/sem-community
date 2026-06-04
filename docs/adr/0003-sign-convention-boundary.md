# ADR 0003 — Sign convention boundary lives at `sensor_reader`

**Status:** Accepted (v1.4.0 onward — ratified after commit 00e449c rollback)

## Context

Different inverter brands emit sensor data with different sign
conventions:

| Quantity | Some brands | Others |
|---|---|---|
| Grid power | + = export, − = import | + = import, − = export |
| Battery power | + = charge, − = discharge | + = discharge, − = charge |
| Solar power | + only | + only |
| EV power | + only | + only |

SEM's internal convention is:

| Quantity | SEM convention |
|---|---|
| `grid_power` | − = import, + = export |
| `battery_power` | − = discharge, + = charge |

Commit `00e449c` tried to normalise downstream by unconditionally
negating, which broke Huawei (which already matched SEM's convention)
and silently produced wrong-sign Sankey diagrams + wrong-sign battery
SOC decisions.

## Decision

**All sign translation happens in `coordinator/sensor_reader.py`,
specifically in `_read_from_energy_dashboard`. No other module
negates raw sensor reads.**

- Per-platform autodetect (Huawei / SMA / Fronius / etc.) belongs in
  `sensor_reader`.
- Downstream code (`PowerReadings.calculate_derived`, `FlowCalculator`,
  the SOC-zone strategy, etc.) consumes the canonical SEM convention
  and never re-checks signs.
- If a future user reports the opposite sign on their inverter, the
  fix is a per-platform autodetect entry in `sensor_reader`, never a
  downstream negation.

## Consequences

**Good.** Sign bugs become structurally local — the only place a
flip can happen is the one file that's responsible for it. Downstream
code is simpler because there's nothing sign-dependent in it.

**Risk.** The autodetect logic in `sensor_reader` is now load-bearing
and needs to handle every supported brand's quirk. Mitigation:
pipeline tests (ADR 0005) cover every supported brand's full chain,
so any regression surfaces deterministically in CI.

See [`CLAUDE.md`](../../CLAUDE.md#sign-convention-summary) for the
operator-level summary and the commit `00e449c` postmortem.
