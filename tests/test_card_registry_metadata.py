"""Every card carries an anchor and a description.

A card registers itself with HA's card picker through
``window.customCards`` (``semDefineCard``'s third argument). HA reads
four fields off that entry:

* ``type``    — the **bare** element tag. HA prepends ``custom:`` itself
                when it builds the YAML, so a ``custom:`` in this field
                yields ``custom:custom:sem-…`` and the picker cannot
                instantiate the card.
* ``name``    — what the picker lists.
* ``description`` — the one line that tells a user what the card is for.
* ``documentationURL`` — rendered as a **help link in the card editor**.
                That link is the card's anchor: the only path from "I am
                looking at this card" to "here is what it does".

Before this guard, 31 registered cards split 15 correct / 14
``custom:``-prefixed / 2 with no ``type`` at all — and *none* carried a
``documentationURL``. ``sem-energy-plan-card``, the headline card of
2.0, was among the two that could not be added from the picker.

The anchor contract is deliberately mechanical so it cannot rot: a
card's heading in ``docs/DASHBOARD_GUIDE.md`` is *exactly its tag*, so
the anchor is derivable from the tag alone and this test can verify
both ends.

See #783. The two-file agreement test also guards #784.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CARD_SRC = REPO / "dashboard" / "card" / "src" / "cards"
CARD_ROOT = REPO / "dashboard" / "card"
GUIDE = REPO / "docs" / "DASHBOARD_GUIDE.md"

# Top-level files that are the base layer / generated locale data, not
# cards. sem-system-diagram-card.js IS a card and is deliberately scanned:
# it ships standalone (its own Lovelace resource) *as well as* inside the
# bundle, and semDefineCard is first-wins, so both copies must agree.
NOT_A_CARD = {"sem-shared.js", "sem-reactive-base.js"}

DOC_BASE = (
    "https://github.com/traktore-org/sem-community/blob/main/"
    "docs/DASHBOARD_GUIDE.md#"
)

# Back-compat aliases: a second tag serving an already-registered card.
# These deliberately omit the picker entry so the card is not listed
# twice. Every entry here is a RENAME, never a new card.
ALIAS_TAGS = {
    # dashboards generated before the #638 rename still say
    # custom:sem-overnight-plan-card
    "sem-overnight-plan-card",
}


def _split_top_level_args(text: str) -> list[str]:
    """Split a JS argument list on commas that are not nested."""
    args, depth, buf, i = [], 0, [], 0
    quote = None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                buf.append(text[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        args.append("".join(buf))
    return [a.strip() for a in args]


def _call_args(src: str, start: int) -> str:
    """Return the raw text inside semDefineCard( ... )."""
    i = src.index("(", start) + 1
    depth, out, quote = 1, [], None
    while i < len(src):
        ch = src[i]
        if quote:
            if ch == "\\":
                out.append(src[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return "".join(out)
        out.append(ch)
        i += 1
    raise AssertionError("unbalanced semDefineCard( call")


def _field(obj: str, key: str) -> str | None:
    m = re.search(
        rf"\b{key}\s*:\s*(['\"])(.*?)(?<!\\)\1", obj, re.S
    )
    return m.group(2) if m else None


def _card_files() -> list[Path]:
    """Every file that may register a card with the picker."""
    roots = sorted(CARD_SRC.glob("*.js"))
    roots += [
        p
        for p in sorted(CARD_ROOT.glob("*.js"))
        if p.name not in NOT_A_CARD and not p.name.startswith("sem-localize")
    ]
    return roots


def _registrations() -> list[tuple[Path, str, str | None]]:
    """(path, tag, cardInfo-object-text or None) per semDefineCard call."""
    out = []
    for path in _card_files():
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\bsemDefineCard\s*\(", src):
            args = _split_top_level_args(_call_args(src, m.start()))
            tag = re.sub(r"^['\"]|['\"]$", "", args[0])
            info = None
            if len(args) >= 3:
                info = args[2]
                # third arg may be an identifier bound earlier in the file
                if re.fullmatch(r"[A-Za-z_$][\w$]*", info):
                    b = re.search(
                        rf"\b(?:const|let|var)\s+{re.escape(info)}\s*=\s*(\{{.*?\n\}});",
                        src,
                        re.S,
                    )
                    info = b.group(1) if b else None
            out.append((path, tag, info))
    return out


def _guide_anchors() -> set[str]:
    """Headings in DASHBOARD_GUIDE.md, as GitHub anchor slugs."""
    anchors = set()
    for line in GUIDE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#{2,6}\s+(.*?)\s*$", line)
        if not m:
            continue
        slug = m.group(1).strip().lower()
        slug = slug.replace("`", "")
        slug = re.sub(r"[^\w\s-]", "", slug)
        anchors.add(re.sub(r"\s+", "-", slug))
    return anchors


def test_every_card_declares_its_bare_tag_as_type():
    """HA prepends ``custom:`` — declaring it here doubles it."""
    offenders = []
    for path, tag, info in _registrations():
        if info is None:
            continue
        declared = _field(info, "type")
        if declared != tag:
            offenders.append(f"{path.name}: tag {tag!r} but type={declared!r}")
    assert not offenders, (
        "window.customCards `type` must be the BARE element tag — HA adds "
        "the `custom:` prefix itself, so a prefix here becomes "
        "`custom:custom:sem-…` and the picker cannot build the card:\n  "
        + "\n  ".join(offenders)
    )


def test_every_card_has_a_description():
    offenders = [
        f"{path.name} ({tag})"
        for path, tag, info in _registrations()
        if info is None or not (_field(info, "description") or "").strip()
    ]
    offenders = [o for o in offenders if o.split("(")[-1].rstrip(")") not in ALIAS_TAGS]
    assert not offenders, (
        "Every card needs a description — it is the only thing the HA "
        "card picker shows about it:\n  " + "\n  ".join(offenders)
    )


def test_every_card_has_an_anchor_into_the_dashboard_guide():
    """documentationURL is the help link in HA's card editor."""
    offenders = []
    for path, tag, info in _registrations():
        if tag in ALIAS_TAGS:
            continue
        url = _field(info or "", "documentationURL")
        if not url:
            offenders.append(f"{path.name} ({tag}): no documentationURL")
        elif url != f"{DOC_BASE}{tag}":
            offenders.append(f"{path.name} ({tag}): {url}")
    assert not offenders, (
        "Every card deserves an anchor. documentationURL must be "
        f"{DOC_BASE}<tag> so the card editor's help link lands on that "
        "card's own section:\n  " + "\n  ".join(offenders)
    )


