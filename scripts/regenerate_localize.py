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

    The body is wrapped in a top-level IIFE so ``_semTranslations``
    stays scoped (doesn't leak as a window-level global). Only
    ``semLocalize`` is published. At the end of the IIFE, a
    ``sem-localize-ready`` CustomEvent fires on ``document`` so cards
    that were constructed before this script parsed can re-render
    (handled in ``dashboard/card/src/base/sem-lit-base.js``).

    Single delivery channel: this file is registered as a Lovelace
    resource only (see ``__init__.py:_async_register_frontend_resources``
    and #453). The IIFE no longer needs a ``window.semLocalize`` guard
    — the file loads exactly once per page.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        "// Auto-generated from translations.json — do not edit manually",
        f"// Generated: {timestamp}",
        "// IIFE-scoped translations; publishes ``window.semLocalize`` and",
        "// dispatches ``sem-localize-ready`` on document for late-loading cards.",
        "(function() {",
        "  if (typeof window === 'undefined') return;",
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
