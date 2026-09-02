"""#830 — the default view is shrink-only, and it has no name.

Guido: *"if a user is starting with SEM he is overwhelmed with so many options
and stops using it — it is just too much."* And on naming: *"we do not name it
beginner. It's just nameless and advanced view."* Nobody is labelled a
beginner; there is the configuration, and an **Advanced** switch for whoever
wants the rest.

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
"""

import re
from pathlib import Path

CARD = (Path(__file__).resolve().parent.parent / "dashboard" / "card" / "src"
        / "cards" / "sem-config-card.js")


def _set(name):
    src = CARD.read_text(encoding="utf-8")
    m = re.search(r"const " + name + r" = new Set\(\[(.*?)\]\)", src, re.DOTALL)
    assert m, f"{name} not found"
    return set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))


#: The ceiling. Raising either number is a decision, not a detail.
MAX_SECTIONS = 4
#: 5 → 7 (#897): the load-management arm switch and its ceiling. The shedder
#: switches off house circuits, and hiding its on/off behind Advanced is how
#: a first install shed a Span panel circuit by circuit (forum #30). A
#: control that can turn the lights off is not one to bury.
MAX_CONTROLS = 7


def test_the_default_view_shows_at_most_four_sections():
    got = _set("ESSENTIAL_SECTIONS")
    assert len(got) <= MAX_SECTIONS, (
        f"the default view grew to {len(got)} sections: {sorted(got)}. "
        f"It exists to be small; if this one genuinely belongs, raise "
        f"MAX_SECTIONS deliberately and say why.")


def test_the_default_view_shows_at_most_five_loose_controls():
    got = _set("ESSENTIAL_CONTROLS")
    assert len(got) <= MAX_CONTROLS, (
        f"the default view grew to {len(got)} controls: {sorted(got)}. "
        f"Every one of ninety arrived for a good reason — that is the whole "
        f"problem this list is against.")


def test_it_covers_what_sem_cannot_work_without():
    """The inverse pin: shrink-only must not shrink into uselessness. Without
    a price SEM reports zero savings, and without the EV section most installs
    have nothing to control."""
    secs = _set("ESSENTIAL_SECTIONS")
    assert "tariff" in secs, "SEM cannot cost anything without a tariff"
    assert "ev_chargers" in secs
    assert "overview" in secs, "the setup guide is how a user finds the rest"
    ctrls = _set("ESSENTIAL_CONTROLS")
    assert "tariff_mode" in ctrls, "the one tariff decision must be reachable"


def test_advanced_hides_nothing():
    """The escape. Whatever the tiering decides, advanced shows everything —
    so the split can never lose a user a setting."""
    src = CARD.read_text(encoding="utf-8")
    assert "if (this._advanced) return true;" in src, (
        "the control filter no longer short-circuits for advanced — something "
        "can now be unreachable")
    assert "this._advanced || ESSENTIAL_SECTIONS.has(s.id)" in src, (
        "the section filter no longer short-circuits for advanced")


def test_a_configured_subsystem_stays_visible():
    src = CARD.read_text(encoding="utf-8")
    assert "this._sectionConfigured(s.id)" in src, (
        "a section the user already set up can now vanish from the default "
        "view — that is losing their work, not simplifying")


def test_the_configured_check_reuses_the_setup_overview():
    """One answer to 'is this configured'. Two would drift, and the overview's
    is the one already shown to the user."""
    src = CARD.read_text(encoding="utf-8")
    m = re.search(r"_sectionConfigured\(id\) \{(.*?)\n    \}", src, re.DOTALL)
    assert m and "this._setupItems()" in m.group(1), (
        "_sectionConfigured no longer derives from the Setup overview's own "
        "done-signals")


def test_the_view_preference_is_per_browser_not_per_install():
    """A view preference is not a setting. Storing it in the config entry would
    make one person's choice everyone's."""
    src = CARD.read_text(encoding="utf-8")
    assert "localStorage.setItem(ADV_KEY" in src
    assert "catch (e)" in src, (
        "storage access is not guarded — a private window or blocked site data "
        "would throw and take the card with it")


def test_nothing_is_called_beginner():
    """Guido, explicitly: the default view has no name. A label that tells
    someone they are a beginner is a reason to leave."""
    src = CARD.read_text(encoding="utf-8")
    # Strip comments before looking. A line-prefix check cannot see the middle
    # of a block comment, and the word appears there legitimately — explaining
    # exactly why the view has no name.
    stripped = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    stripped = re.sub(r"//[^\n]*", "", stripped)
    offenders = [ln.strip() for ln in stripped.split("\n")
                 if re.search(r"\bbeginner\b", ln, re.I)]
    assert not offenders, f"user-facing 'beginner' wording: {offenders}"


def test_the_translations_never_say_beginner():
    """The word must not reach a user in any of the sixteen languages."""
    import json
    tr = json.loads((Path(__file__).resolve().parent.parent / "dashboard"
                     / "translations.json").read_text(encoding="utf-8"))
    bad = []
    for lang, table in tr.items():
        for key, value in table.items():
            if "beginner" in str(key).lower() or "beginner" in str(value).lower():
                bad.append(f"{lang}.{key}")
    assert not bad, f"'beginner' reaches the user: {bad[:5]}"
