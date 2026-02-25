"""
app.serve
~~~~~~~~~
Thin uvicorn entry point for the ``moat-mcp-rest`` console script.

Runs the FastAPI REST server directly without needing to remember the
uvicorn invocation::

    moat-mcp-rest              # from installed entry point
    python -m app.serve        # direct invocation
"""

from __future__ import annotations

import uvicorn

from app.config import settings


def main() -> None:
    """Start the MCP REST server via uvicorn."""
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
