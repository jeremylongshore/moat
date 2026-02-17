"""
Tests for moat_core.policy.

Covers: each denial rule, allow path, default-deny (no bundle), timing,
and determinism of PolicyDecision fields.
"""

from __future__ import annotations

import pytest

from moat_core import (
    CapabilityManifest,
    PolicyBundle,
    PolicyDecision,
    RiskClass,
    evaluate_policy,
)
from moat_core.models import CapabilityStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manifest() -> CapabilityManifest:
    return CapabilityManifest(
        id="cap_search_v1",
        name="Web Search",
        version="1.0.0",
        provider="acme-corp",
        method="POST /search",
        description="Searches the web.",
        scopes=["search:read"],
        risk_class=RiskClass.LOW,
        domain_allowlist=["*.acme.com"],
        status=CapabilityStatus.PUBLISHED,
    )


@pytest.fixture()
def bundle(manifest: CapabilityManifest) -> PolicyBundle:
    return PolicyBundle(
        id="bundle_abc_search",
        tenant_id="tenant_abc",
        capability_id=manifest.id,
        allowed_scopes=["search:read", "search:write"],
        budget_daily=1_000,  # $10.00
        domain_allowlist=["*.acme.com", "*.example.com"],
    )


# ---------------------------------------------------------------------------
# Happy path: all checks pass
# ---------------------------------------------------------------------------


