"""
app.adapters.local_cli
~~~~~~~~~~~~~~~~~~~~~~
Adapter for executing local CLI commands (GWI, etc.) as Moat capabilities.

Runs whitelisted commands via asyncio subprocess with strict timeouts.
Only commands matching registered capability templates are allowed —
arbitrary shell execution is blocked.

Security model
--------------
- Commands are NOT passed through a shell; we use create_subprocess_exec()
  with explicit argument lists to prevent injection.
- Each capability maps to a fixed command template; only the parameterised
  parts (e.g. PR URL) are substituted.
- Credentials are injected as environment variables, never as CLI arguments.
- stdout/stderr are captured and returned; raw credential values are never
  included in the output.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

from app.adapters.base import AdapterInterface

logger = logging.getLogger(__name__)

# Default timeout for subprocess execution (seconds)
_DEFAULT_TIMEOUT_S = 120

# Maximum output size to capture (bytes) — prevents OOM from runaway commands
_MAX_OUTPUT_BYTES = 1_048_576  # 1 MB

# Allowlisted URL patterns for parameter validation
_GITHUB_URL_RE = re.compile(
    r"^https://github\.com/[\w.\-]+/[\w.\-]+/(pull|issues)/\d+$"
)

# Command templates per capability.
# {url} is the only substitutable parameter; everything else is fixed.
_COMMAND_TEMPLATES: dict[str, list[str]] = {
    "gwi.triage": ["node", "apps/cli/dist/index.js", "triage", "{url}"],
    "gwi.review": ["node", "apps/cli/dist/index.js", "review", "{url}"],
    "gwi.issue-to-code": ["node", "apps/cli/dist/index.js", "issue-to-code", "{url}"],
    "gwi.resolve": ["node", "apps/cli/dist/index.js", "resolve", "{url}"],
}

# Working directory for GWI commands
_GWI_WORKDIR = os.environ.get(
    "GWI_PROJECT_DIR", "/home/jeremy/000-projects/git-with-intent"
)


class LocalCLIAdapter(AdapterInterface):
    """Adapter for executing local CLI commands as Moat capabilities.

    Provider name: ``"local-cli"``

    Only executes commands from the pre-defined command template registry.
    Parameters are validated before substitution. No shell expansion occurs.
    """

    @property
    def provider_name(self) -> str:
        return "local-cli"

    async def execute(
        self,
        capability_id: str,
        capability_name: str,
        params: dict[str, Any],
        credential: str | None,
    ) -> dict[str, Any]:
        """Execute a local CLI command for the given capability.

        Parameters
        ----------
        capability_id:
            Must match a key in ``_COMMAND_TEMPLATES``.
        capability_name:
            Human-readable name for logging.
        params:
            Must include ``url`` for GWI commands.
            URL is validated against GitHub URL pattern.
        credential:
            If provided, injected as env vars (not CLI args).

        Returns
        -------
        dict
            Result with stdout, stderr, exit_code, and execution metadata.

        Raises
        ------
        RuntimeError
            If the capability has no template, params are invalid,
            or the command times out.
        """
        # 1. Look up command template (by UUID first, then by name)
        template = _COMMAND_TEMPLATES.get(capability_id)
        if template is None:
            template = _COMMAND_TEMPLATES.get(capability_name)
        if template is None:
            raise RuntimeError(
                f"No command template registered for capability '{capability_id}' "
                f"(name='{capability_name}'). "
                f"Registered: {list(_COMMAND_TEMPLATES.keys())}"
            )

        # 2. Validate and substitute parameters
        url = params.get("url", "")
        if "{url}" in str(template):
            if not url:
                raise RuntimeError(
                    f"Parameter 'url' is required for capability '{capability_id}'"
                )
            if not _GITHUB_URL_RE.match(url):
                raise RuntimeError(
                    f"Invalid URL format: '{url}'. "
                    f"Must match pattern: https://github.com/owner/repo/(pull|issues)/number"
                )

        # Build the actual command (no shell, explicit args)
        cmd = [arg.replace("{url}", url) if "{url}" in arg else arg for arg in template]

        # 3. Set up environment (inject credentials as env vars, not CLI args)
        env = os.environ.copy()
        if credential:
            env["MOAT_INJECTED_CREDENTIAL"] = credential

        timeout = params.get("timeout", _DEFAULT_TIMEOUT_S)

        logger.info(
            "LocalCLIAdapter executing",
            extra={
                "capability_id": capability_id,
                "cmd_program": cmd[0],
                "cmd_args_count": len(cmd) - 1,
                "has_credential": credential is not None,
                "timeout_s": timeout,
                # URL is logged for audit; credentials are NOT
            },
        )

        # 4. Execute via asyncio subprocess (no shell!)
        start = datetime.now(UTC)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=_GWI_WORKDIR,
                env=env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            # Kill the process on timeout
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            raise RuntimeError(
                f"Command timed out after {timeout}s for capability '{capability_id}'"
            ) from None

        end = datetime.now(UTC)
        latency_ms = (end - start).total_seconds() * 1000

        # 5. Truncate output if too large
        stdout = stdout_bytes[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        stderr = stderr_bytes[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")

        exit_code = proc.returncode or 0

        logger.info(
            "LocalCLIAdapter completed",
            extra={
                "capability_id": capability_id,
                "exit_code": exit_code,
                "stdout_len": len(stdout),
                "stderr_len": len(stderr),
                "latency_ms": round(latency_ms, 1),
            },
        )

        if exit_code != 0:
            raise RuntimeError(
                f"Command failed (exit {exit_code}) for '{capability_id}': "
                f"{stderr[:500] if stderr else 'no stderr'}"
            )

        return {
            "status": "success",
            "capability_id": capability_id,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr if stderr else None,
            "latency_ms": round(latency_ms, 1),
            "executed_at": end.isoformat(),
        }
