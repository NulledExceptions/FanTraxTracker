"""NBA schedule from the SCHEDULE_FULL roster grids, and games-played outlook for a roster."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

from fantrax_analytics.analytics.roster import RosterPlayer
from fantrax_analytics.analytics.tables import header_cells, player_rows

_DATE_KEY_RE = re.compile(r"^sched_(\d{1,2})/(\d{1,2})$")
_UPCOMING_RE = re.compile(r"^(@?)([A-Z]{2,3})\s*(.*)$")


@dataclass(frozen=True)
class Game:
    date: dt.date
    opponent: str
    home: bool
    detail: str  # "Tue 8:00PM" or "PHO 114 @OKC 125 F"
    event_id: str
    final: bool


Schedule = dict[str, dict[dt.date, Game]]  # nba team → date → game


def _date_from_key(key: str, anchor: dt.date) -> dt.date | None:
    match = _DATE_KEY_RE.match(key)
    if not match:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    year = anchor.year
    if month < anchor.month - 6:  # grid wrapped into the next calendar year
        year += 1
    elif month > anchor.month + 6:
        year -= 1
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _parse_cell(content: str, own_team: str, date: dt.date, event_id: str) -> Game | None:
    text = re.sub(r"<br\s*/?>", " ", content).strip()
    if not text:
        return None
    final = bool(re.search(r"\bF(\(OT\))?\s*$|\d+\s+@?[A-Z]{2,3}\s+\d+", text))
    if final:
        teams = re.findall(r"(@?)([A-Z]{2,3})\s+\d+", text)
        others = [(at, t) for at, t in teams if t != own_team]
        if not others:
            return None
        at, opp = others[0]
        # In a finished line the "@" marks the home side; we were away if the opponent has no "@".
        return Game(date, opp, home=(at == ""), detail=text, event_id=event_id, final=True)
    match = _UPCOMING_RE.match(text)
    if not match:
        return None
    return Game(
        date,
        match.group(2),
        home=(match.group(1) == ""),
        detail=match.group(3),
        event_id=event_id,
        final=False,
    )


def parse_schedule(payload: Any, anchor: dt.date) -> Schedule:
    """Union of SCHEDULE_FULL grids: a single payload or a ``{fantasy_team_id: payload}`` bundle."""
    bundles = list(payload.values()) if isinstance(payload, dict) and "tables" not in payload else [payload]
    schedule: Schedule = {}
    for bundle in bundles:
        tables = bundle.get("tables") if isinstance(bundle, dict) else None
        for table in tables if isinstance(tables, list) else []:
            dates = [_date_from_key(str(c.get("key", "")), anchor) for c in header_cells(table)]
            for row in player_rows(table):
                team = str(row["scorer"].get("teamShortName", ""))
                if not team:
                    continue
                for date, cell in zip(dates, row.get("cells") or [], strict=False):
                    if date is None or not isinstance(cell, dict):
                        continue
                    game = _parse_cell(
                        str(cell.get("content") or ""), team, date, str(cell.get("eventId", ""))
                    )
                    if game is not None:
                        schedule.setdefault(team, {}).setdefault(date, game)
    return schedule


def games_for(
    schedule: Schedule, team: str, dates: list[dt.date], *, include_final: bool = False
) -> list[Game]:
    team_games = schedule.get(team, {})
    return [g for d in dates if (g := team_games.get(d)) is not None and (include_final or not g.final)]


@dataclass
class DayLoad:
    date: dt.date
    playing: list[RosterPlayer]  # active players with a game that day
    slots: int

    @property
    def count(self) -> int:
        return len(self.playing)

    @property
    def overflow(self) -> int:
        return max(0, self.count - self.slots)


@dataclass
class GamesOutlook:
    period_dates: list[dt.date]
    remaining_dates: list[dt.date]
    played: int | None  # team games played so far this period (Fantrax GP total)
    max_games: int | None  # Fantrax "Games Played" maximum for the period, if any
    days: list[DayLoad]
    remaining_by_player: dict[str, int] = field(default_factory=dict)  # player_id → games left (all statuses)

    @property
    def active_remaining(self) -> int:
        return sum(d.count for d in self.days)

    @property
    def usable_remaining(self) -> int:
        """Games that fit the active slots day by day (what you get without roster moves)."""
        return sum(min(d.count, d.slots) for d in self.days)

    @property
    def projected_total(self) -> int | None:
        if self.played is None:
            return None
        total = self.played + self.usable_remaining
        return min(total, self.max_games) if self.max_games is not None else total

    @property
    def slack(self) -> int | None:
        """Games still allowed under the cap after everything scheduled is played."""
        if self.max_games is None or self.projected_total is None:
            return None
        return self.max_games - self.projected_total


def games_outlook(
    players: list[RosterPlayer],
    schedule: Schedule,
    *,
    period_dates: list[dt.date],
    today: dt.date,
    active_slots: int,
    played: int | None,
    max_games: int | None,
) -> GamesOutlook:
    remaining_dates = [d for d in period_dates if d >= today]
    days = [
        DayLoad(
            date=d,
            playing=[p for p in players if p.status == "active" and games_for(schedule, p.nba_team, [d])],
            slots=active_slots,
        )
        for d in remaining_dates
    ]
    remaining = {p.player_id: len(games_for(schedule, p.nba_team, remaining_dates)) for p in players}
    return GamesOutlook(period_dates, remaining_dates, played, max_games, days, remaining)


def parse_games_played_limits(payload: Any) -> tuple[int | None, int | None]:
    """(games played so far, max games) from GAMES_PER_POS ``scMinMaxData``; max None if 'No max'."""
    rows = payload.get("scMinMaxData", {}).get("tableData") if isinstance(payload, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if "Games Played" in str(row.get("scoringCategory", "")):
            total = row.get("total")
            maximum = row.get("max")
            played = int(float(total)) if str(total).replace(".", "").isdigit() else None
            cap = int(float(maximum)) if str(maximum).replace(".", "").isdigit() else None
            return played, cap
    return None, None
