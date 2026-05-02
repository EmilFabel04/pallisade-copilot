"""
Verify-token helpers for the Custom Source integration flow.

After the /verify endpoint completes a successful probe run (all_pass=True),
it issues a short-lived HMAC-signed verify_token.  The Next.js persist route
(/api/integrations) must present this token; if absent or invalid, persist is
rejected — closing the server-side verify gate.

Token format:
    <base64url(json_payload)>.<hex_hmac_sha256>

Payload keys:
    org_id       — the organization that performed the verify run.
    config_hash  — SHA-256 of the canonical verify body (sorted-key JSON).
    exp          — UNIX epoch second at which the token expires.

HMAC secret:
    Read from env var SOURCES_VERIFY_HMAC_SECRET.  If unset at module load,
    an ephemeral key is generated and a WARNING is logged.  Tokens issued with
    an ephemeral key will NOT survive a process restart.

Config hash canonicalization:
    ``compute_config_hash(d)`` dumps *d* as canonical JSON (sorted keys, no
    whitespace) and returns the SHA-256 hex digest.  The TypeScript counterpart
    in ``lib/server/verify-token.ts`` must produce the same hash for the same
    input — use the same canonical algorithm or the gate is broken.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SEC = 300  # 5 minutes


def _load_hmac_secret() -> bytes:
    """Load SOURCES_VERIFY_HMAC_SECRET from env, falling back to an ephemeral key."""
    raw = os.environ.get("SOURCES_VERIFY_HMAC_SECRET", "").strip()
    if raw:
        return raw.encode()
    key = secrets.token_bytes(32)
    logger.warning(
        "SOURCES_VERIFY_HMAC_SECRET not set; using ephemeral key — "
        "verify tokens won't survive restarts.  Set this env var in production."
    )
    return key


# Load once at module import.  Tests can monkeypatch os.environ before import
# or patch _HMAC_SECRET directly.
_HMAC_SECRET: bytes = _load_hmac_secret()


def compute_config_hash(verify_body_dict: dict) -> str:
    """Return SHA-256 hex digest of the canonical JSON representation of *verify_body_dict*.

    Canonical = sorted keys, no whitespace separators.  Must match the
    TypeScript ``computeConfigHash`` in ``lib/server/verify-token.ts``.
    """
    canonical = json.dumps(verify_body_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def issue_verify_token(
    payload: dict,
    secret: Optional[bytes] = None,
    ttl_sec: int = _DEFAULT_TTL_SEC,
) -> str:
    """Create a signed verify token.

    Args:
        payload: Dict containing at least ``org_id`` and ``config_hash``.
                 A fresh ``exp`` key is added automatically.
        secret:  HMAC key; defaults to the module-level ``_HMAC_SECRET``.
        ttl_sec: Token lifetime in seconds (default 5 minutes).

    Returns:
        A dot-separated string ``<base64url_payload>.<hex_signature>``.
    """
    key = secret if secret is not None else _HMAC_SECRET
    payload = {**payload, "exp": int(time.time()) + ttl_sec}
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
    sig = hmac.new(key, b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def validate_verify_token(
    token: str,
    expected_org_id: str,
    expected_config_hash: str,
    secret: Optional[bytes] = None,
) -> Tuple[bool, Optional[str]]:
    """Validate a verify token.

    Returns:
        ``(True, None)`` if the token is valid.
        ``(False, reason)`` if any check fails.
    """
    key = secret if secret is not None else _HMAC_SECRET

    # ── 1. Parse structure ────────────────────────────────────────────────────
    parts = token.split(".")
    if len(parts) != 2:
        return False, "malformed token"

    b64_part, provided_sig = parts

    # ── 2. Verify signature (constant-time) ───────────────────────────────────
    expected_sig = hmac.new(key, b64_part.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        return False, "signature mismatch"

    # ── 3. Decode payload ─────────────────────────────────────────────────────
    # Re-add stripped padding.
    padding = 4 - len(b64_part) % 4
    padded = b64_part + ("=" * (padding % 4))
    try:
        payload_bytes = base64.urlsafe_b64decode(padded)
        payload = json.loads(payload_bytes)
    except Exception:
        return False, "payload decode error"

    # ── 4. Expiry ─────────────────────────────────────────────────────────────
    exp = payload.get("exp")
    if exp is None or int(time.time()) > exp:
        return False, "token expired"

    # ── 5. Org check ─────────────────────────────────────────────────────────
    if payload.get("org_id") != expected_org_id:
        return False, "org_id mismatch"

    # ── 6. Config hash ───────────────────────────────────────────────────────
    if payload.get("config_hash") != expected_config_hash:
        return False, "config_hash mismatch"

    return True, None
