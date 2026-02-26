"""
app.skill_builder
~~~~~~~~~~~~~~~~~
Discover A2A agents and register their skills as Moat capabilities.

The Skill Builder bridges the A2A discovery protocol with Moat's
capability registry. Given an agent URL, it:

1. Fetches the agent's A2A AgentCard
2. Parses each skill into a CapabilityManifest
3. Registers each as a capability in the control-plane
4. Creates a PolicyBundle so the tenant can invoke it

This enables automatic onboarding of A2A-compatible agents into the
Moat execution pipeline with full policy, receipts, and trust scoring.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_DISCOVERY_TIMEOUT_S = 10.0


async def fetch_agent_card(agent_url: str) -> dict[str, Any] | None:
    """Fetch the A2A AgentCard from a remote agent.

    Tries ``/.well-known/agent.json`` per the A2A spec.

    Returns:
        The AgentCard dict, or None if unreachable/invalid.
    """
    url = f"{agent_url.rstrip('/')}/.well-known/agent.json"
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT_S) as client:
            resp = await client.get(
                url, headers={"User-Agent": "Moat-SkillBuilder/0.1.0"}
            )
            if resp.status_code == 200:
                card = resp.json()
                logger.info(
                    "Fetched A2A AgentCard",
                    extra={
                        "agent_url": agent_url,
                        "agent_name": card.get("name", "unknown"),
                        "skill_count": len(card.get("skills", [])),
                    },
                )
                return card
            logger.warning(
                "Agent discovery failed",
                extra={"agent_url": url, "status_code": resp.status_code},
            )
    except Exception as exc:
        logger.warning(
            "Failed to fetch AgentCard",
            extra={"agent_url": url, "error": str(exc)},
        )
    return None


def _skill_to_capability(
    skill: dict[str, Any],
    agent_card: dict[str, Any],
) -> dict[str, Any]:
    """Convert an A2A skill to a Moat capability registration payload.

    Maps A2A skill fields to the control-plane's capability schema.
    """
    agent_name = agent_card.get("name", "unknown-agent")
    skill_id = skill.get("id", skill.get("name", "unknown-skill"))

    return {
        "name": f"{agent_name}/{skill_id}",
        "description": skill.get("description", ""),
        "provider": "a2a",
        "version": agent_card.get("version", "0.1.0"),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_url": {
                    "type": "string",
                    "description": "A2A agent base URL",
                    "default": agent_card.get("url", ""),
                },
                "skill_id": {
                    "type": "string",
                    "description": "Skill to invoke",
                    "default": skill_id,
                },
                "message": {
                    "type": "string",
                    "description": "Input message for the skill",
                },
            },
            "required": ["message"],
        },
        "output_schema": {},
        "status": "active",
        "tags": skill.get("tags", []) + ["a2a", f"agent:{agent_name}"],
    }


async def register_agent_skills(
    agent_url: str,
    *,
    tenant_id: str = "automaton",
    budget_daily: int = 5000,
) -> dict[str, Any]:
    """Discover an A2A agent and register its skills as Moat capabilities.

    Args:
        agent_url: Base URL of the A2A agent.
        tenant_id: Tenant that will own the capabilities.
        budget_daily: Daily budget (cents) for each capability's PolicyBundle.

    Returns:
        Summary dict with registered capabilities and any errors.
    """
    card = await fetch_agent_card(agent_url)
    if card is None:
        return {
            "status": "error",
            "error": f"Could not fetch AgentCard from {agent_url}",
            "capabilities_registered": 0,
        }

    skills = card.get("skills", [])
    if not skills:
        return {
            "status": "no_skills",
            "agent_name": card.get("name", "unknown"),
            "capabilities_registered": 0,
        }

    registered = []
    errors = []

    for skill in skills:
        cap_payload = _skill_to_capability(skill, card)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Register capability in control-plane
                resp = await client.post(
                    f"{settings.CONTROL_PLANE_URL}/capabilities",
                    json=cap_payload,
                )

                if resp.status_code in (200, 201):
                    cap_data = resp.json()
                    cap_id = cap_data.get("capability_id", "")
                    registered.append(
                        {
                            "capability_id": cap_id,
                            "name": cap_payload["name"],
                            "skill_id": skill.get("id", ""),
                        }
                    )

                    # Register a PolicyBundle for this capability
                    _register_skill_policy(
                        capability_id=cap_id,
                        capability_name=cap_payload["name"],
                        tenant_id=tenant_id,
                        budget_daily=budget_daily,
                    )
                else:
                    errors.append(
                        {
                            "skill": skill.get("id", "unknown"),
                            "status_code": resp.status_code,
                            "error": resp.text[:200],
                        }
                    )
        except Exception as exc:
            errors.append(
                {
                    "skill": skill.get("id", "unknown"),
                    "error": str(exc),
                }
            )

    result = {
        "status": "success" if registered else "partial",
        "agent_name": card.get("name", "unknown"),
        "agent_url": agent_url,
        "capabilities_registered": len(registered),
        "registered": registered,
    }

    if errors:
        result["errors"] = errors
        if not registered:
            result["status"] = "error"

    logger.info(
        "Skill builder completed",
        extra={
            "agent_url": agent_url,
            "registered": len(registered),
            "errors": len(errors),
        },
    )

    return result


def _register_skill_policy(
    capability_id: str,
    capability_name: str,
    tenant_id: str,
    budget_daily: int,
) -> None:
    """Register a PolicyBundle for a discovered A2A skill."""
    from moat_core.models import PolicyBundle

    from app.policy_bridge import register_policy_bundle

    safe_name = capability_name.replace("/", "_").replace(".", "_")
    bundle = PolicyBundle(
        id=f"pb_{tenant_id}_{safe_name}",
        tenant_id=tenant_id,
        capability_id=capability_id,
        allowed_scopes=["execute"],
        budget_daily=budget_daily,
    )
    register_policy_bundle(bundle)
