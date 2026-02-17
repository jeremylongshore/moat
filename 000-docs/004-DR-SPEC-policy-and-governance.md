# 004 - Policy Specification

**Moat: Verified Agent Capabilities Marketplace**
*Method-level scopes, budget model, domain allowlists, approval gates, and PolicyDecision format*

---

## Overview

Every capability execution is gated by a **policy evaluation** that runs synchronously before the adapter call. The policy engine is **default-deny**: unless an explicit grant covers the request, execution is blocked.

Policy is evaluated at the intersection of **tenant** and **capability**. Tenants carry a policy bundle; capabilities carry default policy templates. The effective policy is the merge of both, with tenant overrides taking precedence.

---

## Policy Evaluation Order

```
Request arrives at Gateway
        │
        ▼
1. Idempotency check (return cached receipt if key seen in 24h)
        │
        ▼
2. Scope check (does tenant have the required method scope?)
        │
        ▼
3. Budget check (is there remaining daily/monthly quota?)
        │
        ▼
4. Domain allowlist check (are outbound targets declared?)
        │
        ▼
5. Approval gate check (does risk class require human approval?)
        │
        ▼
6. ALLOWED → proceed to credential injection + execution
```

Any check failing produces an immediate `DENIED` with the specific `rule_hit` code. All results (allowed and denied) are persisted as `PolicyDecision` records.

---

## Method-Level Scopes

### Scope Format

```
{provider}.{action}

Examples:
  slack.post_message
  slack.list_channels
  slack.delete_message
  github.create_issue
  github.merge_pull_request
  github.delete_repo
  stripe.create_payment_intent
  stripe.refund_charge
```

### Scope Grant Model

Scopes are granted at the **tenant connection** level. When a tenant connects a provider (registers credentials), they select which scopes they grant to Moat for that connection.

```json
{
  "connection_id": "conn_01J...",
  "provider": "slack",
  "granted_scopes": [
    "slack.post_message",
    "slack.list_channels"
  ],
  "denied_scopes": [
    "slack.delete_message"
  ]
}
```

**Rules:**
- Scopes not listed under `granted_scopes` are implicitly denied.
- `denied_scopes` is an explicit denylist (belt-and-suspenders for sensitive actions).
- Capability manifests declare their required scopes. All required scopes must appear in `granted_scopes`.
- Scope grants are stored in the `connections` table; they are not in the JWT (to allow revocation without token rotation).

### Scope Hierarchy (Future)

Wildcard scopes may be introduced in a future version (e.g., `slack.*` grants all Slack scopes). Until then, all grants are explicit. This avoids accidental over-permissioning during MVP.

---

## Budget Model

Budgets are defined per **tenant** per **capability** and are enforced before execution.

### Budget Types

| Type | Granularity | Reset |
|------|------------|-------|
| `daily_calls` | Calls per UTC day | Midnight UTC |
| `monthly_calls` | Calls per calendar month | First of month UTC |
| `daily_cost_usd` | Spend per UTC day (for priced capabilities) | Midnight UTC |
| `monthly_cost_usd` | Spend per calendar month | First of month UTC |

### Budget Configuration

```python
from pydantic import BaseModel


class BudgetConfig(BaseModel):
    capability_id: str
    tenant_id: str

    # Call volume limits
    daily_calls: int | None = None        # None = unlimited
    monthly_calls: int | None = None      # None = unlimited

    # Cost limits (for priced capabilities)
    daily_cost_usd: float | None = None
    monthly_cost_usd: float | None = None

    # Soft vs hard limits
    hard_limit: bool = True
    # True  = deny when limit hit (default, safe)
    # False = allow but emit BudgetExceeded warning event
```

### Budget Enforcement

Budget counters are tracked in a fast store (Redis or Postgres with advisory locks). Enforcement uses an optimistic pre-check:

1. Read current counter from fast store.
2. If `current >= limit`, deny immediately (emit `PolicyDecision` with `rule_hit=BUDGET_DAILY_CALLS_EXCEEDED`).
3. If allowed, execute. On success, increment counter atomically.
4. On execution failure, do not increment (failed calls do not count against budget).

### Default Budgets

