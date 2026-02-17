"""
app.store
~~~~~~~~~
In-memory stores for MVP development.

These are module-level singletons intentionally kept simple. Replace with
real DB-backed repositories (SQLAlchemy async + Alembic) when moving to
production.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


# ---------------------------------------------------------------------------
# Capability store
# ---------------------------------------------------------------------------

class CapabilityRecord:
    """Lightweight container for a registered capability."""

    def __init__(
        self,
        *,
        capability_id: str,
        name: str,
        description: str,
        provider: str,
        version: str,
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        status: str = "active",
        tags: list[str] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.capability_id = capability_id
        self.name = name
        self.description = description
        self.provider = provider
        self.version = version
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.status = status
        self.tags = tags or []
        self.created_at = created_at or datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "provider": self.provider,
            "version": self.version,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "status": self.status,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
        }


class CapabilityStore:
    """In-memory capability registry."""

    def __init__(self) -> None:
        self._records: dict[str, CapabilityRecord] = {}

    def create(self, data: dict[str, Any]) -> CapabilityRecord:
        capability_id = str(uuid4())
        record = CapabilityRecord(capability_id=capability_id, **data)
        self._records[capability_id] = record
        return record

    def get(self, capability_id: str) -> CapabilityRecord | None:
        return self._records.get(capability_id)

    def list(
        self,
        provider: str | None = None,
        status: str | None = None,
    ) -> list[CapabilityRecord]:
        results = list(self._records.values())
        if provider:
            results = [r for r in results if r.provider == provider]
        if status:
            results = [r for r in results if r.status == status]
        return results

    def update_status(self, capability_id: str, status: str) -> CapabilityRecord | None:
        record = self._records.get(capability_id)
        if record:
            record.status = status
        return record

    def __len__(self) -> int:
        return len(self._records)


# ---------------------------------------------------------------------------
# Connection store
# ---------------------------------------------------------------------------

class ConnectionRecord:
    """A connection links a tenant to a provider via a credential reference."""

    def __init__(
        self,
        *,
        connection_id: str,
        tenant_id: str,
        provider: str,
        credential_reference: str,
        display_name: str = "",
        created_at: datetime | None = None,
    ) -> None:
        self.connection_id = connection_id
        self.tenant_id = tenant_id
        self.provider = provider
        # Store only the opaque reference, never the secret itself.
        self.credential_reference = credential_reference
        self.display_name = display_name
        self.created_at = created_at or datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "tenant_id": self.tenant_id,
            "provider": self.provider,
            # credential_reference is safe to return (opaque pointer, not the secret)
            "credential_reference": self.credential_reference,
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat(),
        }


class ConnectionStore:
    """In-memory connection registry."""

    def __init__(self) -> None:
        self._records: dict[str, ConnectionRecord] = {}

    def create(self, data: dict[str, Any]) -> ConnectionRecord:
        connection_id = str(uuid4())
        record = ConnectionRecord(connection_id=connection_id, **data)
        self._records[connection_id] = record
        return record

    def get(self, connection_id: str) -> ConnectionRecord | None:
        return self._records.get(connection_id)

    def list(self, tenant_id: str | None = None) -> list[ConnectionRecord]:
        results = list(self._records.values())
        if tenant_id:
            results = [r for r in results if r.tenant_id == tenant_id]
        return results

    def __len__(self) -> int:
        return len(self._records)


# Module-level singletons
capability_store = CapabilityStore()
connection_store = ConnectionStore()
