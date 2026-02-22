"""
Tests for IRSB receipt hook — hash computation, signing, dry-run, and
on-chain submission.

The IRSB receipt hook is a post-execution side-effect that submits an
IntentReceipt to the IntentReceiptHub contract on Sepolia after every
successful Moat capability execution. These tests validate:

  - All five keccak256 hash functions produce 32-byte, deterministic output
  - _build_message_hash constructs the exact EVM-encoded preimage
  - _sign_receipt_message produces valid 65-byte EIP-191 signatures
  - post_irsb_receipt dry-run path: returns receipt with chain='dry_run'
  - Non-success moat receipts return None (no receipt posted)
  - Missing RPC URL falls back to chain='dry_run_no_rpc'
  - Missing signing key falls back to chain='dry_run_no_key'
  - Live path delegates to _submit_on_chain and merges chain metadata
  - DRY_RUN env-var parsing (case-insensitive, default-true)

Test private key: Foundry's default anvil key #0
  Private key : 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
  Address     : 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
"""

from __future__ import annotations

import os

# Set env before any module-level import that reads from os.environ.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("MOAT_AUTH_DISABLED", "true")
os.environ.setdefault("IRSB_DRY_RUN", "true")

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.hooks.irsb_receipt import (
    _build_message_hash,
    _keccak256,
    _sign_receipt_message,
    _to_bytes32,
    compute_constraints_hash,
    compute_evidence_hash,
    compute_intent_hash,
    compute_result_hash,
    compute_route_hash,
    post_irsb_receipt,
)

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

# Foundry default test key (publicly known, safe for test use).
_TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_TEST_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

# A realistic moat_receipt dict that represents a successful execution.
_BASE_RECEIPT: dict = {
    "status": "success",
    "receipt_id": "receipt-uuid-001",
    "capability_id": "cap-test-001",
    "tenant_id": "tenant-alpha",
    "executed_at": "2026-02-21T12:00:00Z",
    "adapter": "stub",
    "scope": "execute",
    "result": {"stub": True, "echo_params": {"x": 1}},
}

# Minimal 32-byte zero buffer used as a sentinel in hash tests.
_ZERO_32 = b"\x00" * 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_receipt(**overrides) -> dict:
    """Return a copy of _BASE_RECEIPT with the given keys overridden."""
    return {**_BASE_RECEIPT, **overrides}


# ---------------------------------------------------------------------------
# Class 1: Hash computation
# ---------------------------------------------------------------------------


