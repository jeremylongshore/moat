# Moat Stack Strategy

You can stack multiple moats into one MCP-first platform, but you can't build them all at once at full strength. The correct move is to design the architecture so every moat is "pluggable" from day 1, then sequence them so you're early and compounding.

Below is a "full moat stack" plan that fits your gateway/catalog/trust-plane blueprint and keeps MCP as the primary surface.

## The full moat stack (what "all moats" actually means)

### Moat 1: Trust moat (reliability + verification)

**What it is:** Agents route to what works. You become the default because you publish machine-evaluable proof.
- capability-level success rates + latency percentiles
- synthetic checks + conformance tests
- deterministic receipts (redacted input hashes, output hashes, version IDs)
- "dead capability = hidden/throttled"

**Why it's defensible:** Compounds with time + traffic + testing history. Hard to fake.

### Moat 2: Governance moat (policy + audit + compliance)

**What it is:** Enterprises need "allowed, trusted, auditable."
- method-level scopes
- budgets + rate limits + approval gates
- outbound domain allowlists (SSRF prevention)
- tamper-evident audit log + exports

**Why it's defensible:** Once embedded in policies and audits, switching costs are high.

### Moat 3: Execution moat (permissioned action layer)

**What it is:** Real-world side effects: comms, payments, tickets, workflows.
- agent calls capabilities, not provider APIs
- you enforce safe execution, idempotency, retries, rollback-ish patterns

**Why it's defensible:** You become "the safe button" for action. That's sticky.

### Moat 4: Data moat (privileged/proprietary signals)

**What it is:** Things they can't compute cheaply:
- aggregated reliability telemetry across providers/methods
- curated capability metadata + policy templates
- (later) partner datasets, enrichment corpora, verified compliance metadata

**Why it's defensible:** Unique dataset + continuous refresh + provenance.

### Moat 5: Compute moat (expensive, specialized services)

**What it is:** Endpoints where you own the heavy lifting:
- large-scale extraction/dedupe/entity resolution
- forecasting ensembles/backtests
- "verified" scoring endpoints

**Why it's defensible:** Infra + tuning + cost curves + operational expertise.

### Moat 6: Ecosystem moat (SDK + community connectors)

**What it is:** Others build on you.
- connector/capability SDK
- verification harness that contributors must pass
- signed releases + provenance

**Why it's defensible:** Network effects: catalog + trust history + distribution.

### Moat 7: Distribution moat (MCP is the wedge)

**What it is:** You're the default tool surface for agents.
- MCP server for discovery + execution + stats
- REST/OpenAPI for everyone else
- "capability manifests" become the standard contract

**Why it's defensible:** Default integration path becomes you.

---

## How to implement "all moats" without boiling the ocean

### Core architecture (supports every moat)
- **Control plane:** users/tenants, auth, billing, credential references, policies
- **Data plane (gateway):** execute capabilities, inject creds, enforce policy, emit receipts
- **Trust plane:** checks + scoring + verification artifacts + routing recommendations
- **Catalog:** capability registry + schemas + OpenAPI export + policy templates
- **Interfaces:** MCP + REST

This is the minimal skeleton that lets you add data, compute, and ecosystem later without rewriting everything.

---

## Sequence: what you ship first to be early

### Weeks 1-2 (Blueprint-only, but decisive)
1. Capability contract spec (schema, scopes, receipts, risk class)
2. Trust plane spec (synthetic checks, scoring, hide/throttle rules)
3. Policy spec (default-deny, budgets, allowlists, approvals)
4. MCP surface spec (discover/list/search/execute/stats endpoints)

### Weeks 3-6 (MVP build)

Ship these moats immediately:
- **Trust moat (basic):** synthetic checks + receipts + success/latency stats
- **Governance moat (basic):** scopes + budgets + allowlists + redaction
- **Execution moat (basic):** idempotent execution + normalized errors
- **Distribution moat:** MCP + REST with capability manifests

Defer but design hooks for:
- **Data moat** (partner data) and **Compute moat** (heavy endpoints)
- **Ecosystem moat** (public SDK) until you have internal quality gates working

### Weeks 7-12 (the compounding phase)
- Add "Verified" badges backed by conformance tests
- Add routing/fallback (policy-aware)
- Add export/audit features
- Start SDK + contributor program once the harness is rock solid

---

## The key design decision that makes "all moats" possible

**Make "receipt + score + policy" mandatory for every capability.**

If every tool call produces:
- a receipt (audit + replay-ready)
- an outcome event (metrics)
- a policy evaluation record (why allowed/blocked)

...then trust, governance, and data moats compound automatically.

---

## What to avoid
- **Chasing "50 connectors"** before you have verification + policy. That's how you become an unreliable directory.
- **Letting agents hold raw provider secrets.** That destroys your governance moat and increases breach risk.
- **Semantic search as the core differentiator.** Reliability beats embeddings.

---

## The "all moats" MVP definition (crisp)

You can truthfully claim "all moats" early if MVP includes:
1. **Verified execution** (receipts + health checks)
2. **Policy enforcement** (scopes + budgets + allowlists)
3. **MCP-native distribution** (capability manifests + execute + stats)
4. **A path to data/compute** (hooks for premium endpoints + datasets)

That's the stack.
