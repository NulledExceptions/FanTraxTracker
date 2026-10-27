from __future__ import annotations

import datetime as dt
from typing import Any

from fantrax_analytics.analytics.available import attach_schedule, help_by_category, merge_pools
from fantrax_analytics.analytics.categories import format_value, make_category, parse_number
from fantrax_analytics.analytics.matchup import (
    category_edges,
    fantrax_projected_wlt,
    my_matchup,
    parse_period_matchups,
    period_categories,
    period_table,
)
from fantrax_analytics.analytics.projection import compare_projections, project_team, projected_record
from fantrax_analytics.analytics.roster import parse_roster
from fantrax_analytics.analytics.schedule import games_outlook, parse_games_played_limits, parse_schedule
from fantrax_analytics.reports.dashboard import build_dashboard, period_game_dates, repair_mojibake
from fantrax_analytics.reports.html import render
from fantrax_analytics.reports.payloads import ReportPayloads, find_opponent, projection_code
from tests.conftest import fixture

EDT = dt.timezone(dt.timedelta(hours=-4))
NOW = dt.datetime(2026, 10, 27, 9, 0, tzinfo=EDT)
ME, THEM = "tm5marc", "tm1"


def _data(name: str) -> Any:
    return fixture(name)["responses"][0]["data"]


def _roster_payload(
    rows: list[tuple[str, str, str, str, list[str]]], *, projected: bool = False
) -> dict[str, Any]:
    """rows: (id, name, team, statusId, cells[GP, FG%, 3PTM, FT%, PTS, REB, AST, ST, BLK, TO])."""
    header = {"cells": [{"key": "opponent", "shortName": "Opp"}, {"key": "3010#1350#-1", "shortName": "GP"}]}
    for key, short in (
        ("1520", "FG%"),
        ("1620", "3PTM"),
        ("1550", "FT%"),
        ("1590", "PTS"),
        ("1600", "REB"),
        ("1470", "AST"),
        ("1610", "ST"),
        ("1480", "BLK"),
        ("1650", "TO"),
    ):
        header["cells"].append({"key": f"3010#{key}#-1", "shortName": short})
    table_rows: list[dict[str, Any]] = [
        {
            "scorer": {"scorerId": pid, "name": name, "teamShortName": team, "posShortNames": "PG,G"},
            "statusId": status,
            "posId": "300",
            "cells": [{"content": "@LAL<br/>Tue 10:00PM"}, *({"content": c} for c in cells)],
        }
        for pid, name, team, status, cells in rows
    ]
    table_rows.append({"numSpotsAvailableText": "Reserve spot(s) available", "cells": []})
    code = "PROJECTION_0_41n_EVENT_PROJECTED_WEEKLY" if projected else "SEASON_41n_YEAR_TO_DATE"
    return {
        "tables": [{"scGroup": "3010", "header": header, "rows": table_rows}],
        "seasonOrProjections": [
            {"code": "PROJECTION_0_41n_EVENT_PROJECTED_WEEKLY"},
            {"code": "PROJECTION_0_41n_SEASON"},
        ],
        "displayedSelections": {"displayedSeasonOrProjection": {"code": code}},
    }


MY_ROSTER = _roster_payload(
    [
        (
            "p1",
            "Some Player",
            "CHI",
            "1",
            ["3", ".500", "2.0", ".800", "20.0", "5.0", "4.0", "1.0", "0.5", "2.0"],
        ),
        (
            "p2",
            "Other Player",
            "PHO",
            "1",
            ["3", ".450", "1.0", ".700", "10.0", "8.0", "2.0", "1.0", "1.5", "1.0"],
        ),
        (
            "p3",
            "Bench Guy",
            "CHI",
            "2",
            ["2", ".400", "0.5", ".600", "5.0", "2.0", "1.0", "0.5", "0.0", "0.5"],
        ),
    ]
)
MY_ROSTER_PROJ = _roster_payload(
    [
        (
            "p1",
            "Some Player",
            "CHI",
            "1",
            ["2", ".480", "2.5", ".820", "22.0", "5.0", "4.0", "1.0", "0.5", "2.0"],
        ),
        (
            "p2",
            "Other Player",
            "PHO",
            "1",
            ["1", ".460", "1.0", ".750", "12.0", "8.0", "2.0", "1.0", "1.5", "1.0"],
        ),
        (
            "p3",
            "Bench Guy",
            "CHI",
            "2",
            ["2", ".400", "0.5", ".600", "5.0", "2.0", "1.0", "0.5", "0.0", "0.5"],
        ),
    ],
    projected=True,
)


