"""Fetch and load the raw payloads the dashboard needs.

This is the only place in ``reports/`` that touches the network or the filesystem. Each domain is
saved under ``discovery/<domain>.json`` (same files the discovery command writes) so the report
can be rebuilt offline with ``--offline``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fantrax_analytics.adapters.auth import ClientFactory
from fantrax_analytics.adapters.fxpa import FxpaClient
from fantrax_analytics.adapters.official import OfficialApiClient
from fantrax_analytics.config import Settings
from fantrax_analytics.discover import derive_current_period, period_bounds
from fantrax_analytics.exceptions import FantraxError
from fantrax_analytics.logging_setup import get_logger
from fantrax_analytics.raw_store import load_raw, save_raw

log = get_logger(__name__)

POOL_PAGES = 3  # 3 x 50 available players, Fantrax "Score" order
PROJECTION_CODE_SUFFIX = "_EVENT_PROJECTED_WEEKLY"


@dataclass
class ReportPayloads:
    """Everything the dashboard reads, keyed by domain. Missing domains are simply absent."""

    payloads: dict[str, Any] = field(default_factory=dict)
    fetched_at: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def get(self, domain: str) -> Any:
        return self.payloads.get(domain)


def find_opponent(league_info: Any, period: int, team_id: str) -> str | None:
    matchups = league_info.get("matchups") if isinstance(league_info, dict) else None
    for entry in matchups if isinstance(matchups, list) else []:
        if entry.get("period") != period:
            continue
        for pair in entry.get("matchupList") or []:
            away, home = pair.get("away") or {}, pair.get("home") or {}
            if away.get("id") == team_id:
                return str(home.get("id")) if home.get("id") else None
            if home.get("id") == team_id:
                return str(away.get("id")) if away.get("id") else None
    return None


def projection_code(payload: Any) -> str | None:
    """The ``seasonOrProjections`` code for Fantrax's projected-per-game view, from any STATS payload."""
    options = payload.get("seasonOrProjections") if isinstance(payload, dict) else None
    if not isinstance(options, list):
        lists = payload.get("displayedLists") if isinstance(payload, dict) else None
        options = lists.get("seasonOrProjections") if isinstance(lists, dict) else None
    for option in options if isinstance(options, list) else []:
        code = str(option.get("code", "")) if isinstance(option, dict) else ""
        if code.endswith(PROJECTION_CODE_SUFFIX):
            return code
    return None


class ReportFetcher:
    """Refreshes the dashboard's domains through the adapters (cache-aware, rate-limited)."""

    def __init__(self, settings: Settings, factory: ClientFactory, *, now: dt.datetime | None = None) -> None:
        self.settings = settings
        self.factory = factory
        self.now = (now or dt.datetime.now()).astimezone()
        self.today = self.now.date()
        self.out = ReportPayloads()

    @property
    def fxpa(self) -> FxpaClient:
        return FxpaClient(self.factory.client("none"), self.settings.league_id)

    @property
    def official(self) -> OfficialApiClient:
        return OfficialApiClient(self.factory.client("none"))

    def _grab(self, domain: str, fn: Any) -> Any:
        try:
            raw = fn()
        except FantraxError as exc:
            log.warning("report.fetch_failed", domain=domain, error=str(exc))
            self.out.errors[domain] = str(exc)
            return None
        save_raw(self.settings.discovery_dir, domain, raw)
        self.out.payloads[domain] = raw.payload
        self.out.fetched_at[domain] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        log.info("report.fetched", domain=domain, bytes=raw.size_bytes, from_cache=raw.from_cache)
        return raw.payload

    def fetch(self) -> ReportPayloads:
        s = self.settings
        team_id = s.my_team_id
        if not team_id:
            raise FantraxError("FANTRAX_MY_TEAM_ID is not set; run `fantrax discover` first")
        league_info = self._grab("league_info", lambda: self.official.get_league_info(s.league_id))
        period = derive_current_period(league_info, "scoring", self.now)
        if period is None:
            raise FantraxError("could not derive the current scoring period from getLeagueInfo")
        opponent = find_opponent(league_info, period, team_id)
        fx = self.fxpa

        self._grab("matchups_current", lambda: fx.live_scoring_stats(self.today, period))
        self._grab("fx_matchup_results", fx.matchup_results)
        roster = self._grab("fx_my_roster_stats", lambda: fx.team_roster(team_id))
        code = projection_code(roster)
        if code:
            self._grab("fx_my_roster_proj", lambda: fx.team_roster(team_id, season_or_projection=code))
        if opponent:
            self._grab("fx_opp_roster_stats", lambda: fx.team_roster(opponent))
            if code:
                self._grab("fx_opp_roster_proj", lambda: fx.team_roster(opponent, season_or_projection=code))
        self._grab("fx_my_roster_games_per_pos", lambda: fx.team_games_per_position(team_id, period))
        self._grab("fx_league_info", fx.league_info)

        teams = league_info.get("teamInfo") if isinstance(league_info, dict) else None
        team_ids = [str(k) for k in teams] if isinstance(teams, dict) else [team_id]
        bundle: dict[str, Any] = {}
        first = None
        for tid in team_ids:
            try:
                raw = fx.team_roster_schedule(tid, period)
            except FantraxError as exc:
                self.out.errors[f"schedule:{tid}"] = str(exc)
                continue
            first = first or raw
            bundle[tid] = raw.payload
        if first is not None:
            from dataclasses import replace

            self._grab("fx_league_roster_schedules", lambda: replace(first, payload=bundle, from_cache=False))

        for page in range(1, POOL_PAGES + 1):
            self._grab(f"fx_player_pool_season_p{page}", lambda page=page: fx.player_stats(page=page))
            if code:
                self._grab(
                    f"fx_player_pool_proj_p{page}",
                    lambda page=page: fx.player_stats(page=page, season_or_projection=code),
                )
        self.out.payloads["_period"] = period
        self.out.payloads["_opponent"] = opponent
        self.out.payloads["_bounds"] = period_bounds(league_info, "scoring", period)
        return self.out


def load_payloads(
    discovery_dir: Path, *, now: dt.datetime | None = None, my_team_id: str | None = None
) -> ReportPayloads:
    """Offline: read the saved files and re-derive period/opponent from the saved league info."""
    out = ReportPayloads()
    domains = [
        "league_info",
        "matchups_current",
        "fx_matchup_results",
        "fx_my_roster_stats",
        "fx_my_roster_proj",
        "fx_opp_roster_stats",
        "fx_opp_roster_proj",
        "fx_my_roster_games_per_pos",
        "fx_league_info",
        "fx_league_roster_schedules",
        "fx_my_roster_schedule",
    ]
    domains += [f"fx_player_pool_season_p{i}" for i in range(1, POOL_PAGES + 1)]
    domains += [f"fx_player_pool_proj_p{i}" for i in range(1, POOL_PAGES + 1)]
    domains.append("fx_player_pool_season")  # discovery's single page, as a fallback
    for domain in domains:
        loaded = load_raw(discovery_dir, domain)
        if loaded is None:
            continue
        meta, payload = loaded
        out.payloads[domain] = payload
        out.fetched_at[domain] = str(meta.get("fetched_at", ""))
    league_info = out.get("league_info")
    instant = (now or dt.datetime.now()).astimezone()
    period = derive_current_period(league_info, "scoring", instant)
    out.payloads["_period"] = period
    out.payloads["_opponent"] = (
        find_opponent(league_info, period, my_team_id) if period and my_team_id else None
    )
    out.payloads["_bounds"] = period_bounds(league_info, "scoring", period) if period else None
    return out
