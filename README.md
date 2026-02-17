# Moat

**Verified Agent Capabilities Marketplace — MCP-first trust + policy + execution layer for agents.**

Moat is not a generic API marketplace. It is the **policy-enforced execution and trust layer** for AI agents. The atomic unit is a **Capability** (method-level tool contract), not a connector.

Every capability execution produces:
1. A **Receipt** (audit + replay-ready)
2. An **Outcome Event** (reliability scoring)
3. A **Policy Decision** record (allowed/denied + why)

MCP is the primary interface. REST/OpenAPI is the required fallback.

## Architecture

```
                    ┌──────────────┐
                    │  MCP Server  │  Agent-facing tool surface
                    │   :8004      │  (list/search/execute/stats)
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
    ┌──────────────┐ ┌──────────┐ ┌──────────────┐
    │Control Plane │ │ Gateway  │ │ Trust Plane  │
    │   :8001      │ │  :8002   │ │   :8003      │
    │              │ │          │ │              │
    │ - Catalog    │ │ - Policy │ │ - Scoring    │
    │ - Connections│ │ - Execute│ │ - Synthetic  │
    │ - Tenants    │ │ - Receipt│ │   checks     │
    └──────────────┘ └──────────┘ └──────────────┘
              │            │            │
              └────────────┴────────────┘
                     Postgres + Redis
```

## Quick Start

```bash
# Clone
git clone https://github.com/jeremylongshore/moat.git
cd moat

# Option A: Local dev (no Docker)
python3 -m venv .venv && source .venv/bin/activate
make install
bash scripts/dev.sh

# Option B: Docker
make docker-up

# Run the demo
make demo
```

## Project Structure

```
moat/
├── 000-docs/              # Blueprint documentation (flat)
│   ├── 000-moat-stack-strategy.md
│   ├── 001-architecture.md
│   ├── 002-request-flows.md
│   ├── 003-capability-spec.md
│   ├── 004-policy-spec.md
│   ├── 005-receipts-and-events.md
│   ├── 006-data-model.md
│   ├── 007-security.md
│   ├── 008-trust-plane.md
│   └── 009-mcp-and-rest-apis.md
├── packages/
│   ├── core/              # Shared types, schemas, policy engine, receipts
│   └── sdk/               # Client SDK (REST + MCP helpers)
├── services/
│   ├── control-plane/     # Capability registry, connections, tenants
│   ├── gateway/           # Execute capabilities, enforce policy, emit receipts
│   ├── trust-plane/       # Reliability scoring, synthetic checks
│   └── mcp-server/        # MCP tool surface for agents
├── infra/local/           # Docker Compose for local dev
├── scripts/               # Dev and demo scripts
└── .github/workflows/     # CI pipeline
```

## How It Works

### 1. Register a Capability

A capability is a method-level tool contract (e.g., `slack.post_message`).

```bash
curl -X POST http://localhost:8001/capabilities \
  -H "Content-Type: application/json" \
  -d '{
    "name": "slack.post_message",
    "version": "1.0.0",
    "provider": "slack",
    "method": "post_message",
    "description": "Post a message to a Slack channel",
    "scopes": ["slack.post_message"],
    "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}}},
    "output_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
    "risk_class": "medium",
    "domain_allowlist": ["slack.com", "api.slack.com"]
  }'
```

### 2. Execute via Gateway

Every execution enforces policy, produces a receipt, and emits an outcome event.

```bash
curl -X POST http://localhost:8002/execute/slack.post_message \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-001",
    "scope": "slack.post_message",
    "params": {"channel": "#general", "text": "Hello from Moat!"},
    "idempotency_key": "demo-001"
  }'
```

### 3. Check Trust Stats

```bash
curl http://localhost:8003/capabilities/slack.post_message/stats
```

### 4. Use via MCP

Agents call capabilities through the MCP tool surface:

```bash
curl -X POST http://localhost:8004/tools/capabilities.execute \
  -H "Content-Type: application/json" \
  -d '{
    "capability_id": "slack.post_message",
    "params": {"channel": "#general", "text": "Hello from agent!"},
    "idempotency_key": "agent-run-001",
    "tenant_id": "tenant-001"
  }'
```

## How Receipts + Policy + Trust Work

**Every capability execution must produce three artifacts:**

| Artifact | Purpose | Moat Built |
|----------|---------|------------|
| Receipt | Append-only audit trail, idempotency | Trust + Governance |
| Outcome Event | Success/failure/latency metrics | Data + Trust |
| Policy Decision | Allowed/denied + which rule | Governance |

This is the key design decision that makes all moats compound automatically.

## Adding a New Capability

1. Define the `CapabilityManifest` (see `003-capability-spec.md`)
2. Implement an adapter in `services/gateway/app/adapters/`
3. Register the adapter in the `AdapterRegistry`
4. Register the capability via the control plane API
5. The trust plane will automatically start scoring it

## Development

```bash
make ci          # Lint + typecheck + test
make lint        # Ruff check + format check
make format      # Auto-format
make test        # Pytest
make typecheck   # mypy
make clean       # Clean caches
```

## The Seven Moats

See `000-docs/000-moat-stack-strategy.md` for the full strategy. MVP ships:

1. **Trust Moat** - Receipts + synthetic checks + reliability scoring
2. **Governance Moat** - Scopes + budgets + domain allowlists + policy decisions
3. **Execution Moat** - Idempotent, safe capability execution with normalized errors
4. **Distribution Moat** - MCP-native tool surface for agents

With architectural hooks for:
5. **Data Moat** - Aggregated telemetry + curated metadata
6. **Compute Moat** - Premium processing endpoints
7. **Ecosystem Moat** - SDK + contributor verification harness

## License

Proprietary - Intent Solutions
