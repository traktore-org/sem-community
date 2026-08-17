"""The CI matrix must vary Home Assistant, not just Python (#787).

For nineteen months every one of SEM's tests ran against Home Assistant
2025.1.4 while users ran 2026.8.x. Nobody noticed, because nothing said
out loud which HA the suite was actually exercising: the matrix listed
Python 3.12 and 3.13, both legs installed the same
``pytest-homeassistant-custom-component`` pin, and that pin — not the
matrix — chose the HA.

``phacc`` pins exactly one HA version per release and each release has a
Python floor, so the interpreter *is* the HA selector:

    0.13.205  (py3.12+)  ->  homeassistant 2025.1.4
    0.13.316  (py3.13+)  ->  homeassistant 2026.2.3
    0.13.356  (py3.14+)  ->  homeassistant 2026.8.2

This file pins the shape, not the numbers. It fails when a matrix leg has
no pin that applies to it (the leg would silently resolve to whatever pip
picks that day), when the pins collapse onto a single HA (the 2025→2026
blind spot, reopened), or when the HA version ``hacs.json`` promises to
support stops being one of the versions actually tested.

The numbers themselves live in ``tests/requirements_test.txt``, declared
next to the pin they describe. Bumping a pin without saying which HA it
brings fails here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "tests.yml"
REQUIREMENTS = REPO / "tests" / "requirements_test.txt"
HACS = REPO / "hacs.json"

PHACC = "pytest-homeassistant-custom-component"


def _matrix_python_versions() -> list[str]:
    """The ``python-version`` list from the Tests workflow.

    Parsed with a regex rather than a YAML loader: the workflow is full of
    ``${{ }}`` expressions and this only needs one line. The assertion
    below that the list is non-empty is what catches a parse that drifted.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(r"python-version:\s*\[([^\]]+)\]", text)
    assert m, f"no `python-version: [...]` matrix found in {WORKFLOW.name}"
    return re.findall(r'"([^"]+)"', m.group(1))


def _declared_pins() -> list[tuple[str, tuple[int, ...], str, str]]:
    """Every phacc pin in requirements_test.txt, with its marker and HA.

    Returns ``(version, python_floor, marker_op, ha_version)`` per line.
    The HA version is read from a trailing ``# -> homeassistant X.Y.Z``
    comment on the same line — the pin and the thing it actually selects
    have to be written down together or the next reader learns nothing.
    """
    out = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith(PHACC):
            continue
        ver = re.search(rf"{re.escape(PHACC)}==([\d.]+)", line)
        marker = re.search(r'python_version\s*(>=|==|<)\s*"([\d.]+)"', line)
        ha = re.search(r"->\s*homeassistant\s+([\d.]+)", line)
        assert ver, f"phacc line without an exact pin: {raw}"
        assert marker, (
            f"phacc pin without a python_version marker: {raw}\n"
            "Every pin must say which interpreter it applies to, or a "
            "matrix leg resolves to whatever pip feels like."
        )
        assert ha, (
            f"phacc pin without a `# -> homeassistant X.Y.Z` note: {raw}\n"
            "The pin selects the HA under test. Write down which one."
        )
        floor = tuple(int(p) for p in marker.group(2).split("."))
        out.append((ver.group(1), floor, marker.group(1), ha.group(1)))
    assert out, f"no {PHACC} pin found in {REQUIREMENTS.name}"
    return out


def _ha_for(python_version: str) -> str | None:
    """Which HA a given matrix leg installs, per the declared markers."""
    py = tuple(int(p) for p in python_version.split("."))
    for _ver, floor, op, ha in _declared_pins():
        if op == ">=" and py >= floor:
            return ha
        if op == "==" and py == floor:
            return ha
        if op == "<" and py < floor:
            return ha
    return None


def test_every_matrix_leg_has_a_pin_that_applies_to_it():
    """A leg with no matching marker installs an unpinned HA."""
    unpinned = [v for v in _matrix_python_versions() if _ha_for(v) is None]
    assert not unpinned, (
        "These CI matrix legs have no phacc pin whose python_version marker "
        f"matches, so pip picks the HA for them: {unpinned}. Add a pin in "
        f"{REQUIREMENTS.name}."
    )


def test_the_matrix_varies_home_assistant_not_only_python():
    """The #787 bug itself: two legs, one HA, nineteen months unnoticed."""
    versions = _matrix_python_versions()
    covered = {_ha_for(v) for v in versions} - {None}
    assert len(covered) > 1, (
        f"The CI matrix runs {versions} but every leg installs the same Home "
        f"Assistant ({covered}). Varying the interpreter against a fixed HA "
        "is the axis that matters least — SEM breaks on HA API drift, not on "
        "Python minor versions. Give at least one leg a newer phacc pin."
    )


def test_the_supported_floor_is_a_version_we_actually_test():
    """`hacs.json` is a promise. Test the version it promises."""
    floor = json.loads(HACS.read_text(encoding="utf-8"))["homeassistant"]
    covered = {_ha_for(v) for v in _matrix_python_versions()} - {None}

    def parts(v):
        return tuple(int(p) for p in v.split("."))

    # A pin of 2025.1.4 satisfies a declared floor of 2025.1.0: same release
    # line, patch-level ahead. A floor of 2026.x with nothing tested above
    # 2025.x does not.
    assert any(parts(c)[:2] == parts(floor)[:2] and parts(c) >= parts(floor)
               for c in covered), (
        f"hacs.json promises Home Assistant {floor} but CI tests {sorted(covered)}. "
        "Either test the floor or stop promising it."
    )


def test_the_newest_tested_ha_is_not_a_year_behind():
    """The drift itself, bounded.

    Not 'must equal the newest HA' — that would fail every month on the
    upstream release cadence, and a gate that reddens by itself gets
    muted. This fails only when the newest HA under test falls a full
    year behind the newest phacc pin we have declared, which is the
    slope #787 was filed about.
    """
    pins = _declared_pins()
    newest_declared = max(tuple(int(p) for p in ha.split(".")) for *_, ha in pins)
    covered = {_ha_for(v) for v in _matrix_python_versions()} - {None}
    if not covered:
        pytest.skip("covered by test_every_matrix_leg_has_a_pin_that_applies_to_it")
    newest_tested = max(tuple(int(p) for p in c.split(".")) for c in covered)

    # HA versions are YEAR.MONTH.PATCH.
    months_behind = (newest_declared[0] - newest_tested[0]) * 12 + (
        newest_declared[1] - newest_tested[1]
    )
    assert months_behind < 12, (
        f"The newest HA any CI leg installs is {newest_tested}, but "
        f"{REQUIREMENTS.name} declares a pin for {newest_declared} — "
        f"{months_behind} months of API drift that no test ever sees. "
        "Add the matrix leg that uses it."
    )
