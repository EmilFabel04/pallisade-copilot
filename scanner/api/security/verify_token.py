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
    Read from env var SOURCES_VERIFY_HMAC_SECRET.  If unset, behaviour depends
    on the runtime environment (ENVIRONMENT env var):
    - production: raises RuntimeError immediately — misconfiguration must be
      caught at deploy time, not masked by an ephemeral key that breaks under
      multi-worker uvicorn (each worker would generate a different key).
    - dev/test: generates an ephemeral key and logs a WARNING.  Tokens won't
      survive restarts and will NOT match across workers, but that's acceptable
      in non-production contexts.

Config hash canonicalization:
    ``compute_config_hash(d)`` normalises the input to a canonical shape before
    hashing so that both the wizard-side camelCase payload (TypeScript) and the
    Pydantic snake_case model_dump() produce the same hash.  See
    ``canonicalize_for_hash`` for the field projection rules.  The TypeScript
    counterpart in ``lib/server/verify-token.ts`` must produce the same hash
    for the same input or the gate is broken.
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
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SEC = 300  # 5 minutes


def _is_production() -> bool:
    """Return True when running in a production-class environment."""
    env = (os.environ.get("ENVIRONMENT") or "").strip().lower()
    return env in ("production", "prod")


def _load_hmac_secret() -> bytes:
    """Load SOURCES_VERIFY_HMAC_SECRET from env.

    In production: raises RuntimeError if the var is unset — a missing secret
    causes token mismatch across workers and must be caught at deploy time.
    In dev/test: falls back to an ephemeral key with a WARNING log.
    """
    raw = os.environ.get("SOURCES_VERIFY_HMAC_SECRET", "").strip()
    if raw:
        return raw.encode()
    if _is_production():
        raise RuntimeError(
            "SOURCES_VERIFY_HMAC_SECRET is not set in a production environment. "
            "Generate with: openssl rand -hex 32  and set it identically on ALL "
            "FastAPI workers before starting the process."
        )
    key = secrets.token_bytes(32)
    logger.warning(
        "SOURCES_VERIFY_HMAC_SECRET not set; using ephemeral key — "
        "verify tokens won't survive restarts and will fail across workers.  "
        "Set this env var (openssl rand -hex 32) before deploying to production."
    )
    return key


# Load once at module import.  Tests can monkeypatch os.environ before import
# or patch _HMAC_SECRET directly.
_HMAC_SECRET: bytes = _load_hmac_secret()


# ---------------------------------------------------------------------------
# Canonical projection
# ---------------------------------------------------------------------------


def canonicalize_for_hash(config: Dict[str, Any]) -> Dict[str, Any]:
    """Produce a canonical, shape-normalised representation of a source config.

    Accepts either:
    - Wizard-style camelCase payload (``headerName``, optional fields omitted)
    - Pydantic snake_case model_dump() (``header_name``, optional fields as None)

    Both inputs are mapped to the same projected shape so that
    ``compute_config_hash`` returns the same digest for equivalent configs.

    Canonical shape (all fields present; missing → null):
    {
        "auth": {
            "header_name": str | null,
            "kind": str,
            "secret_ref": str,
            "username": str | null
        },
        "base_url": str,
        "datasets": [
            {
                "cursor_param": str | null,
                "endpoint": str,
                "id": str,
                "json_root": str | null,
                "lands_in": str | null,
                "timestamp_column": str
            },
            ...
        ],
        "platform_label": str,
        "schedule": str
    }

    Note: ``sort_keys=True`` in ``json.dumps`` handles key ordering; this
    function only ensures every field is present with the right name.
    """
    raw_auth = config.get("auth") or {}
    auth: Dict[str, Any] = {
        "kind": raw_auth.get("kind", ""),
        # Accept camelCase (wizard) or snake_case (Pydantic model_dump)
        "header_name": raw_auth.get("header_name") or raw_auth.get("headerName") or None,
        "username": raw_auth.get("username") or None,
        "secret_ref": raw_auth.get("secret_ref") or raw_auth.get("secretRef") or "",
    }

    raw_datasets: List[Any] = config.get("datasets") or []
    datasets: List[Dict[str, Any]] = []
    for ds in raw_datasets:
        datasets.append({
            "id": ds.get("id", ""),
            "endpoint": ds.get("endpoint", ""),
            "json_root": ds.get("json_root") or ds.get("jsonRoot") or None,
            "timestamp_column": ds.get("timestamp_column") or ds.get("timestampColumn") or "",
            "lands_in": ds.get("lands_in") or ds.get("landsIn") or None,
            "cursor_param": ds.get("cursor_param") or ds.get("cursorParam") or None,
        })

    return {
        "base_url": config.get("base_url") or config.get("baseUrl") or "",
        "schedule": config.get("schedule") or "",
        "platform_label": config.get("platform_label") or config.get("platformLabel") or "",
        "auth": auth,
        "datasets": datasets,
    }


def compute_config_hash(config: dict) -> str:
    """Return SHA-256 hex digest of the canonical JSON representation of *config*.

    Normalises *config* via ``canonicalize_for_hash`` before hashing so that
    wizard camelCase and Pydantic snake_case inputs produce the same digest.
    Canonical = sorted keys, no whitespace separators.  Must match the
    TypeScript ``computeConfigHash`` in ``lib/server/verify-token.ts``.
    """
    canonical = canonicalize_for_hash(config)
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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
