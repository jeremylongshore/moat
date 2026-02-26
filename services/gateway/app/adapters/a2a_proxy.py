"""
app.adapters.a2a_proxy
~~~~~~~~~~~~~~~~~~~~~~
Proxy adapter that forwards execution to remote A2A-protocol agents.

When an A2A agent's skills are registered as Moat capabilities (via the
skill builder), the gateway routes execution through this adapter. It
constructs an A2A-compatible request and sends it to the agent's URL.

Provider name: ``"a2a"``

Request flow:
    1. Receive capability execution from gateway pipeline
    2. Look up the target agent URL from capability metadata
    3. POST to agent's task endpoint with A2A task payload
    4. Poll/wait for task completion
    5. Return result to gateway
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from app.adapters.base import AdapterInterface

logger = logging.getLogger(__name__)

# Timeout for A2A agent communication
_A2A_TIMEOUT_S = 60.0


class A2AProxyAdapter(AdapterInterface):
    """Adapter that proxies execution to remote A2A-protocol agents.

    Capabilities backed by this adapter must include ``agent_url``
    in their metadata (stored in capability tags or input_schema).

    The adapter sends an A2A task/send request and returns the result.
    """

    @property
    def provider_name(self) -> str:
        return "a2a"

    async def execute(
        self,
        capability_id: str,
        capability_name: str,
        params: dict[str, Any],
        credential: str | None,
    ) -> dict[str, Any]:
        """Forward execution to a remote A2A agent.

        Expected params:
            - ``agent_url`` (str): The A2A agent's base URL.
            - ``skill_id`` (str, optional): The specific skill to invoke.
            - ``message`` (str or dict): The input message/payload.
            - Any other params are forwarded as-is.
        """
        agent_url = params.pop("agent_url", "")
        skill_id = params.pop("skill_id", capability_id)
        message = params.pop("message", params)

        if not agent_url:
            return {
                "status": "error",
                "error": "agent_url is required in params",
                "capability_id": capability_id,
            }

        # Build A2A task payload
        task_id = str(uuid.uuid4())
        a2a_payload = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": task_id,
            "params": {
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                message if isinstance(message, str) else str(message)
                            ),
                        }
                    ],
                },
                "metadata": {
                    "skill_id": skill_id,
                    "capability_id": capability_id,
                    "source": "moat-gateway",
                },
            },
        }

        # Add auth header if credential provided
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "Moat-Gateway/0.1.0",
        }
        if credential:
            headers["Authorization"] = f"Bearer {credential}"

        start = datetime.now(UTC)

        try:
            async with httpx.AsyncClient(timeout=_A2A_TIMEOUT_S) as client:
                # Discover agent card first to validate endpoint
                card_resp = await client.get(
                    f"{agent_url.rstrip('/')}/.well-known/agent.json",
                    headers={"User-Agent": "Moat-Gateway/0.1.0"},
                )

                agent_card = None
                if card_resp.status_code == 200:
                    agent_card = card_resp.json()

                # Send task to the agent
                resp = await client.post(
                    agent_url.rstrip("/"),
                    json=a2a_payload,
                    headers=headers,
                )

                latency_ms = (datetime.now(UTC) - start).total_seconds() * 1000

                if resp.status_code >= 400:
                    logger.warning(
                        "A2A agent returned error",
                        extra={
                            "agent_url": agent_url,
                            "status_code": resp.status_code,
                            "capability_id": capability_id,
                        },
                    )
                    return {
                        "status": "error",
                        "error": f"A2A agent returned HTTP {resp.status_code}",
                        "response_body": resp.text[:1000],
                        "capability_id": capability_id,
                        "latency_ms": round(latency_ms, 1),
                    }

                result = resp.json()

                # Extract the A2A result from JSON-RPC response
                a2a_result = result.get("result", result)
                task_status = "completed"
                if isinstance(a2a_result, dict):
                    task_status = a2a_result.get("status", {}).get("state", "completed")

                logger.info(
                    "A2A proxy execution completed",
                    extra={
                        "agent_url": agent_url,
                        "capability_id": capability_id,
                        "task_id": task_id,
                        "task_status": task_status,
                        "latency_ms": round(latency_ms, 1),
                    },
                )

                return {
                    "status": "success" if task_status == "completed" else task_status,
                    "capability_id": capability_id,
                    "task_id": task_id,
                    "a2a_result": a2a_result,
                    "agent_url": agent_url,
                    "agent_name": (agent_card.get("name") if agent_card else None),
                    "latency_ms": round(latency_ms, 1),
                    "executed_at": datetime.now(UTC).isoformat(),
                }

        except httpx.TimeoutException:
            latency_ms = (datetime.now(UTC) - start).total_seconds() * 1000
            logger.warning(
                "A2A proxy timed out",
                extra={
                    "agent_url": agent_url,
                    "capability_id": capability_id,
                    "timeout_s": _A2A_TIMEOUT_S,
                },
            )
            return {
                "status": "timeout",
                "error": f"A2A agent timed out after {_A2A_TIMEOUT_S}s",
                "capability_id": capability_id,
                "agent_url": agent_url,
                "latency_ms": round(latency_ms, 1),
            }
        except httpx.HTTPError as exc:
            latency_ms = (datetime.now(UTC) - start).total_seconds() * 1000
            logger.error(
                "A2A proxy HTTP error",
                extra={
                    "agent_url": agent_url,
                    "capability_id": capability_id,
                    "error": str(exc),
                },
            )
            return {
                "status": "error",
                "error": str(exc),
                "capability_id": capability_id,
                "agent_url": agent_url,
                "latency_ms": round(latency_ms, 1),
            }
