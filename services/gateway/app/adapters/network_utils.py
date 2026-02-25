"""
app.adapters.network_utils
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Shared network validation utilities used by multiple adapters.
"""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse


def is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/reserved IP range.

    Returns True for:
    - RFC 1918 private addresses (10.x, 172.16-31.x, 192.168.x)
    - Loopback (127.x, ::1)
    - Reserved ranges
    - Known private hostnames (localhost, *.local, *.internal)
    """
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_reserved or addr.is_loopback
    except ValueError:
        # Not a bare IP — hostname will be resolved by httpx.
        # Block known private patterns.
        lower = hostname.lower()
        return lower == "localhost" or lower.endswith((".local", ".internal"))


def validate_url_domain(url: str, allowlist: set[str]) -> str:
    """Validate URL against a domain allowlist and security rules.

    Returns the validated URL or raises RuntimeError.
    """
    parsed = urlparse(url)

    # Require HTTPS (allow HTTP only for localhost in tests)
    if parsed.scheme not in ("https", "http"):
        raise RuntimeError(
            f"Unsupported scheme: {parsed.scheme!r}. Only HTTPS is allowed."
        )

    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"):
        raise RuntimeError("HTTP is not allowed for external requests. Use HTTPS.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise RuntimeError("URL has no hostname.")

    # Block private IPs / internal hosts
    if is_private_ip(hostname):
        raise RuntimeError(
            f"Requests to private/internal addresses are blocked: {hostname}"
        )

    # Check domain allowlist
    if hostname not in allowlist:
        raise RuntimeError(
            f"Domain {hostname!r} is not in the allowlist. Allowed: {sorted(allowlist)}"
        )

    return url


def parse_domain_allowlist(env_var: str, default: str = "") -> set[str]:
    """Parse a comma-separated domain allowlist from an environment variable."""
    raw = os.environ.get(env_var, default)
    return {d.strip().lower() for d in raw.split(",") if d.strip()}
