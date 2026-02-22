# Moat: Operator-Grade System Analysis

*For: DevOps Engineer / CTO*
*Generated: 2026-02-19*
*Version: 2890c49 (main)*

---

## 1. Executive Summary

### Business Purpose

Moat is a **policy-enforced execution and trust layer for AI agents**. It positions itself as "MCP-first" — the Model Context Protocol interface is the primary agent-facing surface. The core value proposition: every capability call produces a **receipt**, an **outcome event**, and a **policy decision record**. This creates compounding defensibility through trust signals (reliability scoring), governance (audit trails), and execution safety (idempotency, credential isolation).

The platform implements a **default-deny** security model: capabilities are inaccessible until explicitly unlocked via PolicyBundles. Agents never see raw credentials — all secrets live in a vault abstraction and are injected at execution time.

**Current status:** Early MVP. The architecture is clean and well-documented (9 design docs, 113-line CLAUDE.md, comprehensive README). The core domain models and policy engine are production-quality with 167 passing tests. However, all stateful components use in-memory dicts — nothing persists across restarts. The only adapter is a stub. Auth is hardcoded to disabled.

**Primary risk:** The system cannot be demonstrated to stakeholders or used in any real capacity until persistent storage and at least one real provider adapter are implemented. The wide architecture with stubs everywhere means no single path works end-to-end against real infrastructure.

### Operational Status Matrix

| Environment | Status | Uptime Target | Release Cadence |
|-------------|--------|---------------|-----------------|
| Production | Not deployed | N/A | N/A |
| Staging | Not deployed | N/A | N/A |
| Local (docker-compose) | Functional | N/A | On-demand |
| Local (uvicorn) | Functional | N/A | On-demand |

### Technology Stack

| Category | Technology | Version | Purpose |
|----------|------------|---------|---------|
| Language | Python | 3.11+ (3.12 in CI) | All services |
| Framework | FastAPI | >=0.110 | REST API layer |
| Validation | Pydantic | v2 | Domain models, settings |
| Database (planned) | PostgreSQL | 16-alpine | Primary data store |
| Cache (planned) | Redis | 7-alpine | Rate limiting, token cache |
| Containerization | Docker | Multi-stage builds | All services |
| Orchestration | Docker Compose | v2 | Local development |
| CI/CD | GitHub Actions | Ubuntu-latest | lint → typecheck → test → security |
| Linting | Ruff | >=0.4.0 | Fast Python linting + formatting |
| Type Checking | mypy | >=1.9.0 | Static type analysis |
| Testing | pytest | >=8.0 | Unit + integration tests |
| HTTP Client | httpx | >=0.27 | Async HTTP calls between services |

---

## 2. System Architecture

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AI AGENTS                                       │
│                    (Claude, GPT, custom agents)                             │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ MCP Protocol (REST/JSON for now)
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MCP SERVER (:8004)                                  │
│  Tools: capabilities.list, .search, .execute, .stats                        │
│  Proxies to: control-plane, gateway, trust-plane                           │
└──────────────┬─────────────────────────────────────────────┬────────────────┘
               │                                             │
               ▼                                             ▼
┌──────────────────────────┐                    ┌─────────────────────────────┐
│  CONTROL PLANE (:8001)   │                    │    TRUST PLANE (:8003)      │
│                          │                    │                             │
│  • Capability registry   │◄───────────────────│  • OutcomeEvent ingestion   │
│  • Connection management │    stats lookup    │  • 7-day success rate       │
│  • Vault abstraction     │                    │  • p95 latency scoring      │
│  • Tenant management     │                    │  • should_hide/throttle     │
└──────────────┬───────────┘                    └──────────────▲──────────────┘
               │                                               │
               │ capability lookup                             │ outcome events
               ▼                                               │
┌─────────────────────────────────────────────────────────────┴───────────────┐
│                           GATEWAY (:8002)                                    │
│                                                                             │
│  EXECUTION PIPELINE (10 steps):                                             │
│  1. Fetch capability (cached 5min)    6. Dispatch to adapter                │
│  2. Validate status = active          7. Build Receipt                      │
│  3. Evaluate policy (default-deny)    8. Emit OutcomeEvent (async)          │
│  4. Check idempotency key             9. Store in idempotency cache         │
│  5. Resolve credential from vault    10. Return Receipt                     │
│                                                                             │
│  Middleware: RequestID, Redaction, CORS                                     │
└─────────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROVIDER ADAPTERS                                    │
│                                                                             │
│  AdapterRegistry (module singleton)                                         │
│  ├── StubAdapter (provider="stub") ← ONLY IMPLEMENTATION                    │
│  └── [future: OpenAI, Anthropic, Slack, etc.]                              │
└─────────────────────────────────────────────────────────────────────────────┘

