"""Phase 0: endpoint discovery against the real league.

Runs a fixed, ordered list of probes (official API first, then the undocumented fxpa
fallback at escalating auth levels), saves every raw payload under ``discovery/``, and
writes ``discovery/ENDPOINT_REPORT.md``. It never designs anything: its job is to tell us
what is reachable, from where, with what auth, and in what shape.

The command is permanent — rerun it whenever Fantrax changes something.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from fantrax_analytics.adapters.auth import ClientFactory
from fantrax_analytics.adapters.fxpa import LIBRARY_EQUIVALENTS, FxpaClient
from fantrax_analytics.adapters.http import AuthLevel, RawResponse
from fantrax_analytics.adapters.official import OfficialApiClient
from fantrax_analytics.config import Settings, write_env_var
from fantrax_analytics.exceptions import AuthError, ConfigError, EdgeRejectedError, FantraxError
from fantrax_analytics.logging_setup import get_logger

log = get_logger(__name__)

Status = Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE", "SKIPPED"]
Priority = Literal["high", "low"]

SAMPLE_MAX_CHARS = 1200
KEY_SCAN_MAX_DEPTH = 6
KEY_SCAN_MAX_ITEMS = 25  # per list — enough to see the shape without walking 2k players

# Fantrax NBA team abbreviations as they appear in getPlayerIds / roster rows (note GS, NO, NY, SA,
# PHO, BKN rather than the NBA.com tricodes). Used only to measure schedule coverage.
FANTRAX_NBA_TEAMS: frozenset[str] = frozenset(
    {
        *("ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GS"),
        *("HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NO", "NY"),
        *("OKC", "ORL", "PHI", "PHO", "POR", "SA", "SAC", "TOR", "UTA", "WAS"),
    }
)
_SCHED_TEAM_RE = re.compile(r"@?\b([A-Z]{2,3})\b")


# ----------------------------------------------------------------------------- helpers
def collect_keys(payload: Any, *, depth: int = 0, acc: set[str] | None = None) -> set[str]:
    """All dict keys reachable in ``payload`` (bounded depth/width)."""
    keys: set[str] = set() if acc is None else acc
    if depth > KEY_SCAN_MAX_DEPTH:
        return keys
    if isinstance(payload, dict):
        for k, v in payload.items():
            keys.add(str(k))
            collect_keys(v, depth=depth + 1, acc=keys)
    elif isinstance(payload, list):
        for item in payload[:KEY_SCAN_MAX_ITEMS]:
            collect_keys(item, depth=depth + 1, acc=keys)
    return keys


def match_expected(keys: Iterable[str], expected: Sequence[str]) -> tuple[list[str], list[str]]:
    lowered = [k.lower() for k in keys]
    found = [e for e in expected if any(e.lower() in k for k in lowered)]
    missing = [e for e in expected if e not in found]
    return found, missing


def first_record(payload: Any) -> Any:
    """Best-effort 'first interesting record' for the report."""
    if isinstance(payload, list):
        return payload[0] if payload else None
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value[0]
            if isinstance(value, dict):
                nested = first_record(value)
                if isinstance(nested, dict):
                    return nested
        return {k: v for k, v in payload.items() if not isinstance(v, (dict, list))}
    return payload


def truncate_json(value: Any, limit: int = SAMPLE_MAX_CHARS) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"... (+{len(text) - limit} chars)"


def top_level_keys(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        return [str(k) for k in payload]
    if isinstance(payload, list):
        return [f"<list of {len(payload)}>"]
    return [f"<{type(payload).__name__}>"]


def find_dict_containing(payload: Any, *, value: str, depth: int = 0) -> dict[str, Any] | None:
    """Depth-first search for the first dict that has ``value`` among its values."""
    if depth > KEY_SCAN_MAX_DEPTH:
        return None
    if isinstance(payload, dict):
        if any(v == value for v in payload.values()):
            return payload
        for v in payload.values():
            hit = find_dict_containing(v, value=value, depth=depth + 1)
            if hit is not None:
                return hit
    elif isinstance(payload, list):
        for item in payload:
            hit = find_dict_containing(item, value=value, depth=depth + 1)
            if hit is not None:
                return hit
    return None


def _pick_key(record: dict[str, Any], *needles: str) -> Any:
    """Value of the first key whose lowercase name contains all needles."""
    for k, v in record.items():
        lk = k.lower()
        if all(n in lk for n in needles):
            return v
    return None


When = dt.datetime | dt.date


def _parse_when(value: Any) -> When | None:
    """Parse a Fantrax period bound.

    The real ``getLeagueInfo`` payload uses instants with a UTC offset
    (``2026-10-26T18:59:59.0-0400``): period 1 *ends* at 18:59:59 on the 26th and period 2
    *starts* at 19:00:00 on the same day, so comparing calendar dates picks the wrong period on
    every boundary day. Offset-bearing strings therefore come back as aware datetimes; date-only
    strings come back as dates.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    for fmt, width in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10), ("%m/%d/%Y", 10)):
        try:
            return dt.datetime.strptime(text[:width], fmt).date()
        except ValueError:
            continue
    return None


def _as_aware(now: When) -> dt.datetime:
    """Normalise ``now`` to an aware datetime (plain dates → local noon, naive → local time)."""
    if not isinstance(now, dt.datetime):
        now = dt.datetime.combine(now, dt.time(12))
    return now if now.tzinfo is not None else now.astimezone()


