"""Integration health snapshots — structured failure reasons.

The default ``ConnectionResult`` carries only ``ok`` and a human string,
which means the LLM gets "Metabase connection failed: 503" instead of
"Metabase trial expired / instance deprovisioned (BILLING)". This
module adds a classification layer that maps provider-specific
responses to canonical ``FailureCategory`` values plus a small store
that persists the latest snapshot per ``(org_id, pipeline_id,
integration_type)``.

Why a separate module:

* The classifier needs per-provider patterns that don't belong in
  ``ConnectionResult`` itself.
* Snapshots persist beyond a single ``test_connection`` call so the
  copilot can answer "why is Metabase down?" without re-probing.
* User-provided corrections ("it's billing, I cancelled my trial")
  attach to the snapshot as a high-signal annotation that survives
  subsequent classifier runs.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Failure categories
# ---------------------------------------------------------------------------


class FailureCategory(str, Enum):
    """Canonical reason a connection didn't work.

    Inherits from str so dict serialization and JSON round-trips
    produce readable values. The categories are deliberately coarse —
    a follow-up classifier can refine inside one category without
    breaking downstream consumers that branch on the top-level value.
    """
    AUTH = "AUTH"                # 401, invalid token, expired key
    NOT_FOUND = "NOT_FOUND"      # 404, resource gone, instance deleted
    BILLING = "BILLING"          # trial expired, payment required, subscription suspended
    RATE_LIMIT = "RATE_LIMIT"    # 429, throttled
    CONFIG = "CONFIG"            # bad URL, missing required field, malformed creds
    NETWORK = "NETWORK"          # DNS failure, connection refused, timeout
    SERVER = "SERVER"            # 5xx that isn't billing-related
    UNKNOWN = "UNKNOWN"          # classifier couldn't decide; raw message preserved


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


@dataclass
class IntegrationHealth:
    """One health snapshot for a single (tenant, pipeline, integration).

    Fields beyond ``status`` and ``reason`` are optional because not
    every detection path produces them — a TCP-level failure has no
    ``status_code``; a structured-billing-page detection has no
    ``provider_error_code``. The classifier fills what it can.
    """
    integration_type: str
    status: str                              # "OK" / "FAILED"
    failure_category: Optional[FailureCategory] = None
    reason: str = ""                         # human one-liner
    observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    status_code: Optional[int] = None
    provider_error_code: Optional[str] = None
    provider_error_message: Optional[str] = None
    is_retryable: Optional[bool] = None
    # High-signal override the user supplied via chat. When present,
    # downstream consumers (and the LLM) should treat this as more
    # authoritative than the auto-classification.
    user_annotation: Optional[str] = None
    # Free-form evidence (response excerpt, status page link, etc.)
    # the classifier collected while deciding the category.
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "integration_type": self.integration_type,
            "status": self.status,
            "failure_category": (
                self.failure_category.value if self.failure_category else None
            ),
            "reason": self.reason,
            "observed_at": self.observed_at.isoformat(),
            "status_code": self.status_code,
            "provider_error_code": self.provider_error_code,
            "provider_error_message": self.provider_error_message,
            "is_retryable": self.is_retryable,
            "user_annotation": self.user_annotation,
            "evidence": self.evidence,
        }

    @property
    def ok(self) -> bool:
        return self.status == "OK"


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


# Patterns that indicate billing problems regardless of provider. The
# classifier checks these before category-specific patterns because a
# trial-expired response can come back wearing many costumes (HTTP 402,
# HTTP 503 with a billing page, HTTP 200 with a redirect to an upgrade
# page). The user's original incident (Metabase Cloud trial expired,
# instance deprovisioned) wouldn't surface as a clean 402 — it returns
# the marketing site or a "subscription required" page.
_BILLING_PHRASES = re.compile(
    r"\b("
    r"trial\s+(expired|ended|over)|"
    r"subscription\s+(required|expired|cancelled|canceled|inactive)|"
    r"payment\s+(required|overdue|failed)|"
    r"upgrade\s+(required|your\s+plan)|"
    r"plan\s+(expired|cancelled|canceled)|"
    r"billing\s+(issue|problem|required)|"
    r"account\s+suspended|"
    r"deprovisioned|"
    r"instance\s+(suspended|deprovisioned|deleted)"
    r")\b",
    re.IGNORECASE,
)

_AUTH_PHRASES = re.compile(
    r"\b("
    r"unauthori[sz]ed|"
    r"invalid\s+(api\s+key|token|credentials?)|"
    r"authentication\s+failed|"
    r"expired\s+(token|key|credentials?)|"
    r"forbidden|access\s+denied"
    r")\b",
    re.IGNORECASE,
)

_NOT_FOUND_PHRASES = re.compile(
    r"\b("
    r"not\s+found|does\s+not\s+exist|no\s+such\s+(host|database|table)|"
    r"resource\s+(missing|gone)"
    r")\b",
    re.IGNORECASE,
)

_RATE_LIMIT_PHRASES = re.compile(
    r"\b(rate[-\s]?limit|throttl(?:ed|ing)|too\s+many\s+requests)\b",
    re.IGNORECASE,
)

_NETWORK_PHRASES = re.compile(
    r"\b("
    r"connection\s+(refused|reset|aborted|timed?\s*out)|"
    r"name\s+or\s+service\s+not\s+known|"
    r"temporary\s+failure\s+in\s+name\s+resolution|"
    r"dns\s+(lookup\s+)?(failed|error)|"
    r"timeout|timed?\s*out|"
    r"network\s+(is\s+)?unreachable|"
    r"no\s+route\s+to\s+host"
    r")\b",
    re.IGNORECASE,
)

_CONFIG_PHRASES = re.compile(
    r"\b("
    r"missing\s+(required|config|configuration)|"
    r"invalid\s+(url|host|port|configuration)|"
    r"malformed\s+(url|key|credentials?)|"
    r"required\s+field"
    r")\b",
    re.IGNORECASE,
)


def classify_error(
    *,
    integration_type: str,
    status_code: Optional[int] = None,
    message: str = "",
    response_body: Optional[str] = None,
) -> Tuple[FailureCategory, bool]:
    """Map a raw error to ``(FailureCategory, is_retryable)``.

    Order of evidence:
    1. Billing phrases — they trump status codes because billing pages
       commonly arrive as 200/302/503 in disguise.
    2. Status code (when meaningful: 401/403/404/429/402/5xx).
    3. Auth / not-found / rate-limit / network / config phrases.
    4. Default to UNKNOWN with retry=False so the system doesn't
       hammer a degraded endpoint on guesswork.

    ``integration_type`` is currently unused by the generic classifier
    but reserved for per-provider overrides (e.g. detecting a
    Metabase-specific upgrade redirect that doesn't trip the generic
    phrase set).
    """
    haystack = " ".join(filter(None, [message or "", response_body or ""]))

    if _BILLING_PHRASES.search(haystack):
        return FailureCategory.BILLING, False

    if status_code is not None:
        if status_code == 401 or status_code == 403:
            return FailureCategory.AUTH, False
        if status_code == 404:
            return FailureCategory.NOT_FOUND, False
        if status_code == 402:
            return FailureCategory.BILLING, False
        if status_code == 429:
            return FailureCategory.RATE_LIMIT, True
        if 500 <= status_code < 600:
            return FailureCategory.SERVER, True

    if _AUTH_PHRASES.search(haystack):
        return FailureCategory.AUTH, False
    if _NOT_FOUND_PHRASES.search(haystack):
        return FailureCategory.NOT_FOUND, False
    if _RATE_LIMIT_PHRASES.search(haystack):
        return FailureCategory.RATE_LIMIT, True
    if _NETWORK_PHRASES.search(haystack):
        return FailureCategory.NETWORK, True
    if _CONFIG_PHRASES.search(haystack):
        return FailureCategory.CONFIG, False

    return FailureCategory.UNKNOWN, False


def build_failure_snapshot(
    *,
    integration_type: str,
    status_code: Optional[int] = None,
    message: str = "",
    response_body: Optional[str] = None,
    provider_error_code: Optional[str] = None,
) -> IntegrationHealth:
    """Convenience: classify and build a FAILED snapshot in one call.

    Most callers don't need to construct ``IntegrationHealth``
    by hand — they have a raw error and want a structured snapshot.
    """
    category, retryable = classify_error(
        integration_type=integration_type,
        status_code=status_code,
        message=message,
        response_body=response_body,
    )
    return IntegrationHealth(
        integration_type=integration_type,
        status="FAILED",
        failure_category=category,
        reason=_default_reason(category, message),
        status_code=status_code,
        provider_error_code=provider_error_code,
        provider_error_message=message or None,
        is_retryable=retryable,
        evidence={"response_excerpt": (response_body or "")[:500]} if response_body else {},
    )


def _default_reason(category: FailureCategory, message: str) -> str:
    """Human one-liner for the snapshot ``reason`` field.

    Falls back to the raw message when the category is UNKNOWN so we
    don't overwrite the only signal we had with a generic phrase.
    """
    presets = {
        FailureCategory.AUTH: "Authentication failed — credentials may be invalid or expired",
        FailureCategory.NOT_FOUND: "Resource not found at the configured endpoint",
        FailureCategory.BILLING: "Likely billing issue — trial may have expired or subscription is suspended",
        FailureCategory.RATE_LIMIT: "Rate limited by the provider",
        FailureCategory.CONFIG: "Configuration issue — required field missing or malformed",
        FailureCategory.NETWORK: "Network failure — provider unreachable from this host",
        FailureCategory.SERVER: "Provider returned a server error",
    }
    return presets.get(category) or (message or "Unknown failure")


# ---------------------------------------------------------------------------
# Health store
# ---------------------------------------------------------------------------


# Composite key: (org_id, pipeline_id, integration_type). The first two
# default to "_default" when not provided so tests and CLI invocations
# without a tenant context still get a usable bucket — same pattern the
# specialist response cache uses (see Tier-4 item 2).
_HealthKey = Tuple[str, str, str]


class HealthStore:
    """Thread-safe in-memory store for the latest snapshot per
    ``(org_id, pipeline_id, integration_type)``.

    Snapshots are not persisted across process restarts. A future
    follow-up can persist to disk or DB; the surface here was chosen
    so that change is invisible to callers — they go through ``record``
    / ``get`` / ``list_for`` regardless of backing store.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshots: Dict[_HealthKey, IntegrationHealth] = {}

    @staticmethod
    def _key(
        org_id: Optional[str],
        pipeline_id: Optional[str],
        integration_type: str,
    ) -> _HealthKey:
        return (
            org_id or "_default",
            pipeline_id or "_default",
            integration_type.upper(),
        )

    def record(
        self,
        snapshot: IntegrationHealth,
        *,
        org_id: Optional[str] = None,
        pipeline_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._snapshots[
                self._key(org_id, pipeline_id, snapshot.integration_type)
            ] = snapshot

    def get(
        self,
        integration_type: str,
        *,
        org_id: Optional[str] = None,
        pipeline_id: Optional[str] = None,
    ) -> Optional[IntegrationHealth]:
        with self._lock:
            return self._snapshots.get(self._key(org_id, pipeline_id, integration_type))

    def list_for(
        self,
        *,
        org_id: Optional[str] = None,
        pipeline_id: Optional[str] = None,
    ) -> List[IntegrationHealth]:
        prefix = (org_id or "_default", pipeline_id or "_default")
        with self._lock:
            return [
                snap
                for key, snap in self._snapshots.items()
                if key[:2] == prefix
            ]

    def annotate(
        self,
        integration_type: str,
        annotation: str,
        *,
        org_id: Optional[str] = None,
        pipeline_id: Optional[str] = None,
    ) -> Optional[IntegrationHealth]:
        """Attach a user-provided correction to the latest snapshot.

        Returns the updated snapshot, or None if no snapshot exists
        yet (the user can't annotate something we haven't observed).
        """
        with self._lock:
            key = self._key(org_id, pipeline_id, integration_type)
            existing = self._snapshots.get(key)
            if existing is None:
                return None
            existing.user_annotation = annotation
            return existing

    def clear(self) -> None:
        """Test hook."""
        with self._lock:
            self._snapshots.clear()


# Module-level singleton for ergonomics. Production code should pass
# the store explicitly; the singleton is for incremental adoption
# while individual call sites are migrated.
_default_store = HealthStore()


def get_default_store() -> HealthStore:
    return _default_store
