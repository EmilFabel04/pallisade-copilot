"""
Tests for scanner.api.security.verify_token.

Covers:
1. Round-trip valid token.
2. Expired token rejected.
3. Tampered signature rejected.
4. Wrong org_id rejected.
5. Wrong config_hash rejected.
6. Malformed token rejected.
"""

from __future__ import annotations

import time

import pytest

_TEST_SECRET = b"test_secret_32_bytes_minimum_____"
_ORG_ID = "org_test_abc"
_CONFIG_HASH = "aabbccdd1234567890abcdef1234567890abcdef1234567890abcdef12345678"


def _make_token(*, org_id=_ORG_ID, config_hash=_CONFIG_HASH, ttl_sec=60, secret=_TEST_SECRET):
    from scanner.api.security.verify_token import issue_verify_token
    return issue_verify_token(
        {"org_id": org_id, "config_hash": config_hash},
        secret=secret,
        ttl_sec=ttl_sec,
    )


def _validate(token, *, org_id=_ORG_ID, config_hash=_CONFIG_HASH, secret=_TEST_SECRET):
    from scanner.api.security.verify_token import validate_verify_token
    return validate_verify_token(
        token,
        expected_org_id=org_id,
        expected_config_hash=config_hash,
        secret=secret,
    )


# ---------------------------------------------------------------------------
# 1. Round-trip valid token
# ---------------------------------------------------------------------------


def test_round_trip_valid_token():
    """Issue a token and immediately validate it — expect (True, None)."""
    token = _make_token()
    valid, reason = _validate(token)
    assert valid is True, f"Expected valid=True, got reason={reason!r}"
    assert reason is None


# ---------------------------------------------------------------------------
# 2. Expired token rejected
# ---------------------------------------------------------------------------