def _contains(start: When, end: When, now: dt.datetime) -> bool:
    if isinstance(start, dt.datetime) and isinstance(end, dt.datetime):
        return start <= now <= end
    start_date = start.date() if isinstance(start, dt.datetime) else start
    end_date = end.date() if isinstance(end, dt.datetime) else end
    return start_date <= now.astimezone().date() <= end_date


def _iter_periods(league_info: Any, kind: Literal["scoring", "roster"]) -> Iterable[dict[str, Any]]:
    if not isinstance(league_info, dict):
        return
    for k, v in league_info.items():
        if kind not in k.lower() or "period" not in k.lower():
            continue
        entries = list(v.values()) if isinstance(v, dict) else v if isinstance(v, list) else []
        for entry in entries:
            if isinstance(entry, dict):
                yield entry


def _period_number(entry: dict[str, Any]) -> int | None:
    number = _pick_key(entry, "number") or _pick_key(entry, "period") or entry.get("id")
    try:
        return int(number) if number is not None else None
    except (TypeError, ValueError):
        return None


def derive_current_period(league_info: Any, kind: Literal["scoring", "roster"], now: When) -> int | None:
    """Number of the ``kind`` period whose bounds contain ``now`` (an instant, not a date)."""
    instant = _as_aware(now)
    for entry in _iter_periods(league_info, kind):
        start = _parse_when(_pick_key(entry, "start"))
        end = _parse_when(_pick_key(entry, "end"))
        number = _period_number(entry)
        if start and end and number is not None and _contains(start, end, instant):
            return number
    return None


def period_bounds(
    league_info: Any, kind: Literal["scoring", "roster"], number: int
) -> tuple[dt.date, dt.date] | None:
    """Local calendar dates (first, last) spanned by period ``number``."""
    for entry in _iter_periods(league_info, kind):
        if _period_number(entry) != number:
            continue
        start = _parse_when(_pick_key(entry, "start"))
        end = _parse_when(_pick_key(entry, "end"))
        if start is None or end is None:
            return None
        first = start.astimezone().date() if isinstance(start, dt.datetime) else start
        last = end.astimezone().date() if isinstance(end, dt.datetime) else end
        return first, last
    return None


def _non_member_view(payload: Any) -> str | None:
    """Escalation trigger for ``getFantasyLeagueInfo``: Fantrax served the public view."""
    settings = payload.get("fantasySettings") if isinstance(payload, dict) else None
    if isinstance(settings, dict) and settings.get("isMember") is False:
        return "isMember=false — Fantrax served the public (non-member) view"
    return None


def schedule_coverage(payload: Any) -> dict[str, Any]:
    """Summarise one or more ``getTeamRosterInfo`` SCHEDULE_FULL payloads.

    Accepts a single payload or a ``{fantasy_team_id: payload}`` bundle. Every row is one
    rostered player with their NBA team (``scorer.teamShortName``) and one cell per game date
    (``sched_<m>/<d>`` header keys) holding the opponent, tip-off and ``eventId``. NBA teams
    rostered anywhere in the league are *directly* covered (every one of their games is in the
    grid); teams that only appear as opponents are *seen* (games between two unrostered teams
    would be missing).
    """
    bundles = list(payload.values()) if isinstance(payload, dict) and "tables" not in payload else [payload]
    dates: dict[str, None] = {}
    direct: set[str] = set()
    seen: set[str] = set()
    players = 0
    for bundle in bundles:
        tables = bundle.get("tables") if isinstance(bundle, dict) else None
        for table in tables if isinstance(tables, list) else []:
            if not isinstance(table, dict):
                continue
            header = table.get("header") or {}
            for cell in header.get("cells", []) if isinstance(header, dict) else []:
                key = str(cell.get("key", "")) if isinstance(cell, dict) else ""
                if key.startswith("sched_"):
                    dates[key.removeprefix("sched_")] = None
            for row in table.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                scorer = row.get("scorer") or {}
                team = scorer.get("teamShortName") if isinstance(scorer, dict) else None
                if isinstance(team, str) and team in FANTRAX_NBA_TEAMS:
                    direct.add(team)
                    players += 1
                for cell in row.get("cells") or []:
                    content = cell.get("content") if isinstance(cell, dict) else None
                    if isinstance(content, str):
                        seen.update(t for t in _SCHED_TEAM_RE.findall(content) if t in FANTRAX_NBA_TEAMS)
    seen |= direct
    return {
        "players": players,
        "dates": list(dates),
        "teams_direct": sorted(direct),
        "teams_seen": sorted(seen),
        "teams_missing": sorted(FANTRAX_NBA_TEAMS - direct),
    }


# ------------------------------------------------------------------------------- model
@dataclass
class ProbeSpec:
    domain: str
    description: str
    source: Literal["official", "fxpa"]
    endpoint: str
    expected: tuple[str, ...]
    run: Callable[[AuthLevel], RawResponse]
    auth_levels: tuple[AuthLevel, ...] = ("none",)
    priority: Priority = "high"
    library_method: str | None = None
    enabled: bool = True
    # Returns a reason to try the next auth level even though the request succeeded (e.g. the
    # endpoint answered with a public, non-member view). The first such payload is kept as a
    # fallback if no level produces a better one.
    escalate_if: Callable[[Any], str | None] | None = None


