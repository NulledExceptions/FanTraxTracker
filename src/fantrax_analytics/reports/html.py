"""Render a :class:`Dashboard` as one self-contained HTML page (inline CSS + SVG, no external assets).

Colour roles follow the project's data-viz conventions: my team is categorical slot 1 (blue), the
opponent slot 2 (orange); lead/trail margins use the blue/red diverging pair around a neutral
midpoint; the games grid uses the single-hue sequential blue; status colours always ship with a
text label. Text never wears a series colour.
"""

from __future__ import annotations

from html import escape
from typing import Any

from fantrax_analytics.analytics.available import CategoryHelp
from fantrax_analytics.analytics.categories import Category, format_value
from fantrax_analytics.analytics.matchup import CategoryEdge
from fantrax_analytics.reports.dashboard import Dashboard

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10); --mid: #f0efec;
  --me: #2a78d6; --me-soft: #9ec5f4; --them: #eb6834; --them-soft: #f6c3ad;
  --lead: #2a78d6; --trail: #e34948;
  --seq-1: #cde2fb; --seq-2: #86b6ef; --seq-3: #3987e5; --seq-4: #1c5cab;
  --good: #0ca30c; --warn: #fab219; --serious: #ec835a; --critical: #d03b3b; --good-text: #006300;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10); --mid: #383835;
    --me: #3987e5; --me-soft: #1c5cab; --them: #d95926; --them-soft: #7a3416;
    --lead: #3987e5; --trail: #e66767;
    --seq-1: #184f95; --seq-2: #256abf; --seq-3: #5598e7; --seq-4: #b7d3f6;
    --good-text: #0ca30c;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10); --mid: #383835;
  --me: #3987e5; --me-soft: #1c5cab; --them: #d95926; --them-soft: #7a3416;
  --lead: #3987e5; --trail: #e66767;
  --seq-1: #184f95; --seq-2: #256abf; --seq-3: #5598e7; --seq-4: #b7d3f6;
  --good-text: #0ca30c;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1240px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 32px 0 12px; }
