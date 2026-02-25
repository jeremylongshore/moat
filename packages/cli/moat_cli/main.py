"""
moat_cli.main
~~~~~~~~~~~~~
Typer application entry point for the ``moat`` CLI.

Usage::

    moat execute gwi.triage --params '{"url":"https://github.com/org/repo/issues/42"}'
    moat list --provider stub
    moat search "openai"
    moat stats gwi.triage
    moat register --name my-cap --provider acme --version 1.0.0
    moat bounty discover --platform algora
    moat bounty triage https://github.com/org/repo/issues/42 --json

Environment variables for service URLs::

    MOAT_GATEWAY_URL       (default: http://localhost:8002)
    MOAT_CONTROL_PLANE_URL (default: http://localhost:8001)
    MOAT_TRUST_PLANE_URL   (default: http://localhost:8003)
    MOAT_TENANT_ID         (default: automaton)
"""

from __future__ import annotations

from typing import Annotated

import typer

from moat_cli.client import MoatClient
from moat_cli.commands.bounty import bounty_app

app = typer.Typer(
    name="moat",
    help="Moat CLI — Policy-enforced execution layer for AI agents.",
    no_args_is_help=True,
)
app.add_typer(bounty_app, name="bounty")

# ---------------------------------------------------------------------------
# Global state (populated by the callback)
# ---------------------------------------------------------------------------

_client: MoatClient | None = None
_json_output: bool = False


def get_client() -> MoatClient:
    """Return the global MoatClient instance."""
    if _client is None:
        raise typer.Exit(code=1)
    return _client


def is_json() -> bool:
    """Return True if --json output was requested."""
    return _json_output


@app.callback()
def main(
    gateway_url: Annotated[
        str, typer.Option(envvar="MOAT_GATEWAY_URL", help="Gateway service URL")
    ] = "http://localhost:8002",
    control_plane_url: Annotated[
        str, typer.Option(envvar="MOAT_CONTROL_PLANE_URL", help="Control plane URL")
    ] = "http://localhost:8001",
    trust_plane_url: Annotated[
        str, typer.Option(envvar="MOAT_TRUST_PLANE_URL", help="Trust plane URL")
    ] = "http://localhost:8003",
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
    tenant_id: Annotated[str, typer.Option(envvar="MOAT_TENANT_ID", help="Tenant ID")] = "automaton",
) -> None:
    """Configure global options for all commands."""
    global _client, _json_output  # noqa: PLW0603
    _json_output = json_output
    _client = MoatClient(
        gateway_url=gateway_url,
        control_plane_url=control_plane_url,
        trust_plane_url=trust_plane_url,
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


@app.command()
def execute(
    capability_id: Annotated[str, typer.Argument(help="Capability ID to execute")],
    params: Annotated[str | None, typer.Option("--params", "-p", help="JSON params string")] = None,
    scope: Annotated[str, typer.Option(help="Permission scope")] = "execute",
    idempotency_key: Annotated[str | None, typer.Option("--key", "-k", help="Idempotency key")] = None,
) -> None:
    """Execute a capability through the Moat gateway."""
    import json

    from moat_cli.output import print_receipt

    parsed_params = json.loads(params) if params else {}

    client = get_client()
    try:
        result = client.execute(
            capability_id=capability_id,
            params=parsed_params,
            scope=scope,
            idempotency_key=idempotency_key,
        )
        print_receipt(result, json_output=is_json())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list")
def list_cmd(
    provider: Annotated[str | None, typer.Option("--provider", help="Filter by provider")] = None,
    status: Annotated[str | None, typer.Option("--status", help="Filter by status")] = None,
) -> None:
    """List capabilities from the registry."""
    from moat_cli.output import print_capabilities

    client = get_client()
    try:
        result = client.list_capabilities(provider=provider, status=status)
        print_capabilities(result, json_output=is_json())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query string")],
) -> None:
    """Search capabilities by name or description."""
    from moat_cli.output import print_capabilities

    client = get_client()
    try:
        result = client.search_capabilities(query)
        print_capabilities(result, json_output=is_json())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


@app.command()
def stats(
    capability_id: Annotated[str, typer.Argument(help="Capability ID")],
) -> None:
    """Get reliability stats for a capability."""
    from moat_cli.output import print_stats

    client = get_client()
    try:
        result = client.get_stats(capability_id)
        print_stats(result, json_output=is_json())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


@app.command()
def register(
    name: Annotated[str, typer.Option("--name", "-n", help="Capability name")],
    provider: Annotated[str, typer.Option("--provider", help="Provider name")],
    version: Annotated[str, typer.Option("--version", "-v", help="Semver version")] = "0.0.1",
    description: Annotated[str | None, typer.Option("--description", "-d", help="Description")] = None,
    method: Annotated[str, typer.Option(help="HTTP method + path")] = "POST /execute",
    risk_class: Annotated[str, typer.Option(help="Risk classification")] = "low",
) -> None:
    """Register a new capability with the control plane."""
    from moat_cli.output import print_json

    client = get_client()
    try:
        result = client.register_capability(
            name=name,
            provider=provider,
            version=version,
            description=description or "",
            method=method,
            risk_class=risk_class,
        )
        if is_json():
            print_json(result)
        else:
            typer.echo(f"Registered: {result.get('capability_id', result.get('id', 'unknown'))}")
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
