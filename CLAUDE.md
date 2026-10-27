# CLAUDE.md — fantrax-analytics

Working conventions for this repo. Read before changing anything.

## What this is

Local analytics for one Fantrax NBA league (`fqj3m6m8murmhnko`, 2026-27, 10 teams).
Owner's team: "No Mercy, Just Usage Rate" (manager Shaqattaq1). Runs on a Mac Studio.
No cloud services, no hosted DBs, no telemetry.

## Current phase

**Phase 0 — discovery.** The only runnable command is `fantrax discover`. Do not write
schema, ingest, repository, analytics or report code until `discovery/ENDPOINT_REPORT.md`
exists for the real league and the owner has reviewed it. The report decides:

- which domains come from the official API vs `/fxpa/req`
- whether any auth beyond `User-Agent` + secret ID is needed (and therefore whether the
  Selenium `auth` command gets built at all)
- the actual JSON shapes the Pydantic models and tables are derived from
- where the NBA game schedule comes from (Fantrax field vs `nba_api` vs static file)

Build order after that: Phase 1 schema + migrations + one ingest domain end-to-end →
Phase 2 remaining domains + real sync → Phase 3 `analytics/METHODS.md` (stop for review)
→ analytics + reports. Stop and show output after each phase.

## Architecture rules (enforced by review, not tooling — don't break them)

```
adapters → models (Pydantic) → repositories → analytics → reports
```

- `adapters/` is the **only** package that performs HTTP. Nothing else imports `requests`.
- No layer imports from a layer above it.
- `models/` keeps API-shape (Pydantic) and DB-shape (SQLAlchemy) classes in separate modules.
- `repositories/` owns all SQL. No queries anywhere else.
- `analytics/` is pure functions returning dataclasses / DataFrames. No I/O.
- `ingest/` is one module per domain; each is idempotent and catches `FantraxError` at its
  boundary so one failing domain never aborts a sync.

## Data source facts (verified against `fantraxapi` 1.0.1 source and the beta API docs)

- Official API: `GET|POST https://www.fantrax.com/fxea/general/<method>`; params as query
  string or JSON body, equivalent. `User-Agent` header mandatory — missing it yields a 403
  HTML page (Cloudflare error 1010). Treat 403+HTML as `EdgeRejectedError`, not auth.
- `getLeagues` takes `userSecretId` — send it in the POST body only, never a URL.
- `getLeagueInfo` has distinct `rosterPeriods` and `scoringPeriods` with separate numbering.
  `getTeamRosters?period=` is a roster period; fxpa `getLiveScoringStats` `period=` is a
  scoring period. Never mix them. Period bounds are instants with a UTC offset
  (`2026-10-26T18:59:59.0-0400`; the next period starts 19:00 ET the same day), so resolve
  "current period" from an aware datetime, never a calendar date.
- The official API has **no** matchup method: `getTeamStatsForMatchups`, `getMatchups`,
  `getMatchupResults`, `getTeamStats`, `getScoringPeriodResults` all answer HTTP 200 with
  `{"error": {"message": "Unable to find method ..."}}`. Matchups come from fxpa:
  `getLiveScoringStats` (date + scoring period) for live/daily, `getStandings view=SCHEDULE`
  for per-period category W/L/T results.
- NBA schedule source (decided in discovery): fxpa `getTeamRosterInfo view=SCHEDULE_FULL`
  per fantasy team — a dated opponent/tip-off/`eventId` grid ~30 days ahead per rostered
  player, keyed by `scorer.teamShortName`. All 30 NBA teams are rostered across the league,
  so the union of the ten grids is complete. NBA.com's static schedule JSON 403s non-browser
  user agents; do not spoof a browser to fetch it.
- Transaction rules (claim limits, FA budget, days-used) are member-only: fxpa
  `getLeagueSettings` / `getLeagueSetup` answer `WARNING_NOT_LOGGED_IN` and
  `getFantasyLeagueInfo` serves `isMember=false` without cookies. This is the only domain
  that justifies the cookie level / Selenium `auth` command.
- `/fxpa/req`: `POST ?leagueId=<id>` with `{"msgs":[{"method": M, "data": {"leagueId":..}}]}`,
  all data values as strings. Response `responses[0].data`. `pageError.code` of
  `WARNING_NOT_LOGGED_IN` / `NOT_MEMBER_OF_LEAGUE` → `AuthError`.
- The beta API is explicitly incomplete and field names may change: tolerate unknown fields
  (log at DEBUG), raise `EndpointChangedError` on missing required ones, and keep every raw
  payload in `raw_responses`.

## Storage rules (for Phase 1)

- SQLite + SQLAlchemy 2.x + Alembic. Season is a key on every snapshot table.
- `player_stats` is long-format (player / period / stat / window); a wide view per scoring
  category is rebuilt after each sync for analytics.
- Snapshot tables are append-only with `run_id` and `fetched_at`; current-state tables are
  upserted. Document which is which in the ORM module docstring. Never overwrite history.
- The disk cache (`.cache/`) is dev-only and git-ignored. `raw_responses` is the audit log.

## Engineering conventions

- Python 3.12, `uv`, `pyproject.toml` only. `ruff` (line length 110), `mypy --strict`
  with `ignore_missing_imports` for untyped third-party packages. Do not write stubs for
  `fantraxapi`.
- `structlog`; bind `league_id`, `season`, `run_id`, and `domain` via contextvars rather
  than passing them through signatures.
- Exceptions: `FantraxError` → `ConfigError`, `EdgeRejectedError`, `AuthError`,
  `RateLimitError`, `TransientError`, `EndpointChangedError`, `DataIntegrityError`.
  Only `RateLimitError` and `TransientError` are retried.
- Tests mock HTTP with `responses`; fixtures under `tests/fixtures/` are hand-written
  stand-ins until real (secret-scrubbed) payloads from Phase 0 replace them.
- CLI exits non-zero on failure and prints a one-line summary on success.
- Rate limit ~1 req/s by default. Be a good citizen.

## Things that are deliberately NOT built yet

- `fantrax auth` (Selenium cookie capture) — only if discovery proves it is needed.
- `sync`, `team`, `available`, `matchup`, `standings`, `report`, `db` commands.
- Any ORM model, migration, or analytics function.