Capability manifests may declare a **recommended default budget** in their policy template. This is applied to new tenant connections unless overridden:

```json
{
  "policy_template": {
    "default_daily_calls": 1000,
    "default_monthly_calls": 20000,
    "default_daily_cost_usd": null,
    "default_monthly_cost_usd": null
  }
}
```

Moat platform-level defaults (applied when no capability template exists):
- `daily_calls`: 500
- `monthly_calls`: 10000
- Cost limits: null (unlimited; applied when pricing is added)

---

## Domain Allowlists

Domain allowlists are declared in the **CapabilityManifest** (see `003-capability-spec.md`). The gateway enforces them at the network layer before any outbound HTTP call.

### Enforcement Rules

1. The capability manifest's `domain_allowlist` is the authoritative list of permitted outbound hosts.
2. No wildcards. Each entry must be an exact hostname.
3. Port restrictions: only ports 80 and 443 are permitted. Other ports are rejected regardless of allowlist.
4. IP addresses are never permitted in the allowlist. Hostnames only (prevents IP-based SSRF bypasses).
5. DNS resolution happens inside the gateway after allowlist validation. If a hostname resolves to a private/RFC-1918 address, the request is rejected.
6. Redirects: if a provider API redirects to a host not in the allowlist, the redirect is not followed and the request fails.

### SSRF Prevention Checklist

| Check | Mechanism |
|-------|----------|
| Allowlist enforcement | Manifest `domain_allowlist` |
| No wildcard domains | `field_validator` in manifest model |
| No IP literals | Regex validation at manifest registration |
| No private IP resolution | Post-DNS check in adapter executor |
| No port escapes | Port whitelist (80, 443 only) |
| No redirect escapes | Redirect policy: no-follow or re-validate |

---

## Approval Gates

Capabilities with `risk_class=critical` require an **approval gate** before execution. This is a forward-looking feature with a defined interface; the MVP ships with automatic approval for LOW/MEDIUM/HIGH and a blocking hold for CRITICAL.

### Approval Gate Model

```python
from enum import Enum
from pydantic import BaseModel


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class ApprovalRequest(BaseModel):
    id: str                    # UUID v7
    capability_id: str
    capability_version: str
    tenant_id: str
    requested_by: str          # user or agent ID
    requested_at: str          # ISO 8601
    expires_at: str            # ISO 8601 (default: +1h)
    status: ApprovalStatus
    reviewed_by: str | None    # human reviewer ID
    reviewed_at: str | None
    review_note: str | None
    original_request_id: str   # the blocked execution request ID
```

### Risk Class → Gate Behavior

| Risk Class | Gate Behavior |
|-----------|--------------|
| `low` | No gate. Automatic allow (subject to scope + budget). |
| `medium` | No gate. Automatic allow (subject to scope + budget). |
| `high` | No gate by default. Tenant may configure mandatory gate via policy bundle. |
| `critical` | Mandatory human approval gate. Execution blocked until approved. |

### Approval Flow (Future / Phase 2)

```
Agent requests CRITICAL capability
        │
        ▼
Gateway: APPROVAL_REQUIRED → return ApprovalRequest (pending)
        │
        ▼
Notification sent (email / Slack / webhook) to designated approver
        │
        ▼
Approver reviews context, approves or denies
        │
        ▼
Agent polls or receives webhook: ApprovalRequest.status = approved
        │
        ▼
Agent resubmits with approval_request_id → Gateway allows
```

---

## PolicyDecision Record

A `PolicyDecision` is written for **every** policy evaluation (allowed and denied). This is the immutable audit record of why an execution was permitted or blocked.

### Schema

```python
from pydantic import BaseModel


class PolicyDecision(BaseModel):
    id: str                      # UUID v7
    capability_id: str
    capability_version: str
    tenant_id: str
    connection_id: str | None    # None for catalog-only requests
    request_id: str              # Correlates to the inbound execute request
    timestamp: str               # ISO 8601 UTC

    # Outcome
    decision: str                # "allowed" | "denied"
    rule_hit: str                # The specific rule that determined outcome (see below)
    evaluation_ms: int           # Time spent in policy engine

    # Context
    requested_scopes: list[str]  # Scopes required by capability
    granted_scopes: list[str]    # Scopes the tenant has
    budget_state: dict           # Snapshot of budget counters at evaluation time
    idempotency_key: str | None
    is_synthetic: bool           # True if triggered by synthetic prober
```