class TestHashComputation:
    """Verify the five keccak256 hash helpers.

    Each function should:
    - Return exactly 32 bytes (keccak256 output length).
    - Be deterministic: same input → same output.
    - Be sensitive to input changes: different input → different output.
    """

    # --- compute_intent_hash ---

    def test_intent_hash_returns_32_bytes(self):
        """compute_intent_hash output is exactly 32 bytes."""
        h = compute_intent_hash("cap-x", "input-hash-abc", "tenant-1", "2026-01-01T00:00:00Z")
        assert len(h) == 32

    def test_intent_hash_is_deterministic(self):
        """compute_intent_hash is pure: identical args produce identical output."""
        args = ("cap-x", "input-hash-abc", "tenant-1", "2026-01-01T00:00:00Z")
        assert compute_intent_hash(*args) == compute_intent_hash(*args)

    def test_intent_hash_differs_for_different_capability(self):
        """Changing capability_id changes the hash."""
        h1 = compute_intent_hash("cap-a", "hash", "tenant-1", "ts")
        h2 = compute_intent_hash("cap-b", "hash", "tenant-1", "ts")
        assert h1 != h2

    def test_intent_hash_differs_for_different_tenant(self):
        """Changing tenant_id changes the hash."""
        h1 = compute_intent_hash("cap-x", "hash", "tenant-1", "ts")
        h2 = compute_intent_hash("cap-x", "hash", "tenant-2", "ts")
        assert h1 != h2

    def test_intent_hash_differs_for_different_timestamp(self):
        """Changing timestamp changes the hash."""
        h1 = compute_intent_hash("cap-x", "hash", "tenant-1", "2026-01-01T00:00:00Z")
        h2 = compute_intent_hash("cap-x", "hash", "tenant-1", "2026-01-02T00:00:00Z")
        assert h1 != h2

    def test_intent_hash_differs_for_different_input_hash(self):
        """Changing input_hash changes the output."""
        h1 = compute_intent_hash("cap-x", "hash-aaa", "tenant-1", "ts")
        h2 = compute_intent_hash("cap-x", "hash-bbb", "tenant-1", "ts")
        assert h1 != h2

    # --- compute_result_hash ---

    def test_result_hash_returns_32_bytes(self):
        """compute_result_hash output is exactly 32 bytes."""
        receipt = _make_receipt()
        assert len(compute_result_hash(receipt)) == 32

    def test_result_hash_is_deterministic(self):
        """compute_result_hash is pure."""
        receipt = _make_receipt()
        assert compute_result_hash(receipt) == compute_result_hash(receipt)

    def test_result_hash_differs_for_different_result(self):
        """Mutating the result field produces a different hash."""
        receipt_a = _make_receipt(result={"value": 1})
        receipt_b = _make_receipt(result={"value": 2})
        assert compute_result_hash(receipt_a) != compute_result_hash(receipt_b)

    def test_result_hash_with_empty_result(self):
        """compute_result_hash handles an absent/empty result gracefully."""
        receipt = _make_receipt()
        receipt.pop("result", None)
        h = compute_result_hash(receipt)
        assert len(h) == 32

    # --- compute_constraints_hash ---

    def test_constraints_hash_returns_32_bytes(self):
        """compute_constraints_hash output is exactly 32 bytes."""
        assert len(compute_constraints_hash(_make_receipt())) == 32

    def test_constraints_hash_is_deterministic(self):
        """compute_constraints_hash is pure."""
        receipt = _make_receipt()
        assert compute_constraints_hash(receipt) == compute_constraints_hash(receipt)

    def test_constraints_hash_differs_for_different_capability(self):
        """Changing capability_id in the receipt changes the constraints hash."""
        r1 = _make_receipt(capability_id="cap-a")
        r2 = _make_receipt(capability_id="cap-b")
        assert compute_constraints_hash(r1) != compute_constraints_hash(r2)

    def test_constraints_hash_differs_for_different_tenant(self):
        """Changing tenant_id in the receipt changes the constraints hash."""
        r1 = _make_receipt(tenant_id="tenant-a")
        r2 = _make_receipt(tenant_id="tenant-b")
        assert compute_constraints_hash(r1) != compute_constraints_hash(r2)

    def test_constraints_hash_differs_for_different_scope(self):
        """Changing scope in the receipt changes the constraints hash."""
        r1 = _make_receipt(scope="execute")
        r2 = _make_receipt(scope="admin:delete")
        assert compute_constraints_hash(r1) != compute_constraints_hash(r2)

    # --- compute_route_hash ---

    def test_route_hash_returns_32_bytes(self):
        """compute_route_hash output is exactly 32 bytes."""
        assert len(compute_route_hash(_make_receipt())) == 32

    def test_route_hash_is_deterministic(self):
        """compute_route_hash is pure."""
        receipt = _make_receipt()
        assert compute_route_hash(receipt) == compute_route_hash(receipt)

    def test_route_hash_differs_for_different_adapter(self):
        """Changing adapter changes the route hash."""
        r1 = _make_receipt(adapter="stub")
        r2 = _make_receipt(adapter="slack")
        assert compute_route_hash(r1) != compute_route_hash(r2)

    def test_route_hash_differs_for_different_capability(self):
        """Changing capability_id changes the route hash."""
        r1 = _make_receipt(capability_id="cap-a")
        r2 = _make_receipt(capability_id="cap-b")
        assert compute_route_hash(r1) != compute_route_hash(r2)

    # --- compute_evidence_hash ---

    def test_evidence_hash_returns_32_bytes(self):
        """compute_evidence_hash output is exactly 32 bytes."""
        assert len(compute_evidence_hash(_make_receipt())) == 32

    def test_evidence_hash_is_deterministic(self):
        """compute_evidence_hash is pure."""
        receipt = _make_receipt()
        assert compute_evidence_hash(receipt) == compute_evidence_hash(receipt)

    def test_evidence_hash_covers_entire_receipt(self):
        """Adding any field to the receipt changes the evidence hash."""
        r1 = _make_receipt()
        r2 = _make_receipt(extra_field="sneaky-data")
        assert compute_evidence_hash(r1) != compute_evidence_hash(r2)

    def test_all_five_hashes_differ_from_each_other(self):
        """The five hash functions produce distinct values for the same receipt."""
        receipt = _make_receipt()
        # Intent hash is computed slightly differently (not from the receipt dict),
        # so we compare the others.
        hashes = [
            compute_result_hash(receipt),
            compute_constraints_hash(receipt),
            compute_route_hash(receipt),
            compute_evidence_hash(receipt),
        ]
        # All pairs must differ (no accidental collision between functions).
        for i, h1 in enumerate(hashes):
            for j, h2 in enumerate(hashes):
                if i != j:
                    assert h1 != h2, f"Hash {i} and hash {j} unexpectedly collided"


