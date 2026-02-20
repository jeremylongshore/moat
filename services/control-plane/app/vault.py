"""
app.vault
~~~~~~~~~
Abstraction layer for secret storage.

In production, credentials are NEVER stored inline or logged. The control
plane only stores *references* (opaque strings) pointing to secrets held
in an external vault (e.g. Google Secret Manager).

Classes
-------
VaultInterface
    Abstract base class that all vault implementations must satisfy.

LocalVault
    In-memory implementation for local development only.
    WARNING: data is lost on restart and is not suitable for production.

SecretManagerVault
    Skeleton for Google Secret Manager integration.
    Raises NotImplementedError until fully implemented.
"""

from __future__ import annotations

import os
import secrets
from abc import ABC, abstractmethod


class VaultInterface(ABC):
    """Abstract interface for secret storage backends."""

    @abstractmethod
    async def get_secret(self, reference: str) -> str:
        """Resolve a secret reference to its plaintext value.

        Parameters
        ----------
        reference:
            The opaque reference string returned by :meth:`store_secret`.

        Returns
        -------
        str
            The plaintext secret value.

        Raises
        ------
        KeyError
            If the reference is not found in the vault.
        """

    @abstractmethod
    async def store_secret(self, key: str, value: str) -> str:
        """Persist a secret and return an opaque reference.

        The plaintext *value* must never be stored verbatim in the control
        plane database or appear in logs. Only the returned *reference*
        (an opaque, non-guessable string) should be persisted.

        Parameters
        ----------
        key:
            A logical name for the secret (e.g. ``"openai-api-key"``).
        value:
            The plaintext secret value.

        Returns
        -------
        str
            An opaque reference string safe to persist in the database.
        """


class LocalVault(VaultInterface):
    """In-memory vault for local development and testing.

    WARNING
    -------
    This implementation holds plaintext secrets in a Python dict. It is
    **not** suitable for production use. It exists solely to allow the
    service to run without external dependencies during development.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get_secret(self, reference: str) -> str:
        try:
            return self._store[reference]
        except KeyError:
            raise KeyError(f"Secret reference not found: {reference!r}") from None

    async def store_secret(self, key: str, value: str) -> str:
        # Generate a cryptographically random, non-guessable reference.
        reference = f"local://{key}/{secrets.token_urlsafe(32)}"
        self._store[reference] = value
        return reference


class SecretManagerVault(VaultInterface):
    """Google Secret Manager-backed vault.

    To activate this implementation:

    1. Install the client library::

           pip install google-cloud-secret-manager

    2. Set ``SECRET_MANAGER_PROJECT`` in the service environment.

    3. Replace the ``NotImplementedError`` calls below with real calls to
       ``google.cloud.secretmanager_v1.SecretManagerServiceClient``.
    """

    def __init__(self, project_id: str) -> None:
        self._project_id = project_id
        self._client = None  # Initialise lazily to avoid import-time failures.

    def _get_client(self) -> object:
        try:
            from google.cloud import secretmanager  # type: ignore[import]

            if self._client is None:
                self._client = secretmanager.SecretManagerServiceClient()
            return self._client
        except ImportError as exc:
            raise ImportError(
                "google-cloud-secret-manager is not installed. "
                "Run: pip install google-cloud-secret-manager"
            ) from exc

    async def get_secret(self, reference: str) -> str:
        """Retrieve a secret version from Google Secret Manager.

        Not yet implemented. Connect the ``_get_client()`` call and parse
        the reference (format: ``projects/{project}/secrets/{name}/versions/{ver}``)
        to build the full resource name.
        """
        raise NotImplementedError(
            "SecretManagerVault.get_secret is not yet implemented. "
            "Use LocalVault for development or implement the GCP integration. "
            f"Reference requested: {reference!r}"
        )

    async def store_secret(self, key: str, value: str) -> str:
        """Create or add a version to a Google Secret Manager secret.

        Not yet implemented. Connect the ``_get_client()`` call to create
        the secret (if not exists) and add a version with the payload.
        Returns the full resource name as the reference.
        """
        raise NotImplementedError(
            "SecretManagerVault.store_secret is not yet implemented. "
            "Use LocalVault for development or implement the GCP integration. "
            f"Key: {key!r}"
        )


class EnvVault(VaultInterface):
    """Vault that reads secrets from environment variables.

    Useful for local development and CI where secrets are injected
    via env vars rather than a vault service.

    Reference format: ``env://VARIABLE_NAME``
    """

    async def get_secret(self, reference: str) -> str:
        if reference.startswith("env://"):
            var_name = reference[6:]  # Strip "env://" prefix
            value = os.environ.get(var_name, "")
            if not value:
                raise KeyError(f"Environment variable not set: {var_name!r}")
            return value
        raise KeyError(f"EnvVault only handles env:// references, got: {reference!r}")

    async def store_secret(self, key: str, value: str) -> str:
        # For env vault, we store in memory and return an env-style reference
        var_name = key.upper().replace("/", "_").replace("-", "_")
        os.environ[var_name] = value
        return f"env://{var_name}"


def get_vault(project_id: str | None = None) -> VaultInterface:
    """Factory: return the appropriate vault for the current environment.

    If ``project_id`` is provided, a :class:`SecretManagerVault` skeleton is
    returned. Otherwise, :class:`LocalVault` is used.
    """
    if project_id:
        return SecretManagerVault(project_id=project_id)
    return LocalVault()