class TestAllowPath:
    def test_returns_policy_decision(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert isinstance(decision, PolicyDecision)

    def test_allowed_true_when_all_pass(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert decision.allowed is True

    def test_rule_hit_is_all_checks_passed(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert decision.rule_hit == "all_checks_passed"

    def test_decision_carries_correct_ids(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(
            bundle, manifest, "search:read", 0, request_id="req_99"
        )
        assert decision.policy_bundle_id == bundle.id
        assert decision.tenant_id == bundle.tenant_id
        assert decision.capability_id == manifest.id
        assert decision.request_id == "req_99"

    def test_evaluation_ms_is_positive(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert decision.evaluation_ms >= 0.0

    def test_auto_request_id_generated_when_not_supplied(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert len(decision.request_id) > 0

    def test_spend_below_budget_is_allowed(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "search:read", 999)
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Rule 1: scope_not_allowed
# ---------------------------------------------------------------------------


class TestScopeNotAllowed:
    def test_denied_when_scope_missing(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "admin:write", 0)
        assert decision.allowed is False

    def test_rule_hit_contains_scope(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "admin:write", 0)
        assert "scope_not_allowed" in decision.rule_hit
        assert "admin:write" in decision.rule_hit

    def test_empty_allowed_scopes_denies_everything(
        self, manifest: CapabilityManifest
    ) -> None:
        bundle = PolicyBundle(
            id="b",
            tenant_id="t",
            capability_id=manifest.id,
            allowed_scopes=[],
        )
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert decision.allowed is False
        assert "scope_not_allowed" in decision.rule_hit


# ---------------------------------------------------------------------------
# Rule 2: budget_daily_exceeded
# ---------------------------------------------------------------------------


class TestBudgetDailyExceeded:
    def test_denied_at_exact_budget(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "search:read", 1_000)
        assert decision.allowed is False
        assert "budget_daily_exceeded" in decision.rule_hit

    def test_denied_above_budget(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "search:read", 5_000)
        assert decision.allowed is False

    def test_rule_hit_includes_spend_and_limit(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "search:read", 1_500)
        assert "1500" in decision.rule_hit
        assert "1000" in decision.rule_hit

    def test_no_budget_set_means_unlimited(
        self, manifest: CapabilityManifest
    ) -> None:
        bundle = PolicyBundle(
            id="b",
            tenant_id="t",
            capability_id=manifest.id,
            allowed_scopes=["search:read"],
            budget_daily=None,
        )
        decision = evaluate_policy(bundle, manifest, "search:read", 999_999_999)
        assert decision.allowed is True

    def test_zero_budget_denies_any_spend(
        self, manifest: CapabilityManifest
    ) -> None:
        bundle = PolicyBundle(
            id="b",
            tenant_id="t",
            capability_id=manifest.id,
            allowed_scopes=["search:read"],
            budget_daily=0,
        )
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert decision.allowed is False
        assert "budget_daily_exceeded" in decision.rule_hit


# ---------------------------------------------------------------------------
# Rule 3: domain_allowlist_conflict
# ---------------------------------------------------------------------------


class TestDomainAllowlistConflict:
    def test_denied_when_capability_domain_not_in_bundle(
        self, manifest: CapabilityManifest
    ) -> None:
        # Bundle restricts to example.com; capability requires acme.com
        bundle = PolicyBundle(
            id="b",
            tenant_id="t",
            capability_id=manifest.id,
            allowed_scopes=["search:read"],
            budget_daily=1_000,
            domain_allowlist=["*.example.com"],  # missing *.acme.com
        )
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert decision.allowed is False
        assert "domain_allowlist_conflict" in decision.rule_hit

    def test_rule_hit_lists_disallowed_domains(
        self, manifest: CapabilityManifest
    ) -> None:
        bundle = PolicyBundle(
            id="b",
            tenant_id="t",
            capability_id=manifest.id,
            allowed_scopes=["search:read"],
            domain_allowlist=["*.other.com"],
        )
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert "*.acme.com" in decision.rule_hit

    def test_empty_bundle_allowlist_permits_all(
        self, manifest: CapabilityManifest
    ) -> None:
        bundle = PolicyBundle(
            id="b",
            tenant_id="t",
            capability_id=manifest.id,
            allowed_scopes=["search:read"],
            domain_allowlist=[],  # no restriction
        )
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert decision.allowed is True

    def test_capability_subset_of_bundle_is_allowed(
        self, manifest: CapabilityManifest
    ) -> None:
        # Capability restricts to *.acme.com; bundle allows *.acme.com + more
        bundle = PolicyBundle(
            id="b",
            tenant_id="t",
            capability_id=manifest.id,
            allowed_scopes=["search:read"],
            domain_allowlist=["*.acme.com", "*.example.com", "*.extra.io"],
        )
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert decision.allowed is True

    def test_capability_with_no_domains_always_passes_domain_check(
        self,
    ) -> None:
        cap = CapabilityManifest(
            id="cap_nodomain",
            name="No Domain",
            version="1.0.0",
            provider="p",
            method="GET /",
            description=".",
            risk_class=RiskClass.LOW,
            domain_allowlist=[],  # no domain restrictions
        )
        bundle = PolicyBundle(
            id="b",
            tenant_id="t",
            capability_id=cap.id,
            allowed_scopes=["search:read"],
            domain_allowlist=["*.example.com"],
        )
        decision = evaluate_policy(bundle, cap, "search:read", 0)
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Rule 4: require_approval
# ---------------------------------------------------------------------------


class TestRequireApproval:
    def test_denied_when_require_approval_true(
        self, manifest: CapabilityManifest
    ) -> None:
        bundle = PolicyBundle(
            id="b",
            tenant_id="t",
            capability_id=manifest.id,
            allowed_scopes=["search:read"],
            domain_allowlist=["*.acme.com"],
            require_approval=True,
        )
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert decision.allowed is False
        assert decision.rule_hit == "require_approval"

    def test_allowed_when_require_approval_false(
        self, bundle: PolicyBundle, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(bundle, manifest, "search:read", 0)
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Default-deny: no bundle
# ---------------------------------------------------------------------------


class TestDefaultDeny:
    def test_none_bundle_denies(self, manifest: CapabilityManifest) -> None:
        decision = evaluate_policy(None, manifest, "search:read", 0)
        assert decision.allowed is False

    def test_none_bundle_rule_hit(self, manifest: CapabilityManifest) -> None:
        decision = evaluate_policy(None, manifest, "search:read", 0)
        assert decision.rule_hit == "no_policy_bundle"

    def test_none_bundle_uses_no_policy_bundle_id(
        self, manifest: CapabilityManifest
    ) -> None:
        decision = evaluate_policy(None, manifest, "search:read", 0)
        assert decision.policy_bundle_id == "__none__"


# ---------------------------------------------------------------------------
# Rule priority: scope checked before budget
# ---------------------------------------------------------------------------


class TestRulePriority:
    def test_scope_checked_before_budget(
        self, manifest: CapabilityManifest
    ) -> None:
        """Scope denial takes precedence over budget denial."""
        bundle = PolicyBundle(
            id="b",
            tenant_id="t",
            capability_id=manifest.id,
            allowed_scopes=["search:read"],
            budget_daily=100,
        )
        # Both scope failure AND budget failure apply; scope wins
        decision = evaluate_policy(bundle, manifest, "wrong:scope", 999_999)
        assert "scope_not_allowed" in decision.rule_hit
