"""Real-hass + filesystem coverage for the bundled-card cache-bust path.

When SEM ships a new bundle, the browser MUST pick it up automatically.
The mechanism: the Lovelace resource URL includes a content-hash
query suffix (`?v={version}-{sha1(content)[:8]}`). The hash changes
when the bundle changes, the URL changes, the browser fetches the new
bundle, the card renders the new code. Pre-fix (#240, v1.5.11) the
resource URL was bare and the service-worker would happily serve the
old bundle for hours after an upgrade.

What these tests pin
--------------------
* The content-hash computation matches `sha1(bundle_bytes).hexdigest()[:8]`
  — the algorithm `_async_register_frontend_resources` uses.
* The bundle file actually exists where the registrar looks
  (`dashboard/card/dist/sem-cards.js`).
* The manifest version is what gets prepended to the hash.

These tests are filesystem-level (no real_hass needed). They protect
the cache-bust invariant: if anyone subtly changes the hash algorithm,
truncates differently, or moves the bundle, this test catches it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _project_root() -> Path:
    """Walk up to the manifest.json — works from CI / dev / package layout."""
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "manifest.json").exists():
            return parent
    raise RuntimeError("project root not found")


# ---------------------------------------------------------------------------
# Bundle presence + readable
# ---------------------------------------------------------------------------


def test_bundle_file_exists_at_expected_path() -> None:
    """The Lit bundle SEM registers as a Lovelace resource MUST live at
    ``dashboard/card/dist/sem-cards.js``. If anyone moves the build
    output, the resource registrar in ``__init__.py`` falls back
    silently to the unhashed bare path — users get stale-bundle
    behaviour after every upgrade."""
    bundle = _project_root() / "dashboard" / "card" / "dist" / "sem-cards.js"
    assert bundle.exists(), (
        f"bundle missing at {bundle}. The Rollup output path or the "
        f"registrar in __init__.py:_async_register_frontend_resources "
        f"changed without the other being updated."
    )
    assert bundle.stat().st_size > 10_000, (
        f"bundle suspiciously small ({bundle.stat().st_size} bytes). "
        f"Likely a build failure that committed an empty / stub file."
    )


def test_content_hash_algorithm_matches_registrar() -> None:
    """The cache-bust suffix is ``sha1(content).hexdigest()[:8]``. If
    anyone switches to a different hash (md5, sha256), truncates
    differently, or hashes the file path instead of the content, the
    URL would still appear valid but never change on bundle update —
    the exact failure mode #240 fixed.
    """
    bundle = _project_root() / "dashboard" / "card" / "dist" / "sem-cards.js"
    content = bundle.read_bytes()
    expected_hash = hashlib.sha1(content).hexdigest()[:8]

    # Read the registrar source and grep for the algorithm. This is a
    # source-level lint — the actual call only happens inside a real
    # HA setup which we can't easily drive here.
    init_src = (_project_root() / "__init__.py").read_text()
    assert "sha1" in init_src, (
        "registrar source no longer references sha1 — cache-bust "
        "algorithm likely changed"
    )
    assert ".hexdigest()[:8]" in init_src, (
        "registrar source no longer slices [:8] off the hexdigest — "
        "URL hash length likely changed (invalidates cached URLs but "
        "won't catch future drift)"
    )

    # Anchor — exact hash for diagnosis if a future test fails.
    assert len(expected_hash) == 8


def test_manifest_version_present_for_url_prefix() -> None:
    """The resource URL prefix is ``?v={manifest_version}-{hash}``. The
    manifest version is fetched via ``DOMAIN_MANIFEST.version`` at
    registration time. If the manifest is malformed (missing
    ``version`` key, invalid JSON) the registrar would either crash or
    fall back to a hardcoded sentinel — neither is what we want."""
    manifest = _project_root() / "manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert "version" in data, "manifest.json missing 'version' key"
    version = data["version"]
    assert isinstance(version, str), "manifest version is not a string"
    # Sanity — every version we've shipped matches one of these shapes.
    assert (
        version.count(".") == 2
        or "-beta" in version
        or "-rc" in version
    ), f"manifest version {version!r} doesn't match expected v?.?.? or pre-release shape"
