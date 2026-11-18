"""Dashboard generator for Solar Energy Management integration."""
from __future__ import annotations

import json
import logging
import os
import re
import yaml
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# (#1321) The SEM dashboard: one dashboard, five screens by question.
NEXT_DASHBOARD_ICON = "mdi:view-dashboard-variant-outline"
NEXT_DASHBOARD_PATH = "sem-next"
NEXT_DASHBOARD_TITLE = "SEM-dashboard"


def _holds_next(dashboard) -> bool:
    """Does this live dashboard serve the SEM dashboard (its loaded views are ours)?"""
    data = getattr(dashboard, "_data", None)
    config = data.get("config") if isinstance(data, dict) else None
    paths = {str(v.get("path")) for v in (config or {}).get("views", []) if isinstance(v, dict)}
    return bool(paths) and paths <= _NEXT_VIEW_PATHS and bool(paths & {"now", "plan", "devices", "insights"})


_NEXT_VIEW_PATHS = frozenset({"now", "plan", "devices", "insights", "system"})


def sem_dashboard_path(hass: HomeAssistant) -> str | None:
    """URL path of the live SEM dashboard (#1321), or None while it is not live.

    Links never hard-code it: a migrated install may keep the old
    ``sem-dashboard`` path (the migration rewrote it with the SEM dashboard),
    a fresh one uses ``sem-next``. A kept, edited classic dashboard at
    ``sem-dashboard`` is not it: until the SEM dashboard is registered there is
    no path to link to.
    """
    try:
        ll_data = hass.data.get("lovelace")
        dashboards = getattr(ll_data, "dashboards", None)
        if dashboards is None and isinstance(ll_data, dict):
            dashboards = ll_data.get("dashboards")
        if isinstance(dashboards, dict):
            if NEXT_DASHBOARD_PATH in dashboards:
                return NEXT_DASHBOARD_PATH
            marked = {e.options.get("_next_dashboard_path") for e in hass.config_entries.async_entries("solar_energy_management")}
            for path, dash in dashboards.items():
                if path and (path in marked or _holds_next(dash)):
                    return path
    except Exception:  # noqa: BLE001
        pass
    return None


def sem_dashboard_url(hass: HomeAssistant, view: str = "now") -> str:
    """A link into the SEM dashboard, else the dashboard root."""
    path = sem_dashboard_path(hass)
    return f"/{path}/{view}" if path else "/"


