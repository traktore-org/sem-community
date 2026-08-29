#!/usr/bin/env python3
"""Regenerate the sem-localize files from translations.json.

Usage:
    python3 scripts/regenerate_localize.py [--check]

    --check   Verify the committed files are in sync without overwriting.

(#738) The single-file sem-localize.js was split per language — the real
generator is ``dashboard/card/build_localize.py`` and this script now
DELEGATES to it. It stays because it is the documented entry point (and
muscle memory): a second generator writing the same file is how the
1.2 MB monolith would silently come back.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD_DIR = os.path.join(REPO, "dashboard", "card")


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "build_localize", os.path.join(CARD_DIR, "build_localize.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    gen = _load_generator()
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            written = gen.generate(out_dir=tmp)
            stale = []
            for path in written:
                name = os.path.basename(path)
                committed = os.path.join(CARD_DIR, name)
                if not os.path.exists(committed):
                    stale.append(f"{name}: missing")
                    continue
                # Skip the two generated-stamp header lines on both sides.
                fresh = open(path, encoding="utf-8").read().split("\n", 2)[2]
                have = open(committed, encoding="utf-8").read().split("\n", 2)[2]
                if fresh != have:
                    stale.append(f"{name}: drifted")
            if stale:
                print("sem-localize out of sync with translations.json:")
                for s in stale:
                    print(f"  {s}")
                return 1
            print(f"sem-localize in sync ({len(written)} files)")
            return 0
    written = gen.generate()
    for p in written:
        print(f"wrote {os.path.basename(p)} ({os.path.getsize(p)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
