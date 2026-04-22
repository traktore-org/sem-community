"""Shared translation helper for dynamic text (#62).

Loads translations from dashboard/translations.json (single source of truth)
and provides get_text() for Python code that generates user-visible strings.
"""
import json
import logging
import os
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Module-level cache — loaded once per HA restart
_translations_cache: Optional[Dict[str, Dict[str, str]]] = None


def _load_translations() -> Dict[str, Dict[str, str]]:
    """Load translations from dashboard/translations.json."""
    global _translations_cache
    if _translations_cache is not None:
        return _translations_cache

    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "dashboard", "translations.json",
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            _translations_cache = json.load(f)
    except (OSError, ValueError) as e:
        _LOGGER.warning("Could not load translations: %s", e)
        _translations_cache = {}
    return _translations_cache


def get_text(hass: HomeAssistant, key: str, default: str = "", **kwargs: Any) -> str:
    """Get translated text for a key.

    Args:
        hass: HomeAssistant instance (for language detection).
        key: Translation key (e.g. "state_solar_charging_active").
        default: Fallback if key not found (English text).
        **kwargs: Format variables (e.g. soc=95, power=1000).

    Returns:
        Translated and formatted string.
    """
    lang = hass.config.language or "en"
    translations = _load_translations()

    lang_dict = translations.get(lang, translations.get("en", {}))
    text = lang_dict.get(key, default)

    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # If formatting fails, return unformatted text
            pass

    return text
