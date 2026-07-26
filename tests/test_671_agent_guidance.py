"""#671 — the agent-facing guidance file must not rot the way it did for 3.5 months.

``.github/copilot-instructions.md`` is the first file an AI agent reads when it
touches this repo, and it sat untouched from ``530db4c`` (v1.0.0, 2026-04-12)
through ~25 releases. By the time anyone re-read it, it claimed
``DEFAULT_UPDATE_INTERVAL = 300  # 5 minutes`` against a real value of ``10``
seconds, gave ``DEFAULT_BATTERY_PRIORITY_SOC`` both a wrong number *and* an
inverted meaning, pointed at six files/dirs that do not exist, named five
constants that do not exist, and documented ``SEM_SENSORS`` — the registry
deleted in #669 — attributed to the wrong module.

Nothing in CI read it, no test asserted any of it, and its readers are agents
that treat it as ground truth and do not check. That is the same silent-failure
condition that let ``consts/sensors.py`` reach 45% dead (#669) and the label
registry reach 38% dead (#667): **a reference nobody resolves.**

The durable fix is not the refresh — a refresh buys another 3.5 months. It is
this: every path the file names must exist, every code symbol it names must
appear in the tree, and it must not restate a numeric constant at all. A doc
that quotes ``= 300`` will drift from the code; a doc that names the file the
constant lives in cannot.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_GUIDANCE = _ROOT / ".github" / "copilot-instructions.md"

_CODE_EXT = (".py", ".md", ".yaml", ".yml", ".js", ".json", ".sh")

# Source of truth for the symbol scan. Excludes docs/ and .github/ so the
# guidance cannot vouch for itself, and node_modules/dist so a vendored bundle
# cannot accidentally satisfy a claim about SEM's own code.
_SOURCE_FILES = tuple(
    path
    for path in _ROOT.rglob("*")
    if path.suffix in (".py", ".yaml", ".js")
    and path.is_file()
    and not any(
        part in {".git", "node_modules", "dist", "docs", ".github", "vendor"}
        for part in path.relative_to(_ROOT).parts
    )
)


def _prose() -> str:
    """The file with fenced code blocks stripped.

    Fenced blocks hold shell recipes with throwaway paths (``/tmp/ha-config``)
    that are created by the command itself. Only inline-backtick claims are
    assertions *about this repo*.
    """
    return re.sub(r"```.*?```", "", _GUIDANCE.read_text(), flags=re.DOTALL)


def _inline_tokens() -> list[str]:
    return re.findall(r"`([^`\n]+)`", _prose())


@pytest.mark.unit
class TestAgentGuidance671:
    def test_the_guidance_file_exists_and_the_scan_sees_it(self):
        """Bug class 8: if the file moved or the regex broke, every assertion
        below would pass vacuously and this guard would be worth nothing."""
        assert _GUIDANCE.exists(), f"{_GUIDANCE} is gone — did it move?"
        tokens = _inline_tokens()
        assert len(tokens) > 30, f"only {len(tokens)} backtick tokens — scan broke"
        assert len(_SOURCE_FILES) > 100, (
            f"only {len(_SOURCE_FILES)} source files — the symbol scan's "
            "haystack is empty, so it would vouch for nothing"
        )

    def test_every_path_it_names_exists(self):
        """The #671 failure, made checkable.

        A token counts as a path claim only if it is a single word containing a
        ``/`` or ending in a source extension, and holds no ``*``. That
        deliberately excludes prose backticks (``main``, ``develop``,
        ``unknown``), dotted attribute access (``power.ev_power``,
        ``states.get``), shell one-liners with spaces (``cd dashboard/card &&
        npm run build``), and globs (``*_GUIDE.md`` names a set, not a file) —
        a guard that cries wolf on those gets routed around instead of fixed.

        The exclusions were derived by running it, not guessed: the first
        version flagged a glob and a deliberate *negative* claim ("this repo has
        no wrapper directory"). The glob is excluded here; the negation was
        reworded, because teaching the rule to parse English negation would
        make it unpredictable — and an unpredictable guard is one people mute.
        """
        missing = []
        for token in _inline_tokens():
            if " " in token or "*" in token:
                continue
            if "/" not in token and not token.endswith(_CODE_EXT):
                continue
            target = token.rstrip("/")
            if not (_ROOT / target).exists():
                missing.append(token)
        assert not missing, (
            f"guidance names paths that do not exist: {sorted(set(missing))}. "
            "The previous version named six such (run_tests.sh, "
            "hardware_scanner.py, migration/backfill_sem_statistics.py, "
            "docs/technical/, docs/migration/, dashboard/docs/) and nothing "
            "noticed for 3.5 months (#671)."
        )

    def test_every_code_symbol_it_names_exists_in_the_tree(self):
        """The other half: five named constants had no definition anywhere.

        Restricted to tokens that are unambiguously code — a bare identifier
        with an underscore or an internal capital. English words in backticks
        are not claims about the tree.
        """
        symbols = [
            t for t in _inline_tokens()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t)
            and ("_" in t or re.search(r"[a-z][A-Z]", t))
        ]
        assert symbols, "no code symbols found — the filter is too strict"

        # A filesystem walk, deliberately NOT ``git grep``: CI copies the tree
        # to /tmp WITHOUT .git, so a git-backed scan would fail for every symbol
        # there while passing locally — a guard that only works on the author's
        # machine. Caught by running it, not by reasoning about it.
        haystack = "\n".join(
            path.read_text(errors="ignore")
            for path in _SOURCE_FILES
        )
        unknown = [
            sym for sym in sorted(set(symbols))
            if not re.search(rf"\b{re.escape(sym)}\b", haystack)
        ]
        assert not unknown, (
            f"guidance names symbols found nowhere in the code: {unknown}. "
            "The previous version named DEFAULT_POWER_DELTA, DEFAULT_SOC_DELTA, "
            "DEFAULT_BATTERY_MINIMUM_SOC, DEFAULT_BATTERY_RESUME_SOC and "
            "HARDWARE_PATTERNS, none of which existed (#671)."
        )

    def test_it_does_not_restate_numeric_constants(self):
        """The dangerous half, banned outright rather than checked.

        Two values were not merely stale, they were confidently wrong:
        ``DEFAULT_UPDATE_INTERVAL = 300  # 5 minutes`` (real: ``10`` seconds,
        30x off, with the wrong unit spelled out) and
        ``DEFAULT_BATTERY_PRIORITY_SOC = 90  # Battery first`` (real: ``30``, and
        it is a floor, not a ceiling — the meaning was inverted too).

        Checking a restated value against the code would work, but banning the
        restatement is strictly better: it removes the drift surface instead of
        monitoring it, and the file loses nothing by naming ``const.py`` instead.
        ``docs/BUG_CLASSES.md`` already records the rule — "when a doc states a
        value the code also states, the doc needs a test."

        The header quotes both wrong values as the cautionary example, so the
        scan runs below the header rather than over the whole file.
        """
        prose = _prose()
        marker = "## Project Overview"
        assert marker in prose, "header anchor moved — this scan lost its start"
        body = prose.split(marker, 1)[1]

        restated = re.findall(r"`([A-Z][A-Z0-9_]{3,}\s*[=:]\s*-?\d[\d._]*)`", body)
        assert not restated, (
            f"guidance restates constant values: {restated}. Name the module "
            "the constant lives in instead — a quoted number drifts, a file "
            "reference cannot (#671)."
        )

    def test_the_rules_can_actually_fire(self):
        """Both rules, proven against real #671 input and real live input.

        A rule that only ever passes and a rule that flags everything are
        equally useless, so each direction is checked.
        """
        # Path rule: the real dead reference vs a real live one.
        assert not (_ROOT / "run_tests.sh").exists(), (
            "run_tests.sh is back — pick another known-absent path for this test"
        )
        assert (_ROOT / "hardware_detection.py").exists()

        # Value rule: the exact line that was wrong for 3.5 months.
        pattern = r"`([A-Z][A-Z0-9_]{3,}\s*[=:]\s*-?\d[\d._]*)`"
        bad = re.findall(pattern, "text `DEFAULT_UPDATE_INTERVAL = 300` more")
        assert bad, "the restated-constant shape #671 was about would be missed"

        good = re.findall(pattern, "see `const.py` for `DEFAULT_UPDATE_INTERVAL`")
        assert not good, "the rule would flag a bare reference — it must not"
