#!/usr/bin/env python3
"""Regenerate sem-localize.js from translations.json.

Usage:
    python3 scripts/regenerate_localize.py [--check]

    --check   Verify sem-localize.js is in sync without overwriting (for CI).
              Exit code 0 = in sync, 1 = out of sync.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS_JSON = REPO_ROOT / "dashboard" / "translations.json"
LOCALIZE_JS = REPO_ROOT / "dashboard" / "card" / "sem-localize.js"


def generate_js(translations: dict) -> str:
    """Generate the sem-localize.js source from the translations dict.

    v1.7.2-beta.4 (2026-06-08): the body is wrapped in a top-level
    IIFE with a ``window.semLocalize`` guard so the file is safe to
    load via BOTH ``add_extra_js_url`` AND as a Lovelace resource.
    Without the guard, a second load would re-execute
    ``const _semTranslations = {...}`` and throw a SyntaxError
    (and the existing block-scoped semLocalize would silently shadow).

    Why dual-channel: ``add_extra_js_url`` is the desktop-friendly
    channel (loaded before Lovelace modules so cards see the global
    immediately). Mobile Companion app does NOT reliably pick up
    add_extra_js_url scripts (RienduPre + others, 2026-06-08), so we
    ALSO register as a Lovelace resource. With the guard, the second
    load is a clean no-op.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        "// Auto-generated from translations.json — do not edit manually",
        f"// Generated: {timestamp}",
        "// v1.7.2-beta.4: IIFE-wrapped with window.semLocalize guard so",
        "// dual-channel loading (add_extra_js_url + Lovelace resource) is safe.",
        "(function() {",
        "  if (typeof window === 'undefined') return;",
        "  // Guard: if a prior load already defined semLocalize, no-op.",
        "  // Both load channels point at the same hash-suffixed URL, so",
        "  // there's never a stale-vs-fresh race — they're identical.",
        "  if (window.semLocalize) return;",
        "  const _semTranslations = {",
    ]

    langs = list(translations.keys())
    for lang_idx, lang in enumerate(langs):
        lines.append(f'    "{lang}": {{')
        keys = list(translations[lang].items())
        for i, (key, value) in enumerate(keys):
            # Escape backslashes, then quotes, then newlines
            escaped = (
                value.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n")
            )
            comma = "," if i < len(keys) - 1 else ""
            lines.append(f'      "{key}": "{escaped}"{comma}')
        comma = "," if lang_idx < len(langs) - 1 else ""
        lines.append(f"    }}{comma}")

    lines.append("  };")
    lines.append("")
    lines.append("  function semLocalize(key, lang) {")
    lines.append('    lang = lang || "en";')
    lines.append(
        '    const t = _semTranslations[lang] || _semTranslations["en"] || {};'
    )
    lines.append('    const fallback = _semTranslations["en"] || {};')
    lines.append("    return t[key] || fallback[key] || key;")
    lines.append("  }")
    lines.append("")
    lines.append("  window.semLocalize = semLocalize;")
    lines.append(
        '  document.dispatchEvent(new CustomEvent("sem-localize-ready"));'
    )
    lines.append("})();")
    lines.append("")

    return "\n".join(lines)


def normalize_for_compare(content: str) -> str:
    """Strip the timestamp line for comparison (it changes every run)."""
    lines = content.splitlines()
    return "\n".join(line for line in lines if not line.startswith("// Generated:"))


def main():
    check_mode = "--check" in sys.argv

    if not TRANSLATIONS_JSON.exists():
        print(f"ERROR: {TRANSLATIONS_JSON} not found", file=sys.stderr)
        sys.exit(1)

    with open(TRANSLATIONS_JSON, "r", encoding="utf-8") as f:
        translations = json.load(f)

    # Validate: all languages must have the same keys as EN
    en_keys = set(translations.get("en", {}).keys())
    errors = []
    for lang, entries in translations.items():
        lang_keys = set(entries.keys())
        missing = en_keys - lang_keys
        extra = lang_keys - en_keys
        if missing:
            errors.append(f"  {lang}: missing {len(missing)} keys: {sorted(missing)[:5]}...")
        if extra:
            errors.append(f"  {lang}: {len(extra)} extra keys: {sorted(extra)[:5]}...")

    if errors:
        print("WARNING: Key mismatches found:")
        for e in errors:
            print(e)

    generated = generate_js(translations)

    if check_mode:
        if not LOCALIZE_JS.exists():
            print(f"FAIL: {LOCALIZE_JS} does not exist", file=sys.stderr)
            sys.exit(1)
        existing = LOCALIZE_JS.read_text(encoding="utf-8")
        if normalize_for_compare(existing) != normalize_for_compare(generated):
            print(
                "FAIL: sem-localize.js is out of sync with translations.json",
                file=sys.stderr,
            )
            print(
                "Run: python3 scripts/regenerate_localize.py", file=sys.stderr
            )
            sys.exit(1)
        else:
            print("OK: sem-localize.js is in sync with translations.json")
            sys.exit(0)

    with open(LOCALIZE_JS, "w", encoding="utf-8") as f:
        f.write(generated)

    lang_count = len(translations)
    key_count = len(en_keys)
    print(f"Generated {LOCALIZE_JS.name}: {key_count} keys × {lang_count} languages")


if __name__ == "__main__":
    main()
