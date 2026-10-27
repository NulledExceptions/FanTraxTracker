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
from dataclasses import asdict, dataclass, field
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


def _parse_date(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(value[: len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    return None


def derive_current_period(league_info: Any, kind: Literal["scoring", "roster"], today: dt.date) -> int | None:
    """Find the period whose date range contains ``today`` in a ``*Periods`` list."""
    if not isinstance(league_info, dict):
        return None
    candidates: list[Any] = []
    for k, v in league_info.items():
        if kind in k.lower() and "period" in k.lower():
            candidates.append(v)
    for container in candidates:
        entries: list[Any]
        if isinstance(container, dict):
            entries = list(container.values())
        elif isinstance(container, list):
            entries = container
        else:
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            start = _parse_date(_pick_key(entry, "start"))
            end = _parse_date(_pick_key(entry, "end"))
            number = _pick_key(entry, "number") or _pick_key(entry, "period") or entry.get("id")
            if start and end and start <= today <= end and number is not None:
                try:
                    return int(number)
                except (TypeError, ValueError):
                    return None
    return None


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
        include_fallback: bool = True,
        include_low_priority: bool = True,
        only_domains: Sequence[str] | None = None,
    ) -> None:
        self.settings = settings
        self.factory = factory
        self.today = today or dt.date.today()
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
    def _official_probes(self) -> list[ProbeSpec]:
        s = self.settings
        lid = s.league_id
        league_levels: tuple[AuthLevel, ...] = ("none", "cookie")
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
                "getLeagueInfo (POST excludePlayerInfo)",
                ("scoring", "period", "team"),
                lambda lvl: self.official(lvl).get_league_info(lid, exclude_player_info=True),
                auth_levels=league_levels,
            ),
            ProbeSpec(
                "rosters_current",
                "All team rosters, current lineup period",
                "official",
                "getTeamRosters",
                ("team", "player", "status"),
                lambda lvl: self.official(lvl).get_team_rosters(lid),
                auth_levels=league_levels,
            ),
            ProbeSpec(
                "rosters_past",
                "All team rosters, one past lineup period",
                "official",
                "getTeamRosters?period=",
                ("team", "player"),
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
                "Matchup scores incl. per-category team stats, current scoring period",
                "official",
                "getTeamStatsForMatchups",
                ("team", "stat"),
                lambda lvl: self.official(lvl).get_team_stats_for_matchups(lid),
                auth_levels=league_levels,
            ),
            ProbeSpec(
                "matchups_past",
                "Matchup scores, one past scoring period",
                "official",
                "getTeamStatsForMatchups?period=",
                ("team", "stat"),
                lambda lvl: self.official(lvl).get_team_stats_for_matchups(
                    lid, period=self._past(self.current_scoring_period)
                ),
                auth_levels=league_levels,
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
                ("team",),
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
                "fxpa league info — transaction rules, claim budgets, days-used rule",
                "fxpa",
                "getFantasyLeagueInfo",
                ("claim", "budget"),
                lambda lvl: self.fxpa(lvl).league_info(),
                auth_levels=levels,
                library_method=lib("getFantasyLeagueInfo"),
            ),
            ProbeSpec(
                "fx_my_roster_stats",
                "My roster with per-player stats (view=STATS)",
                "fxpa",
                "getTeamRosterInfo",
                ("player", "stat"),
                lambda lvl: self.fxpa(lvl).team_roster(self._team_for_roster_probe()),
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

    def _team_for_roster_probe(self) -> str:
        if self.my_team_id:
            return self.my_team_id
        raise ConfigError("MY_TEAM_ID unknown and could not be resolved; skipping roster-stats probe")

    # ------------------------------------------------------------------- run
    def run(self) -> list[ProbeResult]:
        probes = self._official_probes()
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
            self._record_success(spec, result, raw, level)
            return result

        result.status = "UNAVAILABLE"
        result.error = repr(last_error) if last_error else "no auth level succeeded"
        if any(a.startswith("cookie: not testable") for a in result.notes):
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
            self.current_scoring_period = derive_current_period(info, "scoring", self.today)
            self.current_roster_period = derive_current_period(info, "roster", self.today)
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
        checks: list[tuple[str, str, Sequence[str], tuple[str, ...], str]] = [
            (
                "nba_schedule",
                "Games remaining / games-this-period per NBA team (needed for matchup projection)",
                ("league_info", "rosters_current", "fx_my_roster_stats", "fx_player_pool_season"),
                ("gamesremaining", "numgames", "gamesthisweek", "gamesplayed", "upcominggame", "schedule"),
                "If UNAVAILABLE: source the NBA schedule from nba_api or a static schedule file.",
            ),
            (
                "transaction_rules",
                "Claim limits, FA/WW budget, days-used rule in league settings",
                ("league_info", "league_info_settings", "fx_league_info"),
                ("claim", "budget", "waiver", "faab", "daysused", "maxgames", "gameslimit"),
                "If missing: derive remaining claims from transactions; confirm days-used rule in the UI.",
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
            result = ProbeResult(
                domain=domain,
                description=desc,
                source="derived",
                endpoint=f"inspects: {', '.join(sources)}",
                status="SKIPPED",
                priority="high",
                recommendation=rec,
            )
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
            out.append(result)
        return out

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
            f"current roster period: {self.current_roster_period or 'undetermined'}",
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
        for domain in ("league_info", "rosters_current", "matchups_current", "standings"):
            r = by.get(domain)
            if r and r.status != "AVAILABLE":
                out.append(
                    f"Core official endpoint `{domain}` is {r.status}: {r.error or '; '.join(r.notes)}"
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
