"""Available players ranked by how much they can add in each category this period."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

from fantrax_analytics.analytics.categories import Category, categories_from_header, parse_number
from fantrax_analytics.analytics.schedule import Schedule, games_for
from fantrax_analytics.analytics.tables import cell_text, column_index, first_table, header_cells, player_rows

_TAG_RE = re.compile(r"<[^>]+>")
MIN_RATE_PTS = 8.0  # per-game scoring floor before a FG%/FT% candidate is shown


@dataclass
class AvailablePlayer:
    player_id: str
    name: str
    nba_team: str
    positions: list[str]
    availability: str  # "FA" or "W (Tue)" — waiver claim day
    score: float | None  # Fantrax league-tailored value score
    rostered_pct: float | None
    per_game: dict[str, float | None] = field(default_factory=dict)  # YTD per game
    projected: dict[str, float | None] = field(default_factory=dict)  # Fantrax projected per game
    games_remaining: int = 0
    next_games: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    player: AvailablePlayer
    per_game: float  # value used for ranking (projected if available, else YTD)
    impact: float  # per_game x games remaining for counting cats; per_game for rates


@dataclass
class CategoryHelp:
    category: Category
    candidates: list[Candidate]


def parse_pool(payload: Any) -> tuple[list[Category], dict[str, AvailablePlayer]]:
    """One page of ``getPlayerStats``; returns players keyed by id."""
    table = first_table(payload)
    if table is None:
        return [], {}
    cells = header_cells(table)
    categories = categories_from_header(cells)
    cat_index = {cat.key: column_index(cells, short_name=cat.key) for cat in categories}
    status_i = column_index(cells, key="status")
    score_i = column_index(cells, key="score")
    ros_i = column_index(cells, short_name="Ros")
    out: dict[str, AvailablePlayer] = {}
    for row in player_rows(table):
        scorer = row["scorer"]
        pid = str(scorer.get("scorerId", ""))
        out[pid] = AvailablePlayer(
            player_id=pid,
            name=str(scorer.get("name", "?")),
            nba_team=str(scorer.get("teamShortName", "")),
            positions=str(scorer.get("posShortNames", "")).split(",") if scorer.get("posShortNames") else [],
            availability=_TAG_RE.sub("", cell_text(row, status_i) or "FA").strip(),
            score=parse_number(cell_text(row, score_i)),
            rostered_pct=parse_number(cell_text(row, ros_i)),
            per_game={cat.key: parse_number(cell_text(row, cat_index[cat.key])) for cat in categories},
        )
    return categories, out


def merge_pools(
    ytd_pages: list[Any], projected_pages: list[Any]
) -> tuple[list[Category], list[AvailablePlayer]]:
    categories: list[Category] = []
    players: dict[str, AvailablePlayer] = {}
    for page in ytd_pages:
        cats, parsed = parse_pool(page)
        categories = categories or cats
        for pid, p in parsed.items():
            players.setdefault(pid, p)
    for page in projected_pages:
        cats, parsed = parse_pool(page)
        categories = categories or cats
        for pid, p in parsed.items():
            if pid in players:
                players[pid].projected = p.per_game
            else:
                p.projected, p.per_game = p.per_game, {}
                players[pid] = p
    return categories, list(players.values())


def attach_schedule(
    players: list[AvailablePlayer], schedule: Schedule, remaining_dates: list[dt.date]
) -> None:
    for p in players:
        games = games_for(schedule, p.nba_team, remaining_dates)
        p.games_remaining = len(games)
        p.next_games = [f"{g.date.strftime('%a')} {'' if g.home else '@'}{g.opponent}" for g in games]


def _scoring_volume(player: AvailablePlayer) -> float:
    values = [v for v in (player.projected.get("PTS"), player.per_game.get("PTS")) if v is not None]
    return min(values) if values else 0.0


def help_by_category(
    players: list[AvailablePlayer], categories: list[Category], *, top_n: int = 8, min_games: int = 1
) -> list[CategoryHelp]:
    out: list[CategoryHelp] = []
    for cat in categories:
        candidates: list[Candidate] = []
        for p in players:
            if p.games_remaining < min_games:
                continue
            value = p.projected.get(cat.key)
            if value is None:
                value = p.per_game.get(cat.key)
            if value is None:
                continue
            impact = value if cat.is_rate else value * p.games_remaining
            candidates.append(Candidate(p, value, impact))
        candidates.sort(key=lambda c: c.impact, reverse=cat.higher_is_better)
        if cat.is_rate:
            # a high percentage on tiny volume is noise: require real scoring volume (YTD and projected)
            candidates = [c for c in candidates if _scoring_volume(c.player) >= MIN_RATE_PTS]
        out.append(CategoryHelp(cat, candidates[:top_n]))
    return out
