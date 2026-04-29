"""Eager context loading before iter 0.

When a user asks an investigative question ("are my monitors failing", "what's
broken", etc.), the LLM previously had to spend an iteration calling
`list_configured_monitors` just to find out the high-level shape of the user's
monitor inventory. This module pre-fires that call (with a tight timeout) and
stuffs the resulting summary into the system prompt, so the LLM either answers
directly from the snapshot or drills into specifics from a more informed
position.

Design constraints:
- Only fires for investigative queries (reuses the same regex as iter-0
  tool-forcing) so non-investigative questions don't pay the latency cost.
- Per-call timeout (default 2s) — partial failure is fine; we return whatever
  succeeded.
- All exceptions swallowed at the per-task level — prefetch must never crash
  the chat loop.
- Returns None when the query is non-investigative or every task failed; the
  system-prompt builder treats None as "no snapshot section".
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from .llm import _should_force_initial_tool

logger = logging.getLogger(__name__)


def _summarise_monitors(data: Any) -> Optional[Dict[str, Any]]:
    """Compute a count summary from a `list_configured_monitors` result.
    Defensive across the heterogeneous shapes the tool can return."""
    monitors = None
    if isinstance(data, list):
        monitors = data
    elif isinstance(data, dict):
        for key in ("monitors", "items", "results"):
            if isinstance(data.get(key), list):
                monitors = data[key]
                break
    if monitors is None:
        return None

    by_status: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    for m in monitors:
        if not isinstance(m, dict):
            continue
        status = (m.get("status") or m.get("last_status") or "UNKNOWN")
        mtype = (m.get("type") or m.get("monitor_type") or "UNKNOWN")
        by_status[str(status).upper()] = by_status.get(str(status).upper(), 0) + 1
        by_type[str(mtype).upper()] = by_type.get(str(mtype).upper(), 0) + 1

    return {
        "total": len(monitors),
        "by_status": by_status,
        "by_type": by_type,
    }


async def _safe_run(coro, timeout: float, label: str) -> Optional[Any]:
    """Run an awaitable with timeout, returning None on any failure / timeout."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.info(f"[Prefetch] {label} timed out after {timeout}s — skipping")
        return None
    except Exception as e:
        logger.info(f"[Prefetch] {label} failed: {e} — skipping")
        return None


async def prefetch_for_query(
    context: Any,  # CopilotContext (avoid circular import)
    query: str,
    executor: Any,  # ToolExecutor
    timeout: float = 2.0,
) -> Optional[Dict[str, Any]]:
    """Prefetch aggregate state for investigative queries. Returns None when:
    - query is non-investigative (skip entirely)
    - every prefetch task failed/timed out
    Otherwise returns a partial dict — keys present iff that task succeeded."""
    if not _should_force_initial_tool(query):
        return None

    snapshot: Dict[str, Any] = {}

    monitors_result = await _safe_run(
        executor.execute("list_configured_monitors", {}),
        timeout=timeout,
        label="list_configured_monitors",
    )
    if monitors_result is not None and getattr(monitors_result, "success", False):
        summary = _summarise_monitors(getattr(monitors_result, "data", None))
        if summary is not None:
            snapshot["monitors"] = summary

    return snapshot or None


def render_snapshot_section(snapshot: Optional[Dict[str, Any]]) -> str:
    """Render a prefetched snapshot as a system-prompt section. Empty string
    if the snapshot is None or empty — caller can concatenate unconditionally."""
    if not snapshot:
        return ""

    lines = ["## Pre-loaded Snapshot (from this session — accurate as of iter 0)"]
    lines.append(
        "These figures were fetched before you saw the user's question. Use them "
        "directly when the user asks high-level 'how many X' questions; you only "
        "need a fresh tool call for details, drilling into specifics, or to "
        "confirm a number that needs to be exact right now."
    )

    monitors = snapshot.get("monitors")
    if monitors:
        total = monitors.get("total", 0)
        lines.append(f"\n**Monitors configured**: {total}")
        by_status = monitors.get("by_status") or {}
        if by_status:
            parts = ", ".join(f"{s}: {n}" for s, n in sorted(by_status.items()))
            lines.append(f"  - by status: {parts}")
        by_type = monitors.get("by_type") or {}
        if by_type:
            top = sorted(by_type.items(), key=lambda kv: -kv[1])[:8]
            parts = ", ".join(f"{t}: {n}" for t, n in top)
            lines.append(f"  - by type: {parts}")

    return "\n".join(lines) + "\n"
