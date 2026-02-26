"""
app.intent_listener
~~~~~~~~~~~~~~~~~~~
Webhook endpoint for inbound on-chain intents.

When the IRSB indexer (Envio HyperIndex) detects an on-chain intent that
maps to a Moat capability, it POSTs to this webhook. The gateway then
routes the intent through the standard execution pipeline (policy → adapter
→ receipt → trust plane).

This is a one-way bridge: on-chain → off-chain execution. The reverse
direction (off-chain execution → on-chain receipt) is handled by the
IRSB receipt hook (hooks/irsb_receipt.py).

Usage::

    POST /intents/inbound
    {
        "intent_hash": "0xabc...",
        "chain_id": 11155111,
        "contract_address": "0xD66A...",
        "block_number": 12345,
        "tx_hash": "0xdef...",
        "capability_id": "gwi.triage",
        "params": {"url": "https://github.com/org/repo/issues/42"},
        "tenant_id": "automaton",
        "sender": "0x83Be..."
    }
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intents", tags=["web3-bridge"])


# ---------------------------------------------------------------------------
# Agent address → tenant mapping
# ---------------------------------------------------------------------------

# Fallback mapping for known addresses when control-plane is unreachable.
# Loaded from env: INTENT_FALLBACK_TENANTS="0xAddr1:tenant1,0xAddr2:tenant2"
import os as _os

_raw_fallback = _os.environ.get(
    "INTENT_FALLBACK_TENANTS",
    "0x83Be08FFB22b61733eDf15b0ee9Caf5562cd888d:automaton",
)
_FALLBACK_TENANT_MAP: dict[str, str] = {
    pair.split(":")[0].strip().lower(): pair.split(":")[1].strip()
    for pair in _raw_fallback.split(",")
    if ":" in pair
}

# In-memory cache: address → tenant_id (populated from control-plane)
_address_tenant_cache: dict[str, str] = {}


async def _resolve_tenant_from_registry(sender: str) -> str | None:
    """Look up the tenant_id for a sender address via control-plane agents API.

    Checks in-memory cache first, then queries the control-plane agent
    registry for agents with a matching ERC-8004 registry address
    (the on-chain solver/agent address).
    """
    sender_lower = sender.lower()

    # Check cache
    if sender_lower in _address_tenant_cache:
        return _address_tenant_cache[sender_lower]

    # Query control-plane agent registry
    try:
        import httpx

        from app.config import settings

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.CONTROL_PLANE_URL}/agents")
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                for agent in items:
                    # Match on ERC-8004 registry address (solver address)
                    reg_addr = (agent.get("erc8004_registry_address") or "").lower()
                    if reg_addr == sender_lower:
                        tenant = agent.get("owner_tenant_id") or "automaton"
                        _address_tenant_cache[sender_lower] = tenant
                        return tenant
    except Exception as exc:
        logger.debug(
            "Control-plane lookup failed, using fallback",
            extra={"sender": sender, "error": str(exc)},
        )

    # Fall back to hardcoded map
    tenant = _FALLBACK_TENANT_MAP.get(sender_lower)
    if tenant:
        _address_tenant_cache[sender_lower] = tenant
    return tenant


def _resolve_tenant(sender: str) -> str | None:
    """Synchronous wrapper — check cache and fallback only.

    The async path (_resolve_tenant_from_registry) is preferred.
    This exists for backwards compatibility in sync contexts.
    """
    sender_lower = sender.lower()
    cached = _address_tenant_cache.get(sender_lower)
    if cached:
        return cached
    return _FALLBACK_TENANT_MAP.get(sender_lower)


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class InboundIntentEvent(BaseModel):
    """On-chain intent event forwarded by the IRSB indexer."""

    intent_hash: str = Field(
        ...,
        description="bytes32 intent hash (0x-prefixed)",
    )
    chain_id: int = Field(
        ...,
        description="EIP-155 chain ID where the intent was emitted",
    )
    contract_address: str = Field(
        ...,
        description="Address of the contract that emitted the intent",
    )
    block_number: int = Field(
        ...,
        description="Block number containing the intent transaction",
    )
    tx_hash: str = Field(
        ...,
        description="Transaction hash (0x-prefixed)",
    )
    capability_id: str = Field(
        ...,
        description="Moat capability ID mapped from the on-chain action",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Decoded parameters from calldata",
    )
    tenant_id: str = Field(
        default="",
        description="Tenant ID (derived from sender if not provided)",
    )
    sender: str = Field(
        ...,
        description="On-chain sender address (the agent)",
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/inbound",
    summary="Receive an inbound on-chain intent",
    responses={
        200: {"description": "Intent processed, receipt returned"},
        403: {"description": "Sender not authorized"},
        502: {"description": "Execution failed"},
    },
)
async def receive_intent(
    event: InboundIntentEvent,
    request: Request,
) -> dict[str, Any]:
    """Receive an on-chain intent and execute it through the Moat pipeline.

    Steps:
    1. Validate sender has a registered tenant mapping
    2. Construct an execute request from the intent fields
    3. Call the same execute pipeline (policy → adapter → receipt)
    4. Return receipt with on-chain correlation metadata
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # Step 1: Resolve tenant from sender address (async DB lookup)
    tenant_id = event.tenant_id
    if not tenant_id:
        tenant_id = await _resolve_tenant_from_registry(event.sender)
    if not tenant_id:
        logger.warning(
            "Inbound intent from unregistered sender",
            extra={
                "sender": event.sender,
                "intent_hash": event.intent_hash,
                "request_id": request_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sender {event.sender} is not registered as a Moat tenant",
        )

    logger.info(
        "Processing inbound intent",
        extra={
            "intent_hash": event.intent_hash,
            "chain_id": event.chain_id,
            "capability_id": event.capability_id,
            "tenant_id": tenant_id,
            "sender": event.sender,
            "block_number": event.block_number,
            "request_id": request_id,
        },
    )

    # Step 2 & 3: Execute through the gateway pipeline
    # Import here to avoid circular imports
    from app.routers.execute import ExecuteRequest, execute_capability

    exec_request = ExecuteRequest(
        params=event.params,
        tenant_id=tenant_id,
        scope="execute",
    )

    try:
        # We need to simulate a proper FastAPI request context.
        # The execute_capability expects BackgroundTasks and auth.
        from fastapi import BackgroundTasks

        bg_tasks = BackgroundTasks()

        receipt = await execute_capability(
            capability_id=event.capability_id,
            body=exec_request,
            request=request,
            background_tasks=bg_tasks,
            auth_tenant_id=tenant_id,  # Bypass auth — indexer is trusted
        )

        # Run background tasks (IRSB receipt hook, outcome event)
        for task in bg_tasks.tasks:
            try:
                await task.func(*task.args, **task.kwargs)
            except Exception as bg_exc:
                logger.warning(
                    "Background task failed for intent",
                    extra={"error": str(bg_exc), "intent_hash": event.intent_hash},
                )

        receipt_dict = (
            receipt.model_dump() if hasattr(receipt, "model_dump") else dict(receipt)
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Intent execution failed",
            extra={
                "intent_hash": event.intent_hash,
                "capability_id": event.capability_id,
                "error": str(exc),
                "request_id": request_id,
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Intent execution failed: {exc}",
        ) from exc

    # Step 4: Return receipt with on-chain correlation
    return {
        "receipt": receipt_dict,
        "intent_correlation": {
            "intent_hash": event.intent_hash,
            "chain_id": event.chain_id,
            "tx_hash": event.tx_hash,
            "block_number": event.block_number,
            "contract_address": event.contract_address,
            "sender": event.sender,
        },
        "request_id": request_id,
    }
