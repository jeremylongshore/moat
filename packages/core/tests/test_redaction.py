"""
Tests for moat_core.redaction.

Covers: header redaction, body redaction (flat and nested), custom
denylists, hash determinism, and key-order independence.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from moat_core import REDACT_KEYS, hash_redacted, redact_body, redact_headers


_SENTINEL = "[REDACTED]"


# ---------------------------------------------------------------------------
# redact_headers
# ---------------------------------------------------------------------------


class TestRedactHeaders:
    def test_redacts_authorization(self) -> None:
        result = redact_headers({"Authorization": "Bearer tok123"})
        assert result["Authorization"] == _SENTINEL

    def test_case_insensitive_matching(self) -> None:
        for variant in ("authorization", "AUTHORIZATION", "Authorization"):
            result = redact_headers({variant: "Bearer tok"})
            assert result[variant] == _SENTINEL

    def test_preserves_non_sensitive_headers(self) -> None:
        result = redact_headers(
            {"Content-Type": "application/json", "X-Request-Id": "abc"}
        )
        assert result["Content-Type"] == "application/json"
        assert result["X-Request-Id"] == "abc"

    def test_redacts_multiple_sensitive_headers(self) -> None:
        result = redact_headers(
            {
                "Authorization": "Bearer tok",
                "X-Api-Key": "key123",
                "Content-Type": "application/json",
            }
        )
        assert result["Authorization"] == _SENTINEL
        assert result["X-Api-Key"] == _SENTINEL
        assert result["Content-Type"] == "application/json"

    def test_empty_headers(self) -> None:
        assert redact_headers({}) == {}

    def test_does_not_mutate_original(self) -> None:
        original = {"Authorization": "Bearer tok", "X-Foo": "bar"}
        redact_headers(original)
        assert original["Authorization"] == "Bearer tok"

    @pytest.mark.parametrize(
        "key",
        [
            "authorization",
            "api_key",
            "api-key",
            "token",
            "password",
            "secret",
            "access_token",
            "refresh_token",
            "x-api-key",
        ],
    )
    def test_all_default_redact_keys(self, key: str) -> None:
        result = redact_headers({key: "sensitive"})
        assert result[key] == _SENTINEL


# ---------------------------------------------------------------------------
# redact_body
# ---------------------------------------------------------------------------


class TestRedactBody:
    def test_flat_redaction(self) -> None:
        result = redact_body({"user": "alice", "password": "s3cr3t"})
        assert result["user"] == "alice"
        assert result["password"] == _SENTINEL

    def test_nested_dict_redaction(self) -> None:
        result = redact_body(
            {"outer": "safe", "nested": {"api_key": "abc123", "value": 42}}
        )
        assert result["outer"] == "safe"
        assert result["nested"]["api_key"] == _SENTINEL
        assert result["nested"]["value"] == 42

    def test_list_of_dicts(self) -> None:
        result = redact_body(
            {"items": [{"token": "tok1"}, {"token": "tok2", "name": "item"}]}
        )
        assert result["items"][0]["token"] == _SENTINEL
        assert result["items"][1]["token"] == _SENTINEL
        assert result["items"][1]["name"] == "item"

    def test_deeply_nested(self) -> None:
        result = redact_body(
            {"a": {"b": {"c": {"password": "deep"}}}}
        )
        assert result["a"]["b"]["c"]["password"] == _SENTINEL

    def test_custom_denylist_extends_defaults(self) -> None:
        result = redact_body(
            {"my_custom_secret": "shh", "user": "alice"},
            denylist=frozenset({"my_custom_secret"}),
        )
        assert result["my_custom_secret"] == _SENTINEL
        assert result["user"] == "alice"

    def test_default_keys_still_applied_with_custom_denylist(self) -> None:
        result = redact_body(
            {"password": "pw", "custom": "val"},
            denylist=frozenset({"custom"}),
        )
        assert result["password"] == _SENTINEL
        assert result["custom"] == _SENTINEL

    def test_empty_dict(self) -> None:
        assert redact_body({}) == {}

    def test_does_not_mutate_original(self) -> None:
        original = {"password": "secret", "user": "bob"}
        redact_body(original)
        assert original["password"] == "secret"

    def test_non_string_values_preserved(self) -> None:
        result = redact_body({"count": 42, "active": True, "ratio": 3.14})
        assert result == {"count": 42, "active": True, "ratio": 3.14}

    def test_none_values_preserved(self) -> None:
        result = redact_body({"value": None})
        assert result["value"] is None


# ---------------------------------------------------------------------------
# hash_redacted
# ---------------------------------------------------------------------------


class TestHashRedacted:
    def test_returns_64_char_hex(self) -> None:
        digest = hash_redacted({"user": "alice"})
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_deterministic(self) -> None:
        data = {"user": "alice", "query": "hello"}
        assert hash_redacted(data) == hash_redacted(data)

    def test_key_order_independent(self) -> None:
        d1 = {"a": 1, "b": 2}
        d2 = {"b": 2, "a": 1}
        assert hash_redacted(d1) == hash_redacted(d2)

    def test_different_data_different_hash(self) -> None:
        h1 = hash_redacted({"user": "alice"})
        h2 = hash_redacted({"user": "bob"})
        assert h1 != h2

    def test_secrets_are_redacted_before_hashing(self) -> None:
        # Both payloads have different passwords but same non-secret fields;
        # their hashes must be equal because password -> [REDACTED] always.
        h1 = hash_redacted({"user": "alice", "password": "pw1"})
        h2 = hash_redacted({"user": "alice", "password": "pw2"})
        assert h1 == h2

    def test_matches_manual_sha256(self) -> None:
        data = {"user": "alice", "query": "test"}
        # Redacted: password is not present, so no redaction needed here
        redacted = redact_body(data)
        expected = hashlib.sha256(
            json.dumps(redacted, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        assert hash_redacted(data) == expected

    def test_works_with_list_input(self) -> None:
        digest = hash_redacted([1, 2, 3])
        assert len(digest) == 64

    def test_works_with_string_input(self) -> None:
        digest = hash_redacted("hello world")
        assert len(digest) == 64

    def test_custom_denylist_applied(self) -> None:
        h_no_custom = hash_redacted({"field": "val"})
        h_with_custom = hash_redacted(
            {"field": "val"}, denylist=frozenset({"field"})
        )
        # With custom denylist, "field" is redacted → [REDACTED]
        # so the hashes differ
        assert h_no_custom != h_with_custom


# ---------------------------------------------------------------------------
# REDACT_KEYS completeness
# ---------------------------------------------------------------------------


class TestRedactKeys:
    def test_is_frozenset(self) -> None:
        assert isinstance(REDACT_KEYS, frozenset)

    def test_contains_critical_keys(self) -> None:
        required = {
            "authorization",
            "api_key",
            "token",
            "password",
            "secret",
            "access_token",
            "refresh_token",
            "client_secret",
            "private_key",
        }
        assert required.issubset(REDACT_KEYS)

    def test_all_lowercase(self) -> None:
        for key in REDACT_KEYS:
            assert key == key.lower(), f"Key '{key}' is not lowercase"
