"""
app.adapters.base
~~~~~~~~~~~~~~~~~
Base adapter interface and registry for provider integrations.

Each adapter wraps a single external provider (OpenAI, Anthropic, internal
tools, etc.) and presents a uniform async execute() interface to the gateway.

The AdapterRegistry is a module-level singleton that maps provider names to
adapter instances. The gateway looks up the correct adapter at execution time
based on the capability's provider field.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class AdapterInterface(ABC):
    """Abstract base class for all provider adapters.

    Subclasses must implement :meth:`execute`. They should:
    - Perform all I/O asynchronously
    - Never log the raw credential value
    - Raise :class:`moat_core.errors.AdapterError` on upstream failures
      (falling back to a plain RuntimeError if moat_core is unavailable)
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the canonical provider name (e.g. ``'openai'``)."""

    @abstractmethod
    async def execute(
        self,
        capability_id: str,
        capability_name: str,
        params: dict[str, Any],
        credential: str | None,
    ) -> dict[str, Any]:
        """Execute the capability against the upstream provider.

        Parameters
        ----------
        capability_id:
            Unique identifier of the capability being invoked.
        capability_name:
            Human-readable name of the capability (for logging).
        params:
            Validated input parameters from the caller.
        credential:
            Plaintext credential fetched from the vault for this execution.
            This value must **never** appear in logs or be persisted.

        Returns
        -------
        dict
            Raw result from the upstream provider.

        Raises
        ------
        RuntimeError or moat_core.errors.AdapterError
            On any upstream failure.
        """


class AdapterRegistry:
    """Registry mapping provider names to :class:`AdapterInterface` instances.

    Usage::

        registry = AdapterRegistry()
        registry.register(StubAdapter())

        adapter = registry.get("stub")  # Returns StubAdapter instance
    """

    def __init__(self) -> None:
        self._adapters: dict[str, AdapterInterface] = {}

    def register(self, adapter: AdapterInterface) -> None:
        """Register an adapter under its provider name.

        If an adapter is already registered for the same provider name, it
        will be silently replaced (allowing hot-swap in tests).
        """
        name = adapter.provider_name
        if name in self._adapters:
            logger.warning("Replacing existing adapter for provider", extra={"provider": name})
        self._adapters[name] = adapter
        logger.info("Adapter registered", extra={"provider": name, "adapter": type(adapter).__name__})

    def get(self, provider: str) -> AdapterInterface | None:
        """Return the adapter for ``provider``, or None if not registered."""
        return self._adapters.get(provider)

    def get_or_stub(self, provider: str) -> AdapterInterface:
        """Return the adapter for ``provider``, falling back to the stub adapter.

        Useful during development when real adapters are not yet wired.
        """
        from app.adapters.stub import StubAdapter

        adapter = self._adapters.get(provider)
        if adapter is None:
            logger.warning(
                "No adapter registered for provider, using StubAdapter",
                extra={"provider": provider},
            )
            return StubAdapter()
        return adapter

    @property
    def registered_providers(self) -> list[str]:
        return list(self._adapters.keys())


# Module-level registry singleton
registry = AdapterRegistry()