DATA STORES (docker-compose, NOT CONNECTED TO SERVICES):
┌──────────────────┐     ┌──────────────────┐
│  PostgreSQL 16   │     │     Redis 7      │
│  (moat database) │     │  (rate limiting) │
└──────────────────┘     └──────────────────┘
```

### Service Boundaries

| Service | Port | Responsibility | State | Test Coverage |
|---------|------|----------------|-------|---------------|
| control-plane | 8001 | Capability registry, connections, vault | In-memory dict | 0 tests |
| gateway | 8002 | Policy enforcement, execution, receipts | In-memory dict | 0 tests |
| trust-plane | 8003 | Outcome events, reliability scoring | In-memory deque | 0 tests |
| mcp-server | 8004 | Agent-facing MCP tool surface | Stateless proxy | 0 tests |
| moat-core | N/A | Shared models, policy engine, redaction | N/A | 167 tests |

### Data Flow

1. **Agent → MCP Server**: `POST /tools/capabilities.execute`
2. **MCP Server → Gateway**: `POST /execute/{capability_id}`
3. **Gateway → Control Plane**: `GET /capabilities/{id}` (cached)
4. **Gateway**: Policy evaluation (moat_core.policy.evaluate_policy)
5. **Gateway → Adapter**: Execute against provider (stub returns fake data)
6. **Gateway → Trust Plane**: `POST /events` (async, best-effort)
7. **Gateway → Agent**: Receipt with status, result, latency

---

## 3. Directory Analysis

### Project Structure

```
moat/
├── CLAUDE.md                    # AI assistant guidance (113 lines)
├── README.md                    # Quick start, architecture table
├── Makefile                     # Build commands (166 lines)
├── pyproject.toml               # Root ruff/mypy/pytest config
├── requirements-dev.txt         # Dev dependencies
│
├── packages/
│   └── core/                    # moat-core shared library
│       ├── pyproject.toml       # hatchling build
│       ├── moat_core/
│       │   ├── __init__.py      # Public API surface (all exports)
│       │   ├── models.py        # Pydantic v2 domain models (391 lines)
│       │   ├── policy.py        # Default-deny policy engine (249 lines)
│       │   ├── errors.py        # Exception hierarchy
│       │   ├── redaction.py     # Secret scrubbing + hashing
│       │   └── idempotency.py   # Key generation + store protocol
│       └── tests/               # 167 passing tests
│           ├── test_models.py
│           ├── test_policy.py
│           ├── test_redaction.py
│           ├── test_idempotency.py
│           └── test_errors.py
│
├── services/
│   ├── control-plane/           # Capability registry (:8001)
│   │   ├── Dockerfile           # Multi-stage, non-root
│   │   ├── pyproject.toml
│   │   └── app/
│   │       ├── main.py          # FastAPI app
│   │       ├── config.py        # pydantic-settings
│   │       ├── store.py         # In-memory CapabilityStore, ConnectionStore
│   │       ├── vault.py         # Stub vault abstraction
│   │       ├── logging_config.py
│   │       └── routers/
│   │           ├── capabilities.py
│   │           └── connections.py
│   │
│   ├── gateway/                 # Execution gateway (:8002)
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   └── app/
│   │       ├── main.py          # FastAPI + middleware
│   │       ├── config.py
│   │       ├── middleware.py    # RequestID, Redaction
│   │       ├── policy_bridge.py # Shim to moat_core.policy
│   │       ├── capability_cache.py
│   │       ├── idempotency_store.py  # In-memory
│   │       ├── adapters/
│   │       │   ├── base.py      # AdapterInterface + Registry
│   │       │   └── stub.py      # StubAdapter (only impl)
│   │       └── routers/
│   │           └── execute.py   # 10-step execution pipeline
│   │
│   ├── trust-plane/             # Reliability scoring (:8003)
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   └── app/
│   │       ├── main.py
│   │       ├── config.py
│   │       ├── scoring.py       # StatsStore, should_hide/throttle
│   │       └── routers/
│   │           ├── events.py
│   │           └── stats.py
│   │
│   └── mcp-server/              # Agent interface (:8004)
│       ├── Dockerfile
│       ├── pyproject.toml
│       └── app/
│           ├── main.py          # MCP tool manifest
│           ├── config.py
│           ├── http_client.py   # Upstream service calls
│           └── routers/
│               └── tools.py     # capabilities.list/.search/.execute/.stats
│
├── infra/
│   └── local/
│       ├── docker-compose.yml   # 6 services: pg, redis, 4 apps
│       └── .env.example         # Environment template
│
├── scripts/
│   ├── dev.sh                   # Start 4 uvicorn processes
│   └── demo.sh                  # End-to-end demo script
│
├── 000-docs/                    # Design documentation (9 files)
│   ├── 000-PP-STRT-moat-stack-strategy.md
│   ├── 001-AT-ARCH-platform-architecture.md
│   ├── 002-AT-FLOW-request-flows.md
│   ├── 003-DR-SPEC-capability-manifest.md
│   ├── 004-DR-SPEC-policy-and-governance.md
│   ├── 005-DR-SPEC-receipts-and-events.md
│   ├── 006-AT-DATA-data-model.md
│   ├── 007-AT-SECR-security-threat-model.md
│   ├── 008-AT-ARCH-trust-plane.md
│   └── 009-DR-SPEC-mcp-and-rest-apis.md
│
└── .github/
    └── workflows/
        └── ci.yml               # lint → typecheck → test → security
