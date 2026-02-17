# Moat

**Policy-enforced execution and trust layer for AI agents. MCP-first.**

Moat is not an API marketplace. It is the verified execution layer where agents call **capabilities** (method-level tool contracts), not connectors. Every call produces a receipt, an outcome event, and a policy decision record.

**Interfaces:** MCP (primary) + REST/OpenAPI (fallback)
**License:** [Elastic License 2.0](LICENSE)

## Core Guarantees

- **Receipt on every call** - append-only audit trail, idempotency, replay-ready
- **Policy on every call** - scopes, budgets, domain allowlists, default-deny
- **Score on every call** - success rate, latency percentiles, verified badges
- **No open proxy** - capabilities declare allowed outbound domains; everything else is blocked
- **No raw secrets** - credentials live in a vault; agents never see them

## Architecture

| Service | Port | Role |
|---------|------|------|
| Control Plane | 8001 | Capability registry, connections, tenants |
| Gateway | 8002 | Execute, enforce policy, emit receipts |
| Trust Plane | 8003 | Reliability scoring, synthetic checks |
| MCP Server | 8004 | Agent-facing tool surface |

## Quick Start

```bash
git clone https://github.com/jeremylongshore/moat.git && cd moat
make install && bash scripts/dev.sh   # start all services
make demo                              # register → execute → receipt → stats
```

## Docs

All documentation is in [`000-docs/`](000-docs/) using the doc-filing system. See the [Standards Catalog](000-docs/000-DR-INDEX-standards-catalog.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Questions: [Discussions](https://github.com/jeremylongshore/moat/discussions). Security: [SECURITY.md](SECURITY.md).
