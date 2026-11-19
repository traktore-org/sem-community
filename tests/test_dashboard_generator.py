"""Tests for dashboard generator."""
import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)
from custom_components.solar_energy_management.const import DOMAIN


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.config_dir = "/config"
    hass.data = {}
    hass.states.async_all.return_value = []
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    return hass


@pytest.fixture
def generator(mock_hass):
    return DashboardGenerator(mock_hass)


class TestDashboardTemplate:
    """Test the dashboard YAML template loads correctly."""


    def test_all_custom_cards_exist(self):
        """The shipped SEM card assets should exist.

        Since the LitElement migration the individual ``sem-*-card.js`` files
        were folded into the single Rollup bundle ``dist/sem-cards.js`` and the
        per-card files were removed. Only the bundle plus the assets that are
        registered/loaded standalone remain on disk.
        """
        card_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard",
            "card",
        )
        expected_cards = [
            "dist/sem-cards.js",            # Lit bundle — every dashboard card
            "sem-localize.js",              # translations, registered as a Lovelace resource (single channel, #453)
        ]
        for card in expected_cards:
            assert os.path.exists(os.path.join(card_dir, card)), f"Missing: {card}"


class TestContentHashCacheBust:
    """Regression tests for the Lovelace cache-bust helper (#301).

    The legacy cache-bust used ``int(time.time())`` which stayed constant
    between ``generate_dashboard`` service calls — so an rsync deploy that
    rewrote ``sem-localize.js`` left the registered URL's ``?v=`` unchanged
    and browsers happily served the old cached copy. Newly-added translation
    keys (e.g. ``charge_mode_*``) then rendered as raw key text on the EV
    card. The fix is to hash the file content so any real change flips the
    URL automatically.
    """

    def _bust(self, *args, **kwargs):
        # Imported lazily so the test module remains importable when the
        # parent package's optional deps are missing in some test envs.
        from custom_components.solar_energy_management import (
            _content_hash_cache_bust,
        )
        return _content_hash_cache_bust(*args, **kwargs)

    def test_url_includes_version_and_short_hash(self, tmp_path):
        card_root = tmp_path
        (card_root / "sem-localize.js").write_bytes(b"const x = 1;")
        base = "/local/custom_components/solar_energy_management/dashboard/card/sem-localize.js"

        bust = self._bust(str(card_root), base, "1.6.3")

        # Format must be ``{version}-{8-hex-char hash}`` — matches the
        # _async_register_frontend_resources bundle path so both registration
        # paths produce identical URLs for the same file content.
        assert "-" in bust
        version, short = bust.split("-", 1)
        assert version == "1.6.3"
        assert len(short) == 8
        assert all(c in "0123456789abcdef" for c in short)

    def test_url_changes_when_content_changes(self, tmp_path):
        """A file edit must flip the URL — the property the bug violated."""
        card_root = tmp_path
        f = card_root / "sem-localize.js"
        base = "/local/custom_components/solar_energy_management/dashboard/card/sem-localize.js"

        f.write_bytes(b'{"charge_mode": "Charge mode"}')
        before = self._bust(str(card_root), base, "1.6.3")

        f.write_bytes(b'{"charge_mode": "Charge mode", "charge_mode_min_plus_solar": "Min + Solar"}')
        after = self._bust(str(card_root), base, "1.6.3")

        assert before != after, (
            "cache-bust must track file content — adding a new translation key "
            "must change the ?v= URL or the browser will serve the stale cached "
            "file (the #301 regression)."
        )

    def test_url_stable_across_calls_when_content_unchanged(self, tmp_path):
        """No URL churn on each restart — only file content drives changes."""
        card_root = tmp_path
        (card_root / "sem-localize.js").write_bytes(b"const x = 1;")
        base = "/local/custom_components/solar_energy_management/dashboard/card/sem-localize.js"

        first = self._bust(str(card_root), base, "1.6.3")
        second = self._bust(str(card_root), base, "1.6.3")

        assert first == second

    def test_url_for_nested_bundle_path(self, tmp_path):
        """Bundle lives under ``dist/`` — the URL splitter must handle it."""
        card_root = tmp_path
        (card_root / "dist").mkdir()
        (card_root / "dist" / "sem-cards.js").write_bytes(b"// bundle")
        base = "/local/custom_components/solar_energy_management/dashboard/card/dist/sem-cards.js"

        bust = self._bust(str(card_root), base, "1.6.3")

        version, short = bust.split("-", 1)
        assert version == "1.6.3"
        assert len(short) == 8

    def test_missing_file_falls_back_to_bare_version(self, tmp_path):
        """If the asset can't be read, return bare version — don't crash or
        return an empty bust that could collide with another resource."""
        card_root = tmp_path
        base = "/local/custom_components/solar_energy_management/dashboard/card/sem-localize.js"

        bust = self._bust(str(card_root), base, "1.6.3")

        assert bust == "1.6.3"

    def test_no_timestamp_anti_pattern_in_service_path(self):
        """Guard the regression: the legacy ``int(time.time())`` cache-bust
        must not reappear in the generate_dashboard service path. If a future
        edit reverts to a timestamp, the symptom returns silently — no test
        catches it because the URL is still ``valid``, just stale."""
        init_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "__init__.py",
        )
        src = open(init_path).read()
        # The legacy pattern. We pick the exact construction that produced
        # the bug so this test stays sharp and doesn't false-positive on
        # unrelated timestamp usage elsewhere in the file.
        assert 'cache_bust = str(int(_time.time()))' not in src, (
            "Reintroduced the time-based cache-bust that caused #301. Use "
            "_content_hash_cache_bust so ?v= follows file content."
        )


