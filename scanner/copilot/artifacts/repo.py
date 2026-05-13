"""Persistence layer for artefacts — calls the Next.js /api/artifacts routes
using the same internal-API pattern as _execute_run_watch (tool_executor.py:6110).
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import aiohttp

from .models import ArtifactKind, ArtifactStatus, ArtifactRisk


class ArtifactRepo:
    """HTTP-backed repo. Talks to /api/artifacts/internal/* with X-Internal-Secret."""

    def __init__(self, base_url: str, org_id: str, user_id: str):
        self.base_url = base_url
        self.org_id = org_id
        self.user_id = user_id

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Internal-Secret": os.environ.get("INTERNAL_API_SECRET", "pallisade-internal"),
            "X-Organization-Id": self.org_id,
            "X-User-Id": self.user_id,
            "Content-Type": "application/json",
        }

    async def upsert(
        self,
        *,
        idempotency_key: str,
        kind: ArtifactKind,
        status: ArtifactStatus,
        payload: Dict[str, Any],
        title: str,
        summary: Optional[str] = None,
        subtype: Optional[str] = None,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        agent_session_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        agent_run_id: Optional[str] = None,
        integration_id: Optional[str] = None,
        external_ref: Optional[Dict[str, Any]] = None,
        risk_level: Optional[ArtifactRisk] = None,
        rollback_hint: Optional[str] = None,
        is_saved: bool = False,
    ) -> Dict[str, Any]:
        body = {
            "idempotencyKey": idempotency_key,
            "kind": kind.value,
            "status": status.value,
            "subtype": subtype,
            "payload": payload,
            "title": title,
            "summary": summary,
            "sourceSessionId": source_session_id,
            "sourceMessageId": source_message_id,
            "agentSessionId": agent_session_id,
            "toolCallId": tool_call_id,
            "agentRunId": agent_run_id,
            "integrationId": integration_id,
            "externalRef": external_ref,
            "riskLevel": risk_level.value if risk_level else None,
            "rollbackHint": rollback_hint,
            "isSaved": is_saved,
        }
        url = f"{self.base_url}/api/artifacts/internal/upsert"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self._headers(), json=body) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    raise RuntimeError(f"ArtifactRepo.upsert failed ({resp.status}): {text}")
                return await resp.json()

    async def update_status(
        self,
        artifact_id: str,
        status: ArtifactStatus,
        *,
        external_ref_patch: Optional[Dict[str, Any]] = None,
        payload_patch: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"status": status.value}
        if external_ref_patch is not None:
            body["externalRefPatch"] = external_ref_patch
        if payload_patch is not None:
            body["payloadPatch"] = payload_patch
        url = f"{self.base_url}/api/artifacts/internal/{artifact_id}"
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self._headers(), json=body) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"ArtifactRepo.update_status failed ({resp.status}): {text}")
                return await resp.json()
