"""
app.erc8004.metadata
~~~~~~~~~~~~~~~~~~~~
Generate ERC-8004 compliant agent metadata from Moat agent data.

The agentURI in ERC-8004 points to a JSON registration file that
describes the agent. This module builds that JSON from either a
Moat AgentCard or a DB AgentRow dict.

Spec reference: https://eips.ethereum.org/EIPS/eip-8004
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_agent_metadata(
    agent: dict[str, Any],
    *,
    chain_id: int = 11155111,
    registry_address: str = "",
) -> dict[str, Any]:
    """Build ERC-8004 registration metadata JSON.

    Args:
        agent: Agent dict (from AgentRow.to_dict() or AgentCard).
        chain_id: EIP-155 chain ID for the registry reference.
        registry_address: Identity Registry contract address.

    Returns:
        ERC-8004 compliant registration JSON.
    """
    # Build services from skills
    services = []
    skills = agent.get("skills", [])
    for skill in skills:
        services.append(
            {
                "name": skill.get("id", skill.get("name", "")),
                "endpoint": agent.get("url", ""),
                "version": agent.get("version", "0.1.0"),
                "skills": skill.get("tags", []),
            }
        )

    # If no skills, add a single service entry
    if not services:
        services.append(
            {
                "name": agent.get("name", "moat-agent"),
                "endpoint": agent.get("url", ""),
                "version": agent.get("version", "0.1.0"),
            }
        )

    # Build registrations array
    registrations = []
    erc8004_id = agent.get("erc8004_agent_id")
    if erc8004_id is not None:
        reg_addr = agent.get("erc8004_registry_address") or registry_address
        reg_chain = agent.get("erc8004_chain_id") or chain_id
        registrations.append(
            {
                "agentId": erc8004_id,
                "agentRegistry": (f"eip155:{reg_chain}:{reg_addr}"),
            }
        )

    return {
        "type": ("https://eips.ethereum.org/EIPS/eip-8004#registration-v1"),
        "name": agent.get("name", ""),
        "description": agent.get("description", ""),
        "image": "",
        "services": services,
        "x402Support": False,
        "active": agent.get("status", "active") == "active",
        "registrations": registrations,
        "supportedTrust": ["reputation"],
    }


def build_feedback_metadata(
    agent_id: int,
    *,
    chain_id: int = 11155111,
    registry_address: str = "",
    client_address: str = "",
    value: int = 100,
    tag1: str = "moat-execution",
    tag2: str = "",
    endpoint: str = "",
    capability_id: str = "",
) -> dict[str, Any]:
    """Build ERC-8004 Reputation Registry feedback metadata.

    Used when posting execution feedback on-chain after
    trust-plane scoring.
    """
    return {
        "agentRegistry": (f"eip155:{chain_id}:{registry_address}"),
        "agentId": agent_id,
        "clientAddress": f"eip155:{chain_id}:{client_address}",
        "value": value,
        "valueDecimals": 0,
        "tag1": tag1,
        "tag2": tag2 or capability_id,
        "endpoint": endpoint,
    }
