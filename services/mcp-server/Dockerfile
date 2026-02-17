# Moat – MCP Server Service
# Build context: PROJECT ROOT
#
# The MCP Server exposes a Model Context Protocol interface so AI agents can
# discover and invoke verified capabilities without knowing the internal
# service topology. It is a read-mostly fan-out layer that aggregates data
# from control-plane and trust-plane.
#
# See services/control-plane/Dockerfile for stage-by-stage commentary.

# ---------------------------------------------------------------------------
# Stage 1: builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY packages/core /tmp/core
RUN pip install --no-cache-dir /tmp/core

COPY services/mcp-server /tmp/service
RUN pip install --no-cache-dir /tmp/service

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 1001 --no-create-home moat

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY services/mcp-server/app ./app

RUN chown -R moat:moat /app
USER moat

EXPOSE 8004

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -sf http://localhost:8004/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
