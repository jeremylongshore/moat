# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-02-25

### Added
- **A2A Protocol v0.3.0**: AgentCard discovery on mcp-server and gateway (`/.well-known/agent.json`)
- **A2A Models**: AgentSkill, AgentCard, A2ATask, A2AMessage, A2AArtifact, A2ATaskStatus in moat-core
- **Agent Registry**: Full CRUD at control-plane `/agents` with ERC-8004 on-chain identity and SPIFFE workload identity fields
- **ERC-8004 Metadata**: Build standards-compliant registration JSON from agent data (`services/gateway/app/erc8004/metadata.py`)
- **ERC-8004 Registry Sync**: On-chain register/update agent identity via Identity Registry (`registry_sync.py`)
- **IPFS Pinning**: Pin agent metadata and service catalog to IPFS via Pinata (`ipfs.py`)
- **ERC-6551 TBA**: Token Bound Accounts for agent NFTs — allows NFTs to own assets (`tba.py`)
- **A2A Proxy Adapter**: Forward execution to remote A2A agents via JSON-RPC (`adapters/a2a_proxy.py`)
- **Skill Builder**: Auto-discover A2A agents and register skills as Moat capabilities (`skill_builder.py`)
- **Skill Builder API**: `POST /skill-builder/register` and `GET /skill-builder/discover` endpoints
- **Gateway Discovery**: `/.well-known/agent.json` and ERC-8004 metadata endpoints on gateway
- **Dynamic Tenant Resolution**: Intent listener resolves sender addresses via agent registry (replaces hardcoded map)
- **Web3 Adapter**: Contract read/write via RPC for on-chain interactions
- 65+ new tests across all services (total: 399 tests)

### Changed
- IRSB receipt hook upgraded from EIP-191 to EIP-712 typed data signing with CIE struct hash
- Intent listener now uses async DB lookup for tenant resolution with fallback to hardcoded map
- Makefile test target includes mcp-server tests

## [0.1.0] - 2026-02-22

Initial release of Moat — policy-enforced execution and trust layer for AI agents.

### Added
- Four FastAPI microservices: control-plane (:8001), gateway (:8002), trust-plane (:8003), mcp-server (:8004)
- Shared core library (`moat-core`): Pydantic v2 models, policy engine, redaction, idempotency
- Default-deny policy engine with scope enforcement, daily budget tracking, and domain allowlists
- Gateway execute pipeline: policy check → idempotency → adapter dispatch → receipt → outcome event
- IRSB on-chain receipt hook with EIP-191 signing, keccak256 hashes, and Sepolia integration (dry-run by default)
- HTTP proxy adapter with domain allowlist enforcement for sandboxed agents
- OpenAI proxy adapter with server-side API key injection
- Slack adapter for message delivery
- Local CLI adapter for GWI command execution
- JWT authentication middleware with RBAC (disable via `MOAT_AUTH_DISABLED=true`)
- Async SQLAlchemy persistence layer with SQLite (dev) and PostgreSQL (prod) support
- Structured JSON logging with sensitive field auto-redaction
- Security headers middleware (CSP, HSTS, X-Content-Type-Options)
- Request tracing via `X-Request-ID` header propagation
- Docker Compose stack with PostgreSQL 16, Redis 7, and all 4 services
- GitHub Actions CI: lint, typecheck, test, security audit, Docker build (3x matrix), integration tests
- 117+ gateway integration tests covering policy bridge, IRSB receipts, and execute pipeline
- Control-plane tests for capabilities and connections CRUD
- Core library tests for policy engine, models, auth, and redaction
- Blueprint documentation (9 design docs) in `000-docs/`
- Makefile with setup, dev, test, lint, format, docker, and demo targets
- End-to-end demo script (`scripts/demo.sh`)

### Security
- Elastic License 2.0
- No raw secrets in receipts (SHA-256 hashed inputs/outputs)
- Vault abstraction for credential storage
- Domain allowlist enforcement on HTTP proxy and OpenAI adapters
- `RedactionMiddleware` for sensitive field masking in logs
