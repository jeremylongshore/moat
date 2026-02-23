# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Moat

Policy-enforced execution and trust layer for AI agents. MCP-first. Every capability call produces a receipt, an outcome event, and a policy decision record. Default-deny: capabilities start inaccessible until explicitly unlocked via PolicyBundles.

## Build & Dev Commands

```bash
# First-time setup (creates venv + installs everything)
make setup
source .venv/bin/activate

# Install all packages in editable mode (if venv already active)
make install

# Start all 4 services locally with hot-reload (ports 8001-8004)
make dev

# Run the full CI gate (lint + typecheck + test)
make ci

# Individual checks
make lint          # ruff check + ruff format --check
make format        # ruff format + ruff check --fix (writes changes)
make typecheck     # mypy (continue-on-error, non-blocking)
make test          # pytest across all packages and services
make test-coverage # pytest with coverage report

# Run a single test file or test
pytest packages/core/tests/test_policy.py -v
pytest packages/core/tests/test_policy.py::test_name -v

# End-to-end demo (requires services running)
make demo

# Docker
make docker-up     # docker-compose stack (infra/local/)
make docker-down
```

## Architecture

Four FastAPI microservices + one shared library, all Python 3.11+ (CI runs 3.12):

```
packages/core (moat-core)     Shared Pydantic v2 models, policy engine, auth, redaction, DB ORM
  └── moat_core/              Import everything from top-level: `from moat_core import Receipt, evaluate_policy`

services/
  control-plane (:8001)       Capability registry, connections, vault abstraction
  gateway (:8002)             Execution choke-point: policy → idempotency → adapter → receipt → trust-plane
  trust-plane (:8003)         Reliability scoring, outcome event ingestion, stats
  mcp-server (:8004)          Agent-facing tool surface (REST MVP; MCP SDK stdio planned)
```

### Request flow (gateway execute pipeline)

1. Fetch capability from control-plane (cached 5min via `capability_cache`; falls back to synthetic stub if control-plane unreachable)
2. Validate capability status is `active`
3. Evaluate policy via `policy_bridge` (wires real `moat_core.policy.evaluate_policy`; default-deny if no PolicyBundle registered; fails closed on errors)
4. Check idempotency key — return cached receipt if seen before (DB-backed, 24h TTL)
5. Dispatch to provider adapter (`AdapterRegistry` in `app.adapters.base`; falls back to `StubAdapter`)
6. Build Receipt
7. Emit OutcomeEvent to trust-plane (async, best-effort)
8. Store in idempotency cache (success only)
9. Return Receipt
10. (Background) Post IRSB receipt via `hooks/irsb_receipt.py` (dry-run by default; set `IRSB_DRY_RUN=false` for on-chain)
11. (Background) Record spend for budget tracking via `policy_bridge.record_spend()` — currently 1 cent per successful call

### Key domain models (`moat_core.models`)

All models are frozen (immutable) Pydantic v2 with UTC datetimes:
- **CapabilityManifest** — registry entry with semver, risk_class, domain_allowlist, input/output schemas
- **Receipt** — audit record with SHA-256 hashed inputs/outputs (no raw secrets)
- **OutcomeEvent** — lightweight analytics event for SLO tracking
- **PolicyBundle** — tenant-scoped rules: allowed_scopes, budget_daily, domain_allowlist, require_approval
- **PolicyDecision** — immutable evaluation result with rule_hit and timing

### Policy engine (`moat_core.policy.evaluate_policy`)

Priority-ordered, first failure short-circuits:
1. `no_policy_bundle` (None → deny)
2. `scope_not_allowed`
3. `budget_daily_exceeded`
4. `domain_allowlist_conflict`
5. `require_approval`
6. `all_checks_passed` → allowed

### Database layer (`moat_core.db`)

Async SQLAlchemy with ORM rows: `CapabilityRow`, `ConnectionRow`, `ReceiptRow`, `OutcomeEventRow`, `PolicyBundleRow`, `IdempotencyCacheRow`. All services call `init_tables()` at startup.

- **Local dev (no Docker)**: SQLite via `aiosqlite` — each service uses its own `*_dev.db` file
- **Docker**: shared Postgres 16 via `asyncpg` (connection string from `DATABASE_URL` env var)
- **Redis**: present in docker-compose but not yet wired into application code (v2 path for rate-limiting/caching)

The only remaining in-memory stores are the `policy_bridge` bundle registry and daily spend tracker.

### Authentication (`moat_core.auth`)

JWT-based: `JWTConfig`, `decode_jwt()`, `create_jwt()`, FastAPI deps `get_current_tenant` / `get_optional_tenant` / `require_tenant`.

- **Local dev**: `MOAT_AUTH_DISABLED=true` — uses `X-Tenant-ID` header passthrough (defaults to `"dev-tenant"`)
- **Production**: `MOAT_JWT_SECRET` (min 32 chars) required; `configure_auth()` raises `RuntimeError` if auth disabled outside `local`/`test` environments
- The execute endpoint validates `body.tenant_id` matches the authenticated tenant (confused deputy guard)

### Adapter pattern

New providers implement `AdapterInterface` (ABC in `services/gateway/app/adapters/base.py`) and register with the module-level `AdapterRegistry` singleton. Routing: `execute.py` looks up adapters by `capability.get("provider")`.

