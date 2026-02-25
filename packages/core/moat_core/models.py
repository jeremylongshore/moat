"""
moat_core.models
~~~~~~~~~~~~~~~~
Pydantic v2 domain models for the Moat Verified Agent Capabilities Marketplace.

All models are immutable by default (``model_config = ConfigDict(frozen=True)``),
serialise datetimes as ISO-8601 UTC strings, and validate on assignment.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class RiskClass(StrEnum):
    """Ordered severity tiers for capability risk classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CapabilityStatus(StrEnum):
    """Lifecycle state of a published capability."""

    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class ExecutionStatus(StrEnum):
    """Terminal status of a single capability invocation."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    POLICY_DENIED = "policy_denied"


class ErrorTaxonomy(StrEnum):
    """Coarse-grained error categories for outcome reporting."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    PROVIDER_5XX = "provider_5xx"
    VALIDATION = "validation"
    POLICY_DENIED = "policy_denied"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    """Return current UTC time with timezone awareness."""
    return datetime.now(tz=UTC)


def _new_uuid() -> str:
    """Return a fresh UUID4 string."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Base configuration
# ---------------------------------------------------------------------------


class _FrozenModel(BaseModel):
    """Shared base: immutable, strict-mode, UTC-serialised datetimes."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


# ---------------------------------------------------------------------------
# CapabilityManifest
# ---------------------------------------------------------------------------


