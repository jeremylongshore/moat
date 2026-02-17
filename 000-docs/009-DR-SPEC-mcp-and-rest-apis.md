# 009 - MCP and REST APIs

**Moat: Verified Agent Capabilities Marketplace**
*MCP tool surface, REST endpoint definitions, and standard error model*

---

## Overview

Moat exposes two API surfaces that share the same underlying semantics:

| Surface | Primary Audience | Protocol |
|---------|----------------|---------|
| **MCP Server** | AI agents (ADK, LangChain, Claude, etc.) | Model Context Protocol |
| **REST API** | Human developers, integrations, CI/CD | HTTP / OpenAPI 3.1 |

Both surfaces enforce the same auth, policy, and execution pipeline. The MCP server is a thin adapter over the same gateway and catalog services.

---

## MCP Tool Surface

The MCP server exposes four tools. All tools require a valid tenant API key passed as the MCP server credential.

### Tool: `capabilities.list`

Browse the capability catalog with filters.

```json
{
  "name": "capabilities.list",
  "description": "List available capabilities from the Moat catalog. Supports filtering by provider, category, and verification status. Returns paginated results sorted by trust score (preferred first).",
  "inputSchema": {
    "type": "object",
    "properties": {
      "provider": {
        "type": "string",
        "description": "Filter by provider (e.g., 'slack', 'github', 'stripe'). Optional.",
        "examples": ["slack", "github"]
      },
      "category": {
        "type": "string",
        "description": "Filter by capability category. Optional.",
        "examples": ["messaging", "code", "payments", "data", "storage"]
      },
      "verified": {
        "type": "boolean",
        "description": "If true, return only Verified capabilities. Optional."
      },
      "risk_class": {
        "type": "string",
        "enum": ["low", "medium", "high", "critical"],
        "description": "Filter by risk class. Optional."
      },
      "page": {
        "type": "integer",
        "minimum": 1,
        "default": 1
      },
      "page_size": {
        "type": "integer",
        "minimum": 1,
        "maximum": 100,
        "default": 20
      }
    },
    "additionalProperties": false
  }
}
```

**Example input:**
```json
{
  "provider": "slack",
  "verified": true,
  "page_size": 10
}
```

**Example output:**
```json
{
  "capabilities": [
    {
      "id": "slack.post_message",
      "name": "Post Slack Message",
      "version": "1.2.0",
      "provider": "slack",
      "category": "messaging",
      "description": "Posts a message to a Slack channel or DM.",
      "risk_class": "medium",
      "verified": true,
      "routing_status": "preferred",
      "stats_summary": {
        "success_rate_7d": 0.9987,
        "p95_latency_ms": 844
      }
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 10,
    "total": 1,
    "has_next": false
  }
}
```

---

### Tool: `capabilities.search`

Free-text and structured search across the capability catalog.

```json
{
  "name": "capabilities.search",
  "description": "Search capabilities by name, description, or tags. Combines free-text matching with optional structured filters. Returns results ranked by relevance and trust score.",
  "inputSchema": {
    "type": "object",
    "required": ["query"],
    "properties": {
      "query": {
        "type": "string",
        "description": "Free-text search string. Matched against capability name, description, and tags.",
        "minLength": 2,
        "maxLength": 256,
        "examples": ["send slack message", "create github issue", "charge credit card"]
      },
      "provider": {
        "type": "string",
        "description": "Optional provider filter."
      },
      "category": {
        "type": "string",
        "description": "Optional category filter."
      },
      "verified_only": {
        "type": "boolean",
        "default": false,
        "description": "Restrict to Verified capabilities only."
      },
      "max_risk_class": {
        "type": "string",
        "enum": ["low", "medium", "high", "critical"],
        "description": "Maximum acceptable risk class. Capabilities above this level are excluded."
      },
      "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 20,
        "default": 5
      }
    },
    "additionalProperties": false
  }
}
```

**Example input:**
```json
{
  "query": "post message to slack channel",
  "verified_only": true,
  "limit": 3
}
```

**Example output:**
```json
{
  "results": [
    {
      "id": "slack.post_message",
      "name": "Post Slack Message",
      "version": "1.2.0",
      "relevance_score": 0.97,
      "provider": "slack",
      "description": "Posts a message to a Slack channel or DM.",
      "risk_class": "medium",
      "verified": true,
      "stats_summary": {
        "success_rate_7d": 0.9987,
        "p95_latency_ms": 844
      }
    }
  ],
  "total_matches": 1,
  "query": "post message to slack channel"
}
```

---

### Tool: `capabilities.execute`

Execute a capability with full policy enforcement, credential injection, and receipt generation.

