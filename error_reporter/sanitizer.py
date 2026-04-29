"""Sanitize report payloads before sending to a public repo.

Strips or hashes anything that identifies the user's installation:
- Entity IDs that contain user-chosen names (sensor.my_keba_in_garage)
- Absolute paths (/config/, /home/<user>/)
- IP addresses, MAC addresses
- HA token / cookie shaped strings
- Anything inside common secret keys
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

# Keys whose value must never leave the host
SECRET_KEYS = frozenset({
    "github_token",
    "n8n_webhook_url",
    "access_token",
    "refresh_token",
    "password",
    "api_key",
    "auth",
    "authorization",
    "bearer",
    "secret",
    "token",
})

# Regexes for sensitive substrings inside strings
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
_PATH_RE = re.compile(r"(?:/config|/home/[^/\s]+|/Users/[^/\s]+)")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")


def hash_entity_id(entity_id: str) -> str:
    """Hash an entity ID stably so the same sensor produces the same tag.

    Keeps the domain prefix (sensor., binary_sensor., etc.) so the report
    still tells you what kind of entity is involved.
    """
    if not isinstance(entity_id, str) or "." not in entity_id:
        return _short_hash(str(entity_id))
    domain, _, _ = entity_id.partition(".")
    return f"{domain}.<hash:{_short_hash(entity_id)}>"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _redact_string(text: str) -> str:
    if not text:
        return text
    text = _PATH_RE.sub("<path>", text)
    text = _IP_RE.sub("<ip>", text)
    text = _MAC_RE.sub("<mac>", text)
    text = _LONG_TOKEN_RE.sub("<token>", text)
    return text


def _looks_like_entity_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if "." not in value:
        return False
    domain, _, name = value.partition(".")
    # HA entity domains are short lowercase ascii
    return (
        1 <= len(domain) <= 32
        and domain.replace("_", "").isalnum()
        and domain.islower()
        and bool(name)
        and " " not in value
    )


def sanitize_payload(payload: Any, *, _depth: int = 0) -> Any:
    """Recursively redact a payload.

    - Drops values for any key in SECRET_KEYS
    - Hashes entity-id-shaped strings
    - Redacts paths/IPs/MACs/long opaque tokens inside free-text strings
    - Caps recursion depth to avoid runaway dicts
    """
    if _depth > 8:
        return "<truncated>"

    if isinstance(payload, Mapping):
        out: dict[str, Any] = {}
        for k, v in payload.items():
            key_lower = str(k).lower()
            if key_lower in SECRET_KEYS or any(s in key_lower for s in ("token", "secret", "password")):
                out[str(k)] = "<redacted>"
                continue
            out[str(k)] = sanitize_payload(v, _depth=_depth + 1)
        return out

    if isinstance(payload, (list, tuple)):
        return [sanitize_payload(v, _depth=_depth + 1) for v in payload]

    if isinstance(payload, str):
        if _looks_like_entity_id(payload):
            return hash_entity_id(payload)
        return _redact_string(payload)

    # numbers, bool, None pass through
    return payload