# ---------------------------------------------------------------------------
# Class 2: _build_message_hash
# ---------------------------------------------------------------------------


class TestBuildMessageHash:
    """Tests for _build_message_hash.

    This function builds the exact ABI-encoded preimage that the Solidity
    IntentReceiptHub contract will verify. The output must be 32 bytes,
    deterministic, and sensitive to every input parameter.
    """

    def _call(self, **overrides) -> bytes:
        """Call _build_message_hash with reasonable defaults, applying overrides."""
        defaults = dict(
            chain_id=11155111,
            contract_address="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
            nonce=0,
            intent_hash=_keccak256(b"intent"),
            constraints_hash=_keccak256(b"constraints"),
            route_hash=_keccak256(b"route"),
            outcome_hash=_keccak256(b"outcome"),
            evidence_hash=_keccak256(b"evidence"),
            created_at=1_700_000_000,
            expiry=1_700_086_400,
            solver_id=_to_bytes32("0x83Be08FFB22b61733eDf15b0ee9Caf5562cd888d"),
        )
        defaults.update(overrides)
        return _build_message_hash(**defaults)

    def test_returns_32_bytes(self):
        """_build_message_hash always returns exactly 32 bytes."""
        assert len(self._call()) == 32

    def test_is_deterministic(self):
        """Same inputs always produce the same message hash."""
        assert self._call() == self._call()

    def test_differs_for_different_chain_id(self):
        """Different chain_id produces a different message hash."""
        h1 = self._call(chain_id=11155111)
        h2 = self._call(chain_id=1)
        assert h1 != h2

    def test_differs_for_different_nonce(self):
        """Different nonce produces a different message hash (replay protection)."""
        h1 = self._call(nonce=0)
        h2 = self._call(nonce=1)
        assert h1 != h2

    def test_differs_for_different_intent_hash(self):
        """Different intent hash produces a different message hash."""
        h1 = self._call(intent_hash=_keccak256(b"intent-a"))
        h2 = self._call(intent_hash=_keccak256(b"intent-b"))
        assert h1 != h2

    def test_differs_for_different_contract_address(self):
        """Different contract address produces a different message hash."""
        h1 = self._call(contract_address="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c")
        h2 = self._call(contract_address="0xB6ab964832808E49635fF82D1996D6a888ecB745")
        assert h1 != h2

    def test_differs_for_different_expiry(self):
        """Different expiry timestamp produces a different message hash."""
        h1 = self._call(expiry=1_700_086_400)
        h2 = self._call(expiry=1_700_172_800)
        assert h1 != h2

    def test_known_input_produces_bytes(self):
        """_build_message_hash returns raw bytes (not a hex string or int)."""
        result = self._call()
        assert isinstance(result, bytes)

    def test_encoding_covers_all_eleven_fields(self):
        """Changing each of the 11 ABI-encoded fields alters the output.

        This is a batch sensitivity check: we mutate one field at a time and
        confirm the output changes, ensuring no field is silently ignored.
        """
        base = self._call()
        mutations = [
            dict(chain_id=1),
            dict(contract_address="0xB6ab964832808E49635fF82D1996D6a888ecB745"),
            dict(nonce=42),
            dict(intent_hash=_keccak256(b"x")),
            dict(constraints_hash=_keccak256(b"x")),
            dict(route_hash=_keccak256(b"x")),
            dict(outcome_hash=_keccak256(b"x")),
            dict(evidence_hash=_keccak256(b"x")),
            dict(created_at=0),
            dict(expiry=9_999_999_999),
            dict(solver_id=_to_bytes32("0x0000000000000000000000000000000000000001")),
        ]
        for mutation in mutations:
            mutated = self._call(**mutation)
            assert mutated != base, (
                f"Mutation {mutation} did not change the message hash"
            )


