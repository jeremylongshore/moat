"""
app.erc8004.ipfs
~~~~~~~~~~~~~~~~
Pin agent metadata and service catalog to IPFS.

Supports Pinata as the primary pinning service, with a local
fallback that writes to disk for testing/dev environments.

Pinned content:
  - Agent registration JSON (ERC-8004 agentURI target)
  - Service catalog (full list of registered agents)
  - Execution receipts (immutable audit trail)

The IPFS CID is used as the agentURI in the ERC-8004 Identity Registry,
providing content-addressed, immutable agent metadata.

Configuration:
  PINATA_JWT:       Pinata API JWT (required for production pinning)
  PINATA_GATEWAY:   Pinata gateway URL (default: gateway.pinata.cloud)
  IPFS_DRY_RUN:    Log but don't actually pin (default: true)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PINATA_JWT = os.environ.get("PINATA_JWT", "")
PINATA_GATEWAY = os.environ.get("PINATA_GATEWAY", "gateway.pinata.cloud")
PINATA_API_URL = "https://api.pinata.cloud"
IPFS_DRY_RUN = os.environ.get("IPFS_DRY_RUN", "true").lower() == "true"


# ---------------------------------------------------------------------------
# Pinning operations
# ---------------------------------------------------------------------------


async def pin_json(
    data: dict[str, Any],
    name: str = "moat-agent-metadata",
) -> dict[str, Any]:
    """Pin a JSON object to IPFS via Pinata.

    Args:
        data: JSON-serializable dict to pin.
        name: Human-readable name for the pin (metadata label).

    Returns:
        Dict with ipfs_hash (CID), gateway_url, size, and status.
    """
    result: dict[str, Any] = {"name": name}

    if IPFS_DRY_RUN:
        # Compute a deterministic hash for dry-run
        import hashlib

        content = json.dumps(data, sort_keys=True)
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:46]
        dry_cid = f"bafybeig{content_hash}"

        result["ipfs_hash"] = dry_cid
        result["gateway_url"] = f"https://{PINATA_GATEWAY}/ipfs/{dry_cid}"
        result["size"] = len(content)
        result["status"] = "dry_run"

        logger.info(
            "IPFS pin (dry-run)",
            extra={"cid": dry_cid, "pin_name": name, "size": len(content)},
        )
        return result

    if not PINATA_JWT:
        result["status"] = "no_jwt"
        logger.warning("PINATA_JWT not configured — cannot pin to IPFS")
        return result

    try:
        import httpx

        headers = {
            "Authorization": f"Bearer {PINATA_JWT}",
            "Content-Type": "application/json",
        }

        payload = {
            "pinataContent": data,
            "pinataMetadata": {"name": name},
            "pinataOptions": {"cidVersion": 1},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{PINATA_API_URL}/pinning/pinJSONToIPFS",
                headers=headers,
                json=payload,
            )

            if resp.status_code == 200:
                pin_data = resp.json()
                cid = pin_data["IpfsHash"]
                result["ipfs_hash"] = cid
                result["gateway_url"] = f"https://{PINATA_GATEWAY}/ipfs/{cid}"
                result["size"] = pin_data.get("PinSize", 0)
                result["status"] = "pinned"
                result["timestamp"] = pin_data.get("Timestamp", "")

                logger.info(
                    "Pinned to IPFS via Pinata",
                    extra={"cid": cid, "pin_name": name, "size": result["size"]},
                )
            else:
                result["status"] = "error"
                result["error"] = resp.text[:500]
                logger.warning(
                    "Pinata pin failed",
                    extra={
                        "status_code": resp.status_code,
                        "pin_name": name,
                        "error": resp.text[:200],
                    },
                )

    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        logger.error("IPFS pin error", extra={"pin_name": name, "error": str(exc)})

    return result


async def pin_agent_metadata(
    agent: dict[str, Any],
    *,
    chain_id: int = 11155111,
    registry_address: str = "",
) -> dict[str, Any]:
    """Build and pin ERC-8004 agent metadata to IPFS.

    Combines metadata generation with IPFS pinning. Returns the
    pin result including the IPFS CID that can be used as the
    agentURI on-chain.

    Args:
        agent: Agent dict from AgentRow.to_dict().
        chain_id: EIP-155 chain ID.
        registry_address: Identity Registry address.

    Returns:
        Dict with metadata, ipfs_hash, gateway_url.
    """
    from app.erc8004.metadata import build_agent_metadata

    metadata = build_agent_metadata(
        agent, chain_id=chain_id, registry_address=registry_address
    )

    agent_name = agent.get("name", "moat-agent")
    pin_result = await pin_json(metadata, name=f"erc8004-{agent_name}")

    return {
        "metadata": metadata,
        "pin": pin_result,
        "agent_uri": pin_result.get("gateway_url", ""),
    }


async def pin_service_catalog(
    agents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pin a full service catalog (list of all agents) to IPFS.

    This provides a single CID containing the complete directory
    of registered agents, useful for on-chain catalog discovery.
    """
    catalog = {
        "type": "moat-service-catalog",
        "version": "0.1.0",
        "agents": [
            {
                "name": a.get("name", ""),
                "description": a.get("description", ""),
                "url": a.get("url", ""),
                "status": a.get("status", "active"),
                "erc8004_agent_id": a.get("erc8004_agent_id"),
            }
            for a in agents
        ],
        "total": len(agents),
    }

    return await pin_json(catalog, name="moat-service-catalog")
