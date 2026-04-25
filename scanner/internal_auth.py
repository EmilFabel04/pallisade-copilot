"""Shared accessor for INTERNAL_API_KEY used by server-to-server auth."""

import os
from typing import Optional

_DEV_FALLBACK = "dev-internal-key-not-for-production"
INTERNAL_API_KEY_HEADER = "x-internal-api-key"

_warned = False


def get_internal_api_key() -> str:
    """Return the configured INTERNAL_API_KEY, or fail loudly in production.

    In non-production environments, falls back to a fixed dev value with a
    one-time warning so local workflows still function. In production, raises
    if the env var is unset rather than silently using a guessable secret.
    """
    global _warned
    key: Optional[str] = os.environ.get("INTERNAL_API_KEY")
    if key:
        return key

    env = (os.environ.get("ENVIRONMENT") or os.environ.get("NODE_ENV") or "").strip().lower()
    if env == "production":
        raise RuntimeError(
            "INTERNAL_API_KEY is not set. Refusing to use the dev fallback in production."
        )
    if not _warned:
        import sys

        print(
            "[security] INTERNAL_API_KEY is unset — using insecure dev fallback. "
            "Set INTERNAL_API_KEY (e.g. `openssl rand -hex 32`) before deploying.",
            file=sys.stderr,
        )
        _warned = True
    return _DEV_FALLBACK