# ---------------------------------------------------------------------------
# Class 3: _sign_receipt_message
# ---------------------------------------------------------------------------


class TestSignReceiptMessage:
    """Tests for EIP-191 message signing.

    Uses Foundry's public test key so no real funds are at risk.
    """

    def test_signature_is_65_bytes(self):
        """EIP-191 personal_sign produces a 65-byte (r + s + v) signature."""
        msg_hash = _keccak256(b"test message")
        sig = _sign_receipt_message(msg_hash, _TEST_PRIVATE_KEY)
        assert len(sig) == 65

    def test_signature_is_deterministic_for_same_key_and_message(self):
        """Same key + same message always produces the same signature."""
        msg_hash = _keccak256(b"deterministic test")
        sig1 = _sign_receipt_message(msg_hash, _TEST_PRIVATE_KEY)
        sig2 = _sign_receipt_message(msg_hash, _TEST_PRIVATE_KEY)
        assert sig1 == sig2

    def test_signature_differs_for_different_message(self):
        """Different message → different signature."""
        h1 = _keccak256(b"message-a")
        h2 = _keccak256(b"message-b")
        sig1 = _sign_receipt_message(h1, _TEST_PRIVATE_KEY)
        sig2 = _sign_receipt_message(h2, _TEST_PRIVATE_KEY)
        assert sig1 != sig2

    def test_signature_is_verifiable_against_signer_address(self):
        """The recovered address from the signature matches the test key's address."""
        from eth_account import Account
        from eth_account.messages import encode_defunct

        msg_hash = _keccak256(b"verify me")
        sig = _sign_receipt_message(msg_hash, _TEST_PRIVATE_KEY)

        msg = encode_defunct(msg_hash)
        recovered = Account.recover_message(msg, signature=sig)
        assert recovered.lower() == _TEST_ADDRESS.lower()

    def test_signature_is_bytes_type(self):
        """_sign_receipt_message returns raw bytes (not hex string)."""
        msg_hash = _keccak256(b"type check")
        sig = _sign_receipt_message(msg_hash, _TEST_PRIVATE_KEY)
        assert isinstance(sig, bytes)

    def test_v_byte_is_27_or_28_canonical(self):
        """The final byte (v) of the signature must be 27 or 28 (canonical EIP-191)."""
        msg_hash = _keccak256(b"v byte test")
        sig = _sign_receipt_message(msg_hash, _TEST_PRIVATE_KEY)
        v = sig[-1]
        assert v in (27, 28), f"Expected v in {{27, 28}}, got {v}"

    def test_r_and_s_are_non_zero(self):
        """The r and s components of the signature should be non-zero."""
        msg_hash = _keccak256(b"r s check")
        sig = _sign_receipt_message(msg_hash, _TEST_PRIVATE_KEY)
        r_bytes = sig[:32]
        s_bytes = sig[32:64]
        assert r_bytes != b"\x00" * 32
        assert s_bytes != b"\x00" * 32


# ---------------------------------------------------------------------------
# Class 4: post_irsb_receipt
# ---------------------------------------------------------------------------


