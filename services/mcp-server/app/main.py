"""
app.main
~~~~~~~~
Moat MCP Server - FastAPI application entry point.

The MCP server is the AI agent integration layer for Moat. It exposes
MCP-style tool endpoints (as REST for MVP) that AI agents can call to:
- Discover verified capabilities (``capabilities.list``, ``capabilities.search``)
- Execute capabilities with policy enforcement (``capabilities.execute``)
- Retrieve reliability statistics (``capabilities.stats``)

All tool endpoints call upstream Moat services (control plane, gateway,
trust plane) via httpx. If a service is unavailable, stub responses are
returned so the MCP server remains operational independently.

Transport
---------
Currently REST (HTTP POST). Future transports:
- MCP SDK stdio (for Claude Desktop / direct AI agent use)
- Server-Sent Events (SSE) for streaming tool results
- WebSocket for bidirectional MCP protocol

Start with::

    uvicorn app.main:app --port 8004 --reload
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from moat_core.logging import configure_logging
from moat_core.security_headers import SecurityHeadersMiddleware

from app.config import settings
from app.routers.tools import router as tools_router

# Configure structured JSON logging before anything else writes to the log.
configure_logging(level=settings.LOG_LEVEL, service_name=settings.SERVICE_NAME)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from moat_core.auth import AuthConfig, configure_auth

    logger.info(
        "MCP Server starting",
        extra={
            "service": settings.SERVICE_NAME,
            "control_plane_url": settings.CONTROL_PLANE_URL,
            "gateway_url": settings.GATEWAY_URL,
            "trust_plane_url": settings.TRUST_PLANE_URL,
        },
    )

    # Configure authentication
    auth_config = AuthConfig(
        jwt_secret=settings.MOAT_JWT_SECRET,
        auth_disabled=settings.MOAT_AUTH_DISABLED,
    )
    configure_auth(auth_config, environment=settings.MOAT_ENV)

    logger.info("Auth configured", extra={"auth_disabled": settings.MOAT_AUTH_DISABLED})
    yield
    logger.info("MCP Server shutting down")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

_expose_docs = settings.MOAT_ENV in ("local", "test", "dev")
app = FastAPI(
    title="Moat MCP Server",
    description=(
        "MCP-style tool endpoints for AI agent integration with the Moat "
        "Verified Agent Capabilities Marketplace.\n\n"
        "**Available tools:**\n"
        "- `POST /tools/capabilities.list` - List capabilities\n"
        "- `POST /tools/capabilities.search` - Search by name/description\n"
        "- `POST /tools/capabilities.execute` - Execute a capability\n"
        "- `POST /tools/capabilities.stats` - Get reliability stats\n"
    ),
    version="0.1.0",
    docs_url="/docs" if _expose_docs else None,
    redoc_url="/redoc" if _expose_docs else None,
    openapi_url="/openapi.json" if _expose_docs else None,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next: object) -> Response:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.monotonic()

    response: Response = await call_next(request)  # type: ignore[arg-type]
    duration_ms = (time.monotonic() - start) * 1000

    response.headers["X-Request-ID"] = request_id
    logger.info(
        "Request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        "Unhandled exception",
        extra={"request_id": request_id, "error": str(exc)},
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

app.include_router(tools_router)


@app.get("/healthz", tags=["ops"], summary="Health check")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.get(
    "/tools",
    tags=["tools"],
    summary="List available tools",
)
async def list_tools() -> dict[str, object]:
    """Return a manifest of all available MCP tools and their descriptions."""
    return {
        "tools": [
            {
                "name": "capabilities.list",
                "endpoint": "POST /tools/capabilities.list",
                "description": (
                    "List capabilities from the registry with optional filters"
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filter": {
                            "type": "object",
                            "properties": {
                                "provider": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["active", "inactive", "deprecated"],
                                },
                                "verified": {"type": "boolean"},
                            },
                        }
                    },
                },
            },
            {
                "name": "capabilities.search",
                "endpoint": "POST /tools/capabilities.search",
                "description": "Search capabilities by name, description, or tags",
                "input_schema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
            },
            {
                "name": "capabilities.execute",
                "endpoint": "POST /tools/capabilities.execute",
                "description": (
                    "Execute a capability through the policy-enforced gateway"
                ),
                "input_schema": {
                    "type": "object",
                    "required": ["capability_id", "tenant_id"],
                    "properties": {
                        "capability_id": {"type": "string"},
                        "params": {"type": "object"},
                        "tenant_id": {"type": "string"},
                        "idempotency_key": {"type": "string"},
                        "scope": {"type": "string"},
                    },
                },
            },
            {
                "name": "capabilities.stats",
                "endpoint": "POST /tools/capabilities.stats",
                "description": (
                    "Get 7-day reliability stats and trust signals for a capability"
                ),
                "input_schema": {
                    "type": "object",
                    "required": ["capability_id"],
                    "properties": {"capability_id": {"type": "string"}},
                },
            },
        ]
    }


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": settings.SERVICE_NAME,
        "version": "0.1.0",
        "docs": "/docs",
        "tools": "/tools",
    }
