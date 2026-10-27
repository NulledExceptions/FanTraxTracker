from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from fantrax_analytics.config import load_settings, write_env_var


def test_write_env_var_replaces_and_appends(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FANTRAX_LEAGUE_ID=abc\nFANTRAX_MY_TEAM_ID=\nOTHER=1\n")
    write_env_var(env, "FANTRAX_MY_TEAM_ID", "tm5")
    write_env_var(env, "NEW_KEY", "x")
    assert env.read_text() == "FANTRAX_LEAGUE_ID=abc\nFANTRAX_MY_TEAM_ID=tm5\nOTHER=1\nNEW_KEY=x\n"


def test_write_env_var_creates_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    write_env_var(env, "K", "v")
    assert env.read_text() == "K=v\n"


def test_season_validation() -> None:
    with pytest.raises(ValidationError):
        load_settings(_env_file=None, season="2026")


def test_secret_masked_in_dump() -> None:
    s = load_settings(_env_file=None, user_secret_id="abc")
    assert "abc" not in repr(s)
    assert s.secret_id_value == "abc"
