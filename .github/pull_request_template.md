<!--
Thanks for contributing to SEM! This template mirrors what our automated
maintainer review checks — filling it honestly gets your PR through faster.
-->

## What does this PR do?
<!-- One or two sentences. Link the issue it addresses: Fixes #123 / Refs #123.
     PRs without a linked issue should explain the problem they solve. -->

## Type of change
<!-- Check ONE. This routes your PR: during a stabilization phase (feature
     freeze), feature PRs are parked with a friendly note and reviewed after
     the next stable release — bug fixes are reviewed immediately. -->

- [ ] 🐛 Bug fix (corrects existing behaviour, no new surface)
- [ ] ✨ Feature (new capability, config surface, entities, or device support)
- [ ] 🌍 Translation / documentation only

## How was it tested?
<!-- SEM controls real inverters, batteries and chargers — tell us what stood
     between your change and someone's hardware. -->

- [ ] Unit tests added/updated that **pin the new behaviour** (a test that
      passes against the unfixed code pins nothing)
- [ ] Full suite passes locally (see CONTRIBUTING.md for the namespaced
      test-runner — plain `pytest` from the repo root fails by design)
- [ ] Verified on my own hardware: <!-- inverter/charger model, what you observed -->
- [ ] Not hardware-verifiable by me — I've noted below what a maintainer or
      another user must confirm

## SEM-specific checklist
<!-- Only tick what applies — untouched areas can stay unchecked. These are
     the invariants the automated review will hold you to. -->

- [ ] **Translations move together**: any new user-visible string is added to
      `strings.json` AND all 16 `translations/*.json` with the identical key set
- [ ] **No sign flips**: I did not negate a power/energy sensor "to follow
      convention" — SEM's conventions are battery −=discharge/+=charge,
      grid −=import/+=export, with per-platform detection, never unconditional
- [ ] **Persisted state round-trips**: any new key emitted for persistence is
      registered in `storage.CALCULATOR_STATE_KEYS` (a CI guard enforces this)
- [ ] **Fail closed**: discovery verifies what it adopts; control paths write
      nothing in observer mode; no success is claimed without verification
- [ ] **Entity hygiene**: stable `unique_id`s; diagnostics carry
      `EntityCategory.DIAGNOSTIC`; rarely-used entities are
      `entity_registry_enabled_default=False`
- [ ] **Zero-config safety**: an install that does NOT configure this change
      behaves exactly as before
- [ ] **Docs**: user-facing behaviour changes come with a docs update

## What happens next
<!-- No action needed — for your information. -->

Your PR gets an automated maintainer review that checks the invariants above
against the full diff. It will either request changes with specific
file-and-line findings (the PR is then assigned back to you), or formally
approve and hand it to the maintainer — merging is always a human decision.
CI on first-time contributions needs a manual approval before it runs;
that's GitHub policy, not distrust.
