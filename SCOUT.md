# Scout — Broker Agent Scope

Scout (`intent-scout-001`) is the **broker** embedded in Moat. ONE JOB: discover work, match agents, route through Moat, collect receipts.

## What Scout Does (Broker Scope)

- **Discover** available agents via A2A AgentCards
- **Match** incoming work requests to the right agent/capability
- **Route** matched work through Moat gateway (policy enforcement happens at Moat level)
- **Collect** IRSB receipts as proof of completed work
- **Feed** results back to requester (via CLI or MCP)

## What Scout Does NOT Do

| Concern | Owned By | NOT Scout |
|---------|----------|-----------|
| Execute DeFi | Lit Agent | Scout routes to Lit Agent, doesn't execute |
| Execute git ops | Git Agent (future) | Scout routes, doesn't execute |
| Enforce policy | Moat Gateway | Scout's requests are subject to policy |
| Generate receipts | IRSB Protocol | Scout triggers receipt hooks, doesn't own signing |
| Register capabilities | Moat Control-Plane | Scout consumes the registry |

## Scout's Identity

| Item | Value |
|------|-------|
| Tenant ID | `automaton` |
| ERC-8004 Agent | `#1319` |
| Solver Address | `0x83Be08FFB22b61733eDf15b0ee9Caf5562cd888d` |

## Where Scout Code Lives (in Moat)

| File | Role | Status |
|------|------|--------|
| `services/gateway/app/main.py` | PolicyBundles for intent-scout-001 | OK — broker scope |
| `services/gateway/app/hooks/irsb_receipt.py` | Receipt posting hook | BOUNDARY — receipt signing should migrate to IRSB service |
| `services/mcp-server/app/stdio_server.py` | Scout-workflow MCP tools | OK — bounty.* tools are broker work |
| `services/mcp-server/app/tool_definitions.py` | Tool schemas | OK |
| `services/mcp-server/app/http_client.py` | Gateway RPC helpers | OK — clean abstraction |
| `packages/cli/moat_cli/commands/bounty.py` | CLI commands | OK — broker workflow |
| `services/gateway/app/intent_listener.py` | Inbound intent routing | OK — contains hardcoded fallback address |

## Known Boundary Violations (TODO)

1. **Receipt generation** (`irsb_receipt.py`): Scout's hook directly signs and posts on-chain receipts. This should eventually move to a dedicated IRSB service. Scout should emit execution results; IRSB subscribes and posts.

2. **Hardcoded identity**: Agent ID #1319 and solver address are hardcoded. Should move to env vars (`SCOUT_AGENT_ID`, `SCOUT_SOLVER_ADDRESS`).

3. **A2A discovery tools**: `agents.discover` and `agents.card` are exposed as MCP tools. These are capability-registration concerns — Scout should use them internally but not expose as first-class tools.

## Decision: Scout Stays in Moat

Scout is tightly coupled to Moat's routing logic — it's essentially Moat's "brain" for brokering. If it grows too complex, extract to a standalone agent later.