class TestPostIrsbReceipt:
    """Tests for the top-level async post_irsb_receipt hook.

    Most tests operate in dry-run mode (IRSB_DRY_RUN=true) which is the
    safe default. Live-mode tests mock _submit_on_chain.
    """

    async def test_dry_run_returns_receipt_with_dry_run_chain(self):
        """In dry-run mode, post_irsb_receipt returns a receipt dict with chain='dry_run'."""
        import app.hooks.irsb_receipt as mod

        with patch.object(mod, "DRY_RUN", True):
            result = await post_irsb_receipt(_make_receipt())

        assert result is not None
        assert result["chain"] == "dry_run"

    async def test_dry_run_receipt_contains_all_five_hashes(self):
        """The dry-run receipt contains all five 0x-prefixed hash fields."""
        import app.hooks.irsb_receipt as mod

        with patch.object(mod, "DRY_RUN", True):
            result = await post_irsb_receipt(_make_receipt())

        assert result is not None
        for field in ("intent_hash", "outcome_hash", "constraints_hash", "route_hash", "evidence_hash"):
            assert field in result, f"Missing field: {field}"
            assert result[field].startswith("0x"), f"{field} should be 0x-prefixed"

    async def test_dry_run_receipt_contains_metadata_fields(self):
        """The dry-run receipt carries capability_id, tenant_id, moat_receipt_id, and solver."""
        import app.hooks.irsb_receipt as mod

        receipt_in = _make_receipt()
        with patch.object(mod, "DRY_RUN", True):
            result = await post_irsb_receipt(receipt_in)

        assert result is not None
        assert result["capability_id"] == receipt_in["capability_id"]
        assert result["tenant_id"] == receipt_in["tenant_id"]
        assert result["moat_receipt_id"] == receipt_in["receipt_id"]

    async def test_non_success_status_returns_none(self):
        """A receipt with status != 'success' is silently skipped (returns None)."""
        import app.hooks.irsb_receipt as mod

        for status in ("failure", "timeout", "policy_denied", "error"):
            result = await post_irsb_receipt(_make_receipt(status=status))
            assert result is None, f"Expected None for status={status!r}, got {result!r}"

    async def test_no_rpc_url_falls_back_to_dry_run_no_rpc(self):
        """When DRY_RUN=False but no RPC URL is set, falls back to dry_run_no_rpc."""
        import app.hooks.irsb_receipt as mod

        with (
            patch.object(mod, "DRY_RUN", False),
            patch.object(mod, "SEPOLIA_RPC_URL", ""),
            patch.object(mod, "SOLVER_PRIVATE_KEY", _TEST_PRIVATE_KEY),
        ):
            result = await post_irsb_receipt(_make_receipt())

        assert result is not None
        assert result["chain"] == "dry_run_no_rpc"

    async def test_no_signing_key_falls_back_to_dry_run_no_key(self):
        """When DRY_RUN=False but no signing key is set, falls back to dry_run_no_key."""
        import app.hooks.irsb_receipt as mod

        with (
            patch.object(mod, "DRY_RUN", False),
            patch.object(mod, "SEPOLIA_RPC_URL", "https://rpc.example.com"),
            patch.object(mod, "SOLVER_PRIVATE_KEY", None),
        ):
            result = await post_irsb_receipt(_make_receipt())

        assert result is not None
        assert result["chain"] == "dry_run_no_key"

    async def test_live_mode_calls_submit_on_chain(self):
        """In live mode with RPC+key configured, _submit_on_chain is awaited."""
        import app.hooks.irsb_receipt as mod

        mock_chain_result = {
            "tx_hash": "0xdeadbeef",
            "receipt_id": "0xcafe",
            "block_number": 12345,
            "status": "confirmed",
            "gas_used": 50_000,
        }

        with (
            patch.object(mod, "DRY_RUN", False),
            patch.object(mod, "SEPOLIA_RPC_URL", "https://rpc.sepolia.example.com"),
            patch.object(mod, "SOLVER_PRIVATE_KEY", _TEST_PRIVATE_KEY),
            patch.object(
                mod, "_submit_on_chain", new=AsyncMock(return_value=mock_chain_result)
            ),
        ):
            result = await post_irsb_receipt(_make_receipt())

        assert result is not None
        assert result["chain"] == "sepolia"
        assert result["tx_hash"] == "0xdeadbeef"
        assert result["block_number"] == 12345
        assert result["gas_used"] == 50_000

    async def test_live_mode_submit_exception_returns_error_receipt(self):
        """When _submit_on_chain raises, the exception is caught and chain='sepolia_failed'."""
        import app.hooks.irsb_receipt as mod

        with (
            patch.object(mod, "DRY_RUN", False),
            patch.object(mod, "SEPOLIA_RPC_URL", "https://rpc.sepolia.example.com"),
            patch.object(mod, "SOLVER_PRIVATE_KEY", _TEST_PRIVATE_KEY),
            patch.object(
                mod,
                "_submit_on_chain",
                new=AsyncMock(side_effect=ConnectionError("RPC timeout")),
            ),
        ):
            result = await post_irsb_receipt(_make_receipt())

        assert result is not None
        assert result["chain"] == "sepolia_failed"
        assert "RPC timeout" in result.get("error", "")

    async def test_result_is_none_does_not_raise(self):
        """Absent 'result' key in the moat_receipt is handled gracefully."""
        import app.hooks.irsb_receipt as mod

        receipt = _make_receipt()
        receipt.pop("result", None)
        with patch.object(mod, "DRY_RUN", True):
            result = await post_irsb_receipt(receipt)

        assert result is not None
        assert result["chain"] == "dry_run"

    async def test_hashes_are_deterministic_across_calls(self):
        """Two calls with the same receipt produce identical hash fields."""
        import app.hooks.irsb_receipt as mod

        receipt = _make_receipt()
        with patch.object(mod, "DRY_RUN", True):
            r1 = await post_irsb_receipt(receipt)
            r2 = await post_irsb_receipt(receipt)

        assert r1 is not None and r2 is not None
        for field in ("intent_hash", "outcome_hash", "constraints_hash", "route_hash", "evidence_hash"):
            assert r1[field] == r2[field], f"Non-deterministic field: {field}"


