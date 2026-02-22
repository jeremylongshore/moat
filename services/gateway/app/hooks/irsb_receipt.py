"""
app.hooks.irsb_receipt
~~~~~~~~~~~~~~~~~~~~~~
Post-execution hook that submits IRSB receipts on-chain after every
successful Moat capability execution.

Architecture
------------
Every Moat execution produces two audit records:

1. **Moat Receipt** (off-chain) — created by the gateway pipeline in execute.py
2. **IRSB IntentReceipt** (on-chain) — submitted by this hook to Sepolia

Both share the same intentId, enabling cross-reference between the off-chain
audit log and the on-chain proof.

Intent ID computation (PLACEHOLDER)
------------------------------------
The intentId below is NOT a Canonical Intent Envelope (CIE) per 041-AT-SPEC.
When IRSB Phase 1 (CIE) is built, this becomes a proper EIP-712 struct hash
over all 12 CIE fields with CIE_TYPEHASH. For now, a deterministic hash
that uniquely identifies this action.

The placeholder maps to the same ``intentHash`` field in IntentReceipt on-chain,
so upgrading is a hash computation change, not a schema change.

Signing
-------
MVP: Raw key signing via eth_account (key from env var or Docker secret).
Production: Cloud KMS via @irsb/kms-signer (no private keys in memory).

Contract addresses (Sepolia Testnet)
-------------------------------------
IntentReceiptHub: 0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c
SolverRegistry:   0xB6ab964832808E49635fF82D1996D6a888ecB745
ERC-8004 Agent:   #1319 (intent-scout-001)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INTENT_RECEIPT_HUB = "0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c"
SOLVER_ADDRESS = "0x83Be08FFB22b61733eDf15b0ee9Caf5562cd888d"
CHAIN_ID = 11155111  # Sepolia

SEPOLIA_RPC_URL = os.environ.get(
    "IRSB_RPC_URL",
    os.environ.get("SEPOLIA_RPC_URL", ""),
)

# Dry-run mode: log receipt but don't submit on-chain.
# Set IRSB_DRY_RUN=false when signing key is configured.
DRY_RUN = os.environ.get("IRSB_DRY_RUN", "true").lower() == "true"

# Solver private key for signing receipts (MVP — production uses Cloud KMS).
# Read from Docker secret file first, fall back to env var.
_SECRET_PATH = "/run/secrets/scout_private_key"
SOLVER_PRIVATE_KEY: str | None = None
if os.path.isfile(_SECRET_PATH):
    SOLVER_PRIVATE_KEY = open(_SECRET_PATH).read().strip()  # noqa: SIM115
elif os.environ.get("IRSB_SOLVER_KEY"):
    SOLVER_PRIVATE_KEY = os.environ["IRSB_SOLVER_KEY"]

# Minimal ABI — only the functions we call.
RECEIPT_HUB_ABI = [
    {
        "type": "function",
        "name": "postReceipt",
        "inputs": [
            {
                "name": "receipt",
                "type": "tuple",
                "components": [
                    {"name": "intentHash", "type": "bytes32"},
                    {"name": "constraintsHash", "type": "bytes32"},
                    {"name": "routeHash", "type": "bytes32"},
                    {"name": "outcomeHash", "type": "bytes32"},
                    {"name": "evidenceHash", "type": "bytes32"},
                    {"name": "createdAt", "type": "uint64"},
                    {"name": "expiry", "type": "uint64"},
                    {"name": "solverId", "type": "bytes32"},
                    {"name": "solverSig", "type": "bytes"},
                ],
            },
            {"name": "declaredVolume", "type": "uint256"},
        ],
        "outputs": [{"name": "receiptId", "type": "bytes32"}],
        "stateMutability": "nonpayable",
    },
    {
        "type": "function",
        "name": "solverNonces",
        "inputs": [{"name": "", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
    {
        "type": "event",
        "name": "ReceiptPosted",
        "inputs": [
            {"name": "receiptId", "type": "bytes32", "indexed": True},
            {"name": "intentHash", "type": "bytes32", "indexed": True},
            {"name": "solverId", "type": "bytes32", "indexed": True},
            {"name": "expiry", "type": "uint64", "indexed": False},
        ],
        "anonymous": False,
    },
]


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------


def _keccak256(data: bytes) -> bytes:
    """Keccak-256 hash using web3.py's implementation."""
    from web3 import Web3

    return Web3.keccak(data)


