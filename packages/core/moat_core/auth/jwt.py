"""
moat_core.auth.jwt
~~~~~~~~~~~~~~~~~~
JWT token encoding and decoding utilities.

Uses PyJWT for HS256 tokens. Tokens contain:
- sub: tenant_id (required)
- exp: expiration timestamp (required)
- iat: issued-at timestamp (auto-set)
- iss: issuer (optional, for multi-issuer validation)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError


@dataclass(frozen=True)
class JWTConfig:
    """Configuration for JWT operations."""

    secret: str
    algorithm: str = "HS256"
    issuer: str | None = None
    default_ttl_seconds: int = 3600  # 1 hour


@dataclass(frozen=True)
class JWTPayload:
    """Decoded JWT payload with extracted tenant context."""

    tenant_id: str
    issued_at: int
    expires_at: int
    issuer: str | None = None
    raw_claims: dict[str, Any] | None = None


class JWTError(Exception):
    """Base exception for JWT-related errors."""


class JWTExpiredError(JWTError):
    """Token has expired."""


class JWTInvalidError(JWTError):
    """Token is malformed or signature is invalid."""


def decode_jwt(token: str, config: JWTConfig) -> JWTPayload:
    """Decode and validate a JWT token.

    Args:
        token: The JWT string (without "Bearer " prefix).
        config: JWT configuration with secret and algorithm.

    Returns:
        JWTPayload with tenant_id and timing info.

    Raises:
        JWTExpiredError: If the token has expired.
        JWTInvalidError: If the token is malformed or signature fails.
    """
    try:
        options = {"require": ["sub", "exp", "iat"]}
        if config.issuer:
            options["require"].append("iss")

        payload = jwt.decode(
            token,
            config.secret,
            algorithms=[config.algorithm],
            options=options,
            issuer=config.issuer if config.issuer else None,
        )

        return JWTPayload(
            tenant_id=payload["sub"],
            issued_at=payload["iat"],
            expires_at=payload["exp"],
            issuer=payload.get("iss"),
            raw_claims=payload,
        )
    except ExpiredSignatureError as e:
        raise JWTExpiredError("Token has expired") from e
    except InvalidTokenError as e:
        raise JWTInvalidError(f"Invalid token: {e}") from e


def create_jwt(
    tenant_id: str,
    config: JWTConfig,
    ttl_seconds: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT token.

    Args:
        tenant_id: The tenant identifier (stored in 'sub' claim).
        config: JWT configuration with secret and algorithm.
        ttl_seconds: Token lifetime in seconds (defaults to config.default_ttl_seconds).
        extra_claims: Additional claims to include in the payload.

    Returns:
        Signed JWT string.
    """
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else config.default_ttl_seconds

    payload: dict[str, Any] = {
        "sub": tenant_id,
        "iat": now,
        "exp": now + ttl,
    }

    if config.issuer:
        payload["iss"] = config.issuer

    if extra_claims:
        _reserved = {"sub", "iat", "exp", "iss"}
        safe_claims = {k: v for k, v in extra_claims.items() if k not in _reserved}
        payload.update(safe_claims)

    return jwt.encode(payload, config.secret, algorithm=config.algorithm)
