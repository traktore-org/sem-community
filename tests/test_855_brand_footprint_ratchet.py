"""#855 — brand knowledge in the generic device layer is shrink-only.

Guido, 29.08.2026, on what the arc is actually for:

> *"the 2nd layer has one communication string to the 3rd layer for ev
> charger, then the rest follows the lead, and the observation should not
> be a matter any more — more a matter of get the work done."*

SEM already built that shape, for loads:
``compute_load_intent`` (layer 1) → ``_desired_intents`` (layer 2) →
``reconcile_load`` (layer 3, **the single actuator**). Its own docstring
states the prize:

> *"Here — the ONLY execution seam — we LOG the command we WOULD send …
> This is why observer mode needs no separate ``observe_only`` path — a
> clean layer cut makes it a one-line branch in the actuator."*

Chargers never got that shape. Their mechanics live in ``devices/base.py``
— the GENERIC layer — so there is no single string from layer 2 to layer
3, and observer mode (which cuts above the adapter) reports the DECISION
rather than the COMMANDS. What that cost, in one month:

* **#854** — the KEBA "stop" was ``set_current`` + ``set_energy(1.0)`` +
  ``enable``: a start wearing a stop's name, ~1 kWh into the car on every
  plug-in against a zero ask. Invisible in observer mode, because the
  ``enable`` sat below the cut.
* **#804** — phase switching could not be exercised on the rig at all.
* **#852** — a reporter's Wallbox stop could not be reproduced on the rig.

Each ended in "turn observer off", which on shared hardware means
commanding a real box.

**This test does not move any code.** It is stage 1 of the arc: freeze the
problem so it cannot get worse while the rest is done. The count may fall,
never rise — and a brand appearing here for the FIRST time fails loudest,
because that is a new brand being taught to the wrong layer.
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_counter():
    """Load the audit script by path — `scripts/` is not an importable
    package in the CI layout (the repo lives under
    custom_components/solar_energy_management/). Same approach as #830's
    ratchet, and it keeps ONE implementation of the count: the test and
    the regenerate command can never disagree about what a brand mention
    is."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "audit_brand_footprint", ROOT / "scripts" / "audit_brand_footprint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.count_brands


count_brands = _load_counter()
TARGET = ROOT / "devices" / "base.py"
BASELINE = json.loads(
    (ROOT / "tests" / "brand_footprint_baseline.json").read_text())


def _counts() -> dict[str, int]:
    return count_brands(TARGET.read_text())


def test_no_brand_appears_in_the_generic_layer_for_the_first_time():
    """The loudest failure: a brand being taught to the wrong layer."""
    known = set(BASELINE["per_brand"])
    new = sorted(set(_counts()) - known)
    assert not new, (
        f"{', '.join(new)} now appears in devices/base.py, the GENERIC "
        "device layer. Brand quirks belong in "
        "coordinator/charger_adapters/<brand>.py — that is what the "
        "adapter layer exists for, and putting them here is how a "
        "one-idea fix ends up spanning two layers (#854) and how observer "
        "mode ends up unable to show what SEM would send (#855)."
    )


def test_the_brand_footprint_never_grows():
    counts = _counts()
    grew = {b: (BASELINE["per_brand"].get(b, 0), n)
            for b, n in counts.items() if n > BASELINE["per_brand"].get(b, 0)}
    assert not grew, (
        "brand knowledge in devices/base.py grew: "
        + ", ".join(f"{b} {was}→{now}" for b, (was, now) in grew.items())
        + ". The generic layer knows about DEVICES; adapters know about "
        "brands. If this addition genuinely cannot live in an adapter, say "
        "why in the diff and regenerate the baseline — but that is the "
        "question #855 exists to keep asking."
    )


def test_a_shrink_is_recorded_not_silent():
    """Shrink fails too — with good news. A retirement must show up as a
    line in the diff, exactly like #830's option ratchet, so the ceiling
    is never quietly loosened."""
    total = sum(_counts().values())
    assert total >= BASELINE["total"], (
        f"good news: the footprint fell {BASELINE['total']} → {total}. "
        "Regenerate so the win is recorded and cannot be given back:\n"
        "    python3 scripts/audit_brand_footprint.py --baseline"
    )


def test_the_baseline_describes_today():
    """The ratchet is worthless if the baseline drifts from reality."""
    assert sum(_counts().values()) == BASELINE["total"]
    assert _counts() == BASELINE["per_brand"]


def test_the_adapters_are_where_brands_belong():
    """The other half of the invariant, stated as a fact about the tree:
    a per-brand adapter module exists, so there is somewhere to move to."""
    adapters = ROOT / "coordinator" / "charger_adapters"
    assert (adapters / "keba.py").exists()
    assert (adapters / "wallbox.py").exists()
    assert (adapters / "generic.py").exists()
