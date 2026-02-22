"""
app.policy_bridge
~~~~~~~~~~~~~~~~~
Policy evaluation bridge for the gateway.

Integrates with moat_core.policy.evaluate_policy to enforce default-deny
policy on all capability executions. PolicyBundles are fetched from the
control plane (with in-memory fallback for MVP) and capabilities are
converted to CapabilityManifest models for the policy engine.

Spend tracking queries the trust plane for recent receipts to enforce
daily budget ceilings.

Architecture note
-----------------
This policy engine is a stepping stone. When IRSB Phase 2 lands, the
Moat policy engine will be replaced by Cedar policies evaluated inside
the Intentions Gateway. Keep rules simple and portable — do NOT build
Moat-specific features that don't have Cedar equivalents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from moat_core.models import (
    CapabilityManifest,
    CapabilityStatus,
    PolicyBundle,
    PolicyDecision,
    RiskClass,
)
from moat_core.policy import evaluate_policy as _core_evaluate

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class PolicyResult:
    """Simplified policy decision returned by the bridge."""

    allowed: bool
    reason: str = ""
    rule_hit: str = ""
    risk_class: str = "LOW"


# ---------------------------------------------------------------------------
# In-memory PolicyBundle registry (MVP)
#
# Production path: store in Postgres via control-plane API.
# For now, bundles are registered at startup via register_policy_bundle().
# ---------------------------------------------------------------------------

_bundles: dict[str, PolicyBundle] = {}  # key: "{tenant_id}:{capability_id}"


def register_policy_bundle(bundle: PolicyBundle) -> None:
    """Register a PolicyBundle for (tenant_id, capability_id).

    Call this at startup to pre-populate policies for known capabilities.
    """
    key = f"{bundle.tenant_id}:{bundle.capability_id}"
    _bundles[key] = bundle
    logger.info(
        "PolicyBundle registered",
        extra={
            "key": key,
            "allowed_scopes": bundle.allowed_scopes,
            "budget_daily": bundle.budget_daily,
        },
    )


def _get_bundle(tenant_id: str, capability_id: str) -> PolicyBundle | None:
    """Look up the PolicyBundle for a tenant+capability pair."""
    return _bundles.get(f"{tenant_id}:{capability_id}")


# ---------------------------------------------------------------------------
# Spend tracking (in-memory MVP)
#
# Production path: query trust-plane receipts via HTTP or read from DB.
# For now, track spend per (tenant_id, date) in a simple dict.
# ---------------------------------------------------------------------------

_daily_spend: dict[str, int] = {}  # key: "{tenant_id}:{YYYY-MM-DD}" → cents
_last_spend_reset: datetime | None = None


def record_spend(tenant_id: str, amount_cents: int) -> None:
    """Record spend for budget tracking. Called after successful execution."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    key = f"{tenant_id}:{today}"
    _daily_spend[key] = _daily_spend.get(key, 0) + amount_cents


def _get_current_spend(tenant_id: str) -> int:
    """Get today's accumulated spend for a tenant."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return _daily_spend.get(f"{tenant_id}:{today}", 0)


# ---------------------------------------------------------------------------
# Capability dict → CapabilityManifest conversion
# ---------------------------------------------------------------------------


def _dict_to_manifest(cap: dict[str, Any]) -> CapabilityManifest:
    """Convert a capability dict (from cache/control-plane) to a
    CapabilityManifest Pydantic model for the policy engine."""
    # Map status strings. The cache uses "active" but the model uses
    # CapabilityStatus enum values (draft/published/deprecated/archived).
    status_map = {
        "active": CapabilityStatus.PUBLISHED,
        "published": CapabilityStatus.PUBLISHED,
        "draft": CapabilityStatus.DRAFT,
        "deprecated": CapabilityStatus.DEPRECATED,
        "archived": CapabilityStatus.ARCHIVED,
    }
    raw_status = cap.get("status", "active")
    mapped_status = status_map.get(raw_status, CapabilityStatus.PUBLISHED)

    # Risk class mapping
    risk_map = {
        "low": RiskClass.LOW,
        "medium": RiskClass.MEDIUM,
        "high": RiskClass.HIGH,
        "critical": RiskClass.CRITICAL,
    }
    raw_risk = cap.get("risk_class", "low")
    mapped_risk = risk_map.get(str(raw_risk).lower(), RiskClass.LOW)

    return CapabilityManifest(
        id=cap.get("capability_id") or cap.get("id") or "unknown",
        name=cap.get("name", "unknown"),
        version=cap.get("version", "0.0.1"),
        provider=cap.get("provider", "stub"),
        method=cap.get("method", "POST /execute"),
        description=cap.get("description", ""),
        scopes=cap.get("scopes", []),
        domain_allowlist=cap.get("domain_allowlist", []),
        risk_class=mapped_risk,
        status=mapped_status,
    )


# ---------------------------------------------------------------------------
# Public API — called by execute.py step 3
# ---------------------------------------------------------------------------


def evaluate_policy(
    capability_id: str,
    tenant_id: str,
    scope: str,
    params: dict[str, Any],
    *,
    capability_dict: dict[str, Any] | None = None,
    request_id: str = "",
) -> PolicyResult:
    """Evaluate the policy bundle for a capability execution request.

    Uses moat_core.policy.evaluate_policy with real PolicyBundle lookup
    and spend tracking. Default-deny: if no bundle exists, request is denied.

    Args:
        capability_id: The capability being invoked.
        tenant_id: The tenant making the request.
        scope: The requested permission scope (e.g. 'execute').
        params: The request parameters.
        capability_dict: Optional pre-fetched capability metadata dict.
            If not provided, a minimal manifest is constructed.
        request_id: Trace ID for correlation.
    """
    # Look up the PolicyBundle by UUID first, then by name
    bundle = _get_bundle(tenant_id, capability_id)
    if bundle is None and capability_dict:
        cap_name = capability_dict.get("name", "")
        if cap_name:
            bundle = _get_bundle(tenant_id, cap_name)

    # Build CapabilityManifest from dict or minimal defaults
    if capability_dict:
        manifest = _dict_to_manifest(capability_dict)
    else:
        manifest = CapabilityManifest(
            id=capability_id,
            name=capability_id,
            version="0.0.1",
            provider="unknown",
            method="POST /execute",
            description="Auto-generated manifest",
            risk_class=RiskClass.LOW,
        )

    # Get current spend for budget enforcement
    current_spend = _get_current_spend(tenant_id)

    # Call the real policy engine
    decision: PolicyDecision = _core_evaluate(
        bundle=bundle,
        capability=manifest,
        scope=scope,
        current_spend_cents=current_spend,
        request_id=request_id,
    )

    logger.info(
        "Policy evaluation complete",
        extra={
            "capability_id": capability_id,
            "tenant_id": tenant_id,
            "allowed": decision.allowed,
            "rule_hit": decision.rule_hit,
            "evaluation_ms": round(decision.evaluation_ms, 3),
            "current_spend_cents": current_spend,
            "has_bundle": bundle is not None,
        },
    )

    return PolicyResult(
        allowed=decision.allowed,
        reason=decision.rule_hit,
        rule_hit=decision.rule_hit,
        risk_class=manifest.risk_class.value if hasattr(manifest.risk_class, 'value') else str(manifest.risk_class),
    )
