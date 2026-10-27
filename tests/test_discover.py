from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import responses
from tenacity import wait_none

from fantrax_analytics.adapters.auth import ClientFactory
from fantrax_analytics.adapters.http import AuthLevel, FantraxHttpClient
from fantrax_analytics.config import Settings
from fantrax_analytics.discover import (
    Discovery,
    collect_keys,
    derive_current_period,
    find_dict_containing,
    first_record,
    match_expected,
)
from tests.conftest import BASE, fixture

TODAY = dt.date(2026, 10, 26)


class FastFactory(ClientFactory):
    def client(self, level: AuthLevel) -> FantraxHttpClient:
        c = super().client(level)
        c._retrying.wait = wait_none()
        return c


def _mock_official() -> None:
    g = f"{BASE}/fxea/general"
    responses.post(f"{g}/getLeagues", json=fixture("getLeagues"))
    responses.get(f"{g}/getLeagueInfo", json=fixture("getLeagueInfo"))
    responses.post(
        f"{g}/getLeagueInfo", json={k: v for k, v in fixture("getLeagueInfo").items() if k != "playerInfo"}
    )
    responses.get(f"{g}/getTeamRosters", json=fixture("getTeamRosters"))
    responses.get(f"{g}/getStandings", json=fixture("getStandings"))
    responses.get(f"{g}/getTeamStatsForMatchups", json=fixture("getTeamStatsForMatchups"))
    responses.get(f"{g}/getDraftResults", json={})
    responses.get(f"{g}/getDraftPicks", status=500)
    responses.get(f"{g}/getPlayerIds", json=[{"fantraxId": "p1", "name": "Some Player"}])
    responses.get(f"{g}/getAdp", json={"players": [{"name": "Some Player", "adp": 12.3}]})


@responses.activate
def test_full_discovery_run(settings: Settings) -> None:
    _mock_official()
    responses.post(f"{BASE}/fxpa/req", json={"pageError": {"code": "WARNING_NOT_LOGGED_IN"}})

    disc = Discovery(settings, FastFactory(settings, use_cache=False), today=TODAY)
    results = disc.run()
    by = {r.domain: r for r in results}

    # team id resolved from getLeagues and written to .env
    assert disc.my_team_id == "tm5marc"
    assert "FANTRAX_MY_TEAM_ID=tm5marc" in settings.env_file.read_text()

    # periods derived from league info; past-period probes used current-1
    assert disc.current_scoring_period == 2
    assert disc.current_roster_period == 7
    past_calls = [c.request.url for c in responses.calls if "period=" in c.request.url]
    assert any("getTeamStatsForMatchups?leagueId=fqj3m6m8murmhnko&period=1" in u for u in past_calls)
    assert any("getTeamRosters?leagueId=fqj3m6m8murmhnko&period=6" in u for u in past_calls)

    assert by["league_info"].status == "AVAILABLE"
    assert by["standings"].status == "AVAILABLE"
    assert by["matchups_current"].status == "AVAILABLE"
    assert by["draft_results"].status == "UNAVAILABLE"  # empty payload
    assert by["draft_picks"].status == "UNAVAILABLE"  # 5xx exhausted
    assert "TransientError" in (by["draft_picks"].error or "")

    # fxpa: rejected at none and secret, cookie untestable -> UNAVAILABLE with escalation note
    fx = by["fx_transactions"]
    assert fx.status == "UNAVAILABLE"
    assert fx.auth_attempts == ["none", "secret", "cookie"]
    assert any("cookie: not testable" in n for n in fx.notes)
    # the secret level actually sent the secret as a query param
    secret_calls = [c for c in responses.calls if "userSecretId=s3cr3t" in c.request.url]
    assert secret_calls and all("/fxpa/req" in c.request.url for c in secret_calls)

    # roster-stats probe needs a team id, which we had
    assert by["fx_my_roster_stats"].auth_attempts == ["none", "secret", "cookie"]

    # derived checks ran
    assert by["player_pool_availability"].status in ("AVAILABLE", "PARTIAL")
    assert by["nba_schedule"].status == "UNAVAILABLE"

    # artefacts
    report = disc.write_report()
    text = report.read_text()
    assert "| league_info | **AVAILABLE** |" in text
    assert "Selenium" in text  # decision about the cookie path
    assert "nba_schedule" in text
    assert (settings.discovery_dir / "league_info.json").exists()
    saved = json.loads((settings.discovery_dir / "league_info.json").read_text())
    assert saved["meta"]["endpoint"] == "getLeagueInfo"
    assert json.loads((settings.discovery_dir / "summary.json").read_text())


@responses.activate
def test_edge_rejection_stops_escalation(settings: Settings) -> None:
    responses.get(
        f"{BASE}/fxea/general/getStandings",
        body="<html>error code: 1010</html>",
        status=403,
        content_type="text/html",
    )
    disc = Discovery(
        settings, FastFactory(settings, use_cache=False), today=TODAY, only_domains=["standings"]
    )
    results = disc.run()
    standings = next(r for r in results if r.domain == "standings")
    assert standings.status == "UNAVAILABLE"
    assert standings.auth_attempts == ["none"]  # did not bother with cookies
    assert "Edge rejection" in disc.render_report()


def test_discovery_without_secret_skips_leagues(settings: Settings, tmp_path: Path) -> None:
    s = settings.model_copy(update={"user_secret_id": None})
    disc = Discovery(s, FastFactory(s, use_cache=False), today=TODAY, only_domains=["leagues"])
    results = disc.run()
    assert results[0].status == "SKIPPED"


def test_helpers() -> None:
    info = fixture("getLeagueInfo")
    assert derive_current_period(info, "scoring", TODAY) == 2
    assert derive_current_period(info, "roster", dt.date(2026, 10, 25)) == 6
    assert derive_current_period(info, "scoring", dt.date(2030, 1, 1)) is None
    keys = collect_keys(info)
    assert {"scoringSystem", "periodNumber", "playerInfo"} <= keys
    assert match_expected(keys, ("scoring", "nothing")) == (["scoring"], ["nothing"])
    hit = find_dict_containing(fixture("getLeagues"), value="fqj3m6m8murmhnko")
    assert hit and hit["teamId"] == "tm5marc"
    assert first_record(fixture("getStandings")) == {"teamId": "tm1", "wins": 4, "losses": 2}
