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
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.middleware import RedactionMiddleware, RequestIDMiddleware
from app.routers.execute import router as execute_router

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

def _configure_logging(level: str, service_name: str) -> None:
    import json
    import time

    class _JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "service": service_name,
                "timestamp": self.formatTime(record),
            }
            for key, val in record.__dict__.items():
                if key not in {
                    "args", "asctime", "created", "exc_info", "exc_text",
                    "filename", "funcName", "levelname", "levelno", "lineno",
                    "message", "module", "msecs", "msg", "name", "pathname",
                    "process", "processName", "relativeCreated", "stack_info",
                    "thread", "threadName",
                }:
                    payload[key] = val
            if record.exc_info:
                payload["exc_info"] = self.formatException(record.exc_info)
            return json.dumps(payload, default=str)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers = [handler]
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


_configure_logging(settings.LOG_LEVEL, settings.SERVICE_NAME)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "Gateway starting",
        extra={
            "service": settings.SERVICE_NAME,
            "control_plane_url": settings.CONTROL_PLANE_URL,
            "trust_plane_url": settings.TRUST_PLANE_URL,
        },
    )
    yield
    logger.info("Gateway shutting down")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Moat Gateway",
    description=(
        "Policy-enforced capability execution gateway for the Moat "
        "Verified Agent Capabilities Marketplace."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware  (added in reverse order - last added = outermost)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(RedactionMiddleware)


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
