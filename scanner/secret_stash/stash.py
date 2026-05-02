"""
Ephemeral secret stash for wizard sessions.

Stores raw credentials in a short-lived in-process TTLCache keyed by an opaque
``stash_<uuid4>`` reference.  The stash is intentionally ephemeral:

- Secrets expire after 30 minutes (enough for one wizard session).
- Owner isolation: the cache key includes the owner user_id, so a ref can only
  be resolved by the user who created it.
- NOT persisted: on process restart the stash is empty.

Thread-safety note: cachetools.TTLCache is NOT thread-safe.  We rely on
FastAPI's single-threaded asyncio event loop.  Do NOT switch to a
multi-threaded WSGI runner without wrapping this with a threading.Lock.

TODO: Replace the in-process TTLCache with Redis for multi-worker production
deployments.  With the current implementation, a wizard session that is routed
to a different worker will fail to resolve its stash ref.
"""

from __future__ import annotations

import uuid
from typing import Optional

from cachetools import TTLCache

# 30-minute TTL — long enough to survive a full wizard session.
_STASH_TTL_SECONDS = 1800
_STASH: TTLCache = TTLCache(maxsize=1024, ttl=_STASH_TTL_SECONDS)


class SecretNotFoundError(Exception):
    """Raised when a stash ref cannot be resolved (expired / unknown / wrong owner)."""


def stash_secret(secret: str, owner_id: str) -> str:
    """Store *secret* and return an opaque stash ref.

    Args:
        secret: The raw credential value (API key, bearer token, password, …).
        owner_id: The user ID of the user who owns this secret.

    Returns:
        An opaque ref string like ``stash_<uuid4>`` that can be passed to
        :func:`resolve_secret_ref` to retrieve the original secret.
    """
    ref = f"stash_{uuid.uuid4().hex}"
    _STASH[(ref, owner_id)] = secret
    return ref


def resolve_secret_ref(ref: str, owner_id: str) -> Optional[str]:
    """Look up *ref* and return the secret if it exists and is owned by *owner_id*.

    Returns ``None`` if the ref is expired, unknown, or belongs to a different user.
    Does NOT raise — the caller is responsible for converting ``None`` into an
    appropriate HTTP error.
    """
    return _STASH.get((ref, owner_id))
