"""
Tests for scanner.secret_stash.stash — ephemeral secret stash.

Covers:
1. stash + resolve happy path.
2. Resolution by wrong owner returns None.
3. Unknown ref returns None.
4. Expired ref returns None (TTL simulation via direct cache manipulation).
"""

from __future__ import annotations

import pytest
from scanner.secret_stash.stash import stash_secret, resolve_secret_ref, _STASH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_stash():
    """Empty the TTLCache between tests."""
    _STASH.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_stash_and_resolve_happy_path():
    """stash_secret returns an opaque ref; resolve_secret_ref returns the original secret."""
    _clear_stash()

    owner = "user_001"
    secret = "my-super-secret-api-key"

    ref = stash_secret(secret, owner_id=owner)

    assert ref.startswith("stash_"), f"Expected stash_ prefix, got {ref!r}"
    assert resolve_secret_ref(ref, owner_id=owner) == secret


def test_resolve_wrong_owner_returns_none():
    """A ref owned by user A cannot be resolved by user B."""
    _clear_stash()

    owner_a = "user_alice"
    owner_b = "user_bob"
    ref = stash_secret("alice-secret", owner_id=owner_a)

    result = resolve_secret_ref(ref, owner_id=owner_b)
    assert result is None, f"Expected None for wrong owner, got {result!r}"


def test_resolve_unknown_ref_returns_none():
    """Resolving a ref that was never stashed returns None."""
    _clear_stash()

    result = resolve_secret_ref("stash_does_not_exist", owner_id="user_001")
    assert result is None


def test_resolve_expired_ref_returns_none():
    """After expiry (simulated by direct cache eviction), resolution returns None."""
    _clear_stash()

    owner = "user_expire"
    ref = stash_secret("expiring-secret", owner_id=owner)

    # Simulate expiry by directly removing from the cache.
    _STASH.pop((ref, owner), None)

    result = resolve_secret_ref(ref, owner_id=owner)
    assert result is None, f"Expected None after expiry, got {result!r}"


def test_stash_returns_unique_refs():
    """Two calls with the same secret produce different refs."""
    _clear_stash()

    owner = "user_unique"
    secret = "same-secret"

    ref1 = stash_secret(secret, owner_id=owner)
    ref2 = stash_secret(secret, owner_id=owner)

    assert ref1 != ref2, "Two stash calls must return distinct refs"
    assert resolve_secret_ref(ref1, owner_id=owner) == secret
    assert resolve_secret_ref(ref2, owner_id=owner) == secret
