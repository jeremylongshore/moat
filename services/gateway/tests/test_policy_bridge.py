"""
Tests for the policy bridge — default-deny enforcement, budget tracking,
and bundle management.

The policy bridge is the gateway's integration layer between the HTTP
execution pipeline and moat_core's policy engine. These tests validate:

  - PolicyBundle registration and retrieval from the in-memory registry
  - Per-tenant daily spend accumulation and isolation
  - Capability dict → CapabilityManifest conversion (all status/risk variants)
  - evaluate_policy default-deny contract: no bundle → denied
  - evaluate_policy allow path: matching scope + budget headroom → allowed
  - Budget enforcement: spend at/above ceiling → denied
  - Scope enforcement: wrong scope → denied
  - Capability name fallback lookup (UUID miss → name hit)
  - Minimal manifest path when capability_dict is omitted
"""

from __future__ import annotations

import os

# Must set env vars before any app import to satisfy pydantic-settings.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("MOAT_AUTH_DISABLED", "true")

import pytest
from moat_core.models import (
    CapabilityStatus,
    PolicyBundle,
    RiskClass,
)

from app.policy_bridge import (
    PolicyResult,
    _bundles,
    _daily_spend,
    _dict_to_manifest,
    _get_bundle,
    _get_current_spend,
    evaluate_policy,
    record_spend,
    register_policy_bundle,
)

# ---------------------------------------------------------------------------
# Shared helpers / factory functions
# ---------------------------------------------------------------------------


def _make_bundle(
    tenant_id: str = "tenant-alpha",
    capability_id: str = "cap-001",
    allowed_scopes: list[str] | None = None,
    budget_daily: int | None = 10_000,
    require_approval: bool = False,
    domain_allowlist: list[str] | None = None,
) -> PolicyBundle:
    """Create a minimal PolicyBundle for test use."""
    return PolicyBundle(
        id=f"bundle-{tenant_id}-{capability_id}",
        tenant_id=tenant_id,
        capability_id=capability_id,
        allowed_scopes=allowed_scopes if allowed_scopes is not None else ["execute"],
        budget_daily=budget_daily,
        require_approval=require_approval,
        domain_allowlist=domain_allowlist if domain_allowlist is not None else [],
    )


def _make_capability_dict(
    capability_id: str = "cap-001",
    name: str = "Test Capability",
    status: str = "active",
    risk_class: str = "low",
    scopes: list[str] | None = None,
    domain_allowlist: list[str] | None = None,
) -> dict:
    """Return a capability dict as produced by the control-plane cache."""
    return {
        "capability_id": capability_id,
        "name": name,
        "version": "1.0.0",
        "provider": "acme",
        "method": "POST /execute",
        "description": "A test capability",
        "status": status,
        "risk_class": risk_class,
        "scopes": scopes if scopes is not None else ["execute"],
        "domain_allowlist": domain_allowlist if domain_allowlist is not None else [],
    }


# ---------------------------------------------------------------------------
# Class 1: PolicyBundle registry
# ---------------------------------------------------------------------------


