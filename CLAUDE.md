# Moat CLAUDE.md

Policy-enforced execution and trust layer for AI agents. MCP-first. Every capability call produces a receipt, an outcome event, and a policy decision record. Default-deny.

## Build & Dev

```bash
make setup && source .venv/bin/activate  # First time
make dev          # Start 4 services (ports 8001-8004)
make ci           # Full CI gate (lint + typecheck + test)
make lint         # ruff check + format --check
make format       # ruff format + ruff check --fix
make typecheck    # mypy (non-blocking)
make test         # pytest all packages/services
pytest packages/core/tests/test_policy.py -v  # Single test
```

## Architecture

Four FastAPI microservices + shared library (Python 3.11+, CI runs 3.12):

```
packages/core (moat-core)     Shared models, policy engine, auth, redaction, DB ORM
services/
  control-plane (:8001)       Capability registry, connections, vault
  gateway (:8002)             Execute pipeline: policy → idempotency → adapter → receipt
  trust-plane (:8003)         Reliability scoring, outcome events
  mcp-server (:8004)          Agent-facing tool surface (REST MVP)
```

**Import convention**: Always `from moat_core import X` — never reach into sub-modules.

## Key Patterns

- **Policy engine**: Priority-ordered, first-failure short-circuits. no_policy_bundle → scope → budget → domain → approval → allowed
- **Service lifespan**: configure_logging → configure_auth → init_tables → store init → (gateway: seed PolicyBundles)
- **Execute pipeline**: fetch capability → validate active → evaluate policy → idempotency check → adapter dispatch → receipt → outcome event → cache
- **Auth**: JWT-based. Dev: `MOAT_AUTH_DISABLED=true` uses `X-Tenant-ID` header. Prod: `MOAT_JWT_SECRET` required.
- **DB**: Async SQLAlchemy. Local: SQLite per-service. Docker: shared Postgres 16.
- **Adapters**: StubAdapter, SlackAdapter, LocalCLIAdapter, HttpProxyAdapter, OpenAIProxyAdapter, Web3Adapter, A2AProxyAdapter — implement `AdapterInterface` and register with `AdapterRegistry`
- **A2A Discovery**: Both mcp-server and gateway serve `/.well-known/agent.json` (AgentCard per A2A v0.3.0)
- **Agent Registry**: Control-plane CRUD at `/agents` — supports ERC-8004 on-chain identity + SPIFFE IDs
- **Skill Builder**: `POST /skill-builder/register` auto-discovers A2A agents and registers their skills as Moat capabilities
- **ERC-8004**: `services/gateway/app/erc8004/` — metadata generation, on-chain registry sync, IPFS pinning, ERC-6551 TBA
- **Intent Bridge**: Gateway `/intents/inbound` — routes on-chain intents through execution pipeline with dynamic tenant resolution via agent registry

## Testing

- Each service conftest: inserts service root on sys.path, creates temp SQLite, sets auth disabled
- Gateway tests: must register PolicyBundle for test capabilities (default-deny rejects otherwise)
- CI: uses `PYTHONPATH=services/<svc>` not editable installs (avoids `app` package collisions)
- Config: `asyncio_mode = "auto"`, `--import-mode=importlib`, coverage floor 50%

## Conventions

- **Commits**: `<type>(<scope>): <subject>` (feat, fix, docs, test, ci, chore, refactor)
- **License**: Elastic License 2.0
- **Secrets**: vault abstraction, receipts store SHA-256 hashes only
- **Tracing**: `X-Request-ID` propagated via middleware

## ERC-8004 / Web3 Modules

```
services/gateway/app/erc8004/
  metadata.py        Build ERC-8004 registration JSON from agent data
  registry_sync.py   On-chain register/update agent identity (dry-run default)
  ipfs.py            Pin metadata to IPFS via Pinata (dry-run default)
  tba.py             ERC-6551 Token Bound Account for agent NFTs (dry-run default)
```

Env vars: `ERC8004_DRY_RUN`, `ERC8004_IDENTITY_REGISTRY`, `ERC8004_OPERATOR_KEY`, `PINATA_JWT`, `IPFS_DRY_RUN`, `ERC6551_DRY_RUN`

## A2A Protocol Integration

- **Models** (`moat_core`): AgentSkill, AgentCard, A2ATask, A2AMessage, A2AArtifact, A2ATaskStatus
- **Discovery** (mcp-server + gateway): `GET /.well-known/agent.json` serves AgentCards
- **Agent Registry** (control-plane): `POST/GET/PATCH/DELETE /agents` with ERC-8004 + SPIFFE fields
- **A2A Proxy Adapter** (gateway): Forwards execution to remote A2A agents via JSON-RPC tasks/send
- **Skill Builder** (gateway): `POST /skill-builder/register` → discovers agent → registers skills as capabilities

## Reference

For detailed docs (error hierarchy, model fields, adapter specifics, env vars, IRSB hook): see `000-docs/`
