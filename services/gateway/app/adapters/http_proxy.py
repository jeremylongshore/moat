"""
app.adapters.http_proxy
~~~~~~~~~~~~~~~~~~~~~~~~
Generic HTTPS proxy adapter with domain allowlist enforcement.

The sandboxed agent sends an HTTP request description (url, method, headers,
body) through the Moat execute endpoint.  This adapter validates the target
URL against a domain allowlist, strips dangerous headers, blocks private IPs,
and forwards the request to the external service.

The agent never gets direct network access -- all external HTTP flows through
this adapter, governed by Moat policy.

Setup
-----
1. Set ``HTTP_PROXY_DOMAIN_ALLOWLIST`` in the gateway environment::

       HTTP_PROXY_DOMAIN_ALLOWLIST=api.github.com,console.algora.io

2. Register the ``http.proxy`` capability (already in seed script).

3. Execute::

       curl -X POST http://localhost:8002/execute/http.proxy \\
           -H "Content-Type: application/json" \\
           -d '{"tenant_id": "automaton", "scope": "execute",
                "params": {"url": "https://api.github.com/zen",
                            "method": "GET"}}'
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from app.adapters.base import AdapterInterface
from app.adapters.network_utils import is_private_ip

logger = logging.getLogger(__name__)

_MAX_TIMEOUT_SECONDS = 30.0

# Hop-by-hop headers (RFC 2616 s13.5.1) — never forwarded.
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

# Headers the adapter never forwards from the caller.
_STRIPPED_REQUEST_HEADERS = _HOP_BY_HOP_HEADERS | frozenset(
    {
        "host",
        "content-length",  # httpx recalculates
    }
)

# Headers stripped from the upstream response before returning to the agent.
_STRIPPED_RESPONSE_HEADERS = _HOP_BY_HOP_HEADERS | frozenset(
    {
        "content-encoding",  # httpx already decodes
        "content-length",
    }
)

_ALLOWED_METHODS = frozenset(
    {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
)

# Persistent HTTP client — reused across requests for connection pooling.
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx client, creating it on first call."""
    global _http_client  # noqa: PLW0603
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=_MAX_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=5,
        )
    return _http_client


def _get_domain_allowlist() -> set[str]:
    """Parse the domain allowlist from the environment variable."""
    raw = os.environ.get(
        "HTTP_PROXY_DOMAIN_ALLOWLIST",
        "api.github.com,console.algora.io,gitcoin.co,api.polar.sh,"
        "api.hackerone.com,api.bugcrowd.com,api.thegraph.com,"
        "eth-mainnet.g.alchemy.com,polygon-mainnet.g.alchemy.com,"
        "arb-mainnet.g.alchemy.com,opt-mainnet.g.alchemy.com",
    )
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/reserved IP range.

    Delegates to the shared network_utils module.
    """
    return is_private_ip(hostname)


def _validate_url(url: str, allowlist: set[str]) -> str:
    """Validate URL against the domain allowlist and security rules.

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
    if _is_private_ip(hostname):
        raise RuntimeError(
            f"Requests to private/internal addresses are blocked: {hostname}"
        )

    # Check domain allowlist
    if hostname not in allowlist:
        raise RuntimeError(
            f"Domain {hostname!r} is not in the allowlist. "
            f"Allowed domains: {sorted(allowlist)}"
        )

    return url


class HttpProxyAdapter(AdapterInterface):
    """Generic HTTPS proxy adapter with domain allowlist enforcement.

    Provider name: ``"http_proxy"``

    Expected ``params`` keys:

    - ``url`` (str, required): Target URL (must be HTTPS, domain on allowlist).
    - ``method`` (str): HTTP method. Default ``GET``.
    - ``headers`` (dict): Request headers to forward.
    - ``body`` (any): Request body (sent as JSON if dict, raw otherwise).
    - ``timeout`` (float): Request timeout in seconds (max 30s).
    """

    @property
    def provider_name(self) -> str:
        return "http_proxy"

    async def execute(
        self,
        capability_id: str,
        capability_name: str,
        params: dict[str, Any],
        credential: str | None,
    ) -> dict[str, Any]:
        """Proxy an HTTP request to an allowlisted external service.

        Returns
        -------
        dict
            ``{ status_code, headers, body, content_type }``

        Raises
        ------
        RuntimeError
            If the URL is blocked, the method is invalid, or the upstream fails.
        """
        url = params.get("url")
        if not url or not isinstance(url, str):
            raise RuntimeError("HttpProxyAdapter requires 'url' (string) in params.")

        method = params.get("method", "GET").upper()
        if method not in _ALLOWED_METHODS:
            raise RuntimeError(
                f"HTTP method {method!r} is not allowed. "
                f"Allowed: {sorted(_ALLOWED_METHODS)}"
            )

        # Validate URL against allowlist and security rules
        allowlist = _get_domain_allowlist()
        url = _validate_url(url, allowlist)

        # Sanitise request headers — strip hop-by-hop and dangerous headers
        raw_headers = params.get("headers") or {}
        if not isinstance(raw_headers, dict):
            raise RuntimeError("'headers' must be a dict.")

        headers: dict[str, str] = {}
        for key, value in raw_headers.items():
            if key.lower() not in _STRIPPED_REQUEST_HEADERS:
                headers[str(key)] = str(value)

        # Request body
        body = params.get("body")

        # Timeout — capped at _MAX_TIMEOUT_SECONDS
        timeout = min(
            float(params.get("timeout", _MAX_TIMEOUT_SECONDS)), _MAX_TIMEOUT_SECONDS
        )

        logger.info(
            "Proxying HTTP request",
            extra={
                "capability_id": capability_id,
                "method": method,
                "url_host": urlparse(url).hostname,
                "url_path": urlparse(url).path,
                # Full URL logged for debugging; no credentials in URL params
            },
        )

        client = _get_http_client()

        # Build request kwargs
        request_kwargs: dict[str, Any] = {
            "method": method,
            "url": url,
            "headers": headers,
            "timeout": timeout,
        }

        if body is not None and method in ("POST", "PUT", "PATCH"):
            if isinstance(body, (dict, list)):
                request_kwargs["json"] = body
            elif isinstance(body, str):
                request_kwargs["content"] = body
            else:
                request_kwargs["content"] = str(body)

        response = await client.request(**request_kwargs)

        # Build sanitised response headers
        response_headers: dict[str, str] = {}
        for key, value in response.headers.items():
            if key.lower() not in _STRIPPED_RESPONSE_HEADERS:
                response_headers[key] = value

        # Parse response body
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                response_body = response.json()
            except Exception:
                response_body = response.text
        else:
            response_body = response.text

        logger.info(
            "HTTP proxy response received",
            extra={
                "capability_id": capability_id,
                "status_code": response.status_code,
                "content_type": content_type,
                "response_size": len(response.content),
            },
        )

        return {
            "status_code": response.status_code,
            "headers": response_headers,
            "body": response_body,
            "content_type": content_type,
        }