class TestPolicyBundleRegistry:
    """Tests for register_policy_bundle / _get_bundle.

    The registry is an in-memory dict keyed by "{tenant_id}:{capability_id}".
    Each test gets a clean slate via the autouse fixture.
    """

    @pytest.fixture(autouse=True)
    def clear_bundles(self):
        """Clear the module-level _bundles dict before and after each test."""
        _bundles.clear()
        yield
        _bundles.clear()

    def test_register_stores_bundle_under_composite_key(self):
        """register_policy_bundle places the bundle at tenant:capability key."""
        bundle = _make_bundle(tenant_id="t1", capability_id="cap-x")
        register_policy_bundle(bundle)
        assert _bundles.get("t1:cap-x") is bundle

    def test_get_bundle_retrieves_registered_bundle(self):
        """_get_bundle returns the exact bundle registered for (tenant, cap)."""
        bundle = _make_bundle(tenant_id="t2", capability_id="cap-y")
        register_policy_bundle(bundle)
        result = _get_bundle("t2", "cap-y")
        assert result is bundle

    def test_get_bundle_returns_none_for_missing_key(self):
        """_get_bundle returns None when no bundle has been registered."""
        result = _get_bundle("ghost-tenant", "nonexistent-cap")
        assert result is None

    def test_get_bundle_isolates_by_tenant(self):
        """Bundles for different tenants on the same capability don't collide."""
        bundle_a = _make_bundle(tenant_id="tenant-a", capability_id="shared-cap")
        bundle_b = _make_bundle(tenant_id="tenant-b", capability_id="shared-cap")
        register_policy_bundle(bundle_a)
        register_policy_bundle(bundle_b)

        assert _get_bundle("tenant-a", "shared-cap") is bundle_a
        assert _get_bundle("tenant-b", "shared-cap") is bundle_b

    def test_get_bundle_isolates_by_capability(self):
        """Bundles for the same tenant on different capabilities don't collide."""
        bundle_1 = _make_bundle(tenant_id="shared-tenant", capability_id="cap-1")
        bundle_2 = _make_bundle(tenant_id="shared-tenant", capability_id="cap-2")
        register_policy_bundle(bundle_1)
        register_policy_bundle(bundle_2)

        assert _get_bundle("shared-tenant", "cap-1") is bundle_1
        assert _get_bundle("shared-tenant", "cap-2") is bundle_2

    def test_re_registering_overwrites_previous_bundle(self):
        """Registering a new bundle for the same key replaces the old one."""
        old_bundle = _make_bundle(
            tenant_id="t1", capability_id="cap-x", budget_daily=100
        )
        new_bundle = _make_bundle(
            tenant_id="t1", capability_id="cap-x", budget_daily=999
        )
        register_policy_bundle(old_bundle)
        register_policy_bundle(new_bundle)

        retrieved = _get_bundle("t1", "cap-x")
        assert retrieved is new_bundle
        assert retrieved.budget_daily == 999

    def test_registry_starts_empty_after_fixture_clear(self):
        """After the autouse clear, the registry contains no bundles."""
        assert len(_bundles) == 0

    def test_multiple_bundles_coexist(self):
        """Registering several distinct bundles all persist simultaneously."""
        pairs = [("t1", "c1"), ("t1", "c2"), ("t2", "c1"), ("t2", "c2")]
        bundles = {}
        for tenant, cap in pairs:
            b = _make_bundle(tenant_id=tenant, capability_id=cap)
            register_policy_bundle(b)
            bundles[(tenant, cap)] = b

        for (tenant, cap), expected in bundles.items():
            assert _get_bundle(tenant, cap) is expected


# ---------------------------------------------------------------------------
# Class 2: Spend tracking
# ---------------------------------------------------------------------------


class TestSpendTracking:
    """Tests for record_spend / _get_current_spend.

    Spend is stored as "{tenant_id}:{YYYY-MM-DD}" → int (cents).
    Per-tenant isolation is critical for multi-tenant budget enforcement.
    """

    @pytest.fixture(autouse=True)
    def clear_spend(self):
        """Clear the module-level _daily_spend dict before and after each test."""
        _daily_spend.clear()
        yield
        _daily_spend.clear()

    def test_initial_spend_is_zero(self):
        """A tenant with no recorded spend returns 0."""
        assert _get_current_spend("fresh-tenant") == 0

    def test_record_spend_increments_total(self):
        """record_spend adds to the running total for the tenant."""
        record_spend("tenant-x", 500)
        assert _get_current_spend("tenant-x") == 500

    def test_multiple_record_spend_calls_accumulate(self):
        """Successive record_spend calls sum together for the same tenant."""
        record_spend("tenant-x", 100)
        record_spend("tenant-x", 250)
        record_spend("tenant-x", 50)
        assert _get_current_spend("tenant-x") == 400

    def test_spend_is_isolated_between_tenants(self):
        """Spend recorded for tenant A does not affect tenant B."""
        record_spend("tenant-a", 1_000)
        record_spend("tenant-b", 2_000)

        assert _get_current_spend("tenant-a") == 1_000
        assert _get_current_spend("tenant-b") == 2_000

    def test_spend_starts_fresh_after_fixture_clear(self):
        """After the autouse clear, all spend balances are zero."""
        assert len(_daily_spend) == 0

    def test_record_spend_zero_amount(self):
        """Recording zero spend is a no-op but does not raise."""
        record_spend("tenant-x", 0)
        assert _get_current_spend("tenant-x") == 0

    def test_record_spend_large_amount(self):
        """Large spend values (e.g. $10,000/day) accumulate correctly."""
        record_spend("big-spender", 1_000_000)  # $10,000 in cents
        assert _get_current_spend("big-spender") == 1_000_000

    def test_unknown_tenant_returns_zero_without_error(self):
        """Querying a tenant that has never spent returns 0, never raises."""
        result = _get_current_spend("i-do-not-exist")
        assert result == 0


