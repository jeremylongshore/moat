#!/usr/bin/env bash
# scripts/demo.sh – Moat end-to-end capability marketplace demo
#
# What this script does:
#   1. Verifies all 4 services are healthy (starts them via dev.sh if not).
#   2. Registers a "slack.post_message" capability on the Control Plane.
#   3. Executes that capability via the Gateway.
#   4. Fetches execution stats from the Trust Plane.
#   5. Lists available capabilities via the MCP Server.
#   6. Pretty-prints every response with jq.
#
# Requirements:
#   - curl
#   - jq  (install: apt install jq / brew install jq)
#   - All 4 Moat services running (see `make dev` or `make docker-up`)

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

step()  { printf "\n${CYAN}${BOLD}==> %s${RESET}\n" "$*"; }
ok()    { printf "${GREEN}[ok]${RESET} %s\n" "$*"; }
warn()  { printf "${YELLOW}[warn]${RESET} %s\n" "$*"; }
error() { printf "${RED}[error]${RESET} %s\n" "$*" >&2; }

# ── Prereq checks ─────────────────────────────────────────────────────────────
for cmd in curl jq; do
    if ! command -v "$cmd" &>/dev/null; then
        error "'$cmd' is required but not installed."
        error "Install: apt install $cmd   or   brew install $cmd"
        exit 1
    fi
done

# ── Service endpoints ──────────────────────────────────────────────────────────
CONTROL_PLANE="http://localhost:8001"
GATEWAY="http://localhost:8002"
TRUST_PLANE="http://localhost:8003"
MCP_SERVER="http://localhost:8004"

# ── Step 1: Health checks ──────────────────────────────────────────────────────
step "1/5  Checking service health"

SERVICES_DOWN=0
check_service() {
    local name="$1"
    local url="$2"
    if curl -sf "${url}/healthz" --max-time 3 &>/dev/null; then
        ok "${name} is healthy (${url})"
    else
        warn "${name} is NOT responding at ${url}"
        SERVICES_DOWN=$((SERVICES_DOWN + 1))
    fi
}

check_service "control-plane" "$CONTROL_PLANE"
check_service "gateway"        "$GATEWAY"
check_service "trust-plane"    "$TRUST_PLANE"
check_service "mcp-server"     "$MCP_SERVER"

if [[ "$SERVICES_DOWN" -gt 0 ]]; then
    warn "${SERVICES_DOWN} service(s) not responding."
    warn "Starting services via dev.sh in the background..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    bash "${SCRIPT_DIR}/dev.sh" &
    DEV_PID=$!
    # Wait up to 30 seconds for all services to come up.
    for i in $(seq 1 30); do
        sleep 1
        ALL_UP=1
        for url in "$CONTROL_PLANE" "$GATEWAY" "$TRUST_PLANE" "$MCP_SERVER"; do
            curl -sf "${url}/healthz" --max-time 2 &>/dev/null || ALL_UP=0
        done
        [[ "$ALL_UP" -eq 1 ]] && { ok "All services healthy after ${i}s."; break; }
        [[ "$i" -eq 30 ]] && { error "Services did not start in 30s. Check logs."; kill "$DEV_PID" 2>/dev/null; exit 1; }
    done
fi

# ── Step 2: Register capability ───────────────────────────────────────────────
step "2/5  Registering capability: slack.post_message"

REGISTER_RESPONSE=$(curl -s -X POST "${CONTROL_PLANE}/capabilities" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "slack.post_message",
      "version": "1.0.0",
      "provider": "slack",
      "method": "post_message",
      "description": "Post a message to a Slack channel",
      "scopes": ["slack.post_message"],
      "input_schema": {
        "type": "object",
        "properties": {
          "channel": {"type": "string", "description": "Target channel, e.g. #general"},
          "text":    {"type": "string", "description": "Message body"}
        },
        "required": ["channel", "text"]
      },
      "output_schema": {
        "type": "object",
        "properties": {
          "ok": {"type": "boolean"},
          "ts": {"type": "string", "description": "Slack message timestamp"}
        }
      },
      "risk_class": "medium",
      "domain_allowlist": ["slack.com", "api.slack.com"]
    }')

echo "$REGISTER_RESPONSE" | jq '.'

# Extract capability ID for use in subsequent steps.
CAPABILITY_ID=$(echo "$REGISTER_RESPONSE" | jq -r '.id // .capability_id // empty')

if [[ -z "$CAPABILITY_ID" ]]; then
    # If the service returned a 409 (already exists) or similar, try to discover it.
    warn "Could not parse capability ID from response. Attempting discovery..."
    CAPABILITY_ID=$(curl -s "${CONTROL_PLANE}/capabilities?name=slack.post_message" \
        | jq -r '.items[0].id // .[0].id // empty' 2>/dev/null || true)
fi

if [[ -z "$CAPABILITY_ID" ]]; then
    warn "Could not determine capability ID. Using placeholder 'UNKNOWN' for execute step."
    CAPABILITY_ID="UNKNOWN"
else
    ok "Capability registered with ID: ${CAPABILITY_ID}"
fi

# ── Step 3: Execute capability via Gateway ────────────────────────────────────
step "3/5  Executing capability via Gateway (ID: ${CAPABILITY_ID})"

EXECUTE_RESPONSE=$(curl -s -X POST "${GATEWAY}/execute/${CAPABILITY_ID}" \
    -H "Content-Type: application/json" \
    -d '{
      "tenant_id": "tenant-001",
      "scope": "slack.post_message",
      "params": {
        "channel": "#general",
        "text": "Hello from Moat!"
      },
      "idempotency_key": "demo-001"
    }')

echo "$EXECUTE_RESPONSE" | jq '.'

EXECUTION_ID=$(echo "$EXECUTE_RESPONSE" | jq -r '.execution_id // .id // empty')
[[ -n "$EXECUTION_ID" ]] && ok "Execution ID: ${EXECUTION_ID}" || warn "No execution ID in response."

# ── Step 4: Trust Plane stats ─────────────────────────────────────────────────
step "4/5  Fetching execution stats from Trust Plane"

STATS_RESPONSE=$(curl -s "${TRUST_PLANE}/stats")
echo "$STATS_RESPONSE" | jq '.'

# Also fetch the specific receipt if we have an execution ID.
if [[ -n "${EXECUTION_ID:-}" && "$EXECUTION_ID" != "null" ]]; then
    printf "\n${CYAN}Verification receipt for execution ${EXECUTION_ID}:${RESET}\n"
    curl -s "${TRUST_PLANE}/receipts/${EXECUTION_ID}" | jq '.' || warn "Receipt not found (service may not have written it yet)."
fi

# ── Step 5: MCP Server capability listing ─────────────────────────────────────
step "5/5  Listing capabilities via MCP Server"

MCP_RESPONSE=$(curl -s "${MCP_SERVER}/capabilities")
echo "$MCP_RESPONSE" | jq '.'

# ── Summary ───────────────────────────────────────────────────────────────────
printf "\n${BOLD}${GREEN}Demo complete.${RESET}\n"
printf "  Capability registered : ${CAPABILITY_ID}\n"
[[ -n "${EXECUTION_ID:-}" ]] && printf "  Execution ID          : ${EXECUTION_ID}\n"
printf "\n${CYAN}Explore the interactive API docs:${RESET}\n"
printf "  Control Plane : ${CONTROL_PLANE}/docs\n"
printf "  Gateway       : ${GATEWAY}/docs\n"
printf "  Trust Plane   : ${TRUST_PLANE}/docs\n"
printf "  MCP Server    : ${MCP_SERVER}/docs\n\n"
