"""
Tests for moat_core.models.

Covers: field validation, enum values, cross-field validators, and
serialisation round-trips.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from moat_core import (
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manifest_kwargs() -> dict:
    return {
        "id": "cap_search_v1",
        "name": "Web Search",
        "version": "1.0.0",
        "provider": "acme-corp",
        "method": "POST /search",
        "description": "Searches the web.",
        "scopes": ["search:read"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "risk_class": RiskClass.LOW,
        "domain_allowlist": ["*.acme.com"],
        "status": CapabilityStatus.PUBLISHED,
    }


@pytest.fixture()
def receipt_kwargs() -> dict:
    return {
        "capability_id": "cap_search_v1",
        "capability_version": "1.0.0",
        "tenant_id": "tenant_abc",
        "idempotency_key": "idem_xyz",
        "input_hash": "a" * 64,
        "output_hash": "b" * 64,
        "latency_ms": 142.5,
        "status": ExecutionStatus.SUCCESS,
    }


# ---------------------------------------------------------------------------
# CapabilityManifest
# ---------------------------------------------------------------------------


class TestCapabilityManifest:
    def test_valid_manifest(self, manifest_kwargs: dict) -> None:
        m = CapabilityManifest(**manifest_kwargs)
        assert m.id == "cap_search_v1"
        assert m.risk_class == RiskClass.LOW
        assert m.status == CapabilityStatus.PUBLISHED

    def test_default_status_is_draft(self, manifest_kwargs: dict) -> None:
        manifest_kwargs.pop("status")
        m = CapabilityManifest(**manifest_kwargs)
        assert m.status == CapabilityStatus.DRAFT

    def test_timestamps_default_to_utc_now(self, manifest_kwargs: dict) -> None:
        before = datetime.now(tz=timezone.utc)
        m = CapabilityManifest(**manifest_kwargs)
        after = datetime.now(tz=timezone.utc)
        assert before <= m.created_at <= after
        assert before <= m.updated_at <= after

    @pytest.mark.parametrize(
        "version",
        ["1.0.0", "0.0.1", "2.11.3", "1.0.0-beta.1", "3.0.0-rc.2"],
    )
    def test_valid_semver(self, manifest_kwargs: dict, version: str) -> None:
        kwargs = {**manifest_kwargs, "version": version}
        m = CapabilityManifest(**kwargs)
        assert m.version == version

    @pytest.mark.parametrize(
        "bad_version",
        ["1.0", "v1.0.0", "1.0.0.0", "latest", "", "1.0.0-"],
    )
    def test_invalid_semver_raises(self, manifest_kwargs: dict, bad_version: str) -> None:
        kwargs = {**manifest_kwargs, "version": bad_version}
        with pytest.raises(ValidationError, match="semver"):
            CapabilityManifest(**kwargs)

    def test_updated_before_created_raises(self, manifest_kwargs: dict) -> None:
        now = datetime.now(tz=timezone.utc)
        manifest_kwargs["created_at"] = now
        manifest_kwargs["updated_at"] = now - timedelta(hours=1)
        with pytest.raises(ValidationError, match="updated_at"):
            CapabilityManifest(**manifest_kwargs)

    def test_empty_id_raises(self, manifest_kwargs: dict) -> None:
        manifest_kwargs["id"] = ""
        with pytest.raises(ValidationError):
            CapabilityManifest(**manifest_kwargs)

    def test_model_is_frozen(self, manifest_kwargs: dict) -> None:
        m = CapabilityManifest(**manifest_kwargs)
        with pytest.raises(ValidationError):
            m.name = "Modified"  # type: ignore[misc]

    def test_json_round_trip(self, manifest_kwargs: dict) -> None:
        m = CapabilityManifest(**manifest_kwargs)
        restored = CapabilityManifest.model_validate_json(m.model_dump_json())
        assert restored == m

    @pytest.mark.parametrize(
        "risk_class",
        [RiskClass.LOW, RiskClass.MEDIUM, RiskClass.HIGH, RiskClass.CRITICAL],
    )
    def test_all_risk_classes_accepted(
        self, manifest_kwargs: dict, risk_class: RiskClass
    ) -> None:
        manifest_kwargs["risk_class"] = risk_class
        m = CapabilityManifest(**manifest_kwargs)
        assert m.risk_class == risk_class


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


class TestReceipt:
    def test_valid_receipt(self, receipt_kwargs: dict) -> None:
        r = Receipt(**receipt_kwargs)
        assert r.status == ExecutionStatus.SUCCESS
        assert len(r.id) == 36  # UUID4

    def test_auto_uuid_id(self, receipt_kwargs: dict) -> None:
        r1 = Receipt(**receipt_kwargs)
        r2 = Receipt(**receipt_kwargs)
        assert r1.id != r2.id

    def test_custom_id_accepted(self, receipt_kwargs: dict) -> None:
        custom_id = str(uuid.uuid4())
        r = Receipt(id=custom_id, **receipt_kwargs)
        assert r.id == custom_id

    def test_hash_must_be_64_chars(self, receipt_kwargs: dict) -> None:
        receipt_kwargs["input_hash"] = "abc"  # too short
        with pytest.raises(ValidationError):
            Receipt(**receipt_kwargs)

    def test_hash_must_be_hex(self, receipt_kwargs: dict) -> None:
        receipt_kwargs["input_hash"] = "g" * 64  # 'g' is not hex
        with pytest.raises(ValidationError):
            Receipt(**receipt_kwargs)

    def test_hash_normalised_to_lowercase(self, receipt_kwargs: dict) -> None:
        receipt_kwargs["input_hash"] = "A" * 64
        r = Receipt(**receipt_kwargs)
        assert r.input_hash == "a" * 64

    def test_negative_latency_raises(self, receipt_kwargs: dict) -> None:
        receipt_kwargs["latency_ms"] = -1.0
        with pytest.raises(ValidationError):
            Receipt(**receipt_kwargs)

    def test_optional_fields_default_none(self, receipt_kwargs: dict) -> None:
        r = Receipt(**receipt_kwargs)
        assert r.error_code is None
        assert r.provider_request_id is None

    @pytest.mark.parametrize("status", list(ExecutionStatus))
    def test_all_statuses_accepted(
        self, receipt_kwargs: dict, status: ExecutionStatus
    ) -> None:
        receipt_kwargs["status"] = status
        r = Receipt(**receipt_kwargs)
        assert r.status == status

    def test_json_round_trip(self, receipt_kwargs: dict) -> None:
        r = Receipt(**receipt_kwargs)
        restored = Receipt.model_validate_json(r.model_dump_json())
        assert restored == r


# ---------------------------------------------------------------------------
# OutcomeEvent
# ---------------------------------------------------------------------------


class TestOutcomeEvent:
    def test_success_event(self) -> None:
        e = OutcomeEvent(
            receipt_id="rid",
            capability_id="cap",
            tenant_id="t1",
            success=True,
            latency_ms=10.0,
        )
        assert e.success is True
        assert e.error_taxonomy is None

    def test_failure_event_requires_taxonomy(self) -> None:
        with pytest.raises(ValidationError, match="error_taxonomy"):
            OutcomeEvent(
                receipt_id="rid",
                capability_id="cap",
                tenant_id="t1",
                success=False,
                latency_ms=10.0,
                # error_taxonomy missing -> should raise
            )

    def test_success_with_taxonomy_raises(self) -> None:
        with pytest.raises(ValidationError, match="error_taxonomy"):
            OutcomeEvent(
                receipt_id="rid",
                capability_id="cap",
                tenant_id="t1",
                success=True,
                latency_ms=10.0,
                error_taxonomy=ErrorTaxonomy.AUTH,
            )

    def test_failure_event_with_taxonomy(self) -> None:
        e = OutcomeEvent(
            receipt_id="rid",
            capability_id="cap",
            tenant_id="t1",
            success=False,
            latency_ms=10.0,
            error_taxonomy=ErrorTaxonomy.RATE_LIMIT,
        )
        assert e.error_taxonomy == ErrorTaxonomy.RATE_LIMIT

    @pytest.mark.parametrize("taxonomy", list(ErrorTaxonomy))
    def test_all_taxonomies_accepted(self, taxonomy: ErrorTaxonomy) -> None:
        e = OutcomeEvent(
            receipt_id="r",
            capability_id="c",
            tenant_id="t",
            success=False,
            latency_ms=5.0,
            error_taxonomy=taxonomy,
        )
        assert e.error_taxonomy == taxonomy


# ---------------------------------------------------------------------------
# PolicyBundle
# ---------------------------------------------------------------------------


class TestPolicyBundle:
    def test_minimal_bundle(self) -> None:
        b = PolicyBundle(
            id="b1",
            tenant_id="t1",
            capability_id="cap_v1",
        )
        assert b.require_approval is False
        assert b.budget_daily is None
        assert b.budget_monthly is None

    def test_budget_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            PolicyBundle(
                id="b1",
                tenant_id="t1",
                capability_id="cap",
                budget_daily=-1,
            )

    def test_full_bundle(self) -> None:
        b = PolicyBundle(
            id="b1",
            tenant_id="t1",
            capability_id="cap",
            allowed_scopes=["search:read", "search:write"],
            budget_daily=500,
            budget_monthly=10_000,
            domain_allowlist=["*.example.com"],
            require_approval=True,
        )
        assert b.budget_daily == 500
        assert b.require_approval is True


# ---------------------------------------------------------------------------
# PolicyDecision
# ---------------------------------------------------------------------------


class TestPolicyDecision:
    def test_allowed_decision(self) -> None:
        d = PolicyDecision(
            policy_bundle_id="b1",
            tenant_id="t1",
            capability_id="cap",
            allowed=True,
            rule_hit="all_checks_passed",
            evaluation_ms=0.5,
            request_id="req_1",
        )
        assert d.allowed is True

    def test_denied_decision(self) -> None:
        d = PolicyDecision(
            policy_bundle_id="b1",
            tenant_id="t1",
            capability_id="cap",
            allowed=False,
            rule_hit="scope_not_allowed:admin:write",
            evaluation_ms=0.1,
            request_id="req_2",
        )
        assert d.allowed is False
        assert "scope_not_allowed" in d.rule_hit

    def test_auto_uuid_id(self) -> None:
        d1 = PolicyDecision(
            policy_bundle_id="b",
            tenant_id="t",
            capability_id="c",
            allowed=True,
            rule_hit="ok",
            evaluation_ms=0.0,
            request_id="r",
        )
        d2 = PolicyDecision(
            policy_bundle_id="b",
            tenant_id="t",
            capability_id="c",
            allowed=True,
            rule_hit="ok",
            evaluation_ms=0.0,
            request_id="r",
        )
        assert d1.id != d2.id


# ---------------------------------------------------------------------------
# Enum completeness checks
# ---------------------------------------------------------------------------


class TestEnums:
    def test_risk_class_values(self) -> None:
        assert set(RiskClass) == {"low", "medium", "high", "critical"}

    def test_capability_status_values(self) -> None:
        assert set(CapabilityStatus) == {"draft", "published", "deprecated", "archived"}

    def test_execution_status_values(self) -> None:
        assert set(ExecutionStatus) == {"success", "failure", "timeout", "policy_denied"}

    def test_error_taxonomy_values(self) -> None:
        assert set(ErrorTaxonomy) == {
            "auth",
            "rate_limit",
            "timeout",
            "provider_5xx",
            "validation",
            "policy_denied",
            "unknown",
        }
