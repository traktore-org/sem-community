"""#830 — the default view is shrink-only, and it has no name.

Rule: *"if a user is starting with SEM he is overwhelmed with so many options
and stops using it — it is just too much."* And on naming: *"we do not name it
beginner. It's just nameless and advanced view."* Nobody is labelled a
beginner; there is the configuration, and a switch for whoever wants the
rest. The switch has two named states, **Everyday** (the default view) and
**All settings**, and neither labels the person using it.

A default view is only useful while it stays small. Every control on it arrived
for a good reason, which is exactly how ninety happened in the first place — so
the essential list is ratcheted the same shrink-only way as the option surface:
growth fails and has to be argued for.

Two properties matter as much as the size:

* **advanced hides nothing.** Everything remains one toggle away, so the split
  can never lose someone a setting they need;
* **a configured subsystem stays visible.** Hiding a section a user has already
  set up is not simplification, it is losing their work — so the section filter
  consults the Setup overview's own done-signals rather than a second opinion.

Since #1321 the default view is the sentences of the System screen and "All
settings" lists the rest. The size ceilings (groups, value slots in the
sentences) are pinned where the screen is built, by
``dashboard/card/test/next-settings.test.js``; this file keeps what does not
need the screen: the view preference, the words, the name.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dashboard" / "card" / "src"


VIEW_MODE = SRC / "util" / "view-mode.js"


def test_the_view_preference_is_per_browser_not_per_install():
    """A view preference is not a setting. Storing it in the config entry would
    make one person's choice everyone's. The store moved to a helper every card
    shares (one switch for every tab); the key stayed, so a choice made before
    the move is kept."""
    helper = VIEW_MODE.read_text(encoding="utf-8")
    assert 'VIEW_MODE_KEY = "sem_config_advanced_v1"' in helper, (
        "the key changed — every existing choice would be lost")
    assert "localStorage.setItem(VIEW_MODE_KEY" in helper
    assert helper.count("catch (_e)") == 2, (
        "storage access is not guarded — a private window or blocked site data "
        "would throw and take the card with it")


def test_the_switch_reads_all_settings():
    tr = json.loads((ROOT / "dashboard" / "translations.json").read_text(encoding="utf-8"))
    assert tr["en"]["next_all_settings"] == "All settings"
    for lang, table in tr.items():
        for key in ("next_all_settings", "config_more_in_all"):
            assert table.get(key), f"{lang}.{key} missing"
        if lang != "en":
            assert table["next_all_settings"] != "All settings", lang


def test_nothing_is_called_beginner():
    """Explicit rule: the default view has no name. A label that tells
    someone they are a beginner is a reason to leave."""
    offenders = []
    for path in sorted(SRC.rglob("*.js")):
        # Strip comments before looking: the word appears there legitimately,
        # explaining exactly why the view has no name.
        stripped = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
        stripped = re.sub(r"//[^\n]*", "", stripped)
        offenders += [f"{path.name}: {ln.strip()}" for ln in stripped.split("\n")
                      if re.search(r"\bbeginner\b", ln, re.I)]
    assert not offenders, f"user-facing 'beginner' wording: {offenders}"


def test_the_translations_never_say_beginner():
    """The word must not reach a user in any of the sixteen languages."""
    tr = json.loads((ROOT / "dashboard" / "translations.json").read_text(encoding="utf-8"))
    bad = []
    for lang, table in tr.items():
        for key, value in table.items():
            if "beginner" in str(key).lower() or "beginner" in str(value).lower():
                bad.append(f"{lang}.{key}")
    assert not bad, f"'beginner' reaches the user: {bad[:5]}"
