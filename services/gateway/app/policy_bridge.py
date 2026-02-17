"""
app.policy_bridge
~~~~~~~~~~~~~~~~~
Thin shim that calls moat_core.policy.evaluate_policy when available,
falling back to a permissive stub when the core package is not yet complete.

This allows the gateway to run and be tested without the full moat_core
package being installed.
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

    Delegates to ``moat_core.policy.evaluate_policy`` if available.
    Falls back to a permissive stub that logs a warning.
    """
    try:
        from moat_core.policy import evaluate_policy as core_evaluate  # type: ignore[import]

        decision = core_evaluate(
            capability_id=capability_id,
            tenant_id=tenant_id,
            scope=scope,
            params=params,
        )
        # Adapt moat_core PolicyDecision to our internal PolicyResult
        return PolicyResult(
            allowed=decision.allowed,
            reason=getattr(decision, "reason", ""),
            rule_hit=getattr(decision, "rule_hit", ""),
            risk_class=getattr(decision, "risk_class", "LOW"),
        )
    except ImportError:
        logger.warning(
            "moat_core.policy not available - using permissive stub. "
            "Install moat-core with full policy engine for production.",
            extra={"capability_id": capability_id, "tenant_id": tenant_id},
        )
        return PolicyResult(
            allowed=True,
            reason="stub_policy_allow",
            rule_hit="",
            risk_class="LOW",
        )
    except Exception as exc:
        logger.error(
            "Policy evaluation error - denying request for safety",
            extra={
                "capability_id": capability_id,
                "tenant_id": tenant_id,
                "error": str(exc),
            },
            exc_info=True,
        )
        # Fail closed: deny on any unexpected policy engine error
        return PolicyResult(
            allowed=False,
            reason="policy_engine_error",
            rule_hit="error_failsafe",
            risk_class="HIGH",
        )
