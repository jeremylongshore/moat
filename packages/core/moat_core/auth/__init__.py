"""
moat_core.auth
~~~~~~~~~~~~~~
JWT authentication and authorization utilities for Moat services.

Provides:
- JWT token decoding and validation
- FastAPI dependencies for extracting tenant context
- Optional auth bypass for local development
"""

from __future__ import annotations

from moat_core.auth.jwt import JWTConfig, JWTPayload, create_jwt, decode_jwt
from moat_core.auth.middleware import (
    AuthConfig,
    configure_auth,
    get_current_tenant,
    get_optional_tenant,
    require_tenant,
)

__all__ = [
    "AuthConfig",
    "JWTConfig",
    "JWTPayload",
    "configure_auth",
    "create_jwt",
    "decode_jwt",
    "get_current_tenant",
    "get_optional_tenant",
    "require_tenant",
]
