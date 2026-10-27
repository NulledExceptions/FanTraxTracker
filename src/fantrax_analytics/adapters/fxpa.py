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

    def standings(self, view: str | None = None) -> RawResponse:
        return self.call("getStandings", view=view)

    def team_roster(self, team_id: str, *, view: str = "STATS", period: int | None = None) -> RawResponse:
        return self.call("getTeamRosterInfo", teamId=team_id, view=view, period=period)

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
    ) -> RawResponse:
        """Player pool with stats — the web client's 'Players' page request.

        ``timeframe`` values seen in the web client: YEAR_TO_DATE, LAST_7_DAYS, LAST_15_DAYS,
        LAST_30_DAYS. ``status_filter``: ALL, ALL_AVAILABLE, ALL_TAKEN, or a team id.
        """
        return self.call(
            "getPlayerStats",
            statusOrTeamFilter=status_filter,
            timeframeTypeCode=timeframe,
            positionOrGroup=position,
            pageNumber=page,
            maxResultsPerPage=per_page,
        )
