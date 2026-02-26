"""
app.routers.agents
~~~~~~~~~~~~~~~~~~
Agent registry endpoints with ERC-8004 on-chain identity support.

Agents are registered AI services that can be discovered via
A2A protocol. Each agent has:
- A2A AgentCard metadata (name, url, skills, capabilities)
- Optional ERC-8004 on-chain identity (NFT-based agent ID)
- Optional SPIFFE workload identity (for service mesh auth)

Storage: async SQLAlchemy (Postgres in production, SQLite local).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from moat_core.auth import get_current_tenant, get_optional_tenant
from pydantic import BaseModel, Field

from app.store import agent_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AgentSkillSchema(BaseModel):
    """Skill advertised by an agent."""

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class ERC8004Identity(BaseModel):
    """ERC-8004 on-chain identity fields."""

    agent_id: int | None = Field(
        default=None,
        description="ERC-8004 NFT token ID",
    )
    chain_id: int | None = Field(
        default=None,
        description="EIP-155 chain ID (e.g. 1 for mainnet)",
    )
    registry_address: str | None = Field(
        default=None,
        description="Identity Registry contract address",
    )
    agent_uri: str | None = Field(
        default=None,
        description="Agent URI pointing to registration JSON",
    )


class AgentCreateRequest(BaseModel):
    """Payload to register a new agent."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Unique agent name",
    )
    description: str = Field(
        default="",
        max_length=2048,
        description="What this agent does",
    )
    url: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Agent base URL",
    )
    version: str = Field(default="0.1.0")
    provider_org: str = Field(default="Moat")
    skills: list[AgentSkillSchema] = Field(
        default_factory=list,
    )
    capabilities: dict[str, Any] = Field(
        default_factory=lambda: {
            "streaming": False,
            "push_notifications": False,
            "state_transition_history": False,
        },
    )
    authentication: dict[str, Any] = Field(
        default_factory=dict,
    )
    erc8004: ERC8004Identity = Field(
        default_factory=ERC8004Identity,
    )
    spiffe_id: str | None = Field(
        default=None,
        description="SPIFFE workload identity URI",
    )


class AgentUpdateRequest(BaseModel):
    """Payload to update an existing agent."""

    description: str | None = None
    url: str | None = None
    version: str | None = None
    skills: list[AgentSkillSchema] | None = None
    capabilities: dict[str, Any] | None = None
    authentication: dict[str, Any] | None = None
    status: str | None = None
    erc8004: ERC8004Identity | None = None
    spiffe_id: str | None = None


class AgentResponse(BaseModel):
    """Agent representation returned by the API."""

    agent_id: str
    name: str
    description: str
    url: str
    version: str
    provider_org: str
    skills: list[dict[str, Any]]
    capabilities: dict[str, Any]
    authentication: dict[str, Any]
    status: str
    owner_tenant_id: str | None = None
    erc8004_agent_id: int | None = None
    erc8004_chain_id: int | None = None
    erc8004_registry_address: str | None = None
    erc8004_agent_uri: str | None = None
    spiffe_id: str | None = None
    created_at: str


class AgentListResponse(BaseModel):
    items: list[AgentResponse]
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new agent",
)
async def create_agent(
    body: AgentCreateRequest,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> AgentResponse:
    """Register a new agent in the Moat agent registry.

    Supports A2A AgentCard fields and optional ERC-8004
    on-chain identity binding.
    """
    # Check for duplicate name
    existing = await agent_store.get_by_name(body.name)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent '{body.name}' already exists",
        )

    data = {
        "name": body.name,
        "description": body.description,
        "url": body.url,
        "version": body.version,
        "provider_org": body.provider_org,
        "skills": [s.model_dump() for s in body.skills],
        "capabilities_meta": body.capabilities,
        "authentication": body.authentication,
        "owner_tenant_id": tenant_id,
        "erc8004_agent_id": body.erc8004.agent_id,
        "erc8004_chain_id": body.erc8004.chain_id,
        "erc8004_registry_address": (body.erc8004.registry_address),
        "erc8004_agent_uri": body.erc8004.agent_uri,
        "spiffe_id": body.spiffe_id,
    }

    record = await agent_store.create(data)
    logger.info(
        "Agent registered",
        extra={
            "agent_id": record.agent_id,
            "agent_name": record.name,
            "owner_tenant_id": tenant_id,
            "erc8004_agent_id": record.erc8004_agent_id,
        },
    )
    return AgentResponse(**record.to_dict())


@router.get(
    "",
    response_model=AgentListResponse,
    summary="List registered agents",
)
async def list_agents(
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter by status"),
    ] = None,
    _tenant_id: Annotated[str | None, Depends(get_optional_tenant)] = None,
) -> AgentListResponse:
    """Return all registered agents with optional filters."""
    records = await agent_store.list(status=status_filter)
    items = [AgentResponse(**r.to_dict()) for r in records]
    return AgentListResponse(items=items, total=len(items))


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Get a single agent",
)
async def get_agent(
    agent_id: str,
    _tenant_id: Annotated[str | None, Depends(get_optional_tenant)] = None,
) -> AgentResponse:
    """Fetch a single agent by its ID."""
    record = await agent_store.get(agent_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    return AgentResponse(**record.to_dict())


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Update an agent",
)
async def update_agent(
    agent_id: str,
    body: AgentUpdateRequest,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> AgentResponse:
    """Update an agent's metadata, skills, or identity."""
    existing = await agent_store.get(agent_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    if existing.owner_tenant_id and existing.owner_tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this agent",
        )

    update_data: dict[str, Any] = {}
    if body.description is not None:
        update_data["description"] = body.description
    if body.url is not None:
        update_data["url"] = body.url
    if body.version is not None:
        update_data["version"] = body.version
    if body.skills is not None:
        update_data["skills"] = [s.model_dump() for s in body.skills]
    if body.capabilities is not None:
        update_data["capabilities_meta"] = body.capabilities
    if body.authentication is not None:
        update_data["authentication"] = body.authentication
    if body.status is not None:
        update_data["status"] = body.status
    if body.spiffe_id is not None:
        update_data["spiffe_id"] = body.spiffe_id
    if body.erc8004 is not None:
        erc = body.erc8004
        if erc.agent_id is not None:
            update_data["erc8004_agent_id"] = erc.agent_id
        if erc.chain_id is not None:
            update_data["erc8004_chain_id"] = erc.chain_id
        if erc.registry_address is not None:
            update_data["erc8004_registry_address"] = erc.registry_address
        if erc.agent_uri is not None:
            update_data["erc8004_agent_uri"] = erc.agent_uri

    record = await agent_store.update(agent_id, update_data)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    logger.info(
        "Agent updated",
        extra={
            "agent_id": agent_id,
            "fields_updated": list(update_data.keys()),
            "tenant_id": tenant_id,
        },
    )
    return AgentResponse(**record.to_dict())


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent",
)
async def delete_agent(
    agent_id: str,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> None:
    """Remove an agent from the registry."""
    existing = await agent_store.get(agent_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    if existing.owner_tenant_id and existing.owner_tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this agent",
        )

    await agent_store.delete(agent_id)
    logger.info(
        "Agent deleted",
        extra={
            "agent_id": agent_id,
            "tenant_id": tenant_id,
        },
    )
