from __future__ import annotations

import json
from pathlib import Path

import pytest
from tenacity import wait_none

from fantrax_analytics.adapters.http import FantraxHttpClient
from fantrax_analytics.config import Settings, load_settings

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.fantrax.com"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        _env_file=None,
        user_secret_id="s3cr3t",
        league_id="fqj3m6m8murmhnko",
        rate_limit_rps=1000.0,
        max_retries=2,
        cache_dir=tmp_path / "cache",
        cache_ttl_seconds=3600,
        discovery_dir=tmp_path / "discovery",
        log_dir=tmp_path / "logs",
        env_file=tmp_path / ".env",
        cookie_file=tmp_path / "cookies.json",
    )


@pytest.fixture
def http(settings: Settings) -> FantraxHttpClient:
    client = FantraxHttpClient(settings)
    client._retrying.wait = wait_none()  # keep tests fast
    return client
