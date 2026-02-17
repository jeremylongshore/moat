"""
moat_core.policy
~~~~~~~~~~~~~~~~
Policy evaluation engine for Moat.

``evaluate_policy`` is the single entry point.  It receives a
:class:`~moat_core.models.PolicyBundle` (tenant-scoped rules) and a
:class:`~moat_core.models.CapabilityManifest` (what is being requested),
plus runtime state (requested scope and current spend), and returns an
immutable :class:`~moat_core.models.PolicyDecision`.

Evaluation order
----------------
Rules are checked in priority order and the first failure short-circuits:

1. ``scope_not_allowed``  - the requested OAuth scope is absent from the bundle.
2. ``budget_daily_exceeded`` - current spend meets or exceeds the daily ceiling.
3. ``domain_allowlist_conflict`` - the bundle restricts domains and the
   capability's own ``domain_allowlist`` is not a strict subset.
4. ``require_approval`` - the bundle requires human approval (always deny
   at evaluation time; the approval flow is handled upstream).
5. ``all_checks_passed`` - every rule passed; request is allowed.

Default-deny
------------
If no PolicyBundle is available (the caller passes ``None``), the engine
returns a denied decision with ``rule_hit="no_policy_bundle"``.  This
ensures new capabilities start inaccessible until explicitly unlocked.
"""

from __future__ import annotations

import time
import uuid
from typing import overload

from moat_core.models import (
    CapabilityManifest,
    PolicyBundle,
    PolicyDecision,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@overload
def evaluate_policy(
    bundle: None,
    capability: CapabilityManifest,
    scope: str,
    current_spend_cents: int,
    *,
    request_id: str = ...,
) -> PolicyDecision: ...


@overload
def evaluate_policy(
    bundle: PolicyBundle,
    capability: CapabilityManifest,
    scope: str,
    current_spend_cents: int,
    *,
    request_id: str = ...,
) -> PolicyDecision: ...


def evaluate_policy(
    bundle: PolicyBundle | None,
    capability: CapabilityManifest,
    scope: str,
    current_spend_cents: int,
    *,
    request_id: str = "",
) -> PolicyDecision:
    """Evaluate whether a request is permitted under the given policy bundle.

    Args:
        bundle: The tenant-scoped :class:`~moat_core.models.PolicyBundle`
            to evaluate against.  Pass ``None`` to trigger default-deny
            (no bundle configured).
        capability: The :class:`~moat_core.models.CapabilityManifest`
            being invoked.
        scope: The OAuth-style scope string requested by the caller,
            e.g. ``'search:read'``.
        current_spend_cents: Accumulated spend for today in US cents.
            Used to enforce ``budget_daily``.
        request_id: Caller-supplied trace ID.  A UUID is generated when
            not provided.

    Returns:
        An immutable :class:`~moat_core.models.PolicyDecision` with
        ``allowed=True`` iff all rules passed.

    Example::

        bundle = PolicyBundle(
            id="b1",
            tenant_id="t1",
            capability_id="cap_v1",
            allowed_scopes=["search:read"],
            budget_daily=500,
        )
        manifest = CapabilityManifest(
            id="cap_v1", name="Search", version="1.0.0",
            provider="acme", method="POST /search",
            description="...", risk_class=RiskClass.LOW,
        )
        decision = evaluate_policy(bundle, manifest, "search:read", 100)
        assert decision.allowed is True
    """
    _request_id = request_id or str(uuid.uuid4())
    t_start = time.perf_counter()

    # ------------------------------------------------------------------
    # Default-deny: no bundle configured
    # ------------------------------------------------------------------
    if bundle is None:
        return _decision(
            bundle_id="__none__",
            tenant_id="__unknown__",
            capability_id=capability.id,
            allowed=False,
            rule_hit="no_policy_bundle",
            t_start=t_start,
            request_id=_request_id,
        )

    # ------------------------------------------------------------------
    # Rule 1: scope must be in allowed_scopes
    # ------------------------------------------------------------------
    if scope not in bundle.allowed_scopes:
        return _decision(
            bundle_id=bundle.id,
            tenant_id=bundle.tenant_id,
            capability_id=capability.id,
            allowed=False,
            rule_hit=f"scope_not_allowed:{scope}",
            t_start=t_start,
            request_id=_request_id,
        )

    # ------------------------------------------------------------------
    # Rule 2: daily budget ceiling
    # ------------------------------------------------------------------
    if (
        bundle.budget_daily is not None
        and current_spend_cents >= bundle.budget_daily
    ):
        return _decision(
            bundle_id=bundle.id,
            tenant_id=bundle.tenant_id,
            capability_id=capability.id,
            allowed=False,
            rule_hit=(
                f"budget_daily_exceeded:"
                f"spend={current_spend_cents},"
                f"limit={bundle.budget_daily}"
            ),
            t_start=t_start,
            request_id=_request_id,
        )

    # ------------------------------------------------------------------
    # Rule 3: domain allowlist - bundle domains must be a superset of
    # the capability's domain_allowlist (or the bundle allows all domains)
    # ------------------------------------------------------------------
    if bundle.domain_allowlist:
        # Capability may further restrict to a subset of the bundle's
        # domains.  A capability domain is rejected if it does not appear
        # verbatim in the bundle's allowlist.
        # This is a simple exact-match check; glob expansion is out of
        # scope for the core policy engine.
        cap_domains = set(capability.domain_allowlist)
        bundle_domains = set(bundle.domain_allowlist)
        disallowed = cap_domains - bundle_domains
        if disallowed:
            return _decision(
                bundle_id=bundle.id,
                tenant_id=bundle.tenant_id,
                capability_id=capability.id,
                allowed=False,
                rule_hit=(
                    f"domain_allowlist_conflict:"
                    f"disallowed={sorted(disallowed)}"
                ),
                t_start=t_start,
                request_id=_request_id,
            )

    # ------------------------------------------------------------------
    # Rule 4: require_approval blocks automated execution
    # ------------------------------------------------------------------
    if bundle.require_approval:
        return _decision(
            bundle_id=bundle.id,
            tenant_id=bundle.tenant_id,
            capability_id=capability.id,
            allowed=False,
            rule_hit="require_approval",
            t_start=t_start,
            request_id=_request_id,
        )

    # ------------------------------------------------------------------
    # All checks passed
    # ------------------------------------------------------------------
    return _decision(
        bundle_id=bundle.id,
        tenant_id=bundle.tenant_id,
        capability_id=capability.id,
        allowed=True,
        rule_hit="all_checks_passed",
        t_start=t_start,
        request_id=_request_id,
    )


# ---------------------------------------------------------------------------
# Internal factory
# ---------------------------------------------------------------------------


def _decision(
    *,
    bundle_id: str,
    tenant_id: str,
    capability_id: str,
    allowed: bool,
    rule_hit: str,
    t_start: float,
    request_id: str,
) -> PolicyDecision:
    """Construct a :class:`~moat_core.models.PolicyDecision` with
    timing information filled in automatically."""
    evaluation_ms = (time.perf_counter() - t_start) * 1_000
    return PolicyDecision(
        policy_bundle_id=bundle_id,
        tenant_id=tenant_id,
        capability_id=capability_id,
        allowed=allowed,
        rule_hit=rule_hit,
        evaluation_ms=evaluation_ms,
        request_id=request_id,
    )