```json
{
  "name": "capabilities.execute",
  "description": "Execute a Moat capability. Enforces policy (scope, budget, domain allowlist), injects credentials, and returns a signed receipt. Idempotent: same idempotency_key within 24h returns the original receipt without re-executing.",
  "inputSchema": {
    "type": "object",
    "required": ["capability_id", "params", "idempotency_key"],
    "properties": {
      "capability_id": {
        "type": "string",
        "description": "Capability ID to execute (e.g., 'slack.post_message').",
        "pattern": "^[a-z0-9_]+\\.[a-z0-9_]+$"
      },
      "capability_version": {
        "type": "string",
        "description": "Specific semver to pin. Defaults to latest published version.",
        "pattern": "^\\d+\\.\\d+\\.\\d+$"
      },
      "params": {
        "type": "object",
        "description": "Capability input parameters. Must conform to the capability's input_schema."
      },
      "idempotency_key": {
        "type": "string",
        "description": "Caller-supplied idempotency key. Unique per tenant. Same key within 24h returns cached receipt without re-executing.",
        "maxLength": 256,
        "examples": ["agent-run-abc123-step-7", "workflow-x-slack-notify-1"]
      },
      "connection_id": {
        "type": "string",
        "description": "Specific connection to use. Defaults to the active connection for the capability's provider."
      }
    },
    "additionalProperties": false
  }
}
```

**Example input:**
```json
{
  "capability_id": "slack.post_message",
  "params": {
    "channel": "C01234ABCDE",
    "text": "Deployment complete: v2.3.1 is live."
  },
  "idempotency_key": "deploy-v2.3.1-slack-notify"
}
```

**Example output (success):**
```json
{
  "receipt_id": "01JP4X7B3K0000000000000001",
  "capability_id": "slack.post_message",
  "capability_version": "1.2.0",
  "status": "success",
  "output": {
    "ok": true,
    "ts": "1739800000.000100",
    "channel": "C01234ABCDE"
  },
  "latency_ms": 342,
  "idempotency_key": "deploy-v2.3.1-slack-notify",
  "idempotent_hit": false,
  "timestamp": "2026-02-17T14:22:11.004Z"
}
```

**Example output (idempotent hit):**
```json
{
  "receipt_id": "01JP4X7B3K0000000000000001",
  "capability_id": "slack.post_message",
  "capability_version": "1.2.0",
  "status": "success",
  "output": {
    "ok": true,
    "ts": "1739800000.000100",
    "channel": "C01234ABCDE"
  },
  "latency_ms": 342,
  "idempotency_key": "deploy-v2.3.1-slack-notify",
  "idempotent_hit": true,
  "timestamp": "2026-02-17T14:22:11.004Z"
}
```

---

### Tool: `capabilities.stats`

Read trust scores and health metrics for a capability.

```json
{
  "name": "capabilities.stats",
  "description": "Get trust scores, reliability metrics, and synthetic probe status for a capability. Use this before executing a capability to assess its current health.",
  "inputSchema": {
    "type": "object",
    "required": ["capability_id"],
    "properties": {
      "capability_id": {
        "type": "string",
        "description": "Capability ID.",
        "pattern": "^[a-z0-9_]+\\.[a-z0-9_]+$"
      },
      "capability_version": {
        "type": "string",
        "description": "Specific version. Defaults to latest published.",
        "pattern": "^\\d+\\.\\d+\\.\\d+$"
      }
    },
    "additionalProperties": false
  }
}
```

**Example input:**
```json
{
  "capability_id": "slack.post_message"
}
```

**Example output:**
```json
{
  "capability_id": "slack.post_message",
  "capability_version": "1.2.0",
  "verified": true,
  "verified_at": "2026-01-15T00:00:00Z",
  "routing_status": "preferred",
  "metrics": {
    "success_rate_7d": 0.9987,
    "p50_latency_ms": 218,
    "p95_latency_ms": 844,
    "total_calls_7d": 14203,
    "data_window": "7d"
  },
  "synthetic": {
    "last_check_at": "2026-02-17T13:45:00Z",
    "last_status": "success",
    "probe_interval_minutes": 30
  },
  "computed_at": "2026-02-17T14:00:00Z"
}
```

---

## REST API

### Authentication

All REST API calls require:

```
Authorization: Bearer <tenant_api_key>
```

The API key is exchanged for a short-lived JWT at the auth layer. Clients may also use JWT directly (for service-to-service calls with pre-issued tokens).

---

### Control Plane Endpoints

#### Capabilities

```
POST /v1/capabilities
```
Register a new capability manifest (draft status). Provider-authenticated.

Request body: `CapabilityManifest` (see `003-capability-spec.md`)

Response: `201 Created` with `capability_id`, `version`, `status=draft`

---

```
GET /v1/capabilities
```
List capabilities (same semantics as `capabilities.list` MCP tool).

