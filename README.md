# fantrax-analytics

Local, offline-first analytics for a Fantrax NBA fantasy league. Pulls league, roster,
matchup, standings and player data; stores it in SQLite with full history; reports back.

**Status: Phase 0 (endpoint discovery).** Nothing is ingested or stored yet. The
`discover` command probes every known endpoint against the real league and writes a
report that decides the schema and whether a browser session is needed at all.

## Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"          # or: just setup
cp .env.example .env
```

Then fill in `FANTRAX_USER_SECRET_ID`. Fantrax → your **User Profile** screen → *Secret ID*.
It is only ever sent in a POST body, never in a URL, and `.env` is git-ignored.

## Run discovery

```bash
fantrax discover                     # or: just discover
fantrax discover --no-cache          # bypass the dev cache
fantrax discover --skip-fallback     # official beta API only
fantrax discover -d league_info -d standings
```

Outputs:

- `discovery/ENDPOINT_REPORT.md` — one row per domain: AVAILABLE / PARTIAL / UNAVAILABLE,
  source, auth level required, bytes, which expected fields were seen, and a **Decisions
  needed** section.
- `discovery/<domain>.json` — every raw payload with request metadata (git-ignored; they
  contain other owners' names).
- `discovery/summary.json` — the same results machine-readably.
- `FANTRAX_MY_TEAM_ID` written into `.env` once resolved from `getLeagues`.

Exit code is 1 if a core official endpoint (league info, rosters, standings, matchups) is
unavailable; 2 for configuration errors.

## How the probes escalate

| Level  | What it adds                                   | When it's tried                              |
|--------|------------------------------------------------|----------------------------------------------|
| none   | `User-Agent` only                              | always first                                 |
| secret | `userSecretId` query param                     | fxpa probes, if the level above was rejected |
| cookie | browser cookies from `.fantrax_cookies.json`   | only if the file exists                      |

A 403 with an HTML body is reported as **edge rejection** (Cloudflare 1010) — that means the
`User-Agent` is missing or blocked, and no credential will fix it, so escalation stops.

The Selenium cookie-capture command is **not** built. If the report shows every fxpa probe
rejected at `none` and `secret`, that is the moment to decide whether to build it. To test
the cookie level by hand first, export your fantrax.com cookies as a JSON list of
`{name, value, domain, path}` objects to `.fantrax_cookies.json` and rerun discovery.

## Data sources

**Primary — official REST API (v1.0 beta), `https://www.fantrax.com/fxea/general/`:**
`getLeagues`, `getLeagueInfo`, `getTeamRosters`, `getStandings`, `getTeamStatsForMatchups`,
`getDraftPicks`, `getDraftResults`, `getPlayerIds`, `getAdp`. Every request must send a
`User-Agent`.

**Fallback — undocumented `/fxpa/req` message API** (same request pattern `fantraxapi`
uses) for what the beta API does not expose: per-player stats, the free-agent pool with
stats, transactions, claim budgets. Method names are best-known; discovery records which
work for this league.

## Development

```bash
just test     # pytest (mocked HTTP; no network)
just lint     # ruff + mypy --strict
just fmt
```

Logs go to `logs/fantrax.log` (JSON, rotating) and the console. Every line carries
`league_id`, `season`, `run_id`.
