"""
app.adapters.stub
~~~~~~~~~~~~~~~~~
Stub adapter for development and testing.

The StubAdapter simulates a successful provider response without making
any real network calls. It echoes the submitted params back in the result
and adds a synthetic ``latency_ms`` field to aid performance testing.

Simulated latency is between 100-500ms via asyncio.sleep.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any

from app.adapters.base import AdapterInterface

logger = logging.getLogger(__name__)

# Simulated latency range in seconds
_MIN_LATENCY_S = 0.1
_MAX_LATENCY_S = 0.5


class StubAdapter(AdapterInterface):
    """Fake provider adapter that returns a synthetic success response.

    Use this adapter during development to exercise the full gateway
    pipeline (policy evaluation, idempotency, receipts) without requiring
    real provider credentials.

    Provider name: ``"stub"``

    The adapter registers itself under the name ``"stub"`` and is also
    returned as a fallback by :meth:`AdapterRegistry.get_or_stub` for any
    provider that has no registered adapter.
    """

    @property
    def provider_name(self) -> str:
        return "stub"

    async def execute(
        self,
        capability_id: str,
        capability_name: str,
        params: dict[str, Any],
        credential: str | None,
    ) -> dict[str, Any]:
        """Return a fake success response after simulating network latency.

        Parameters
        ----------
        capability_id:
            ID of the capability being executed.
        capability_name:
            Friendly name for logging purposes.
        params:
            Input parameters echoed back in the response.
        credential:
            Ignored by the stub (no real network call is made). The raw
            value is never logged.

        Returns
        -------
        dict
            Synthetic result payload containing:
            - ``status``: always ``"success"``
            - ``capability_id``: the requested capability
            - ``echo_params``: the submitted params (for debugging)
            - ``latency_ms``: the simulated latency in milliseconds
            - ``stub``: ``True`` (flag to distinguish stub from real results)
            - ``executed_at``: ISO 8601 timestamp
        """
        latency_s = random.uniform(_MIN_LATENCY_S, _MAX_LATENCY_S)
        await asyncio.sleep(latency_s)
        latency_ms = round(latency_s * 1000, 1)

        logger.debug(
            "StubAdapter executed",
            extra={
                "capability_id": capability_id,
                "capability_name": capability_name,
                "latency_ms": latency_ms,
                "has_credential": credential is not None,
                # credential value is intentionally NOT logged
            },
        )

        return {
            "status": "success",
            "capability_id": capability_id,
            "capability_name": capability_name,
            "echo_params": params,
            "latency_ms": latency_ms,
            "stub": True,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
