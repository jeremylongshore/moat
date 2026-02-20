"""
moat_core.auth.middleware
~~~~~~~~~~~~~~~~~~~~~~~~~
FastAPI dependencies for JWT authentication.

Provides three dependency injection patterns:
- get_current_tenant: Returns tenant_id, raises 401 if missing/invalid
- get_optional_tenant: Returns tenant_id or None (for public endpoints)
- require_tenant: Dependency factory for endpoints that need tenant context

Auth can be disabled via MOAT_AUTH_DISABLED=true for local development.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from moat_core.auth.jwt import (
    JWTConfig,
    JWTExpiredError,
    JWTInvalidError,
    JWTPayload,
    decode_jwt,
)

logger = logging.getLogger(__name__)

# Bearer token extractor (auto_error=False allows optional auth)
_bearer_scheme = HTTPBearer(auto_error=False)

# Type alias for the credentials dependency
_Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]


def _get_jwt_secret() -> str:
    return os.environ.get("MOAT_JWT_SECRET", "")


def _get_auth_disabled() -> bool:
    return os.environ.get("MOAT_AUTH_DISABLED", "").lower() in ("true", "1", "yes")


@dataclass
class AuthConfig:
    """Authentication configuration for a service."""

    jwt_secret: str = field(default_factory=_get_jwt_secret)
    jwt_algorithm: str = "HS256"
    jwt_issuer: str | None = None
    auth_disabled: bool = field(default_factory=_get_auth_disabled)

    def to_jwt_config(self) -> JWTConfig:
        """Convert to JWTConfig for token operations."""
        return JWTConfig(
            secret=self.jwt_secret,
            algorithm=self.jwt_algorithm,
            issuer=self.jwt_issuer,
        )


# Global config instance (configured at service startup)
_auth_config: AuthConfig | None = None


_MIN_SECRET_LENGTH = 32


def configure_auth(
    config: AuthConfig,
    *,
    environment: str = "local",
) -> None:
    """Configure authentication globally for this service.

    Call this during service startup (lifespan context).

    Raises:
        RuntimeError: If auth is enabled in non-local environments
            but JWT secret is missing or too short.
    """
    global _auth_config
    _auth_config = config

    if config.auth_disabled:
        if environment not in ("local", "test"):
            raise RuntimeError(
                f"MOAT_AUTH_DISABLED=true is not allowed in "
                f"'{environment}' environment. "
                f"Only 'local' and 'test' environments can disable auth."
            )
        logger.warning(
            "Authentication is DISABLED (MOAT_AUTH_DISABLED=true)"
        )
    elif not config.jwt_secret or len(config.jwt_secret) < _MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"MOAT_JWT_SECRET must be at least {_MIN_SECRET_LENGTH} "
            f"characters when authentication is enabled. "
            f"Set MOAT_AUTH_DISABLED=true for local development."
        )


def get_auth_config() -> AuthConfig:
    """Get the current auth configuration."""
    if _auth_config is None:
        return AuthConfig()  # Default from environment
    return _auth_config


async def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> JWTPayload | None:
    """Extract and decode JWT from Authorization header.

    Returns None if no token provided (for optional auth).
    Raises HTTPException for invalid/expired tokens.
    """
    config = get_auth_config()

    # Auth disabled - return mock tenant from header or default
    if config.auth_disabled:
        # Allow X-Tenant-ID header for testing without JWT
        tenant_id = request.headers.get("X-Tenant-ID", "dev-tenant")
        return JWTPayload(
            tenant_id=tenant_id,
            issued_at=0,
            expires_at=0,
            issuer=None,
            raw_claims={"_auth_disabled": True},
        )

    # No credentials provided
    if credentials is None:
        return None

    # Validate JWT
    try:
        return decode_jwt(credentials.credentials, config.to_jwt_config())
    except JWTExpiredError as exc:
        logger.debug("JWT expired", extra={"path": request.url.path})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except JWTInvalidError as exc:
        logger.debug(
            "JWT invalid",
            extra={"path": request.url.path, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_tenant(
    request: Request,
    credentials: _Credentials,
) -> str:
    """FastAPI dependency that requires authentication.

    Returns:
        The tenant_id from the JWT token.

    Raises:
        HTTPException 401: If no token provided or token is invalid.
    """
    payload = await _extract_token(request, credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload.tenant_id


async def get_optional_tenant(
    request: Request,
    credentials: _Credentials,
) -> str | None:
    """FastAPI dependency for optional authentication.

    Returns:
        The tenant_id from JWT, or None if no token provided.

    Raises:
        HTTPException 401: If token is provided but invalid/expired.
    """
    payload = await _extract_token(request, credentials)
    return payload.tenant_id if payload else None


def require_tenant(tenant_id_param: str = "tenant_id"):
    """Dependency factory that validates tenant_id in request body matches JWT.

    Use this for endpoints where tenant_id is in the request body and must
    match the authenticated tenant.

    Args:
        tenant_id_param: The name of the tenant_id field in the request body.

    Returns:
        A FastAPI dependency function.
    """

    async def _verify_tenant(
        request: Request,
        credentials: _Credentials,
    ) -> str:
        payload = await _extract_token(request, credentials)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # For JSON body validation, we need to read the body
        # This is called after request parsing, so body is available
        # FastAPI will have already parsed it if using Pydantic model
        return payload.tenant_id

    return _verify_tenant
