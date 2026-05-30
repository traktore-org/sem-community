"""Obsolete after #277 Phase C.

This file pinned the per-charger night-charging switch behaviour
(#193 / #255). Phase C removed those switches entirely — the named
``charge_mode`` selector now carries the same intent — so the tests
no longer have a real fixture to exercise. The replacement coverage
lives in:

  - ``test_277_charge_mode_phase_b.py::TestNightGateFromMode`` —
    end-to-end mode-driven night-gate decisions
  - ``test_277_charge_mode_phase_b.py::TestSmartNightFromMode`` —
    mode-driven smart-night enablement
  - ``test_277_charge_mode_phase_b.py::TestRuntimeMigrationEquivalence``
    (pre-Phase-C) was retitled in Phase C to
    ``TestDeriveChargeModeAllLegacyCombinations`` and now covers the
    migration's mode-derivation truth table

The legacy one-time reconciliation (``force_off`` parameter on
``SEMPerChargerSwitch``) is dormant — the class still exists but no
production code path constructs it post-Phase-C. ``SEMPerChargerSwitch``
itself is scheduled for removal in Phase D / v1.7.x cleanup.

Kept as an empty module so a) the file isn't ghost-collected with a
collection error, b) the deletion is visible in git history.
"""