def _to_bytes32(hex_str: str) -> bytes:
    """Convert a 0x-prefixed hex string to 32-byte padding."""
    raw = bytes.fromhex(hex_str.removeprefix("0x"))
    return raw.rjust(32, b"\x00")


def _sha256_hex(data: str) -> str:
    """SHA-256 hash returning 0x-prefixed hex."""
    return "0x" + hashlib.sha256(data.encode()).hexdigest()


def compute_intent_hash(
    capability_id: str,
    input_hash: str,
    tenant_id: str,
    timestamp: str,
) -> bytes:
    """Compute a PLACEHOLDER intentId for the IRSB receipt.

    This is NOT a Canonical Intent Envelope intentId per 041-AT-SPEC.
    Real CIE computation requires:
        intentId = keccak256(abi.encode(CIE_TYPEHASH, version, tenantId,
            agentAddress, agentId, domain, actionHash, constraintsHash,
            nonce, timestamp, expiry, extensionHash))

    For now, a deterministic keccak256 hash that uniquely identifies this action.
    When IRSB Phase 1 (CIE) is built, swap this computation only.
    """
    preimage = f"{capability_id}:{input_hash}:{tenant_id}:{timestamp}"
    return _keccak256(preimage.encode())


def compute_result_hash(receipt: dict[str, Any]) -> bytes:
    """Compute keccak256 of the execution result."""
    result_str = json.dumps(receipt.get("result", {}), sort_keys=True)
    return _keccak256(result_str.encode())


def compute_constraints_hash(receipt: dict[str, Any]) -> bytes:
    """Hash the policy constraints that governed this execution."""
    constraints = {
        "capability_id": receipt.get("capability_id", ""),
        "scope": receipt.get("scope", "execute"),
        "tenant_id": receipt.get("tenant_id", ""),
    }
    return _keccak256(json.dumps(constraints, sort_keys=True).encode())


def compute_route_hash(receipt: dict[str, Any]) -> bytes:
    """Hash the execution route (adapter + capability)."""
    route = {
        "adapter": receipt.get("adapter", "unknown"),
        "capability_id": receipt.get("capability_id", ""),
    }
    return _keccak256(json.dumps(route, sort_keys=True).encode())


def compute_evidence_hash(receipt: dict[str, Any]) -> bytes:
    """Hash the evidence bundle (full Moat receipt for audit)."""
    # The entire Moat receipt is the evidence for this execution.
    evidence = json.dumps(receipt, sort_keys=True, default=str)
    return _keccak256(evidence.encode())


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


def _sign_receipt_message(
    message_hash: bytes,
    private_key: str,
) -> bytes:
    """Sign a message hash using eth_account (EIP-191 personal_sign).

    Returns 65-byte signature: r (32) + s (32) + v (1).
    """
    from eth_account import Account
    from eth_account.messages import encode_defunct

    msg = encode_defunct(message_hash)
    signed = Account.sign_message(msg, private_key=private_key)
    return signed.signature


def _build_message_hash(
    chain_id: int,
    contract_address: str,
    nonce: int,
    intent_hash: bytes,
    constraints_hash: bytes,
    route_hash: bytes,
    outcome_hash: bytes,
    evidence_hash: bytes,
    created_at: int,
    expiry: int,
    solver_id: bytes,
) -> bytes:
    """Build the exact message hash that IntentReceiptHub expects.

    Matches the Solidity:
        keccak256(abi.encode(
            block.chainid, address(this), currentNonce,
            receipt.intentHash, receipt.constraintsHash, receipt.routeHash,
            receipt.outcomeHash, receipt.evidenceHash,
            receipt.createdAt, receipt.expiry, receipt.solverId
        ))
    """
    from eth_abi import encode

    encoded = encode(
        [
            "uint256",
            "address",
            "uint256",
            "bytes32",
            "bytes32",
            "bytes32",
            "bytes32",
            "bytes32",
            "uint64",
            "uint64",
            "bytes32",
        ],
        [
            chain_id,
            contract_address,
            nonce,
            intent_hash,
            constraints_hash,
            route_hash,
            outcome_hash,
            evidence_hash,
            created_at,
            expiry,
            solver_id,
        ],
    )
    return _keccak256(encoded)


