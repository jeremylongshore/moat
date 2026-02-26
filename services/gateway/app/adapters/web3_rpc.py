"""
app.adapters.web3_rpc
~~~~~~~~~~~~~~~~~~~~~
Web3 JSON-RPC adapter for smart contract reads and writes.

Enables Moat-governed agents to interact with on-chain contracts through
the same policy-enforced gateway pipeline as all other capabilities.

Capabilities:
    - ``contract.read``  — eth_call for view/pure functions (no gas, no signing)
    - ``contract.write`` — eth_sendTransaction for state-changing functions

Security:
    - Domain allowlist for RPC endpoints (same pattern as HttpProxyAdapter)
    - Private IP blocking
    - Gas limit enforcement on writes
    - Credential-based signing (private key from vault, never logged)

Setup::

    WEB3_RPC_DOMAIN_ALLOWLIST=sepolia.infura.io,eth-mainnet.g.alchemy.com

Execute::

    curl -X POST http://localhost:8002/execute/contract.read \\
        -H "Content-Type: application/json" \\
        -d '{
            "tenant_id": "automaton",
            "scope": "execute",
            "params": {
                "rpc_url": "https://sepolia.infura.io/v3/...",
                "to": "0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
                "data": "0x...",
                "chain_id": 11155111
            }
        }'
"""

from __future__ import annotations

import logging
from typing import Any

from app.adapters.base import AdapterInterface
from app.adapters.network_utils import is_private_ip, parse_domain_allowlist

logger = logging.getLogger(__name__)

_DEFAULT_GAS_LIMIT = 500_000
_MAX_GAS_LIMIT = 3_000_000
_DEFAULT_CHAIN_ID = 11155111  # Sepolia

_WEB3_RPC_DEFAULT_ALLOWLIST = (
    "eth-sepolia.g.alchemy.com,"
    "base-sepolia.g.alchemy.com,"
    "eth-mainnet.g.alchemy.com,"
    "base-mainnet.g.alchemy.com,"
    "polygon-mainnet.g.alchemy.com,"
    "arb-mainnet.g.alchemy.com,"
    "opt-mainnet.g.alchemy.com,"
    "sepolia.infura.io,"
    "api.thegraph.com"
)


def _get_rpc_domain_allowlist() -> set[str]:
    """Parse the RPC domain allowlist from the environment."""
    return parse_domain_allowlist(
        "WEB3_RPC_DOMAIN_ALLOWLIST", _WEB3_RPC_DEFAULT_ALLOWLIST
    )