# ---------------------------------------------------------------------------
# Class 3: Dict → CapabilityManifest conversion
# ---------------------------------------------------------------------------


class TestDictToManifest:
    """Tests for _dict_to_manifest.

    The bridge converts capability dicts (from the control-plane cache) into
    CapabilityManifest Pydantic models. Status and risk_class strings are
    mapped to their enum equivalents. Missing fields fall back to safe defaults.
    """

    # --- Status mapping ---

    def test_active_status_maps_to_published(self):
        """'active' (cache convention) maps to CapabilityStatus.PUBLISHED."""
        cap = _make_capability_dict(status="active")
        manifest = _dict_to_manifest(cap)
        assert manifest.status == CapabilityStatus.PUBLISHED

    def test_published_status_maps_to_published(self):
        """'published' (canonical) maps to CapabilityStatus.PUBLISHED."""
        cap = _make_capability_dict(status="published")
        manifest = _dict_to_manifest(cap)
        assert manifest.status == CapabilityStatus.PUBLISHED

    def test_draft_status_maps_to_draft(self):
        """'draft' maps to CapabilityStatus.DRAFT."""
        cap = _make_capability_dict(status="draft")
        manifest = _dict_to_manifest(cap)
        assert manifest.status == CapabilityStatus.DRAFT

    def test_deprecated_status_maps_to_deprecated(self):
        """'deprecated' maps to CapabilityStatus.DEPRECATED."""
        cap = _make_capability_dict(status="deprecated")
        manifest = _dict_to_manifest(cap)
        assert manifest.status == CapabilityStatus.DEPRECATED

    def test_archived_status_maps_to_archived(self):
        """'archived' maps to CapabilityStatus.ARCHIVED."""
        cap = _make_capability_dict(status="archived")
        manifest = _dict_to_manifest(cap)
        assert manifest.status == CapabilityStatus.ARCHIVED

    def test_unknown_status_defaults_to_published(self):
        """Unrecognised status strings fall back to CapabilityStatus.PUBLISHED."""
        cap = _make_capability_dict(status="unknown_status")
        manifest = _dict_to_manifest(cap)
        assert manifest.status == CapabilityStatus.PUBLISHED

    def test_missing_status_defaults_to_published(self):
        """Absent status key falls back to CapabilityStatus.PUBLISHED."""
        cap = _make_capability_dict()
        cap.pop("status")
        manifest = _dict_to_manifest(cap)
        assert manifest.status == CapabilityStatus.PUBLISHED

    # --- Risk class mapping ---

    def test_low_risk_maps_to_low(self):
        """'low' maps to RiskClass.LOW."""
        cap = _make_capability_dict(risk_class="low")
        manifest = _dict_to_manifest(cap)
        assert manifest.risk_class == RiskClass.LOW

    def test_medium_risk_maps_to_medium(self):
        """'medium' maps to RiskClass.MEDIUM."""
        cap = _make_capability_dict(risk_class="medium")
        manifest = _dict_to_manifest(cap)
        assert manifest.risk_class == RiskClass.MEDIUM

    def test_high_risk_maps_to_high(self):
        """'high' maps to RiskClass.HIGH."""
        cap = _make_capability_dict(risk_class="high")
        manifest = _dict_to_manifest(cap)
        assert manifest.risk_class == RiskClass.HIGH

    def test_critical_risk_maps_to_critical(self):
        """'critical' maps to RiskClass.CRITICAL."""
        cap = _make_capability_dict(risk_class="critical")
        manifest = _dict_to_manifest(cap)
        assert manifest.risk_class == RiskClass.CRITICAL

    def test_uppercase_risk_class_is_case_insensitive(self):
        """Risk class mapping normalises to lowercase before lookup."""
        cap = _make_capability_dict(risk_class="HIGH")
        manifest = _dict_to_manifest(cap)
        assert manifest.risk_class == RiskClass.HIGH

    def test_unknown_risk_class_defaults_to_low(self):
        """Unrecognised risk_class strings fall back to RiskClass.LOW."""
        cap = _make_capability_dict(risk_class="galactic")
        manifest = _dict_to_manifest(cap)
        assert manifest.risk_class == RiskClass.LOW

    def test_missing_risk_class_defaults_to_low(self):
        """Absent risk_class key falls back to RiskClass.LOW."""
        cap = _make_capability_dict()
        cap.pop("risk_class")
        manifest = _dict_to_manifest(cap)
        assert manifest.risk_class == RiskClass.LOW

    # --- Field extraction ---

    def test_capability_id_field_used_for_manifest_id(self):
        """capability_id key is used as the manifest's id field."""
        cap = _make_capability_dict(capability_id="uuid-cap-999")
        manifest = _dict_to_manifest(cap)
        assert manifest.id == "uuid-cap-999"

    def test_id_field_used_when_capability_id_absent(self):
        """Falls back to 'id' key when 'capability_id' is absent."""
        cap = _make_capability_dict()
        cap.pop("capability_id")
        cap["id"] = "alt-id-888"
        manifest = _dict_to_manifest(cap)
        assert manifest.id == "alt-id-888"

    def test_defaults_when_all_optional_fields_absent(self):
        """A minimal dict with only required fields produces a valid manifest."""
        cap = {
            "capability_id": "min-cap",
            "name": "Minimal",
            "description": "Minimal capability for testing",
        }
        manifest = _dict_to_manifest(cap)
        assert manifest.id == "min-cap"
        assert manifest.version == "0.0.1"
        assert manifest.provider == "stub"
        assert manifest.method == "POST /execute"
        assert manifest.scopes == []
        assert manifest.domain_allowlist == []

    def test_scopes_are_propagated(self):
        """Scopes list from the dict is preserved on the manifest."""
        cap = _make_capability_dict(scopes=["read:data", "write:data"])
        manifest = _dict_to_manifest(cap)
        assert manifest.scopes == ["read:data", "write:data"]

    def test_domain_allowlist_is_propagated(self):
        """domain_allowlist from the dict is preserved on the manifest."""
        cap = _make_capability_dict(domain_allowlist=["*.example.com"])
        manifest = _dict_to_manifest(cap)
        assert manifest.domain_allowlist == ["*.example.com"]

    def test_returns_capability_manifest_instance(self):
        """_dict_to_manifest always returns a CapabilityManifest."""
        from moat_core.models import CapabilityManifest

        cap = _make_capability_dict()
        manifest = _dict_to_manifest(cap)
        assert isinstance(manifest, CapabilityManifest)


