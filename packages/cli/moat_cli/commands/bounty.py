"""
moat_cli.commands.bounty
~~~~~~~~~~~~~~~~~~~~~~~~
Scout-workflow shortcuts for bounty hunting.

Usage::

    moat bounty discover --platform algora --query "rust"
    moat bounty triage https://github.com/org/repo/issues/42
    moat bounty execute https://github.com/org/repo/issues/42
    moat bounty status https://github.com/org/repo/issues/42
"""

from __future__ import annotations

from typing import Annotated

import typer

bounty_app = typer.Typer(
    name="bounty",
    help="Scout-workflow commands for bounty hunting.",
    no_args_is_help=True,
)


def _get_client():  # type: ignore[no-untyped-def]
    from moat_cli.main import get_client

    return get_client()


def _is_json() -> bool:
    from moat_cli.main import is_json

    return is_json()


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


@bounty_app.command()
def discover(
    platform: Annotated[str, typer.Option("--platform", "-p", help="Bounty platform")] = "algora",
    query: Annotated[str, typer.Option("--query", "-q", help="Search query")] = "",
    language: Annotated[str | None, typer.Option("--language", "-l", help="Language filter")] = None,
    max_results: Annotated[int, typer.Option("--max", help="Max results")] = 20,
) -> None:
    """Search bounty platforms for open issues and funded bounties."""
    from moat_cli.output import print_json, print_receipt

    client = _get_client()

    # Build platform-specific URL
    platform_urls = {
        "algora": "https://console.algora.io/api/bounties",
        "gitcoin": "https://gitcoin.co/api/v0.1/bounties/",
        "polar": "https://api.polar.sh/v1/issues/search",
        "github": "https://api.github.com/search/issues",
    }

    base_url = platform_urls.get(platform)
    if not base_url:
        typer.echo(f"Unknown platform: {platform}. Supported: {list(platform_urls.keys())}", err=True)
        raise typer.Exit(code=1)

    if platform == "algora":
        url = f"{base_url}?limit={max_results}"
        if query:
            url = f"{base_url}?q={query}&limit={max_results}"
    elif platform == "github":
        q_parts = ["type:issue", "state:open", "label:bounty"]
        if query:
            q_parts.insert(0, query)
        if language:
            q_parts.append(f"language:{language}")
        url = f"{base_url}?q={'+'.join(q_parts)}&per_page={max_results}"
    elif platform == "gitcoin":
        url = f"{base_url}?is_open=true&limit={max_results}"
        if query:
            url += f"&keyword={query}"
    else:  # polar
        url = f"{base_url}?have_badge=true&limit={max_results}"
        if query:
            url += f"&q={query}"

    try:
        result = client.execute(
            capability_id="http.proxy",
            params={"url": url, "method": "GET"},
        )
        if _is_json():
            print_json({"platform": platform, "query": query, "receipt": result})
        else:
            print_receipt(result, json_output=False)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# triage
# ---------------------------------------------------------------------------


@bounty_app.command()
def triage(
    url: Annotated[str, typer.Argument(help="GitHub issue or PR URL")],
) -> None:
    """Triage a GitHub issue via GWI — returns complexity score and assessment."""
    from moat_cli.output import print_json, print_receipt

    client = _get_client()
    try:
        result = client.execute(
            capability_id="gwi.triage",
            params={"url": url},
        )
        if _is_json():
            print_json(result)
        else:
            print_receipt(result, json_output=False)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


@bounty_app.command("execute")
def execute_cmd(
    url: Annotated[str, typer.Argument(help="GitHub issue URL to fix")],
    command: Annotated[str, typer.Option("--command", "-c", help="GWI command")] = "issue-to-code",
) -> None:
    """Execute a fix for a GitHub issue using GWI."""
    from moat_cli.output import print_json, print_receipt

    client = _get_client()
    cap_id = f"gwi.{command}" if command in ("issue-to-code", "resolve") else "gwi.issue-to-code"

    try:
        result = client.execute(
            capability_id=cap_id,
            params={"url": url},
        )
        if _is_json():
            print_json(result)
        else:
            print_receipt(result, json_output=False)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@bounty_app.command()
def status(
    url: Annotated[str, typer.Argument(help="GitHub issue URL")],
    capability_id: Annotated[str, typer.Option("--cap", help="Capability for stats")] = "gwi.triage",
) -> None:
    """Check bounty status: triage score + trust stats."""
    from moat_cli.output import print_json, print_stats

    client = _get_client()
    try:
        stats_data = client.get_stats(capability_id)
        if _is_json():
            print_json({"url": url, "trust_stats": stats_data})
        else:
            typer.echo(f"Status for: {url}")
            print_stats(stats_data, json_output=False)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
