from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import responses
from tenacity import wait_none

from fantrax_analytics.adapters.auth import ClientFactory
from fantrax_analytics.adapters.http import AuthLevel, FantraxHttpClient
from fantrax_analytics.config import Settings
from fantrax_analytics.discover import (
    FANTRAX_NBA_TEAMS,
    Discovery,
    collect_keys,
    derive_current_period,
    find_dict_containing,
    first_record,
    match_expected,
    period_bounds,
    schedule_coverage,
)
from tests.conftest import BASE, fixture

EDT = dt.timezone(dt.timedelta(hours=-4))
# 23:30 ET on Oct 26: scoring period 2 / roster period 7 have started (bounds flip at 19:00 ET).
NOW = dt.datetime(2026, 10, 26, 23, 30, tzinfo=EDT)
TODAY = NOW.date()


class FastFactory(ClientFactory):
    def client(self, level: AuthLevel) -> FantraxHttpClient:
        c = super().client(level)
        c._retrying.wait = wait_none()
        return c


def _mock_official() -> None:
    g = f"{BASE}/fxea/general"
    responses.post(f"{g}/getLeagues", json=fixture("getLeagues"))
    responses.get(f"{g}/getLeagueInfo", json=fixture("getLeagueInfo"))
    responses.get(f"{g}/getTeamRosters", json=fixture("getTeamRosters"))
    responses.get(f"{g}/getStandings", json=fixture("getStandings"))
    responses.get(f"{g}/getDraftResults", json={})
    responses.get(f"{g}/getDraftPicks", status=500)
    responses.get(f"{g}/getPlayerIds", json=[{"fantraxId": "p1", "name": "Some Player"}])
    responses.get(f"{g}/getAdp", json={"players": [{"name": "Some Player", "adp": 12.3}]})


def _mock_fxpa(allowed: dict[str, str]) -> None:
    """Route ``/fxpa/req`` by ``method`` (or ``method:view``) to a fixture; anything else is NOT_LOGGED_IN."""

    def callback(request: Any) -> tuple[int, dict[str, str], str]:
        msg = json.loads(request.body)["msgs"][0]
        name = allowed.get(f"{msg['method']}:{msg['data'].get('view')}") or allowed.get(msg["method"])
        body = fixture(name) if name else {"pageError": {"code": "WARNING_NOT_LOGGED_IN"}}
        return 200, {}, json.dumps(body)

    responses.add_callback(
        responses.POST, f"{BASE}/fxpa/req", callback=callback, content_type="application/json"
    )


FXPA_PUBLIC = {
    "getLiveScoringStats": "fxpa_getLiveScoringStats",
    "getStandings:SCHEDULE": "fxpa_getStandings_SCHEDULE",
    "getTeamRosterInfo:SCHEDULE_FULL": "fxpa_getTeamRosterInfo_SCHEDULE_FULL",
    "getFantasyLeagueInfo": "fxpa_getFantasyLeagueInfo",
}


def _fxpa_calls(method: str) -> list[dict[str, str]]:
    out = []
    for c in responses.calls:
        if c.request.body and b"/fxpa/req" in c.request.url.encode():
            msg = json.loads(c.request.body)["msgs"][0]
            if msg["method"] == method:
                out.append(msg["data"])
    return out


@responses.activate
def test_full_discovery_run(settings: Settings) -> None:
    _mock_official()
    _mock_fxpa(FXPA_PUBLIC)

    disc = Discovery(settings, FastFactory(settings, use_cache=False), now=NOW)
    results = disc.run()
    by = {r.domain: r for r in results}

    # team id resolved from getLeagues and written to .env
    assert disc.my_team_id == "tm5marc"
    assert "FANTRAX_MY_TEAM_ID=tm5marc" in settings.env_file.read_text()

    # periods derived from league info as instants; past-period probes used current-1
    assert disc.current_scoring_period == 2
    assert disc.current_roster_period == 7
    past_calls = [c.request.url for c in responses.calls if "period=" in c.request.url]
    assert any("getTeamRosters?leagueId=fqj3m6m8murmhnko&period=6" in u for u in past_calls)

    # matchups: current = today + scoring period 2; past = first day of period 1 + period 1
    live = _fxpa_calls("getLiveScoringStats")
    assert {"date": TODAY.isoformat(), "period": "2"}.items() <= live[0].items()
    assert live[1]["period"] == "1" and live[1]["date"].startswith("2026-10-2")
    assert by["matchups_current"].status == "AVAILABLE"
    assert by["matchups_past"].status == "AVAILABLE"
    assert by["fx_matchup_results"].status == "AVAILABLE"

    assert by["league_info"].status == "AVAILABLE"
    assert by["standings"].status == "AVAILABLE"
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

    # getFantasyLeagueInfo answers with the public view -> escalate through every level, keep it
    info = by["fx_league_info"]
    assert info.status == "PARTIAL"
    assert info.auth_attempts == ["none", "secret", "cookie"]
    assert any("isMember=false" in n for n in info.notes)
    assert "cookie" in info.recommendation
    assert by["fx_league_settings"].status == "UNAVAILABLE"

    # roster-stats probe needs a team id, which we had
    assert by["fx_my_roster_stats"].auth_attempts == ["none", "secret", "cookie"]

    # league-wide schedule: one SCHEDULE_FULL call per fantasy team, bundled
    sched_calls = [d for d in _fxpa_calls("getTeamRosterInfo") if d.get("view") == "SCHEDULE_FULL"]
    assert {d["teamId"] for d in sched_calls} >= {"tm1", "tm5marc"}
    assert by["fx_league_roster_schedules"].status == "AVAILABLE"
    nba = by["nba_schedule"]
    assert nba.status == "PARTIAL"  # fixture rosters only two NBA teams
    assert any("NBA teams rostered 2/30" in n for n in nba.notes)
    assert "CHI" not in nba.missing and "BOS" in nba.missing
    assert by["available_player_schedule"].status == "SKIPPED"  # pool was not fetched

    # derived checks ran
    assert by["player_pool_availability"].status in ("AVAILABLE", "PARTIAL")
    assert by["transaction_rules"].status == "UNAVAILABLE"

    # artefacts
    report = disc.write_report()
    text = report.read_text()
    assert "| league_info | **AVAILABLE** |" in text
    assert "| matchups_current | **AVAILABLE** |" in text
    assert "Selenium" in text  # decision about the cookie path
    assert "getLeagueSettings answers WARNING_NOT_LOGGED_IN" in text
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
    disc = Discovery(settings, FastFactory(settings, use_cache=False), now=NOW, only_domains=["standings"])
    results = disc.run()
    standings = next(r for r in results if r.domain == "standings")
    assert standings.status == "UNAVAILABLE"
    assert standings.auth_attempts == ["none"]  # did not bother with cookies
    assert "Edge rejection" in disc.render_report()


