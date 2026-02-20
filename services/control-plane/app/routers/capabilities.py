"""
app.routers.capabilities
~~~~~~~~~~~~~~~~~~~~~~~~
Capability registry endpoints.

Capabilities are the atomic units of verifiable AI behaviour that Moat
tracks. Each capability has a provider, a versioned JSON schema pair
(input/output), and a lifecycle status.

Storage: async SQLAlchemy (Postgres in production, SQLite for local dev).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from moat_core.auth import get_current_tenant, get_optional_tenant
from pydantic import BaseModel, Field, field_validator

from app.store import capability_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CapabilityCreateRequest(BaseModel):
    """Payload to register a new capability."""

    name: str = Field(
        ..., min_length=1, max_length=128, description="Human-readable capability name"
    )
    description: str = Field(
        ..., min_length=1, max_length=2048, description="What this capability does"
    )
    provider: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Provider identifier (e.g. 'openai', 'anthropic')",
    )
    version: str = Field(
        ..., pattern=r"^\d+\.\d+\.\d+$", description="Semver capability version"
    )
    input_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for accepted input parameters"
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for returned output"
    )
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    status: Literal["active", "inactive", "deprecated"] = Field(
        default="active",
        description="Initial lifecycle status",
    )

    @field_validator("tags")
    @classmethod
    def normalise_tags(cls, v: list[str]) -> list[str]:
        return [t.lower().strip() for t in v if t.strip()]


class CapabilityResponse(BaseModel):
    """Capability representation returned by the API."""

    capability_id: str
    name: str
    description: str
    provider: str
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: str
    tags: list[str]
    owner_tenant_id: str | None = None
    created_at: str


class CapabilityListResponse(BaseModel):
    items: list[CapabilityResponse]
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CapabilityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new capability",
)
async def create_capability(
    body: CapabilityCreateRequest,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> CapabilityResponse:
    """Register a new capability in the Moat registry.

    Returns the created capability with its server-assigned ``capability_id``.
    """
    data = body.model_dump()
    data["owner_tenant_id"] = tenant_id
    record = await capability_store.create(data)
    logger.info(
        "Capability registered",
        extra={
            "capability_id": record.capability_id,
            "provider": record.provider,
            "capability_name": record.name,
            "owner_tenant_id": tenant_id,
        },
    )
    return CapabilityResponse(**record.to_dict())


@router.get(
    "",
    response_model=CapabilityListResponse,
    summary="List capabilities",
)
async def list_capabilities(
    provider: Annotated[str | None, Query(description="Filter by provider")] = None,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    _tenant_id: Annotated[str | None, Depends(get_optional_tenant)] = None,
) -> CapabilityListResponse:
    """Return all registered capabilities with optional filters."""
    records = await capability_store.list(provider=provider, status=status)
    items = [CapabilityResponse(**r.to_dict()) for r in records]
    return CapabilityListResponse(items=items, total=len(items))


@router.get(
    "/{capability_id}",
    response_model=CapabilityResponse,
    summary="Get a single capability",
)
async def get_capability(
    capability_id: str,
    _tenant_id: Annotated[str | None, Depends(get_optional_tenant)] = None,
) -> CapabilityResponse:
    """Fetch a single capability by its ID."""
    record = await capability_store.get(capability_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{capability_id}' not found",
        )
    return CapabilityResponse(**record.to_dict())


@router.patch(
    "/{capability_id}/status",
    response_model=CapabilityResponse,
    summary="Update capability status",
)
async def update_capability_status(
    capability_id: str,
    new_status: Annotated[Literal["active", "inactive", "deprecated"], Query()],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> CapabilityResponse:
    """Change a capability's lifecycle status."""
    # Verify capability exists and caller owns it
    existing = await capability_store.get(capability_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{capability_id}' not found",
        )
    if existing.owner_tenant_id and existing.owner_tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this capability",
        )

    record = await capability_store.update_status(capability_id, new_status)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{capability_id}' not found",
        )
    logger.info(
        "Capability status updated",
        extra={
            "capability_id": capability_id,
            "new_status": new_status,
            "tenant_id": tenant_id,
        },
    )
    return CapabilityResponse(**record.to_dict())
