"""
app.routers.execute
~~~~~~~~~~~~~~~~~~~
Capability execution endpoint.

Full execution pipeline per request
------------------------------------
1. Fetch capability metadata from control plane (or local cache)
2. Validate capability is active
3. Evaluate policy (moat_core.policy via policy_bridge)
4. Check idempotency - if key exists, return cached receipt immediately
5. Resolve credential from vault (stub in MVP)
6. Dispatch to adapter (StubAdapter or real provider adapter)
7. Build Receipt
8. Emit OutcomeEvent to trust plane (async, best-effort)
9. Store result in idempotency cache
10. Return Receipt to caller
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from moat_core.auth import get_current_tenant
from pydantic import BaseModel, Field

from app.adapters.base import registry as adapter_registry
from app.adapters.local_cli import LocalCLIAdapter
from app.adapters.slack import SlackAdapter
from app.adapters.stub import StubAdapter
from app.capability_cache import get_capability
from app.config import settings
from app.hooks.irsb_receipt import post_irsb_receipt
from app.idempotency_store import idempotency_store
from app.policy_bridge import evaluate_policy, record_spend

# Register adapters — stub for dev fallback, real providers for production
adapter_registry.register(StubAdapter())
adapter_registry.register(SlackAdapter())
adapter_registry.register(LocalCLIAdapter())

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/execute", tags=["execution"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ExecuteRequest(BaseModel):
    """Payload for a capability execution request."""

    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Input parameters for the capability "
            "(validated against capability's input_schema)"
        ),
    )
    tenant_id: str = Field(..., min_length=1, description="Tenant making the request")
    scope: str = Field(
        default="execute",
        description="Permission scope (e.g. 'execute', 'read', 'admin')",
    )
    idempotency_key: str | None = Field(
        default=None,
        description=(
            "Optional idempotency key. If provided and a prior request with the same "
            "tenant_id + key succeeded, the cached receipt is returned immediately "
            "without re-executing the capability."
        ),
    )


class ReceiptResponse(BaseModel):
    """Receipt returned after a capability execution."""

    receipt_id: str
    capability_id: str
    tenant_id: str
    status: str  # "success" | "failure"
    result: dict[str, Any]
    idempotency_key: str | None
    executed_at: str
    latency_ms: float
    cached: bool = Field(
        default=False,
        description="True if this receipt was returned from the idempotency cache",
    )
    policy_risk_class: str = "LOW"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_receipt(
    capability_id: str,
    tenant_id: str,
    result: dict[str, Any],
    idempotency_key: str | None,
    executed_at: datetime,
    latency_ms: float,
    policy_risk_class: str,
    exec_status: str = "success",
) -> dict[str, Any]:
    return {
        "receipt_id": str(uuid.uuid4()),
        "capability_id": capability_id,
        "tenant_id": tenant_id,
        "status": exec_status,
        "result": result,
        "idempotency_key": idempotency_key,
        "executed_at": executed_at.isoformat(),
        "latency_ms": latency_ms,
        "cached": False,
        "policy_risk_class": policy_risk_class,
    }


async def _emit_outcome_event(receipt: dict[str, Any]) -> None:
    """Send an OutcomeEvent to the trust plane (best-effort, non-blocking)."""
    event = {
        "event_id": str(uuid.uuid4()),
        "capability_id": receipt["capability_id"],
        "tenant_id": receipt["tenant_id"],
        "receipt_id": receipt["receipt_id"],
        "execution_status": receipt["status"],
        "latency_ms": receipt.get("latency_ms", 0),
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{settings.TRUST_PLANE_URL}/events",
                json=event,
            )
            if response.status_code not in (200, 201, 204):
                logger.warning(
                    "Trust plane returned unexpected status",
                    extra={
                        "status_code": response.status_code,
                        "receipt_id": receipt["receipt_id"],
                    },
                )
    except httpx.HTTPError as exc:
        # Non-fatal: trust plane stats may lag, but execution is not blocked.
        logger.warning(
            "Failed to emit outcome event to trust plane",
            extra={"error": str(exc), "receipt_id": receipt["receipt_id"]},
        )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/{capability_id}",
    response_model=ReceiptResponse,
    summary="Execute a capability",
    responses={
        200: {"description": "Execution succeeded (or idempotency cache hit)"},
        401: {"description": "Authentication required"},
        403: {"description": "Policy denied the execution or tenant mismatch"},
        404: {"description": "Capability not found"},
        422: {"description": "Invalid request parameters"},
        502: {"description": "Upstream adapter failure"},
    },
)
async def execute_capability(
    capability_id: str,
    body: ExecuteRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    auth_tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ReceiptResponse:
    """Execute a capability through the full Moat pipeline.

    **Pipeline steps:**

    1. Fetch capability from control plane (cached locally for 5 min)
    2. Validate capability status is ``active``
    3. Evaluate policy - deny and return 403 if not allowed
    4. Check idempotency key - return cached receipt if key was seen before
    5. Execute via the appropriate adapter
    6. Build and cache the receipt
    7. Emit OutcomeEvent to trust plane (best-effort)
    8. Return the receipt
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # ------------------------------------------------------------------
    # Step 0: Verify tenant_id in body matches authenticated tenant
    # ------------------------------------------------------------------
    if body.tenant_id != auth_tenant_id:
        logger.warning(
            "Tenant ID mismatch",
            extra={
                "body_tenant_id": body.tenant_id,
                "auth_tenant_id": auth_tenant_id,
                "capability_id": capability_id,
                "request_id": request_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant ID in request body does not match authenticated tenant",
        )

    # ------------------------------------------------------------------
    # Step 1: Fetch capability
    # ------------------------------------------------------------------
    capability = await get_capability(capability_id)
    if capability is None:
        logger.warning(
            "Capability not found",
            extra={"capability_id": capability_id, "request_id": request_id},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{capability_id}' not found",
        )

    # ------------------------------------------------------------------
    # Step 2: Validate capability is active
    # ------------------------------------------------------------------
    cap_status = capability.get("status", "active")
    if cap_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Capability '{capability_id}' is not active (status: {cap_status})",
        )

    # ------------------------------------------------------------------
    # Step 3: Policy evaluation
    # ------------------------------------------------------------------
    policy_result = evaluate_policy(
        capability_id=capability_id,
        tenant_id=body.tenant_id,
        scope=body.scope,
        params=body.params,
        capability_dict=capability,
        request_id=request_id,
    )

    if not policy_result.allowed:
        logger.warning(
            "Policy denied execution",
            extra={
                "capability_id": capability_id,
                "tenant_id": body.tenant_id,
                "rule_hit": policy_result.rule_hit,
                "reason": policy_result.reason,
                "request_id": request_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "policy_denied",
                "reason": policy_result.reason,
                "rule_hit": policy_result.rule_hit,
                "risk_class": policy_result.risk_class,
                "capability_id": capability_id,
                "tenant_id": body.tenant_id,
            },
        )

    # ------------------------------------------------------------------
    # Step 4: Idempotency check
    # ------------------------------------------------------------------
    if body.idempotency_key:
        cached_receipt = await idempotency_store.get(
            body.tenant_id, body.idempotency_key
        )
        if cached_receipt is not None:
            logger.info(
                "Idempotency cache hit - returning cached receipt",
                extra={
                    "capability_id": capability_id,
                    "tenant_id": body.tenant_id,
                    "idempotency_key": body.idempotency_key,
                    "receipt_id": cached_receipt.get("receipt_id"),
                    "request_id": request_id,
                },
            )
            cached_receipt = dict(cached_receipt)
            cached_receipt["cached"] = True
            return ReceiptResponse(**cached_receipt)

    # ------------------------------------------------------------------
    # Step 5: Resolve credential (stub: no real vault in MVP)
    # ------------------------------------------------------------------
    # In production, retrieve the credential reference from the connection
    # record and resolve it via the vault. For MVP, pass None.
    credential: str | None = None

    # ------------------------------------------------------------------
    # Step 6: Execute via adapter
    # ------------------------------------------------------------------
    provider = capability.get("provider", "stub")
    adapter = adapter_registry.get_or_stub(provider)

    start = datetime.now(UTC)
    try:
        result = await adapter.execute(
            capability_id=capability_id,
            capability_name=capability.get("name", capability_id),
            params=body.params,
            credential=credential,
        )
        exec_status = "success"
    except Exception as exc:
        logger.error(
            "Adapter execution failed",
            extra={
                "capability_id": capability_id,
                "provider": provider,
                "error": str(exc),
                "request_id": request_id,
            },
            exc_info=True,
        )
        # Still build a failure receipt rather than returning a raw 500.
        # Don't leak internal error details to client.
        result = {"error": "adapter_execution_failed", "provider": provider}
        exec_status = "failure"

    end = datetime.now(UTC)
    latency_ms = (end - start).total_seconds() * 1000

    # ------------------------------------------------------------------
    # Step 7: Build receipt
    # ------------------------------------------------------------------
    receipt = _build_receipt(
        capability_id=capability_id,
        tenant_id=body.tenant_id,
        result=result,
        idempotency_key=body.idempotency_key,
        executed_at=start,
        latency_ms=round(latency_ms, 2),
        policy_risk_class=policy_result.risk_class,
        exec_status=exec_status,
    )

    # ------------------------------------------------------------------
    # Step 8: Emit outcome event to trust plane (best-effort)
    # ------------------------------------------------------------------
    background_tasks.add_task(_emit_outcome_event, receipt)

    # ------------------------------------------------------------------
    # Step 8b: Post IRSB receipt on-chain (best-effort, non-blocking)
    # ------------------------------------------------------------------
    background_tasks.add_task(post_irsb_receipt, receipt)

    # ------------------------------------------------------------------
    # Step 9: Store in idempotency cache (only for successful executions)
    # ------------------------------------------------------------------
    if body.idempotency_key and exec_status == "success":
        await idempotency_store.set(body.tenant_id, body.idempotency_key, receipt)

    # Track spend for budget enforcement (1 cent per call for now)
    if exec_status == "success":
        record_spend(body.tenant_id, 1)

    # ------------------------------------------------------------------
    # Step 10: Return receipt
    # ------------------------------------------------------------------
    logger.info(
        "Capability executed",
        extra={
            "capability_id": capability_id,
            "tenant_id": body.tenant_id,
            "provider": provider,
            "status": exec_status,
            "latency_ms": round(latency_ms, 2),
            "request_id": request_id,
        },
    )
    return ReceiptResponse(**receipt)
