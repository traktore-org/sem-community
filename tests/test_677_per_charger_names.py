"""Per-charger entities must resolve a translation, and it must name the charger.

#677. Two opposite failures from the same #255 global→per-charger split:

* **numbers kept the discriminator and lost the translation.** The entity
  description key carries the charger id (``charger_keba_target_soc``), so it
  can never be declared in ``strings.json``. ``SEMPerChargerNumber`` used it as
  the translation key anyway; HA looked it up, missed, and fell back to
  ``entity_description.name`` — a hardcoded English f-string. Nine sliders read
  English on every install regardless of language.
* **selects kept the translation and lost the discriminator.** They already
  keyed on the bare config key, which resolves — but the name carried no
  charger, so on a two-charger install both selects rendered the *same*
  friendly name with different entity_ids.

The fix is one mechanism for both: bare config key as the translation key,
charger name supplied as a ``{charger}`` placeholder.

That places a live constraint on the pair. HA's
``Entity._substitute_name_placeholders`` does ``name.format(**placeholders)``
and on a mismatch *raises* ``HomeAssistantError`` outside the stable release
channel. So a name string naming a placeholder the entity does not supply is a
crash, not a cosmetic defect — hence the placeholder rule below is checked in
both directions, like the #674 one.

Same class as #674 (**bug class 24** — a reference nobody resolves), and the
same closure shape: the live key set is *derivable* from the source, so the
guard demands exact parity rather than flagging additions.
"""
import json
import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_TRANSLATIONS = sorted((_ROOT / "translations").glob("*.json"))

# The only placeholder a per-charger entity name may use. ``number.py`` and
# ``select.py`` both pass exactly ``{"charger": cname}``.
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def per_charger_translation_keys() -> dict[str, tuple[str, ...]]:
    """Derive the per-charger translation keys from the platform source.

    These are invisible to the ``key="…"`` scan in ``test_translations.py``:
    the descriptions build their key with an f-string (``key=f"charger_{cid}_…"``)
    and the *translation* key is the bare config key passed alongside. So the
    keys are read off the construction call sites instead.

    Exported rather than inlined so ``test_translations.py`` can use the same
    derivation — the alternative was a hand-maintained exemption list beside a
    hand-maintained key list, which is the very shape #668/#673/#674 kept
    failing on.
    """
    number_src = (_ROOT / "number.py").read_text(encoding="utf-8")
    start = number_src.index("# Per-charger number entities (#193)")
    end = number_src.index("per_charger_descriptions.append(base_desc)")
    numbers = re.findall(r'\)\s*,\s*"([a-z_0-9]+)"\s*,', number_src[start:end])

    select_src = (_ROOT / "select.py").read_text(encoding="utf-8")
    selects = re.findall(r'entry,\s*cid,\s*"([a-z_0-9]+)"\s*,', select_src)

    return {"number": tuple(numbers), "select": tuple(selects)}


