"""Client for the undocumented ``/fxpa/req`` message API.

This mirrors exactly what ``fantraxapi`` 1.0 does internally:
``POST /fxpa/req?leagueId=<id>`` with ``{"msgs": [{"method": <name>, "data": {"leagueId": ..}}]}``.
All data values are sent as strings (the site does the same). Responses are unwrapped from
``responses[i].data``; ``pageError`` codes map to our exception hierarchy.

Used only for what the official beta API does not expose (per-player stats, the FA pool with
stats, transactions, claim budgets). Method names below are the best-known ones from the
library and the web client; discovery records which actually work for this league.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

from fantrax_analytics.adapters.http import FantraxHttpClient, RawResponse
from fantrax_analytics.exceptions import AuthError, FantraxError

REQ_PATH = "/fxpa/req"

# fantraxapi equivalents, for the discovery report's "library method" column.
LIBRARY_EQUIVALENTS: dict[str, str] = {
    "getFantasyLeagueInfo": "League() init",
    "getStandings": "League.standings()",
    "getTeamRosterInfo": "League.team_roster()",
    "getTransactionDetailsHistory": "League.transactions()",
    "getPendingTransactions": "League.pending_trades()",
    "getTradeBlocks": "League.trade_block()",
    "getLiveScoringStats": "League.live_scores()",
    "getPlayerStats": "(none)",
    "getLeagueSettings": "(none)",
}


class FxpaClient:
    def __init__(self, http: FantraxHttpClient, league_id: str) -> None:
        self.http = http
        self.league_id = league_id

    def call(self, method: str, *, use_cache: bool = True, **data: Any) -> RawResponse:
        payload_data: dict[str, str] = {"leagueId": self.league_id}
        payload_data.update({k: str(v) for k, v in data.items() if v is not None})
        body = {"msgs": [{"method": method, "data": payload_data}]}
        raw = self.http.request(
            "POST",
            REQ_PATH,
            endpoint=f"fxpa:{method}",
            source="fxpa",
            params={"leagueId": self.league_id},
            json_body=body,
            use_cache=use_cache,
        )
        return replace(raw, payload=self._unwrap(raw.payload, method))

    @staticmethod
    def _unwrap(payload: Any, method: str) -> Any:
        if not isinstance(payload, dict):
            raise FantraxError(f"fxpa {method}: unexpected top-level type {type(payload).__name__}")
        page_error = payload.get("pageError")
        if isinstance(page_error, dict):
            code = page_error.get("code")
            if code in ("WARNING_NOT_LOGGED_IN", "NOT_MEMBER_OF_LEAGUE"):
                raise AuthError(f"fxpa {method}: {code}")
            raise FantraxError(f"fxpa {method}: pageError {code}: {page_error.get('title')}")
        responses = payload.get("responses")
        if not isinstance(responses, list) or not responses:
            raise FantraxError(f"fxpa {method}: no 'responses' in payload (keys={list(payload)[:10]})")
        first = responses[0]
        if isinstance(first, dict) and "data" in first:
            return first["data"]
        return first

    # ----------------------------------------------------- known method helpers
    def league_info(self) -> RawResponse:
        return self.call("getFantasyLeagueInfo")

    def league_settings(self) -> RawResponse:
        """League settings page (transaction rules, claim limits, FA budget).

        Discovery showed this method exists but answers ``WARNING_NOT_LOGGED_IN`` without a
        browser session, so it is only useful at the ``cookie`` auth level.
        """
        return self.call("getLeagueSettings")

    def standings(self, view: str | None = None) -> RawResponse:
        return self.call("getStandings", view=view)

    def matchup_results(self) -> RawResponse:
        """Per-scoring-period matchup results (category W/L/T per team) — ``getStandings`` SCHEDULE view.

        One table per scoring period in ``tableList``; each row carries ``matchupId`` and the
        team's category wins/losses for that period. This is the source for past matchups: the
        official API has no matchup method at all.
        """
        return self.call("getStandings", view="SCHEDULE")

    def team_roster(
        self,
        team_id: str,
        *,
        view: str = "STATS",
        period: int | None = None,
        season_or_projection: str | None = None,
    ) -> RawResponse:
        """Roster table. ``season_or_projection`` selects the stat source, e.g.
        ``PROJECTION_0_<seasonId>_EVENT_PROJECTED_WEEKLY`` (Fantrax projected per game; the GP
        column then holds projected games this period) — codes come from
        ``seasonOrProjections`` in any STATS payload."""
        return self.call(
            "getTeamRosterInfo",
            teamId=team_id,
            view=view,
            period=period,
            seasonOrProjection=season_or_projection,
        )

    def team_roster_schedule(self, team_id: str, period: int | None = None) -> RawResponse:
        return self.call("getTeamRosterInfo", teamId=team_id, view="SCHEDULE_FULL", period=period)

    def team_games_per_position(self, team_id: str, scoring_period: int | None = None) -> RawResponse:
        return self.call(
            "getTeamRosterInfo", teamId=team_id, view="GAMES_PER_POS", scoringPeriod=scoring_period
        )

    def live_scoring_stats(self, scoring_date: date, scoring_period: int | None = None) -> RawResponse:
        """Live matchup scores and per-player stats for one date.

        ``scoring_period`` is the *scoring* period that contains ``scoring_date`` (never a roster
        period). ``fantraxapi`` always sends ``period=1`` and lets the date win; we send the real
        period when discovery has derived it so the request is unambiguous for past periods.
        """
        return self.call(
            "getLiveScoringStats",
            date=scoring_date.isoformat(),
            newView=True,
            period=scoring_period,
            playerViewType=1,
            sppId=-1,
            viewType=1,
        )

    def transactions(self, per_page: int = 100) -> RawResponse:
        return self.call("getTransactionDetailsHistory", maxResultsPerPage=per_page)

    def pending_transactions(self) -> RawResponse:
        return self.call("getPendingTransactions")

    def player_stats(
        self,
        *,
        status_filter: str = "ALL_AVAILABLE",
        timeframe: str = "YEAR_TO_DATE",
        position: str | None = None,
        page: int = 1,
        per_page: int = 50,
        season_or_projection: str | None = None,
    ) -> RawResponse:
        """Player pool with stats — the web client's 'Players' page request.

        ``timeframe``: this league only honours YEAR_TO_DATE and BY_PERIOD (``period=``); the
        LAST_N_DAYS codes and ``goBackDays`` are silently ignored (verified in discovery).
        ``status_filter``: ALL, ALL_AVAILABLE, ALL_TAKEN, or a team id. ``season_or_projection``
        as for :meth:`team_roster` (``PROJECTION_0_<seasonId>_EVENT_PROJECTED_WEEKLY`` etc.).
        """
        return self.call(
            "getPlayerStats",
            statusOrTeamFilter=status_filter,
            timeframeTypeCode=timeframe,
            positionOrGroup=position,
            pageNumber=page,
            maxResultsPerPage=per_page,
            seasonOrProjection=season_or_projection,
        )
