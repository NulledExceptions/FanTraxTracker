"""Assemble everything the dashboard shows from the fetched payloads (pure: no I/O)."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

from fantrax_analytics.analytics.available import (
    AvailablePlayer,
    CategoryHelp,
    attach_schedule,
    help_by_category,
    merge_pools,
)
from fantrax_analytics.analytics.categories import Category
from fantrax_analytics.analytics.matchup import (
    CategoryEdge,
    Matchup,
    category_edges,
    fantrax_projected_wlt,
    league_average_totals,
    my_matchup,
    parse_period_matchups,
    period_categories,
    period_table,
)
from fantrax_analytics.analytics.projection import (
    CategoryProjection,
    TeamProjection,
    compare_projections,
    project_team,
    projected_record,
)
from fantrax_analytics.analytics.roster import RosterPlayer, parse_roster
from fantrax_analytics.analytics.schedule import (
    GamesOutlook,
    Schedule,
    games_outlook,
    parse_games_played_limits,
    parse_schedule,
)
from fantrax_analytics.reports.payloads import POOL_PAGES, ReportPayloads

_PERIOD_LABEL_RE = re.compile(r"\((\w{3}) (\d{1,2}) - (\w{3}) (\d{1,2})\)")


@dataclass
class Dashboard:
    league_name: str
    my_team_id: str
    my_team_name: str
    opponent_id: str | None
    opponent_name: str
    period: int | None
    period_dates: list[dt.date]
    today: dt.date
    generated_at: dt.datetime
    categories: list[Category]
    matchup: Matchup | None
    edges: list[CategoryEdge]
    fantrax_projected_wlt: tuple[float, float, float] | None
    all_matchups: list[Matchup]
    league_average: dict[str, float | None]
    my_roster: list[RosterPlayer]
    my_roster_projected: list[RosterPlayer]
    opp_roster: list[RosterPlayer]
    opp_roster_projected: list[RosterPlayer]
    outlook: GamesOutlook | None
    opp_outlook: GamesOutlook | None
    my_projection: TeamProjection | None
    opp_projection: TeamProjection | None
    projections: list[CategoryProjection]
    projected_record: tuple[int, int, int] | None
    available: list[AvailablePlayer]
    help: list[CategoryHelp]
    schedule: Schedule
    notes: list[str] = field(default_factory=list)
    fetched_at: dict[str, str] = field(default_factory=dict)


def repair_mojibake(text: str) -> str:
    """The official API double-encodes non-ASCII team names ("Rollin\u00e2\u0080\u0099" for "Rollin'")."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _team_names(league_info: Any) -> dict[str, str]:
    teams = league_info.get("teamInfo") if isinstance(league_info, dict) else None
    out: dict[str, str] = {}
    for tid, info in (teams or {}).items():
        name = str(info.get("name", tid)) if isinstance(info, dict) else str(tid)
        out[str(tid)] = repair_mojibake(name)
    return out


def _date_range(first: dt.date, last: dt.date) -> list[dt.date]:
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


def period_game_dates(
    live_payload: Any, period: int | None, bounds: tuple[dt.date, dt.date] | None
) -> list[dt.date]:
    """Calendar dates whose games count for ``period``.

    Preferred source is the live-scoring ``periods`` list ("2 (Oct 26 - Nov 1)"); the fallback is
    the getLeagueInfo bounds, whose end instant (18:59 ET) falls on the *next* period's first day.
    """
    year = bounds[0].year if bounds else dt.date.today().year
    periods = live_payload.get("periods") if isinstance(live_payload, dict) else None
    for entry in periods if isinstance(periods, list) else []:
        if not isinstance(entry, dict) or entry.get("object1") != period:
            continue
        match = _PERIOD_LABEL_RE.search(str(entry.get("object2", "")))
        if match:
            try:
                first = dt.datetime.strptime(f"{match.group(1)} {match.group(2)} {year}", "%b %d %Y").date()
                last = dt.datetime.strptime(f"{match.group(3)} {match.group(4)} {year}", "%b %d %Y").date()
            except ValueError:
                break
            if last < first:  # wrapped into the next calendar year
                last = last.replace(year=year + 1)
            return _date_range(first, last)
    if bounds:
        first, last = bounds
        return _date_range(first, last - dt.timedelta(days=1) if last > first else last)
    return []


def _active_slots(league_info: Any) -> int:
    info = league_info.get("rosterInfo") if isinstance(league_info, dict) else None
    value = info.get("maxTotalActivePlayers") if isinstance(info, dict) else None
    return int(value) if isinstance(value, (int, float)) else 10


def _games_played_estimate(roster: list[RosterPlayer]) -> int:
    return int(sum(p.games or 0 for p in roster if p.status == "active"))