def test_categories_and_numbers() -> None:
    assert parse_number(".457") == 0.457
    assert parse_number("1,234") == 1234.0
    assert parse_number("W <small>(Tue)</small>") is None
    assert parse_number("") is None
    to = make_category("TO")
    assert not to.higher_is_better and to.better(10, 12) == 1
    fg = make_category("FG%", "Field Goal %")
    assert fg.is_rate and format_value(fg, 0.4567) == ".457"
    assert format_value(make_category("PTS"), 1234.0) == "1,234"


def test_matchup_from_standings_schedule() -> None:
    standings = _data("fxpa_getStandings_SCHEDULE")
    table = period_table(standings, 1)
    assert table is not None and period_table(standings, 9) is None
    cats = period_categories(table)
    assert [c.key for c in cats] == []  # the fixture table carries only W/L/T columns
    matchups = parse_period_matchups(table)
    assert len(matchups) == 1
    mine = my_matchup(matchups, ME)
    assert mine is not None and mine.side(ME) is not None
    me, them = mine.side(ME)  # type: ignore[misc]
    assert (me.wins, me.losses, me.ties) == (4.0, 5.0, 0.0) and them.team_name == "bADa bing bong blok"


def test_category_edges_direction() -> None:
    table = {
        "caption": "Scoring Period 2",
        "header": {
            "cells": [
                {"key": "win", "shortName": "W"},
                {"key": "loss", "shortName": "L"},
                {"key": "tie", "shortName": "T"},
                {"key": "cp", "shortName": "Pts"},
                {"key": "scip", "shortName": "PTS", "name": "Points"},
                {"key": "scip", "shortName": "TO", "name": "Turnovers"},
                {"key": "scip", "shortName": "FG%", "name": "Field Goal %"},
            ]
        },
        "rows": [
            {
                "matchupId": "a_b",
                "fixedCells": [{"content": "A", "teamId": ME}],
                "cells": [
                    {"content": "2"},
                    {"content": "1"},
                    {"content": "0"},
                    {"content": "2"},
                    {"content": "100"},
                    {"content": "10"},
                    {"content": ".500"},
                ],
            },
            {
                "matchupId": "a_b",
                "fixedCells": [{"content": "B", "teamId": THEM}],
                "cells": [
                    {"content": "1"},
                    {"content": "2"},
                    {"content": "0"},
                    {"content": "1"},
                    {"content": "80"},
                    {"content": "12"},
                    {"content": ".500"},
                ],
            },
        ],
    }
    cats = period_categories(table)
    matchup = parse_period_matchups(table)[0]
    edges = {e.category.key: e for e in category_edges(matchup, ME, cats)}
    assert (
        edges["PTS"].leader == "me"
        and edges["PTS"].margin == 20
        and round(edges["PTS"].closeness or 0, 2) == 0.2
    )
    assert edges["TO"].leader == "me" and edges["TO"].margin == 2  # fewer turnovers is a lead
    assert edges["FG%"].leader == "tie" and edges["FG%"].closeness == 0.0


def test_fantrax_projected_wlt() -> None:
    live = {
        "statsPerTeam": {
            "allTeamsStats": {ME: {"ACTIVE": {"wltPerMchupProjected": {"6|2": [6.0, 3.0, 0.0]}}}}
        }
    }
    assert fantrax_projected_wlt(live, ME) == (6.0, 3.0, 0.0)
    assert fantrax_projected_wlt({}, ME) is None


def test_roster_parse_skips_filler_rows() -> None:
    cats, players = parse_roster(MY_ROSTER, {"300": {"shortName": "PG"}})
    assert [c.key for c in cats] == ["FG%", "3PTM", "FT%", "PTS", "REB", "AST", "ST", "BLK", "TO"]
    assert [p.name for p in players] == ["Some Player", "Other Player", "Bench Guy"]
    assert players[0].slot == "PG" and players[0].games == 3 and players[0].per_game["PTS"] == 20.0
    assert players[2].status == "reserve" and players[0].next_game == "@LAL Tue 10:00PM"
    assert projection_code(MY_ROSTER) == "PROJECTION_0_41n_EVENT_PROJECTED_WEEKLY"


