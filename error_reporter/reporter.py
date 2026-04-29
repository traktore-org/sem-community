"""GitHub issue reporter with dedupe + rate limit.

Posts at most one issue per signature per ``dedupe_window`` seconds, and
at most ``daily_cap`` issues per day total. State is persisted in HA's
Store so dedupe survives restarts.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .sanitizer import sanitize_payload

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_STORAGE_KEY = "solar_energy_management_error_reporter"

# Conservative defaults — avoid spamming the public repo.
_DEFAULT_DEDUPE_WINDOW_S = 24 * 60 * 60  # 24h per signature
_DEFAULT_DAILY_CAP = 10  # max new issues per UTC day
_DEFAULT_HTTP_TIMEOUT_S = 10

_GITHUB_API = "https://api.github.com"


@dataclass
class _State:
    """Persisted dedupe + rate-limit state."""

    last_seen: dict[str, float] = field(default_factory=dict)  # signature -> epoch
    day_counts: dict[str, int] = field(default_factory=dict)   # YYYY-MM-DD -> count

    def to_json(self) -> dict[str, Any]:
        return {"last_seen": self.last_seen, "day_counts": self.day_counts}

    @classmethod
    def from_json(cls, raw: Any) -> "_State":
        if not isinstance(raw, Mapping):
            return cls()
        last_seen = raw.get("last_seen") or {}
        day_counts = raw.get("day_counts") or {}
        if not isinstance(last_seen, Mapping) or not isinstance(day_counts, Mapping):
            return cls()
        return cls(
            last_seen={str(k): float(v) for k, v in last_seen.items()},
            day_counts={str(k): int(v) for k, v in day_counts.items()},
        )


class ErrorReporter:
    """Report SEM errors and anomalies as GitHub issues.

    Construct once per config entry. Call ``async_load`` before first use,
    then ``async_report_exception`` or ``async_report_anomaly``.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        github_token: str,
        github_repo: str,
        integration_version: str,
        enabled: bool = True,
        dedupe_window_s: int = _DEFAULT_DEDUPE_WINDOW_S,
        daily_cap: int = _DEFAULT_DAILY_CAP,
        labels: Optional[list[str]] = None,
        entry_id: Optional[str] = None,
    ) -> None:
        self.hass = hass
        self._token = github_token
        self._repo = github_repo
        self._version = integration_version
        self._enabled = enabled
        self._dedupe_window_s = dedupe_window_s
        self._daily_cap = daily_cap
        self._labels = labels or ["auto-reported"]

        suffix = f"_{entry_id}" if entry_id else ""
        self._store: Store = Store(hass, _STORAGE_VERSION, f"{_STORAGE_KEY}{suffix}")
        self._state: _State = _State()
        self._lock = asyncio.Lock()
        self._loaded = False

    # ---------------- lifecycle ----------------
    async def async_load(self) -> None:
        raw = await self._store.async_load()
        self._state = _State.from_json(raw)
        self._gc_old_days()
        self._loaded = True

    async def _async_save(self) -> None:
        await self._store.async_save(self._state.to_json())

    # ---------------- public API ----------------
    async def async_report_exception(
        self,
        exc: BaseException,
        *,
        component: str,
        context: Optional[Mapping[str, Any]] = None,
    ) -> Optional[int]:
        """Report a hard exception. Returns issue number if created."""
        signature = _exc_signature(component, exc)
        title = f"[auto] {component}: {type(exc).__name__}: {_one_liner(str(exc))}"
        body = self._build_exception_body(component, exc, context or {})
        return await self._dispatch(signature=signature, title=title, body=body)

    async def async_report_anomaly(
        self,
        *,
        signature: str,
        title: str,
        details: Mapping[str, Any],
    ) -> Optional[int]:
        """Report a soft anomaly. ``signature`` must be stable per-issue-class."""
        full_title = f"[auto] anomaly: {title}"
        body = self._build_anomaly_body(signature, title, details)
        return await self._dispatch(signature=signature, title=full_title, body=body)

    # ---------------- internals ----------------
    async def _dispatch(self, *, signature: str, title: str, body: str) -> Optional[int]:
        if not self._enabled:
            return None
        if not self._token or not self._repo or "/" not in self._repo:
            _LOGGER.debug("Error reporter not configured; skipping")
            return None
        if not self._loaded:
            _LOGGER.debug("Error reporter not loaded yet; skipping")
            return None

        async with self._lock:
            now = time.time()
            today = _utc_date(now)

            last = self._state.last_seen.get(signature)
            if last is not None and (now - last) < self._dedupe_window_s:
                _LOGGER.debug("Suppressing duplicate signature=%s", signature)
                return None

            count_today = self._state.day_counts.get(today, 0)
            if count_today >= self._daily_cap:
                _LOGGER.warning(
                    "Daily issue cap reached (%d) — skipping signature=%s",
                    self._daily_cap, signature,
                )
                return None

            issue_number = await self._post_issue(title=title, body=body)
            if issue_number is None:
                # Don't burn the dedupe slot if we failed to post.
                return None

            self._state.last_seen[signature] = now
            self._state.day_counts[today] = count_today + 1
            self._gc_old_days()
            await self._async_save()
            return issue_number

    async def _post_issue(self, *, title: str, body: str) -> Optional[int]:
        url = f"{_GITHUB_API}/repos/{self._repo}/issues"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"sem-error-reporter/{self._version}",
        }
        payload = {
            "title": title[:240],  # GitHub caps title length
            "body": body,
            "labels": self._labels,
        }
        try:
            session: aiohttp.ClientSession = async_get_clientsession(self.hass)
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=_DEFAULT_HTTP_TIMEOUT_S),
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    number = data.get("number") if isinstance(data, dict) else None
                    _LOGGER.info("Filed auto-issue #%s on %s", number, self._repo)
                    return number if isinstance(number, int) else None
                text = await resp.text()
                _LOGGER.warning(
                    "GitHub issue create failed: status=%s body=%s",
                    resp.status, text[:200],
                )
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            _LOGGER.warning("GitHub issue create network error: %s", e)
            return None

    # ---------------- body formatting ----------------
    def _build_exception_body(
        self,
        component: str,
        exc: BaseException,
        context: Mapping[str, Any],
    ) -> str:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        safe_context = sanitize_payload(dict(context))
        return _render_body(
            kind="exception",
            component=component,
            integration_version=self._version,
            ha_version=context.get("ha_version", "unknown"),
            extra_sections=[
                ("Traceback", f"```\n{_truncate(tb, 4000)}\n```"),
                ("Context", f"```json\n{_json(safe_context)}\n```"),
            ],
        )

    def _build_anomaly_body(
        self,
        signature: str,
        title: str,
        details: Mapping[str, Any],
    ) -> str:
        safe_details = sanitize_payload(dict(details))
        return _render_body(
            kind="anomaly",
            component=safe_details.get("component", "unknown"),
            integration_version=self._version,
            ha_version=safe_details.get("ha_version", "unknown"),
            extra_sections=[
                ("Signature", f"`{signature}`"),
                ("What happened", title),
                ("Details", f"```json\n{_json(safe_details)}\n```"),
            ],
        )

    # ---------------- maintenance ----------------
    def _gc_old_days(self) -> None:
        """Drop day_counts entries older than 7 days."""
        if not self._state.day_counts:
            return
        cutoff = time.time() - 7 * 24 * 60 * 60
        cutoff_day = _utc_date(cutoff)
        self._state.day_counts = {
            d: c for d, c in self._state.day_counts.items() if d >= cutoff_day
        }


