"""Client for the Fantrax official REST API (v1.0 beta) at ``/fxea/general/``.

Every method returns a :class:`RawResponse`; no parsing happens here. Field names in the
beta API may change, so validation lives in ``models/`` and tolerates unknown fields.
"""

from __future__ import annotations

from typing import Any

from fantrax_analytics.adapters.http import FantraxHttpClient, RawResponse
from fantrax_analytics.exceptions import ConfigError

BASE_PATH = "/fxea/general"


class OfficialApiClient:
    def __init__(self, http: FantraxHttpClient) -> None:
        self.http = http

    def _get(self, name: str, params: dict[str, Any], *, use_cache: bool = True) -> RawResponse:
        clean = {k: v for k, v in params.items() if v is not None}
        return self.http.request(
            "GET", f"{BASE_PATH}/{name}", endpoint=name, source="official", params=clean, use_cache=use_cache
        )

    def _post(self, name: str, body: dict[str, Any], *, use_cache: bool = True) -> RawResponse:
        clean = {k: v for k, v in body.items() if v is not None}
        return self.http.request(
            "POST",
            f"{BASE_PATH}/{name}",
            endpoint=name,
            source="official",
            json_body=clean,
            use_cache=use_cache,
        )

    # --------------------------------------------------------------- user-level
    def get_leagues(self, user_secret_id: str | None) -> RawResponse:
        if not user_secret_id:
            raise ConfigError("getLeagues requires FANTRAX_USER_SECRET_ID")
        # Secret goes in the POST body so it never lands in a URL / cache key in plain text.
        return self._post("getLeagues", {"userSecretId": user_secret_id})

    # ------------------------------------------------------------- league-level
    def get_league_info(self, league_id: str, *, exclude_player_info: bool = False) -> RawResponse:
        if exclude_player_info:
            return self._post("getLeagueInfo", {"leagueId": league_id, "excludePlayerInfo": True})
        return self._get("getLeagueInfo", {"leagueId": league_id})

    def get_team_rosters(self, league_id: str, period: int | None = None) -> RawResponse:
        return self._get("getTeamRosters", {"leagueId": league_id, "period": period})

    def get_standings(self, league_id: str) -> RawResponse:
        return self._get("getStandings", {"leagueId": league_id})

    def get_team_stats_for_matchups(self, league_id: str, period: int | None = None) -> RawResponse:
        return self._get("getTeamStatsForMatchups", {"leagueId": league_id, "period": period})

    def get_draft_picks(self, league_id: str) -> RawResponse:
        return self._get("getDraftPicks", {"leagueId": league_id})

    def get_draft_results(self, league_id: str) -> RawResponse:
        return self._get("getDraftResults", {"leagueId": league_id})

    # -------------------------------------------------------------- sport-level
    def get_player_ids(self, sport: str) -> RawResponse:
        return self._get("getPlayerIds", {"sport": sport})

    def get_adp(
        self,
        sport: str,
        *,
        position: str | None = None,
        show_all_positions: bool | None = None,
        start: int | None = None,
        limit: int | None = None,
        order: str | None = None,
    ) -> RawResponse:
        return self._get(
            "getAdp",
            {
                "sport": sport,
                "position": position,
                "showAllPositions": show_all_positions,
                "start": start,
                "limit": limit,
                "order": order,
            },
        )
