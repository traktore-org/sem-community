# ADR 0005 — Pipeline test per supported brand is mandatory

**Status:** Accepted (v1.4.0 onward, after issue #129 postmortem)

## Context

Issue `#129` shipped a regression that all the unit tests passed:
individual sign-convention helpers, individual sensor parsers, and
individual flow calculators all returned the correct value when tested
in isolation. But the full pipeline — Energy Dashboard config →
`SensorReader` → `PowerReadings` → derived flows → final sensors — had
a subtle composition bug that none of the unit tests touched.

Unit tests pass; production breaks. Classic.

## Decision

**Every inverter or charger brand listed in `README.md`'s supported
list MUST have a corresponding pipeline scenario in
`tests/test_split_grid_integration.py`.**

A pipeline test exercises the _complete_ chain end-to-end for that
brand's specific sensor shape (combined grid vs split L1/L2/L3,
positive-import vs positive-export, battery sign, etc.). It feeds in
realistic Energy Dashboard config and asserts the final flow sensors
are correct.

Adding a new brand to the supported list without adding a pipeline
test is a review-blocker — flagged by CodeRabbit per
`.coderabbit.yaml`'s path instructions and caught at review time.

## Consequences

**Good.** The class of bug from #129 is closed structurally — any new
brand contributes a deterministic CI scenario that future refactors
must keep green.

**Cost.** ~30 min per new brand to write the scenario. Acceptable
overhead for a new platform that's going to live in the codebase
forever.

Reference inverter patterns (grid sign × battery sign):

- Pattern A: grid += export, battery += charge (Huawei, SMA, Victron, Sungrow)
- Pattern B: grid += import, battery += discharge (Fronius, Enphase, Powerwall, Kostal, SolarEdge)
- Pattern C: grid += export, battery += discharge (GoodWe, Sonnen)
- Pattern D: grid += import, battery += charge (SolaX)
- Pattern E: split grid, no combined sensor (Growatt)
- Pattern F: solar-only, no grid sensor

Reference charger patterns (control method):

- Service-based: KEBA (`keba.set_current`), Easee, Zaptec
- Number entity: Wallbox, go-eCharger, ChargePoint, Heidelberg, OpenWB, OCPP, Ohme, Peblar, V2C, Blue Current, OpenEVSE, Alfen
- Power unit: W vs kW auto-conversion

See `tests/test_split_grid_integration.py` for the existing scenarios
and [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the standing rule:
every brand listed in the README must have a pipeline test — adding a
brand to the supported list requires adding its test in the same change.
