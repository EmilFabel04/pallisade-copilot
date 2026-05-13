"""emit_artifact — single helper that turns a successful write-tool call
into an Artifact row. Idempotent on (tool_call_id, kind).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Union

from pydantic import BaseModel

from .models import ArtifactKind, ArtifactRisk, ArtifactSpec, ArtifactStatus


def _serialise_payload(payload: Union[BaseModel, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(payload, BaseModel):
        return payload.model_dump()
    return dict(payload)


async def emit_artifact(
    *,
    repo: Any,  # ArtifactRepo (any object with .upsert(**kwargs))
    spec: ArtifactSpec,
    tool_call_id: str,
    agent_run_id: str,
    payload: Union[BaseModel, Dict[str, Any]],
    title: str,
    status: ArtifactStatus,
    summary: Optional[str] = None,
    subtype: Optional[str] = None,
    source_session_id: Optional[str] = None,
    source_message_id: Optional[str] = None,
    agent_session_id: Optional[str] = None,
    integration_id: Optional[str] = None,
    external_ref: Optional[Dict[str, Any]] = None,
    risk_level: Optional[ArtifactRisk] = None,
    rollback_hint: Optional[str] = None,
    is_saved: bool = False,
) -> Dict[str, Any]:
    """Persist (upsert) an Artifact row. Returns the persisted row dict.

    Idempotency key: prefer ``f"agent_session:{agent_session_id}"`` so that
    ``begin_artefact``'s pre-created draft and the subsequent write-tool
    auto-emit collapse to the SAME row. Fall back to
    ``f"{tool_call_id}:{spec.kind}"`` for write tools fired without a
    preceding ``begin_artefact``.
    """
    # Prefer agent_session_id as the identity key so begin_artefact + subsequent
    # write-tool auto-emits in the same turn collapse to one row.
    if agent_session_id:
        idempotency_key = f"agent_session:{agent_session_id}"
    else:
        idempotency_key = f"{tool_call_id}:{spec.kind}"
    return await repo.upsert(
        idempotency_key=idempotency_key,
        kind=ArtifactKind(spec.kind),
        status=status,
        payload=_serialise_payload(payload),
        title=title,
        summary=summary,
        subtype=subtype,
        source_session_id=source_session_id,
        source_message_id=source_message_id,
        agent_session_id=agent_session_id,
        tool_call_id=tool_call_id,
        agent_run_id=agent_run_id,
        integration_id=integration_id,
        external_ref=external_ref,
        risk_level=risk_level,
        rollback_hint=rollback_hint,
        is_saved=is_saved,
    )
