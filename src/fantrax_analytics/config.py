"""Application settings, loaded from the environment and ``.env``.

All variables are prefixed ``FANTRAX_`` (e.g. ``FANTRAX_USER_SECRET_ID``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FANTRAX_",
        extra="ignore",
    )

    # League identity
    user_secret_id: SecretStr | None = None
    league_id: str = "fqj3m6m8murmhnko"
    season: str = "2026-27"
    sport: str = "NBA"
    my_team_id: str | None = None
    my_team_name: str = "No Mercy, Just Usage Rate"

    # HTTP behaviour
    base_url: str = "https://www.fantrax.com"
    user_agent: str = "fantrax-analytics/0.1 (local)"
    rate_limit_rps: float = Field(default=1.0, gt=0)
    max_retries: int = Field(default=4, ge=0)
    timeout_seconds: float = Field(default=30.0, gt=0)

    # Paths
    cache_dir: Path = Path(".cache")
    cache_ttl_seconds: int = Field(default=3600, ge=0)
    discovery_dir: Path = Path("discovery")
    report_dir: Path = Path("reports")
    log_dir: Path = Path("logs")
    db_path: Path = Path("data/fantrax.sqlite")
    cookie_file: Path = Path(".fantrax_cookies.json")
    env_file: Path = Path(".env")

    log_level: LogLevel = "INFO"

    @field_validator("season")
    @classmethod
    def _season_format(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}", value):
            raise ValueError("season must look like 2026-27")
        return value

    @field_validator("base_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def secret_id_value(self) -> str | None:
        return self.user_secret_id.get_secret_value() if self.user_secret_id else None


def load_settings(**overrides: object) -> Settings:
    """Build settings, allowing explicit overrides (used by tests and the CLI)."""
    return Settings(**overrides)  # type: ignore[arg-type]


def write_env_var(env_file: Path, key: str, value: str) -> None:
    """Set ``key=value`` in a dotenv file, replacing an existing line or appending.

    Preserves every other line byte-for-byte. Creates the file if missing.
    """
    lines: list[str] = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    new_line = f"{key}={value}"
    replaced = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
