"""
app.erc8004.tba
~~~~~~~~~~~~~~~
ERC-6551 Token Bound Account (TBA) for agent NFTs.

ERC-6551 enables every ERC-721 NFT to own a smart contract wallet.
When an agent is registered on the ERC-8004 Identity Registry (which
mints an NFT), that NFT can have a TBA created for it. The TBA can:

  - Hold ETH and ERC-20 tokens (receive bounty payments)
  - Own other NFTs (sub-agent identities)
  - Execute arbitrary transactions (via the agent operator)
  - Accumulate on-chain reputation tokens

Contract addresses (Sepolia Testnet):
  ERC-6551 Registry: 0x000000006551c19487814612e58FE06813775758
  (canonical across all EVM chains per the EIP)

Configuration:
  ERC6551_IMPLEMENTATION: TBA implementation contract address
  ERC6551_DRY_RUN:       Log but don't submit (default: true)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ERC-6551 Registry (canonical address, same on all EVM chains)
ERC6551_REGISTRY = "0x000000006551c19487814612e58FE06813775758"

# TBA implementation contract (deploy your own or use a standard one)
ERC6551_IMPLEMENTATION = os.environ.get(
    "ERC6551_IMPLEMENTATION",
    "0x55266d75D1a14E4572138116aF39863Ed6596E7F",  # Reference impl on Sepolia
)

CHAIN_ID = int(os.environ.get("ERC6551_CHAIN_ID", "11155111"))

SEPOLIA_RPC_URL = os.environ.get(
    "ERC6551_RPC_URL",
    os.environ.get("SEPOLIA_RPC_URL", ""),
)

OPERATOR_PRIVATE_KEY: str | None = None
_SECRET_PATH = "/run/secrets/erc6551_operator_key"
if os.path.isfile(_SECRET_PATH):
    OPERATOR_PRIVATE_KEY = open(_SECRET_PATH).read().strip()  # noqa: SIM115
elif os.environ.get("ERC6551_OPERATOR_KEY"):
    OPERATOR_PRIVATE_KEY = os.environ["ERC6551_OPERATOR_KEY"]

DRY_RUN = os.environ.get("ERC6551_DRY_RUN", "true").lower() == "true"

# Minimal ABI for the ERC-6551 Registry
REGISTRY_ABI = [
    {
        "type": "function",
        "name": "createAccount",
        "inputs": [
            {"name": "implementation", "type": "address"},
            {"name": "salt", "type": "bytes32"},
            {"name": "chainId", "type": "uint256"},
            {"name": "tokenContract", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
        ],
        "outputs": [{"name": "account", "type": "address"}],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "account",
        "inputs": [
            {"name": "implementation", "type": "address"},
            {"name": "salt", "type": "bytes32"},
            {"name": "chainId", "type": "uint256"},
            {"name": "tokenContract", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
    },
]


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def compute_tba_address(
    token_contract: str,
    token_id: int,
    *,
    salt: bytes = bytes(32),
    implementation: str = ERC6551_IMPLEMENTATION,
    chain_id: int = CHAIN_ID,
) -> str | None:
    """Compute the deterministic TBA address for an NFT (off-chain).

    The address is deterministic based on the ERC-6551 CREATE2 formula:
    registry + implementation + salt + chainId + tokenContract + tokenId.

    Returns:
        The checksummed TBA address, or None if web3 is unavailable.
    """
    if not SEPOLIA_RPC_URL:
        logger.debug("No RPC configured, cannot compute TBA address on-chain")
        return None

    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
        registry = w3.eth.contract(
            address=Web3.to_checksum_address(ERC6551_REGISTRY),
            abi=REGISTRY_ABI,
        )

        return registry.functions.account(
            Web3.to_checksum_address(implementation),
            salt,
            chain_id,
            Web3.to_checksum_address(token_contract),
            token_id,
        ).call()
    except Exception as exc:
        logger.warning(
            "Failed to compute TBA address",
            extra={
                "token_contract": token_contract,
                "token_id": token_id,
                "error": str(exc),
            },
        )
        return None


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


async def create_tba(
    token_contract: str,
    token_id: int,
    *,
    salt: bytes = bytes(32),
    implementation: str = ERC6551_IMPLEMENTATION,
) -> dict[str, Any]:
    """Create an ERC-6551 Token Bound Account for an agent NFT.

    Calls the canonical ERC-6551 Registry's createAccount function.
    The resulting address is deterministic — calling this again with
    the same params returns the same address (idempotent).

    Args:
        token_contract: ERC-8004 Identity Registry address (NFT contract).
        token_id: The agent's ERC-8004 agentId (NFT token ID).
        salt: Optional salt for address derivation (default: zero).
        implementation: TBA implementation contract address.

    Returns:
        Dict with tba_address, tx_hash, status.
    """
    result: dict[str, Any] = {
        "token_contract": token_contract,
        "token_id": token_id,
        "chain_id": CHAIN_ID,
        "registry": ERC6551_REGISTRY,
        "implementation": implementation,
    }

    if DRY_RUN:
        # Compute a deterministic placeholder address for dry-run
        import hashlib

        addr_hash = hashlib.sha256(
            f"{token_contract}:{token_id}:{CHAIN_ID}".encode()
        ).hexdigest()[:40]
        result["tba_address"] = f"0x{addr_hash}"
        result["status"] = "dry_run"
        logger.info(
            "ERC-6551 TBA create (dry-run)",
            extra={
                "token_id": token_id,
                "tba_address": result["tba_address"],
            },
        )
        return result

    if not SEPOLIA_RPC_URL:
        result["status"] = "no_rpc"
        return result

    if not OPERATOR_PRIVATE_KEY:
        result["status"] = "no_key"
        return result

    try:
        from eth_account import Account
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
        registry = w3.eth.contract(
            address=Web3.to_checksum_address(ERC6551_REGISTRY),
            abi=REGISTRY_ABI,
        )

        account = Account.from_key(OPERATOR_PRIVATE_KEY)
        sender = account.address

        tx = registry.functions.createAccount(
            Web3.to_checksum_address(implementation),
            salt,
            CHAIN_ID,
            Web3.to_checksum_address(token_contract),
            token_id,
        ).build_transaction(
            {
                "from": sender,
                "nonce": w3.eth.get_transaction_count(sender),
                "gasPrice": w3.eth.gas_price,
                "chainId": CHAIN_ID,
            }
        )

        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        # The TBA address is deterministic — read it from the registry
        tba_address = registry.functions.account(
            Web3.to_checksum_address(implementation),
            salt,
            CHAIN_ID,
            Web3.to_checksum_address(token_contract),
            token_id,
        ).call()

        result["tba_address"] = tba_address
        result["tx_hash"] = tx_hash.hex()
        result["block_number"] = tx_receipt["blockNumber"]
        result["gas_used"] = tx_receipt["gasUsed"]
        result["status"] = "confirmed" if tx_receipt["status"] == 1 else "failed"

        logger.info(
            "ERC-6551 TBA created on-chain",
            extra={
                "token_id": token_id,
                "tba_address": tba_address,
                "tx_hash": tx_hash.hex(),
            },
        )
        return result

    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        logger.error(
            "ERC-6551 TBA creation failed",
            extra={"token_id": token_id, "error": str(exc)},
        )
        return result


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------


async def ensure_agent_tba(
    agent: dict[str, Any],
    identity_registry: str,
) -> dict[str, Any]:
    """Ensure an agent's ERC-8004 NFT has a Token Bound Account.

    If the agent has an erc8004_agent_id, creates a TBA for it.
    Returns the TBA info including the deterministic address.
    """
    agent_id = agent.get("erc8004_agent_id")
    if agent_id is None:
        return {
            "status": "skip",
            "reason": "Agent has no on-chain identity (erc8004_agent_id is None)",
        }

    return await create_tba(
        token_contract=identity_registry,
        token_id=agent_id,
    )
