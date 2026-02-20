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
from app.middleware import RedactionMiddleware, RequestIDMiddleware
from app.routers.execute import router as execute_router

# Configure structured JSON logging before anything else writes to the log.
configure_logging(level=settings.LOG_LEVEL, service_name=settings.SERVICE_NAME)
logger = logging.getLogger(__name__)


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
    yield

    await engine.dispose()
    logger.info("Gateway shutting down")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

_expose_docs = settings.MOAT_ENV in ("local", "test", "dev")
app = FastAPI(
    title="Moat Gateway",
    description=(
        "Policy-enforced capability execution gateway for the Moat "
        "Verified Agent Capabilities Marketplace."
    ),
    version="0.1.0",
    docs_url="/docs" if _expose_docs else None,
    redoc_url="/redoc" if _expose_docs else None,
    openapi_url="/openapi.json" if _expose_docs else None,
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
