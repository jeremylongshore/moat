"""
app.policy_bridge
~~~~~~~~~~~~~~~~~
Thin shim that provides policy evaluation for the gateway.

Currently uses a permissive stub that allows all requests. In Phase 4,
this will be replaced with proper moat_core.policy.evaluate_policy
integration once PolicyBundle storage and tenant isolation are implemented.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PolicyResult:
    """Simplified policy decision returned by the bridge."""

    allowed: bool
    reason: str = ""
    rule_hit: str = ""
    risk_class: str = "LOW"


def evaluate_policy(
    capability_id: str,
    tenant_id: str,
    scope: str,
    params: dict[str, Any],
) -> PolicyResult:
    """Evaluate the policy bundle for a capability execution request.

    Currently returns a permissive stub that allows all requests.
    This will be integrated with moat_core.policy.evaluate_policy
    in Phase 4 when PolicyBundle storage is implemented.

    Args:
        capability_id: The capability being invoked.
        tenant_id: The tenant making the request.
        scope: The requested permission scope (e.g. 'execute').
        params: The request parameters (for future spend tracking).

    Returns:
        PolicyResult with allowed=True (permissive stub).
    """
    # TODO Phase 4: Look up PolicyBundle from DB for (tenant_id, capability_id)
    # TODO Phase 4: Calculate current_spend_cents from recent receipts
    # TODO Phase 4: Build CapabilityManifest from capability metadata
    # TODO Phase 4: Call moat_core.policy.evaluate_policy(bundle, manifest, scope, spend)

    logger.debug(
        "Policy evaluation (permissive stub)",
        extra={
            "capability_id": capability_id,
            "tenant_id": tenant_id,
            "scope": scope,
        },
    )

    return PolicyResult(
        allowed=True,
        reason="stub_policy_allow",
        rule_hit="all_checks_passed",
        risk_class="LOW",
    )
