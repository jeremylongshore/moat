# Moat – Control Plane Service
# Build context: PROJECT ROOT (so we can reach packages/core)
#
# Multi-stage build:
#   1. builder  – installs deps into a venv, keeps final image lean
#   2. runtime  – copies venv + app code, runs as non-root
#
# Why non-root? Principle of least privilege. If the container process is
# compromised, the attacker has no write access to the host OS.

# ---------------------------------------------------------------------------
# Stage 1: builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps needed for compiling C extensions (psycopg2-binary is pre-built
# but asyncpg may compile native code). curl is used for healthcheck probing
# in the runtime stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated venv so the runtime stage only needs to copy one dir.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install shared core package first (cached layer – changes rarely).
# Include [postgres] extra for asyncpg driver needed by DATABASE_URL.
COPY packages/core /tmp/core
RUN pip install --no-cache-dir "/tmp/core[postgres]"

# Install service package (changes more frequently – separate layer).
COPY services/control-plane /tmp/service
RUN pip install --no-cache-dir /tmp/service

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Install curl for the HEALTHCHECK below.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security.
RUN useradd --system --uid 1001 --no-create-home moat

WORKDIR /app

# Copy venv from builder – no compilers needed in the final image.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source (the `app` package).
COPY services/control-plane/app ./app

# Own the app directory by our non-root user.
RUN chown -R moat:moat /app
USER moat

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -sf http://localhost:8001/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
