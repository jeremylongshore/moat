"""
app.main
~~~~~~~~
Moat Gateway - FastAPI application entry point.

The gateway is the single execution choke point for all capability
invocations. It enforces:
- Policy evaluation (moat_core.policy)
- Idempotency (prevent duplicate executions)
- Credential resolution from vault (never inline)
- Structured, redacted logging
- Outcome event emission to the trust plane

Start with::

    uvicorn app.main:app --port 8002 --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from moat_core.logging import configure_logging
from moat_core.security_headers import SecurityHeadersMiddleware

from app.config import settings
from app.intent_listener import router as intent_router
from app.middleware import RedactionMiddleware, RequestIDMiddleware
from app.routers.execute import router as execute_router

# Configure structured JSON logging before anything else writes to the log.
configure_logging(level=settings.LOG_LEVEL, service_name=settings.SERVICE_NAME)
logger = logging.getLogger(__name__)


def _seed_policy_bundles() -> None:
    """Register default PolicyBundles for the intent-scout-001 tenant.

    These define which capabilities the agent is allowed to invoke and
    the daily budget for each. Called once at gateway startup.
    """
    from moat_core.models import PolicyBundle

    from app.policy_bridge import register_policy_bundle

    tenant = "automaton"

    bundles = [
        # GWI code services (local CLI execution)
        PolicyBundle(
            id="pb_automaton_gwi_triage",
            tenant_id=tenant,
            capability_id="gwi.triage",
            allowed_scopes=["execute"],
            budget_daily=5000,  # $50/day (50 calls)
        ),
        PolicyBundle(
            id="pb_automaton_gwi_review",
            tenant_id=tenant,
            capability_id="gwi.review",
            allowed_scopes=["execute"],
            budget_daily=2000,  # $20/day (20 calls)
        ),
        PolicyBundle(
            id="pb_automaton_gwi_issue_to_code",
            tenant_id=tenant,
            capability_id="gwi.issue-to-code",
            allowed_scopes=["execute"],
            budget_daily=1000,  # $10/day (10 calls)
        ),
        PolicyBundle(
            id="pb_automaton_gwi_resolve",
            tenant_id=tenant,
            capability_id="gwi.resolve",
            allowed_scopes=["execute"],
            budget_daily=1000,  # $10/day (10 calls)
        ),
        # External API services (proxied through Moat)
        PolicyBundle(
            id="pb_automaton_github_api",
            tenant_id=tenant,
            capability_id="github.api",
            allowed_scopes=["execute"],
            budget_daily=10000,  # $100/day (100 calls)
            domain_allowlist=["api.github.com"],
        ),
        PolicyBundle(
            id="pb_automaton_openai_inference",
            tenant_id=tenant,
            capability_id="openai.inference",
            allowed_scopes=["execute"],
            budget_daily=20000,  # $200/day (200 calls)
            domain_allowlist=["api.openai.com"],
        ),
        PolicyBundle(
            id="pb_automaton_irsb_receipt",
            tenant_id=tenant,
            capability_id="irsb.receipt",
            allowed_scopes=["execute"],
            budget_daily=5000,  # $50/day (50 calls)
            domain_allowlist=["sepolia.infura.io"],
        ),
        # Web3 contract interactions (via Web3Adapter)
        PolicyBundle(
            id="pb_automaton_contract_read",
            tenant_id=tenant,
            capability_id="contract.read",
            allowed_scopes=["execute"],
            budget_daily=5000,  # $50/day
            domain_allowlist=[
                "eth-mainnet.g.alchemy.com",
                "polygon-mainnet.g.alchemy.com",
                "arb-mainnet.g.alchemy.com",
                "opt-mainnet.g.alchemy.com",
                "sepolia.infura.io",
                "api.thegraph.com",
            ],
        ),
        PolicyBundle(
            id="pb_automaton_contract_write",
            tenant_id=tenant,
            capability_id="contract.write",
            allowed_scopes=["execute"],
            budget_daily=1000,  # $10/day — testnet only for now
            domain_allowlist=[
                "sepolia.infura.io",
            ],
        ),
        # Generic HTTPS proxy — bounty discovery across all platforms
        PolicyBundle(
            id="pb_automaton_http_proxy",
            tenant_id=tenant,
            capability_id="http.proxy",
            allowed_scopes=["execute"],
            budget_daily=15000,  # $150/day
            domain_allowlist=[
                # Bounty platforms (REST APIs)
                "api.github.com",  # GitHub — foundation layer + audit contest repos
                "console.algora.io",  # Algora — open-source bounties
                "gitcoin.co",  # Gitcoin — public bounty API (no auth)
                "api.polar.sh",  # Polar.sh — sponsored issues (KEY NEEDED)
                "api.hackerone.com",  # HackerOne — bug bounties (KEY NEEDED)
                "api.bugcrowd.com",  # Bugcrowd — vulnerability bounties (KEY NEEDED)
                # Web3 on-chain reads (RPC endpoints)
                "api.thegraph.com",  # The Graph — subgraph queries for Web3 platforms
                "eth-mainnet.g.alchemy.com",  # Ethereum mainnet RPC (KEY NEEDED)
                "polygon-mainnet.g.alchemy.com",  # Polygon RPC
                "arb-mainnet.g.alchemy.com",  # Arbitrum RPC
                "opt-mainnet.g.alchemy.com",  # Optimism RPC
            ],
        ),
    ]

    for bundle in bundles:
        register_policy_bundle(bundle)

    logger.info(
        "Seeded PolicyBundles",
        extra={"count": len(bundles), "tenant": tenant},
    )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from moat_core.auth import AuthConfig, configure_auth
    from moat_core.db import create_engine, create_session_factory, init_tables

    from app.idempotency_store import idempotency_store

    logger.info(
        "Gateway starting",
        extra={
            "service": settings.SERVICE_NAME,
            "control_plane_url": settings.CONTROL_PLANE_URL,
            "trust_plane_url": settings.TRUST_PLANE_URL,
        },
    )

    # Configure authentication
    auth_config = AuthConfig(
        jwt_secret=settings.MOAT_JWT_SECRET,
        auth_disabled=settings.MOAT_AUTH_DISABLED,
    )
    configure_auth(auth_config, environment=settings.MOAT_ENV)

    # Initialize database for idempotency cache
    engine = create_engine(settings.DATABASE_URL)
    session_factory = create_session_factory(engine)
    await init_tables(engine)
    idempotency_store.configure(session_factory)

    logger.info(
        "Gateway database initialized",
        extra={"auth_disabled": settings.MOAT_AUTH_DISABLED},
    )

    # Seed PolicyBundles for known capabilities (intent-scout-001 tenant)
    _seed_policy_bundles()

    yield

    await engine.dispose()
    logger.info("Gateway shutting down")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

_expose_interactive = settings.MOAT_ENV in ("local", "test", "dev")
app = FastAPI(
    title="Moat Gateway",
    description=(
        "Policy-enforced capability execution gateway for the Moat "
        "Verified Agent Capabilities Marketplace."
    ),
    version="0.1.0",
    openapi_url="/openapi.json",  # Always available — agents need schema discovery
    docs_url="/docs" if _expose_interactive else None,
    redoc_url="/redoc" if _expose_interactive else None,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware  (added in reverse order - last added = outermost)
# ---------------------------------------------------------------------------

_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(RedactionMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        "Unhandled exception",
        extra={"request_id": request_id, "path": request.url.path, "error": str(exc)},
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred.",
            "request_id": request_id,
        },
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(execute_router)
app.include_router(intent_router)


@app.get("/healthz", tags=["ops"], summary="Health check")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": settings.SERVICE_NAME,
        "version": "0.1.0",
        "docs": "/docs",
    }