def build_dashboard(payloads: ReportPayloads, *, my_team_id: str, now: dt.datetime) -> Dashboard:
    notes: list[str] = []
    league_info = payloads.get("league_info") or {}
    live = payloads.get("matchups_current") or {}
    standings = payloads.get("fx_matchup_results") or {}
    fx_info = payloads.get("fx_league_info") or {}
    position_map = fx_info.get("positionMap") if isinstance(fx_info, dict) else None
    period = payloads.get("_period")
    opponent_id = payloads.get("_opponent")
    bounds = payloads.get("_bounds")
    names = _team_names(league_info)
    today = now.astimezone().date()
    period_dates = period_game_dates(live, period, bounds)

    # ---- matchup (period totals from the standings schedule view)
    table = period_table(standings, period) if period else None
    categories = period_categories(table) if table else []
    all_matchups = parse_period_matchups(table) if table else []
    matchup = my_matchup(all_matchups, my_team_id)
    edges = category_edges(matchup, my_team_id, categories) if matchup else []
    if matchup is None:
        notes.append("Period totals are missing: fx_matchup_results had no table for this scoring period.")
    if matchup and opponent_id is None:
        sides = matchup.side(my_team_id)
        opponent_id = sides[1].team_id if sides else None

    # ---- rosters
    cats_r, my_roster = parse_roster(payloads.get("fx_my_roster_stats"), position_map)
    _, my_roster_proj = parse_roster(payloads.get("fx_my_roster_proj"), position_map)
    _, opp_roster = parse_roster(payloads.get("fx_opp_roster_stats"), position_map)
    _, opp_roster_proj = parse_roster(payloads.get("fx_opp_roster_proj"), position_map)
    categories = categories or cats_r
    if not my_roster_proj:
        notes.append(
            "Fantrax projected per-game stats were not fetched; projections fall back to year-to-date averages."
        )
        my_roster_proj = my_roster
    if opp_roster and not opp_roster_proj:
        opp_roster_proj = opp_roster
    if not opp_roster:
        notes.append("Opponent roster was not fetched; opponent projections use their current totals only.")

    # ---- schedule and games outlook
    schedule_payload = payloads.get("fx_league_roster_schedules") or payloads.get("fx_my_roster_schedule")
    anchor = period_dates[0] if period_dates else today
    schedule = parse_schedule(schedule_payload, anchor) if schedule_payload else {}
    if not schedule:
        notes.append("No schedule grid was available; games remaining are unknown.")
    played, max_games = parse_games_played_limits(payloads.get("fx_my_roster_games_per_pos"))
    slots = _active_slots(league_info)
    outlook = (
        games_outlook(
            my_roster,
            schedule,
            period_dates=period_dates,
            today=today,
            active_slots=slots,
            played=played,
            max_games=max_games,
        )
        if my_roster and period_dates
        else None
    )
    opp_outlook = (
        games_outlook(
            opp_roster,
            schedule,
            period_dates=period_dates,
            today=today,
            active_slots=slots,
            played=None,
            max_games=max_games,
        )
        if opp_roster and period_dates
        else None
    )

    # ---- projections
    my_projection = opp_projection = None
    projections: list[CategoryProjection] = []
    record = None
    if matchup and categories:
        mine_line, theirs_line = matchup.side(my_team_id) or (matchup.away, matchup.home)
        my_remaining = outlook.remaining_by_player if outlook else None
        opp_remaining = opp_outlook.remaining_by_player if opp_outlook else None
        my_played = played if played is not None else _games_played_estimate(my_roster)
        my_projection = project_team(
            mine_line.totals, my_roster_proj, categories, games_played=my_played, remaining_by_player=my_remaining
        )
        opp_projection = project_team(
            theirs_line.totals,
            opp_roster_proj,
            categories,
            games_played=my_played,
            remaining_by_player=opp_remaining,
        )
        projections = compare_projections(my_projection, opp_projection, categories)
        record = projected_record(projections)
        if played is None:
            notes.append("Games played so far was not available; rate-category projections use an estimate.")
        notes.append(
            "FG% and FT% projections blend the current period rate with players' projected rates weighted "
            "by games; Fantrax exposes no per-player attempts, so treat them as rough."
        )

    # ---- available players
    ytd_pages = [p for i in range(1, POOL_PAGES + 1) if (p := payloads.get(f"fx_player_pool_season_p{i}"))]
    if not ytd_pages and payloads.get("fx_player_pool_season"):
        ytd_pages = [payloads.get("fx_player_pool_season")]
    proj_pages = [p for i in range(1, POOL_PAGES + 1) if (p := payloads.get(f"fx_player_pool_proj_p{i}"))]
    cats_p, available = merge_pools(ytd_pages, proj_pages)
    categories = categories or cats_p
    remaining_dates = outlook.remaining_dates if outlook else [d for d in period_dates if d >= today]
    attach_schedule(available, schedule, remaining_dates)
    help_ = help_by_category(available, categories) if available else []
    if not proj_pages and available:
        notes.append("Available-player rankings use year-to-date per-game averages (no projection pages fetched).")

    league_name = str(league_info.get("leagueName", "Fantrax league")) if isinstance(league_info, dict) else ""
    return Dashboard(
        league_name=league_name,
        my_team_id=my_team_id,
        my_team_name=names.get(my_team_id, my_team_id),
        opponent_id=opponent_id,
        opponent_name=names.get(opponent_id or "", opponent_id or "no opponent"),
        period=period,
        period_dates=period_dates,
        today=today,
        generated_at=now,
        categories=categories,
        matchup=matchup,
        edges=edges,
        fantrax_projected_wlt=fantrax_projected_wlt(live, my_team_id),
        all_matchups=all_matchups,
        league_average=league_average_totals(all_matchups, categories),
        my_roster=my_roster,
        my_roster_projected=my_roster_proj,
        opp_roster=opp_roster,
        opp_roster_projected=opp_roster_proj,
        outlook=outlook,
        opp_outlook=opp_outlook,
        my_projection=my_projection,
        opp_projection=opp_projection,
        projections=projections,
        projected_record=record,
        available=available,
        help=help_,
        schedule=schedule,
        notes=notes,
        fetched_at=dict(payloads.fetched_at),
    )
