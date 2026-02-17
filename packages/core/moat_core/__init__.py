"""
moat_core
~~~~~~~~~
Shared types, schemas, policy engine, and receipts for the Moat
Verified Agent Capabilities Marketplace.

Public surface
--------------
This package exposes **all** public symbols through its top-level
namespace so consumers never need to import from internal sub-modules
directly::

    # Preferred
    from moat_core import CapabilityManifest, evaluate_policy

    # Also valid but discouraged
    from moat_core.models import CapabilityManifest
    from moat_core.policy import evaluate_policy

Sub-module summary
------------------
:mod:`moat_core.models`
    Pydantic v2 domain models (CapabilityManifest, Receipt, etc.) and
    all enumerations (RiskClass, ExecutionStatus, …).

:mod:`moat_core.errors`
    Exception hierarchy rooted at :exc:`MoatError`.

:mod:`moat_core.redaction`
    Secret-scrubbing helpers and deterministic hashing.

:mod:`moat_core.idempotency`
    Key generation, the :class:`IdempotencyStore` Protocol, and the
    built-in :class:`InMemoryIdempotencyStore`.

:mod:`moat_core.policy`
    :func:`evaluate_policy` – the default-deny policy evaluation engine.
"""

from __future__ import annotations

# --- Models & enumerations --------------------------------------------------
from moat_core.models import (
    CapabilityManifest,
    CapabilityStatus,
    ErrorTaxonomy,
    ExecutionStatus,
    OutcomeEvent,
    PolicyBundle,
    PolicyDecision,
    Receipt,
    RiskClass,
)

# --- Exceptions -------------------------------------------------------------
from moat_core.errors import (
    AdapterError,
    BudgetExceededError,
    CapabilityNotFoundError,
    IdempotencyConflictError,
    MoatError,
    PolicyDeniedError,
)

# --- Redaction & hashing ----------------------------------------------------
from moat_core.redaction import (
    REDACT_KEYS,
    hash_redacted,
    redact_body,
    redact_headers,
)

# --- Idempotency ------------------------------------------------------------
from moat_core.idempotency import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    generate_idempotency_key,
)

# --- Policy engine ----------------------------------------------------------
from moat_core.policy import evaluate_policy

__all__: list[str] = [
    # Models
    "CapabilityManifest",
    "CapabilityStatus",
    "ErrorTaxonomy",
    "ExecutionStatus",
    "OutcomeEvent",
    "PolicyBundle",
    "PolicyDecision",
    "Receipt",
    "RiskClass",
    # Errors
    "AdapterError",
    "BudgetExceededError",
    "CapabilityNotFoundError",
    "IdempotencyConflictError",
    "MoatError",
    "PolicyDeniedError",
    # Redaction
    "REDACT_KEYS",
    "hash_redacted",
    "redact_body",
    "redact_headers",
    # Idempotency
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "generate_idempotency_key",
    # Policy
    "evaluate_policy",
]

__version__: str = "0.1.0"