def _validate_rpc_url(rpc_url: str, allowlist: set[str]) -> str:
    """Validate RPC URL against domain allowlist and security rules."""
    from urllib.parse import urlparse

    parsed = urlparse(rpc_url)

    if parsed.scheme not in ("https", "http"):
        raise RuntimeError(f"Unsupported RPC scheme: {parsed.scheme!r}. Use HTTPS.")

    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"):
        raise RuntimeError("HTTP is not allowed for external RPC endpoints. Use HTTPS.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise RuntimeError("RPC URL has no hostname.")

    if is_private_ip(hostname):
        raise RuntimeError(
            f"RPC requests to private/internal addresses are blocked: {hostname}"
        )

    if hostname not in allowlist:
        raise RuntimeError(
            f"RPC domain {hostname!r} is not in the allowlist. "
            f"Allowed: {sorted(allowlist)}"
        )

    return rpc_url


class Web3Adapter(AdapterInterface):
    """Execute smart contract calls via JSON-RPC.

    Reuses web3.py for RPC communication. Applies the same domain allowlist
    and private IP blocking pattern as HttpProxyAdapter.

    Provider name: ``"web3"``

    Expected ``params`` keys:

    - ``rpc_url`` (str, required): JSON-RPC endpoint URL (must be on allowlist).
    - ``to`` (str, required): Contract address (0x-prefixed, checksummed).
    - ``data`` (str): ABI-encoded calldata (0x-prefixed hex).
    - ``method`` (str): ``"eth_call"`` (read) or
      ``"eth_sendTransaction"`` (write). Default: eth_call.
    - ``abi`` (list): Contract ABI for decode (optional).
    - ``function_name`` (str): Function name to decode (needs abi).
    - ``function_args`` (list): Args for ABI encoding (needs abi).
    - ``value`` (int): Value in wei to send (writes only, default 0).
    - ``gas_limit`` (int): Gas limit for writes (default 500k, max 3M).
    - ``chain_id`` (int): Chain ID (default 11155111 = Sepolia).
    """

    @property
    def provider_name(self) -> str:
        return "web3"

    async def execute(
        self,
        capability_id: str,
        capability_name: str,
        params: dict[str, Any],
        credential: str | None,
    ) -> dict[str, Any]:
        """Execute a contract read or write via JSON-RPC."""
        from web3 import Web3

        rpc_url = params.get("rpc_url")
        if not rpc_url or not isinstance(rpc_url, str):
            raise RuntimeError("Web3Adapter requires 'rpc_url' (string) in params.")

        to_address = params.get("to")
        if not to_address or not isinstance(to_address, str):
            raise RuntimeError(
                "Web3Adapter requires 'to' (contract address) in params."
            )

        # Validate RPC URL domain
        allowlist = _get_rpc_domain_allowlist()
        rpc_url = _validate_rpc_url(rpc_url, allowlist)

        method = params.get("method", "eth_call")
        chain_id = params.get("chain_id", _DEFAULT_CHAIN_ID)
        abi = params.get("abi")
        function_name = params.get("function_name")
        function_args = params.get("function_args", [])
        data = params.get("data", "0x")
        value = params.get("value", 0)
        gas_limit = min(params.get("gas_limit", _DEFAULT_GAS_LIMIT), _MAX_GAS_LIMIT)

        logger.info(
            "Web3 RPC request",
            extra={
                "capability_id": capability_id,
                "method": method,
                "to": to_address,
                "chain_id": chain_id,
                "rpc_domain": rpc_url.split("/")[2] if "/" in rpc_url else "unknown",
            },
        )

        w3 = Web3(Web3.HTTPProvider(rpc_url))
        to_checksum = Web3.to_checksum_address(to_address)

        # Build calldata from ABI if provided
        if abi and function_name:
            contract = w3.eth.contract(address=to_checksum, abi=abi)
            fn = contract.functions[function_name](*function_args)
            data = fn._encode_transaction_data()

        if method == "eth_call":
            return await self._do_read(
                w3, to_checksum, data, abi, function_name, chain_id
            )
        if method == "eth_sendTransaction":
            return await self._do_write(
                w3,
                to_checksum,
                data,
                credential,
                value,
                gas_limit,
                chain_id,
                abi,
                function_name,
            )
        raise RuntimeError(
            f"Unsupported method: {method!r}. Use 'eth_call' or 'eth_sendTransaction'."
        )

    async def _do_read(
        self,
        w3: Any,
        to_address: str,
        data: str,
        abi: list[dict[str, Any]] | None,
        function_name: str | None,
        chain_id: int,
    ) -> dict[str, Any]:
        """Execute a read-only eth_call."""

        result = w3.eth.call({"to": to_address, "data": data})
        block = w3.eth.block_number

        response: dict[str, Any] = {
            "result": "0x" + result.hex() if isinstance(result, bytes) else str(result),
            "block_number": block,
            "chain_id": chain_id,
        }

        # Decode if ABI provided
        if abi and function_name:
            try:
                contract = w3.eth.contract(address=to_address, abi=abi)
                decoded = contract.functions[function_name]().call()
                response["decoded_result"] = _serialize_web3_result(decoded)
            except Exception as exc:
                logger.warning("Failed to decode result", extra={"error": str(exc)})

        logger.info(
            "Web3 read complete",
            extra={"to": to_address, "block": block, "chain_id": chain_id},
        )
        return response

    async def _do_write(
        self,
        w3: Any,
        to_address: str,
        data: str,
        credential: str | None,
        value: int,
        gas_limit: int,
        chain_id: int,
        abi: list[dict[str, Any]] | None,
        function_name: str | None,
    ) -> dict[str, Any]:
        """Execute a state-changing eth_sendTransaction."""
        from eth_account import Account

        if not credential:
            raise RuntimeError(
                "Web3 write transactions require a signing credential (private key)."
            )

        account = Account.from_key(credential)
        sender = account.address

        tx: dict[str, Any] = {
            "from": sender,
            "to": to_address,
            "data": data,
            "value": value,
            "gas": gas_limit,
            "nonce": w3.eth.get_transaction_count(sender),
            "chainId": chain_id,
            "gasPrice": w3.eth.gas_price,
        }

        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

        logger.info(
            "Web3 tx broadcast",
            extra={
                "tx_hash": tx_hash.hex(),
                "sender": sender,
                "to": to_address,
                "chain_id": chain_id,
            },
        )

        # Wait for confirmation
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        response: dict[str, Any] = {
            "tx_hash": tx_hash.hex(),
            "block_number": receipt["blockNumber"],
            "gas_used": receipt["gasUsed"],
            "status": "confirmed" if receipt["status"] == 1 else "failed",
            "chain_id": chain_id,
        }

        logger.info(
            "Web3 tx confirmed",
            extra={
                "tx_hash": tx_hash.hex(),
                "block": receipt["blockNumber"],
                "gas_used": receipt["gasUsed"],
                "status": response["status"],
            },
        )
        return response


def _serialize_web3_result(val: Any) -> Any:
    """Convert web3.py return types to JSON-serializable values."""
    if isinstance(val, bytes):
        return "0x" + val.hex()
    if isinstance(val, (list, tuple)):
        return [_serialize_web3_result(v) for v in val]
    if isinstance(val, dict):
        return {k: _serialize_web3_result(v) for k, v in val.items()}
    return val
