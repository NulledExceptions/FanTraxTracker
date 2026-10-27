"""Current-period matchup: category totals, W/L/T and per-category edges.

Source: fxpa ``getStandings view=SCHEDULE`` (one table per scoring period; two rows per matchup,
away on top, home below, each with W/L/T, category points and the period totals per category)
plus ``getLiveScoringStats`` for Fantrax's own projected W/L/T.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from fantrax_analytics.analytics.categories import Category, categories_from_header, parse_number
from fantrax_analytics.analytics.tables import cell_text, column_index, header_cells

Leader = Literal["me", "them", "tie", "unknown"]


@dataclass
class TeamPeriodLine:
    team_id: str
    team_name: str
    wins: float
    losses: float
    ties: float
    points: float
    totals: dict[str, float | None] = field(default_factory=dict)  # category key → period total


@dataclass
class Matchup:
    matchup_id: str
    away: TeamPeriodLine
    home: TeamPeriodLine

    def side(self, team_id: str) -> tuple[TeamPeriodLine, TeamPeriodLine] | None:
        if self.away.team_id == team_id:
            return self.away, self.home
        if self.home.team_id == team_id:
            return self.home, self.away
        return None


@dataclass
class CategoryEdge:
    category: Category
    mine: float | None
    theirs: float | None
    leader: Leader
    margin: float | None  # positive = I lead, in the category's own units
    closeness: float | None  # |margin| / max(|mine|, |theirs|); 0 = dead heat


_PERIOD_RE = re.compile(r"scoring period\s+(\d+)", re.IGNORECASE)


def repair_text(text: str) -> str:
    """Undo the double-encoding Fantrax applies to non-ASCII names in some payloads."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def period_table(standings_payload: Any, period: int) -> dict[str, Any] | None:
    tables = standings_payload.get("tableList") if isinstance(standings_payload, dict) else None
    for table in tables if isinstance(tables, list) else []:
        match = _PERIOD_RE.search(str(table.get("caption", "")))
        if match and int(match.group(1)) == period and isinstance(table, dict):
            return cast(dict[str, Any], table)
    return None


def period_categories(table: dict[str, Any]) -> list[Category]:
    return categories_from_header(header_cells(table))


def _line(
    row: dict[str, Any], cells: list[dict[str, Any]], categories: list[Category]
) -> TeamPeriodLine | None:
    fixed = row.get("fixedCells") or []
    team = fixed[0] if fixed and isinstance(fixed[0], dict) else {}
    team_id = team.get("teamId")
    if not team_id:
        return None
    scip_indexes = [i for i, c in enumerate(cells) if c.get("key") == "scip"]
    totals = {
        cat.key: parse_number(cell_text(row, idx)) for cat, idx in zip(categories, scip_indexes, strict=False)
    }
    return TeamPeriodLine(
        team_id=str(team_id),
        team_name=repair_text(str(team.get("content", team_id))),
        wins=parse_number(cell_text(row, column_index(cells, key="win"))) or 0.0,
        losses=parse_number(cell_text(row, column_index(cells, key="loss"))) or 0.0,
        ties=parse_number(cell_text(row, column_index(cells, key="tie"))) or 0.0,
        points=parse_number(cell_text(row, column_index(cells, key="cp"))) or 0.0,
        totals=totals,
    )


def parse_period_matchups(table: dict[str, Any]) -> list[Matchup]:
    cells = header_cells(table)
    categories = categories_from_header(cells)
    by_id: dict[str, list[TeamPeriodLine]] = {}
    order: list[str] = []
    for row in table.get("rows") or []:
        if not isinstance(row, dict):
            continue
        line = _line(row, cells, categories)
        matchup_id = row.get("matchupId")
        if line is None or not matchup_id:
            continue
        if matchup_id not in by_id:
            order.append(str(matchup_id))
        by_id.setdefault(str(matchup_id), []).append(line)
    out: list[Matchup] = []
    for matchup_id in order:
        lines = by_id[matchup_id]
        if len(lines) == 2:
            out.append(Matchup(matchup_id=matchup_id, away=lines[0], home=lines[1]))
    return out


def my_matchup(matchups: list[Matchup], team_id: str) -> Matchup | None:
    return next((m for m in matchups if m.side(team_id) is not None), None)


def category_edges(matchup: Matchup, team_id: str, categories: list[Category]) -> list[CategoryEdge]:
    sides = matchup.side(team_id)
    if sides is None:
        return []
    mine_line, theirs_line = sides
    out: list[CategoryEdge] = []
    for cat in categories:
        mine, theirs = mine_line.totals.get(cat.key), theirs_line.totals.get(cat.key)
        if mine is None or theirs is None:
            out.append(CategoryEdge(cat, mine, theirs, "unknown", None, None))
            continue
        cmp = cat.better(mine, theirs)
        leader: Leader = "me" if cmp > 0 else "them" if cmp < 0 else "tie"
        margin = (mine - theirs) * (1 if cat.higher_is_better else -1)
        scale = max(abs(mine), abs(theirs))
        out.append(CategoryEdge(cat, mine, theirs, leader, margin, abs(margin) / scale if scale else 0.0))
    return out


def fantrax_projected_wlt(live_payload: Any, team_id: str) -> tuple[float, float, float] | None:
    """Fantrax's projected category W/L/T for the team's matchup, from getLiveScoringStats."""
    try:
        active = live_payload["statsPerTeam"]["allTeamsStats"][team_id]["ACTIVE"]
        projected = active["wltPerMchupProjected"]
        values = next(iter(projected.values()))
        return float(values[0]), float(values[1]), float(values[2])
    except (KeyError, TypeError, ValueError, StopIteration, IndexError):
        return None


def league_average_totals(matchups: list[Matchup], categories: list[Category]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for cat in categories:
        values = [
            v for m in matchups for line in (m.away, m.home) if (v := line.totals.get(cat.key)) is not None
        ]
        out[cat.key] = sum(values) / len(values) if values else None
    return out
