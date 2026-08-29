"""#738 — sem-localize.js split per language.

The single file had grown to 1.2 MB (16 languages × ~850 keys), parsed by
every browser to use exactly one. The split ships the loader with English
inline (fallback floor: worst case is English text, never raw keys) and
lazily injects one sibling language file.

The ``sem-localize-ready`` contract is load-bearing (#240 class): cards
wait for it and re-render on every dispatch — which is exactly what makes
the late language upgrade free.
"""
import json
import os


HERE = os.path.dirname(os.path.abspath(__file__))
CARD_DIR = os.path.join(HERE, "..", "dashboard", "card")
TRANSLATIONS = os.path.join(HERE, "..", "dashboard", "translations.json")


def _langs():
    with open(TRANSLATIONS, encoding="utf-8") as f:
        return sorted(json.load(f))


class TestGeneratedArtifacts:
    """The committed artifacts match the generator's contract."""

    def test_every_non_english_language_has_its_own_file(self):
        for lang in _langs():
            if lang == "en":
                continue
            path = os.path.join(CARD_DIR, f"sem-localize.{lang}.js")
            assert os.path.exists(path), f"missing sem-localize.{lang}.js"

    def test_the_loader_is_an_order_of_magnitude_smaller(self):
        """The whole point: ~75 KB with English inline, not 1.2 MB."""
        size = os.path.getsize(os.path.join(CARD_DIR, "sem-localize.js"))
        assert size < 250_000, f"loader is {size} bytes — the split regressed"

    def test_the_loader_keeps_the_ready_contract(self):
        src = open(os.path.join(CARD_DIR, "sem-localize.js"),
                   encoding="utf-8").read()
        assert "sem-localize-ready" in src
        assert "window.semLocalize" in src
        assert src.lstrip().startswith("//")

    def test_language_files_redispatch_ready(self):
        """The late-arriving table must trigger the re-render cards already
        do on this event — that is what makes lazy loading invisible."""
        src = open(os.path.join(CARD_DIR, "sem-localize.de.js"),
                   encoding="utf-8").read()
        assert "sem-localize-ready" in src

    def test_the_loader_contains_english_but_not_german(self):
        """English inline = the fallback floor. Any other language inline
        = the 1.2 MB problem growing back."""
        src = open(os.path.join(CARD_DIR, "sem-localize.js"),
                   encoding="utf-8").read()
        with open(TRANSLATIONS, encoding="utf-8") as f:
            data = json.load(f)
        probe_en = data["en"]["comfort_section"]
        probe_de = data["de"]["comfort_section"]
        assert probe_en in src
        if probe_de != probe_en:
            assert f'"{probe_de}"' not in src

    def test_siblings_inherit_the_loaders_cache_token(self):
        """A language change must bust the SIBLING caches too — the loader
        propagates its own ?v (hashed from translations.json) onto every
        injected script URL."""
        src = open(os.path.join(CARD_DIR, "sem-localize.js"),
                   encoding="utf-8").read()
        assert "query" in src and "document.currentScript" in src


class TestRegistrationHashesTheSource:
    """The ?v token must follow translations.json — hashing only the
    loader would keep serving a stale German file after a German-only
    change (the loader's bytes wouldn't move)."""

    def test_the_localize_token_reads_translations_json(self):
        src = open(os.path.join(HERE, "..", "__init__.py"),
                   encoding="utf-8").read()
        i = src.index('"localize": ')
        window = src[i - 1500:i + 200]
        assert "translations.json" in window, (
            "the localize cache token no longer hashes translations.json — "
            "a single-language change would serve stale siblings forever"
        )


class TestWwwMirrorCarriesTheSiblings:
    """(#617 class) the /config/www mirror must include the per-language
    files, or the legacy /local channel 404s them."""

    def test_the_copier_includes_language_files(self):
        src = open(os.path.join(HERE, "..", "__init__.py"),
                   encoding="utf-8").read()
        assert "sem-localize." in src.split("CANONICAL_TOP_LEVEL")[1][:900], (
            "the www-mirror copier does not carry sem-localize.<lang>.js"
        )


class TestGeneratorRoundTrip:
    """The generator regenerates what is committed (drift guard)."""

    def test_generator_output_matches_committed_files(self, tmp_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_localize", os.path.join(CARD_DIR, "build_localize.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        written = mod.generate(out_dir=str(tmp_path))
        assert len(written) == len(_langs())  # loader + n-1 languages
        for path in written:
            name = os.path.basename(path)
            committed = os.path.join(CARD_DIR, name)
            assert os.path.exists(committed), f"{name} not committed"
            gen = open(path, encoding="utf-8").read().split("\n", 2)[2]
            com = open(committed, encoding="utf-8").read().split("\n", 2)[2]
            assert gen == com, f"{name} drifted from the generator"