```

### Key Files by Function

| File | Purpose | Lines | Notes |
|------|---------|-------|-------|
| `packages/core/moat_core/models.py` | Domain models | 391 | Frozen Pydantic v2, production-quality |
| `packages/core/moat_core/policy.py` | Policy engine | 249 | Default-deny, 5 evaluation rules |
| `services/gateway/app/routers/execute.py` | Execution pipeline | 342 | Critical path, 0 tests |
| `services/gateway/app/middleware.py` | Request ID + redaction | 126 | Security middleware |
| `services/trust-plane/app/scoring.py` | Reliability scoring | 202 | 7-day rolling window |
| `services/mcp-server/app/routers/tools.py` | MCP tools | 303 | Agent-facing API |
| `Makefile` | Build automation | 166 | Comprehensive targets |

---

## 4. Operational Reference

### Development Setup

#### Prerequisites
- Python 3.11+ (3.12 recommended)
- Docker + Docker Compose (for Postgres/Redis)
- curl, jq (for demo script)

#### Local Development (Recommended)

```bash
# Clone and setup
git clone https://github.com/jeremylongshore/moat.git && cd moat

# Create venv + install all packages
make setup
source .venv/bin/activate

# Start all 4 services with hot-reload
make dev
# Services: :8001 (control-plane), :8002 (gateway), :8003 (trust-plane), :8004 (mcp-server)

# In another terminal, run the demo
make demo
```

#### Docker Development

```bash
# Copy env file
cp infra/local/.env.example infra/local/.env

# Start full stack (Postgres, Redis, 4 services)
make docker-up

# View logs
docker compose -f infra/local/docker-compose.yml logs -f

# Stop
make docker-down
```

### Build & Test Commands

| Command | Purpose | Duration |
|---------|---------|----------|
| `make setup` | Create venv + install everything | ~30s |
| `make install` | Install packages (venv active) | ~15s |
| `make dev` | Start 4 services with hot-reload | Persistent |
| `make ci` | Full CI gate (lint + typecheck + test) | ~5s |
| `make lint` | ruff check + format --check | ~1s |
| `make format` | ruff format (writes changes) | ~1s |
| `make typecheck` | mypy (non-blocking) | ~3s |
| `make test` | pytest all packages/services | ~2s |
| `make test-coverage` | pytest with coverage report | ~3s |
| `make demo` | End-to-end demo script | ~10s |
| `make clean` | Remove build artifacts | ~1s |

#### Running Single Tests

```bash
# Single file
pytest packages/core/tests/test_policy.py -v

# Single test
pytest packages/core/tests/test_policy.py::test_scope_not_allowed -v

