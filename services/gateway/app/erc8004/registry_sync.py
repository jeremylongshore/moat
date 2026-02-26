"""
app.erc8004.registry_sync
~~~~~~~~~~~~~~~~~~~~~~~~~
Sync agent identity between Moat's control-plane DB and the
ERC-8004 Identity Registry on-chain.

Operations:
  - register_agent: Call register(agentURI) → mint NFT → get agentId
  - update_agent_uri: Update agentURI on-chain for existing agent
  - read_agent_onchain: Read agent info from on-chain registry
  - sync_agent_to_chain: Full sync from control-plane → on-chain

Contract addresses (Sepolia Testnet):
  Identity Registry:  0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c
  Reputation Registry: (TBD — Phase 2)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ERC-8004 Identity Registry on Sepolia
IDENTITY_REGISTRY_ADDRESS = os.environ.get(
    "ERC8004_IDENTITY_REGISTRY",
    "0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
)

CHAIN_ID = int(os.environ.get("ERC8004_CHAIN_ID", "11155111"))

SEPOLIA_RPC_URL = os.environ.get(
    "ERC8004_RPC_URL",
    os.environ.get("SEPOLIA_RPC_URL", ""),
)

# Operator key for on-chain transactions
OPERATOR_PRIVATE_KEY: str | None = None
_SECRET_PATH = "/run/secrets/erc8004_operator_key"
if os.path.isfile(_SECRET_PATH):
    OPERATOR_PRIVATE_KEY = open(_SECRET_PATH).read().strip()  # noqa: SIM115
elif os.environ.get("ERC8004_OPERATOR_KEY"):
    OPERATOR_PRIVATE_KEY = os.environ["ERC8004_OPERATOR_KEY"]

# Dry-run mode: log but don't submit on-chain
DRY_RUN = os.environ.get("ERC8004_DRY_RUN", "true").lower() == "true"

# Minimal ABI for the ERC-8004 Identity Registry
IDENTITY_REGISTRY_ABI = [
    {
        "type": "function",
        "name": "register",
        "inputs": [{"name": "agentURI", "type": "string"}],
        "outputs": [{"name": "agentId", "type": "uint256"}],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "updateAgentURI",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "newAgentURI", "type": "string"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "agentURI",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "ownerOf",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
    },
    {
        "type": "event",
        "name": "AgentRegistered",
        "inputs": [
            {"name": "agentId", "type": "uint256", "indexed": True},
            {"name": "owner", "type": "address", "indexed": True},
            {"name": "agentURI", "type": "string", "indexed": False},
        ],
        "anonymous": False,
    },
]


# ---------------------------------------------------------------------------
# On-chain read operations (no signing required)
# ---------------------------------------------------------------------------


async def read_agent_uri(agent_id: int) -> str | None:
    """Read agentURI from the on-chain Identity Registry.

    Returns the URI string, or None if the agent doesn't exist or
    RPC is unavailable.
    """
    if not SEPOLIA_RPC_URL:
        logger.debug("No RPC URL configured, cannot read on-chain agent URI")
        return None

    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(IDENTITY_REGISTRY_ADDRESS),
            abi=IDENTITY_REGISTRY_ABI,
        )
        return contract.functions.agentURI(agent_id).call()
    except Exception as exc:
        logger.warning(
            "Failed to read agent URI from chain",
            extra={"agent_id": agent_id, "error": str(exc)},
        )
        return None


async def read_agent_owner(agent_id: int) -> str | None:
    """Read the owner address of an on-chain agent NFT."""
    if not SEPOLIA_RPC_URL:
        return None

    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(IDENTITY_REGISTRY_ADDRESS),
            abi=IDENTITY_REGISTRY_ABI,
        )
        return contract.functions.ownerOf(agent_id).call()
    except Exception as exc:
        logger.warning(
            "Failed to read agent owner from chain",
            extra={"agent_id": agent_id, "error": str(exc)},
        )
        return None


# ---------------------------------------------------------------------------
# On-chain write operations (signing required)
# ---------------------------------------------------------------------------


async def register_agent(agent_uri: str) -> dict[str, Any]:
    """Register a new agent on the ERC-8004 Identity Registry.

    Calls register(agentURI) which mints an ERC-721 NFT and returns
    the new agentId.

    Returns:
        Dict with agent_id, tx_hash, block_number, status.
    """
    result: dict[str, Any] = {
        "agent_uri": agent_uri,
        "chain_id": CHAIN_ID,
        "registry": IDENTITY_REGISTRY_ADDRESS,
    }

    if DRY_RUN:
        result["status"] = "dry_run"
        result["agent_id"] = None
        logger.info(
            "ERC-8004 register (dry-run)",
            extra={"agent_uri": agent_uri},
        )
        return result

    if not SEPOLIA_RPC_URL:
        result["status"] = "no_rpc"
        logger.warning("No RPC URL — cannot register agent on-chain")
        return result

    if not OPERATOR_PRIVATE_KEY:
        result["status"] = "no_key"
        logger.warning("No operator key — cannot register agent on-chain")
        return result

    try:
        from eth_account import Account
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(IDENTITY_REGISTRY_ADDRESS),
            abi=IDENTITY_REGISTRY_ABI,
        )

        account = Account.from_key(OPERATOR_PRIVATE_KEY)
        sender = account.address

        tx = contract.functions.register(agent_uri).build_transaction(
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

        # Parse AgentRegistered event for the agentId
        agent_id = None
        logs = contract.events.AgentRegistered().process_receipt(tx_receipt)
        if logs:
            agent_id = logs[0]["args"]["agentId"]

        result["status"] = "confirmed" if tx_receipt["status"] == 1 else "failed"
        result["agent_id"] = agent_id
        result["tx_hash"] = tx_hash.hex()
        result["block_number"] = tx_receipt["blockNumber"]
        result["gas_used"] = tx_receipt["gasUsed"]

        logger.info(
            "ERC-8004 agent registered on-chain",
            extra={
                "agent_id": agent_id,
                "tx_hash": tx_hash.hex(),
                "block": tx_receipt["blockNumber"],
            },
        )
        return result

    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        logger.error(
            "ERC-8004 registration failed",
            extra={"agent_uri": agent_uri, "error": str(exc)},
        )
        return result


async def update_agent_uri(agent_id: int, new_uri: str) -> dict[str, Any]:
    """Update the agentURI for an existing on-chain agent.

    Returns:
        Dict with status, tx_hash, block_number.
    """
    result: dict[str, Any] = {
        "agent_id": agent_id,
        "new_uri": new_uri,
        "chain_id": CHAIN_ID,
    }

    if DRY_RUN:
        result["status"] = "dry_run"
        logger.info(
            "ERC-8004 updateAgentURI (dry-run)",
            extra={"agent_id": agent_id, "new_uri": new_uri},
        )
        return result

    if not SEPOLIA_RPC_URL or not OPERATOR_PRIVATE_KEY:
        result["status"] = "no_rpc" if not SEPOLIA_RPC_URL else "no_key"
        return result

    try:
        from eth_account import Account
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(IDENTITY_REGISTRY_ADDRESS),
            abi=IDENTITY_REGISTRY_ABI,
        )

        account = Account.from_key(OPERATOR_PRIVATE_KEY)
        sender = account.address

        tx = contract.functions.updateAgentURI(agent_id, new_uri).build_transaction(
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

        result["status"] = "confirmed" if tx_receipt["status"] == 1 else "failed"
        result["tx_hash"] = tx_hash.hex()
        result["block_number"] = tx_receipt["blockNumber"]

        logger.info(
            "ERC-8004 agentURI updated on-chain",
            extra={"agent_id": agent_id, "tx_hash": tx_hash.hex()},
        )
        return result

    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        logger.error(
            "ERC-8004 URI update failed",
            extra={"agent_id": agent_id, "error": str(exc)},
        )
        return result


# ---------------------------------------------------------------------------
# High-level sync
# ---------------------------------------------------------------------------


async def sync_agent_to_chain(
    agent: dict[str, Any],
    base_url: str = "",
) -> dict[str, Any]:
    """Sync an agent from the control-plane DB to on-chain ERC-8004.

    If the agent has no on-chain identity (erc8004_agent_id is None),
    registers it. If it already has one, checks and updates the URI
    if needed.

    Args:
        agent: Agent dict from AgentRow.to_dict().
        base_url: Base URL for the agent's metadata endpoint
                  (e.g. "https://moat.dev").

    Returns:
        Dict with sync action taken and result.
    """
    from app.erc8004.metadata import build_agent_metadata

    agent_name = agent.get("name", "unknown")
    erc8004_id = agent.get("erc8004_agent_id")

    # Build the metadata JSON that the agentURI will point to
    metadata = build_agent_metadata(
        agent,
        chain_id=CHAIN_ID,
        registry_address=IDENTITY_REGISTRY_ADDRESS,
    )

    # The agentURI that will be stored on-chain
    agent_uri = agent.get("erc8004_agent_uri") or ""
    if not agent_uri and base_url:
        agent_uri = f"{base_url}/.well-known/agents/{agent_name}.json"

    if erc8004_id is None:
        # New agent — register on-chain
        if not agent_uri:
            return {
                "action": "skip",
                "reason": "no agent_uri configured",
                "agent_name": agent_name,
            }

        reg_result = await register_agent(agent_uri)
        return {
            "action": "register",
            "agent_name": agent_name,
            "agent_uri": agent_uri,
            "metadata": metadata,
            **reg_result,
        }

    # Existing agent — check if URI needs updating
    current_uri = await read_agent_uri(erc8004_id)
    if current_uri and current_uri == agent_uri:
        return {
            "action": "noop",
            "agent_name": agent_name,
            "agent_id": erc8004_id,
            "reason": "URI already matches on-chain",
        }

    if agent_uri:
        update_result = await update_agent_uri(erc8004_id, agent_uri)
        return {
            "action": "update_uri",
            "agent_name": agent_name,
            "agent_id": erc8004_id,
            "old_uri": current_uri,
            "new_uri": agent_uri,
            "metadata": metadata,
            **update_result,
        }

    return {
        "action": "noop",
        "agent_name": agent_name,
        "agent_id": erc8004_id,
        "reason": "no new URI to set",
    }