# ---------------------------------------------------------------------------
# On-chain submission
# ---------------------------------------------------------------------------


async def _submit_on_chain(
    intent_hash: bytes,
    constraints_hash: bytes,
    route_hash: bytes,
    outcome_hash: bytes,
    evidence_hash: bytes,
    created_at: int,
    expiry: int,
    solver_id: bytes,
    declared_volume: int,
) -> dict[str, Any]:
    """Submit an IntentReceipt to the IntentReceiptHub on Sepolia.

    Returns dict with tx_hash, receipt_id, and status.
    """
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(INTENT_RECEIPT_HUB),
        abi=RECEIPT_HUB_ABI,
    )

    # Read current solver nonce from contract
    current_nonce = contract.functions.solverNonces(solver_id).call()

    # Build and sign the message hash
    msg_hash = _build_message_hash(
        chain_id=CHAIN_ID,
        contract_address=INTENT_RECEIPT_HUB,
        nonce=current_nonce,
        intent_hash=intent_hash,
        constraints_hash=constraints_hash,
        route_hash=route_hash,
        outcome_hash=outcome_hash,
        evidence_hash=evidence_hash,
        created_at=created_at,
        expiry=expiry,
        solver_id=solver_id,
    )

    solver_sig = _sign_receipt_message(msg_hash, SOLVER_PRIVATE_KEY)

    # Build the receipt tuple
    receipt_tuple = (
        intent_hash,
        constraints_hash,
        route_hash,
        outcome_hash,
        evidence_hash,
        created_at,
        expiry,
        solver_id,
        solver_sig,
    )

    # Get sender account
    from eth_account import Account

    account = Account.from_key(SOLVER_PRIVATE_KEY)
    sender = account.address

    # Build transaction
    tx = contract.functions.postReceipt(
        receipt_tuple,
        declared_volume,
    ).build_transaction(
        {
            "from": sender,
            "nonce": w3.eth.get_transaction_count(sender),
            "gasPrice": w3.eth.gas_price,
            "chainId": CHAIN_ID,
        }
    )

    # Sign and send
    signed_tx = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

    logger.info(
        "IRSB receipt tx broadcast",
        extra={
            "tx_hash": tx_hash.hex(),
            "solver_nonce": current_nonce,
            "intent_hash": intent_hash.hex(),
        },
    )

    # Wait for confirmation (with timeout)
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

    # Parse ReceiptPosted event
    receipt_id = None
    logs = contract.events.ReceiptPosted().process_receipt(tx_receipt)
    if logs:
        receipt_id = logs[0]["args"]["receiptId"].hex()

    return {
        "tx_hash": tx_hash.hex(),
        "receipt_id": receipt_id,
        "block_number": tx_receipt["blockNumber"],
        "status": "confirmed" if tx_receipt["status"] == 1 else "failed",
        "gas_used": tx_receipt["gasUsed"],
    }


# ---------------------------------------------------------------------------
# Main hook
# ---------------------------------------------------------------------------


