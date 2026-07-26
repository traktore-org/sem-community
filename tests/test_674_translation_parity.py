"""#674 — ``strings.json`` and ``translations/`` must not drift apart.

``strings.json`` is where a developer naturally edits: it is Home Assistant's
documented source file and the one hassfest validates. But **HA never reads it
at runtime for a custom component.** ``helpers/translation.py`` builds its file
list as ``integration.file_path / "translations" / f"{language}.json"`` and
nothing else. In HA core a build step copies ``strings.json`` into
``translations/en.json``; SEM has no such step, so the two are a hand-maintained
mirror — and they had drifted 50 keys one way and 35 the other, identically in
all 16 languages.

What that cost users: the entire Heat Pump options step (``async_step_heat_pump``,
live in ``OptionsFlowHandler``) rendered with no title, no description and eight
raw voluptuous keys instead of labels, because the frontend falls back to the
key name when a label is missing. Same for the EV-charger add/remove menu. The
``soc_cap_unenforceable`` repair issue — one of the most carefully written
strings in the repo — had no title or description at all. Three exception
messages and one config-flow error resolved to their bare keys.

**Bug class 24**, a hand-maintained list mirroring a structure that grows —
third instance after #668 (storage whitelist, 11 of 20) and #673
(``services.yaml``, 14 of 18). Unlike those two this one *is* derivable, so the
guard demands exact parity rather than merely flagging additions.

Silent by construction, like every sibling in this family (#667/#669/#671/#672/
#673): a missing translation key never raises. The step still opens, it is just
illegible — so it survives every test, every deploy and every reviewer who does
not happen to open that particular step in that particular language.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_STRINGS = _ROOT / "strings.json"
_TRANSLATIONS = sorted((_ROOT / "translations").glob("*.json"))

# Every ``{placeholder}`` HA will ``.format()`` into the string. A translation
# that drops one silently prints nothing useful; one that *invents* one raises
# KeyError at render time, which is worse — it turns a label into a traceback.
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def _flat(data: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flat(value, path))
        else:
            out[path] = value
    return out


def _load(path: Path) -> dict[str, str]:
    return _flat(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.unit
class TestTranslationParity674:
    def test_the_scan_sees_both_sides(self):
        """Bug class 8: two empty dicts are trivially equal, and this guard
        would then certify a completely unlocalised integration."""
        assert _STRINGS.is_file(), "strings.json is gone — retarget this guard"
        assert len(_TRANSLATIONS) >= 16, (
            f"only {len(_TRANSLATIONS)} translation files found — SEM ships 16"
        )
        source = _load(_STRINGS)
        assert len(source) > 400, (
            f"strings.json flattened to only {len(source)} keys — the scan "
            "broke, or the file was gutted. Fix the scan; do not relax this."
        )

    def test_every_language_has_exactly_the_source_keys(self):
        """Both directions, per language.

        Missing is the #674 failure: the string does not render at all. Extra is
        the quieter one — a key no longer in ``strings.json`` is dead weight
        every translator pays for (#673 found 288 such strings for a config-flow
        step that never existed).
        """
        source = set(_load(_STRINGS))
        problems: list[str] = []
        for path in _TRANSLATIONS:
            keys = set(_load(path))
            if missing := sorted(source - keys):
                problems.append(
                    f"{path.name}: {len(missing)} keys in strings.json but not "
                    f"here — they render as raw keys: {missing[:6]}"
                    + (" …" if len(missing) > 6 else "")
                )
            if extra := sorted(keys - source):
                problems.append(
                    f"{path.name}: {len(extra)} keys here but not in "
                    f"strings.json — dead, or strings.json is stale: {extra[:6]}"
                    + (" …" if len(extra) > 6 else "")
                )
        assert not problems, (
            "strings.json and translations/ have drifted (#674).\n  "
            + "\n  ".join(problems)
            + "\n\nHA reads ONLY translations/<lang>.json at runtime; "
            "strings.json is never loaded for a custom component. Add the key "
            "to every language, or delete it from strings.json if it is dead."
        )

    def test_no_translation_invents_or_drops_a_placeholder(self):
        """A dropped ``{name}`` loses information; an invented one is a
        KeyError at render time, because HA ``.format()``s the string with
        exactly the placeholders the caller passed."""
        source = _load(_STRINGS)
        problems: list[str] = []
        for path in _TRANSLATIONS:
            for key, value in _load(path).items():
                if key not in source or not isinstance(value, str):
                    continue
                want = set(_PLACEHOLDER.findall(source[key]))
                got = set(_PLACEHOLDER.findall(value))
                if got - want:
                    problems.append(
                        f"{path.name}:{key} invents {sorted(got - want)} — "
                        "this raises KeyError when HA formats it"
                    )
                elif want - got:
                    problems.append(
                        f"{path.name}:{key} drops {sorted(want - got)}"
                    )
        assert not problems, "placeholder drift (#674):\n  " + "\n  ".join(problems)

    def test_the_rule_can_actually_fire_parity(self):
        """Both directions, on real data — a guard that only ever passes and
        one that flags everything are equally useless."""
        source = _load(_STRINGS)
        en = _load(_ROOT / "translations" / "en.json")
        assert source and en, "one side loaded empty — the flattener is broken"

        # The #674 shape: a key present on one side only must be detected.
        assert "options.step.heat_pump.title" in source, (
            "the heat-pump step lost its title again — that was the headline "
            "symptom of #674"
        )
        assert set(source) - (set(en) - {"options.step.heat_pump.title"}), (
            "removing a key from one side produced no difference — the "
            "comparison above cannot fail"
        )
        # And the placeholder rule has real placeholders to work with.
        assert _PLACEHOLDER.findall(source["issues.soc_cap_unenforceable.title"]), (
            "no placeholders in a string known to have {target} and {name} — "
            "the placeholder regex is broken"
        )


@pytest.mark.unit
class TestConfigFlowStringsResolve674:
    """The same rot one level in: strings the flow *uses* vs strings it declares.

    Writing the parity guard above surfaced that the two files agreeing with
    each other says nothing about either agreeing with the code. Three separate
    failures were sitting behind that:

    * **Two abort reasons that did not exist.** ``async_abort(reason=
      "energy_dashboard_not_configured")`` and ``…_incomplete`` are what a brand
      new user hits when they install SEM before configuring HA's Energy
      Dashboard — the first words SEM ever says to them. Neither had a
      ``config.abort`` entry, so HA rendered the raw key as the entire failure
      message: no explanation, no link to ``/config/energy``, even though the
      code carefully passes ``{url}`` and ``{missing}`` for a message that was
      never written.
    * **Twelve config errors nothing assigns.** Per-sensor validation messages
      ("Battery power sensor is required and must provide readings in Watts…")
      left over from the validation design the #397 slim-down replaced. Four of
      the sixteen declared error keys are actually reachable. Deleted rather
      than resurrected: restoring the validation is a feature decision, and a
      translated string for a code path that does not exist is the #673
      ``dashboard_options`` shape — it reads as covered.
    * **Placeholders nobody supplies.** ``config.error.entity_not_found`` said
      "Entity {entity_id} was not found", and ``service_not_found`` named
      ``{service}`` — but neither call site passes those in
      ``description_placeholders``, so the user read the literal token
      ``{entity_id}``. Five files carried the placeholder version, two the
      correct generic one; nothing could tell them apart.

    All three are the same silent-by-construction shape as the parity failure:
    HA falls back to *something* renderable for a missing key, so the flow still
    opens and no test fails.
    """

    _FLOW = _ROOT / "config_flow.py"

    # HA sets this one itself via _abort_if_unique_id_configured(), so it is
    # declared-but-never-literally-written and must not read as dead.
    _IMPLICIT_ABORTS = {"already_configured"}

    def _src(self) -> str:
        return self._FLOW.read_text(encoding="utf-8")

    def _config_block(self, name: str) -> dict:
        return json.loads(_STRINGS.read_text(encoding="utf-8"))["config"][name]

    def test_the_scans_find_something(self):
        """Bug class 8 — every assertion below compares two scanned sets, so a
        regex that stopped matching would make all of them pass on empty."""
        src = self._src()
        assert len(src) > 50_000, "config_flow.py shrank unexpectedly"
        assert re.findall(r'errors\[[^\]]+\]\s*=\s*"([a-z_]+)"', src)
        assert re.findall(r'reason\s*=\s*"([a-z_]+)"', src)
        assert re.findall(r"description_placeholders\s*=\s*\{", src)

    def test_every_error_key_is_both_declared_and_reachable(self):
        declared = set(self._config_block("error"))
        assigned = set(re.findall(r'errors\[[^\]]+\]\s*=\s*"([a-z_]+)"', self._src()))
        assert not (assigned - declared), (
            f"config_flow.py sets errors the strings do not declare: "
            f"{sorted(assigned - declared)} — the user sees the raw key (#674)"
        )
        assert not (declared - assigned), (
            f"config.error keys nothing ever assigns: {sorted(declared - assigned)}. "
            "Every language pays to translate these and no user can reach them. "
            "Delete them, or wire up the validation that was meant to set them "
            "(#674)."
        )

    def test_every_abort_reason_has_a_message(self):
        declared = set(self._config_block("abort"))
        used = set(re.findall(r'reason\s*=\s*"([a-z_]+)"', self._src()))
        assert not (used - declared), (
            f"async_abort reasons with no config.abort entry: "
            f"{sorted(used - declared)}. HA renders the bare reason string as "
            "the whole message — this is what a new user sees instead of the "
            "setup wizard (#674)."
        )
        assert not (declared - used - self._IMPLICIT_ABORTS), (
            f"config.abort entries no code path reaches: "
            f"{sorted(declared - used - self._IMPLICIT_ABORTS)} (#674)"
        )

    def test_no_flow_string_names_a_placeholder_the_flow_never_supplies(self):
        """A placeholder HA is never handed renders as the literal ``{token}``.

        Only ``description_placeholders`` in ``config_flow.py`` can fill these,
        so the supplied set is exactly what that file passes.
        """
        supplied: set[str] = set()
        for block in re.findall(
            r"description_placeholders\s*=\s*\{(.*?)\}", self._src(), re.S
        ):
            supplied |= set(re.findall(r'"([a-z_][a-z0-9_]*)"\s*:', block))

        source = _load(_STRINGS)
        orphans: list[str] = []
        for key, value in source.items():
            if not key.startswith(("config.", "options.")) or not isinstance(value, str):
                continue
            for token in set(_PLACEHOLDER.findall(value)) - supplied:
                orphans.append(f"{key} names {{{token}}}")
        assert not orphans, (
            "flow strings naming placeholders config_flow.py never passes — "
            "these render as the literal token to the user (#674):\n  "
            + "\n  ".join(sorted(orphans))
        )

    def test_the_rules_can_actually_fire(self):
        """Each rule must reject a real bad input and accept a real good one."""
        declared_aborts = set(self._config_block("abort"))
        # Real good input: the two reasons #674 added must now resolve.
        assert {"energy_dashboard_not_configured", "energy_dashboard_incomplete"} <= (
            declared_aborts
        ), "the #674 abort messages are gone again"
        # Real bad input: a reason that does not exist must not be tolerated.
        assert "energy_dashboard_on_fire" not in declared_aborts

        # The placeholder rule has real placeholders on both sides to compare.
        supplied = set(
            re.findall(
                r'"([a-z_][a-z0-9_]*)"\s*:',
                " ".join(
                    re.findall(
                        r"description_placeholders\s*=\s*\{(.*?)\}", self._src(), re.S
                    )
                ),
            )
        )
        assert {"url", "missing"} <= supplied, (
            "the abort call sites stopped passing {url}/{missing} — the rule "
            "above would now reject the messages that use them"
        )
        assert "entity_id" not in supplied, (
            "entity_id is supplied now — if the flow really passes it, the "
            "placeholder may go back into config.error.entity_not_found"
        )
