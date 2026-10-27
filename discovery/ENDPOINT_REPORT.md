# Fantrax endpoint discovery report

- League: `fqj3m6m8murmhnko` — season 2026-27 — sport NBA
- My team ID: `0tjisxjpmurmhnn2` (No Mercy, Just Usage Rate)
- Current scoring period: 2; current roster period: 7 (as of 2026-10-26T23:20-05:00; period bounds are 19:00 ET instants)
- Generated: 2026-10-27T04:21:32+00:00
- Secret ID configured: yes; cookie file present: no

## Summary

| Domain | Status | Source | Endpoint | Auth | HTTP | KB | Found | Missing | Notes |
|---|---|---|---|---|---|---|---|---|---|
| leagues | **UNAVAILABLE** | official | `getLeagues` | none | 200 | 0 | - | league, team | empty payload |
| league_info | **AVAILABLE** | official | `getLeagueInfo` | none | 200 | 101 | scoring, period, team, player, position | - |  |
| league_info_settings | **AVAILABLE** | official | `getLeagueInfo?excludePlayerInfo=true` | none | 200 | 38 | scoring, period, team | - |  |
| rosters_current | **AVAILABLE** | official | `getTeamRosters` | none | 200 | 8 | rosters, rosteritems, status | - |  |
| rosters_past | **AVAILABLE** | official | `getTeamRosters?period=` | none | 200 | 8 | rosters, rosteritems | - |  |
| standings | **AVAILABLE** | official | `getStandings` | none | 200 | 1 | team | - |  |
| matchups_current | **AVAILABLE** | fxpa | `getLiveScoringStats` | none | 200 | 189 | scorerMap, statsPerTeam, matchupMap | - |  |
| matchups_past | **AVAILABLE** | fxpa | `getLiveScoringStats?period=<prev>&date=<prev first day>` | none | 200 | 114 | scorerMap, statsPerTeam, matchupMap | - |  |
| fx_matchup_results | **AVAILABLE** | fxpa | `getStandings (SCHEDULE)` | none | 200 | 146 | tableList, matchupId, caption | - |  |
| draft_results | **AVAILABLE** | official | `getDraftResults` | none | 200 | 14 | team, player | - |  |
| draft_picks | **AVAILABLE** | official | `getDraftPicks` | none | 200 | 0 | draftpick | - |  |
| player_ids | **AVAILABLE** | official | `getPlayerIds?sport=NBA` | none | 200 | 204 | name | - |  |
| adp | **AVAILABLE** | official | `getAdp?sport=NBA` | none | 200 | 1 | name, adp | - |  |
| fx_league_info | **PARTIAL** | fxpa | `getFantasyLeagueInfo` | none | 200 | 4 | - | claim, budget | none: isMember=false — Fantrax served the public (non-member) view; secret: isMember=false — Fantrax served the publi... |
| fx_league_settings | **UNAVAILABLE** | fxpa | `getLeagueSettings` | - | - | - | - | - | none: auth rejected — fxpa getLeagueSettings: WARNING_NOT_LOGGED_IN; secret: auth rejected — fxpa getLeagueSettings: ... |
| fx_my_roster_stats | **AVAILABLE** | fxpa | `getTeamRosterInfo` | none | 200 | 39 | tables, scorer, cells | - | looks paginated |
| fx_my_roster_schedule | **AVAILABLE** | fxpa | `getTeamRosterInfo (SCHEDULE_FULL)` | none | 200 | 53 | schedule, date | - | looks paginated |
| fx_league_roster_schedules | **AVAILABLE** | fxpa | `getTeamRosterInfo (SCHEDULE_FULL) x all teams` | none | 200 | 538 | tables, rows, scorer | - | looks paginated |
| fx_my_roster_games_per_pos | **AVAILABLE** | fxpa | `getTeamRosterInfo (GAMES_PER_POS)` | none | 200 | 7 | gameplayedperpos | - |  |
| fx_player_pool_season | **AVAILABLE** | fxpa | `getPlayerStats (ALL_AVAILABLE, YEAR_TO_DATE)` | none | 200 | 87 | player, stat | - | looks paginated |
| fx_player_pool_7d | **AVAILABLE** | fxpa | `getPlayerStats (ALL_AVAILABLE, LAST_7_DAYS)` | none | 200 | 87 | player, stat | - | looks paginated |
| fx_player_pool_15d | **AVAILABLE** | fxpa | `getPlayerStats (ALL_AVAILABLE, LAST_15_DAYS)` | none | 200 | 87 | player, stat | - | looks paginated |
| fx_player_pool_30d | **AVAILABLE** | fxpa | `getPlayerStats (ALL_AVAILABLE, LAST_30_DAYS)` | none | 200 | 87 | player, stat | - | looks paginated |
| fx_transactions | **AVAILABLE** | fxpa | `getTransactionDetailsHistory` | none | 200 | 81 | transaction | - | looks paginated |
| fx_pending_transactions | **UNAVAILABLE** | fxpa | `getPendingTransactions` | - | - | - | - | - | none: auth rejected — fxpa getPendingTransactions: NOT_MEMBER_OF_LEAGUE; secret: auth rejected — fxpa getPendingTrans... |
| nba_schedule | **AVAILABLE** | derived | `inspects: fx_league_roster_schedules, fx_my_roster_schedule` | - | - | - | sched_ date columns, scorer.teamShortName, eventId | - | inspected: fx_league_roster_schedules; 142 rostered players; 30 game dates (10/27 .. 11/27); NBA teams rostered 30/30... |
| available_player_schedule | **AVAILABLE** | derived | `inspects: fx_player_pool_season, nba_schedule` | - | - | - | scorer.teamShortName | - | inspected: fx_player_pool_season (50/50 rows carry an NBA team) |
| game_limits | **AVAILABLE** | derived | `inspects: fx_my_roster_games_per_pos` | - | - | - | gameplayedperpos, max | - | inspected: ['fx_my_roster_games_per_pos']; per-position games-played and max columns are present |
| transaction_rules | **UNAVAILABLE** | derived | `inspects: league_info, league_info_settings, fx_league_info, fx_league_settings` | - | - | - | - | claim, budget, waiver, faab, daysused | inspected: ['league_info', 'league_info_settings', 'fx_league_info']; not fetched (auth rejected or skipped): ['fx_le... |
| player_pool_availability | **AVAILABLE** | derived | `inspects: league_info` | - | - | - | status, team, stat | available, waiver | inspected: ['league_info'] |

## Decisions needed

- Member-only fxpa endpoints rejected without a session (cookie level untested): `getLeagueSettings`, `getPendingTransactions`. Export cookies to test them.
- `transaction_rules` is UNAVAILABLE. Needs a logged-in session: fxpa getLeagueSettings answers WARNING_NOT_LOGGED_IN and getFantasyLeagueInfo serves the public view (isMember=false) without cookies, and the official API carries no transaction settings. Export fantrax.com cookies to the cookie file (see README) and rerun; if that works, build the Selenium `auth` command.

## Details

### leagues — UNAVAILABLE

My leagues and team IDs (resolves MY_TEAM_ID)

- Source: official; endpoint: `getLeagues`
- Auth attempts: none; succeeded with: none
- HTTP 200, 2 bytes, 139 ms
- Raw payload: `discovery/leagues.json`
- Notes:
  - empty payload

```json
{}
```

### league_info — AVAILABLE

Full league info incl. player pool, periods, scoring system

- Source: official; endpoint: `getLeagueInfo`
- Auth attempts: none; succeeded with: none
- HTTP 200, 103665 bytes, 88 ms
- Top-level keys: `matchups`, `rosterInfo`, `endDate`, `playerInfo`, `poolSettings`, `rosterPeriods`, `scoringPeriods`, `teamInfo`, `draftType`, `draftSettings`, `leagueName`, `leagueHistoryId`, `scoringSystem`, `seasonYear`, `startDate`, `playoffs`
- Raw payload: `discovery/league_info.json`

```json
{"period": 1, "matchupList": [{"away": {"name": "Conflict of Interest", "id": "ozju7nsmmurmhnn2", "shortName": "Walker"}, "home": {"name": "Suggs to be You", "id": "rdl7dlplmurmhnn2", "shortName": "Eric"}}, {"away": {"name": "The Fun Guys", "id": "f310mnh8murmhnn2", "shortName": "FUNGUY"}, "home": {"name": "The Rollinâ Treys", "id": "t5zv7h5emurmhnn2", "shortName": "Tristan"}}, {"away": {"name": "bADa bing bong blok", "id": "0j15rgscmurmhnn2", "shortName": "Masi"}, "home": {"name": "The 2026 Revenge Tour", "id": "p8lde4xbmusl24sh", "shortName": "REVENGER"}}, {"away": {"name": "No Mercy, Just Usage Rate", "id": "0tjisxjpmurmhnn2", "shortName": "Mark"}, "home": {"name": "Let's Go Brandon Ingram", "id": "om35rt8imurmhnn2", "shortName": "Catron"}}, {"away": {"name": "Practical", "id": "owvgfdvnmurmhnn2", "shortName": "Jokic"}, "home": {"name": "Bye Week", "id": "6wdc0v27murmhnn2", "shortName": "Ian"}}]}
```

### league_info_settings — AVAILABLE

League info with excludePlayerInfo=true (settings-only refresh)

- Source: official; endpoint: `getLeagueInfo?excludePlayerInfo=true`
- Auth attempts: none; succeeded with: none
- HTTP 200, 39261 bytes, 56 ms
- Top-level keys: `matchups`, `rosterInfo`, `endDate`, `poolSettings`, `rosterPeriods`, `scoringPeriods`, `teamInfo`, `draftType`, `draftSettings`, `leagueName`, `leagueHistoryId`, `scoringSystem`, `seasonYear`, `startDate`, `playoffs`
- Raw payload: `discovery/league_info_settings.json`

```json
{"period": 1, "matchupList": [{"away": {"name": "Conflict of Interest", "id": "ozju7nsmmurmhnn2", "shortName": "Walker"}, "home": {"name": "Suggs to be You", "id": "rdl7dlplmurmhnn2", "shortName": "Eric"}}, {"away": {"name": "The Fun Guys", "id": "f310mnh8murmhnn2", "shortName": "FUNGUY"}, "home": {"name": "The Rollinâ Treys", "id": "t5zv7h5emurmhnn2", "shortName": "Tristan"}}, {"away": {"name": "bADa bing bong blok", "id": "0j15rgscmurmhnn2", "shortName": "Masi"}, "home": {"name": "The 2026 Revenge Tour", "id": "p8lde4xbmusl24sh", "shortName": "REVENGER"}}, {"away": {"name": "No Mercy, Just Usage Rate", "id": "0tjisxjpmurmhnn2", "shortName": "Mark"}, "home": {"name": "Let's Go Brandon Ingram", "id": "om35rt8imurmhnn2", "shortName": "Catron"}}, {"away": {"name": "Practical", "id": "owvgfdvnmurmhnn2", "shortName": "Jokic"}, "home": {"name": "Bye Week", "id": "6wdc0v27murmhnn2", "shortName": "Ian"}}]}
```

### rosters_current — AVAILABLE

All team rosters, current lineup period

- Source: official; endpoint: `getTeamRosters`
- Auth attempts: none; succeeded with: none
- HTTP 200, 8211 bytes, 66 ms
- Top-level keys: `period`, `rosters`
- Raw payload: `discovery/rosters_current.json`

```json
{"id": "04s00", "position": "F", "status": "ACTIVE"}
```

### rosters_past — AVAILABLE

All team rosters, one past lineup period

- Source: official; endpoint: `getTeamRosters?period=`
- Auth attempts: none; succeeded with: none
- HTTP 200, 8064 bytes, 45 ms
- Top-level keys: `period`, `rosters`
- Raw payload: `discovery/rosters_past.json`

```json
{"id": "04s00", "position": "Flx", "status": "ACTIVE"}
```

### standings — AVAILABLE

League standings

- Source: official; endpoint: `getStandings`
- Auth attempts: none; succeeded with: none
- HTTP 200, 1258 bytes, 44 ms
- Top-level keys: `<list of 10>`
- Raw payload: `discovery/standings.json`

```json
{"teamName": "Practical", "teamId": "owvgfdvnmurmhnn2", "gamesBack": 0.0, "rank": 1, "points": "6-3-0", "winPercentage": 0.667}
```

### matchups_current — AVAILABLE

Live matchup scores and per-player stats for today (current scoring period)

- Source: fxpa; endpoint: `getLiveScoringStats`; fantraxapi equivalent: `League.live_scores()`
- Auth attempts: none; succeeded with: none
- HTTP 200, 193983 bytes, 152 ms
- Top-level keys: `date`, `scorerStatusLegend`, `rt`, `scoringCategoryGroups`, `playerGameInfo`, `rosterVersionsEpoch`, `fantasyTeamInfo`, `displayPeriod`, `periods`, `displayedLists`, `allEventsFinished`, `statsPerTeam`, `matchups`, `ownTeamIds`, `standingsTable`, `clientId`, `teams`, `live2`, `scoringCategoriesPerGroup`, `miscData`, `dates`, `allPlayerStats`, `showPositions`, `tableHeaderTopLevelPerScGroup`, `scorerMap`, `matchupBracketGroups`, `showPlayerZeros`, `displayedSelections`, `scorerStatusMap`, `displayDate`, `fantasyTeams`, `rosterVersions`, `resourceMap`, `matchupMap`
- Raw payload: `discovery/matchups_current.json`

```json
{"id": "3010", "name": "Player", "shortName": "Plyr", "description": "Player"}
```

### matchups_past — AVAILABLE

Live-scoring snapshot for a date inside the previous scoring period

- Source: fxpa; endpoint: `getLiveScoringStats?period=<prev>&date=<prev first day>`; fantraxapi equivalent: `League.live_scores()`
- Auth attempts: none; succeeded with: none
- HTTP 200, 116415 bytes, 114 ms
- Top-level keys: `date`, `scorerStatusLegend`, `scoringCategoryGroups`, `playerGameInfo`, `rosterVersionsEpoch`, `fantasyTeamInfo`, `displayPeriod`, `periods`, `displayedLists`, `allEventsFinished`, `statsPerTeam`, `matchups`, `ownTeamIds`, `standingsTable`, `clientId`, `teams`, `live2`, `scoringCategoriesPerGroup`, `miscData`, `dates`, `allPlayerStats`, `showPositions`, `tableHeaderTopLevelPerScGroup`, `scorerMap`, `matchupBracketGroups`, `showPlayerZeros`, `displayedSelections`, `scorerStatusMap`, `displayDate`, `fantasyTeams`, `rosterVersions`, `resourceMap`, `matchupMap`
- Raw payload: `discovery/matchups_past.json`

```json
{"id": "3010", "name": "Player", "shortName": "Plyr", "description": "Player"}
```

### fx_matchup_results — AVAILABLE

Category W/L/T per team for every scoring period (past matchup results)

- Source: fxpa; endpoint: `getStandings (SCHEDULE)`; fantraxapi equivalent: `League.standings()`
- Auth attempts: none; succeeded with: none
- HTTP 200, 149628 bytes, 142 ms
- Top-level keys: `goBackDays`, `fantasyTeamInfo`, `matchupIdsPerTeam`, `displayedSelections`, `miscData`, `tableList`, `displayedLists`
- Raw payload: `discovery/fx_matchup_results.json`

```json
{"name": "Bye Week", "logoUrl512": "https://fantraximg.com/logos/7ls/tmLogo_7lsd5qfpl9atckfr_512.jpg", "shortName": "Ian"}
```

### draft_results — AVAILABLE

Draft results

- Source: official; endpoint: `getDraftResults`
- Auth attempts: none; succeeded with: none
- HTTP 200, 14242 bytes, 52 ms
- Top-level keys: `draftDate`, `draftPicks`, `draftState`, `endDate`, `draftOrder`, `draftType`, `startDate`
- Raw payload: `discovery/draft_results.json`

```json
{"round": 1, "pick": 1, "teamId": "p8lde4xbmusl24sh", "time": 1791209594000, "pickInRound": 1, "playerId": "06cch"}
```

### draft_picks — AVAILABLE

Draft pick ownership

- Source: official; endpoint: `getDraftPicks`
- Auth attempts: none; succeeded with: none
- HTTP 200, 24 bytes, 55 ms
- Top-level keys: `currentDraftPicks`
- Raw payload: `discovery/draft_picks.json`

```json
{}
```

### player_ids — AVAILABLE

NBA player ID crosswalk

- Source: official; endpoint: `getPlayerIds?sport=NBA`
- Auth attempts: none; succeeded with: none
- HTTP 200, 208548 bytes, 95 ms
- Top-level keys: `0722e`, `06mkb`, `06mkc`, `07apr`, `07aps`, `06mka`, `05wah`, `07apl`, `06mjy`, `07apm`, `06mjz`, `07apj`, `06mjw`, `07apk`, `06mjx`, `07aph`, `06mju`, `07api`, `06mjv`, `07apf`, `07apg`, `06mjt`, `07apd`, `07ape`, `07234`, `07235`, `07232`, `07apa`, `059fz`, `40220#3020`, `07231`, `05293`, `059fy`, `07aoz`, `059fx`, `059fu`, `0527l`, `07aoq`, `07aor`, `0527h`
- Raw payload: `discovery/player_ids.json`

```json
{"rotowireId": 6651, "sportRadarId": "5ec8194c-a2fc-4982-8afb-c02948e8c6ef", "name": "Cleveland, Matthew", "fantraxId": "0722e", "team": "(N/A)", "position": "PG"}
```

### adp — AVAILABLE

NBA ADP (first 25)

- Source: official; endpoint: `getAdp?sport=NBA`
- Auth attempts: none; succeeded with: none
- HTTP 200, 1501 bytes, 57 ms
- Top-level keys: `<list of 24>`
- Raw payload: `discovery/adp.json`

```json
{"pos": "C", "name": "Jokic, Nikola", "id": "03e75", "ADP": 1.29}
```

### fx_league_info — PARTIAL

fxpa league info — member view carries transaction rules, claim budgets, days-used rule

- Source: fxpa; endpoint: `getFantasyLeagueInfo`; fantraxapi equivalent: `League() init`
- Auth attempts: none, secret, cookie; succeeded with: none
- HTTP 200, 4032 bytes, 62 ms
- Top-level keys: `fantasySettings`, `positionMap`
- Raw payload: `discovery/fx_league_info.json`
- Notes:
  - none: isMember=false — Fantrax served the public (non-member) view
  - secret: isMember=false — Fantrax served the public (non-member) view
  - cookie: not testable — cookie file .fantrax_cookies.json not found; the cookie auth level cannot be tested
  - expected key fragments not seen: ['claim', 'budget']
  - kept the best payload seen; no auth level produced the member view
- Recommendation: Export fantrax.com cookies to the cookie file and rerun to test the member view

```json
{"code": "REGULAR"}
```

### fx_league_settings — UNAVAILABLE

League settings page — transaction rules, claim limits, FA budget (login required)

- Source: fxpa; endpoint: `getLeagueSettings`; fantraxapi equivalent: `(none)`
- Auth attempts: none, secret, cookie; succeeded with: -
- Notes:
  - none: auth rejected — fxpa getLeagueSettings: WARNING_NOT_LOGGED_IN
  - secret: auth rejected — fxpa getLeagueSettings: WARNING_NOT_LOGGED_IN
  - cookie: not testable — cookie file .fantrax_cookies.json not found; the cookie auth level cannot be tested
- Error: `ConfigError('cookie file .fantrax_cookies.json not found; the cookie auth level cannot be tested')`
- Recommendation: Rejected at none/secret; cookie level untested — export cookies and rerun

### fx_my_roster_stats — AVAILABLE

My roster with per-player stats (view=STATS)

- Source: fxpa; endpoint: `getTeamRosterInfo`; fantraxapi equivalent: `League.team_roster()`
- Auth attempts: none; succeeded with: none
- HTTP 200, 40401 bytes, 464 ms
- Top-level keys: `settings`, `scoringCategoryTypes`, `teamHeadingInfo`, `periodOppnentTeamIds`, `tabs`, `miscData`, `myTeamIds`, `goBackDays`, `rosterDisplayMap`, `hideRowsLineupChange`, `tables`, `displayedSelections`, `fantasyTeams`, `displayedLists`, `availableActiveViewType`, `leagueNotices`
- Raw payload: `discovery/fx_my_roster_stats.json`
- Notes:
  - looks paginated

```json
{"logoUploaded": false, "logoUrl": "/assets/images/badges/nba/gameIcon_NBA_COMMISSIONER.svg"}
```

### fx_my_roster_schedule — AVAILABLE

My roster player schedules (view=SCHEDULE_FULL)

- Source: fxpa; endpoint: `getTeamRosterInfo (SCHEDULE_FULL)`; fantraxapi equivalent: `League.team_roster()`
- Auth attempts: none; succeeded with: none
- HTTP 200, 54607 bytes, 80 ms
- Top-level keys: `settings`, `scoringCategoryTypes`, `teamHeadingInfo`, `periodOppnentTeamIds`, `tabs`, `miscData`, `myTeamIds`, `goBackDays`, `rosterDisplayMap`, `hideRowsLineupChange`, `tables`, `displayedSelections`, `fantasyTeams`, `displayedLists`, `availableActiveViewType`, `leagueNotices`
- Raw payload: `discovery/fx_my_roster_schedule.json`
- Notes:
  - looks paginated

```json
{"logoUploaded": false, "logoUrl": "/assets/images/badges/nba/gameIcon_NBA_COMMISSIONER.svg"}
```

### fx_league_roster_schedules — AVAILABLE

SCHEDULE_FULL grid for every fantasy team — the league-wide NBA schedule source

- Source: fxpa; endpoint: `getTeamRosterInfo (SCHEDULE_FULL) x all teams`; fantraxapi equivalent: `League.team_roster()`
- Auth attempts: none; succeeded with: none
- HTTP 200, 551322 bytes, 739 ms
- Top-level keys: `6wdc0v27murmhnn2`, `f310mnh8murmhnn2`, `p8lde4xbmusl24sh`, `rdl7dlplmurmhnn2`, `om35rt8imurmhnn2`, `t5zv7h5emurmhnn2`, `0tjisxjpmurmhnn2`, `ozju7nsmmurmhnn2`, `0j15rgscmurmhnn2`, `owvgfdvnmurmhnn2`
- Raw payload: `discovery/fx_league_roster_schedules.json`
- Notes:
  - looks paginated

```json
{"logoUploaded": false, "logoUrl": "/assets/images/badges/nba/gameIcon_NBA_COMMISSIONER.svg"}
```

### fx_my_roster_games_per_pos — AVAILABLE

Games played and limits by roster position (view=GAMES_PER_POS)

- Source: fxpa; endpoint: `getTeamRosterInfo (GAMES_PER_POS)`; fantraxapi equivalent: `League.team_roster()`
- Auth attempts: none; succeeded with: none
- HTTP 200, 7459 bytes, 73 ms
- Top-level keys: `myTeamIds`, `gamePlayedPerPosData`, `teamHeadingInfo`, `scMinMaxData`, `displayedSelections`, `tabs`, `fantasyTeams`, `miscData`, `displayedLists`
- Raw payload: `discovery/fx_my_roster_games_per_pos.json`

```json
{"min": "No min", "pos": "Point Guard (PG)", "max": "No max", "gp": 1, "posShort": "PG"}
```

### fx_player_pool_season — AVAILABLE

Available players with season stats

- Source: fxpa; endpoint: `getPlayerStats (ALL_AVAILABLE, YEAR_TO_DATE)`; fantraxapi equivalent: `(none)`
- Auth attempts: none; succeeded with: none
- HTTP 200, 89595 bytes, 147 ms
- Top-level keys: `displayedStatusOrTeam`, `paginatedResultSet`, `statsTable`, `scoringCategoryTypes`, `displayedSchedulePageAdj`, `numScoringPeriods`, `miscDisplayTypes`, `tabs`, `displayedView`, `displayedTimeStartType`, `posOrGroupList`, `goBackDays`, `playerNewsIconRecencyLegend`, `statisticsViewTypeIds`, `numPeriods`, `displayedPosOrGroup`, `displayedLists`, `seasonOrProjections`, `prevSchedPageAllowed`, `periodList`, `displayedSortReversed`, `statisticsTimeframeTypes`, `miscData`, `displayedSortType`, `tableHeader`, `nextSchedPageAllowed`, `displayedPeriod`, `sortOptions`, `displayedSelections`, `displayedMiscDisplayType`, `displayedScoringCategoryType`, `claimsDropsAllowed`, `statusOrTeamList`, `displayedSeasonOrProjection`
- Raw payload: `discovery/fx_player_pool_season.json`
- Notes:
  - looks paginated

```json
{"totalNumPages": 23, "pageNumber": 1, "maxResultsPerPage": 50, "totalNumResults": 1139}
```

### fx_player_pool_7d — AVAILABLE

Available players with 7d stats

- Source: fxpa; endpoint: `getPlayerStats (ALL_AVAILABLE, LAST_7_DAYS)`; fantraxapi equivalent: `(none)`
- Auth attempts: none; succeeded with: none
- HTTP 200, 89119 bytes, 210 ms
- Top-level keys: `displayedStatusOrTeam`, `paginatedResultSet`, `statsTable`, `scoringCategoryTypes`, `displayedSchedulePageAdj`, `numScoringPeriods`, `miscDisplayTypes`, `tabs`, `displayedView`, `displayedTimeStartType`, `posOrGroupList`, `goBackDays`, `playerNewsIconRecencyLegend`, `statisticsViewTypeIds`, `numPeriods`, `displayedPosOrGroup`, `displayedLists`, `seasonOrProjections`, `prevSchedPageAllowed`, `periodList`, `displayedSortReversed`, `statisticsTimeframeTypes`, `miscData`, `displayedSortType`, `tableHeader`, `nextSchedPageAllowed`, `displayedPeriod`, `sortOptions`, `displayedSelections`, `displayedMiscDisplayType`, `displayedScoringCategoryType`, `claimsDropsAllowed`, `statusOrTeamList`
- Raw payload: `discovery/fx_player_pool_7d.json`
- Notes:
  - looks paginated

```json
{"totalNumPages": 23, "pageNumber": 1, "maxResultsPerPage": 50, "totalNumResults": 1139}
```

### fx_player_pool_15d — AVAILABLE

Available players with 15d stats

- Source: fxpa; endpoint: `getPlayerStats (ALL_AVAILABLE, LAST_15_DAYS)`; fantraxapi equivalent: `(none)`
- Auth attempts: none; succeeded with: none
- HTTP 200, 89119 bytes, 153 ms
- Top-level keys: `displayedStatusOrTeam`, `paginatedResultSet`, `statsTable`, `scoringCategoryTypes`, `displayedSchedulePageAdj`, `numScoringPeriods`, `miscDisplayTypes`, `tabs`, `displayedView`, `displayedTimeStartType`, `posOrGroupList`, `goBackDays`, `playerNewsIconRecencyLegend`, `statisticsViewTypeIds`, `numPeriods`, `displayedPosOrGroup`, `displayedLists`, `seasonOrProjections`, `prevSchedPageAllowed`, `periodList`, `displayedSortReversed`, `statisticsTimeframeTypes`, `miscData`, `displayedSortType`, `tableHeader`, `nextSchedPageAllowed`, `displayedPeriod`, `sortOptions`, `displayedSelections`, `displayedMiscDisplayType`, `displayedScoringCategoryType`, `claimsDropsAllowed`, `statusOrTeamList`
- Raw payload: `discovery/fx_player_pool_15d.json`
- Notes:
  - looks paginated

```json
{"totalNumPages": 23, "pageNumber": 1, "maxResultsPerPage": 50, "totalNumResults": 1139}
```

### fx_player_pool_30d — AVAILABLE

Available players with 30d stats

- Source: fxpa; endpoint: `getPlayerStats (ALL_AVAILABLE, LAST_30_DAYS)`; fantraxapi equivalent: `(none)`
- Auth attempts: none; succeeded with: none
- HTTP 200, 89119 bytes, 172 ms
- Top-level keys: `displayedStatusOrTeam`, `paginatedResultSet`, `statsTable`, `scoringCategoryTypes`, `displayedSchedulePageAdj`, `numScoringPeriods`, `miscDisplayTypes`, `tabs`, `displayedView`, `displayedTimeStartType`, `posOrGroupList`, `goBackDays`, `playerNewsIconRecencyLegend`, `statisticsViewTypeIds`, `numPeriods`, `displayedPosOrGroup`, `displayedLists`, `seasonOrProjections`, `prevSchedPageAllowed`, `periodList`, `displayedSortReversed`, `statisticsTimeframeTypes`, `miscData`, `displayedSortType`, `tableHeader`, `nextSchedPageAllowed`, `displayedPeriod`, `sortOptions`, `displayedSelections`, `displayedMiscDisplayType`, `displayedScoringCategoryType`, `claimsDropsAllowed`, `statusOrTeamList`
- Raw payload: `discovery/fx_player_pool_30d.json`
- Notes:
  - looks paginated

```json
{"totalNumPages": 23, "pageNumber": 1, "maxResultsPerPage": 50, "totalNumResults": 1139}
```

### fx_transactions — AVAILABLE

Transaction history (adds/drops/trades/claims)

- Source: fxpa; endpoint: `getTransactionDetailsHistory`; fantraxapi equivalent: `League.transactions()`
- Auth attempts: none; succeeded with: none
- HTTP 200, 82988 bytes, 79 ms
- Top-level keys: `paginatedResultSet`, `filterSettings`, `displayedSelections`, `miscData`, `displayedLists`, `table`
- Raw payload: `discovery/fx_transactions.json`
- Notes:
  - looks paginated

```json
{"totalNumPages": 1, "pageNumber": 1, "maxResultsPerPage": 100, "totalNumResults": 54}
```

### fx_pending_transactions — UNAVAILABLE

Pending transactions / claims

- Source: fxpa; endpoint: `getPendingTransactions`; fantraxapi equivalent: `League.pending_trades()`
- Auth attempts: none, secret, cookie; succeeded with: -
- Notes:
  - none: auth rejected — fxpa getPendingTransactions: NOT_MEMBER_OF_LEAGUE
  - secret: auth rejected — fxpa getPendingTransactions: NOT_MEMBER_OF_LEAGUE
  - cookie: not testable — cookie file .fantrax_cookies.json not found; the cookie auth level cannot be tested
- Error: `ConfigError('cookie file .fantrax_cookies.json not found; the cookie auth level cannot be tested')`
- Recommendation: Rejected at none/secret; cookie level untested — export cookies and rerun

### nba_schedule — AVAILABLE

Dated NBA schedule grid (opponent, tip-off, eventId per player per date) for every NBA team

- Source: derived; endpoint: `inspects: fx_league_roster_schedules, fx_my_roster_schedule`
- Auth attempts: -; succeeded with: -
- Notes:
  - inspected: fx_league_roster_schedules
  - 142 rostered players; 30 game dates (10/27 .. 11/27); NBA teams rostered 30/30, seen as opponent 30/30
- Recommendation: Every NBA team has a rostered player, so the union of all SCHEDULE_FULL grids is the complete league schedule — no external NBA schedule source is needed.

```json
{"players": 142, "dates": ["10/27", "10/28", "10/29", "10/30", "10/31", "11/1", "11/2", "11/4", "11/5", "11/6"], "teams_direct": ["ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GS", "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NO", "NY", "OKC", "ORL", "PHI", "PHO", "POR", "SA", "SAC", "TOR", "UTA", "WAS"], "teams_missing": []}
```

### available_player_schedule — AVAILABLE

Upcoming games for available free agents (pool rows joined to the NBA schedule by team)

- Source: derived; endpoint: `inspects: fx_player_pool_season, nba_schedule`
- Auth attempts: -; succeeded with: -
- Notes:
  - inspected: fx_player_pool_season (50/50 rows carry an NBA team)
- Recommendation: Join each pool row's scorer.teamShortName to the nba_schedule grid for its team.

### game_limits — AVAILABLE

Per-position games played and configured maximums

- Source: derived; endpoint: `inspects: fx_my_roster_games_per_pos`
- Auth attempts: -; succeeded with: -
- Notes:
  - inspected: ['fx_my_roster_games_per_pos']
  - per-position games-played and max columns are present
- Recommendation: Read the max column in the GAMES_PER_POS payload; this league may report No max.

```json
["autoSubOrderMax", "gamePlayedPerPosData", "max", "maxNote", "maxNoteTitle", "minMaxWarnings", "scMinMaxData"]
```

### transaction_rules — UNAVAILABLE

Claim limits, FA/WW budget, and days-used rule

- Source: derived; endpoint: `inspects: league_info, league_info_settings, fx_league_info, fx_league_settings`
- Auth attempts: -; succeeded with: -
- Notes:
  - inspected: ['league_info', 'league_info_settings', 'fx_league_info']
  - not fetched (auth rejected or skipped): ['fx_league_settings']
- Recommendation: Needs a logged-in session: fxpa getLeagueSettings answers WARNING_NOT_LOGGED_IN and getFantasyLeagueInfo serves the public view (isMember=false) without cookies, and the official API carries no transaction settings. Export fantrax.com cookies to the cookie file (see README) and rerun; if that works, build the Selenium `auth` command.

```json
[]
```

### player_pool_availability — AVAILABLE

Does the official player pool mark FA/waiver status and carry stats?

- Source: derived; endpoint: `inspects: league_info`
- Auth attempts: -; succeeded with: -
- Notes:
  - inspected: ['league_info']
- Recommendation: If no status/stats: the FA pool must come from fxpa getPlayerStats.

```json
["numPlayoffTeams", "status", "teamInfo"]
```