# ---------------------------------------------------------------------------
# Class 4: evaluate_policy (public API)
# ---------------------------------------------------------------------------


class TestEvaluatePolicy:
    """Tests for the evaluate_policy bridge function.

    This covers the default-deny contract, the allow path, budget enforcement,
    scope enforcement, name-based fallback lookup, and the minimal-manifest
    code path when capability_dict is omitted.
    """

    @pytest.fixture(autouse=True)
    def clean_state(self):
        """Reset both module-level dicts before and after every test."""
        _bundles.clear()
        _daily_spend.clear()
        yield
        _bundles.clear()
        _daily_spend.clear()

    # --- Default-deny: no bundle ---

    def test_no_bundle_is_denied(self):
        """Default-deny: absent bundle means the request is always denied."""
        result = evaluate_policy(
            capability_id="unknown-cap",
            tenant_id="any-tenant",
            scope="execute",
            params={},
        )
        assert result.allowed is False

    def test_no_bundle_rule_hit_indicates_no_policy(self):
        """Default-deny rule_hit surfaces 'no_policy_bundle'."""
        result = evaluate_policy(
            capability_id="unknown-cap",
            tenant_id="any-tenant",
            scope="execute",
            params={},
        )
        assert "no_policy_bundle" in result.rule_hit

    def test_no_bundle_returns_policy_result_type(self):
        """evaluate_policy always returns a PolicyResult regardless of outcome."""
        result = evaluate_policy(
            capability_id="cap-x",
            tenant_id="t1",
            scope="execute",
            params={},
        )
        assert isinstance(result, PolicyResult)

    # --- Allow path ---

    def test_matching_scope_and_budget_headroom_is_allowed(self):
        """A valid bundle with matching scope and budget headroom allows the request."""
        bundle = _make_bundle(
            tenant_id="t1",
            capability_id="cap-001",
            allowed_scopes=["execute"],
            budget_daily=10_000,
        )
        register_policy_bundle(bundle)
        cap_dict = _make_capability_dict(capability_id="cap-001")
        result = evaluate_policy(
            capability_id="cap-001",
            tenant_id="t1",
            scope="execute",
            params={},
            capability_dict=cap_dict,
        )
        assert result.allowed is True

    def test_allowed_result_has_expected_rule_hit(self):
        """An allowed evaluation records 'all_checks_passed'."""
        bundle = _make_bundle(tenant_id="t1", capability_id="cap-001")
        register_policy_bundle(bundle)
        cap_dict = _make_capability_dict(capability_id="cap-001")
        result = evaluate_policy(
            capability_id="cap-001",
            tenant_id="t1",
            scope="execute",
            params={},
            capability_dict=cap_dict,
        )
        assert result.rule_hit == "all_checks_passed"

    # --- Budget enforcement ---

    def test_budget_exceeded_is_denied(self):
        """Request is denied when today's spend meets the daily ceiling."""
        bundle = _make_bundle(
            tenant_id="t1",
            capability_id="cap-001",
            allowed_scopes=["execute"],
            budget_daily=500,
        )
        register_policy_bundle(bundle)
        # Simulate recorded spend exactly at the ceiling.
        record_spend("t1", 500)

        cap_dict = _make_capability_dict(capability_id="cap-001")
        result = evaluate_policy(
            capability_id="cap-001",
            tenant_id="t1",
            scope="execute",
            params={},
            capability_dict=cap_dict,
        )
        assert result.allowed is False
        assert "budget_daily_exceeded" in result.rule_hit

    def test_spend_above_budget_is_denied(self):
        """Request is denied when spend exceeds the daily ceiling."""
        bundle = _make_bundle(
            tenant_id="t1",
            capability_id="cap-001",
            budget_daily=100,
        )
        register_policy_bundle(bundle)
        record_spend("t1", 999)

        cap_dict = _make_capability_dict(capability_id="cap-001")
        result = evaluate_policy(
            capability_id="cap-001",
            tenant_id="t1",
            scope="execute",
            params={},
            capability_dict=cap_dict,
        )
        assert result.allowed is False

    def test_spend_below_budget_is_allowed(self):
        """Request is allowed when spend is one cent below the daily ceiling."""
        bundle = _make_bundle(
            tenant_id="t1",
            capability_id="cap-001",
            budget_daily=1_000,
        )
        register_policy_bundle(bundle)
        record_spend("t1", 999)  # One cent under the limit.

        cap_dict = _make_capability_dict(capability_id="cap-001")
        result = evaluate_policy(
            capability_id="cap-001",
            tenant_id="t1",
            scope="execute",
            params={},
            capability_dict=cap_dict,
        )
        assert result.allowed is True

    def test_unlimited_budget_never_triggers_budget_denial(self):
        """A bundle with budget_daily=None imposes no spend ceiling."""
        bundle = _make_bundle(
            tenant_id="t1",
            capability_id="cap-001",
            budget_daily=None,
        )
        register_policy_bundle(bundle)
        record_spend("t1", 99_999_999)  # Astronomically high spend.

        cap_dict = _make_capability_dict(capability_id="cap-001")
        result = evaluate_policy(
            capability_id="cap-001",
            tenant_id="t1",
            scope="execute",
            params={},
            capability_dict=cap_dict,
        )
        assert result.allowed is True

    # --- Scope enforcement ---

    def test_wrong_scope_is_denied(self):
        """A request with a scope not in allowed_scopes is denied."""
        bundle = _make_bundle(
            tenant_id="t1",
            capability_id="cap-001",
            allowed_scopes=["execute"],
        )
        register_policy_bundle(bundle)
        cap_dict = _make_capability_dict(capability_id="cap-001")
        result = evaluate_policy(
            capability_id="cap-001",
            tenant_id="t1",
            scope="admin:delete",  # Not in allowed_scopes.
            params={},
            capability_dict=cap_dict,
        )
        assert result.allowed is False
        assert "scope_not_allowed" in result.rule_hit

    def test_scope_denial_takes_priority_over_budget_denial(self):
        """Scope check fires before budget check (rule priority order)."""
        bundle = _make_bundle(
            tenant_id="t1",
            capability_id="cap-001",
            allowed_scopes=["execute"],
            budget_daily=10,
        )
        register_policy_bundle(bundle)
        record_spend("t1", 999_999)  # Would also fail on budget.

        cap_dict = _make_capability_dict(capability_id="cap-001")
        result = evaluate_policy(
            capability_id="cap-001",
            tenant_id="t1",
            scope="wrong_scope",
            params={},
            capability_dict=cap_dict,
        )
        assert "scope_not_allowed" in result.rule_hit

    # --- Name fallback lookup ---

    def test_capability_name_fallback_when_uuid_miss(self):
        """When capability_id lookup misses, the bridge retries using the name field."""
        # Register bundle under the human-readable name, not the UUID.
        bundle = _make_bundle(
            tenant_id="t1",
            capability_id="My Capability",  # Registered by name.
        )
        register_policy_bundle(bundle)

        cap_dict = _make_capability_dict(
            capability_id="uuid-that-misses",
            name="My Capability",  # Name matches the registered bundle.
        )
        result = evaluate_policy(
            capability_id="uuid-that-misses",
            tenant_id="t1",
            scope="execute",
            params={},
            capability_dict=cap_dict,
        )
        # The fallback lookup should find the bundle and allow the request.
        assert result.allowed is True

    def test_name_fallback_not_used_when_capability_dict_absent(self):
        """Name fallback only runs when capability_dict is provided."""
        # Register a bundle under a name.
        bundle = _make_bundle(tenant_id="t1", capability_id="SomeName")
        register_policy_bundle(bundle)

        # No capability_dict → no name to fall back on → default-deny.
        result = evaluate_policy(
            capability_id="uuid-not-registered",
            tenant_id="t1",
            scope="execute",
            params={},
            capability_dict=None,
        )
        assert result.allowed is False

    # --- Minimal manifest path ---

    def test_minimal_manifest_built_when_no_capability_dict(self):
        """Without a capability_dict, evaluate_policy constructs a minimal manifest."""
        bundle = _make_bundle(
            tenant_id="t1",
            capability_id="direct-cap-id",
            allowed_scopes=["execute"],
        )
        register_policy_bundle(bundle)

        result = evaluate_policy(
            capability_id="direct-cap-id",
            tenant_id="t1",
            scope="execute",
            params={},
            capability_dict=None,  # Explicit omission.
        )
        # With a valid bundle and matching scope, this should be allowed even
        # without a capability_dict.
        assert result.allowed is True

    # --- Spend isolation between tenants ---

    def test_budget_check_uses_correct_tenant_spend(self):
        """Budget enforcement is scoped to the requesting tenant, not others."""
        bundle_a = _make_bundle(
            tenant_id="tenant-a", capability_id="cap-shared", budget_daily=100
        )
        bundle_b = _make_bundle(
            tenant_id="tenant-b", capability_id="cap-shared", budget_daily=100
        )
        register_policy_bundle(bundle_a)
        register_policy_bundle(bundle_b)

        # Only tenant-a has exceeded their budget.
        record_spend("tenant-a", 500)

        cap_dict = _make_capability_dict(capability_id="cap-shared")

        result_a = evaluate_policy(
            capability_id="cap-shared",
            tenant_id="tenant-a",
            scope="execute",
            params={},
            capability_dict=cap_dict,
        )
        result_b = evaluate_policy(
            capability_id="cap-shared",
            tenant_id="tenant-b",
            scope="execute",
            params={},
            capability_dict=cap_dict,
        )

        assert result_a.allowed is False  # Budget exceeded.
        assert result_b.allowed is True  # Budget not touched.

    # --- PolicyResult field contract ---

    def test_policy_result_has_allowed_bool(self):
        """PolicyResult.allowed is always a bool."""
        result = evaluate_policy(
            capability_id="any-cap",
            tenant_id="t1",
            scope="execute",
            params={},
        )
        assert isinstance(result.allowed, bool)

    def test_policy_result_has_rule_hit_string(self):
        """PolicyResult.rule_hit is always a non-empty string."""
        result = evaluate_policy(
            capability_id="any-cap",
            tenant_id="t1",
            scope="execute",
            params={},
        )
        assert isinstance(result.rule_hit, str)
        assert len(result.rule_hit) > 0

    def test_policy_result_has_risk_class_string(self):
        """PolicyResult.risk_class is always a non-empty string."""
        bundle = _make_bundle(tenant_id="t1", capability_id="cap-001")
        register_policy_bundle(bundle)
        cap_dict = _make_capability_dict(capability_id="cap-001", risk_class="high")
        result = evaluate_policy(
            capability_id="cap-001",
            tenant_id="t1",
            scope="execute",
            params={},
            capability_dict=cap_dict,
        )
        assert isinstance(result.risk_class, str)
        assert result.risk_class.lower() == "high"

    def test_request_id_forwarded_to_core_engine(self):
        """request_id is accepted without error (trace ID propagation)."""
        result = evaluate_policy(
            capability_id="cap-x",
            tenant_id="t1",
            scope="execute",
            params={},
            request_id="trace-abc-123",
        )
        assert isinstance(result, PolicyResult)
