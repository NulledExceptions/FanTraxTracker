"""Typer CLI entry point (`fantrax`).

Phase 0 commands only. `sync`, `team`, `available`, `matchup`, `standings`, `report` and
`db` are added in Phase 1+ once the discovery report has fixed the schema.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from fantrax_analytics import __version__
from fantrax_analytics.adapters.auth import ClientFactory
from fantrax_analytics.config import Settings, load_settings
from fantrax_analytics.discover import Discovery
from fantrax_analytics.exceptions import FantraxError
from fantrax_analytics.logging_setup import bind_run_context, configure_logging, get_logger, new_run_id

app = typer.Typer(
    name="fantrax",
    help="Local analytics for a Fantrax NBA league.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()
err_console = Console(stderr=True)
log = get_logger(__name__)


class State:
    settings: Settings
    json_output: bool = False


state = State()


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="DEBUG logging")] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Machine-readable output and JSON logs")
    ] = False,
    version: Annotated[bool, typer.Option("--version", help="Print version and exit")] = False,
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()
    try:
        state.settings = load_settings(log_level="DEBUG") if verbose else load_settings()
    except ValidationError as exc:
        err_console.print(f"[red]Invalid configuration:[/red]\n{exc}")
        raise typer.Exit(code=2) from exc
    state.json_output = json_output
    configure_logging(state.settings.log_dir, state.settings.log_level, json_console=json_output)
    bind_run_context(league_id=state.settings.league_id, season=state.settings.season, run_id=new_run_id())


@app.command()
def discover(
    domain: Annotated[
        list[str] | None, typer.Option("--domain", "-d", help="Only run these probe domains (repeatable)")
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Bypass the disk cache")] = False,
    skip_fallback: Annotated[bool, typer.Option(help="Skip the undocumented fxpa probes")] = False,
    skip_low_priority: Annotated[bool, typer.Option(help="Skip draft/ADP/player-id probes")] = False,
) -> None:
    """Phase 0: probe every endpoint for this league and write discovery/ENDPOINT_REPORT.md."""
    settings = state.settings
    if not settings.secret_id_value:
        err_console.print(
            "[yellow]FANTRAX_USER_SECRET_ID is not set — getLeagues (team ID resolution) and the "
            "'secret' auth level will be skipped.[/yellow]"
        )
    factory = ClientFactory(settings, use_cache=not no_cache)
    discovery = Discovery(
        settings,
        factory,
        include_fallback=not skip_fallback,
        include_low_priority=not skip_low_priority,
        only_domains=domain,
    )
    try:
        results = discovery.run()
    except FantraxError as exc:
        err_console.print(f"[red]Discovery aborted:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    report_path = discovery.write_report()

    if state.json_output:
        console.print_json(json.dumps([r.__dict__ for r in results], default=str))
    else:
        table = Table(title="Endpoint discovery", show_lines=False)
        for col in ("Domain", "Status", "Source", "Auth", "HTTP", "KB", "Missing"):
            table.add_column(col)
        colors = {"AVAILABLE": "green", "PARTIAL": "yellow", "UNAVAILABLE": "red", "SKIPPED": "dim"}
        for r in results:
            kb = f"{r.size_bytes / 1024:.0f}" if r.size_bytes is not None else "-"
            table.add_row(
                r.domain,
                f"[{colors[r.status]}]{r.status}[/{colors[r.status]}]",
                r.source,
                r.auth_level,
                str(r.http_status or "-"),
                kb,
                ", ".join(r.missing) or "-",
            )
        console.print(table)
        if discovery.my_team_id:
            console.print(f"My team ID: [bold]{discovery.my_team_id}[/bold] (written to {settings.env_file})")
        else:
            console.print(
                "[yellow]My team ID could not be resolved — set FANTRAX_MY_TEAM_ID manually.[/yellow]"
            )
        console.print(f"Report: [bold]{report_path}[/bold]")

    counts = {
        s: sum(1 for r in results if r.status == s)
        for s in ("AVAILABLE", "PARTIAL", "UNAVAILABLE", "SKIPPED")
    }
    log.info("discover.done", **counts)
    core = {"league_info", "rosters_current", "standings", "matchups_current"}
    if any(r.domain in core and r.status == "UNAVAILABLE" for r in results):
        raise typer.Exit(code=1)


@app.command()
def auth() -> None:
    """Capture a browser session (NOT built yet — see the discovery report)."""
    err_console.print(
        "The Selenium cookie-capture flow is intentionally not implemented until discovery shows the "
        "undocumented endpoints need a logged-in session.\n"
        f"To test the cookie auth level now, export your fantrax.com cookies as JSON "
        f"(list of {{name, value, domain, path}}) to {state.settings.cookie_file} "
        "and rerun `fantrax discover`."
    )
    raise typer.Exit(code=2)


@app.command(name="config")
def show_config() -> None:
    """Print the effective configuration (secret masked)."""
    data = state.settings.model_dump(mode="json")
    data["user_secret_id"] = "***" if state.settings.user_secret_id else None
    if state.json_output:
        console.print_json(json.dumps(data, default=str))
    else:
        for k, v in data.items():
            console.print(f"{k:<22} {v}")


if __name__ == "__main__":
    app()
