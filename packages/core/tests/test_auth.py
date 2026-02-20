"""
Tests for moat_core.auth - JWT authentication utilities.
"""

from __future__ import annotations

import time

import pytest

from moat_core.auth import (
    JWTConfig,
    create_jwt,
    decode_jwt,
)
from moat_core.auth.jwt import JWTExpiredError, JWTInvalidError


class TestJWTCreation:
    """Test JWT token creation."""

    def test_create_basic_jwt(self):
        """Create a simple JWT with tenant_id."""
        config = JWTConfig(secret="test-secret-key")
        token = create_jwt("tenant-123", config)

        assert token
        assert isinstance(token, str)
        assert len(token.split(".")) == 3  # Header.Payload.Signature

    def test_create_jwt_with_issuer(self):
        """JWT includes issuer when configured."""
        config = JWTConfig(secret="test-secret", issuer="moat-auth")
        token = create_jwt("tenant-123", config)
        payload = decode_jwt(token, config)

        assert payload.issuer == "moat-auth"

    def test_create_jwt_with_custom_ttl(self):
        """JWT uses custom TTL when specified."""
        config = JWTConfig(secret="test-secret", default_ttl_seconds=3600)
        token = create_jwt("tenant-123", config, ttl_seconds=60)
        payload = decode_jwt(token, config)

        # Token should expire in ~60 seconds, not 3600
        assert payload.expires_at - payload.issued_at == 60

    def test_create_jwt_with_extra_claims(self):
        """Extra claims are included in token."""
        config = JWTConfig(secret="test-secret")
        token = create_jwt(
            "tenant-123",
            config,
            extra_claims={"role": "admin", "permissions": ["read", "write"]},
        )
        payload = decode_jwt(token, config)

        assert payload.raw_claims is not None
        assert payload.raw_claims.get("role") == "admin"
        assert payload.raw_claims.get("permissions") == ["read", "write"]


class TestJWTDecoding:
    """Test JWT token decoding and validation."""

    def test_decode_valid_jwt(self):
        """Decode a valid JWT successfully."""
        config = JWTConfig(secret="test-secret")
        token = create_jwt("tenant-123", config)
        payload = decode_jwt(token, config)

        assert payload.tenant_id == "tenant-123"
        assert payload.issued_at > 0
        assert payload.expires_at > payload.issued_at

    def test_decode_extracts_tenant_id(self):
        """tenant_id is correctly extracted from sub claim."""
        config = JWTConfig(secret="test-secret")
        token = create_jwt("my-special-tenant", config)
        payload = decode_jwt(token, config)

        assert payload.tenant_id == "my-special-tenant"

    def test_decode_invalid_signature(self):
        """Reject token with wrong signature."""
        config1 = JWTConfig(secret="secret-one")
        config2 = JWTConfig(secret="secret-two")

        token = create_jwt("tenant-123", config1)

        with pytest.raises(JWTInvalidError, match="Invalid token"):
            decode_jwt(token, config2)

    def test_decode_expired_token(self):
        """Reject expired token."""
        config = JWTConfig(secret="test-secret")
        # Create token with 0 TTL (already expired)
        token = create_jwt("tenant-123", config, ttl_seconds=-1)

        with pytest.raises(JWTExpiredError, match="Token has expired"):
            decode_jwt(token, config)

    def test_decode_malformed_token(self):
        """Reject malformed token."""
        config = JWTConfig(secret="test-secret")

        with pytest.raises(JWTInvalidError):
            decode_jwt("not.a.valid.token", config)

        with pytest.raises(JWTInvalidError):
            decode_jwt("completely-invalid", config)

    def test_decode_with_issuer_validation(self):
        """Validate issuer when configured."""
        config_with_issuer = JWTConfig(secret="test-secret", issuer="moat-auth")
        config_wrong_issuer = JWTConfig(secret="test-secret", issuer="other-issuer")

        token = create_jwt("tenant-123", config_with_issuer)

        # Same issuer works
        payload = decode_jwt(token, config_with_issuer)
        assert payload.tenant_id == "tenant-123"

        # Wrong issuer fails
        with pytest.raises(JWTInvalidError):
            decode_jwt(token, config_wrong_issuer)


class TestJWTTiming:
    """Test JWT timing-related functionality."""

    def test_issued_at_is_set(self):
        """JWT includes iat (issued_at) timestamp."""
        config = JWTConfig(secret="test-secret")
        before = int(time.time())
        token = create_jwt("tenant-123", config)
        after = int(time.time())

        payload = decode_jwt(token, config)
        assert before <= payload.issued_at <= after

    def test_expires_at_respects_ttl(self):
        """JWT exp is correctly set based on TTL."""
        config = JWTConfig(secret="test-secret")
        token = create_jwt("tenant-123", config, ttl_seconds=300)
        payload = decode_jwt(token, config)

        expected_exp = payload.issued_at + 300
        assert payload.expires_at == expected_exp


class TestJWTConfig:
    """Test JWTConfig defaults and validation."""

    def test_default_algorithm(self):
        """Default algorithm is HS256."""
        config = JWTConfig(secret="test")
        assert config.algorithm == "HS256"

    def test_default_ttl(self):
        """Default TTL is 1 hour."""
        config = JWTConfig(secret="test")
        assert config.default_ttl_seconds == 3600

    def test_config_is_immutable(self):
        """JWTConfig is frozen (immutable)."""
        config = JWTConfig(secret="test")
        with pytest.raises(AttributeError):
            config.secret = "new-secret"  # type: ignore