async def post_irsb_receipt(moat_receipt: dict[str, Any]) -> dict[str, Any] | None:
    """Post an IRSB receipt on-chain after a successful Moat execution.

    Called as a background task from execute.py. Non-blocking and
    best-effort — failure does not affect the Moat execution.

    Args:
        moat_receipt: The Moat receipt dict from the execution pipeline.

    Returns:
        Receipt metadata dict if successful, None if dry-run or failed.
    """
    # Only submit receipts for successful executions
    if moat_receipt.get("status") != "success":
        logger.debug(
            "Skipping IRSB receipt for non-success execution",
            extra={"receipt_id": moat_receipt.get("receipt_id")},
        )
        return None

    # Compute all five hashes
    input_hash = hashlib.sha256(
        str(moat_receipt.get("result", {})).encode()
    ).hexdigest()

    intent_hash = compute_intent_hash(
        capability_id=moat_receipt["capability_id"],
        input_hash=input_hash,
        tenant_id=moat_receipt["tenant_id"],
        timestamp=moat_receipt.get("executed_at", ""),
    )
    outcome_hash = compute_result_hash(moat_receipt)
    constraints_hash = compute_constraints_hash(moat_receipt)
    route_hash = compute_route_hash(moat_receipt)
    evidence_hash = compute_evidence_hash(moat_receipt)

    # Timestamps
    now = int(time.time())
    created_at = now
    expiry = now + 86400  # 24h window for settlement

    # Solver ID as bytes32 (left-padded address)
    solver_id = _to_bytes32(SOLVER_ADDRESS)

    irsb_receipt = {
        "intent_hash": "0x" + intent_hash.hex(),
        "outcome_hash": "0x" + outcome_hash.hex(),
        "constraints_hash": "0x" + constraints_hash.hex(),
        "route_hash": "0x" + route_hash.hex(),
        "evidence_hash": "0x" + evidence_hash.hex(),
        "solver": SOLVER_ADDRESS,
        "capability_id": moat_receipt["capability_id"],
        "moat_receipt_id": moat_receipt["receipt_id"],
        "tenant_id": moat_receipt["tenant_id"],
        "timestamp": moat_receipt.get("executed_at"),
    }

    if DRY_RUN:
        irsb_receipt["chain"] = "dry_run"
        logger.info(
            "IRSB receipt (dry-run, not submitted on-chain)",
            extra={
                "intent_hash": "0x" + intent_hash.hex(),
                "outcome_hash": "0x" + outcome_hash.hex(),
                "moat_receipt_id": moat_receipt["receipt_id"],
                "capability_id": moat_receipt["capability_id"],
            },
        )
        return irsb_receipt

    # Pre-flight checks
    if not SEPOLIA_RPC_URL:
        logger.warning(
            "IRSB_RPC_URL not configured — falling back to dry-run",
            extra={"moat_receipt_id": moat_receipt["receipt_id"]},
        )
        irsb_receipt["chain"] = "dry_run_no_rpc"
        return irsb_receipt

    if not SOLVER_PRIVATE_KEY:
        logger.warning(
            "No signing key available — falling back to dry-run",
            extra={"moat_receipt_id": moat_receipt["receipt_id"]},
        )
        irsb_receipt["chain"] = "dry_run_no_key"
        return irsb_receipt

    # Submit on-chain
    try:
        chain_result = await _submit_on_chain(
            intent_hash=intent_hash,
            constraints_hash=constraints_hash,
            route_hash=route_hash,
            outcome_hash=outcome_hash,
            evidence_hash=evidence_hash,
            created_at=created_at,
            expiry=expiry,
            solver_id=solver_id,
            declared_volume=0,  # No volume declared for capability executions
        )

        irsb_receipt["chain"] = "sepolia"
        irsb_receipt["tx_hash"] = chain_result["tx_hash"]
        irsb_receipt["on_chain_receipt_id"] = chain_result["receipt_id"]
        irsb_receipt["block_number"] = chain_result["block_number"]
        irsb_receipt["gas_used"] = chain_result["gas_used"]

        logger.info(
            "IRSB receipt submitted on-chain",
            extra={
                "tx_hash": chain_result["tx_hash"],
                "receipt_id": chain_result["receipt_id"],
                "block": chain_result["block_number"],
                "gas": chain_result["gas_used"],
                "intent_hash": "0x" + intent_hash.hex(),
                "moat_receipt_id": moat_receipt["receipt_id"],
            },
        )
        return irsb_receipt

    except Exception as exc:
        logger.warning(
            "Failed to submit IRSB receipt on-chain (non-fatal)",
            extra={
                "error": str(exc),
                "intent_hash": "0x" + intent_hash.hex(),
                "moat_receipt_id": moat_receipt["receipt_id"],
            },
        )
        irsb_receipt["chain"] = "sepolia_failed"
        irsb_receipt["error"] = str(exc)
        return irsb_receipt
