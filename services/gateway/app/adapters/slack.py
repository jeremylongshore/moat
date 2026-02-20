"""
app.adapters.slack
~~~~~~~~~~~~~~~~~~
Slack adapter for posting messages via the Slack Web API.

Uses ``httpx.AsyncClient`` to call ``chat.postMessage``. The OAuth bot
token is resolved from the vault at execution time - it is never stored
in the adapter or logged.

Setup
-----
1. Create a Slack App at https://api.slack.com/apps
2. Add the ``chat:write`` bot scope under **OAuth & Permissions**
3. Install the app to your workspace
4. Copy the **Bot User OAuth Token** (``xoxb-...``)
5. Store it in the Moat vault via::

       curl -X POST http://localhost:8001/connections/store-credential \\
           -H "Content-Type: application/json" \\
           -d '{"tenant_id": "your-tenant", "provider": "slack",
                "credential_value": "xoxb-your-token"}'

6. Register a ``slack.post_message`` capability::

       curl -X POST http://localhost:8001/capabilities \\
           -H "Content-Type: application/json" \\
           -d '{"name": "slack.post_message", "provider": "slack",
                "version": "1.0.0", "description": "Post a message to Slack",
                "input_schema": {"type": "object", "required": ["channel", "text"],
                    "properties": {
                        "channel": {"type": "string"},
                        "text": {"type": "string"}}}}'

7. Execute it::

       curl -X POST \\
           http://localhost:8002/execute/{capability_id} \\
           -H "Content-Type: application/json" \\
           -d '{"tenant_id": "your-tenant",
                "params": {"channel": "#test",
                "text": "Hello from Moat!"}}'

Environment Variable Shortcut
-----------------------------
For local development, set ``SLACK_BOT_TOKEN`` in your environment or ``.env``
file. The adapter will use it as a fallback when no vault credential is provided.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from moat_core.redaction import hash_redacted

from app.adapters.base import AdapterInterface

logger = logging.getLogger(__name__)

_SLACK_API_BASE = "https://slack.com/api"
_TIMEOUT_SECONDS = 10.0

# Persistent HTTP client — reused across requests instead of
# creating a new client per call.  Lazily initialised on first use.
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx client, creating it on first call."""
    global _http_client  # noqa: PLW0603
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    return _http_client


class SlackAdapter(AdapterInterface):
    """Adapter that posts messages to Slack via ``chat.postMessage``.

    Provider name: ``"slack"``

    Expected ``params`` keys:
    - ``channel`` (str): Channel name (``#general``) or ID (``C0123456``).
    - ``text`` (str): Message body (supports Slack mrkdwn formatting).
    - ``thread_ts`` (str, optional): Reply to a thread.
    """

    @property
    def provider_name(self) -> str:
        return "slack"

    async def execute(
        self,
        capability_id: str,
        capability_name: str,
        params: dict[str, Any],
        credential: str | None,
    ) -> dict[str, Any]:
        """Post a message to Slack.

        Parameters
        ----------
        capability_id:
            ID of the capability being executed.
        capability_name:
            Friendly name for logging.
        params:
            Must contain ``channel`` and ``text``. May contain ``thread_ts``.
        credential:
            Slack bot token (``xoxb-...``). Falls back to ``SLACK_BOT_TOKEN``
            env var if None.

        Returns
        -------
        dict
            Slack API response including ``ts`` (message timestamp) and
            ``channel`` (resolved channel ID).

        Raises
        ------
        RuntimeError
            If the Slack API returns ``ok: false`` or the request fails.
        """
        token = credential or os.environ.get("SLACK_BOT_TOKEN")
        if not token:
            raise RuntimeError(
                "No Slack bot token available. Set SLACK_BOT_TOKEN env var "
                "or store a credential via the vault."
            )

        channel = params.get("channel")
        text = params.get("text")
        if not channel or not text:
            raise RuntimeError(
                "SlackAdapter requires 'channel' and 'text' in params. "
                f"Got keys: {list(params.keys())}"
            )

        payload: dict[str, Any] = {
            "channel": channel,
            "text": text,
        }
        if "thread_ts" in params:
            payload["thread_ts"] = params["thread_ts"]

        logger.info(
            "Posting to Slack",
            extra={
                "capability_id": capability_id,
                "channel": channel,
                # token and text content are NOT logged
            },
        )

        client = _get_http_client()
        response = await client.post(
            f"{_SLACK_API_BASE}/chat.postMessage",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=payload,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Slack API HTTP error: {response.status_code} {response.text}"
            )

        data = response.json()
        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            raise RuntimeError(f"Slack API error: {error}")

        result = {
            "ok": True,
            "channel": data.get("channel", channel),
            "ts": data.get("ts", ""),
            # SHA-256 hash — no raw content in receipt
            "message_text_hash": hash_redacted(text),
        }

        logger.info(
            "Slack message posted",
            extra={
                "capability_id": capability_id,
                "channel": result["channel"],
                "ts": result["ts"],
            },
        )

        return result