# With coverage for specific module
pytest --cov=packages/core/moat_core --cov-report=term-missing packages/core/tests/
```

### CI/CD Pipeline

```yaml
# .github/workflows/ci.yml
# Triggers: push to main, PR to main

Jobs:
  lint:        ruff check + format --check
  typecheck:   mypy (continue-on-error: true)
  test:        pytest with coverage (needs: lint)
  security:    pip-audit (needs: test)
```

**Artifacts:**
- `coverage-report` (7 days): coverage.xml + htmlcov/
- `pip-audit-report` (30 days): pip-audit.json

### Health Checks

All services expose `/healthz`:

```bash
curl http://localhost:8001/healthz  # control-plane
curl http://localhost:8002/healthz  # gateway
curl http://localhost:8003/healthz  # trust-plane
curl http://localhost:8004/healthz  # mcp-server
```

### API Documentation

Each service has Swagger UI:
- Control Plane: http://localhost:8001/docs
- Gateway: http://localhost:8002/docs
- Trust Plane: http://localhost:8003/docs
- MCP Server: http://localhost:8004/docs

---

## 5. Security & Access

### Current Security Posture

| Control | Status | Notes |
|---------|--------|-------|
| Authentication | DISABLED | `MOAT_AUTH_DISABLED=true` in .env |
| Authorization | Stub | PolicyBundles not persisted |
| Secrets management | Stub | `vault.py` returns hardcoded responses |
| Credential isolation | Designed | Agents never see raw secrets (architecture enforced) |
| Audit logging | Partial | Receipts generated but not persisted |
| Request tracing | Implemented | X-Request-ID middleware |
| Secret redaction | Implemented | RedactionMiddleware + moat_core.redaction |
| TLS | Not configured | Plaintext HTTP between services |

### Security Design (Not Yet Implemented)

From `000-docs/007-AT-SECR-security-threat-model.md`:
- JWT validation with tenant_id claims
- SSRF prevention via domain allowlists
- Rate limiting via Redis
- Tamper-evident audit logs

### Sensitive Keys Auto-Redacted

```python
# services/gateway/app/middleware.py
_SENSITIVE_KEYS = frozenset({
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "credential", "credential_reference", "authorization", "x-api-key",
    "private_key", "client_secret", "access_token", "refresh_token"
})
```

---

## 6. Cost & Performance

### Infrastructure Costs (Projected)

| Component | Local Dev | Production Estimate |
|-----------|-----------|---------------------|
| Compute | $0 | Cloud Run: ~$50-200/mo |
| PostgreSQL | Docker | Cloud SQL: ~$30-100/mo |
| Redis | Docker | Memorystore: ~$30-50/mo |
| Total | $0 | ~$110-350/mo (low traffic) |

### Performance Characteristics

| Metric | Current | Target |
|--------|---------|--------|
| Gateway latency (stub) | 100-500ms (simulated) | <200ms (real adapters) |
| Policy evaluation | <1ms | <5ms |
| Capability cache TTL | 5 minutes | Configurable |
| Idempotency window | Indefinite (in-memory) | 24-48 hours (Redis) |

### Resource Requirements

```yaml
# Per-service minimums (Docker)
CPU: 0.25 cores
Memory: 256MB
```

---

## 7. Current State Assessment

### What's Working

✅ **Clean architecture** — 4 services with clear boundaries, shared core library
✅ **Domain models** — Production-quality Pydantic v2 models with validation
✅ **Policy engine** — Default-deny with 5 evaluation rules, fully tested
✅ **CI pipeline** — GitHub Actions with lint, typecheck, test, security scan
✅ **Documentation** — 9 design docs, CLAUDE.md, comprehensive README
✅ **Developer ergonomics** — Makefile with 15+ targets, hot-reload dev server
✅ **Security primitives** — Redaction middleware, credential isolation design
✅ **Docker setup** — Multi-stage builds, non-root containers, health checks

### Areas Needing Attention

⚠️ **CRITICAL: No persistent storage**
- `control-plane/app/store.py`: In-memory dict
- `gateway/app/idempotency_store.py`: In-memory dict
- `trust-plane/app/scoring.py`: In-memory deque
- Impact: Data lost on restart, cannot demo to stakeholders

⚠️ **CRITICAL: No real adapters**
- Only `StubAdapter` exists (returns fake data)
- Impact: Cannot prove value proposition against real providers

⚠️ **HIGH: No service-level tests**
- 167 tests in `packages/core/`, 0 tests for 4 services
- `services/gateway/app/routers/execute.py` (342 lines) has no coverage
- Impact: Regressions in critical execution path undetected

⚠️ **HIGH: Auth disabled**
- `MOAT_AUTH_DISABLED=true` hardcoded
- Multi-tenant system with no tenant isolation
- Impact: Cannot onboard real users

⚠️ **MEDIUM: MCP protocol not implemented**
- `mcp-server` is REST API, not MCP (JSON-RPC over stdio/SSE)
- README claims "MCP-first" but doesn't speak MCP
- Impact: Positioning mismatch

⚠️ **MEDIUM: mypy monorepo conflict**
- "Duplicate module named 'app'" error
- Non-blocking (`|| true`) but hides real type errors
- Impact: Reduced type safety

⚠️ **LOW: Code duplication**
- JSON logging formatter duplicated in 3 services
- Request ID middleware duplicated in 3 services
- Impact: Maintenance burden

### Immediate Priorities

| Priority | Issue | Impact | Owner | Effort |
|----------|-------|--------|-------|--------|
| P0 | Persistent storage (Postgres) | Blocking all demos | Backend | 2-3 days |
| P0 | One real adapter (Slack/OpenAI) | Proves value prop | Backend | 2-3 days |
| P1 | Service-level tests | Prevents regressions | Backend | 2-3 days |
| P1 | JWT authentication | Enables multi-tenancy | Backend | 2-3 days |
| P2 | Real MCP protocol | Matches positioning | Backend | 1 week |
| P2 | Fix mypy config | Type safety | DevOps | 1 day |

---

## 8. Quick Reference

### Command Map

| Capability | Command | Notes |
|------------|---------|-------|
| Create venv | `make setup` | First-time only |
| Activate venv | `source .venv/bin/activate` | Required before dev |
| Start services | `make dev` | Hot-reload, ports 8001-8004 |
| Run CI locally | `make ci` | Mirrors GitHub Actions |
| Run tests | `make test` | Or `pytest path/to/test.py` |
| Format code | `make format` | Writes changes |
| Check lint | `make lint` | Read-only |
| Start Docker stack | `make docker-up` | Includes Postgres, Redis |
| Stop Docker stack | `make docker-down` | Removes containers |
| Run demo | `make demo` | Requires services running |
| View logs (Docker) | `docker compose -f infra/local/docker-compose.yml logs -f` | |

### Critical URLs (Local Dev)

| Service | URL | Docs |
|---------|-----|------|
| Control Plane | http://localhost:8001 | http://localhost:8001/docs |
| Gateway | http://localhost:8002 | http://localhost:8002/docs |
| Trust Plane | http://localhost:8003 | http://localhost:8003/docs |
| MCP Server | http://localhost:8004 | http://localhost:8004/docs |
| GitHub Repo | https://github.com/jeremylongshore/moat | |

### Environment Variables

```bash
# Required for production (from infra/local/.env.example)
DATABASE_URL=postgresql+asyncpg://moat:moat_dev@postgres:5432/moat
REDIS_URL=redis://redis:6379/0
MOAT_SIGNING_SECRET=dev-signing-secret-change-me
MOAT_JWT_SECRET=dev-jwt-secret-change-me

