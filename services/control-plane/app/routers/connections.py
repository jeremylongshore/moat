"""
app.routers.connections
~~~~~~~~~~~~~~~~~~~~~~~
Connection management endpoints.

A "connection" represents a tenant's authenticated link to a provider.
The actual credential (API key, OAuth token, etc.) is NEVER stored in the
control plane database. Only an opaque *credential_reference* (pointing to
a vault entry) is persisted and returned.

MVP Storage: in-memory dict (replace with async SQLAlchemy in v2).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.store import connection_store
from app.vault import LocalVault

logger = logging.getLogger(__name__)

# Shared vault instance for this service process.
# In production, swap LocalVault for SecretManagerVault configured via Settings.
_vault = LocalVault()

router = APIRouter(prefix="/connections", tags=["connections"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ConnectionCreateRequest(BaseModel):
    """Payload to create a new provider connection.

    The ``credential_reference`` field must be an **opaque pointer** to a
    secret stored in an external vault, NOT the raw credential value itself.
    If you have a raw credential, use the ``/connections/store-credential``
    helper endpoint first, which will store it in the vault and return a
    reference.
    """

    tenant_id: str = Field(..., min_length=1, max_length=128)
    provider: str = Field(..., min_length=1, max_length=64, description="Provider name (e.g. 'openai')")
    credential_reference: str = Field(
        ...,
        description="Opaque reference to a vault-stored credential. Never the raw secret.",
    )
    display_name: str = Field(default="", max_length=256, description="Human-readable label")


class StoreCredentialRequest(BaseModel):
    """Helper payload to store a raw credential in the vault.

    Use this endpoint to convert a raw secret into a reference. The raw
    secret is passed over TLS, stored in the vault, and discarded from
    the control plane immediately. Only the returned reference is kept.
    """

    tenant_id: str = Field(..., min_length=1)
    provider: str = Field(..., min_length=1)
    credential_value: str = Field(
        ...,
        description="The raw credential (API key, token, etc.). "
                    "Transmitted over TLS only. Never stored in control plane.",
    )


class StoreCredentialResponse(BaseModel):
    credential_reference: str
    provider: str
    tenant_id: str
    message: str = "Credential stored in vault. Use credential_reference for connection creation."


class ConnectionResponse(BaseModel):
    connection_id: str
    tenant_id: str
    provider: str
    credential_reference: str
    display_name: str
    created_at: str


class ConnectionListResponse(BaseModel):
    items: list[ConnectionResponse]
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/store-credential",
    response_model=StoreCredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store a raw credential in the vault and get a reference",
)
async def store_credential(body: StoreCredentialRequest) -> StoreCredentialResponse:
    """Securely store a raw credential in the vault.

    The raw ``credential_value`` is sent over TLS, persisted in the vault
    backend (LocalVault for dev, SecretManagerVault for production), and
    discarded from the control plane's memory immediately after the vault
    call. Only the returned opaque reference should be stored downstream.
    """
    vault_key = f"{body.tenant_id}/{body.provider}/credential"
    reference = await _vault.store_secret(vault_key, body.credential_value)
    logger.info(
        "Credential stored in vault",
        extra={"tenant_id": body.tenant_id, "provider": body.provider},
        # NOTE: credential_value is intentionally NOT logged here.
    )
    return StoreCredentialResponse(
        credential_reference=reference,
        provider=body.provider,
        tenant_id=body.tenant_id,
    )


@router.post(
    "",
    response_model=ConnectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a provider connection",
)
async def create_connection(body: ConnectionCreateRequest) -> ConnectionResponse:
    """Register a new tenant-to-provider connection.

    The ``credential_reference`` must be an opaque vault reference obtained
    from the ``/connections/store-credential`` endpoint. Raw secrets must
    never be passed to this endpoint.
    """
    data = body.model_dump()
    record = connection_store.create(data)
    logger.info(
        "Connection created",
        extra={
            "connection_id": record.connection_id,
            "tenant_id": record.tenant_id,
            "provider": record.provider,
        },
    )
    return ConnectionResponse(**record.to_dict())


@router.get(
    "",
    response_model=ConnectionListResponse,
    summary="List connections",
)
async def list_connections(
    tenant_id: Annotated[str | None, Query(description="Filter by tenant ID")] = None,
) -> ConnectionListResponse:
    """Return all connections, optionally filtered by tenant."""
    records = connection_store.list(tenant_id=tenant_id)
    items = [ConnectionResponse(**r.to_dict()) for r in records]
    return ConnectionListResponse(items=items, total=len(items))


@router.get(
    "/{connection_id}",
    response_model=ConnectionResponse,
    summary="Get a single connection",
)
async def get_connection(connection_id: str) -> ConnectionResponse:
    """Fetch a single connection by its ID."""
    record = connection_store.get(connection_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found",
        )
    return ConnectionResponse(**record.to_dict())