class TestPerChargerNamesResolve677:
    """Every per-charger entity has a translation key that exists everywhere."""

    def test_the_derivation_sees_both_platforms(self):
        """Bug class 8: an empty derivation would make every check below pass."""
        keys = per_charger_translation_keys()
        assert len(keys["number"]) >= 9, (
            f"only {len(keys['number'])} per-charger numbers derived — the "
            "regex or the block markers in number.py moved"
        )
        assert len(keys["select"]) >= 2, (
            f"only {len(keys['select'])} per-charger selects derived — the "
            "construction call shape in select.py moved"
        )
        assert len(_TRANSLATIONS) >= 16, (
            f"only {len(_TRANSLATIONS)} language files found — the glob broke"
        )

    def test_every_per_charger_key_is_declared_in_every_language(self):
        """The #677 bug itself: a key HA looks up and never finds."""
        derived = per_charger_translation_keys()
        missing = []
        for path in [_ROOT / "strings.json", *_TRANSLATIONS]:
            doc = json.loads(path.read_text(encoding="utf-8"))
            entity = doc.get("entity", {})
            for domain, names in derived.items():
                section = entity.get(domain, {})
                for key in names:
                    if key not in section or not section[key].get("name"):
                        missing.append(f"{path.name}: entity.{domain}.{key}")

        assert not missing, (
            f"{len(missing)} per-charger entity names have no translation to "
            "resolve to — HA falls back to entity_description.name, which is "
            "English (#677):\n" + "\n".join(f"  {m}" for m in sorted(missing))
        )

    def test_every_per_charger_name_names_the_charger(self):
        """Without ``{charger}`` a two-charger install shows duplicate names.

        Checked in both directions: a name that omits it loses the
        discriminator, and a name that invents a *different* placeholder is a
        ``HomeAssistantError`` at render time, because the entity only ever
        supplies ``charger``.
        """
        derived = per_charger_translation_keys()
        bad = []
        for path in [_ROOT / "strings.json", *_TRANSLATIONS]:
            doc = json.loads(path.read_text(encoding="utf-8"))
            entity = doc.get("entity", {})
            for domain, names in derived.items():
                for key in names:
                    name = entity.get(domain, {}).get(key, {}).get("name")
                    if not name:
                        continue  # reported by the parity test above
                    found = set(_PLACEHOLDER.findall(name))
                    if found != {"charger"}:
                        bad.append(
                            f"{path.name}: entity.{domain}.{key} = {name!r} "
                            f"has placeholders {sorted(found) or 'none'}"
                        )

        assert not bad, (
            f"{len(bad)} per-charger names do not use exactly one "
            "'{charger}' placeholder — missing it renders identical names on "
            "multi-charger installs, and any other name raises "
            "HomeAssistantError in Entity._substitute_name_placeholders "
            "(#677):\n" + "\n".join(f"  {b}" for b in sorted(bad))
        )

    def test_the_entities_key_on_the_config_key_and_supply_the_placeholder(self):
        """The code half of the contract — this is the regression that shipped.

        ``_attr_translation_key = description.key`` is what made the lookup
        miss. Both classes must key on the bare config key *and* pass the
        placeholder the names above depend on.
        """
        for fname, cls in (("number.py", "SEMPerChargerNumber"),
                           ("select.py", "SEMPerChargerSelect")):
            src = (_ROOT / fname).read_text(encoding="utf-8")
            body = src[src.index(f"class {cls}"):]
            body = body[:body.index("\n\nclass ")] if "\n\nclass " in body else body

            assert '_attr_translation_key = config_key' in body, (
                f"{cls} must set _attr_translation_key from the bare config "
                "key — keying on description.key is #677 itself, because the "
                "description key carries the charger id and no strings.json "
                "can declare it"
            )
            assert '_attr_translation_placeholders = {"charger"' in body, (
                f"{cls} must supply the {{charger}} placeholder every "
                "translated name uses, or HA raises at render time"
            )

    def test_the_rules_can_actually_fire(self):
        """Bug class 8: reject real bad input, accept real good input."""
        derived = per_charger_translation_keys()
        assert "ev_target_soc" in derived["number"], (
            "known per-charger config key vanished from the derivation"
        )
        assert "charge_mode" in derived["select"]
        # description keys must NOT be what we derived — that confusion is the bug
        assert not any(k.startswith("charger_") for ks in derived.values() for k in ks), (
            "the derivation picked up description keys (charger_<id>_…) "
            "instead of config keys — it is measuring the wrong thing"
        )

        good, bad_missing, bad_wrong = "{charger} Phases", "Phases", "{name} Phases"
        assert set(_PLACEHOLDER.findall(good)) == {"charger"}
        assert set(_PLACEHOLDER.findall(bad_missing)) != {"charger"}
        assert set(_PLACEHOLDER.findall(bad_wrong)) != {"charger"}


class TestNoStaleGlobalKeys677:
    """The deleted #676 keys must not creep back as globals."""

    def test_per_charger_keys_are_not_also_global_entity_keys(self):
        """A bare config key now means 'per-charger'. If a *global* entity
        description ever claims the same key, the two share one translation
        and the ``{charger}`` placeholder becomes unsatisfiable for the global
        one — which raises. Catch the collision at the source instead."""
        from .test_translations import _extract_entity_keys

        derived = per_charger_translation_keys()
        collisions = [
            f"{domain}.{key}"
            for domain, names in derived.items()
            for key in names
            if (domain, key) in _extract_entity_keys()
        ]
        assert not collisions, (
            "per-charger translation keys are also claimed by a global entity "
            "description; the global one has no charger to substitute and will "
            "raise HomeAssistantError: " + ", ".join(sorted(collisions))
        )
