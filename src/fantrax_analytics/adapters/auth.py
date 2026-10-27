"""Session construction for each authentication level.

Levels, in the order discovery tries them:

* ``none``   — User-Agent only. The official API docs imply league endpoints need nothing more.
* ``secret`` — adds ``userSecretId`` (from the Fantrax profile page) as a request parameter.
* ``cookie`` — a browser session exported to ``cookie_file``. The Selenium capture command is
  deliberately NOT implemented until discovery proves it is required; this loader only consumes
  a cookie file that already exists.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from fantrax_analytics.adapters.http import AuthLevel, DiskCache, FantraxHttpClient, RateLimiter
from fantrax_analytics.config import Settings
from fantrax_analytics.exceptions import AuthError, ConfigError
from fantrax_analytics.logging_setup import get_logger

log = get_logger(__name__)


def load_cookie_session(settings: Settings) -> requests.Session:
    """Build a session from a JSON cookie export (list of ``{name, value, domain, path}``).

    Raises :class:`ConfigError` if the file does not exist (level untestable) and
    :class:`AuthError` if it exists but is unusable.
    """
    path = settings.cookie_file
    if not path.exists():
        raise ConfigError(f"cookie file {path} not found; the cookie auth level cannot be tested")
    try:
        cookies: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthError(f"cookie file {path} is unreadable: {exc}") from exc
    session = requests.Session()
    loaded = 0
    for cookie in cookies:
        if "name" not in cookie or "value" not in cookie:
            continue
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain", "www.fantrax.com"),
            path=cookie.get("path", "/"),
        )
        loaded += 1
    if loaded == 0:
        raise AuthError(f"cookie file {path} contained no usable cookies")
    log.info("auth.cookies_loaded", count=loaded, path=str(path))
    return session


class ClientFactory:
    """Builds :class:`FantraxHttpClient` instances per auth level, sharing one limiter and cache."""

    def __init__(self, settings: Settings, *, use_cache: bool = True) -> None:
        self.settings = settings
        self.limiter = RateLimiter(settings.rate_limit_rps)
        self.cache = DiskCache(settings.cache_dir, settings.cache_ttl_seconds) if use_cache else None
        self._clients: dict[AuthLevel, FantraxHttpClient] = {}

    def client(self, level: AuthLevel) -> FantraxHttpClient:
        if level in self._clients:
            return self._clients[level]
        session: requests.Session | None = None
        if level == "secret":
            if not self.settings.secret_id_value:
                raise ConfigError("FANTRAX_USER_SECRET_ID is not set; the secret auth level cannot be tested")
            session = requests.Session()
            session.params = {"userSecretId": self.settings.secret_id_value}
        elif level == "cookie":
            session = load_cookie_session(self.settings)
        client = FantraxHttpClient(
            self.settings, session=session, auth_level=level, cache=self.cache, limiter=self.limiter
        )
        self._clients[level] = client
        return client