def test_expired_token_rejected():
    """Token with ttl_sec=0 is immediately expired."""
    from scanner.api.security.verify_token import issue_verify_token, validate_verify_token
    import base64, json

    # Issue a token and manually back-date its exp.
    token = _make_token(ttl_sec=300)
    b64_part, sig = token.rsplit(".", 1)

    # Decode, set exp to 1 second ago, re-encode WITHOUT signing (we want the
    # tamper to show as "expired" not "signature mismatch").
    # Better: issue with ttl_sec=0 and test via the raw token.
    expired_token = _make_token(ttl_sec=0)
    # Sleep 1 second to ensure expiry.  (TTL=0 means exp = now + 0 = already past
    # by the time validate runs because int(time.time()) may equal exp — so we
    # accept either "token expired" or we verify the test still catches it).
    # To avoid flakiness we just issue at -1 offset via monkey-patching time.

    # Simpler: patch the payload manually.
    padding = 4 - len(b64_part) % 4
    padded = b64_part + "=" * (padding % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    payload["exp"] = int(time.time()) - 1  # 1 second in the past

    import hmac, hashlib
    new_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=").decode("ascii")
    new_sig = hmac.new(_TEST_SECRET, new_b64.encode("ascii"), hashlib.sha256).hexdigest()
    expired_token = f"{new_b64}.{new_sig}"

    valid, reason = _validate(expired_token)
    assert valid is False
    assert reason == "token expired", f"Expected 'token expired', got {reason!r}"


# ---------------------------------------------------------------------------
# 3. Tampered signature rejected
# ---------------------------------------------------------------------------


def test_tampered_signature_rejected():
    """Flipping a character in the signature must fail signature check."""
    token = _make_token()
    b64_part, sig = token.rsplit(".", 1)
    # Flip last hex char
    tampered_sig = sig[:-1] + ("a" if sig[-1] != "a" else "b")
    tampered_token = f"{b64_part}.{tampered_sig}"

    valid, reason = _validate(tampered_token)
    assert valid is False
    assert reason == "signature mismatch", f"Expected 'signature mismatch', got {reason!r}"


# ---------------------------------------------------------------------------
# 4. Wrong org_id rejected
# ---------------------------------------------------------------------------


def test_wrong_org_id_rejected():
    """Token issued for org A must fail when validated against org B."""
    token = _make_token(org_id="org_A")
    valid, reason = _validate(token, org_id="org_B")
    assert valid is False
    assert reason == "org_id mismatch", f"Expected 'org_id mismatch', got {reason!r}"


# ---------------------------------------------------------------------------
# 5. Wrong config_hash rejected
# ---------------------------------------------------------------------------


def test_wrong_config_hash_rejected():
    """Token issued for hash X must fail when validated against hash Y."""
    token = _make_token(config_hash="aabbcc" * 10 + "11223344")
    valid, reason = _validate(token, config_hash="deadbeef" * 8)
    assert valid is False
    assert reason == "config_hash mismatch", f"Expected 'config_hash mismatch', got {reason!r}"


# ---------------------------------------------------------------------------
# 6. Malformed token rejected
# ---------------------------------------------------------------------------


def test_malformed_token_no_dot():
    """A token without a dot separator is malformed."""
    valid, reason = _validate("notavalidtoken")
    assert valid is False
    assert reason == "malformed token", f"Expected 'malformed token', got {reason!r}"


def test_malformed_token_empty():
    """Empty string token is malformed."""
    valid, reason = _validate("")
    assert valid is False
    assert reason == "malformed token", f"Got {reason!r}"


# ---------------------------------------------------------------------------
# 7. compute_config_hash determinism
# ---------------------------------------------------------------------------


def test_compute_config_hash_is_deterministic():
    """Same input produces same hash; different inputs produce different hashes."""
    from scanner.api.security.verify_token import compute_config_hash

    d = {"platform_label": "MyCiti", "base_url": "https://api.example.com", "schedule": "daily"}
    h1 = compute_config_hash(d)
    h2 = compute_config_hash(d)
    assert h1 == h2, "Hash must be deterministic"

    d2 = {**d, "schedule": "hourly"}
    h3 = compute_config_hash(d2)
    assert h1 != h3, "Different inputs must produce different hashes"


def test_compute_config_hash_key_order_independent():
    """Hash is identical regardless of key insertion order (sorted-key canonical JSON)."""
    from scanner.api.security.verify_token import compute_config_hash

    d_a = {"z": 1, "a": 2}
    d_b = {"a": 2, "z": 1}
    assert compute_config_hash(d_a) == compute_config_hash(d_b)


# ---------------------------------------------------------------------------
# 8. canonicalize_for_hash — camelCase ↔ snake_case equivalence
# ---------------------------------------------------------------------------


def test_canonicalize_camel_equals_snake():
    """Wizard camelCase payload hashes identically to Pydantic snake_case model_dump."""
    from scanner.api.security.verify_token import compute_config_hash

    # Wizard-style: camelCase, optional fields omitted
    wizard_config = {
        "base_url": "https://api.example.com/v1",
        "schedule": "daily",
        "platform_label": "Test",
        "auth": {
            "kind": "api_key",
            "headerName": "X-API-Key",
            "secret_ref": "stash_abc",
        },
        "datasets": [
            {
                "id": "ds1",
                "endpoint": "/events",
                "timestamp_column": "ts",
            }
        ],
    }

    # Pydantic-style: snake_case, all optional fields explicit with None
    pydantic_config = {
        "base_url": "https://api.example.com/v1",
        "schedule": "daily",
        "platform_label": "Test",
        "auth": {
            "kind": "api_key",
            "header_name": "X-API-Key",
            "username": None,
            "secret_ref": "stash_abc",
        },
        "datasets": [
            {
                "id": "ds1",
                "endpoint": "/events",
                "json_root": None,
                "timestamp_column": "ts",
                "lands_in": None,
                "cursor_param": None,
            }
        ],
    }

    assert compute_config_hash(wizard_config) == compute_config_hash(pydantic_config), (
        "Hash must be identical for logically equivalent camelCase and snake_case configs"
    )


def test_canonicalize_bearer_config():
    """Bearer auth: no headerName in wizard payload, all Nones in Pydantic dump."""
    from scanner.api.security.verify_token import compute_config_hash

    wizard = {
        "base_url": "https://api.example.com",
        "schedule": "hourly",
        "platform_label": "Bearer Test",
        "auth": {"kind": "bearer", "secret_ref": "stash_xyz"},
        "datasets": [
            {"id": "x", "endpoint": "/x", "timestamp_column": "created_at"}
        ],
    }
    pydantic = {
        "base_url": "https://api.example.com",
        "schedule": "hourly",
        "platform_label": "Bearer Test",
        "auth": {
            "kind": "bearer",
            "header_name": None,
            "username": None,
            "secret_ref": "stash_xyz",
        },
        "datasets": [
            {
                "id": "x",
                "endpoint": "/x",
                "json_root": None,
                "timestamp_column": "created_at",
                "lands_in": None,
                "cursor_param": None,
            }
        ],
    }
    assert compute_config_hash(wizard) == compute_config_hash(pydantic)


def test_canonicalize_basic_auth_config():
    """Basic auth: username populated in both representations."""
    from scanner.api.security.verify_token import compute_config_hash

    wizard = {
        "base_url": "https://api.example.com",
        "schedule": "daily",
        "platform_label": "Basic Test",
        "auth": {
            "kind": "basic",
            "username": "myuser",
            "secret_ref": "stash_basic",
        },
        "datasets": [
            {"id": "y", "endpoint": "/y", "timestamp_column": "updated_at"}
        ],
    }
    pydantic = {
        "base_url": "https://api.example.com",
        "schedule": "daily",
        "platform_label": "Basic Test",
        "auth": {
            "kind": "basic",
            "header_name": None,
            "username": "myuser",
            "secret_ref": "stash_basic",
        },
        "datasets": [
            {
                "id": "y",
                "endpoint": "/y",
                "json_root": None,
                "timestamp_column": "updated_at",
                "lands_in": None,
                "cursor_param": None,
            }
        ],
    }
    assert compute_config_hash(wizard) == compute_config_hash(pydantic)


# ---------------------------------------------------------------------------
# 9. HMAC fail-hard in production
# ---------------------------------------------------------------------------


def test_hmac_fails_hard_in_production(monkeypatch):
    """In ENVIRONMENT=production, missing SOURCES_VERIFY_HMAC_SECRET must raise."""
    import importlib
    import sys

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SOURCES_VERIFY_HMAC_SECRET", raising=False)

    # Remove cached module so _load_hmac_secret runs fresh.
    sys.modules.pop("scanner.api.security.verify_token", None)

    import pytest as _pytest
    with _pytest.raises(RuntimeError, match="SOURCES_VERIFY_HMAC_SECRET"):
        import scanner.api.security.verify_token  # noqa: F401 — side-effect import

    # Restore module state so subsequent tests aren't affected.
    sys.modules.pop("scanner.api.security.verify_token", None)


def test_hmac_ephemeral_allowed_in_dev(monkeypatch, caplog):
    """In dev (no ENVIRONMENT=production), missing secret uses ephemeral key with WARNING."""
    import importlib
    import logging
    import sys

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("SOURCES_VERIFY_HMAC_SECRET", raising=False)

    sys.modules.pop("scanner.api.security.verify_token", None)

    with caplog.at_level(logging.WARNING, logger="scanner.api.security.verify_token"):
        import scanner.api.security.verify_token as vt  # noqa: F401

    assert vt._HMAC_SECRET  # non-empty bytes
    assert any("ephemeral" in r.message for r in caplog.records), (
        "Expected a WARNING about ephemeral key in dev mode"
    )

    sys.modules.pop("scanner.api.security.verify_token", None)