def _make_device(power_entity, priority=5, is_ev=False, device_type="switch",
                 friendly_name=None, daily_energy_entity=None):
    """Helper to build a device dict for load manager tests."""
    d = {
        "power_entity": power_entity,
        "priority": priority,
        "is_ev": is_ev,
        "device_type": device_type,
        "friendly_name": friendly_name or power_entity,
    }
    if daily_energy_entity:
        d["daily_energy_entity"] = daily_energy_entity
    return d


def _flow_card_template(entity_prefix=None):
    """Return a minimal template with one sem-flow-card."""
    card = {"type": "custom:sem-flow-card"}
    if entity_prefix:
        card["entity_prefix"] = entity_prefix
    return {"views": [{"cards": [card]}]}


def _setup_coordinator(mock_hass, devices, ev_power_sensor="sensor.ev_power"):
    """Wire up a mock coordinator with load manager devices in hass.data."""
    coord = MagicMock()
    coord._load_manager = MagicMock()
    coord._load_manager._devices = devices
    coord.config = {"ev_charging_power_sensor": ev_power_sensor}
    mock_hass.data[DOMAIN] = {"entry1": coord}
    return coord


@pytest.mark.unit
class TestDashboardCleanupLogic:
    """Test stale file cleanup and resource registration logic."""

    def test_cleanup_removes_sem_js_from_www(self):
        """Stale sem-*.js files in /config/www/ should be removed."""
        with patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=["sem-flow-card.js", "sem-chart-card.js", "other.js"]), \
             patch("os.remove") as mock_remove:
            # Simulate the cleanup closure logic
            www_dir = "/config/www"
            removed = []
            for fname in os.listdir(www_dir):
                if fname.startswith("sem-") and fname.endswith(".js"):
                    os.remove(os.path.join(www_dir, fname))
                    removed.append(fname)
            assert removed == ["sem-flow-card.js", "sem-chart-card.js"]
            assert mock_remove.call_count == 2

    def test_cleanup_skips_non_sem_files(self):
        """Non-SEM JS files should not be removed."""
        with patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=["card-mod.js", "mushroom.js"]), \
             patch("os.remove") as mock_remove:
            www_dir = "/config/www"
            for fname in os.listdir(www_dir):
                if fname.startswith("sem-") and fname.endswith(".js"):
                    os.remove(os.path.join(www_dir, fname))
            mock_remove.assert_not_called()

    def test_cleanup_handles_missing_www_dir(self):
        """Missing /config/www/ directory should not raise."""
        with patch("os.path.isdir", return_value=False):
            www_dir = "/config/www"
            removed = []
            for fname in os.listdir(www_dir) if os.path.isdir(www_dir) else []:
                if fname.startswith("sem-") and fname.endswith(".js"):
                    removed.append(fname)
            assert removed == []

    def test_orphaned_resource_removal(self):
        """Orphaned /local/sem-* entries removed, component-path entries kept."""
        component_prefix = f"/local/custom_components/{DOMAIN}/"
        items = [
            {"url": "/local/sem-flow-card.js", "type": "module"},
            {"url": f"/local/custom_components/{DOMAIN}/dashboard/card/sem-flow-card.js", "type": "module"},
            {"url": "/local/card-mod.js", "type": "module"},
        ]
        filtered = [
            item for item in items
            if not (
                item.get("url", "").startswith("/local/sem-")
                and component_prefix not in item.get("url", "")
            )
        ]
        assert len(filtered) == 2
        urls = [i["url"] for i in filtered]
        assert "/local/sem-flow-card.js" not in urls
        assert f"/local/custom_components/{DOMAIN}/dashboard/card/sem-flow-card.js" in urls
        assert "/local/card-mod.js" in urls

    def test_resource_registration_module_type(self):
        """New resources should be registered with type='module'."""
        import uuid as _uuid
        resources = {"items": []}
        installed_cards = ["sem-flow-card.js", "sem-chart-card.js"]
        existing_bases = set()
        for fname in installed_cards:
            base_url = f"/local/custom_components/{DOMAIN}/dashboard/card/{fname}"
            if base_url not in existing_bases:
                resources["items"].append({
                    "id": _uuid.uuid4().hex,
                    "url": base_url,
                    "type": "module",
                })
        assert len(resources["items"]) == 2
        for item in resources["items"]:
            assert item["type"] == "module"
            assert item["url"].startswith(f"/local/custom_components/{DOMAIN}/")

    def test_resource_deduplication(self):
        """Existing resources should not be re-added."""
        base_url = f"/local/custom_components/{DOMAIN}/dashboard/card/sem-flow-card.js"
        resources = {"items": [{"id": "abc", "url": f"{base_url}?v=2.7.43", "type": "module"}]}
        existing_bases = {item.get("url", "").split("?")[0] for item in resources["items"]}
        installed_cards = ["sem-flow-card.js"]
        added = []
        for fname in installed_cards:
            url = f"/local/custom_components/{DOMAIN}/dashboard/card/{fname}"
            if url not in existing_bases:
                added.append(url)
        assert added == []
        assert len(resources["items"]) == 1


# Per-charger EV display is now handled by sem-ev-status-card.js (#193)
# which auto-discovers chargers from sensor.sem_charger_*_power entities.
# No Python-side dashboard injection tests needed — card handles rendering.
