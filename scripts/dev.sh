#!/usr/bin/env bash
# scripts/dev.sh – Start all Moat services locally (no Docker)
#
# Usage:
#   bash scripts/dev.sh          # from project root
#   make dev                     # via Makefile
#
# Requirements:
#   - Python 3.11+
#   - pip (or a venv already activated)
#   - All packages installed (run `make install` first if needed)
#
# Each service runs with --reload so file edits hot-reload without restart.
# Press Ctrl-C to kill all background processes cleanly via the trap below.

set -euo pipefail

# ── Resolve project root ──────────────────────────────────────────────────────
# Works regardless of the calling directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

log()  { printf "${CYAN}[dev]${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}[warn]${RESET} %s\n" "$*"; }
ok()   { printf "${GREEN}[ok]${RESET} %s\n" "$*"; }

# ── PID tracking for clean shutdown ──────────────────────────────────────────
PIDS=()

cleanup() {
    printf "\n${YELLOW}Stopping all services...${RESET}\n"
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" && ok "Stopped PID $pid"
        fi
    done
    printf "${GREEN}All services stopped.${RESET}\n"
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Install all packages in editable mode ────────────────────────────────────
log "Installing packages in editable mode..."
pip install -e "${ROOT_DIR}/packages/core"       --quiet
pip install -e "${ROOT_DIR}/services/control-plane" --quiet
pip install -e "${ROOT_DIR}/services/gateway"    --quiet
pip install -e "${ROOT_DIR}/services/trust-plane" --quiet
pip install -e "${ROOT_DIR}/services/mcp-server" --quiet
ok "All packages installed."

# ── Helper: check port is free ────────────────────────────────────────────────
port_free() {
    ! lsof -iTCP:"$1" -sTCP:LISTEN -t &>/dev/null 2>&1
}

for port in 8001 8002 8003 8004; do
    if ! port_free "$port"; then
        warn "Port ${port} is already in use. Stop the existing process or use docker-compose."
    fi
done

# ── Start services ────────────────────────────────────────────────────────────
log "Starting control-plane on :8001..."
uvicorn app.main:app \
    --port 8001 \
    --reload \
    --reload-dir "${ROOT_DIR}/services/control-plane/app" \
    --reload-dir "${ROOT_DIR}/packages/core/moat_core" \
    --app-dir "${ROOT_DIR}/services/control-plane" \
    --log-level info \
    2>&1 | sed "s/^/${BOLD}[ctrl-plane]${RESET} /" &
PIDS+=("$!")

log "Starting gateway on :8002..."
uvicorn app.main:app \
    --port 8002 \
    --reload \
    --reload-dir "${ROOT_DIR}/services/gateway/app" \
    --reload-dir "${ROOT_DIR}/packages/core/moat_core" \
    --app-dir "${ROOT_DIR}/services/gateway" \
    --log-level info \
    2>&1 | sed "s/^/${BOLD}[gateway]${RESET}     /" &
PIDS+=("$!")

log "Starting trust-plane on :8003..."
uvicorn app.main:app \
    --port 8003 \
    --reload \
    --reload-dir "${ROOT_DIR}/services/trust-plane/app" \
    --reload-dir "${ROOT_DIR}/packages/core/moat_core" \
    --app-dir "${ROOT_DIR}/services/trust-plane" \
    --log-level info \
    2>&1 | sed "s/^/${BOLD}[trust-plane]${RESET}  /" &
PIDS+=("$!")

log "Starting mcp-server on :8004..."
uvicorn app.main:app \
    --port 8004 \
    --reload \
    --reload-dir "${ROOT_DIR}/services/mcp-server/app" \
    --reload-dir "${ROOT_DIR}/packages/core/moat_core" \
    --app-dir "${ROOT_DIR}/services/mcp-server" \
    --log-level info \
    2>&1 | sed "s/^/${BOLD}[mcp-server]${RESET}   /" &
PIDS+=("$!")

# ── Print endpoint summary ────────────────────────────────────────────────────
sleep 1
printf "\n${BOLD}Moat services running:${RESET}\n"
printf "  Control Plane  → ${GREEN}http://localhost:8001${RESET}  (docs: http://localhost:8001/docs)\n"
printf "  Gateway        → ${GREEN}http://localhost:8002${RESET}  (docs: http://localhost:8002/docs)\n"
printf "  Trust Plane    → ${GREEN}http://localhost:8003${RESET}  (docs: http://localhost:8003/docs)\n"
printf "  MCP Server     → ${GREEN}http://localhost:8004${RESET}  (docs: http://localhost:8004/docs)\n"
printf "\n${YELLOW}Press Ctrl-C to stop all services.${RESET}\n\n"

# ── Wait for all background jobs ──────────────────────────────────────────────
wait
