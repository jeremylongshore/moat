"""
moat_core.db.models
~~~~~~~~~~~~~~~~~~~
SQLAlchemy ORM models for Moat persistence.

Each row class maps to a database table and provides a ``to_dict()``
method that returns the same shape as the legacy in-memory records,
so existing router code only needs to add ``await`` to store calls.
"""

from __future__ import annotations

from datetime import UTC, datetime

# JSON type that works across both Postgres (native JSONB) and SQLite (TEXT).
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from moat_core.db.base import Base


class CapabilityRow(Base):
    """Registered capability in the control-plane registry."""

    __tablename__ = "capabilities"

    capability_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    owner_tenant_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    def to_dict(self) -> dict:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "provider": self.provider,
            "version": self.version,
            "input_schema": self.input_schema or {},
            "output_schema": self.output_schema or {},
            "status": self.status,
            "tags": self.tags or [],
            "owner_tenant_id": self.owner_tenant_id,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class ConnectionRow(Base):
    """Tenant-to-provider connection with vault credential reference."""

    __tablename__ = "connections"

    connection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    def to_dict(self) -> dict:
        return {
            "connection_id": self.connection_id,
            "tenant_id": self.tenant_id,
            "provider": self.provider,
            "credential_reference": self.credential_reference,
            "display_name": self.display_name or "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class ReceiptRow(Base):
    """Execution receipt persisted by the gateway."""

    __tablename__ = "receipts"

    receipt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    capability_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    policy_risk_class: Mapped[str] = mapped_column(String(16), default="LOW")
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    def to_dict(self) -> dict:
        return {
            "receipt_id": self.receipt_id,
            "capability_id": self.capability_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "result": self.result or {},
            "idempotency_key": self.idempotency_key,
            "executed_at": self.executed_at.isoformat() if self.executed_at else "",
            "latency_ms": self.latency_ms,
            "cached": self.cached,
            "policy_risk_class": self.policy_risk_class,
        }


class OutcomeEventRow(Base):
    """Outcome event ingested by the trust plane."""

    __tablename__ = "outcome_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    capability_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    receipt_id: Mapped[str] = mapped_column(String(64), default="")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PolicyBundleRow(Base):
    """Tenant-scoped policy bundle for capability access control."""

    __tablename__ = "policy_bundles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    capability_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    allowed_scopes: Mapped[list] = mapped_column(JSON, default=list)
    budget_daily: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_monthly: Mapped[int | None] = mapped_column(Integer, nullable=True)
    domain_allowlist: Mapped[list] = mapped_column(JSON, default=list)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AgentRow(Base):
    """Registered agent in the control-plane agent registry.

    Supports A2A AgentCard fields plus ERC-8004 on-chain identity.
    """

    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    provider_org: Mapped[str] = mapped_column(String(128), default="Moat")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    capabilities_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    authentication: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    owner_tenant_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    # ERC-8004 on-chain identity fields
    erc8004_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    erc8004_chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    erc8004_registry_address: Mapped[str | None] = mapped_column(
        String(42), nullable=True
    )
    erc8004_agent_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # SPIFFE workload identity (future)
    spiffe_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "provider_org": self.provider_org,
            "skills": self.skills or [],
            "capabilities": self.capabilities_meta or {},
            "authentication": self.authentication or {},
            "status": self.status,
            "owner_tenant_id": self.owner_tenant_id,
            "erc8004_agent_id": self.erc8004_agent_id,
            "erc8004_chain_id": self.erc8004_chain_id,
            "erc8004_registry_address": (self.erc8004_registry_address),
            "erc8004_agent_uri": self.erc8004_agent_uri,
            "spiffe_id": self.spiffe_id,
            "created_at": (self.created_at.isoformat() if self.created_at else ""),
        }


class IdempotencyCacheRow(Base):
    """Idempotency cache entry mapping (tenant, key) to a receipt."""

    __tablename__ = "idempotency_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    receipt_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    stored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_idempotency"),
    )
