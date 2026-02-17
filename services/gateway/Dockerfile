# Moat – Gateway Service
# Build context: PROJECT ROOT
#
# Gateway enforces policy, rate-limits, and routes execution requests.
# It talks to control-plane and trust-plane over the internal docker network.
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

COPY services/gateway /tmp/service
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

COPY services/gateway/app ./app

RUN chown -R moat:moat /app
USER moat

EXPOSE 8002

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -sf http://localhost:8002/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
