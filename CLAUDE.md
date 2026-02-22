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

Four FastAPI microservices + one shared library, all Python 3.11+:

```
packages/core (moat-core)     Shared Pydantic v2 models, policy engine, redaction, idempotency
  └── moat_core/              Import everything from top-level: `from moat_core import Receipt, evaluate_policy`

services/
  control-plane (:8001)       Capability registry, connections, vault abstraction
  gateway (:8002)             Execution choke-point: policy → idempotency → adapter → receipt → trust-plane
  trust-plane (:8003)         Reliability scoring, outcome event ingestion, stats
  mcp-server (:8004)          Agent-facing MCP tool surface, proxies to control-plane + gateway
```

### Request flow (gateway execute pipeline)

1. Fetch capability from control-plane (cached 5min via `capability_cache`)
2. Validate capability status is `active`
3. Evaluate policy via `policy_bridge` (wires real `moat_core.policy.evaluate_policy`; default-deny if no PolicyBundle registered; fails closed on errors)
4. Check idempotency key — return cached receipt if seen before
5. Dispatch to provider adapter (`AdapterRegistry` in `app.adapters.base`; falls back to `StubAdapter`)
6. Build Receipt
7. Emit OutcomeEvent to trust-plane (async, best-effort)
8. Store in idempotency cache (success only)
9. Return Receipt
10. (Background) Post IRSB receipt via `hooks/irsb_receipt.py` (dry-run mode)
11. (Background) Record spend for budget tracking via `policy_bridge.record_spend()`

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

### Adapter pattern

New providers implement `AdapterInterface` (ABC in `services/gateway/app/adapters/base.py`) and register with the module-level `AdapterRegistry` singleton.

Registered adapters:
- **StubAdapter** — development/testing, returns mock responses
- **SlackAdapter** — Slack message delivery
- **LocalCLIAdapter** — local CLI execution for GWI commands (`services/gateway/app/adapters/local_cli.py`). Uses `asyncio.create_subprocess_exec()` (no shell), pre-defined command templates, GitHub URL validation, 1MB output limit, credential injection via env vars.

### IRSB receipt hook

Post-execution hook at `services/gateway/app/hooks/irsb_receipt.py` fires as a background task after every successful gateway execution. Currently **dry-run** (`DRY_RUN = True`) — logs receipt data but doesn't post on-chain. When wired:
- Computes placeholder intentHash (SHA-256, not real CIE yet)
- Computes resultHash from execution output
- Posts to IntentReceiptHub at `0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c` on Sepolia

### Policy bridge (rewritten)

`services/gateway/app/policy_bridge.py` was rewritten from a permissive stub to wire the real `moat_core.policy.evaluate_policy()` engine. Includes:
- In-memory PolicyBundle registry (`register_policy_bundle()` / `_get_bundle()`)
- In-memory daily spend tracking (`record_spend()` / `_get_current_spend()`)
- Capability dict → CapabilityManifest conversion
- Falls back to deny if no bundle registered (default-deny)

## Monorepo layout

- Each service has its own `pyproject.toml` with hatchling build and `app/` package
- Root `pyproject.toml` configures shared ruff/mypy/pytest settings (line-length 120 at root)
- Services depend on `moat-core` as a pip dependency (installed editable via `-e packages/core`)
- `infra/local/` — docker-compose, `.env.example` with Postgres, Redis, service URLs
- intent-scout-001 integration: `/home/jeremy/000-projects/99-forked/automaton/docker-compose.yml` runs Moat as part of the agent security stack (6 containers)
- `000-docs/` — design docs using doc-filing system (NNN-CC-ABCD format)
- `scripts/dev.sh` — starts all 4 uvicorn processes with `--reload`
- `scripts/demo.sh` — registers a capability, executes it, fetches stats

## Conventions

- **Commit format**: `<type>(<scope>): <subject>` — types: feat, fix, docs, test, ci, chore, refactor
- **Storage**: MVP uses in-memory dicts (control-plane `app/store.py`, gateway `app/idempotency_store.py`). Replace with async SQLAlchemy in v2.
- **Logging**: structured JSON to stdout, per-service. Sensitive fields auto-redacted via `RedactionMiddleware` and `moat_core.redaction`.
- **Secrets**: credentials live in vault abstraction (`control-plane/app/vault.py`); agents never see raw secrets. Receipt stores only SHA-256 hashes.
- **Request tracing**: `X-Request-ID` header propagated across services via middleware.
- **Test markers**: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`, `@pytest.mark.docker`
- **asyncio**: `asyncio_mode = "auto"` — async tests don't need decorators.
- **License**: Elastic License 2.0
