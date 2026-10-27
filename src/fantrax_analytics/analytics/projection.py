"""End-of-period category projections for both sides of a matchup.

Counting categories: current period total + sum over active players (projected per-game x games
remaining). Games remaining come from the schedule grid when available, else Fantrax's projected
GP for the period. Rate categories (FG%, FT%) are a games-weighted blend of the current period
rate and the players' projected rates — an approximation, since the payloads expose no attempts
per player.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fantrax_analytics.analytics.categories import Category
from fantrax_analytics.analytics.roster import RosterPlayer


@dataclass
class TeamProjection:
    totals_now: dict[str, float | None]
    totals_projected: dict[str, float | None]
    games_played: int
    games_remaining: int


@dataclass
class CategoryProjection:
    category: Category
    mine_now: float | None
    theirs_now: float | None
    mine_projected: float | None
    theirs_projected: float | None
    leader_projected: Literal["me", "them", "tie", "unknown"]


def project_team(
    totals_now: dict[str, float | None],
    projected_players: list[RosterPlayer],
    categories: list[Category],
    *,
    games_played: int,
    remaining_by_player: dict[str, int] | None,
) -> TeamProjection:
    active = [p for p in projected_players if p.status == "active"]

    def remaining(p: RosterPlayer) -> float:
        if remaining_by_player is not None and p.player_id in remaining_by_player:
            return float(remaining_by_player[p.player_id])
        return float(p.games or 0.0)

    games_remaining = sum(remaining(p) for p in active)
    projected: dict[str, float | None] = {}
    for cat in categories:
        now = totals_now.get(cat.key)
        contributions: list[tuple[float, float]] = [
            (v, g) for p in active if (v := p.per_game.get(cat.key)) is not None and (g := remaining(p)) > 0
        ]
        if cat.is_rate:
            weight_future = sum(g for _, g in contributions)
            future_rate = sum(v * g for v, g in contributions) / weight_future if weight_future else None
            if now is None and future_rate is None:
                projected[cat.key] = None
            elif now is None or games_played <= 0:
                projected[cat.key] = future_rate
            elif future_rate is None:
                projected[cat.key] = now
            else:
                projected[cat.key] = (now * games_played + future_rate * weight_future) / (
                    games_played + weight_future
                )
        else:
            added = sum(v * g for v, g in contributions)
            projected[cat.key] = (now or 0.0) + added if (now is not None or contributions) else None
    return TeamProjection(totals_now, projected, games_played, round(games_remaining))


def compare_projections(
    mine: TeamProjection, theirs: TeamProjection, categories: list[Category]
) -> list[CategoryProjection]:
    out: list[CategoryProjection] = []
    for cat in categories:
        a, b = mine.totals_projected.get(cat.key), theirs.totals_projected.get(cat.key)
        if a is None or b is None:
            leader: Literal["me", "them", "tie", "unknown"] = "unknown"
        else:
            cmp = cat.better(a, b)
            leader = "me" if cmp > 0 else "them" if cmp < 0 else "tie"
        out.append(
            CategoryProjection(
                cat, mine.totals_now.get(cat.key), theirs.totals_now.get(cat.key), a, b, leader
            )
        )
    return out


def projected_record(projections: list[CategoryProjection]) -> tuple[int, int, int]:
    wins = sum(1 for p in projections if p.leader_projected == "me")
    losses = sum(1 for p in projections if p.leader_projected == "them")
    ties = sum(1 for p in projections if p.leader_projected == "tie")
    return wins, losses, ties
