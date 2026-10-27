"""Roster rows from fxpa ``getTeamRosterInfo view=STATS`` (year-to-date or projected per game)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from fantrax_analytics.analytics.categories import Category, categories_from_header, parse_number
from fantrax_analytics.analytics.tables import cell_text, column_index, first_table, header_cells, player_rows

Status = Literal["active", "reserve", "ir"]
_STATUS: dict[str, Status] = {"1": "active", "2": "reserve", "3": "ir"}
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class RosterPlayer:
    player_id: str
    name: str
    nba_team: str
    positions: list[str]
    status: Status
    slot: str  # roster slot short name (PG, Flx, ...) when the position map is known
    games: float | None  # GP column: played so far (YTD view) or projected this period (projection view)
    per_game: dict[str, float | None] = field(default_factory=dict)
    next_game: str = ""


def parse_roster(
    payload: Any, position_map: dict[str, Any] | None = None
) -> tuple[list[Category], list[RosterPlayer]]:
    table = first_table(payload)
    if table is None:
        return [], []
    cells = header_cells(table)
    categories = categories_from_header(cells)
    cat_index = {cat.key: column_index(cells, short_name=cat.key) for cat in categories}
    gp_index = column_index(cells, short_name="GP")
    opp_index = column_index(cells, key="opponent")
    players: list[RosterPlayer] = []
    for row in player_rows(table):
        scorer = row["scorer"]
        pos_id = str(row.get("posId", ""))
        slot_info = (position_map or {}).get(pos_id) if isinstance(position_map, dict) else None
        slot = str(slot_info.get("shortName", pos_id)) if isinstance(slot_info, dict) else pos_id
        next_game = _TAG_RE.sub(" ", cell_text(row, opp_index) or "").strip()
        players.append(
            RosterPlayer(
                player_id=str(scorer.get("scorerId", "")),
                name=str(scorer.get("name", "?")),
                nba_team=str(scorer.get("teamShortName", "")),
                positions=str(scorer.get("posShortNames", "")).split(",")
                if scorer.get("posShortNames")
                else [],
                status=_STATUS.get(str(row.get("statusId")), "reserve"),
                slot=slot,
                games=parse_number(cell_text(row, gp_index)),
                per_game={cat.key: parse_number(cell_text(row, cat_index[cat.key])) for cat in categories},
                next_game=next_game,
            )
        )
    return categories, players


def active(players: list[RosterPlayer]) -> list[RosterPlayer]:
    return [p for p in players if p.status == "active"]