h3 { font-size: 14px; margin: 0 0 8px; }
.sub { color: var(--ink-2); margin: 0 0 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.tile { background: var(--surface); border: 1px solid var(--ring); border-radius: 8px; padding: 12px 14px; }
.tile .label { color: var(--ink-2); font-size: 12px; }
.tile .value { font-size: 26px; font-weight: 600; margin-top: 2px; }
.tile .note { color: var(--muted); font-size: 12px; margin-top: 2px; }
.card { background: var(--surface); border: 1px solid var(--ring); border-radius: 8px; padding: 14px 16px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 12px; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 5px 8px; text-align: right; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--ink-2); font-weight: 600; font-size: 12px; cursor: pointer; user-select: none; }
th.l, td.l { text-align: left; }
tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: var(--mid); }
.muted { color: var(--muted); }
.ink2 { color: var(--ink-2); }
.pill { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; border: 1px solid var(--ring); }
.pill.me { color: var(--ink); background: color-mix(in srgb, var(--me) 18%, transparent); }
.pill.them { color: var(--ink); background: color-mix(in srgb, var(--them) 18%, transparent); }
.pill.tie { color: var(--ink-2); }
.legend { display: flex; gap: 16px; font-size: 12px; color: var(--ink-2); margin: 6px 0 10px; flex-wrap: wrap; }
.sw { display: inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px; margin-right: 4px; }
svg text { fill: var(--ink-2); font-size: 11px; }
svg .val { fill: var(--ink); }
.grid td.g { text-align: center; padding: 3px; }
.grid .cell { display: block; height: 20px; border-radius: 4px; border: 2px solid var(--surface); }
.grid .cell.on { background: var(--seq-3); }
.grid .cell.res { background: var(--seq-1); }
.grid .cell.off { background: var(--mid); }
.grid tfoot td { font-weight: 600; }
.status-warn::before { content: "\\26A0  "; }
.status-good::before { content: "\\2713  "; }
.tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.tabs button { background: var(--surface); color: var(--ink); border: 1px solid var(--ring); border-radius: 14px; padding: 3px 10px; cursor: pointer; font: inherit; font-size: 12px; }
.tabs button[aria-selected="true"] { border-color: var(--me); box-shadow: inset 0 0 0 1px var(--me); }
.help-panel[hidden] { display: none; }
footer { margin-top: 40px; color: var(--muted); font-size: 12px; }
ul.notes { margin: 6px 0 0 18px; padding: 0; }
@media (max-width: 720px) { .cards { grid-template-columns: 1fr; } th, td { padding: 4px 5px; } }
"""

JS = """
document.querySelectorAll('table.sortable th').forEach((th, idx) => {
  th.addEventListener('click', () => {
    const table = th.closest('table'); const tbody = table.tBodies[0];
    const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc'; th.dataset.dir = dir;
    const num = (t) => { const v = parseFloat(String(t).replace(/[^0-9.\\-]/g, '')); return isNaN(v) ? null : v; };
    const rows = Array.from(tbody.rows);
    rows.sort((a, b) => {
      const ta = a.cells[idx]?.dataset.v ?? a.cells[idx]?.textContent ?? '';
      const tb = b.cells[idx]?.dataset.v ?? b.cells[idx]?.textContent ?? '';
      const na = num(ta), nb = num(tb);
      const c = (na !== null && nb !== null) ? na - nb : String(ta).localeCompare(String(tb));
      return dir === 'asc' ? c : -c;
    });
    rows.forEach(r => tbody.appendChild(r));
  });
});
document.querySelectorAll('.tabs').forEach(tabs => {
  tabs.querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => {
    tabs.querySelectorAll('button').forEach(b => b.setAttribute('aria-selected', b === btn ? 'true' : 'false'));
    const root = tabs.parentElement;
    root.querySelectorAll('.help-panel').forEach(p => { p.hidden = p.dataset.cat !== btn.dataset.cat; });
  }));
});
"""


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def _fmt(cat: Category, value: float | None, *, per_game: bool = False) -> str:
    return format_value(cat, value, per_game=per_game)


def _wlt(record: tuple[float, float, float] | None) -> str:
    if record is None:
        return "-"
    w, l, t = record
    return f"{w:g}-{l:g}-{t:g}"


def _tile(label: str, value: str, note: str = "") -> str:
    return (
        f'<div class="tile"><div class="label">{_e(label)}</div><div class="value">{_e(value)}</div>'
        f'<div class="note">{_e(note)}</div></div>'
    )


def _leader_pill(leader: str) -> str:
    text = {"me": "me", "them": "them", "tie": "tie", "unknown": "?"}[leader]
    return f'<span class="pill {leader}">{text}</span>'


# ------------------------------------------------------------------------------ charts
def _margin_bar(edge: CategoryEdge, width: int = 160) -> str:
    """Diverging bar: blue to the right when I lead, red to the left when I trail."""
    if edge.closeness is None:
        return '<span class="muted">-</span>'
    half = width // 2
    span = max(2, int(round(min(edge.closeness, 1.0) * (half - 4))))
    if edge.leader == "me":
        x, fill = half, "var(--lead)"
    elif edge.leader == "them":
        x, fill = half - span, "var(--trail)"
    else:
        x, fill, span = half - 1, "var(--axis)", 2
    pct = f"{edge.closeness * 100:.0f}% gap"
    title = f"{edge.category.key}: {_fmt(edge.category, edge.mine)} vs {_fmt(edge.category, edge.theirs)} ({pct})"
    return (
        f'<svg width="{width}" height="16" role="img" aria-label="{_e(title)}"><title>{_e(title)}</title>'
        f'<rect x="0" y="6" width="{width}" height="4" fill="var(--mid)" rx="2"/>'
        f'<rect x="{half - 1}" y="2" width="2" height="12" fill="var(--axis)"/>'
        f'<rect x="{x}" y="4" width="{span}" height="8" fill="{fill}" rx="4"/></svg>'
    )


def _pair_bars(cat: Category, mine_now: float | None, mine_proj: float | None, theirs_now: float | None,
               theirs_proj: float | None, width: int = 240) -> str:
    """Two thin horizontal bars (me / them) on one shared scale: light = projected, solid = so far."""
    values = [v for v in (mine_now, mine_proj, theirs_now, theirs_proj) if v is not None]
    if not values:
        return '<span class="muted">-</span>'
    if cat.is_rate:
        lo, hi = 0.0, max(values) * 1.05
    else:
        lo, hi = 0.0, max(values) or 1.0
    scale = (width - 56) / (hi - lo) if hi > lo else 0

    def rect(y: int, value: float | None, fill: str) -> str:
        if value is None:
            return ""
        w = max(2, int(round((value - lo) * scale)))
        return f'<rect x="0" y="{y}" width="{w}" height="8" fill="{fill}" rx="4"/>'

    def label(y: int, value: float | None) -> str:
        if value is None:
            return ""
        w = int(round((value - lo) * scale))
        return f'<text class="val" x="{w + 6}" y="{y + 8}">{_e(_fmt(cat, value))}</text>'

    title = (
        f"{cat.key} - me: {_fmt(cat, mine_now)} now, {_fmt(cat, mine_proj)} projected; "
        f"them: {_fmt(cat, theirs_now)} now, {_fmt(cat, theirs_proj)} projected"
    )
    return (
        f'<svg width="{width}" height="30" role="img" aria-label="{_e(title)}"><title>{_e(title)}</title>'
        f"{rect(2, mine_proj, 'var(--me-soft)')}{rect(2, mine_now, 'var(--me)')}{label(2, mine_proj)}"
        f"{rect(16, theirs_proj, 'var(--them-soft)')}{rect(16, theirs_now, 'var(--them)')}{label(16, theirs_proj)}"
        "</svg>"
    )


def _impact_bar(value: float, maximum: float, width: int = 90) -> str:
    w = max(2, int(round(width * value / maximum))) if maximum > 0 else 2
    return (
        f'<svg width="{width}" height="10" aria-hidden="true"><rect x="0" y="1" width="{w}" height="8" '
        f'fill="var(--me)" rx="4"/></svg>'
    )


# ---------------------------------------------------------------------------- sections
def _header(d: Dashboard) -> str:
    dates = ""
    if d.period_dates:
        dates = f"{d.period_dates[0]:%a %b %-d} - {d.period_dates[-1]:%a %b %-d}"
    return (
        f"<h1>{_e(d.my_team_name)} <span class='ink2'>vs</span> {_e(d.opponent_name)}</h1>"
        f"<p class='sub'>{_e(d.league_name)} - scoring period {d.period or '?'} ({_e(dates)}) - "
        f"built {d.generated_at:%a %b %-d, %H:%M}</p>"
    )


def _tiles(d: Dashboard) -> str:
    sides = d.matchup.side(d.my_team_id) if d.matchup else None
    now = _wlt((sides[0].wins, sides[0].losses, sides[0].ties)) if sides else "-"
    my_proj = _wlt(tuple(float(x) for x in d.projected_record)) if d.projected_record else "-"  # type: ignore[arg-type]
    o = d.outlook
    played = str(o.played) if o and o.played is not None else "-"
    projected = str(o.projected_total) if o and o.projected_total is not None else "-"
    cap = f"of {o.max_games} max" if o and o.max_games is not None else "no max"
    slack_note = ""
    if o and o.slack is not None:
        slack_note = f"{o.slack} under the cap" if o.slack >= 0 else f"{-o.slack} over the cap"
    return (
        '<div class="tiles">'
        + _tile("Category score now", now, "W-L-T this period")
        + _tile("Fantrax projects", _wlt(d.fantrax_projected_wlt), "Fantrax's own projection")
        + _tile("This model projects", my_proj, "per-game projections x games left")
        + _tile("Games played", played, "team games so far this period")
        + _tile("Games projected", projected, f"{cap}; {slack_note}".strip("; "))
        + "</div>"
    )


def _matchup_section(d: Dashboard) -> str:
    if not d.matchup or not d.edges:
        return "<h2>Current matchup</h2><p class='muted'>No period totals available.</p>"
    proj_by_key = {p.category.key: p for p in d.projections}
    rows = []
    for edge in d.edges:
        cat = edge.category
        p = proj_by_key.get(cat.key)
        rows.append(
            "<tr>"
            f"<td class='l'><strong>{_e(cat.key)}</strong> <span class='muted'>{_e(cat.name)}</span></td>"
            f"<td data-v='{edge.mine or 0}'>{_fmt(cat, edge.mine)}</td>"
            f"<td data-v='{edge.theirs or 0}'>{_fmt(cat, edge.theirs)}</td>"
            f"<td>{_leader_pill(edge.leader)}</td>"
            f"<td data-v='{edge.closeness or 0}'>{_margin_bar(edge)}</td>"
            f"<td data-v='{(p.mine_projected if p else 0) or 0}'>{_fmt(cat, p.mine_projected) if p else '-'}</td>"
            f"<td data-v='{(p.theirs_projected if p else 0) or 0}'>{_fmt(cat, p.theirs_projected) if p else '-'}</td>"
            f"<td>{_leader_pill(p.leader_projected) if p else ''}</td>"
            "</tr>"
        )
    return (
        "<h2>Current matchup</h2>"
        "<div class='legend'><span><span class='sw' style='background:var(--lead)'></span>I lead</span>"
        "<span><span class='sw' style='background:var(--trail)'></span>I trail</span>"
        "<span>bar length = gap as a share of the larger total</span></div>"
        "<div class='card'><table class='sortable'><thead><tr>"
        "<th class='l'>Category</th><th>Me</th><th>Them</th><th>Lead</th><th>Gap</th>"
        "<th>Me (proj.)</th><th>Them (proj.)</th><th>Proj. lead</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _projection_section(d: Dashboard) -> str:
    if not d.projections:
        return ""
    rows = []
    for p in d.projections:
        rows.append(
            f"<tr><td class='l'><strong>{_e(p.category.key)}</strong></td>"
            f"<td class='l'>{_pair_bars(p.category, p.mine_now, p.mine_projected, p.theirs_now, p.theirs_projected)}</td>"
            f"<td>{_leader_pill(p.leader_projected)}</td></tr>"
        )
    mg = d.my_projection.games_remaining if d.my_projection else 0
    og = d.opp_projection.games_remaining if d.opp_projection else 0
    return (
        "<h2>Category projections to end of period</h2>"
        f"<div class='legend'><span><span class='sw' style='background:var(--me)'></span>Me (solid = so far, "
        f"light = projected; {mg} active games left)</span>"
        f"<span><span class='sw' style='background:var(--them)'></span>Them ({og} active games left)</span></div>"
        "<div class='card'><table><thead><tr><th class='l'>Category</th><th class='l'>So far / projected</th>"
        f"<th>Proj. lead</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _roster_section(d: Dashboard) -> str:
    if not d.my_roster:
        return ""
    cats = d.categories
    proj = {p.player_id: p for p in d.my_roster_projected}
    left = d.outlook.remaining_by_player if d.outlook else {}
    head = "".join(f"<th>{_e(c.key)}</th>" for c in cats)
    rows = []
    order = {"active": 0, "reserve": 1, "ir": 2}
    for p in sorted(d.my_roster, key=lambda x: order[x.status]):  # stable: keeps Fantrax slot order
        pp = proj.get(p.player_id)
        cells = "".join(
            f"<td data-v='{p.per_game.get(c.key) or 0}' title='projected {_fmt(c, pp.per_game.get(c.key) if pp else None, per_game=True)}'>"
            f"{_fmt(c, p.per_game.get(c.key), per_game=True)}</td>"
            for c in cats
        )
        status = {"active": "", "reserve": "Res", "ir": "IR"}[p.status]
        rows.append(
            f"<tr class='{p.status}'><td class='l'>{_e(p.name)}</td><td class='l'>{_e(p.slot)}</td>"
            f"<td class='l muted'>{_e(status)}</td><td class='l'>{_e(p.nba_team)}</td>"
            f"<td data-v='{p.games or 0}'>{p.games:g}</td><td data-v='{left.get(p.player_id, 0)}'>{left.get(p.player_id, 0)}</td>"
            f"<td class='l muted'>{_e(p.next_game)}</td>{cells}</tr>"
            if p.games is not None
            else f"<tr><td class='l'>{_e(p.name)}</td><td class='l'>{_e(p.slot)}</td><td class='l muted'>{_e(status)}</td>"
            f"<td class='l'>{_e(p.nba_team)}</td><td>-</td><td>{left.get(p.player_id, 0)}</td>"
            f"<td class='l muted'>{_e(p.next_game)}</td>{cells}</tr>"
        )
    avg = "".join(f"<td>{_fmt(c, d.league_average.get(c.key))}</td>" for c in cats)
    return (
        "<h2>My roster - category stats (per game, season to date)</h2>"
        "<p class='sub'>Hover a value for Fantrax's projected per-game number. Click a header to sort.</p>"
        "<div class='card'><table class='sortable'><thead><tr><th class='l'>Player</th><th class='l'>Slot</th>"
        f"<th class='l'></th><th class='l'>Team</th><th>GP</th><th>G left</th><th class='l'>Next</th>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"<tfoot><tr><td class='l muted' colspan='7'>League average team total this period</td>{avg}</tr></tfoot>"
        "</table></div>"
    )


def _games_section(d: Dashboard) -> str:
    o = d.outlook
    if o is None:
        return "<h2>Games this period</h2><p class='muted'>No schedule available.</p>"
    dates = o.remaining_dates
    head = "".join(f"<th>{dd:%a}<br><span class='muted'>{dd:%-m/%-d}</span></th>" for dd in dates)
    rows = []
    for p in sorted(d.my_roster, key=lambda x: {"active": 0, "reserve": 1, "ir": 2}[x.status]):
        cells = []
        for dd in dates:
            game = d.schedule.get(p.nba_team, {}).get(dd)
            if game is None or game.final:
                cells.append("<td class='g'><span class='cell off'></span></td>")
            else:
                kind = "on" if p.status == "active" else "res"
                label = f"{'' if game.home else '@'}{game.opponent} {game.detail}".strip()
                cells.append(f"<td class='g' title='{_e(label)}'><span class='cell {kind}'></span></td>")
        tag = {"active": "", "reserve": " (Res)", "ir": " (IR)"}[p.status]
        total = o.remaining_by_player.get(p.player_id, 0)
        rows.append(f"<tr><td class='l'>{_e(p.name)}<span class='muted'>{tag}</span></td>{''.join(cells)}<td>{total}</td></tr>")
    foot = []
    for day in o.days:
        if day.overflow:
            foot.append(f"<td class='status-warn' title='{day.count} active players play; {day.slots} slots'>{day.count}</td>")
        else:
            foot.append(f"<td>{day.count}</td>")
    bench_days = sum(1 for day in o.days for p in d.my_roster if p.status != "active" and d.schedule.get(p.nba_team, {}).get(day.date))
    return (
        "<h2>Games this period</h2>"
        "<div class='tiles'>"
        + _tile("Active games left", str(o.active_remaining), "scheduled for active players")
        + _tile("Usable", str(o.usable_remaining), f"fit in {o.days[0].slots if o.days else 10} active slots per day")
        + _tile("Bench games left", str(bench_days), "reserve/IR players with games")
        + _tile("Max games", str(o.max_games) if o.max_games is not None else "none", "period cap")
        + "</div>"
        "<div class='legend' style='margin-top:12px'><span><span class='sw' style='background:var(--seq-3)'></span>active player game</span>"
        "<span><span class='sw' style='background:var(--seq-1)'></span>bench player game</span>"
        "<span>&#9888; = more active players than slots that day</span></div>"
        "<div class='card'><table class='grid'><thead><tr><th class='l'>Player</th>"
        f"{head}<th>Left</th></tr></thead><tbody>{''.join(rows)}</tbody>"
        f"<tfoot><tr><td class='l'>Active playing</td>{''.join(foot)}<td>{o.active_remaining}</td></tr></tfoot></table></div>"
    )


def _help_section(d: Dashboard) -> str:
    if not d.help:
        return ""
    closeness = {e.category.key: e for e in d.edges}
    def _closeness(h: CategoryHelp) -> float:
        edge = closeness.get(h.category.key)
        return edge.closeness if edge is not None and edge.closeness is not None else 9.0

    ordered = sorted(d.help, key=_closeness)
    buttons = []
    panels = []
    for i, h in enumerate(ordered):
        cat = h.category
        edge = closeness.get(cat.key)
        pill = _leader_pill(edge.leader) if edge else ""
        gap = f" {edge.closeness * 100:.0f}% gap" if edge and edge.closeness is not None else ""
        buttons.append(
            f"<button data-cat='{_e(cat.key)}' aria-selected='{'true' if i == 0 else 'false'}'>"
            f"{_e(cat.key)} {pill}<span class='muted'>{_e(gap)}</span></button>"
        )
        max_impact = max((c.impact for c in h.candidates), default=0.0)
        rows = []
        for c in h.candidates:
            p = c.player
            rows.append(
                f"<tr><td class='l'>{_e(p.name)}</td><td class='l'>{_e(p.nba_team)} <span class='muted'>{_e('/'.join(p.positions))}</span></td>"
                f"<td class='l muted'>{_e(p.availability)}</td>"
                f"<td data-v='{c.per_game}'>{_fmt(cat, c.per_game, per_game=True)}</td>"
                f"<td data-v='{p.per_game.get(cat.key) or 0}' class='muted'>{_fmt(cat, p.per_game.get(cat.key), per_game=True)}</td>"
                f"<td data-v='{p.games_remaining}'>{p.games_remaining}</td>"
                f"<td class='l muted'>{_e(', '.join(p.next_games))}</td>"
                f"<td data-v='{c.impact}'>{_impact_bar(c.impact if cat.higher_is_better else max_impact - c.impact + 0.1, max_impact + 0.1)} "
                f"{_fmt(cat, c.impact, per_game=cat.is_rate)}</td></tr>"
            )
        verb = "lowest" if not cat.higher_is_better else "most"
        unit = "projected per game" if cat.is_rate else f"{verb} added over games left (proj. per game x games)"
        panels.append(
            f"<div class='help-panel' data-cat='{_e(cat.key)}' {'' if i == 0 else 'hidden'}>"
            f"<h3>{_e(cat.name)} - {_e(unit)}</h3>"
            "<table class='sortable'><thead><tr><th class='l'>Player</th><th class='l'>Team</th><th class='l'>Avail.</th>"
            f"<th>Proj/G</th><th>YTD/G</th><th>G left</th><th class='l'>Games</th><th>Impact</th></tr></thead>"
            f"<tbody>{''.join(rows) or '<tr><td colspan=8 class=muted>nobody with games left</td></tr>'}</tbody></table></div>"
        )
    return (
        "<h2>Available players who help a category</h2>"
        f"<p class='sub'>{len(d.available)} available players (top of the Fantrax Score list), ranked by what they'd add "
        "over the games left this period. Tabs are ordered closest category first.</p>"
        f"<div class='card'><div class='tabs'>{''.join(buttons)}</div>{''.join(panels)}</div>"
    )


def _league_section(d: Dashboard) -> str:
    if not d.all_matchups:
        return ""
    rows = []
    for m in d.all_matchups:
        mark = " <span class='pill me'>me</span>" if m.side(d.my_team_id) else ""
        rows.append(
            f"<tr><td class='l'>{_e(m.away.team_name)}{mark if m.away.team_id == d.my_team_id else ''}</td>"
            f"<td>{_wlt((m.away.wins, m.away.losses, m.away.ties))}</td>"
            f"<td>{_wlt((m.home.wins, m.home.losses, m.home.ties))}</td>"
            f"<td class='l'>{_e(m.home.team_name)}{mark if m.home.team_id == d.my_team_id else ''}</td></tr>"
        )
    return (
        "<h2>All matchups this period</h2><div class='card'><table><thead><tr><th class='l'>Away</th><th>W-L-T</th>"
        f"<th>W-L-T</th><th class='l'>Home</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _footer(d: Dashboard) -> str:
    notes = "".join(f"<li>{_e(n)}</li>" for n in d.notes)
    fetched = sorted(v for v in d.fetched_at.values() if v)
    when = f"Data fetched {fetched[0][:16].replace('T', ' ')} UTC" if fetched else "Data from saved payloads"
    return (
        f"<footer>{_e(when)}. Period totals from Fantrax standings; per-game projections from Fantrax; "
        "games from the roster schedule grids."
        f"{'<ul class=notes>' + notes + '</ul>' if notes else ''}</footer>"
    )


def render(d: Dashboard) -> str:
    title = f"{d.my_team_name} - period {d.period or '?'}"
    body = "".join(
        [
            _header(d),
            _tiles(d),
            _matchup_section(d),
            _projection_section(d),
            _games_section(d),
            _help_section(d),
            _roster_section(d),
            _league_section(d),
            _footer(d),
        ]
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_e(title)}</title><style>{CSS}</style></head>"
        f"<body><main>{body}</main><script>{JS}</script></body></html>"
    )


__all__ = ["render"]
