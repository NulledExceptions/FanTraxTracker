from __future__ import annotations

import time

import pytest
import responses

from fantrax_analytics.adapters.http import DiskCache, FantraxHttpClient, RateLimiter
from fantrax_analytics.config import Settings
from fantrax_analytics.exceptions import AuthError, EdgeRejectedError, RateLimitError, TransientError
from tests.conftest import BASE

URL = f"{BASE}/fxea/general/getStandings"


@responses.activate
def test_sends_user_agent_and_parses_json(http: FantraxHttpClient) -> None:
    responses.get(URL, json={"ok": True})
    raw = http.request("GET", "/fxea/general/getStandings", endpoint="getStandings", source="official")
    assert raw.payload == {"ok": True}
    assert raw.source == "official"
    assert responses.calls[0].request.headers["User-Agent"] == http.settings.user_agent


@responses.activate
def test_403_html_is_edge_rejection_not_retried(http: FantraxHttpClient) -> None:
    responses.get(URL, body="<html>error code: 1010</html>", status=403, content_type="text/html")
    with pytest.raises(EdgeRejectedError):
        http.request("GET", "/fxea/general/getStandings", endpoint="x", source="official")
    assert len(responses.calls) == 1


@responses.activate
def test_403_json_is_auth_error(http: FantraxHttpClient) -> None:
    responses.get(URL, json={"error": "forbidden"}, status=403)
    with pytest.raises(AuthError):
        http.request("GET", "/fxea/general/getStandings", endpoint="x", source="official")


@responses.activate
def test_200_html_is_auth_error(http: FantraxHttpClient) -> None:
    responses.get(URL, body="<!doctype html><html>login</html>", status=200, content_type="text/html")
    with pytest.raises(AuthError):
        http.request("GET", "/fxea/general/getStandings", endpoint="x", source="official")


@responses.activate
def test_429_then_success_is_retried(http: FantraxHttpClient) -> None:
    responses.get(URL, json={"err": "slow down"}, status=429)
    responses.get(URL, json={"ok": 1})
    raw = http.request("GET", "/fxea/general/getStandings", endpoint="x", source="official")
    assert raw.payload == {"ok": 1}
    assert len(responses.calls) == 2


@responses.activate
def test_exhausted_retries_raise(http: FantraxHttpClient) -> None:
    for _ in range(http.settings.max_retries + 1):
        responses.get(URL, status=503)
    with pytest.raises(TransientError):
        http.request("GET", "/fxea/general/getStandings", endpoint="x", source="official")
    assert len(responses.calls) == http.settings.max_retries + 1


@responses.activate
def test_rate_limit_error_after_retries(http: FantraxHttpClient) -> None:
    for _ in range(http.settings.max_retries + 1):
        responses.get(URL, status=429)
    with pytest.raises(RateLimitError):
        http.request("GET", "/fxea/general/getStandings", endpoint="x", source="official")


@responses.activate
def test_cache_hit_skips_network(settings: Settings) -> None:
    client = FantraxHttpClient(settings, cache=DiskCache(settings.cache_dir, 3600))
    responses.get(URL, json={"n": 1})
    first = client.request("GET", "/fxea/general/getStandings", endpoint="x", source="official")
    second = client.request("GET", "/fxea/general/getStandings", endpoint="x", source="official")
    assert first.payload == second.payload
    assert not first.from_cache and second.from_cache
    assert len(responses.calls) == 1


@responses.activate
def test_cache_bypass(settings: Settings) -> None:
    client = FantraxHttpClient(settings, cache=DiskCache(settings.cache_dir, 3600))
    responses.get(URL, json={"n": 1})
    responses.get(URL, json={"n": 2})
    client.request("GET", "/fxea/general/getStandings", endpoint="x", source="official")
    raw = client.request(
        "GET", "/fxea/general/getStandings", endpoint="x", source="official", use_cache=False
    )
    assert raw.payload == {"n": 2}


def test_rate_limiter_spacing() -> None:
    limiter = RateLimiter(50)  # 20 ms
    limiter.wait()
    start = time.monotonic()
    limiter.wait()
    assert time.monotonic() - start >= 0.015