Query parameters:
- `provider` — string
- `category` — string
- `verified` — bool
- `risk_class` — enum
- `routing_status` — enum (active, preferred, throttled; hidden excluded by default)
- `page` — int (default 1)
- `page_size` — int (default 20, max 100)

Response: `200 OK` with paginated capability list.

---

```
GET /v1/capabilities/{capability_id}
```
Get latest published version of a capability.

```
GET /v1/capabilities/{capability_id}/versions/{version}
```
Get specific version of a capability.

Response: Full `CapabilityManifest` with stats summary.

---

```
PATCH /v1/capabilities/{capability_id}/versions/{version}/status
```
Transition capability status. Provider-authenticated.

Request body:
```json
{
  "status": "published",
  "deprecation_notice": null
}
```

Rules:
- `draft → published`: Moat review required for HIGH/CRITICAL
- `published → deprecated`: Requires `deprecation_notice`
- Only Moat admin can set `archived`

---

#### Connections

```
POST /v1/connections
```
Register a provider credential for the authenticated tenant.

Request body:
```json
{
  "provider": "slack",
  "credential_payload": {
    "token": "xoxb-..."
  },
  "granted_scopes": ["slack.post_message", "slack.list_channels"]
}
```

Response: `201 Created`
```json
{
  "connection_id": "conn_01J...",
  "provider": "slack",
  "granted_scopes": ["slack.post_message", "slack.list_channels"],
  "status": "active",
  "created_at": "2026-02-17T00:00:00Z"
}
```

Note: `credential_payload` is written to vault; never returned in any response.

---

```
GET /v1/connections
```
List connections for the authenticated tenant.

```
DELETE /v1/connections/{connection_id}
```
Revoke a connection. Sets status to `revoked`; removes vault secret.

---

#### Tenants

```
GET /v1/tenants/me
```
Get the authenticated tenant's profile, tier, and budget defaults.

```
PATCH /v1/tenants/me
```
Update tenant profile (admin_email, name).

```
GET /v1/tenants/me/usage
```
Get current period budget consumption.

Query parameters:
- `capability_id` — filter by capability (optional)
- `period` — `daily` or `monthly` (default `monthly`)

Response:
```json
{
  "tenant_id": "tenant_acme",
  "period": "monthly",
  "period_start": "2026-02-01T00:00:00Z",
  "usage": [
    {
      "capability_id": "slack.post_message",
      "calls_used": 314,
      "calls_limit": 20000,
      "cost_usd": null
    }
  ]
}
```

---

### Gateway Endpoints

#### Execute

```
POST /v1/execute/{capability_id}
```

Execute a capability. Identical semantics to `capabilities.execute` MCP tool.

Request body:
```json
{
  "params": {
    "channel": "C01234ABCDE",
    "text": "Deployment complete."
  },
  "idempotency_key": "deploy-v2.3.1-slack-notify",
  "capability_version": "1.2.0"
}
```

Request headers:
- `Authorization: Bearer <token>` (required)
- `Idempotency-Key: <key>` (alternative to body field; body takes precedence if both present)

Response: `200 OK`
```json
{
  "receipt_id": "01JP4X7B3K0000000000000001",
  "capability_id": "slack.post_message",
  "capability_version": "1.2.0",
  "status": "success",
  "output": {
    "ok": true,
    "ts": "1739800000.000100",
    "channel": "C01234ABCDE"
  },
  "latency_ms": 342,
  "idempotent_hit": false,
  "timestamp": "2026-02-17T14:22:11.004Z"
}
```

On idempotent hit: same body, plus `X-Moat-Idempotent-Replayed: true` header.

---

### Trust Plane Endpoints

```
GET /v1/capabilities/{capability_id}/stats
```

Get trust scores for a capability (same semantics as `capabilities.stats` MCP tool).

Query parameters:
- `version` — specific semver (default: latest published)

Response: See MCP `capabilities.stats` output above.

---

```
GET /v1/capabilities/{capability_id}/stats/history
```

Get historical score snapshots (for charting reliability trends).

Query parameters:
- `window` — `7d`, `30d`, `90d` (default `30d`)
- `granularity` — `hourly`, `daily` (default `daily`)

Response:
```json
{
  "capability_id": "slack.post_message",
  "window": "30d",
  "granularity": "daily",
  "data_points": [
    {
      "date": "2026-01-18",
      "success_rate": 0.9991,
      "p95_latency_ms": 812,
      "total_calls": 483
    }
  ]
}
```

---

## Standard Error Model

All errors from both MCP tools and REST endpoints use this structure:

### Error Response Schema