# ---------------------------------------------------------------------------
# Class 5: Dry-run mode flag behaviour
# ---------------------------------------------------------------------------


class TestDryRunMode:
    """Tests for the DRY_RUN module-level flag.

    The flag is read once at module import from IRSB_DRY_RUN env var.
    Individual test scenarios manipulate the module attribute directly.
    """

    def test_default_is_dry_run_when_env_var_is_true(self):
        """When IRSB_DRY_RUN=true, DRY_RUN should be True (set in module setUp)."""
        import app.hooks.irsb_receipt as mod

        # The test suite sets IRSB_DRY_RUN=true at the top of this file.
        # We just confirm the module reflects this.
        # (We patch it directly in async tests; here we check the parsing logic.)
        dry_run_env = os.environ.get("IRSB_DRY_RUN", "true").lower()
        expected = dry_run_env == "true"
        assert mod.DRY_RUN == expected

    def test_dry_run_true_skips_on_chain_submission(self):
        """When DRY_RUN=True, _submit_on_chain is never called."""
        import app.hooks.irsb_receipt as mod

        submit_mock = AsyncMock()
        with (
            patch.object(mod, "DRY_RUN", True),
            patch.object(mod, "_submit_on_chain", submit_mock),
        ):
            import asyncio

            asyncio.get_event_loop().run_until_complete(
                post_irsb_receipt(_make_receipt())
            )

        submit_mock.assert_not_called()

    async def test_dry_run_false_with_no_config_does_not_call_submit(self):
        """DRY_RUN=False but missing RPC+key still avoids _submit_on_chain."""
        import app.hooks.irsb_receipt as mod

        submit_mock = AsyncMock()
        with (
            patch.object(mod, "DRY_RUN", False),
            patch.object(mod, "SEPOLIA_RPC_URL", ""),
            patch.object(mod, "SOLVER_PRIVATE_KEY", None),
            patch.object(mod, "_submit_on_chain", submit_mock),
        ):
            await post_irsb_receipt(_make_receipt())

        submit_mock.assert_not_called()

    async def test_env_var_false_string_enables_live_mode(self):
        """IRSB_DRY_RUN=false (any case) enables live submission path."""
        # We test this by patching the module attribute to False and verifying
        # the live-mode pre-flight checks run (no RPC → dry_run_no_rpc, not dry_run).
        import app.hooks.irsb_receipt as mod

        with (
            patch.object(mod, "DRY_RUN", False),
            patch.object(mod, "SEPOLIA_RPC_URL", ""),
            patch.object(mod, "SOLVER_PRIVATE_KEY", "some-key"),
        ):
            result = await post_irsb_receipt(_make_receipt())

        assert result is not None
        # Should hit the no-rpc fallback, not the generic dry_run path.
        assert result["chain"] == "dry_run_no_rpc"

    async def test_chain_field_present_in_all_fallback_paths(self):
        """Every code path through post_irsb_receipt sets the 'chain' field."""
        import app.hooks.irsb_receipt as mod

        scenarios = [
            # (DRY_RUN, RPC_URL, KEY, expected_chain)
            (True, "", None, "dry_run"),
            (False, "", _TEST_PRIVATE_KEY, "dry_run_no_rpc"),
            (False, "https://rpc.example.com", None, "dry_run_no_key"),
        ]

        for dry_run, rpc, key, expected_chain in scenarios:
            with (
                patch.object(mod, "DRY_RUN", dry_run),
                patch.object(mod, "SEPOLIA_RPC_URL", rpc),
                patch.object(mod, "SOLVER_PRIVATE_KEY", key),
            ):
                result = await post_irsb_receipt(_make_receipt())

            assert result is not None, f"Scenario {expected_chain!r} returned None"
            assert result["chain"] == expected_chain, (
                f"Expected chain={expected_chain!r}, got {result['chain']!r} "
                f"for scenario (DRY_RUN={dry_run}, rpc={rpc!r}, key={'set' if key else None!r})"
            )