def test_discovery_without_secret_skips_leagues(settings: Settings, tmp_path: Path) -> None:
    s = settings.model_copy(update={"user_secret_id": None})
    disc = Discovery(s, FastFactory(s, use_cache=False), now=NOW, only_domains=["leagues"])
    results = disc.run()
    assert results[0].status == "SKIPPED"


def _grid(teams: list[str], dates: list[str]) -> dict[str, Any]:
    rows = [
        {
            "scorer": {"scorerId": f"p{i}", "name": f"P{i}", "teamShortName": t},
            "cells": [{"content": "", "eventId": ""} for _ in dates],
        }
        for i, t in enumerate(teams)
    ]
    header = {"cells": [{"key": f"sched_{d}", "eventStr": True} for d in dates]}
    return {"tables": [{"header": header, "rows": rows}]}


def test_schedule_coverage_full_league(settings: Settings) -> None:
    teams = sorted(FANTRAX_NBA_TEAMS)
    bundle = {"tmA": _grid(teams[:15], ["10/26", "10/27"]), "tmB": _grid(teams[15:], ["10/26", "10/27"])}
    cov = schedule_coverage(bundle)
    assert cov["players"] == 30 and cov["teams_missing"] == [] and cov["dates"] == ["10/26", "10/27"]
    assert len(cov["teams_direct"]) == 30

    disc = Discovery(settings, FastFactory(settings, use_cache=False), now=NOW)
    disc.payloads["fx_league_roster_schedules"] = bundle
    disc.payloads["fx_player_pool_season"] = {
        "statsTable": [{"scorer": {"teamShortName": "CHI"}}, {"scorer": {"teamShortName": "GS"}}]
    }
    by = {r.domain: r for r in disc._derived_checks()}
    assert by["nba_schedule"].status == "AVAILABLE"
    assert by["nba_schedule"].missing == []
    assert by["available_player_schedule"].status == "AVAILABLE"


def test_schedule_coverage_counts_opponents() -> None:
    cov = schedule_coverage(fixture("fxpa_getTeamRosterInfo_SCHEDULE_FULL")["responses"][0]["data"])
    assert cov["teams_direct"] == ["CHI", "PHO"]
    assert {"DET", "MIL", "LAL"} <= set(cov["teams_seen"])
    assert cov["dates"] == ["10/26", "10/27", "10/28"]


def test_helpers() -> None:
    info = fixture("getLeagueInfo")
    # instants: 18:00 ET on the 26th is still period 1 / roster 6; 23:30 ET is period 2 / roster 7
    before_flip = dt.datetime(2026, 10, 26, 18, 0, tzinfo=EDT)
    assert derive_current_period(info, "scoring", before_flip) == 1
    assert derive_current_period(info, "scoring", NOW) == 2
    assert derive_current_period(info, "roster", before_flip) == 6
    assert derive_current_period(info, "roster", NOW) == 7
    assert derive_current_period(info, "scoring", dt.datetime(2030, 1, 1, tzinfo=dt.UTC)) is None
    assert period_bounds(info, "scoring", 1) == (dt.date(2026, 10, 20), dt.date(2026, 10, 26))
    assert period_bounds(info, "scoring", 99) is None
    # date-only bounds still work and are inclusive
    dated = {"scoringPeriods": [{"number": 3, "startDate": "2026-11-02", "endDate": "2026-11-08"}]}
    assert derive_current_period(dated, "scoring", dt.date(2026, 11, 8)) == 3
    assert derive_current_period(dated, "scoring", dt.date(2026, 11, 9)) is None

    keys = collect_keys(info)
    assert {"scoringSystem", "periodNumber", "playerInfo"} <= keys
    assert match_expected(keys, ("scoring", "nothing")) == (["scoring"], ["nothing"])
    hit = find_dict_containing(fixture("getLeagues"), value="fqj3m6m8murmhnko")
    assert hit and hit["teamId"] == "tm5marc"
    assert first_record(fixture("getStandings")) == {"teamId": "tm1", "wins": 4, "losses": 2}
