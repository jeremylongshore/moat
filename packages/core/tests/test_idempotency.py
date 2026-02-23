"""
Tests for moat_core.idempotency.

Covers: key generation determinism, InMemoryIdempotencyStore get/set/TTL,
and Protocol conformance.
"""

from __future__ import annotations

import asyncio

import pytest

from moat_core import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    Receipt,
    generate_idempotency_key,
)
from moat_core.models import ExecutionStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_receipt() -> Receipt:
    return Receipt(
        capability_id="cap_search_v1",
        capability_version="1.0.0",
        tenant_id="tenant_abc",
        idempotency_key="idem_xyz",
        input_hash="a" * 64,
        output_hash="b" * 64,
        latency_ms=55.0,
        status=ExecutionStatus.SUCCESS,
    )


@pytest.fixture()
def store() -> InMemoryIdempotencyStore:
    return InMemoryIdempotencyStore()


# ---------------------------------------------------------------------------
# generate_idempotency_key
# ---------------------------------------------------------------------------


class TestGenerateIdempotencyKey:
    def test_returns_64_char_hex(self) -> None:
        key = generate_idempotency_key("cap_v1", "t1", {"q": "hello"})
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_deterministic(self) -> None:
        k1 = generate_idempotency_key("cap_v1", "t1", {"q": "hello"})
        k2 = generate_idempotency_key("cap_v1", "t1", {"q": "hello"})
        assert k1 == k2

    def test_key_order_independent(self) -> None:
        k1 = generate_idempotency_key("cap", "t", {"a": 1, "b": 2})
        k2 = generate_idempotency_key("cap", "t", {"b": 2, "a": 1})
        assert k1 == k2

    def test_different_capability_id_yields_different_key(self) -> None:
        k1 = generate_idempotency_key("cap_v1", "t1", {"q": "hello"})
        k2 = generate_idempotency_key("cap_v2", "t1", {"q": "hello"})
        assert k1 != k2

    def test_different_tenant_yields_different_key(self) -> None:
        k1 = generate_idempotency_key("cap", "tenant_a", {"q": "hello"})
        k2 = generate_idempotency_key("cap", "tenant_b", {"q": "hello"})
        assert k1 != k2

    def test_different_input_yields_different_key(self) -> None:
        k1 = generate_idempotency_key("cap", "t", {"q": "hello"})
        k2 = generate_idempotency_key("cap", "t", {"q": "world"})
        assert k1 != k2

    def test_empty_input_dict(self) -> None:
        key = generate_idempotency_key("cap", "t", {})
        assert len(key) == 64


# ---------------------------------------------------------------------------
# InMemoryIdempotencyStore
# ---------------------------------------------------------------------------


class TestInMemoryIdempotencyStore:
    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_key(
        self, store: InMemoryIdempotencyStore
    ) -> None:
        result = await store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get_round_trip(
        self, store: InMemoryIdempotencyStore, sample_receipt: Receipt
    ) -> None:
        await store.set("key1", sample_receipt)
        retrieved = await store.get("key1")
        assert retrieved == sample_receipt

    @pytest.mark.asyncio
    async def test_expired_entry_returns_none(
        self, store: InMemoryIdempotencyStore, sample_receipt: Receipt
    ) -> None:
        # TTL of 0 seconds means immediately expired
        await store.set("expiring", sample_receipt, ttl_seconds=0)
        # Give asyncio scheduler a moment
        await asyncio.sleep(0)
        result = await store.get("expiring")
        assert result is None

    @pytest.mark.asyncio
    async def test_non_expired_entry_returned(
        self, store: InMemoryIdempotencyStore, sample_receipt: Receipt
    ) -> None:
        await store.set("valid", sample_receipt, ttl_seconds=86400)
        result = await store.get("valid")
        assert result == sample_receipt

    @pytest.mark.asyncio
    async def test_overwrite_same_key(
        self, store: InMemoryIdempotencyStore, sample_receipt: Receipt
    ) -> None:
        await store.set("key", sample_receipt, ttl_seconds=86400)
        # Create a different receipt
        other = Receipt(
            id=sample_receipt.id,
            capability_id="cap_other",
            capability_version="2.0.0",
            tenant_id="tenant_xyz",
            idempotency_key="idem_other",
            input_hash="c" * 64,
            output_hash="d" * 64,
            latency_ms=10.0,
            status=ExecutionStatus.FAILURE,
        )
        await store.set("key", other, ttl_seconds=86400)
        result = await store.get("key")
        assert result == other

    @pytest.mark.asyncio
    async def test_size_property(
        self, store: InMemoryIdempotencyStore, sample_receipt: Receipt
    ) -> None:
        assert store.size == 0
        await store.set("k1", sample_receipt)
        await store.set("k2", sample_receipt)
        assert store.size == 2

    @pytest.mark.asyncio
    async def test_clear(
        self, store: InMemoryIdempotencyStore, sample_receipt: Receipt
    ) -> None:
        await store.set("k1", sample_receipt)
        await store.set("k2", sample_receipt)
        await store.clear()
        assert store.size == 0
        assert await store.get("k1") is None

    @pytest.mark.asyncio
    async def test_multiple_keys_independent(
        self, store: InMemoryIdempotencyStore, sample_receipt: Receipt
    ) -> None:
        await store.set("alpha", sample_receipt)
        await store.set("beta", sample_receipt)
        assert await store.get("alpha") == sample_receipt
        assert await store.get("beta") == sample_receipt
        assert await store.get("gamma") is None

    @pytest.mark.asyncio
    async def test_expired_entry_evicted_from_store(
        self, store: InMemoryIdempotencyStore, sample_receipt: Receipt
    ) -> None:
        await store.set("exp", sample_receipt, ttl_seconds=0)
        await asyncio.sleep(0)
        await store.get("exp")  # triggers eviction
        # After eviction, size should decrease
        assert store.size == 0


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestIdempotencyStoreProtocol:
    def test_in_memory_store_is_protocol_instance(self) -> None:
        store = InMemoryIdempotencyStore()
        assert isinstance(store, IdempotencyStore)

    def test_protocol_is_runtime_checkable(self) -> None:
        # Verify Protocol is decorated with @runtime_checkable
        # A class lacking get/set methods should NOT satisfy the protocol
        class NotAStore:
            pass

        assert not isinstance(NotAStore(), IdempotencyStore)

    def test_duck_type_satisfies_protocol(self) -> None:
        """Any class with get/set coroutine methods satisfies IdempotencyStore."""

        class FakeStore:
            async def get(self, key: str) -> Receipt | None:
                return None

            async def set(
                self, key: str, receipt: Receipt, ttl_seconds: int = 86400
            ) -> None:
                pass

        assert isinstance(FakeStore(), IdempotencyStore)
