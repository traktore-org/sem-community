#!/usr/bin/env python3
"""Sanity-check that ``manifest.json`` has the bare minimum HA expects.

Runs as a pre-commit hook before the 15-minute CI Hassfest job. Catches
the one-character mistakes that would otherwise burn a CI cycle.
"""

import json
import sys
from pathlib import Path

REQUIRED_KEYS = ("domain", "version", "name", "documentation", "issue_tracker")


def main() -> int:
    manifest_path = Path(__file__).resolve().parent.parent / "manifest.json"
    try:
        with manifest_path.open() as fh:
            manifest = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"hassfest-lite: cannot read {manifest_path}: {exc}", file=sys.stderr)
        return 1

    missing = [k for k in REQUIRED_KEYS if k not in manifest]
    if missing:
        print(
            f"hassfest-lite: manifest.json missing required keys: {missing}",
            file=sys.stderr,
        )
        return 1

    print(f"hassfest-lite OK: {manifest['domain']} {manifest['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