class DashboardGenerator:
    """Generate Lovelace dashboard configuration for SEM."""

    def __init__(self, hass: HomeAssistant):
        """Initialize dashboard generator."""
        self.hass = hass
        self._config_dir = hass.config.config_dir
        dashboard_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard")
        self._template_path = os.path.join(dashboard_dir, "sem_next_template.yaml")

    def _load_dashboard_translations_sync(self) -> dict:
        """Load translations from dashboard/translations.json (single source of truth).

        Must be called via hass.async_add_executor_job() from async context.
        """
        import json as _json
        translations_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dashboard", "translations.json",
        )
        try:
            with open(translations_path, "r", encoding="utf-8") as f:
                return _json.load(f)
        except (OSError, ValueError) as e:
            _LOGGER.warning("Could not load dashboard translations: %s", e)
            return {}

    def _translate_dashboard(self, config: dict) -> dict:
        """Translate dashboard strings to user's HA language (#60).

        Reads from dashboard/translations.json — the single source of truth
        shared with sem-localize.js (browser cards).
        """
        lang = self.hass.config.language
        if lang == "en":
            return config  # English template, no translation needed

        all_translations = self._cached_translations
        lang_translations = all_translations.get(lang)
        if not lang_translations:
            # Regional variants fall back to the base language
            # (zh-Hans → zh, de-CH → de) — matches semLocalize() in the cards.
            base_lang = lang.lower().split("-")[0]
            lang_translations = all_translations.get(base_lang)
        if not lang_translations:
            return config

        # Build reverse lookup: English text → translated text
        en = all_translations.get("en", {})
        reverse_map = {}
        for key, en_text in en.items():
            translated = lang_translations.get(key)
            if translated and translated != en_text:
                reverse_map[en_text] = translated

        if not reverse_map:
            return config

        # Walk the config and replace English strings with translations
        # Fields that contain plain user-visible text (not Jinja templates).
        # `secondary` is included so static secondary strings translate, but
        # Jinja-templated secondaries still pass through unchanged (the match
        # is exact, and templates never match a plain English translation key).
        translatable_fields = (
            "title", "subtitle", "primary", "secondary", "name", "label", "content",
        )

        # Pre-compute sorted pairs and compiled patterns once (not per-node)
        sorted_pairs = sorted(
            reverse_map.items(), key=lambda x: len(x[0]), reverse=True
        )
        compiled_patterns = [
            (en_text, translated, re.compile(
                r'(?<![a-zA-Z0-9_./])' + re.escape(en_text) + r'(?![a-zA-Z0-9_])'
            ))
            for en_text, translated in sorted_pairs
        ]
        jinja_split_re = re.compile(r'(\{\{.*?\}\}|\{%.*?%\})', re.DOTALL)

        def _walk(obj):
            if isinstance(obj, dict):
                for field in translatable_fields:
                    if field in obj and isinstance(obj[field], str):
                        text = obj[field]
                        if text in reverse_map:
                            obj[field] = reverse_map[text]
                        elif "{%" in text or "{{" in text:
                            parts = jinja_split_re.split(text)
                            for i in range(0, len(parts), 2):
                                for en_text, translated, pattern in compiled_patterns:
                                    if en_text in parts[i]:
                                        parts[i] = pattern.sub(translated, parts[i])
                            obj[field] = ''.join(parts)
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)

        _walk(config)
        _LOGGER.info(
            "Dashboard translated to '%s' (%d strings available)",
            lang, len(reverse_map),
        )
        return config

    async def _load_comprehensive_dashboard_template(
        self, path: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load the dashboard template from its YAML file.

        For stable releases, strips the beta diagnostics section
        (between SEM_BETA_START and SEM_BETA_END markers).
        """
        template_path = path or self._template_path
        try:
            if os.path.exists(template_path):
                def _read():
                    with open(template_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    # Strip beta section for stable releases
                    import re as _re
                    manifest_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "manifest.json")
                    try:
                        import json as _json
                        with open(manifest_path) as mf:
                            version = _json.load(mf).get("version", "")
                        if "beta" not in version and "rc" not in version:
                            content = _re.sub(
                                r'^\s*# SEM_BETA_START.*?# SEM_BETA_END\s*$',
                                '', content, flags=_re.MULTILINE | _re.DOTALL,
                            )
                            _LOGGER.info("Stripped beta diagnostics from dashboard (stable release %s)", version)
                    except Exception as strip_err:
                        _LOGGER.debug("Beta strip skipped: %s", strip_err)
                    return yaml.safe_load(content)
                template = await self.hass.async_add_executor_job(_read)
                _LOGGER.info("Loaded dashboard template from %s", template_path)
                return template
            else:
                _LOGGER.warning("Dashboard template not found at %s", template_path)
                return None
        except Exception as e:
            _LOGGER.error("Failed to load dashboard template: %s", e, exc_info=True)
            return None

    async def generate_dashboard(
        self,
        dashboard_title: str = "Solar Energy Management",
        dashboard_path: str = "sem-dashboard",
        template: str = "next",
    ) -> Dict[str, Any]:
        """Generate the SEM dashboard configuration (#1321).

        Args:
            dashboard_title: Title for the dashboard
            dashboard_path: URL path for accessing the dashboard
            template: only ``next`` exists; ``classic`` is a deprecated
                alias for it and logs one warning.

        Returns:
            Dashboard configuration dictionary
        """
        if template == "classic":
            _LOGGER.warning(
                "generate_dashboard: template 'classic' is retired, "
                "building the SEM dashboard ('next') instead")
        _LOGGER.info(
            "Generating SEM dashboard: %s (path: %s)", dashboard_title, dashboard_path)

        # Pre-load translations for use in _translate_dashboard (avoids blocking I/O)
        self._cached_translations = await self.hass.async_add_executor_job(
            self._load_dashboard_translations_sync
        )

        config = await self._load_comprehensive_dashboard_template()
        if not config or "views" not in config:
            raise FileNotFoundError(f"Dashboard template not found: {self._template_path}")
        config = self._translate_dashboard(config)
        config["title"] = dashboard_title
        config["path"] = dashboard_path
        config["icon"] = NEXT_DASHBOARD_ICON
        config["show_in_sidebar"] = True
        config["require_admin"] = False
        _LOGGER.info("SEM dashboard generated with %d views", len(config["views"]))
        return config

    async def save_dashboard(
        self,
        config: Dict[str, Any],
        storage_key: str = "lovelace.sem-dashboard",
    ) -> bool:
        """Save dashboard configuration to storage and register it.

        Args:
            config: Dashboard configuration dictionary
            storage_key: Storage key for the dashboard

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            storage_path = os.path.join(
                self._config_dir,
                ".storage",
                storage_key,
            )

            # Wrap config in storage format
            storage_data = {
                "version": 1,
                "minor_version": 1,
                "key": storage_key,
                "data": {"config": config},
            }

            def _write_dashboard():
                os.makedirs(os.path.dirname(storage_path), exist_ok=True)
                with open(storage_path, "w", encoding="utf-8") as f:
                    json.dump(storage_data, f, indent=2, ensure_ascii=False)

            await self.hass.async_add_executor_job(_write_dashboard)
            _LOGGER.info("Dashboard saved to %s", storage_path)

            # Register dashboard in lovelace_dashboards
            await self._register_dashboard(config, storage_key)

            return True

        except Exception as e:
            _LOGGER.error("Failed to save dashboard: %s", e, exc_info=True)
            return False

    async def _register_dashboard(
        self,
        config: Dict[str, Any],
        storage_key: str,
    ) -> bool:
        """Register dashboard in lovelace_dashboards storage.

        Args:
            config: Dashboard configuration
            storage_key: Storage key for the dashboard

        Returns:
            True if registered successfully, False otherwise
        """
        try:
            dashboards_path = os.path.join(
                self._config_dir,
                ".storage",
                "lovelace_dashboards",
            )

            # Extract URL key from storage key (e.g., "lovelace.sem-dashboard" -> "sem-dashboard")
            url_key = storage_key.replace("lovelace.", "")

            def _read_and_update_registry():
                # Read current dashboard registry
                if os.path.exists(dashboards_path):
                    with open(dashboards_path, "r", encoding="utf-8") as f:
                        dashboards_data = json.load(f)
                else:
                    dashboards_data = {
                        "version": 1,
                        "minor_version": 1,
                        "key": "lovelace_dashboards",
                        "data": {"items": []},
                    }

                # Check if dashboard already registered
                items = dashboards_data["data"]["items"]
                existing_item = next(
                    (item for item in items if item.get("url_path") == url_key),
                    None
                )

                if existing_item:
                    existing_item.update({
                        "require_admin": config.get("require_admin", False),
                        "show_in_sidebar": config.get("show_in_sidebar", True),
                        "icon": config.get("icon", "mdi:solar-power"),
                        "title": config.get("title", "Solar Energy Management"),
                    })
                    _LOGGER.info("Updated existing dashboard registration: %s", url_key)
                else:
                    new_item = {
                        "id": url_key,
                        "url_path": url_key,
                        "require_admin": config.get("require_admin", False),
                        "show_in_sidebar": config.get("show_in_sidebar", True),
                        "icon": config.get("icon", "mdi:solar-power"),
                        "title": config.get("title", "Solar Energy Management"),
                        "mode": "storage",
                    }
                    items.append(new_item)
                    _LOGGER.info("Added new dashboard registration: %s", url_key)

                # Save updated registry
                with open(dashboards_path, "w", encoding="utf-8") as f:
                    json.dump(dashboards_data, f, indent=2, ensure_ascii=False)

            await self.hass.async_add_executor_job(_read_and_update_registry)
            _LOGGER.info("Dashboard registered in lovelace_dashboards")
            return True

        except Exception as e:
            _LOGGER.error("Failed to register dashboard: %s", e, exc_info=True)
            return False

    async def create_dashboard(
        self,
        dashboard_title: str = "Solar Energy Management",
        dashboard_path: str = "sem-dashboard",
        template: str = "next",
    ) -> Optional[str]:
        """Generate and save dashboard in one step.

        Returns:
            Dashboard path if successful, None otherwise
        """
        try:
            # Generate configuration
            config = await self.generate_dashboard(
                dashboard_title=dashboard_title,
                dashboard_path=dashboard_path,
                template=template,
            )

            # Save to storage
            storage_key = f"lovelace.{dashboard_path}"
            success = await self.save_dashboard(config, storage_key)

            if success:
                _LOGGER.info(
                    "Dashboard created successfully: %s",
                    dashboard_path,
                )
                return dashboard_path

            return None

        except Exception as e:
            _LOGGER.error(
                "Failed to create dashboard: %s",
                e,
                exc_info=True,
            )
            return None
