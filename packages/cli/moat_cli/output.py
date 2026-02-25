"""
moat_cli.output
~~~~~~~~~~~~~~~
Output formatting: JSON or rich tables.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


def print_json(data: Any) -> None:
    """Print data as formatted JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def print_receipt(receipt: dict[str, Any], json_output: bool = False) -> None:
    """Print an execution receipt."""
    if json_output:
        print_json(receipt)
        return

    table = Table(title="Execution Receipt")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Receipt ID", receipt.get("receipt_id", ""))
    table.add_row("Capability", receipt.get("capability_id", ""))
    table.add_row("Tenant", receipt.get("tenant_id", ""))
    table.add_row("Status", receipt.get("status", ""))
    table.add_row("Latency", f"{receipt.get('latency_ms', 0):.1f}ms")
    table.add_row("Cached", str(receipt.get("cached", False)))
    table.add_row("Risk Class", receipt.get("policy_risk_class", ""))
    table.add_row("Executed At", receipt.get("executed_at", ""))

    console.print(table)

    result = receipt.get("result", {})
    if result:
        console.print("\n[bold]Result:[/bold]")
        console.print_json(json.dumps(result, default=str))


def print_capabilities(data: dict[str, Any], json_output: bool = False) -> None:
    """Print a capabilities list."""
    if json_output:
        print_json(data)
        return

    items = data.get("items", [])
    if not items:
        console.print("[yellow]No capabilities found.[/yellow]")
        return

    table = Table(title=f"Capabilities ({data.get('total', len(items))} total)")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Provider", style="magenta")
    table.add_column("Version")
    table.add_column("Status")

    for item in items:
        table.add_row(
            item.get("capability_id", item.get("id", "")),
            item.get("name", ""),
            item.get("provider", ""),
            item.get("version", ""),
            item.get("status", ""),
        )

    console.print(table)


def print_stats(data: dict[str, Any], json_output: bool = False) -> None:
    """Print reliability stats."""
    if json_output:
        print_json(data)
        return

    table = Table(title=f"Stats: {data.get('capability_id', '')}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Success Rate (7d)", f"{data.get('success_rate_7d', 0):.1%}")
    table.add_row("P95 Latency", f"{data.get('p95_latency_ms', 0):.0f}ms")
    table.add_row("Total Executions (7d)", str(data.get("total_executions_7d", 0)))
    table.add_row("Verified", str(data.get("verified", False)))

    console.print(table)
