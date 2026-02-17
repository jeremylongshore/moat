# 002 - Request Flows

**Moat: Verified Agent Capabilities Marketplace**
*Sequence diagrams for all primary flows*

---

## 1. Credential Connect Flow

An agent or admin registers a provider credential for a tenant. The raw secret enters once and is immediately handed to the vault; only an opaque reference is stored in Postgres.

```mermaid
sequenceDiagram
    autonumber
    actor Agent as Agent / Admin
    participant REST as REST API
    participant Auth as Auth Service
    participant Tenants as Tenant Manager
    participant Vault as Credential Vault<br/>(Secret Manager)
    participant PG as PostgreSQL

    Agent->>REST: POST /connections<br/>{provider, credential_payload}
    REST->>Auth: Validate API key → JWT
    Auth-->>REST: JWT {tenant_id, scopes}
    REST->>Tenants: Authorize: tenant can connect provider?
    Tenants-->>REST: allowed

    REST->>Vault: store_secret(tenant_id, provider, credential_payload)
    Vault-->>REST: secret_ref (opaque ID)

    REST->>PG: INSERT connections<br/>{tenant_id, provider, secret_ref, scopes, status=active}
    PG-->>REST: connection_id

    REST-->>Agent: 201 Created<br/>{connection_id, provider, status, created_at}

    Note over REST,Vault: Raw credential_payload is never written to Postgres.<br/>Only secret_ref (opaque vault key) is persisted.
```

---

## 2. Execute Capability Flow (Full Pipeline)

The critical path: policy check, credential injection, outbound call, redaction, receipt generation, outcome event emission.

```mermaid
sequenceDiagram
    autonumber
    actor Agent
    participant MCP as MCP Server
    participant Auth as Auth Service
    participant Router as Execution Router
    participant PolicyEnf as Policy Enforcer
    participant PG as PostgreSQL
    participant CredInj as Credential Injector
    participant Vault as Credential Vault
    participant Exec as Adapter Executor
    participant Redactor as I/O Redactor
    participant ReceiptGen as Receipt Generator
    participant EventStore as Event Store

    Agent->>MCP: capabilities.execute<br/>{capability_id, params, idempotency_key}
    MCP->>Auth: Validate API key → JWT
    Auth-->>MCP: JWT {tenant_id, granted_scopes}

    MCP->>Router: Execute request<br/>{capability_id, params, idempotency_key, tenant_id}

    Router->>PolicyEnf: Pre-execution policy check
    PolicyEnf->>PG: Fetch capability manifest + tenant policy bundle
    PG-->>PolicyEnf: manifest, policy

    PolicyEnf->>PolicyEnf: Evaluate:<br/>1. Scope granted?<br/>2. Budget headroom?<br/>3. Idempotency key seen?<br/>4. Domain allowlist OK?

    alt Idempotency key already seen (within 24h)
        PolicyEnf->>PG: Fetch existing receipt
        PG-->>PolicyEnf: existing_receipt
        PolicyEnf-->>Router: IDEMPOTENT_HIT + receipt
        Router-->>MCP: Existing receipt (no re-execution)
        MCP-->>Agent: {receipt, status: idempotent_hit}
    else Policy denied
        PolicyEnf->>PG: INSERT policy_decisions<br/>{denied, rule_hit, evaluation_ms}
        PolicyEnf-->>Router: DENIED + reason
        Router-->>MCP: 403 PolicyDenied
        MCP-->>Agent: {error: {code: POLICY_DENIED, rule_hit}}
    else Policy allowed
        PolicyEnf->>PG: INSERT policy_decisions<br/>{allowed, rule_hit, evaluation_ms}
        PolicyEnf-->>Router: ALLOWED

        Router->>CredInj: Inject credentials for tenant + provider
        CredInj->>Vault: get_secret(tenant_id, provider)
        Vault-->>CredInj: raw_credential (in-memory only)
        CredInj-->>Router: Enriched request (creds in memory)

        Router->>Exec: Execute outbound call<br/>(to declared domains only)
        Exec->>Exec: Enforce domain allowlist
        Exec->>ExternalProvider: HTTP request (with injected credential)
        ExternalProvider-->>Exec: HTTP response

        Exec->>Redactor: Redact input + output<br/>(strip forbidden keys, compute hashes)
        Redactor-->>Exec: {input_hash, output_hash, redacted_output}

        Exec-->>Router: {status, latency_ms, output_hash, redacted_output}

        Router->>ReceiptGen: Generate receipt
        ReceiptGen->>PG: INSERT receipts<br/>{id, capability_id, version, tenant_id,<br/>timestamp, idempotency_key, input_hash,<br/>output_hash, latency_ms, status}
        PG-->>ReceiptGen: receipt_id

        ReceiptGen->>EventStore: INSERT outcome_events<br/>{receipt_id, capability_id, success,<br/>latency_ms, error_taxonomy, timestamp}

        ReceiptGen-->>Router: receipt
        Router-->>MCP: {receipt, output}
        MCP-->>Agent: {receipt_id, output, status: success}
    end
```

---

