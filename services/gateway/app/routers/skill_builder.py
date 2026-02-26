"""
app.routers.skill_builder
~~~~~~~~~~~~~~~~~~~~~~~~~~
REST endpoints for the A2A Skill Builder.

Allows agents and operators to:
- Discover and register A2A agent skills as Moat capabilities
- Fetch a remote agent's AgentCard
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.skill_builder import fetch_agent_card, register_agent_skills

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skill-builder", tags=["skill-builder"])


class RegisterAgentRequest(BaseModel):
    """Request to register an A2A agent's skills."""

    agent_url: str = Field(..., description="Base URL of the A2A agent")
    tenant_id: str = Field(
        default="automaton",
        description="Tenant that will own the registered capabilities",
    )
    budget_daily: int = Field(
        default=5000,
        description="Daily budget (cents) per capability",
    )


@router.post(
    "/register",
    summary="Register A2A agent skills as Moat capabilities",
    response_model=None,
)
async def register_agent(body: RegisterAgentRequest) -> dict[str, Any]:
    """Discover an A2A agent and register its skills.

    Fetches the agent's ``/.well-known/agent.json``, parses each skill,
    and registers it as a Moat capability in the control-plane with
    provider ``a2a``. A PolicyBundle is created for each so the
    specified tenant can invoke them through the gateway.
    """
    return await register_agent_skills(
        agent_url=body.agent_url,
        tenant_id=body.tenant_id,
        budget_daily=body.budget_daily,
    )


@router.get(
    "/discover",
    summary="Fetch a remote agent's A2A AgentCard",
    response_model=None,
)
async def discover_agent(agent_url: str) -> dict[str, Any]:
    """Fetch the A2A AgentCard from a remote agent URL.

    Does not register anything — just returns the card for inspection.
    """
    card = await fetch_agent_card(agent_url)
    if card is None:
        return {
            "status": "error",
            "error": f"Could not fetch AgentCard from {agent_url}",
        }
    return {"status": "ok", "agent_card": card}