### Rule Hit Codes

| Code | Meaning |
|------|---------|
| `SCOPE_NOT_GRANTED` | Required scope missing from tenant's granted scopes |
| `SCOPE_EXPLICITLY_DENIED` | Scope appears in tenant's `denied_scopes` |
| `BUDGET_DAILY_CALLS_EXCEEDED` | Daily call limit reached |
| `BUDGET_MONTHLY_CALLS_EXCEEDED` | Monthly call limit reached |
| `BUDGET_DAILY_COST_EXCEEDED` | Daily cost cap reached |
| `BUDGET_MONTHLY_COST_EXCEEDED` | Monthly cost cap reached |
| `DOMAIN_NOT_ALLOWLISTED` | Outbound target not in capability's domain allowlist |
| `CAPABILITY_NOT_PUBLISHED` | Capability status is not `published` |
| `CAPABILITY_HIDDEN` | Trust plane has hidden capability due to poor health |
| `APPROVAL_REQUIRED` | CRITICAL capability; waiting for human approval |
| `APPROVAL_PENDING` | Approval request exists but not yet reviewed |
| `APPROVAL_DENIED` | Human reviewer denied the approval request |
| `APPROVAL_EXPIRED` | Approval request expired before review |
| `IDEMPOTENT_HIT` | Request allowed but returning cached receipt (no re-execution) |
| `POLICY_ALLOWED` | All checks passed; execution permitted |

### Example PolicyDecision (denied)

```json
{
  "id": "01JTEST000000000000000001",
  "capability_id": "slack.post_message",
  "capability_version": "1.2.0",
  "tenant_id": "tenant_acme",
  "connection_id": "conn_01J...",
  "request_id": "req_01J...",
  "timestamp": "2026-02-17T12:34:56.789Z",
  "decision": "denied",
  "rule_hit": "BUDGET_DAILY_CALLS_EXCEEDED",
  "evaluation_ms": 4,
  "requested_scopes": ["slack.post_message"],
  "granted_scopes": ["slack.post_message", "slack.list_channels"],
  "budget_state": {
    "daily_calls_used": 1000,
    "daily_calls_limit": 1000,
    "monthly_calls_used": 8432,
    "monthly_calls_limit": 20000
  },
  "idempotency_key": "agent-run-xyz-step-42",
  "is_synthetic": false
}
```

### Example PolicyDecision (allowed)

```json
{
  "id": "01JTEST000000000000000002",
  "capability_id": "slack.post_message",
  "capability_version": "1.2.0",
  "tenant_id": "tenant_acme",
  "connection_id": "conn_01J...",
  "request_id": "req_01J...",
  "timestamp": "2026-02-17T12:34:56.789Z",
  "decision": "allowed",
  "rule_hit": "POLICY_ALLOWED",
  "evaluation_ms": 3,
  "requested_scopes": ["slack.post_message"],
  "granted_scopes": ["slack.post_message", "slack.list_channels"],
  "budget_state": {
    "daily_calls_used": 42,
    "daily_calls_limit": 1000,
    "monthly_calls_used": 314,
    "monthly_calls_limit": 20000
  },
  "idempotency_key": "agent-run-xyz-step-42",
  "is_synthetic": false
}
```

---

## Policy Bundle

A **PolicyBundle** is the complete effective policy for a `(tenant, capability)` pair. It is computed at connection time and cached; changes to tenant policy or capability templates invalidate the cache.

```python
class PolicyBundle(BaseModel):
    tenant_id: str
    capability_id: str
    capability_version: str
    computed_at: str

    # Scope grants (from connection)
    granted_scopes: list[str]
    denied_scopes: list[str]

    # Budget configuration (tenant override > capability default > platform default)
    budget: BudgetConfig

    # Domain allowlist (from capability manifest; not overridable by tenant)
    domain_allowlist: list[str]

    # Approval gate
    approval_gate_enabled: bool
    approval_gate_required_for_risk_classes: list[RiskClass]
```
