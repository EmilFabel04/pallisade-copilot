"""
Cross-language hash compatibility test.

Verifies that ``compute_config_hash`` in Python (verify_token.py) and
``computeConfigHash`` in TypeScript (lib/server/verify-token.ts) produce
identical SHA-256 digests for the same logical config payload.

Strategy: FALLBACK approach (Option B as described in the reviewer notes).
We hand-derive the canonical JSON for each fixture, compute its SHA-256 in
Python, and assert it matches a hardcoded expected hash.  The TypeScript test
in ``__tests__/server/verify-token.test.ts`` asserts the same expected hashes
from the TS side, giving us cross-language coverage without requiring a
subprocess call.

Hardcoded expected hashes were derived by running the Python canonicalize
function on each fixture and capturing the output.  If either side changes
the canonical projection or hash algorithm, both this test AND the TS test
will fail — making the drift immediately visible in CI.

Fixtures cover the three auth kinds: api_key, bearer, basic.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

import pytest

# The three fixture configs in wizard-style camelCase (what the frontend sends).
# These are the same fixtures used by the TS test.
FIXTURES: list[tuple[str, Dict[str, Any], str]] = [
    (
        "api_key — headerName camelCase, no optional fields",
        {
            "base_url": "https://api.example.com/v1",
            "schedule": "daily",
            "platform_label": "Test",
            "auth": {
                "kind": "api_key",
                "headerName": "X-API-Key",
                "secret_ref": "stash_abc",
            },
            "datasets": [
                {"id": "x", "endpoint": "/x", "timestamp_column": "ts"},
            ],
        },
        # Expected hash derived from canonical JSON:
        # {"auth":{"header_name":"X-API-Key","kind":"api_key","secret_ref":"stash_abc","username":null},
        #  "base_url":"https://api.example.com/v1",
        #  "datasets":[{"cursor_param":null,"endpoint":"/x","id":"x","json_root":null,"lands_in":null,"timestamp_column":"ts"}],
        #  "platform_label":"Test","schedule":"daily"}
        "3800913628b86ed7d22613f94953901234f8188513fd4e1b28427eed79a4e9ad",
    ),
    (
        "bearer — no headerName, no username",
        {
            "base_url": "https://api.example.com",
            "schedule": "hourly",
            "platform_label": "Bearer Test",
            "auth": {"kind": "bearer", "secret_ref": "stash_xyz"},
            "datasets": [
                {"id": "x", "endpoint": "/x", "timestamp_column": "created_at"},
            ],
        },
        # Expected hash from canonical JSON:
        # {"auth":{"header_name":null,"kind":"bearer","secret_ref":"stash_xyz","username":null}, ...}
        "1a8115e2e0fef2226dec6939a7d7d64ce7c251e0a4750fac90ec8234ceb20438",
    ),
    (
        "basic — username populated",
        {
            "base_url": "https://api.example.com",
            "schedule": "daily",
            "platform_label": "Basic Test",
            "auth": {
                "kind": "basic",
                "username": "myuser",
                "secret_ref": "stash_basic",
            },
            "datasets": [
                {"id": "y", "endpoint": "/y", "timestamp_column": "updated_at"},
            ],
        },
        # Expected hash from canonical JSON:
        # {"auth":{"header_name":null,"kind":"basic","secret_ref":"stash_basic","username":"myuser"}, ...}
        "9c843bb5922239d8767b6fdcd46c32dbd934157347e9fb3593d369b751e37e35",
    ),
]

# The same fixtures in Pydantic snake_case form (what model_dump() returns).
# These must produce the SAME hashes as the camelCase wizard payloads above.
FIXTURES_SNAKE: list[tuple[str, Dict[str, Any], str]] = [
    (
        "api_key — snake_case, all optional fields as None",
        {
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
                    "id": "x",
                    "endpoint": "/x",
                    "json_root": None,
                    "timestamp_column": "ts",
                    "lands_in": None,
                    "cursor_param": None,
                },
            ],
        },
        "3800913628b86ed7d22613f94953901234f8188513fd4e1b28427eed79a4e9ad",
    ),
    (
        "bearer — snake_case, header_name=None, username=None",
        {
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
                },
            ],
        },
        "1a8115e2e0fef2226dec6939a7d7d64ce7c251e0a4750fac90ec8234ceb20438",
    ),
    (
        "basic — snake_case, username populated",
        {
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
                },
            ],
        },
        "9c843bb5922239d8767b6fdcd46c32dbd934157347e9fb3593d369b751e37e35",
    ),
]


@pytest.mark.parametrize("label,config,expected_hash", FIXTURES, ids=[f[0] for f in FIXTURES])
def test_python_hash_matches_expected_camel(label, config, expected_hash):
    """Python compute_config_hash matches hardcoded expected hash for wizard camelCase input.

    If this test fails, re-derive the expected hashes by running:
        python -c "from scanner.api.security.verify_token import compute_config_hash; ..."
    and update both this test AND the TS test in __tests__/server/verify-token.test.ts.
    """
    from scanner.api.security import verify_token

    actual = verify_token.compute_config_hash(config)
    assert actual == expected_hash, (
        f"[{label}] Hash mismatch.\n"
        f"  Expected: {expected_hash}\n"
        f"  Actual:   {actual}\n"
        "If you changed canonicalize_for_hash, update the expected hashes in BOTH "
        "this test AND __tests__/server/verify-token.test.ts."
    )


@pytest.mark.parametrize("label,config,expected_hash", FIXTURES_SNAKE, ids=[f[0] for f in FIXTURES_SNAKE])
def test_python_hash_matches_expected_snake(label, config, expected_hash):
    """Python compute_config_hash matches same hash for Pydantic snake_case model_dump input.

    Both camelCase and snake_case variants of the same logical config must hash identically.
    """
    from scanner.api.security import verify_token

    actual = verify_token.compute_config_hash(config)
    assert actual == expected_hash, (
        f"[{label}] Hash mismatch (snake_case form).\n"
        f"  Expected: {expected_hash}\n"
        f"  Actual:   {actual}\n"
        "camelCase and snake_case equivalents must produce the same hash."
    )


def test_canonical_json_snapshot():
    """Assert the canonical JSON string for the api_key fixture is exactly as expected.

    This is the ground truth that both Python and TypeScript hash.  If this
    string changes, the cross-language contract is broken and both tests must be
    updated together.
    """
    from scanner.api.security import verify_token

    config = FIXTURES[0][1]  # api_key fixture
    canonical = verify_token.canonicalize_for_hash(config)
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))

    expected_json = (
        '{"auth":{"header_name":"X-API-Key","kind":"api_key","secret_ref":"stash_abc","username":null},'
        '"base_url":"https://api.example.com/v1",'
        '"datasets":[{"cursor_param":null,"endpoint":"/x","id":"x","json_root":null,"lands_in":null,"timestamp_column":"ts"}],'
        '"platform_label":"Test","schedule":"daily"}'
    )
    assert serialized == expected_json, (
        f"Canonical JSON changed — this breaks the TypeScript hash contract.\n"
        f"  Expected: {expected_json}\n"
        f"  Actual:   {serialized}"
    )
    # Verify the SHA-256 of this canonical JSON string matches our hardcoded hash.
    computed_hash = hashlib.sha256(expected_json.encode("utf-8")).hexdigest()
    assert computed_hash == FIXTURES[0][2], (
        f"SHA-256 of canonical JSON does not match hardcoded expected hash.\n"
        f"  JSON:  {expected_json}\n"
        f"  Got:   {computed_hash}\n"
        f"  Expect:{FIXTURES[0][2]}"
    )
