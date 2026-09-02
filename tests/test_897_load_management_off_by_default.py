"""#897 — load management is OFF on a fresh install, and code, docs and card
say the same thing.

Forum #30: a first-run install shed a Span panel circuit by circuit. The
reporter "realised Load Management defaults to off" — because the USER_GUIDE
said ``false`` — while the code seeded ``True`` at install, sized the ceiling
at 5 kW without asking, and the Config card hid the arm switch outside
*Advanced*. Three surfaces, three answers.

The decision (Guido, 01.09.2026): **off** for a fresh install. A shedder that
switches off house circuits is not something a first run arms unasked. An
existing install is untouched: the install flow has seeded the key since
v1.0.0, so every entry carries its own value and never sees the default.
"""

import re
from pathlib import Path

from custom_components.solar_energy_management.consts.core import (
    DEFAULT_LOAD_MANAGEMENT_ENABLED,
)

ROOT = Path(__file__).resolve().parent.parent
CARD = ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"


def test_a_fresh_install_does_not_arm_the_shedder():
    assert DEFAULT_LOAD_MANAGEMENT_ENABLED is False


def test_every_runtime_reader_resolves_through_the_constant():
    """The class behind #895 and #897 alike: a reader with its own literal
    fallback silently disagrees with the constant the moment it changes.
    ``coordinator.py`` carried ``self.config.get("load_management_enabled",
    True)`` — flip the constant and the coordinator still built a shedder."""
    offenders = []
    for path in [ROOT / "__init__.py", *ROOT.glob("coordinator/*.py"),
                 *ROOT.glob("features/*.py")]:
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(
                r'"load_management_enabled",\s*(True|False)\s*\)', src):
            offenders.append(f"{path.relative_to(ROOT)}: {m.group(0)}")
    assert offenders == [], (
        "literal fallbacks for load_management_enabled — resolve through "
        f"DEFAULT_LOAD_MANAGEMENT_ENABLED instead: {offenders}")


def test_the_user_guide_states_the_real_default():
    """USER_GUIDE.md said ``false`` for four months while the code said
    ``True``; the reporter believed the guide. The row is now pinned to the
    constant so the two cannot drift again."""
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    m = re.search(r"^\| `load_management_enabled` \| (\w+) \|", guide, re.M)
    assert m, "USER_GUIDE.md lost its load_management_enabled row"
    assert m.group(1) == str(DEFAULT_LOAD_MANAGEMENT_ENABLED).lower()


def _essential_controls():
    src = CARD.read_text(encoding="utf-8")
    m = re.search(r"const ESSENTIAL_CONTROLS = new Set\(\[(.*?)\]\)", src,
                  re.DOTALL)
    assert m
    return set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))


def test_the_arm_switch_and_its_ceiling_are_reachable_without_advanced():
    """The shedder can switch off house circuits. Its on/off and the number it
    defends must be one toggle away from nobody — the default view."""
    ctrls = _essential_controls()
    assert "load_management_enabled" in ctrls
    assert "target_peak_limit" in ctrls


def test_the_card_fallback_agrees_with_the_constant():
    """The card cannot import the Python constant; its literal fallback for an
    absent key is pinned here instead."""
    src = CARD.read_text(encoding="utf-8")
    m = re.search(
        r"_renderOptionToggle\('load_management_enabled',\s*'config_lm_enabled',"
        r"\s*opts,\s*'config_help_lm_enabled',\s*(true|false)\)", src)
    assert m, "the load management toggle moved"
    assert m.group(1) == str(DEFAULT_LOAD_MANAGEMENT_ENABLED).lower()


def test_a_setup_overview_route_lands_in_the_default_view():
    """The Setup overview's "optional" chip is how a user reaches load
    management once it is off. Its click opened a section the default view
    filters out — a route to nowhere. A section the user asked for is shown."""
    src = CARD.read_text(encoding="utf-8")
    m = re.search(r"_openSection\(id\) \{(.*?)\n    \}", src, re.DOTALL)
    assert m and "this._revealed" in m.group(1), (
        "_openSection no longer reveals the section it routes to")
    assert "|| this._revealed.has(s.id)" in src, (
        "the section filter ignores a section the user routed to")
