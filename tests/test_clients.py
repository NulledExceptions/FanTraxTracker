from __future__ import annotations

import datetime as dt
import json

import pytest
import responses

from fantrax_analytics.adapters.fxpa import FxpaClient
from fantrax_analytics.adapters.http import FantraxHttpClient
from fantrax_analytics.adapters.official import OfficialApiClient
from fantrax_analytics.exceptions import AuthError, ConfigError, EndpointChangedError, FantraxError
from tests.conftest import BASE


@responses.activate
def test_get_leagues_puts_secret_in_body_not_url(http: FantraxHttpClient) -> None:
    responses.post(f"{BASE}/fxea/general/getLeagues", json={"leagues": []})
    OfficialApiClient(http).get_leagues("s3cr3t")
    req = responses.calls[0].request
    assert "s3cr3t" not in req.url
    assert json.loads(req.body) == {"userSecretId": "s3cr3t"}


def test_get_leagues_requires_secret(http: FantraxHttpClient) -> None:
    with pytest.raises(ConfigError):
        OfficialApiClient(http).get_leagues(None)


@responses.activate
def test_league_info_exclude_player_info_uses_get_params(http: FantraxHttpClient) -> None:
    responses.get(f"{BASE}/fxea/general/getLeagueInfo", json={"x": 1})
    OfficialApiClient(http).get_league_info("L1", exclude_player_info=True)
    assert responses.calls[0].request.url == (
        f"{BASE}/fxea/general/getLeagueInfo?leagueId=L1&excludePlayerInfo=True"
    )


@responses.activate
def test_optional_params_are_dropped(http: FantraxHttpClient) -> None:
    responses.get(f"{BASE}/fxea/general/getTeamRosters", json={})
    OfficialApiClient(http).get_team_rosters("L1", period=None)
    assert responses.calls[0].request.url == f"{BASE}/fxea/general/getTeamRosters?leagueId=L1"


@responses.activate
def test_fxpa_request_shape_and_unwrap(http: FantraxHttpClient) -> None:
    responses.post(f"{BASE}/fxpa/req", json={"responses": [{"data": {"hello": "world"}}]})
    raw = FxpaClient(http, "L1").player_stats(timeframe="LAST_7_DAYS", per_page=10)
    req = responses.calls[0].request
    assert req.url == f"{BASE}/fxpa/req?leagueId=L1"
    body = json.loads(req.body)
    assert body == {
        "msgs": [
            {
                "method": "getPlayerStats",
                "data": {
                    "leagueId": "L1",
                    "statusOrTeamFilter": "ALL_AVAILABLE",
                    "timeframeTypeCode": "LAST_7_DAYS",
                    "pageNumber": "1",
                    "maxResultsPerPage": "10",
                },
            }
        ]
    }
    assert raw.payload == {"hello": "world"}
    assert raw.source == "fxpa"
    assert raw.endpoint == "fxpa:getPlayerStats"


@responses.activate
def test_official_error_body_raises(http: FantraxHttpClient) -> None:
    # The beta API answers unknown methods with HTTP 200 + {"error": {...}}
    responses.get(
        f"{BASE}/fxea/general/getStandings",
        json={
            "error": {"onScreen": False, "code": "WARNING", "message": "Unable to find method 'getStandings'"}
        },
    )
    with pytest.raises(EndpointChangedError, match="Unable to find method"):
        OfficialApiClient(http).get_standings("L1")


@responses.activate
def test_fxpa_live_scoring_sends_date_and_scoring_period(http: FantraxHttpClient) -> None:
    responses.post(f"{BASE}/fxpa/req", json={"responses": [{"data": {}}]})
    client = FxpaClient(http, "L1")
    client.live_scoring_stats(dt.date(2026, 10, 26), 2)
    client.live_scoring_stats(dt.date(2026, 10, 26))
    first = json.loads(responses.calls[0].request.body)["msgs"][0]["data"]
    second = json.loads(responses.calls[1].request.body)["msgs"][0]["data"]
    assert first["date"] == "2026-10-26" and first["period"] == "2"
    assert "period" not in second  # unknown period is omitted, Fantrax derives it from the date


@responses.activate
def test_fxpa_page_error_maps_to_auth(http: FantraxHttpClient) -> None:
    responses.post(f"{BASE}/fxpa/req", json={"pageError": {"code": "WARNING_NOT_LOGGED_IN"}})
    with pytest.raises(AuthError):
        FxpaClient(http, "L1").standings()


@responses.activate
def test_fxpa_other_page_error(http: FantraxHttpClient) -> None:
    responses.post(f"{BASE}/fxpa/req", json={"pageError": {"code": "UNEXPECTED_ERROR", "title": "boom"}})
    with pytest.raises(FantraxError, match="boom"):
        FxpaClient(http, "L1").standings()