class CapabilityManifest(_FrozenModel):
    """Registry entry describing a verifiable agent capability.

    Example::

        manifest = CapabilityManifest(
            id="cap_search_v1",
            name="Web Search",
            version="1.0.0",
            provider="acme-corp",
            method="POST /search",
            description="Searches the web and returns ranked results.",
            scopes=["search:read"],
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
            output_schema={"type": "object"},
            risk_class=RiskClass.LOW,
            domain_allowlist=["*.acme.com"],
            status=CapabilityStatus.PUBLISHED,
        )
    """

    id: str = Field(
        ..., min_length=1, description="Stable unique capability identifier."
    )
    name: str = Field(..., min_length=1, description="Human-readable display name.")
    version: str = Field(
        ...,
        description="Semantic version string (semver, e.g. '1.2.3' or '2.0.0-beta.1').",
    )
    provider: str = Field(
        ...,
        min_length=1,
        description="Identifier of the organisation publishing this capability.",
    )
    method: str = Field(
        ...,
        min_length=1,
        description="HTTP method + path, e.g. 'POST /v1/search'.",
    )
    description: str = Field(
        ..., min_length=1, description="Plain-English capability description."
    )
    scopes: list[str] = Field(
        default_factory=list,
        description="OAuth-style scopes required to invoke this capability.",
    )
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema describing the expected request payload.",
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema describing the response payload.",
    )
    risk_class: RiskClass = Field(
        ..., description="Risk classification tier (low → critical)."
    )
    domain_allowlist: list[str] = Field(
        default_factory=list,
        description="Glob-style domain patterns that may call this capability.",
    )
    status: CapabilityStatus = Field(
        default=CapabilityStatus.DRAFT,
        description="Current lifecycle state.",
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        description="UTC timestamp when the manifest was first created.",
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        description="UTC timestamp of the most recent update.",
    )

    @field_validator("version")
    @classmethod
    def _validate_semver(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError(
                f"version '{v}' is not valid semver (expected MAJOR.MINOR.PATCH[-pre])"
            )
        return v

    @model_validator(mode="after")
    def _updated_not_before_created(self) -> CapabilityManifest:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


class Receipt(_FrozenModel):
    """Immutable audit record produced after each capability invocation.

    Inputs and outputs are stored only as SHA-256 hashes of their
    redacted representations - no raw secrets ever enter the receipt.

    Example::

        receipt = Receipt(
            capability_id="cap_search_v1",
            capability_version="1.0.0",
            tenant_id="tenant_abc",
            idempotency_key="idem_xyz",
            input_hash="a" * 64,
            output_hash="b" * 64,
            latency_ms=142.5,
            status=ExecutionStatus.SUCCESS,
        )
    """

    id: str = Field(
        default_factory=_new_uuid,
        description="Unique receipt UUID.",
    )
    capability_id: str = Field(..., min_length=1)
    capability_version: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    timestamp: datetime = Field(default_factory=_utcnow)
    idempotency_key: str = Field(
        ...,
        min_length=1,
        description="Caller-supplied or generated idempotency key.",
    )
    input_hash: str = Field(
        ...,
        description="SHA-256 hex digest of the redacted input payload.",
        min_length=64,
        max_length=64,
    )
    output_hash: str = Field(
        ...,
        description="SHA-256 hex digest of the output payload.",
        min_length=64,
        max_length=64,
    )
    latency_ms: float = Field(
        ..., ge=0.0, description="Wall-clock latency in milliseconds."
    )
    status: ExecutionStatus
    error_code: str | None = Field(
        default=None,
        description=(
            "Short machine-readable error code, present on non-success outcomes."
        ),
    )
    provider_request_id: str | None = Field(
        default=None,
        description="Upstream provider's request identifier for correlation.",
    )

    @field_validator("input_hash", "output_hash")
    @classmethod
    def _validate_sha256_hex(cls, v: str, info: Any) -> str:
        if not all(c in "0123456789abcdef" for c in v.lower()):
            raise ValueError(
                f"{info.field_name} must be a lowercase hex SHA-256 digest"
            )
        return v.lower()


# ---------------------------------------------------------------------------
# OutcomeEvent
# ---------------------------------------------------------------------------


class OutcomeEvent(_FrozenModel):
    """Lightweight analytics event derived from a Receipt.

    Emitted to the outcome stream after each invocation for
    real-time SLA monitoring and SLO tracking.

    Example::

        event = OutcomeEvent(
            receipt_id="some-uuid",
            capability_id="cap_search_v1",
            tenant_id="tenant_abc",
            success=True,
            latency_ms=142.5,
        )
    """

    id: str = Field(default_factory=_new_uuid)
    receipt_id: str = Field(..., min_length=1)
    capability_id: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    success: bool
    latency_ms: float = Field(..., ge=0.0)
    error_taxonomy: ErrorTaxonomy | None = Field(
        default=None,
        description="Coarse error category; None when success=True.",
    )
    timestamp: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _error_taxonomy_on_failure(self) -> OutcomeEvent:
        if not self.success and self.error_taxonomy is None:
            raise ValueError("error_taxonomy must be set when success=False")
        if self.success and self.error_taxonomy is not None:
            raise ValueError("error_taxonomy must be None when success=True")
        return self


# ---------------------------------------------------------------------------
# PolicyBundle
# ---------------------------------------------------------------------------


class PolicyBundle(_FrozenModel):
    """Tenant-scoped policy controlling access and spend for a capability.

    Example::

        bundle = PolicyBundle(
            id="bundle_tenant_abc_search",
            tenant_id="tenant_abc",
            capability_id="cap_search_v1",
            allowed_scopes=["search:read"],
            budget_daily=500,        # $5.00/day
            domain_allowlist=["*.acme.com"],
        )
    """

    id: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    capability_id: str = Field(..., min_length=1)
    allowed_scopes: list[str] = Field(default_factory=list)
    budget_daily: int | None = Field(
        default=None,
        ge=0,
        description="Daily spend ceiling in cents (USD). None = unlimited.",
    )
    budget_monthly: int | None = Field(
        default=None,
        ge=0,
        description="Monthly spend ceiling in cents (USD). None = unlimited.",
    )
    domain_allowlist: list[str] = Field(
        default_factory=list,
        description="Domains permitted to invoke via this bundle. Empty = all.",
    )
    require_approval: bool = Field(
        default=False,
        description="When True, each invocation requires explicit human approval.",
    )
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# PolicyDecision
# ---------------------------------------------------------------------------


class PolicyDecision(_FrozenModel):
    """Immutable result of evaluating a PolicyBundle against a request.

    Produced by :func:`moat_core.policy.evaluate_policy` and stored for
    audit purposes alongside the Receipt.

    Example::

        decision = PolicyDecision(
            policy_bundle_id="bundle_tenant_abc_search",
            tenant_id="tenant_abc",
            capability_id="cap_search_v1",
            allowed=True,
            rule_hit="all_checks_passed",
            evaluation_ms=0.42,
            request_id="req_123",
        )
    """

    id: str = Field(default_factory=_new_uuid)
    policy_bundle_id: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    capability_id: str = Field(..., min_length=1)
    allowed: bool
    rule_hit: str = Field(
        ...,
        min_length=1,
        description="Name of the rule that determined the outcome.",
    )
    evaluation_ms: float = Field(..., ge=0.0)
    timestamp: datetime = Field(default_factory=_utcnow)
    request_id: str = Field(
        ...,
        min_length=1,
        description="Caller-supplied request ID for tracing.",
    )


# ---------------------------------------------------------------------------
# Web3ExecutionContext
# ---------------------------------------------------------------------------


class Web3ExecutionContext(_FrozenModel):
    """Metadata for receipts that touch Web3.

    Attached to Moat receipts for executions that involve on-chain
    interactions — either inbound intents (from IRSB indexer) or
    outbound contract calls (via Web3Adapter).

    Example::

        ctx = Web3ExecutionContext(
            chain_id=11155111,
            contract_address="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
            tx_hash="0xabc...",
            block_number=12345,
            direction="outbound",
        )
    """

    chain_id: int = Field(
        ..., description="EIP-155 chain ID (e.g. 11155111 for Sepolia)."
    )
    contract_address: str = Field(
        default="", description="Target contract address (0x-prefixed)."
    )
    tx_hash: str = Field(
        default="", description="Transaction hash (0x-prefixed hex, 66 chars)."
    )
    block_number: int = Field(default=0, description="Block number of the transaction.")
    rpc_url_domain: str = Field(
        default="", description="Domain of the RPC endpoint used."
    )
    direction: str = Field(
        default="outbound",
        description="Direction: 'outbound' (Moat→chain) or 'inbound' (chain→Moat).",
    )
    intent_hash: str = Field(
        default="",
        description="EIP-712 CIE intentId (0x-prefixed bytes32 hex).",
    )