# ---------------------------------------------------------------------------
# Class 6: _keccak256 and _to_bytes32 primitives
# ---------------------------------------------------------------------------


class TestHashPrimitives:
    """Tests for the low-level _keccak256 and _to_bytes32 helper functions."""

    def test_keccak256_returns_32_bytes(self):
        """_keccak256 always returns exactly 32 bytes."""
        assert len(_keccak256(b"hello")) == 32

    def test_keccak256_is_deterministic(self):
        """Same input always produces the same keccak256 output."""
        assert _keccak256(b"test") == _keccak256(b"test")

    def test_keccak256_differs_for_different_input(self):
        """Different input produces different keccak256 output."""
        assert _keccak256(b"a") != _keccak256(b"b")

    def test_keccak256_known_vector(self):
        """_keccak256(b'') matches the well-known empty-string keccak256 digest."""
        # keccak256("") = 0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470
        expected = bytes.fromhex(
            "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
        )
        assert _keccak256(b"") == expected

    def test_to_bytes32_pads_short_address(self):
        """A 20-byte address is left-padded to 32 bytes."""
        result = _to_bytes32("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")
        assert len(result) == 32
        # First 12 bytes should be zero-padding.
        assert result[:12] == b"\x00" * 12

    def test_to_bytes32_preserves_address_in_last_20_bytes(self):
        """The address bytes occupy the last 20 bytes of the 32-byte result."""
        addr = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
        result = _to_bytes32(addr)
        addr_bytes = bytes.fromhex(addr[2:])
        assert result[12:] == addr_bytes

    def test_to_bytes32_handles_0x_prefix(self):
        """_to_bytes32 strips the '0x' prefix before decoding."""
        with_prefix = _to_bytes32("0xdeadbeef")
        without_prefix = _to_bytes32("deadbeef")
        assert with_prefix == without_prefix

    def test_to_bytes32_is_deterministic(self):
        """Same hex string always produces the same bytes32."""
        addr = "0x83Be08FFB22b61733eDf15b0ee9Caf5562cd888d"
        assert _to_bytes32(addr) == _to_bytes32(addr)
