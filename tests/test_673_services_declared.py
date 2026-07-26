"""#673 — services.yaml must declare every service SEM registers.

``services.yaml`` is a hand-maintained mirror of what ``__init__.py`` actually
calls ``hass.services.async_register`` for. It had drifted to 14 of 18.

The gap is invisible by construction, which is why it survived: an undeclared
service is still fully callable, so nothing raises and no test fails. What it
loses is its entire UI affordance — in Developer Tools → Actions it shows up
with no description, no field pickers and no validation, so the caller has to
already know the parameter names and hand-write YAML.

That landed hardest on ``diagnose``, the one service the troubleshooting docs
tell users to call: ``docs/SEM_TRACE.md`` says "call the
``solar_energy_management.diagnose`` service with ``section: trace``", and a
user following that instruction met an action with no ``section`` dropdown and
no hint that ``trace`` was one of twelve valid values. ``remove_charger`` is
user-facing too; ``get_config`` / ``set_option`` are called by the dashboard
config card, but omission is not a hiding mechanism in HA — they appeared in
the picker regardless, just undocumented.

**Bug class 24** — a hand-maintained list mirroring a structure that grows,
the same shape as #668 (the storage whitelist carried 11 of 20 calculator
keys). Both sides agree on spelling; one side simply does not list the key, so
no lookup ever misses and nothing reports the gap.

Unlike #668 this cannot be closed by deriving one list from the other:
``services.yaml`` holds descriptions and selectors only a human can write. So
the closure is this guard — the moment a service is registered without a
declaration, CI says so.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_INIT = _ROOT / "__init__.py"
_SERVICES_YAML = _ROOT / "services.yaml"

# Matches ``async_register(DOMAIN, "name"`` and its admin variant, tolerating
# the ``hass,`` first arg and a line break before the name (both styles are
# present in __init__.py).
_REGISTER = re.compile(
    r'async_register(?:_admin)?\s*\(\s*(?:hass\s*,\s*)?DOMAIN\s*,\s*\n?\s*"([a-z_]+)"'
)


def _registered() -> set[str]:
    return set(_REGISTER.findall(_INIT.read_text()))


def _declared() -> set[str]:
    return set(yaml.safe_load(_SERVICES_YAML.read_text()))


@pytest.mark.unit
class TestServicesDeclared673:
    def test_the_scan_finds_registrations(self):
        """Bug class 8: a regex that silently matched nothing would make the
        equality below trivially satisfiable by an empty set on one side, and
        this guard would certify a completely undeclared service surface."""
        registered = _registered()
        assert len(registered) >= 18, (
            f"only {len(registered)} async_register calls found — the scan "
            "broke, or a registration style this regex does not know about "
            "was introduced. Fix the scan; do not relax the assertion."
        )
        assert "diagnose" in registered, "the #673 service itself went missing"

    def test_the_yaml_parses_and_is_not_empty(self):
        declared = _declared()
        assert len(declared) >= 18, f"services.yaml declares only {len(declared)}"

    def test_every_registered_service_is_declared(self):
        """The #673 direction: code grew, the yaml did not."""
        missing = sorted(_registered() - _declared())
        assert not missing, (
            f"registered but absent from services.yaml: {missing}. They are "
            "still callable, which is exactly why nobody noticed — but in "
            "Developer Tools → Actions they have no description, no field "
            "pickers and no validation. Add an entry with name/description/"
            "fields (#673)."
        )

    def test_every_declared_service_is_registered(self):
        """The opposite direction, which has never fired but is the more
        user-hostile of the two: a service advertised in the UI that does not
        exist fails only when someone calls it, and reads as a broken
        integration rather than a stale file."""
        phantom = sorted(_declared() - _registered())
        assert not phantom, (
            f"declared in services.yaml but never registered: {phantom}. HA "
            "would offer these in the Actions picker and they would fail on "
            "call (#673)."
        )

    def test_the_documented_diagnose_sections_are_offered_in_the_ui(self):
        """The specific user-visible failure, pinned.

        A ``section`` field with the wrong option list is no better than no
        field at all — the docs would still be the only place the valid values
        exist. ``trace`` is checked by name because it is the one
        ``docs/SEM_TRACE.md`` instructs users to pass.
        """
        spec = yaml.safe_load(_SERVICES_YAML.read_text())["diagnose"]
        options = spec["fields"]["section"]["selector"]["select"]["options"]

        src = _INIT.read_text()
        slicers = set(re.findall(r'^\s{8}"([a-z_]+)":\s*\(_DIAGNOSE_', src, re.M))
        assert slicers, "could not find _DIAGNOSE_SLICERS — retarget this scan"

        missing = sorted(slicers - set(options))
        assert not missing, (
            f"diagnose sections the code handles but the UI does not offer: "
            f"{missing} (#673)"
        )
        assert "trace" in options, (
            "docs/SEM_TRACE.md tells users to pass section: trace — it must be "
            "in the dropdown, or the docs remain the only place it exists"
        )

    def test_the_rule_can_actually_fire(self):
        """Prove the equality is real, not a comparison of two empty sets."""
        assert _registered(), "no services registered — the scan is broken"
        assert "generate_dashboard" in _registered() & _declared()
        # A name in neither set must not be silently tolerated by either check.
        assert "not_a_real_service" not in _registered() | _declared()


@pytest.mark.unit
class TestTranslationStepsDeclared673:
    """The same mirror, in the direction that had actually drifted.

    Found by running the widened sweep question this issue added to
    ``docs/BUG_CLASSES.md`` rather than leaving it rhetorical: *for every
    hand-written list mirroring a code structure — is it derived, or merely
    asserted equal?*

    ``translations/*.json`` mirrors the config-flow's step ids. An
    ``options.step.dashboard_options`` block existed in **all 16 languages**
    — title, description, 8 field labels and 8 field descriptions, 288
    translated strings — for a step no ``async_step_dashboard_options`` has
    ever existed to show. Dead surface that reads as covered: it looked like
    a fully-localized feature, and every translator who worked the file paid
    for it.

    Harmless at runtime (HA only looks up steps it is asked for), which is
    precisely why it survived. The cost is translator effort and the false
    impression that a Dashboard Installation options step exists.
    """

    _FLOW = _ROOT / "config_flow.py"

    def _code_steps(self) -> set[str]:
        return set(re.findall(r"async_step_([a-z0-9_]+)\s*\(", self._FLOW.read_text()))

    def test_the_scan_finds_flow_steps(self):
        steps = self._code_steps()
        assert len(steps) > 10, f"only {len(steps)} async_step_ methods — scan broke"
        assert "settings" in steps

    def test_no_language_translates_a_step_that_does_not_exist(self):
        import json

        code_steps = self._code_steps()
        orphans: dict[str, list[str]] = {}
        for path in sorted((_ROOT / "translations").glob("*.json")):
            data = json.loads(path.read_text())
            for block in ("config", "options"):
                bad = sorted(
                    set(data.get(block, {}).get("step", {})) - code_steps
                )
                if bad:
                    orphans.setdefault(path.name, []).extend(bad)
        assert not orphans, (
            f"translated steps with no async_step_ method: {orphans}. Every "
            "language pays for these and no user ever sees them (#673)."
        )

    def test_the_rule_can_actually_fire(self):
        """The removed block is the fixture: if `dashboard_options` were
        re-added to any language, the check above must catch it."""
        assert "dashboard_options" not in self._code_steps(), (
            "an async_step_dashboard_options now exists — this step is real, "
            "so restore its translations instead of keeping this assertion"
        )
