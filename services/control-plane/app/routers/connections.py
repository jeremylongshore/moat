"""
app.routers.connections
~~~~~~~~~~~~~~~~~~~~~~~
Connection management endpoints.

A "connection" represents a tenant's authenticated link to a provider.
The actual credential (API key, OAuth token, etc.) is NEVER stored in the
control plane database. Only an opaque *credential_reference* (pointing to
a vault entry) is persisted and returned.

Storage: async SQLAlchemy (Postgres in production, SQLite for local dev).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from moat_core.auth import get_current_tenant
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
    tenant_id: str = Field(..., min_length=1, max_length=128)
    provider: str = Field(
        ..., min_length=1, max_length=64, description="Provider name (e.g. 'openai')"
    )
    credential_reference: str = Field(
        ...,
        description=(
            "Opaque reference to a vault-stored credential. "
            "Never the raw secret."
        ),
    )
    display_name: str = Field(
        default="", max_length=256, description="Human-readable label"
    )


class StoreCredentialRequest(BaseModel):
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
    message: str = (
        "Credential stored in vault. Use credential_reference for connection creation."
    )


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
async def store_credential(
    body: StoreCredentialRequest,
    auth_tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> StoreCredentialResponse:
    """Securely store a raw credential in the vault."""
    # Verify body tenant_id matches authenticated tenant
    if body.tenant_id != auth_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant ID in request body does not match authenticated tenant",
        )

    vault_key = f"{body.tenant_id}/{body.provider}/credential"
    reference = await _vault.store_secret(vault_key, body.credential_value)
    logger.info(
        "Credential stored in vault",
        extra={"tenant_id": body.tenant_id, "provider": body.provider},
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
async def create_connection(
    body: ConnectionCreateRequest,
    auth_tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ConnectionResponse:
    """Register a new tenant-to-provider connection."""
    # Verify body tenant_id matches authenticated tenant
    if body.tenant_id != auth_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant ID in request body does not match authenticated tenant",
        )

    data = body.model_dump()
    record = await connection_store.create(data)
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
    auth_tenant_id: Annotated[str, Depends(get_current_tenant)],
    tenant_id: Annotated[
        str | None, Query(description="Filter by tenant ID (ignored, uses auth)")
    ] = None,
) -> ConnectionListResponse:
    """Return all connections for the authenticated tenant.

    Note: The tenant_id query param is ignored - connections are always
    scoped to the authenticated tenant for security.
    """
    # Always filter by authenticated tenant (tenant isolation)
    records = await connection_store.list(tenant_id=auth_tenant_id)
    items = [ConnectionResponse(**r.to_dict()) for r in records]
    return ConnectionListResponse(items=items, total=len(items))


@router.get(
    "/{connection_id}",
    response_model=ConnectionResponse,
    summary="Get a single connection",
)
async def get_connection(
    connection_id: str,
    auth_tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ConnectionResponse:
    """Fetch a single connection by its ID (must belong to authenticated tenant)."""
    record = await connection_store.get(connection_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found",
        )

    # Verify connection belongs to authenticated tenant
    if record.tenant_id != auth_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found",
        )

    return ConnectionResponse(**record.to_dict())