def test_schedule_and_games_outlook() -> None:
    grid = _data("fxpa_getTeamRosterInfo_SCHEDULE_FULL")
    schedule = parse_schedule(grid, dt.date(2026, 10, 26))
    assert (
        schedule["CHI"][dt.date(2026, 10, 26)].final
        and schedule["CHI"][dt.date(2026, 10, 26)].opponent == "DET"
    )
    wed = schedule["CHI"][dt.date(2026, 10, 28)]
    assert wed.opponent == "MIL" and wed.home and not wed.final and wed.event_id == "e2"
    assert (
        schedule["PHO"][dt.date(2026, 10, 27)].opponent == "LAL"
        and not schedule["PHO"][dt.date(2026, 10, 27)].home
    )

    _, players = parse_roster(MY_ROSTER)
    dates = [dt.date(2026, 10, 26) + dt.timedelta(days=i) for i in range(7)]
    outlook = games_outlook(
        players,
        schedule,
        period_dates=dates,
        today=dt.date(2026, 10, 27),
        active_slots=1,
        played=7,
        max_games=42,
    )
    assert [d.count for d in outlook.days] == [
        1,
        1,
        0,
        0,
        0,
        0,
    ]  # Tue PHO, Wed CHI (finished Mon game excluded)
    assert outlook.remaining_by_player == {"p1": 1, "p2": 1, "p3": 1}
    assert outlook.active_remaining == 2 and outlook.usable_remaining == 2
    assert outlook.projected_total == 9 and outlook.slack == 33

    games_per_pos = {
        "scMinMaxData": {
            "tableData": [
                {"scoringCategory": "Games Played (GP)", "total": "7", "max": "42", "min": "No min"},
                {
                    "scoringCategory": "Field Goals Attempted (FGA)",
                    "total": "122",
                    "max": "No max",
                    "min": "50",
                },
            ]
        }
    }
    assert parse_games_played_limits(games_per_pos) == (7, 42)
    assert parse_games_played_limits(
        {
            "scMinMaxData": {
                "tableData": [{"scoringCategory": "Games Played (GP)", "total": "7", "max": "No max"}]
            }
        }
    ) == (7, None)


def test_projection_arithmetic() -> None:
    cats, proj_players = parse_roster(MY_ROSTER_PROJ)
    totals_now = {
        "PTS": 100.0,
        "TO": 10.0,
        "FG%": 0.500,
        "3PTM": 5.0,
        "FT%": 0.8,
        "REB": 1.0,
        "AST": 1.0,
        "ST": 1.0,
        "BLK": 1.0,
    }
    mine = project_team(
        totals_now, proj_players, cats, games_played=4, remaining_by_player={"p1": 2, "p2": 1, "p3": 5}
    )
    # counting: 100 + 22*2 + 12*1 = 156 (bench p3 ignored)
    assert mine.totals_projected["PTS"] == 156.0 and mine.games_remaining == 3
    # rate: (0.5*4 + (0.48*2 + 0.46*1)/3 * 3) / 7
    assert round(mine.totals_projected["FG%"] or 0, 4) == round((0.5 * 4 + 0.48 * 2 + 0.46) / 7, 4)
    theirs = project_team(
        {"PTS": 140.0, "TO": 8.0, "FG%": 0.470}, [], cats, games_played=4, remaining_by_player=None
    )
    assert theirs.totals_projected["PTS"] == 140.0 and theirs.totals_projected["FG%"] == 0.470
    cmp = {p.category.key: p.leader_projected for p in compare_projections(mine, theirs, cats)}
    assert cmp["PTS"] == "me" and cmp["TO"] == "them" and cmp["REB"] == "unknown"
    assert projected_record(compare_projections(mine, theirs, cats)) == (2, 1, 0)


def _pool_payload(rows: list[tuple[str, str, str, str, list[str]]]) -> dict[str, Any]:
    cells = [
        {"key": "rankOv", "shortName": "Rk"},
        {"key": "status", "shortName": "Sta"},
        {"key": "opponent", "shortName": "Opp"},
        {"key": "score", "shortName": "Score"},
        {"shortName": "Ros"},
        {"shortName": "+/-"},
    ]
    for key, short in (
        ("1520", "FG%"),
        ("1620", "3PTM"),
        ("1550", "FT%"),
        ("1590", "PTS"),
        ("1600", "REB"),
        ("1470", "AST"),
        ("1610", "ST"),
        ("1480", "BLK"),
        ("1650", "TO"),
    ):
        cells.append({"key": f"3010#{key}#-1", "shortName": short})
    return {
        "tableHeader": {"cells": cells},
        "statsTable": [
            {
                "scorer": {"scorerId": pid, "name": name, "teamShortName": team, "posShortNames": "SF"},
                "cells": [
                    {"content": "1"},
                    {"content": status},
                    {"content": ""},
                    {"content": "50.1"},
                    {"content": "40%"},
                    {"content": "+1%"},
                    *({"content": c} for c in stats),
                ],
            }
            for pid, name, team, status, stats in rows
        ],
    }