def test_every_card_anchor_resolves_to_a_heading():
    """A dangling anchor is worse than none — it 404s the user."""
    anchors = _guide_anchors()
    missing = [
        tag
        for _, tag, _ in _registrations()
        if tag not in ALIAS_TAGS and tag not in anchors
    ]
    assert not missing, (
        "These cards point at a DASHBOARD_GUIDE.md heading that does not "
        "exist. Each card's heading must be exactly its tag:\n  "
        + "\n  ".join(sorted(set(missing)))
    )


def test_alias_tags_are_real_aliases_not_forgotten_cards():
    """The opt-out list may only hold tags that omit the picker entry."""
    seen: dict[str, list[str | None]] = {}
    for _, tag, info in _registrations():
        seen.setdefault(tag, []).append(info)
    for tag in ALIAS_TAGS:
        assert tag in seen, f"ALIAS_TAGS names {tag!r}, which registers nothing"
        assert all(i is None for i in seen[tag]), (
            f"{tag!r} carries a picker entry, so it is a real card, not an "
            "alias — remove it from ALIAS_TAGS and give it an anchor"
        )


def test_cards_registered_twice_carry_the_same_picker_entry():
    """semDefineCard is first-wins, so load order must not change the entry.

    ``sem-system-diagram-card`` ships both inside ``dist/sem-cards.js`` and
    as its own standalone Lovelace resource. Whichever loads first defines
    the element AND pushes the only ``window.customCards`` entry — the
    second call returns at the ``customElements.get(tag)`` guard. If the two
    copies disagree, the user's help link exists or doesn't depending on
    resource order, which is not something we control.
    """
    by_tag: dict[str, list[tuple[Path, str | None]]] = {}
    for path, tag, info in _registrations():
        by_tag.setdefault(tag, []).append((path, info))

    offenders = []
    for tag, entries in by_tag.items():
        if len(entries) < 2:
            continue
        fields = {
            path: tuple(
                _field(info or "", k)
                for k in ("type", "name", "description", "documentationURL")
            )
            for path, info in entries
        }
        if len(set(fields.values())) > 1:
            detail = "\n    ".join(f"{p.name}: {v}" for p, v in fields.items())
            offenders.append(f"{tag}:\n    {detail}")
    assert not offenders, (
        "These tags register from more than one file with DIFFERENT picker "
        "entries. semDefineCard is first-wins, so the user gets whichever "
        "resource HA loads first — keep the copies identical:\n  "
        + "\n  ".join(offenders)
    )
