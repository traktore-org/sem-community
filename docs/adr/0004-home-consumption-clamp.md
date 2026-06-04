# ADR 0004 — `home_consumption_power` is clamped to zero, never `unknown`

**Status:** Accepted (v1.3.x onward, reaffirmed on every audit)

## Context

`home_consumption_power` is a derived sensor computed from the energy
balance:

```
home = max(0, solar + grid_import + batt_discharge − ev − grid_export − batt_charge)
```

On a perfectly-calibrated install with synchronised sensor reads, the
inner expression is `≥ 0` and the clamp is a no-op. In reality, sensor
reads land a fraction of a second apart, integration polling lags, and
the result drifts slightly negative for a single cycle here and there.

Three options were on the table:

1. Report `unknown` when the inner expression is negative
2. Report the raw negative value
3. Clamp to `0` and accept the brief under-report

## Decision

**Option 3: clamp to zero.**

The user explicitly does not want `home_consumption_power` flipping to
`unknown` mid-day. Their Energy Dashboard derivative falls off a cliff
when an upstream sensor goes unknown — the integration is technically
"correct" but the user's day looks broken.

Negative home consumption is physically impossible (the home is a
load, not a source), so the clamp is also the correct answer in the
limit.

## Consequences

**Good.** The sensor never goes unknown. Energy Dashboard charts stay
continuous. The user's mental model (home is always drawing) matches
what they see.

**Risk.** If the inner expression goes _persistently_ negative, the
clamp masks a real sign bug elsewhere. Mitigation: SEM logs the inner
value at DEBUG when it goes negative, and the sign-convention
boundary (ADR 0003) keeps the class small enough that audits catch
real bugs upstream.

Code path: `coordinator/types.py:PowerReadings.calculate_derived` (line 206).
Do **not** add a `if balance < 0: return None` branch — that
explicitly inverts this decision.