def test_available_players_ranked_by_impact() -> None:
    ytd = _pool_payload(
        [
            (
                "f1",
                "Three Guy",
                "PHO",
                "FA",
                [".400", "3.0", ".800", "12.0", "3.0", "1.0", "1.0", "0.2", "1.0"],
            ),
            (
                "f2",
                "Board Guy",
                "CHI",
                "W <small>(Tue)</small>",
                [".550", "0.5", ".600", "9.0", "10.0", "1.0", "0.5", "1.5", "1.5"],
            ),
            (
                "f3",
                "No Games",
                "BOS",
                "FA",
                [".600", "2.0", ".900", "20.0", "5.0", "5.0", "2.0", "1.0", "2.0"],
            ),
        ]
    )
    proj = _pool_payload(
        [("f1", "Three Guy", "PHO", "FA", [".420", "2.5", ".810", "13.0", "3.0", "1.0", "1.0", "0.2", "1.0"])]
    )
    cats, players = merge_pools([ytd], [proj])
    assert len(players) == 3 and players[0].projected["3PTM"] == 2.5 and players[1].projected == {}
    schedule = parse_schedule(_data("fxpa_getTeamRosterInfo_SCHEDULE_FULL"), dt.date(2026, 10, 26))
    attach_schedule(players, schedule, [dt.date(2026, 10, 27), dt.date(2026, 10, 28)])
    assert (
        players[0].games_remaining == 1
        and players[1].games_remaining == 1
        and players[2].games_remaining == 0
    )
    assert players[1].availability == "W (Tue)"
    helps = {h.category.key: h for h in help_by_category(players, cats, top_n=5)}
    assert [c.player.name for c in helps["3PTM"].candidates] == ["Three Guy", "Board Guy"]
    assert helps["3PTM"].candidates[0].per_game == 2.5  # projected wins over YTD
    assert [c.player.name for c in helps["TO"].candidates] == ["Three Guy", "Board Guy"]  # fewer is better
    assert [c.player.name for c in helps["FG%"].candidates] == ["Board Guy", "Three Guy"]
    assert all(c.player.name != "No Games" for h in helps.values() for c in h.candidates)


def test_dashboard_builds_and_renders() -> None:
    league_info = fixture("getLeagueInfo")
    league_info["matchups"] = [{"period": 2, "matchupList": [{"away": {"id": ME}, "home": {"id": THEM}}]}]
    league_info["rosterInfo"]["maxTotalActivePlayers"] = 2
    live = _data("fxpa_getLiveScoringStats")
    live["statsPerTeam"]["allTeamsStats"][ME] = {"ACTIVE": {"wltPerMchupProjected": {"x": [5.0, 4.0, 0.0]}}}
    standings = _data("fxpa_getStandings_SCHEDULE")
    standings["tableList"][0]["caption"] = "Scoring Period 2"
    payloads = ReportPayloads(
        payloads={
            "league_info": league_info,
            "matchups_current": live,
            "fx_matchup_results": standings,
            "fx_my_roster_stats": MY_ROSTER,
            "fx_my_roster_proj": MY_ROSTER_PROJ,
            "fx_league_roster_schedules": {ME: _data("fxpa_getTeamRosterInfo_SCHEDULE_FULL")},
            "fx_my_roster_games_per_pos": {
                "scMinMaxData": {
                    "tableData": [{"scoringCategory": "Games Played (GP)", "total": "3", "max": "42"}]
                }
            },
            "fx_player_pool_season_p1": _pool_payload(
                [
                    (
                        "f1",
                        "Three Guy",
                        "PHO",
                        "FA",
                        [".400", "3.0", ".800", "12.0", "3.0", "1.0", "1.0", "0.2", "1.0"],
                    )
                ]
            ),
            "_period": 2,
            "_opponent": THEM,
            "_bounds": (dt.date(2026, 10, 26), dt.date(2026, 11, 2)),
        }
    )
    assert find_opponent(league_info, 2, ME) == THEM
    assert period_game_dates(live, 2, (dt.date(2026, 10, 26), dt.date(2026, 11, 2)))[-1] == dt.date(
        2026, 11, 1
    )
    assert period_game_dates({}, 2, (dt.date(2026, 10, 26), dt.date(2026, 11, 2)))[-1] == dt.date(2026, 11, 1)

    dash = build_dashboard(payloads, my_team_id=ME, now=NOW)
    assert dash.opponent_name == "bADa bing bong blok" and dash.period == 2
    assert dash.fantrax_projected_wlt == (5.0, 4.0, 0.0)
    assert dash.outlook is not None and dash.outlook.played == 3 and dash.outlook.max_games == 42
    assert dash.matchup is not None and dash.categories  # categories fall back to the roster header
    assert len(dash.available) == 1 and dash.available[0].games_remaining == 1
    html = render(dash)
    assert "<!doctype html>" in html and "Current matchup" in html and "Three Guy" in html
    assert "Some Player" in html and "Games this period" in html and "prefers-color-scheme: dark" in html


def test_repair_mojibake() -> None:
    assert repair_mojibake("The Rollinâ\u0080\u0099 Treys") == "The Rollin\u2019 Treys"
    assert repair_mojibake("plain") == "plain"