```python
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    field: str | None = None        # Field path for validation errors
    message: str                    # Human-readable detail
    value: str | None = None        # The offending value (safe to log)


class ErrorResponse(BaseModel):
    error: ErrorBody


class ErrorBody(BaseModel):
    code: str           # Machine-readable error code (see table below)
    message: str        # Human-readable summary
    details: list[ErrorDetail] = []  # Additional context (e.g., validation errors)
    request_id: str     # Correlates to gateway access log
    doc_url: str | None = None  # Link to relevant documentation
```

### Error Code Reference

| HTTP Status | Code | Meaning |
|-------------|------|---------|
| 400 | `INVALID_INPUT` | Request body fails validation |
| 400 | `INVALID_IDEMPOTENCY_KEY` | Idempotency key format invalid |
| 400 | `INVALID_CAPABILITY_VERSION` | Version string malformed |
| 401 | `UNAUTHORIZED` | Missing or invalid API key |
| 401 | `TOKEN_EXPIRED` | JWT has expired |
| 403 | `POLICY_DENIED` | Policy check failed (scope, budget, domain) |
| 403 | `SCOPE_NOT_GRANTED` | Required scope not in tenant connection |
| 403 | `BUDGET_EXCEEDED` | Daily or monthly budget limit reached |
| 403 | `APPROVAL_REQUIRED` | CRITICAL capability requires human approval |
| 403 | `CAPABILITY_HIDDEN` | Capability hidden due to poor trust score |
| 404 | `CAPABILITY_NOT_FOUND` | Capability ID or version does not exist |
| 404 | `CONNECTION_NOT_FOUND` | No active connection for provider |
| 409 | `CAPABILITY_NOT_PUBLISHED` | Capability is not in published status |
| 422 | `PARAMS_SCHEMA_VIOLATION` | Params do not match capability input_schema |
| 429 | `RATE_LIMITED` | Too many requests |
| 500 | `GATEWAY_ERROR` | Internal Moat error (retryable) |
| 502 | `PROVIDER_ERROR` | Provider API returned an error |
| 504 | `TIMEOUT` | Provider API did not respond within timeout |

### Example Error Responses

**Policy denied (scope not granted):**
```json
{
  "error": {
    "code": "SCOPE_NOT_GRANTED",
    "message": "The required scope 'slack.post_message' is not in your connection's granted_scopes.",
    "details": [
      {
        "field": "connection.granted_scopes",
        "message": "Add 'slack.post_message' to your Slack connection's granted scopes.",
        "value": null
      }
    ],
    "request_id": "req_01JP4X7B3K0000000000000001",
    "doc_url": "https://docs.moat.dev/guides/managing-connections"
  }
}
```

**Validation error:**
```json
{
  "error": {
    "code": "PARAMS_SCHEMA_VIOLATION",
    "message": "Capability input parameters do not match the declared input schema.",
    "details": [
      {
        "field": "params.channel",
        "message": "Required field 'channel' is missing.",
        "value": null
      },
      {
        "field": "params.text",
        "message": "Value exceeds maxLength of 4000 characters.",
        "value": "[truncated]"
      }
    ],
    "request_id": "req_01JP4X7B3K0000000000000002",
    "doc_url": "https://docs.moat.dev/capabilities/slack.post_message"
  }
}
```

**Budget exceeded:**
```json
{
  "error": {
    "code": "BUDGET_EXCEEDED",
    "message": "Daily call budget for 'slack.post_message' has been reached (1000/1000).",
    "details": [
      {
        "field": "budget.daily_calls",
        "message": "Budget resets at midnight UTC. Current usage: 1000. Limit: 1000.",
        "value": "1000"
      }
    ],
    "request_id": "req_01JP4X7B3K0000000000000003",
    "doc_url": "https://docs.moat.dev/guides/budgets"
  }
}
```

**Provider error:**
```json
{
  "error": {
    "code": "PROVIDER_ERROR",
    "message": "The provider API returned an error. See receipt for details.",
    "details": [
      {
        "field": null,
        "message": "Provider HTTP 429: rate_limited. Retry after 60s.",
        "value": "429"
      }
    ],
    "request_id": "req_01JP4X7B3K0000000000000004",
    "doc_url": null
  }
}
```

---

## API Versioning

All endpoints are prefixed with `/v1/`. Future breaking changes are introduced as `/v2/` with a migration period.

| Version | Status | Sunset Date |
|---------|--------|------------|
| `/v1/` | Active | TBD |

The MCP tool names are not versioned by URL. Breaking changes to MCP tools result in new tool names (e.g., `capabilities.execute_v2`), with the old tool deprecated and removed after a migration window.

---

## OpenAPI Specification

A full OpenAPI 3.1 spec is available at:

```
GET /openapi.json
GET /openapi.yaml
```

Interactive documentation:
```
GET /docs     (Swagger UI)
GET /redoc    (ReDoc)
```
