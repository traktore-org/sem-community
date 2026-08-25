#!/usr/bin/env bash
# Build the HACS release asset.
#
# WHY THIS EXISTS (#834): HACS's "Downloads" column is the sum of a GitHub
# release's ASSET download counts. A repo that ships from its source tree has
# no assets, so HACS renders "-" — which is what SEM did for its whole life,
# alongside every other source-only integration. Attaching a zip is the only
# way to be counted.
#
# LAYOUT: HACS extracts this zip directly into
# ``custom_components/<domain>/``, so the integration's files must sit FLAT at
# the zip root — no wrapper directory. (Verified against BJReplay/ha-solcast-
# solar's published asset, which is the reference implementation.) That is
# already the shape of this repo, which sets ``content_in_root: true``.
#
# CONTENTS: exactly what ``rsync_exclude_args`` in ~/bin/lib/ha-api.sh ships
# to a real Home Assistant instance — the configuration ``validate-sem.sh``
# proves on every deploy. Shipping anything else would put untested surface in
# front of users, so this list is a MIRROR, not an independent judgement. If
# the deploy list changes, change this one in the same commit.
#
# SOURCE: git's tracked files, never the working tree, so local scratch
# (logs/, graphify-out/, __pycache__/) cannot leak into a published artifact.
set -euo pipefail

OUT="${1:-solar_energy_management.zip}"
cd "$(git rev-parse --show-toplevel)"

# Mirrors rsync_exclude_args (~/bin/lib/ha-api.sh). Directory prefixes and
# exact root-level filenames.
EXCLUDE_DIRS=(.github tests docs logo scripts .claude tmp tools)
EXCLUDE_FILES=(CLAUDE.md .mcp.json .gitignore hacs.json LICENSE README.md
               KNOWN_LIMITATIONS.md CHANGELOG.md TROUBLESHOOTING.md
               USER_GUIDE.md)

staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

kept=0
while IFS= read -r f; do
    skip=""
    for d in "${EXCLUDE_DIRS[@]}"; do
        [[ "$f" == "$d/"* ]] && { skip=1; break; }
    done
    [[ -n "$skip" ]] && continue
    for x in "${EXCLUDE_FILES[@]}"; do
        [[ "$f" == "$x" ]] && { skip=1; break; }
    done
    [[ -n "$skip" ]] && continue
    mkdir -p "$staging/$(dirname "$f")"
    cp "$f" "$staging/$f"
    kept=$((kept + 1))
done < <(git ls-files)

# manifest.json is how HACS reads the installed version — without it the
# install is not an integration at all. Fail loudly rather than publish it.
[[ -f "$staging/manifest.json" ]] || { echo "FATAL: manifest.json missing from zip" >&2; exit 1; }
[[ -f "$staging/__init__.py" ]]   || { echo "FATAL: __init__.py missing from zip" >&2; exit 1; }
[[ -f "$staging/dashboard/card/dist/sem-cards.js" ]] || {
    echo "FATAL: card bundle missing — dist/sem-cards.js is the only thing HA loads for the cards" >&2; exit 1; }

rm -f "$OUT"
OUT_ABS="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
# python's zipfile rather than the zip(1) binary: it is present wherever this
# repo's tooling already runs, and the deterministic date makes the artifact
# reproducible for a given tree.
python3 - "$staging" "$OUT_ABS" <<'PYZIP'
import os, sys, zipfile
root, out = sys.argv[1], sys.argv[2]
names = []
for dirpath, _dirnames, filenames in os.walk(root):
    for fn in filenames:
        full = os.path.join(dirpath, fn)
        names.append((os.path.relpath(full, root), full))
names.sort()
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for arc, full in names:
        zi = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = (os.stat(full).st_mode & 0xFFFF) << 16
        with open(full, "rb") as fh:
            z.writestr(zi, fh.read())
print(f"  {len(names)} files")
PYZIP

echo "built $OUT — $kept files, $(du -h "$OUT_ABS" | cut -f1)"
