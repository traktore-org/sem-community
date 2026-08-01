# ADR 0007 — Real-hass test framework adoption and test-layer choice rule

**Status:** Accepted (v1.7.0-beta.10) · ratifies `tests/requirements_test.txt` pin

## Context

SEM's test suite started as pure unit tests (mock `HomeAssistant` objects via
`MagicMock`). By v1.6 a scenario harness (`tests/scenarios/*.yaml` + `scenario_harness.py`)
was added to replay real coordinator traces in CI. Both layers proved insufficient
for a third class of bug: lifecycle interactions with the actual HA process —
entry setup/unload ordering, `hass.data` slot lifecycle, frontend resource
registration races, and coordinator teardown. These bugs were only visible by
running real HA startup, not by mocking it.

`pytest-homeassistant-custom-component` provides a real `HomeAssistant` instance
in-process via the `hass` fixture. Phase 1 of the adoption shipped in commit
`8e34727` (smoke tests + framework wiring). Phase 2 shipped with
v1.7.0-beta.10 (commit `91b0663`): unload/reload cycle tests,
config-entry lifecycle tests, and frontend cache-bust regression guards — all
using the real `hass` fixture against real HA internals.

## Decision

**`pytest-homeassistant-custom-component==0.13.205` (pinned in
`tests/requirements_test.txt`) is first-class in SEM's test suite.**

Pick the test layer that matches the bug class you are guarding:

| Bug class | Layer |
|---|---|
| Pure arithmetic / data-structure logic | Unit test (mock `hass`) |
| Coordinator decision vs enforcement drift across a timeline | Scenario harness (`tests/scenarios/`) |
| HA lifecycle — setup, unload, reload, `hass.data`, frontend resource registration | Real-hass (`hass` fixture from `pytest-homeassistant-custom-component`) |
| Time-boundary effects, entity reactivity, persistence across restart | Live tests (`tests/live/*.sh` against HA-TEST) |

All four layers are necessary; none is sufficient. Do not substitute a mock-hass
test for a bug class that requires real-hass lifecycle, and do not reach for
live tests when a real-hass in-process test is faster and fully deterministic.

## Consequences

**Good.** HA-lifecycle bugs are now caught in CI without a deploy cycle. The
`hass` fixture spins up a real `HomeAssistant` in milliseconds, so the cost
is comparable to mock-hass tests while testing the actual integration path.

**Open.** Both mock-hass and real-hass tests currently coexist for some code
paths (no policy yet for when to retire the mock-hass equivalent once a
real-hass test exists). Track for v1.8: a rule such as "retire the mock-hass
test if the real-hass test covers the same assertion and is not significantly
slower".

See `tests/test_setup_entry_smoke.py`, `tests/test_setup_entry_lifecycle.py`,
and `tests/test_unload_reload_cycle.py` for the real-hass test suite.
See [`CONTRIBUTING.md`](../../CONTRIBUTING.md#the-four-layer-test-pyramid)
for the full pyramid description.