# ---------------- helpers ----------------
def _exc_signature(component: str, exc: BaseException) -> str:
    """Stable hash from the deepest frame + exception type, ignoring message."""
    tb = exc.__traceback__
    frames: list[str] = []
    while tb is not None:
        f = tb.tb_frame
        frames.append(f"{f.f_code.co_filename}:{f.f_code.co_name}:{tb.tb_lineno}")
        tb = tb.tb_next
    payload = f"{component}|{type(exc).__name__}|{'>'.join(frames[-5:])}"
    return "exc:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _one_liner(text: str, limit: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head - 32
    return text[:head] + "\n…[truncated]…\n" + text[-tail:]


def _json(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _utc_date(epoch: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(epoch))


def _render_body(
    *,
    kind: str,
    component: str,
    integration_version: str,
    ha_version: str,
    extra_sections: list[tuple[str, str]],
) -> str:
    parts = [
        f"**Auto-filed by SEM error reporter** · kind: `{kind}`",
        "",
        f"- Component: `{component}`",
        f"- Integration version: `{integration_version}`",
        f"- HA version: `{ha_version}`",
        "",
    ]
    for heading, content in extra_sections:
        parts.append(f"### {heading}")
        parts.append(content)
        parts.append("")
    parts.append(
        "_Sensor entity IDs are hashed and secrets redacted before posting._"
    )
    return "\n".join(parts)
