"""
Tests for moat_core.errors.

Covers: exception hierarchy, attribute presence, default values,
and isinstance checks.
"""

from __future__ import annotations

import pytest

from moat_core import (
    AdapterError,
    BudgetExceededError,
    CapabilityNotFoundError,
    IdempotencyConflictError,
    MoatError,
    PolicyDeniedError,
)


class TestMoatError:
    def test_is_base_exception(self) -> None:
        e = MoatError("base error")
        assert isinstance(e, Exception)

    def test_message_preserved(self) -> None:
        e = MoatError("something failed")
        assert str(e) == "something failed"

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(MoatError):
            raise MoatError("test")


class TestPolicyDeniedError:
    def test_is_moat_error(self) -> None:
        e = PolicyDeniedError("denied")
        assert isinstance(e, MoatError)

    def test_default_attributes(self) -> None:
        e = PolicyDeniedError("denied")
        assert e.rule_hit == "unknown"
        assert e.capability_id == ""
        assert e.tenant_id == ""

    def test_custom_attributes(self) -> None:
        e = PolicyDeniedError(
            "denied",
            rule_hit="scope_not_allowed",
            capability_id="cap_v1",
            tenant_id="tenant_abc",
        )
        assert e.rule_hit == "scope_not_allowed"
        assert e.capability_id == "cap_v1"
        assert e.tenant_id == "tenant_abc"

    def test_message_preserved(self) -> None:
        e = PolicyDeniedError("access denied by policy")
        assert str(e) == "access denied by policy"


class TestBudgetExceededError:
    def test_is_policy_denied_error(self) -> None:
        e = BudgetExceededError("budget exceeded")
        assert isinstance(e, PolicyDeniedError)
        assert isinstance(e, MoatError)

    def test_default_attributes(self) -> None:
        e = BudgetExceededError("over budget")
        assert e.rule_hit == "budget_exceeded"
        assert e.budget_cents == 0
        assert e.current_spend_cents == 0
        assert e.period == "daily"

    def test_custom_attributes(self) -> None:
        e = BudgetExceededError(
            "daily budget exceeded",
            capability_id="cap_v1",
            tenant_id="t1",
            budget_cents=500,
            current_spend_cents=600,
            period="daily",
        )
        assert e.budget_cents == 500
        assert e.current_spend_cents == 600
        assert e.period == "daily"
        assert e.capability_id == "cap_v1"

    def test_monthly_period(self) -> None:
        e = BudgetExceededError("monthly limit", period="monthly")
        assert e.period == "monthly"


class TestCapabilityNotFoundError:
    def test_is_moat_error(self) -> None:
        e = CapabilityNotFoundError("not found")
        assert isinstance(e, MoatError)

    def test_default_capability_id(self) -> None:
        e = CapabilityNotFoundError("not found")
        assert e.capability_id == ""

    def test_custom_capability_id(self) -> None:
        e = CapabilityNotFoundError("not found", capability_id="cap_xyz")
        assert e.capability_id == "cap_xyz"

    def test_message_preserved(self) -> None:
        e = CapabilityNotFoundError("capability cap_xyz not found")
        assert "cap_xyz" in str(e)


class TestAdapterError:
    def test_is_moat_error(self) -> None:
        e = AdapterError("upstream failed")
        assert isinstance(e, MoatError)

    def test_default_attributes(self) -> None:
        e = AdapterError("failed")
        assert e.provider == ""
        assert e.status_code is None
        assert e.provider_request_id is None

    def test_custom_attributes(self) -> None:
        e = AdapterError(
            "upstream error",
            provider="acme-api",
            status_code=503,
            provider_request_id="req_upstream_123",
        )
        assert e.provider == "acme-api"
        assert e.status_code == 503
        assert e.provider_request_id == "req_upstream_123"

    def test_http_500_scenario(self) -> None:
        e = AdapterError("provider 500", provider="search-api", status_code=500)
        assert e.status_code == 500


class TestIdempotencyConflictError:
    def test_is_moat_error(self) -> None:
        e = IdempotencyConflictError("conflict")
        assert isinstance(e, MoatError)

    def test_default_key(self) -> None:
        e = IdempotencyConflictError("conflict")
        assert e.key == ""

    def test_custom_key(self) -> None:
        e = IdempotencyConflictError("idempotency conflict", key="idem_abc123")
        assert e.key == "idem_abc123"


class TestExceptionHierarchy:
    def test_budget_exceeded_caught_by_policy_denied(self) -> None:
        with pytest.raises(PolicyDeniedError):
            raise BudgetExceededError("budget")

    def test_budget_exceeded_caught_by_moat_error(self) -> None:
        with pytest.raises(MoatError):
            raise BudgetExceededError("budget")

    def test_policy_denied_caught_by_moat_error(self) -> None:
        with pytest.raises(MoatError):
            raise PolicyDeniedError("denied")

    def test_capability_not_found_caught_by_moat_error(self) -> None:
        with pytest.raises(MoatError):
            raise CapabilityNotFoundError("not found")

    def test_adapter_error_caught_by_moat_error(self) -> None:
        with pytest.raises(MoatError):
            raise AdapterError("failed")

    def test_idempotency_conflict_caught_by_moat_error(self) -> None:
        with pytest.raises(MoatError):
            raise IdempotencyConflictError("conflict")

    def test_all_errors_not_caught_by_value_error(self) -> None:
        """MoatError does NOT extend ValueError - verify isolation."""
        for exc_cls in (
            MoatError,
            PolicyDeniedError,
            BudgetExceededError,
            CapabilityNotFoundError,
            AdapterError,
            IdempotencyConflictError,
        ):
            assert not issubclass(exc_cls, ValueError)