## 3. Receipt Generation Detail

Zooms into the receipt generation sub-flow to show hashing and storage guarantees.

```mermaid
sequenceDiagram
    autonumber
    participant Exec as Adapter Executor
    participant Redactor as I/O Redactor
    participant ReceiptGen as Receipt Generator
    participant PG as PostgreSQL
    participant EventStore as Event Store

    Exec->>Redactor: {raw_input, raw_output}

    Redactor->>Redactor: Strip keys matching denylist:<br/>[authorization, api_key, token,<br/>password, secret, credential, bearer]
    Redactor->>Redactor: SHA-256(canonical(raw_input)) → input_hash
    Redactor->>Redactor: SHA-256(canonical(raw_output)) → output_hash
    Redactor->>Redactor: Produce redacted_output (safe to log)

    Redactor-->>ReceiptGen: {input_hash, output_hash, redacted_output}

    ReceiptGen->>ReceiptGen: Construct Receipt record:<br/>id = UUID v7 (time-ordered)<br/>capability_id, capability_version<br/>tenant_id, timestamp (UTC)<br/>idempotency_key<br/>input_hash (SHA-256)<br/>output_hash (SHA-256)<br/>latency_ms, status, error_code

    ReceiptGen->>PG: INSERT receipts (...)<br/>ON CONFLICT (idempotency_key) DO NOTHING
    PG-->>ReceiptGen: inserted or no-op

    ReceiptGen->>EventStore: INSERT outcome_events<br/>{receipt_id, capability_id, tenant_id,<br/>success, latency_ms, error_taxonomy,<br/>timestamp, is_synthetic=false}

    Note over ReceiptGen,PG: Receipt is write-once (immutable).<br/>idempotency_key constraint prevents duplicate execution.
```

---

## 4. Trust Scoring Update Flow

Async batch pipeline that consumes outcome events and updates capability trust scores. Does not block execution.

```mermaid
sequenceDiagram
    autonumber
    participant Scheduler as Batch Scheduler<br/>(runs every 15 min)
    participant Scorer as Trust Scorer
    participant EventStore as Event Store
    participant PG as PostgreSQL
    participant RoutingAdvisor as Routing Advisor
    participant Catalog as Catalog / Registry
    participant SyntheticProber as Synthetic Prober

    Note over Scheduler: Runs on schedule (not on hot path)

    Scheduler->>Scorer: Trigger: score_update(capability_ids[])

    Scorer->>EventStore: SELECT outcome_events<br/>WHERE capability_id IN (...)<br/>AND timestamp >= NOW() - 7d
    EventStore-->>Scorer: outcome_event rows (real + synthetic)

    Scorer->>Scorer: Per capability:<br/>- success_rate = count(success) / count(*)<br/>- p95_latency = percentile(latency_ms, 0.95)<br/>- p50_latency = percentile(latency_ms, 0.50)<br/>- total_calls_7d<br/>- last_synthetic_check_at

    Scorer->>PG: UPSERT capability_stats<br/>{capability_id, success_rate, p50_ms,<br/>p95_ms, total_calls_7d, computed_at}

    Scorer->>RoutingAdvisor: Apply threshold rules to scores

    RoutingAdvisor->>RoutingAdvisor: Evaluate rules:<br/>- success_rate < 0.80 for 24h → status=hidden<br/>- p95_ms > 10000 → status=throttled<br/>- Both OK + verified=true → status=preferred

    RoutingAdvisor->>Catalog: UPDATE capabilities<br/>SET routing_status = {hidden|throttled|active|preferred}
    Catalog->>PG: Persist routing_status
    PG-->>Catalog: updated

    Note over SyntheticProber: Runs independently, feeds same event store

    SyntheticProber->>SyntheticProber: Load capabilities due for probe<br/>(probe_interval_minutes elapsed)
    SyntheticProber->>Catalog: GET capability manifest + test fixture
    Catalog-->>SyntheticProber: manifest, test_inputs
    SyntheticProber->>Exec: Execute probe (via gateway, is_synthetic=true)
    Exec-->>SyntheticProber: result
    SyntheticProber->>EventStore: INSERT outcome_events<br/>{..., is_synthetic=true}
    SyntheticProber->>PG: UPDATE capabilities<br/>SET last_synthetic_check_at, last_synthetic_status
```

---

## Flow Summary Table

| Flow | Trigger | Latency Target | Side Effects |
|------|---------|---------------|--------------|
| Credential Connect | Admin POST /connections | < 500ms | connection row, vault secret |
| Execute Capability | Agent call | < p95 of provider + 50ms overhead | receipt, policy_decision, outcome_event |
| Idempotent Hit | Duplicate idempotency_key | < 50ms | no re-execution; returns cached receipt |
| Policy Denied | Policy evaluation fails | < 20ms | policy_decision record only |
| Receipt Generation | Every execute attempt | Inline, async write | receipt row, outcome_event row |
| Trust Score Update | Batch, every 15 min | Background | capability_stats, routing_status |
| Synthetic Probe | Scheduled per-capability | Background | synthetic outcome_events |
