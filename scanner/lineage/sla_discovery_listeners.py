"""Re-run hooks for tentative SLA discoveries when a clarification resolves.

When the user answers a ``timestamp_choice`` (or any other discovery-affecting
clarification), the FastAPI process emits ``context_resolved`` on the in-process
event bus. Guessers that produced tentative results subscribe here so they can
schedule a re-run.

V1 is a logged no-op:
  - Re-running ``discover_sla_profile_for_node`` requires the original adapter
    config (cached in ``_lineage_cache.get_tool_configs``) plus the lineage
    graph. We do not retain that across the FastAPI request boundary today.
  - The frontend already polls ``/api/context-requests`` after answering, so
    a stale tentative discovery is dropped naturally on the next user-driven
    refresh of the SLA editor.
  - A future iteration can plug a background job queue here.

Registration is wired in ``scanner/api/app.py`` at startup so the listener is
present before any clarifications can resolve.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from copilot.clarifications.events import BUS

logger = logging.getLogger(__name__)


def _on_resolved(payload: Dict[str, Any]) -> None:
    """Log the resolution; future iteration triggers a discovery refresh."""
    try:
        kind = payload.get("kind")
        scope_ref = payload.get("scope_ref")
        if kind != "timestamp_choice":
            return
        logger.info(
            "[SLA Discovery] context_resolved kind=%s scope_ref=%s — discovery re-run is "
            "deferred to the next user-triggered refresh (no background queue in v1).",
            kind,
            scope_ref,
        )
    except Exception:
        # Listeners must never blow up the producer. Log and move on.
        logger.debug("[SLA Discovery] _on_resolved raised", exc_info=True)


_REGISTERED = False


def register() -> None:
    """Subscribe ``_on_resolved`` to the ``context_resolved`` bus event.

    Idempotent — calling twice is a safe no-op so reload-friendly setups
    (uvicorn --reload, tests) do not stack duplicate handlers.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    BUS.subscribe("context_resolved", _on_resolved)
    _REGISTERED = True