# Service discovery
CONTROL_PLANE_URL=http://control-plane:8001
GATEWAY_URL=http://gateway:8002
TRUST_PLANE_URL=http://trust-plane:8003
MCP_SERVER_URL=http://mcp-server:8004
```

### First-Week Checklist

- [ ] Clone repo, run `make setup && source .venv/bin/activate`
- [ ] Run `make ci` — all checks pass
- [ ] Run `make dev` — 4 services start on :8001-8004
- [ ] Run `make demo` — end-to-end flow completes
- [ ] Read `000-docs/001-AT-ARCH-platform-architecture.md`
- [ ] Read `000-docs/002-AT-FLOW-request-flows.md`
- [ ] Trace a request through `services/gateway/app/routers/execute.py`
- [ ] Understand policy evaluation in `packages/core/moat_core/policy.py`

---

## 9. Recommendations Roadmap

### Week 1 — Close the Loop (P0 blockers)

**Goal:** One fully working path: register → execute → persist → query

1. **Add PostgreSQL persistence**
   - SQLAlchemy async + Alembic migrations
   - Replace `control-plane/app/store.py` in-memory dict
   - Replace `gateway/app/idempotency_store.py` in-memory dict
   - Replace `trust-plane/app/scoring.py` in-memory deque
   - Measurable: Data survives service restart

2. **Add one real adapter**
   - Implement `SlackAdapter` or `OpenAIAdapter`
   - Wire credential resolution from vault
   - Test end-to-end with real API key
   - Measurable: Real provider response in receipt

3. **Add service-level tests**
   - FastAPI `TestClient` for gateway execute endpoint
   - Mock upstream services with `respx`
   - Target: 50%+ coverage on `execute.py`
   - Measurable: CI includes service tests

### Month 1 — Production Foundation

**Goal:** Multi-tenant, authenticated, observable

4. **Implement JWT authentication**
   - Middleware to validate JWT on all endpoints
   - Extract `tenant_id` from claims
   - Enforce tenant isolation on all queries
   - Measurable: Unauthenticated requests rejected

5. **Add Redis for rate limiting**
   - Token bucket per tenant
   - Integrate with `PolicyBundle.budget_daily`
   - Measurable: Budget exceeded returns 429

6. **Fix observability gaps**
   - Consolidate JSON logging (shared module)
   - Add structured error codes
   - Add OpenTelemetry tracing (optional)
   - Measurable: Request traceable across all 4 services

7. **Fix mypy monorepo conflict**
   - Use `--explicit-package-bases` or rename app packages
   - Remove `|| true` from `make typecheck`
   - Measurable: mypy runs without errors

### Quarter 1 — Strategic Moat Building

**Goal:** Defensible trust and governance moats

8. **Implement real MCP protocol**
   - JSON-RPC over SSE or WebSocket
   - Maintain REST as fallback
   - Measurable: Works with MCP-native clients

9. **Add synthetic checks**
   - Scheduled health probes for each capability
   - Feed results into trust-plane scoring
   - Measurable: Capabilities auto-hidden when unhealthy

10. **Add audit log export**
    - Tamper-evident receipt storage
    - Export to S3/GCS for compliance
    - Measurable: Receipts retrievable by time range

11. **Add capability SDK**
    - Python SDK for capability providers
    - Verification harness (conformance tests)
    - Measurable: External contributor can publish capability

---

## Appendices

### A. Glossary

| Term | Definition |
|------|------------|
| Capability | Atomic unit of verifiable AI behavior (method + schema + scopes) |
| Receipt | Immutable audit record produced after each execution |
| OutcomeEvent | Lightweight analytics event for reliability scoring |
| PolicyBundle | Tenant-scoped rules (scopes, budgets, allowlists) |
| PolicyDecision | Result of evaluating a PolicyBundle against a request |
| Adapter | Provider-specific execution implementation |
| Trust Plane | Service that computes reliability scores from OutcomeEvents |
| MCP | Model Context Protocol — standard for agent tool calling |

### B. Reference Links

- [MCP Specification](https://modelcontextprotocol.io)
- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [Pydantic v2 Documentation](https://docs.pydantic.dev/latest/)
- [SQLAlchemy Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Alembic Migrations](https://alembic.sqlalchemy.org)

### C. Open Questions

1. **MCP transport**: stdio vs SSE vs WebSocket for production?
2. **Vault backend**: HashiCorp Vault, AWS Secrets Manager, or GCP Secret Manager?
3. **Receipt storage**: Postgres, BigQuery, or dedicated audit store?
4. **First real adapter**: Slack (simple), OpenAI (high demand), or internal tool?
5. **Deployment target**: Cloud Run, Kubernetes, or serverless?

### D. Health Score Summary

| Category | Score | Notes |
|----------|-------|-------|
| Architecture | 8/10 | Clean boundaries, good separation |
| Code Quality | 7/10 | Strong core, services need tests |
| Operations | 5/10 | Good local dev, no prod path |
| Security | 6/10 | Designed well, not implemented |
| Documentation | 9/10 | Comprehensive, up-to-date |
| **Overall** | **7/10** | Solid foundation, needs execution |

---

*Document generated by appaudit skill. Review quarterly.*