@dataclass
class ProbeResult:
    domain: str
    description: str
    source: str
    endpoint: str
    status: Status
    priority: Priority
    auth_level: str = "-"
    auth_attempts: list[str] = field(default_factory=list)
    http_status: int | None = None
    size_bytes: int | None = None
    elapsed_ms: int | None = None
    from_cache: bool = False
    library_method: str | None = None
    top_keys: list[str] = field(default_factory=list)
    found: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    sample: str = ""
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    saved_to: str | None = None
    recommendation: str = ""


# ---------------------------------------------------------------------------- discovery
class Discovery:
    def __init__(
        self,
        settings: Settings,
        factory: ClientFactory,
        *,
        today: dt.date | None = None,
        now: dt.datetime | None = None,
        include_fallback: bool = True,
        include_low_priority: bool = True,
        only_domains: Sequence[str] | None = None,
    ) -> None:
        self.settings = settings
        self.factory = factory
        # Period boundaries are instants (19:00 ET), so "now" matters, not just the date.
        self.now = _as_aware(now if now is not None else today if today is not None else dt.datetime.now())
        self.today = self.now.astimezone().date()
        self.include_fallback = include_fallback
        self.include_low_priority = include_low_priority
        self.only_domains = set(only_domains or [])
        self.payloads: dict[str, Any] = {}
        self.results: list[ProbeResult] = []
        self.my_team_id: str | None = settings.my_team_id
        self.current_scoring_period: int | None = None
        self.current_roster_period: int | None = None
        self.out_dir = settings.discovery_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------- clients
    def official(self, level: AuthLevel) -> OfficialApiClient:
        return OfficialApiClient(self.factory.client(level))

    def fxpa(self, level: AuthLevel) -> FxpaClient:
        return FxpaClient(self.factory.client(level), self.settings.league_id)

    # ---------------------------------------------------------------- probes
    def _core_probes(self) -> list[ProbeSpec]:
        """Official-API probes plus the matchup domains, which only exist on fxpa."""
        s = self.settings
        lid = s.league_id
        league_levels: tuple[AuthLevel, ...] = ("none", "cookie")
        fx_levels: tuple[AuthLevel, ...] = ("none", "secret", "cookie")
        return [
            ProbeSpec(
                "leagues",
                "My leagues and team IDs (resolves MY_TEAM_ID)",
                "official",
                "getLeagues",
                ("league", "team"),
                lambda lvl: self.official(lvl).get_leagues(s.secret_id_value),
                auth_levels=("none",),
                enabled=bool(s.secret_id_value),
            ),
            ProbeSpec(
                "league_info",
                "Full league info incl. player pool, periods, scoring system",
                "official",
                "getLeagueInfo",
                ("scoring", "period", "team", "player", "position"),
                lambda lvl: self.official(lvl).get_league_info(lid),
                auth_levels=league_levels,
            ),
            ProbeSpec(
                "league_info_settings",
                "League info with excludePlayerInfo=true (settings-only refresh)",
                "official",
                "getLeagueInfo?excludePlayerInfo=true",
                ("scoring", "period", "team"),
                lambda lvl: self.official(lvl).get_league_info(lid, exclude_player_info=True),
                auth_levels=league_levels,
            ),
            ProbeSpec(
                "rosters_current",
                "All team rosters, current lineup period",
                "official",
                "getTeamRosters",
                ("rosters", "rosteritems", "status"),
                lambda lvl: self.official(lvl).get_team_rosters(lid),
                auth_levels=league_levels,
            ),
            ProbeSpec(
                "rosters_past",
                "All team rosters, one past lineup period",
                "official",
                "getTeamRosters?period=",
                ("rosters", "rosteritems"),
                lambda lvl: self.official(lvl).get_team_rosters(
                    lid, period=self._past(self.current_roster_period)
                ),
                auth_levels=league_levels,
            ),
            ProbeSpec(
                "standings",
                "League standings",
                "official",
                "getStandings",
                ("team",),
                lambda lvl: self.official(lvl).get_standings(lid),
                auth_levels=league_levels,
            ),
            ProbeSpec(
                "matchups_current",
                "Live matchup scores and per-player stats for today (current scoring period)",
                "fxpa",
                "getLiveScoringStats",
                ("scorerMap", "statsPerTeam", "matchupMap"),
                lambda lvl: self.fxpa(lvl).live_scoring_stats(self.today, self.current_scoring_period),
                auth_levels=fx_levels,
                library_method=LIBRARY_EQUIVALENTS.get("getLiveScoringStats"),
            ),
            ProbeSpec(
                "matchups_past",
                "Live-scoring snapshot for a date inside the previous scoring period",
                "fxpa",
                "getLiveScoringStats?period=<prev>&date=<prev first day>",
                ("scorerMap", "statsPerTeam", "matchupMap"),
                lambda lvl: self.fxpa(lvl).live_scoring_stats(*self._past_scoring_date()),
                auth_levels=fx_levels,
                library_method=LIBRARY_EQUIVALENTS.get("getLiveScoringStats"),
            ),
            ProbeSpec(
                "fx_matchup_results",
                "Category W/L/T per team for every scoring period (past matchup results)",
                "fxpa",
                "getStandings (SCHEDULE)",
                ("tableList", "matchupId", "caption"),
                lambda lvl: self.fxpa(lvl).matchup_results(),
                auth_levels=fx_levels,
                library_method=LIBRARY_EQUIVALENTS.get("getStandings"),
            ),
            ProbeSpec(
                "draft_results",
                "Draft results",
                "official",
                "getDraftResults",
                ("team", "player"),
                lambda lvl: self.official(lvl).get_draft_results(lid),
                auth_levels=league_levels,
                priority="low",
            ),
            ProbeSpec(
                "draft_picks",
                "Draft pick ownership",
                "official",
                "getDraftPicks",
                ("draftpick",),
                lambda lvl: self.official(lvl).get_draft_picks(lid),
                auth_levels=league_levels,
                priority="low",
            ),
            ProbeSpec(
                "player_ids",
                "NBA player ID crosswalk",
                "official",
                "getPlayerIds?sport=NBA",
                ("name",),
                lambda lvl: self.official(lvl).get_player_ids(s.sport),
                priority="low",
            ),
            ProbeSpec(
                "adp",
                "NBA ADP (first 25)",
                "official",
                "getAdp?sport=NBA",
                ("name", "adp"),
                lambda lvl: self.official(lvl).get_adp(s.sport, start=1, limit=25),
                priority="low",
            ),
        ]

    def _fallback_probes(self) -> list[ProbeSpec]:
        levels: tuple[AuthLevel, ...] = ("none", "secret", "cookie")

        def lib(name: str) -> str | None:
            return LIBRARY_EQUIVALENTS.get(name)

        probes = [
            ProbeSpec(
                "fx_league_info",
                "fxpa league info — member view carries transaction rules, claim budgets, days-used rule",
                "fxpa",
                "getFantasyLeagueInfo",
                ("claim", "budget"),
                lambda lvl: self.fxpa(lvl).league_info(),
                auth_levels=levels,
                library_method=lib("getFantasyLeagueInfo"),
                escalate_if=_non_member_view,
            ),
            ProbeSpec(
                "fx_league_settings",
                "League settings page — transaction rules, claim limits, FA budget (login required)",
                "fxpa",
                "getLeagueSettings",
                ("transaction", "claim"),
                lambda lvl: self.fxpa(lvl).league_settings(),
                auth_levels=levels,
                library_method=lib("getLeagueSettings"),
            ),
            ProbeSpec(
                "fx_my_roster_stats",
                "My roster with per-player stats (view=STATS)",
                "fxpa",
                "getTeamRosterInfo",
                ("tables", "scorer", "cells"),
                lambda lvl: self.fxpa(lvl).team_roster(self._team_for_roster_probe()),
                auth_levels=levels,
                library_method=lib("getTeamRosterInfo"),
            ),
            ProbeSpec(
                "fx_my_roster_schedule",
                "My roster player schedules (view=SCHEDULE_FULL)",
                "fxpa",
                "getTeamRosterInfo (SCHEDULE_FULL)",
                ("schedule", "date"),
                lambda lvl: self.fxpa(lvl).team_roster_schedule(
                    self._team_for_roster_probe(), self.current_scoring_period
                ),
                auth_levels=levels,
                library_method=lib("getTeamRosterInfo"),
            ),
            ProbeSpec(
                "fx_league_roster_schedules",
                "SCHEDULE_FULL grid for every fantasy team — the league-wide NBA schedule source",
                "fxpa",
                "getTeamRosterInfo (SCHEDULE_FULL) x all teams",
                ("tables", "rows", "scorer"),
                self._all_roster_schedules,
                auth_levels=levels,
                library_method=lib("getTeamRosterInfo"),
            ),
            ProbeSpec(
                "fx_my_roster_games_per_pos",
                "Games played and limits by roster position (view=GAMES_PER_POS)",
                "fxpa",
                "getTeamRosterInfo (GAMES_PER_POS)",
                ("gameplayedperpos",),
                lambda lvl: self.fxpa(lvl).team_games_per_position(
                    self._team_for_roster_probe(), self.current_scoring_period
                ),
                auth_levels=levels,
                library_method=lib("getTeamRosterInfo"),
            ),
        ]
        for code, label in (
            ("YEAR_TO_DATE", "season"),
            ("LAST_7_DAYS", "7d"),
            ("LAST_15_DAYS", "15d"),
            ("LAST_30_DAYS", "30d"),
        ):
            probes.append(
                ProbeSpec(
                    f"fx_player_pool_{label}",
                    f"Available players with {label} stats",
                    "fxpa",
                    f"getPlayerStats (ALL_AVAILABLE, {code})",
                    ("player", "stat"),
                    self._pool_probe(code),
                    auth_levels=levels,
                    library_method=lib("getPlayerStats"),
                    priority="high" if label == "season" else "low",
                )
            )
        probes += [
            ProbeSpec(
                "fx_transactions",
                "Transaction history (adds/drops/trades/claims)",
                "fxpa",
                "getTransactionDetailsHistory",
                ("transaction",),
                lambda lvl: self.fxpa(lvl).transactions(),
                auth_levels=levels,
                library_method=lib("getTransactionDetailsHistory"),
            ),
            ProbeSpec(
                "fx_pending_transactions",
                "Pending transactions / claims",
                "fxpa",
                "getPendingTransactions",
                ("transaction",),
                lambda lvl: self.fxpa(lvl).pending_transactions(),
                auth_levels=levels,
                library_method=lib("getPendingTransactions"),
                priority="low",
            ),
        ]
        return probes

    def _pool_probe(self, timeframe: str) -> Callable[[AuthLevel], RawResponse]:
        def run(level: AuthLevel) -> RawResponse:
            return self.fxpa(level).player_stats(timeframe=timeframe)

        return run

    def _past(self, current: int | None) -> int:
        return max(1, current - 1) if current else 1

    def _past_scoring_date(self) -> tuple[dt.date, int]:
        """(first day, number) of the previous scoring period, falling back to a week ago."""
        previous = self._past(self.current_scoring_period)
        bounds = period_bounds(self.payloads.get("league_info"), "scoring", previous)
        first_day = bounds[0] if bounds else self.today - dt.timedelta(days=7)
        return first_day, previous

    def _fantasy_team_ids(self) -> list[str]:
        info = self.payloads.get("league_info") or self.payloads.get("league_info_settings")
        teams = info.get("teamInfo") if isinstance(info, dict) else None
        if isinstance(teams, dict) and teams:
            return [str(k) for k in teams]
        if self.my_team_id:
            return [self.my_team_id]
        raise ConfigError("no fantasy team ids known (getLeagueInfo not fetched); skipping")

    def _all_roster_schedules(self, level: AuthLevel) -> RawResponse:
        """One SCHEDULE_FULL request per fantasy team, bundled as ``{team_id: payload}``."""
        client = self.fxpa(level)
        bundle: dict[str, Any] = {}
        first: RawResponse | None = None
        size = elapsed = 0
        for team_id in self._fantasy_team_ids():
            raw = client.team_roster_schedule(team_id, self.current_scoring_period)
            first = first or raw
            bundle[team_id] = raw.payload
            size += raw.size_bytes
            elapsed += raw.elapsed_ms
        assert first is not None
        return replace(
            first,
            endpoint=f"fxpa:getTeamRosterInfo(SCHEDULE_FULL) x{len(bundle)}",
            payload=bundle,
            size_bytes=size,
            elapsed_ms=elapsed,
            from_cache=False,
        )

    def _team_for_roster_probe(self) -> str:
        if self.my_team_id:
            return self.my_team_id
        raise ConfigError("MY_TEAM_ID unknown and could not be resolved; skipping roster-stats probe")

    # ------------------------------------------------------------------- run
    def run(self) -> list[ProbeResult]:
        probes = self._core_probes()
        if self.include_fallback:
            probes += self._fallback_probes()
        for spec in probes:
            if self.only_domains and spec.domain not in self.only_domains:
                continue
            if spec.priority == "low" and not self.include_low_priority:
                continue
            result = self._run_probe(spec)
            self.results.append(result)
            self._post_process(spec.domain)
        self.results += self._derived_checks()
        return self.results

    def _run_probe(self, spec: ProbeSpec) -> ProbeResult:
        result = ProbeResult(
            domain=spec.domain,
            description=spec.description,
            source=spec.source,
            endpoint=spec.endpoint,
            status="SKIPPED",
            priority=spec.priority,
            library_method=spec.library_method,
        )
        if not spec.enabled:
            result.notes.append("skipped: missing prerequisite (set FANTRAX_USER_SECRET_ID?)")
            return result

        last_error: Exception | None = None
        fallback: tuple[RawResponse, AuthLevel] | None = None
        for level in spec.auth_levels:
            result.auth_attempts.append(level)
            log.info("discover.probe", domain=spec.domain, auth_level=level)
            try:
                raw = spec.run(level)
            except AuthError as exc:
                last_error = exc
                result.notes.append(f"{level}: auth rejected — {exc}")
                continue
            except ConfigError as exc:
                last_error = exc
                result.notes.append(f"{level}: not testable — {exc}")
                continue
            except EdgeRejectedError as exc:
                last_error = exc
                result.notes.append(f"{level}: EDGE REJECTED — {exc}")
                break  # credentials won't fix a 1010
            except FantraxError as exc:
                last_error = exc
                result.notes.append(f"{level}: {exc.__class__.__name__}: {exc}")
                break
            except Exception as exc:
                last_error = exc
                result.notes.append(f"{level}: unexpected {exc.__class__.__name__}: {exc}")
                log.exception("discover.probe_crashed", domain=spec.domain)
                break
            reason = spec.escalate_if(raw.payload) if spec.escalate_if else None
            if reason is None:
                self._record_success(spec, result, raw, level)
                return result
            result.notes.append(f"{level}: {reason}")
            fallback = fallback or (raw, level)

        cookie_untested = any(a.startswith("cookie: not testable") for a in result.notes)
        if fallback is not None:
            raw, level = fallback
            self._record_success(spec, result, raw, level)
            result.notes.append("kept the best payload seen; no auth level produced the member view")
            if cookie_untested:
                result.recommendation = (
                    "Export fantrax.com cookies to the cookie file and rerun to test the member view"
                )
            return result

        result.status = "UNAVAILABLE"
        result.error = repr(last_error) if last_error else "no auth level succeeded"
        if cookie_untested:
            result.recommendation = (
                "Rejected at none/secret; cookie level untested — export cookies and rerun"
            )
        return result

    def _record_success(
        self, spec: ProbeSpec, result: ProbeResult, raw: RawResponse, level: AuthLevel
    ) -> None:
        self.payloads[spec.domain] = raw.payload
        keys = collect_keys(raw.payload)
        found, missing = match_expected(keys, spec.expected)
        result.auth_level = level
        result.http_status = raw.status_code
        result.size_bytes = raw.size_bytes
        result.elapsed_ms = raw.elapsed_ms
        result.from_cache = raw.from_cache
        result.top_keys = top_level_keys(raw.payload)
        result.found = found
        result.missing = missing
        result.sample = truncate_json(first_record(raw.payload))
        if raw.payload in (None, {}, []):
            result.status = "UNAVAILABLE"
            result.notes.append("empty payload")
        elif missing:
            result.status = "PARTIAL"
            result.notes.append(f"expected key fragments not seen: {missing}")
        else:
            result.status = "AVAILABLE"
        if any(k.lower() in ("pagetoken", "nextpage", "hasmore", "totalpages", "pagenumber") for k in keys):
            result.notes.append("looks paginated")
        result.saved_to = self._save(spec.domain, raw)

    def _save(self, domain: str, raw: RawResponse) -> str:
        path = self.out_dir / f"{domain}.json"
        meta = {k: v for k, v in asdict(raw).items() if k != "payload"}
        meta["fetched_at"] = dt.datetime.now(dt.UTC).isoformat()
        path.write_text(json.dumps({"meta": meta, "payload": raw.payload}, indent=1, default=str), "utf-8")
        return str(path)

    # ---------------------------------------------------------- post-process
    def _post_process(self, domain: str) -> None:
        if domain == "leagues":
            self._resolve_team_from_leagues()
        elif domain == "league_info":
            info = self.payloads.get(domain)
            self.current_scoring_period = derive_current_period(info, "scoring", self.now)
            self.current_roster_period = derive_current_period(info, "roster", self.now)
            log.info(
                "discover.periods",
                scoring=self.current_scoring_period,
                roster=self.current_roster_period,
            )
            if not self.my_team_id:
                self._resolve_team_from_league_info(info)

    def _resolve_team_from_leagues(self) -> None:
        payload = self.payloads.get("leagues")
        entry = find_dict_containing(payload, value=self.settings.league_id)
        if entry is None:
            log.warning("discover.team_id_unresolved", reason="league id not found in getLeagues")
            return
        team_id = _pick_key(entry, "team", "id")
        team_name = _pick_key(entry, "team", "name")
        if team_id:
            self._set_team_id(str(team_id), str(team_name) if team_name else None, "getLeagues")

    def _resolve_team_from_league_info(self, info: Any) -> None:
        wanted = self.settings.my_team_name.strip().lower()
        if not wanted:
            return
        for record in self._iter_dicts(info):
            name = _pick_key(record, "name")
            if isinstance(name, str) and name.strip().lower() == wanted:
                team_id = _pick_key(record, "id")
                if team_id:
                    self._set_team_id(str(team_id), name, "getLeagueInfo (matched team name)")
                    return

    def _iter_dicts(self, payload: Any, depth: int = 0) -> Iterable[dict[str, Any]]:
        if depth > KEY_SCAN_MAX_DEPTH:
            return
        if isinstance(payload, dict):
            yield payload
            for v in payload.values():
                yield from self._iter_dicts(v, depth + 1)
        elif isinstance(payload, list):
            for item in payload:
                yield from self._iter_dicts(item, depth + 1)

    def _set_team_id(self, team_id: str, team_name: str | None, how: str) -> None:
        self.my_team_id = team_id
        log.info("discover.team_id_resolved", team_id=team_id, team_name=team_name, via=how)
        if self.settings.my_team_id != team_id:
            write_env_var(self.settings.env_file, "FANTRAX_MY_TEAM_ID", team_id)
            log.info("discover.env_updated", key="FANTRAX_MY_TEAM_ID", file=str(self.settings.env_file))

    # ---------------------------------------------------------- derived checks
    def _derived_checks(self) -> list[ProbeResult]:
        """Checks that need no new request — they inspect what was already fetched."""
        return [*self._schedule_checks(), *self._generic_derived_checks()]

    COOKIE_RECOMMENDATION = (
        "Needs a logged-in session: fxpa getLeagueSettings answers WARNING_NOT_LOGGED_IN and "
        "getFantasyLeagueInfo serves the public view (isMember=false) without cookies, and the "
        "official API carries no transaction settings. Export fantrax.com cookies to the cookie "
        "file (see README) and rerun; if that works, build the Selenium `auth` command."
    )

    def _generic_derived_checks(self) -> list[ProbeResult]:
        checks: list[tuple[str, str, Sequence[str], tuple[str, ...], str]] = [
            (
                "game_limits",
                "Per-position games played and configured maximums",
                ("fx_my_roster_games_per_pos",),
                ("gameplayedperpos", "max"),
                "Read the max column in the GAMES_PER_POS payload; this league may report No max.",
            ),
            (
                "transaction_rules",
                "Claim limits, FA/WW budget, and days-used rule",
                ("league_info", "league_info_settings", "fx_league_info", "fx_league_settings"),
                ("claim", "budget", "waiver", "faab", "daysused"),
                self.COOKIE_RECOMMENDATION,
            ),
            (
                "player_pool_availability",
                "Does the official player pool mark FA/waiver status and carry stats?",
                ("league_info",),
                ("status", "team", "stat", "available", "waiver"),
                "If no status/stats: the FA pool must come from fxpa getPlayerStats.",
            ),
        ]
        out: list[ProbeResult] = []
        for domain, desc, sources, needles, rec in checks:
            available_sources = [s for s in sources if s in self.payloads]
            result = self._derived_result(domain, desc, sources, rec)
            if not available_sources:
                result.notes.append("none of the source payloads were fetched")
                out.append(result)
                continue
            keys: set[str] = set()
            for src in available_sources:
                keys |= collect_keys(self.payloads[src])
            found, missing = match_expected(keys, needles)
            result.found, result.missing = found, missing
            hits = sorted(k for k in keys if any(n in k.lower() for n in found))[:20]
            result.sample = json.dumps(hits)
            result.notes.append(f"inspected: {available_sources}")
            if not found:
                result.status = "UNAVAILABLE"
            elif len(found) >= max(2, len(needles) // 2):
                result.status = "AVAILABLE"
            else:
                result.status = "PARTIAL"
            if domain == "game_limits" and result.status == "AVAILABLE":
                result.notes.append("per-position games-played and max columns are present")
            if domain == "transaction_rules" and result.status != "AVAILABLE":
                unfetched = [s for s in sources if s not in self.payloads]
                if unfetched:
                    result.notes.append(f"not fetched (auth rejected or skipped): {unfetched}")
            out.append(result)
        return out

    @staticmethod
    def _derived_result(domain: str, desc: str, sources: Sequence[str], rec: str) -> ProbeResult:
        return ProbeResult(
            domain=domain,
            description=desc,
            source="derived",
            endpoint=f"inspects: {', '.join(sources)}",
            status="SKIPPED",
            priority="high",
            recommendation=rec,
        )

    def _schedule_checks(self) -> list[ProbeResult]:
        """NBA schedule coverage from the SCHEDULE_FULL grids (league-wide, then my roster)."""
        total = len(FANTRAX_NBA_TEAMS)
        grid_sources = ("fx_league_roster_schedules", "fx_my_roster_schedule")
        schedule = self._derived_result(
            "nba_schedule",
            "Dated NBA schedule grid (opponent, tip-off, eventId per player per date) for every NBA team",
            grid_sources,
            "Fetch SCHEDULE_FULL for every fantasy team each sync; page further ahead with period=.",
        )
        coverage: dict[str, Any] | None = None
        used = next((src for src in grid_sources if src in self.payloads), None)
        if used is None:
            schedule.notes.append("none of the source payloads were fetched")
        else:
            coverage = schedule_coverage(self.payloads[used])
            dates = coverage["dates"]
            direct, seen = len(coverage["teams_direct"]), len(coverage["teams_seen"])
            schedule.notes.append(f"inspected: {used}")
            schedule.notes.append(
                f"{coverage['players']} rostered players; {len(dates)} game dates"
                + (f" ({dates[0]} .. {dates[-1]})" if dates else "")
                + f"; NBA teams rostered {direct}/{total}, seen as opponent {seen}/{total}"
            )
            schedule.found = ["sched_ date columns", "scorer.teamShortName", "eventId"]
            schedule.missing = coverage["teams_missing"]
            schedule.sample = json.dumps(
                {k: v for k, v in coverage.items() if k != "teams_seen"} | {"dates": dates[:10]}
            )
            if not dates or direct == 0:
                schedule.status = "UNAVAILABLE"
            elif direct == total:
                schedule.status = "AVAILABLE"
                schedule.recommendation = (
                    "Every NBA team has a rostered player, so the union of all SCHEDULE_FULL grids is "
                    "the complete league schedule — no external NBA schedule source is needed."
                )
            else:
                schedule.status = "PARTIAL"
                schedule.recommendation = (
                    f"Only {direct}/{total} NBA teams are rostered: games between the "
                    f"{total - direct} unrostered teams are missing. Fetch SCHEDULE_FULL for every "
                    "fantasy team (fx_league_roster_schedules) or add an external NBA schedule."
                )

        pool = self._derived_result(
            "available_player_schedule",
            "Upcoming games for available free agents (pool rows joined to the NBA schedule by team)",
            ("fx_player_pool_season", "nba_schedule"),
            "Join each pool row's scorer.teamShortName to the nba_schedule grid for its team.",
        )
        rows = (self.payloads.get("fx_player_pool_season") or {}).get("statsTable")
        rows = rows if isinstance(rows, list) else []
        with_team = sum(
            1
            for r in rows
            if isinstance(r, dict) and isinstance(r.get("scorer"), dict) and r["scorer"].get("teamShortName")
        )
        if not rows or coverage is None:
            pool.notes.append("none of the source payloads were fetched")
        else:
            pool.notes.append(
                f"inspected: fx_player_pool_season ({with_team}/{len(rows)} rows carry an NBA team)"
            )
            pool.found = ["scorer.teamShortName"] if with_team else []
            pool.missing = [] if with_team else ["scorer.teamShortName"]
            if with_team == 0:
                pool.status = "UNAVAILABLE"
            elif schedule.status == "AVAILABLE" and with_team == len(rows):
                pool.status = "AVAILABLE"
            else:
                pool.status = "PARTIAL"
                pool.recommendation = (
                    "Pool rows name their NBA team, but the schedule grid is incomplete — see nba_schedule."
                )
        return [schedule, pool]

    # ---------------------------------------------------------------- report
    def write_report(self) -> Path:
        path = self.out_dir / "ENDPOINT_REPORT.md"
        path.write_text(self.render_report(), encoding="utf-8")
        (self.out_dir / "summary.json").write_text(
            json.dumps([asdict(r) for r in self.results], indent=1, default=str), encoding="utf-8"
        )
        return path

    def render_report(self) -> str:
        s = self.settings
        lines: list[str] = [
            "# Fantrax endpoint discovery report",
            "",
            f"- League: `{s.league_id}` — season {s.season} — sport {s.sport}",
            f"- My team ID: `{self.my_team_id or 'UNRESOLVED'}` ({s.my_team_name})",
            f"- Current scoring period: {self.current_scoring_period or 'undetermined'}; "
            f"current roster period: {self.current_roster_period or 'undetermined'} "
            f"(as of {self.now.isoformat(timespec='minutes')}; period bounds are 19:00 ET instants)",
            f"- Generated: {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')}",
            f"- Secret ID configured: {'yes' if s.secret_id_value else 'NO'}; "
            f"cookie file present: {'yes' if s.cookie_file.exists() else 'no'}",
            "",
            "## Summary",
            "",
            "| Domain | Status | Source | Endpoint | Auth | HTTP | KB | Found | Missing | Notes |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in self.results:
            kb = f"{r.size_bytes / 1024:.0f}" if r.size_bytes is not None else "-"
            lines.append(
                f"| {r.domain} | **{r.status}** | {r.source} | `{r.endpoint}` | {r.auth_level} | "
                f"{r.http_status or '-'} | {kb} | {', '.join(r.found) or '-'} | "
                f"{', '.join(r.missing) or '-'} | "
                f"{self._short_notes(r)} |"
            )

        lines += ["", "## Decisions needed", ""]
        decisions = self._decisions()
        lines += [f"- {d}" for d in decisions] or ["- None: every high-priority domain is AVAILABLE."]

        lines += ["", "## Details", ""]
        for r in self.results:
            lines += [f"### {r.domain} — {r.status}", "", f"{r.description}", ""]
            lines += [
                f"- Source: {r.source}; endpoint: `{r.endpoint}`"
                + (f"; fantraxapi equivalent: `{r.library_method}`" if r.library_method else ""),
                f"- Auth attempts: {', '.join(r.auth_attempts) or '-'}; succeeded with: {r.auth_level}",
            ]
            if r.http_status is not None:
                lines.append(
                    f"- HTTP {r.http_status}, {r.size_bytes} bytes, {r.elapsed_ms} ms"
                    + (" (from cache)" if r.from_cache else "")
                )
            if r.top_keys:
                lines.append(f"- Top-level keys: {', '.join(f'`{k}`' for k in r.top_keys[:40])}")
            if r.saved_to:
                lines.append(f"- Raw payload: `{r.saved_to}`")
            if r.notes:
                lines.append("- Notes:")
                lines += [f"  - {n}" for n in r.notes]
            if r.error:
                lines.append(f"- Error: `{r.error}`")
            if r.recommendation:
                lines.append(f"- Recommendation: {r.recommendation}")
            if r.sample:
                lines += ["", "```json", r.sample, "```"]
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _short_notes(r: ProbeResult) -> str:
        text = "; ".join(r.notes)
        text = re.sub(r"\s+", " ", text)
        return (text[:117] + "...") if len(text) > 120 else text

    def _decisions(self) -> list[str]:
        out: list[str] = []
        by = {r.domain: r for r in self.results}
        if not self.my_team_id:
            out.append("MY_TEAM_ID unresolved — set FANTRAX_MY_TEAM_ID manually from the teams list.")
        fallback = [r for r in self.results if r.source == "fxpa"]
        if fallback and all(r.status == "UNAVAILABLE" for r in fallback):
            cookie_untested = any("cookie: not testable" in n for r in fallback for n in r.notes)
            if cookie_untested:
                out.append(
                    "Every fxpa probe was rejected without a session and the cookie level is untested. "
                    "Decide: export browser cookies to test, build the Selenium `auth` command, "
                    "or drop fxpa data."
                )
            else:
                out.append(
                    "Every fxpa probe failed even with cookies — fxpa data "
                    "(player stats, FA pool, transactions) is out."
                )
        if any(r.status == "UNAVAILABLE" and "EDGE REJECTED" in " ".join(r.notes) for r in self.results):
            out.append("Edge rejection (403/1010) seen — verify FANTRAX_USER_AGENT is set and not blocked.")
        for domain in ("league_info", "rosters_current", "standings"):
            r = by.get(domain)
            if r and r.status != "AVAILABLE":
                out.append(
                    f"Core official endpoint `{domain}` is {r.status}: {r.error or '; '.join(r.notes)}"
                )
        matchup = by.get("matchups_current")
        if matchup and matchup.status != "AVAILABLE":
            out.append(
                f"Current live matchup data is {matchup.status}: {matchup.error or '; '.join(matchup.notes)}"
            )
        member_only = [
            r.endpoint
            for r in self.results
            if r.source == "fxpa"
            and r.status == "UNAVAILABLE"
            and any("auth rejected" in n for n in r.notes)
            and any("cookie: not testable" in n for n in r.notes)
        ]
        if member_only:
            out.append(
                "Member-only fxpa endpoints rejected without a session (cookie level untested): "
                + ", ".join(f"`{e}`" for e in member_only)
                + ". Export cookies to test them."
            )
        for r in self.results:
            if r.source == "derived" and r.status != "AVAILABLE":
                out.append(f"`{r.domain}` is {r.status}. {r.recommendation}")
        if self.current_scoring_period is None and "league_info" in self.payloads:
            out.append(
                "Could not derive the current scoring/roster period from getLeagueInfo — "
                "past-period probes used period=1. Check the period structure in league_info.json."
            )
        return out
