"""HTTP transport shared by every Fantrax client.

Responsibilities:
* always send the configured ``User-Agent`` (Fantrax edge protection rejects requests without one)
* rate-limit outgoing requests
* retry with exponential backoff on 429 / 5xx / connection failures
* classify failures into the :mod:`fantrax_analytics.exceptions` hierarchy
* optional TTL disk cache for development re-runs (never a source of truth)
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import requests
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from fantrax_analytics.config import Settings
from fantrax_analytics.exceptions import (
    AuthError,
    EdgeRejectedError,
    FantraxError,
    RateLimitError,
    TransientError,
)
from fantrax_analytics.logging_setup import get_logger

log = get_logger(__name__)

AuthLevel = Literal["none", "secret", "cookie"]
Source = Literal["official", "fxpa", "fantraxapi", "derived"]
JsonValue = Any  # Fantrax payloads are arbitrary JSON; Pydantic validation happens in models/.

_EDGE_MARKERS = ("error code: 1010", "error 1010", "access denied", "cf-error", "cloudflare")


@dataclass(frozen=True)
class RawResponse:
    """One fetched payload plus the metadata discovery and the audit log need."""

    source: Source
    endpoint: str
    url: str
    status_code: int
    payload: JsonValue
    size_bytes: int
    elapsed_ms: int
    auth_level: AuthLevel
    from_cache: bool = False
    request_body: dict[str, Any] | None = field(default=None, compare=False)


class RateLimiter:
    """Simple minimum-interval limiter. Thread-safe."""

    def __init__(self, requests_per_second: float) -> None:
        self._interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next_allowed - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._next_allowed = now + self._interval


class DiskCache:
    """TTL cache of raw JSON payloads keyed by request identity. Dev convenience only."""

    def __init__(self, directory: Path, ttl_seconds: int) -> None:
        self.directory = directory
        self.ttl = ttl_seconds
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key_for(method: str, url: str, params: dict[str, Any] | None, body: dict[str, Any] | None) -> str:
        ident = json.dumps([method, url, params or {}, body or {}], sort_keys=True, default=str)
        return hashlib.sha256(ident.encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        if self.ttl and (time.time() - path.stat().st_mtime) > self.ttl:
            return None
        try:
            entry: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return entry

    def put(self, key: str, entry: dict[str, Any]) -> None:
        self._path(key).write_text(json.dumps(entry, default=str), encoding="utf-8")


def _looks_like_html(text: str, content_type: str) -> bool:
    return "text/html" in content_type.lower() or text.lstrip()[:1] == "<"


def _log_retry(state: RetryCallState) -> None:
    exc = state.outcome.exception() if state.outcome else None
    log.warning(
        "http.retry",
        attempt=state.attempt_number,
        wait=round(state.next_action.sleep, 1) if state.next_action else None,
        error=repr(exc),
    )


class FantraxHttpClient:
    """Thin, instrumented wrapper around :class:`requests.Session`."""

    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
        auth_level: AuthLevel = "none",
        cache: DiskCache | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.settings = settings
        self.auth_level: AuthLevel = auth_level
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = settings.user_agent
        self.session.headers["Accept"] = "application/json, text/plain, */*"
        self.cache = cache
        self.limiter = limiter or RateLimiter(settings.rate_limit_rps)
        self._retrying = Retrying(
            retry=retry_if_exception_type((RateLimitError, TransientError)),
            stop=stop_after_attempt(settings.max_retries + 1),
            wait=wait_exponential_jitter(initial=1, max=30),
            before_sleep=_log_retry,
            reraise=True,
        )

    # ------------------------------------------------------------------ public
    def request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        endpoint: str,
        source: Source,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> RawResponse:
        url = f"{self.settings.base_url}{path}"
        cache_key = DiskCache.key_for(method, url, params, json_body)

        if use_cache and self.cache is not None:
            hit = self.cache.get(cache_key)
            if hit is not None:
                log.debug("http.cache_hit", endpoint=endpoint, url=url)
                return RawResponse(
                    source=source,
                    endpoint=endpoint,
                    url=url,
                    status_code=int(hit["status_code"]),
                    payload=hit["payload"],
                    size_bytes=int(hit["size_bytes"]),
                    elapsed_ms=0,
                    auth_level=self.auth_level,
                    from_cache=True,
                    request_body=json_body,
                )

        response = self._retrying(self._send, method, url, params, json_body, endpoint)
        if use_cache and self.cache is not None:
            self.cache.put(
                cache_key,
                {
                    "status_code": response.status_code,
                    "size_bytes": response.size_bytes,
                    "payload": response.payload,
                },
            )
        return response

    # ----------------------------------------------------------------- private
    def _send(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        endpoint: str,
    ) -> RawResponse:
        self.limiter.wait()
        started = time.monotonic()
        try:
            resp = self.session.request(
                method, url, params=params, json=json_body, timeout=self.settings.timeout_seconds
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientError(f"{method} {url}: {exc.__class__.__name__}: {exc}") from exc
        elapsed_ms = int((time.monotonic() - started) * 1000)

        text = resp.text
        content_type = resp.headers.get("Content-Type", "")
        log.info(
            "http.response",
            endpoint=endpoint,
            method=method,
            url=url,
            status=resp.status_code,
            bytes=len(resp.content),
            ms=elapsed_ms,
            auth_level=self.auth_level,
        )

        self._raise_for_status(resp, text, content_type, url)

        if _looks_like_html(text, content_type):
            # 200 but HTML: Fantrax served a page (login/landing) instead of the API.
            raise AuthError(
                f"{url} returned HTML instead of JSON (status {resp.status_code}); login likely required"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise FantraxError(
                f"{url} returned non-JSON body (status {resp.status_code}): {text[:200]!r}"
            ) from exc

        return RawResponse(
            source="official" if "/fxea/" in url else "fxpa",
            endpoint=endpoint,
            url=url,
            status_code=resp.status_code,
            payload=payload,
            size_bytes=len(resp.content),
            elapsed_ms=elapsed_ms,
            auth_level=self.auth_level,
            request_body=json_body,
        )

    @staticmethod
    def _raise_for_status(resp: requests.Response, text: str, content_type: str, url: str) -> None:
        code = resp.status_code
        if code == 429:
            raise RateLimitError(
                f"{url}: 429 Too Many Requests (Retry-After={resp.headers.get('Retry-After')})"
            )
        if code >= 500:
            raise TransientError(f"{url}: HTTP {code}")
        if code == 403:
            lowered = text.lower()
            if _looks_like_html(text, content_type) or any(marker in lowered for marker in _EDGE_MARKERS):
                raise EdgeRejectedError(
                    f"{url}: 403 from edge protection (Cloudflare 1010). Check the User-Agent header."
                )
            raise AuthError(f"{url}: 403 Forbidden from API")
        if code == 401:
            raise AuthError(f"{url}: 401 Unauthorized")
        if code >= 400:
            raise FantraxError(f"{url}: HTTP {code}: {text[:300]!r}")
