"""
moat_core.errors
~~~~~~~~~~~~~~~~
Custom exception hierarchy for Moat.

All Moat exceptions inherit from MoatError so callers can catch the
full family with a single ``except MoatError`` clause while still
being able to discriminate at finer granularity.
"""

from __future__ import annotations


class MoatError(Exception):
    """Base class for all Moat exceptions."""


class PolicyDeniedError(MoatError):
    """Raised when a policy evaluation denies the requested operation.

    Attributes:
        rule_hit: Human-readable description of the rule that triggered denial.
        capability_id: Capability that was denied.
        tenant_id: Tenant whose request was denied.
    """

    def __init__(
        self,
        message: str,
        *,
        rule_hit: str = "unknown",
        capability_id: str = "",
        tenant_id: str = "",
    ) -> None:
        super().__init__(message)
        self.rule_hit = rule_hit
        self.capability_id = capability_id
        self.tenant_id = tenant_id


class BudgetExceededError(PolicyDeniedError):
    """Raised when a spend budget (daily or monthly) would be exceeded.

    Attributes:
        budget_cents: The configured budget limit in cents.
        current_spend_cents: Current accumulated spend in cents.
        period: 'daily' or 'monthly'.
    """

    def __init__(
        self,
        message: str,
        *,
        rule_hit: str = "budget_exceeded",
        capability_id: str = "",
        tenant_id: str = "",
        budget_cents: int = 0,
        current_spend_cents: int = 0,
        period: str = "daily",
    ) -> None:
        super().__init__(
            message,
            rule_hit=rule_hit,
            capability_id=capability_id,
            tenant_id=tenant_id,
        )
        self.budget_cents = budget_cents
        self.current_spend_cents = current_spend_cents
        self.period = period


class CapabilityNotFoundError(MoatError):
    """Raised when a referenced capability does not exist in the registry.

    Attributes:
        capability_id: The requested capability ID.
    """

    def __init__(self, message: str, *, capability_id: str = "") -> None:
        super().__init__(message)
        self.capability_id = capability_id


class AdapterError(MoatError):
    """Raised when an adapter (upstream provider call) fails.

    Attributes:
        provider: Name of the upstream provider.
        status_code: HTTP status code, if applicable.
        provider_request_id: Provider-side request ID for correlation.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status_code: int | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.provider_request_id = provider_request_id


class IdempotencyConflictError(MoatError):
    """Raised when an idempotency key collision is detected with a
    different payload, indicating a client programming error.

    Attributes:
        key: The conflicting idempotency key.
    """

    def __init__(self, message: str, *, key: str = "") -> None:
        super().__init__(message)
        self.key = key
