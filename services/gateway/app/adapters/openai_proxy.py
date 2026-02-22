"""
app.adapters.openai_proxy
~~~~~~~~~~~~~~~~~~~~~~~~~
Adapter that proxies OpenAI API calls on behalf of sandboxed agents.

The agent sends its chat completion request (model, messages, tools, etc.)
as ``params`` through the Moat execute endpoint.  This adapter resolves the
OpenAI API key from the vault (or ``OPENAI_API_KEY`` env var), forwards the
request to ``https://api.openai.com/v1/chat/completions``, and returns the
response.  The raw API key never reaches the agent.

Setup
-----
1. Store your OpenAI key in the Moat vault::

       curl -X POST http://localhost:8001/connections/store-credential \\
           -H "Content-Type: application/json" \\
           -d '{"tenant_id": "default", "provider": "openai",
                "credential_value": "sk-..."}'

2. Or set ``OPENAI_API_KEY`` in the gateway environment (dev shortcut).

3. Register the ``openai.inference`` capability (already in seed script).

4. Execute::

       curl -X POST http://localhost:8002/execute/{capability_id} \\
           -H "Content-Type: application/json" \\
           -d '{"tenant_id": "default",
                "params": {"model": "gpt-4o-mini",
                           "messages": [{"role": "user", "content": "Hello"}],
                           "max_tokens": 1024}}'
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.adapters.base import AdapterInterface

logger = logging.getLogger(__name__)

_OPENAI_API_BASE = "https://api.openai.com"
_TIMEOUT_SECONDS = 120.0  # LLM calls can be slow

# Persistent HTTP client — reused across requests.
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx client, creating it on first call."""
    global _http_client  # noqa: PLW0603
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    return _http_client


# Keys from the agent's params that we forward to OpenAI.
# Anything not in this set is stripped to prevent injection.
_ALLOWED_BODY_KEYS = frozenset({
    "model",
    "messages",
    "tools",
    "tool_choice",
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "stream",
    "stop",
    "presence_penalty",
    "frequency_penalty",
    "n",
    "response_format",
})


class OpenAIAdapter(AdapterInterface):
    """Adapter that proxies chat completion requests to the OpenAI API.

    Provider name: ``"openai"``

    Expected ``params`` keys (same as OpenAI chat completions API):
    - ``model`` (str): Model name (e.g. ``gpt-4o-mini``).
    - ``messages`` (list): Chat messages array.
    - Plus any optional OpenAI parameters (tools, temperature, etc.).
    """

    @property
    def provider_name(self) -> str:
        return "openai"

    async def execute(
        self,
        capability_id: str,
        capability_name: str,
        params: dict[str, Any],
        credential: str | None,
    ) -> dict[str, Any]:
        """Proxy a chat completion request to OpenAI.

        Parameters
        ----------
        capability_id:
            ID of the capability being executed.
        capability_name:
            Friendly name for logging.
        params:
            OpenAI chat completions body (model, messages, etc.).
        credential:
            OpenAI API key. Falls back to ``OPENAI_API_KEY`` env var.

        Returns
        -------
        dict
            Full OpenAI API response (choices, usage, etc.).

        Raises
        ------
        RuntimeError
            If no API key is available or the OpenAI API returns an error.
        """
        api_key = credential or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "No OpenAI API key available. Set OPENAI_API_KEY env var "
                "or store a credential via the vault."
            )

        model = params.get("model")
        messages = params.get("messages")
        if not model or not messages:
            raise RuntimeError(
                "OpenAIAdapter requires 'model' and 'messages' in params. "
                f"Got keys: {list(params.keys())}"
            )

        # Build sanitised request body — only forward allowed keys
        body: dict[str, Any] = {}
        for key in _ALLOWED_BODY_KEYS:
            if key in params:
                body[key] = params[key]

        # Force stream=false — we return the full response synchronously
        body["stream"] = False

        logger.info(
            "Proxying to OpenAI",
            extra={
                "capability_id": capability_id,
                "model": model,
                "message_count": len(messages),
                # API key is NOT logged
            },
        )

        client = _get_http_client()
        response = await client.post(
            f"{_OPENAI_API_BASE}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )

        if response.status_code != 200:
            # Include status and error message but NOT the API key
            error_text = response.text[:500]
            raise RuntimeError(
                f"OpenAI API error: {response.status_code}: {error_text}"
            )

        data = response.json()

        # Return the full response — the agent needs choices, usage, etc.
        # The receipt will hash the output; raw content stays between
        # gateway and agent on the internal network.
        result = {
            "id": data.get("id", ""),
            "model": data.get("model", model),
            "choices": data.get("choices", []),
            "usage": data.get("usage", {}),
            "created": data.get("created", 0),
        }

        usage = data.get("usage", {})
        logger.info(
            "OpenAI response received",
            extra={
                "capability_id": capability_id,
                "model": result["model"],
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        )

        return result