Registered adapters:
- **StubAdapter** (`provider_name="stub"`) — development/testing, simulated 100-500ms latency
- **SlackAdapter** (`provider_name="slack"`) — Slack message delivery
- **LocalCLIAdapter** (`provider_name="local_cli"`) — GWI commands via `asyncio.create_subprocess_exec()` (no shell), 120s timeout, 1MB output cap, GitHub URL validation
- **HttpProxyAdapter** (`provider_name="http_proxy"`) — HTTPS proxy for sandboxed agents. Enforces domain allowlist + private IP blocking. Note: capability name is `http.proxy` but adapter provider name is `http_proxy`
- **OpenAIProxyAdapter** (`provider_name="openai"`) — OpenAI API proxy, injects API key server-side, explicit allowlist of forwarded params, forces `stream=false`

### IRSB receipt hook

Post-execution hook at `services/gateway/app/hooks/irsb_receipt.py` fires as a background task after every successful gateway execution. Default **dry-run** (`IRSB_DRY_RUN=true`).

- 5-hash computation (keccak256): intent, result, constraints, route, evidence
- ABI-encoded message hash over 11 fields, EIP-191 signing with `eth_account`
- On-chain submission to IntentReceiptHub at `0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c` on Sepolia
- Fallback chain: `dry_run` → `dry_run_no_rpc` → `dry_run_no_key`
- Intent hash is a **placeholder** — not yet a Canonical Intent Envelope per `041-AT-SPEC`; only hash computation will change when CIE lands

### Policy bridge

`services/gateway/app/policy_bridge.py` wires `moat_core.policy.evaluate_policy()`. Includes in-memory PolicyBundle registry and daily spend tracking.

**Architectural note**: This policy engine is a stepping stone. When IRSB Phase 2 lands, it will be replaced by Cedar policies inside the Intentions Gateway. Keep rules simple and portable.

### Trust plane scoring

DB-backed rolling 7-day window. Configurable thresholds:
- `MIN_SUCCESS_RATE_7D=0.80` — below this after 5+ executions, `should_hide()` suppresses capability
- `MAX_P95_LATENCY_MS=10000` — above this, `should_throttle()` kicks in
- `verified` flag requires 10+ executions AND success rate >= threshold

## Monorepo layout

- Each service has its own `pyproject.toml` with hatchling build and `app/` package
- Root `pyproject.toml` configures shared ruff/mypy/pytest settings (line-length 120)
- Services depend on `moat-core` as a pip dependency (installed editable via `-e packages/core`)
- `infra/local/` — docker-compose (Postgres 16 + Redis 7), `.env.example`
- `000-docs/` — 11 design docs using doc-filing system (NNN-CC-ABCD format); check relevant docs before architectural decisions
- `scripts/dev.sh` — starts all 4 uvicorn processes with `--reload`
- `scripts/demo.sh` — registers a capability, executes it, fetches stats

### Environment variables (key ones)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MOAT_ENV` | `local` | Controls OpenAPI docs exposure (only in local/test/dev) |
| `MOAT_AUTH_DISABLED` | `false` | Header-based tenant passthrough for dev |
| `MOAT_JWT_SECRET` | `""` | JWT signing key (min 32 chars in prod) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./X_dev.db` | Per-service DB; Postgres in Docker |
| `HTTP_PROXY_DOMAIN_ALLOWLIST` | `""` | Comma-separated allowed domains for http.proxy |
| `IRSB_DRY_RUN` | `true` | Set `false` for on-chain receipt submission |
| `SLACK_BOT_TOKEN` | `""` | Slack adapter token |

## HTTP Proxy Capability

The `http.proxy` capability enables sandboxed agents to make outbound HTTP requests through Moat with domain enforcement.

**PolicyBundle** registered in `services/gateway/app/main.py`:
- Scopes: `["http.get", "http.post"]`
- Domain allowlist: loaded from `HTTP_PROXY_DOMAIN_ALLOWLIST` env var
- Budget: $150/day (15000 cents)

**Usage from agent**: `POST /execute/http.proxy` with body `{"url": "https://api.github.com/...", "method": "GET"}`. Header `X-Tenant-ID: automaton` required when auth is disabled.

## Conventions

- **Commit format**: `<type>(<scope>): <subject>` — types: feat, fix, docs, test, ci, chore, refactor
- **Logging**: structured JSON to stdout, per-service. Sensitive fields auto-redacted via `RedactionMiddleware` and `moat_core.redaction`.
- **Secrets**: credentials live in vault abstraction (`control-plane/app/vault.py`); agents never see raw secrets. Receipt stores only SHA-256 hashes.
- **Request tracing**: `X-Request-ID` header propagated across services via middleware.
- **Security headers**: `SecurityHeadersMiddleware` on all services (HSTS, X-Frame-Options DENY, nosniff, no-cache).
- **Test markers**: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`, `@pytest.mark.docker`
- **asyncio**: `asyncio_mode = "auto"` — async tests don't need decorators.
- **Coverage floor**: `fail_under = 50` (configured in root `pyproject.toml`)
- **License**: Elastic License 2.0

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) — Python 3.12, 7 jobs:
- **lint** (ruff check + format)
- **typecheck** (mypy, continue-on-error)
- **test** (pytest + coverage, needs lint)
- **security** (pip-audit, needs test)
- **docker** (3x matrix: gateway, control-plane, trust-plane — BuildKit cache)
- **integration** (Docker Compose end-to-end, main-only: health checks, execute pipeline, policy default-deny)
