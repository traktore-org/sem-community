#!/usr/bin/env python3
"""Refuse to publish a HACS zip that would break installs (#834).

HACS's download step **deletes the target directory and recreates it** from
what it downloads (https://hacs.xyz/docs/faq/download/). With ``zip_release``
that means the install becomes *exactly* this archive: anything missing here
disappears from every user's install on their next update, and there is no
fallback to the repository tree. Completeness is therefore a correctness
property of the artifact, not a packaging nicety — so it is asserted before
the asset is ever attached, not after someone reports a broken install.

Checks, in the order they would hurt:

1. **Flat layout.** HACS extracts into ``custom_components/<domain>/``, so the
   integration's files must sit at the archive root. A wrapper directory
   yields an install containing one folder and no integration.
2. **Completeness.** Every git-tracked file that the builder does not
   deliberately exclude must be present. This is what catches "someone added
   a module and the zip predates it".
3. **No development surface.** ``tests/``, ``docs/``, ``.github/`` and the
   local-only files must NOT ship into a user's config directory.
4. **Loadable manifest.** ``manifest.json`` parses and carries the keys HACS
   and Home Assistant require.
5. **The pieces that fail silently.** The card bundle (the only thing HA
   loads for the dashboard cards) and the brand assets HACS documents.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile

REQUIRED_MANIFEST_KEYS = ("domain", "documentation", "issue_tracker",
                          "codeowners", "name", "version")
MUST_EXIST = (
    "manifest.json",
    "__init__.py",
    "dashboard/card/dist/sem-cards.js",   # the only card source HA loads
    "brand/icon.png",                     # HACS's documented brand mechanism
    "icon.png",                           # HA 2026.3+ inline brand assets
)
MUST_NOT_SHIP = ("tests/", "docs/", ".github/", "scripts/", "tools/", "CLAUDE.md",
                 ".mcp.json")


def main(path: str) -> int:
    errors: list[str] = []

    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        manifest_raw = z.read("manifest.json") if "manifest.json" in names else None

    # 1 — flat layout
    if manifest_raw is None:
        errors.append(
            "manifest.json is not at the archive root. HACS extracts this zip "
            "straight into custom_components/<domain>/, so a wrapper directory "
            "produces an install with no integration in it."
        )

    # 2 — completeness against git, using the builder's own exclusions
    tracked = subprocess.run(["git", "ls-files"], capture_output=True,
                             text=True, check=True).stdout.split()
    excl_dirs = (".github/", "tests/", "docs/", "logo/", "scripts/", "tools/",
                 ".claude/", "tmp/")
    excl_files = {"CLAUDE.md", ".mcp.json", ".gitignore", "hacs.json",
                  "LICENSE", "README.md", "KNOWN_LIMITATIONS.md",
                  "CHANGELOG.md", "TROUBLESHOOTING.md", "USER_GUIDE.md"}
    expected = {
        f for f in tracked
        if not f.startswith(excl_dirs) and f not in excl_files
    }
    if missing := sorted(expected - names):
        errors.append(
            f"{len(missing)} tracked file(s) missing from the zip — they would "
            f"vanish from every install on update: {missing[:10]}"
            + (" …" if len(missing) > 10 else "")
        )

    # 3 — no development surface in a user's config directory
    for prefix in MUST_NOT_SHIP:
        if leaked := sorted(n for n in names if n.startswith(prefix)):
            errors.append(f"{prefix} must not ship to users: {leaked[:5]}")

    # 4 — loadable manifest
    if manifest_raw is not None:
        try:
            manifest = json.loads(manifest_raw)
        except json.JSONDecodeError as exc:
            errors.append(f"manifest.json does not parse: {exc}")
        else:
            if absent := [k for k in REQUIRED_MANIFEST_KEYS if k not in manifest]:
                errors.append(f"manifest.json missing required key(s): {absent}")

    # 5 — the pieces whose absence fails silently rather than loudly
    for required in MUST_EXIST:
        if required not in names:
            errors.append(f"missing {required}")

    if errors:
        print(f"REFUSING to publish {path}:", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    print(f"{path} is installable — {len(names)} files, flat layout, "
          f"complete against git, no dev surface")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "solar_energy_management.zip"))
