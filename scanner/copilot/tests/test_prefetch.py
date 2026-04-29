"""Eager context prefetch (`copilot.prefetch`) — fires for investigative queries
only, returns a partial snapshot that build_system_prompt renders into a
'Pre-loaded Snapshot' section, never crashes the chat loop on tool failure or
timeout."""
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest

from copilot.prefetch import (
    _summarise_monitors,
    prefetch_for_query,
    render_snapshot_section,
)
from copilot.tools import ToolResult


# -- _summarise_monitors ------------------------------------------------------


def test_summarise_monitors_handles_raw_list():
    data = [
        {"id": "m1", "type": "FRESHNESS", "status": "PASS"},
        {"id": "m2", "type": "FRESHNESS", "status": "FAIL"},
        {"id": "m3", "type": "VOLUME", "status": "PASS"},
    ]
    s = _summarise_monitors(data)
    assert s == {
        "total": 3,
        "by_status": {"PASS": 2, "FAIL": 1},
        "by_type": {"FRESHNESS": 2, "VOLUME": 1},
    }


def test_summarise_monitors_handles_dict_with_monitors_key():
    data = {"monitors": [
        {"id": "m1", "type": "DBT_CORE_SOURCE_VALIDATION", "status": "ERROR"},
    ], "count": 1}
    s = _summarise_monitors(data)
    assert s["total"] == 1
    assert s["by_status"] == {"ERROR": 1}
    assert s["by_type"] == {"DBT_CORE_SOURCE_VALIDATION": 1}


def test_summarise_monitors_returns_none_for_unrecognised_shape():
    assert _summarise_monitors(None) is None
    assert _summarise_monitors("string-not-list") is None
    assert _summarise_monitors({"unrelated": 42}) is None


def test_summarise_monitors_falls_back_for_missing_status_or_type():
    data = [{"id": "m1"}, {"id": "m2", "status": "PASS"}]
    s = _summarise_monitors(data)
    assert s["total"] == 2
    assert s["by_status"] == {"UNKNOWN": 1, "PASS": 1}
    assert s["by_type"] == {"UNKNOWN": 2}


# -- prefetch_for_query — gating + execution ---------------------------------


@dataclass
class _FakeExecutor:
    """Minimal stand-in for ToolExecutor — records calls and returns scripted results."""
    result: Optional[Any] = None
    raises: Optional[Exception] = None
    sleep: float = 0.0
    calls: list = None

    def __post_init__(self):
        self.calls = []

    async def execute(self, tool_name: str, args: Dict[str, Any]):
        self.calls.append((tool_name, args))
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.raises:
            raise self.raises
        return self.result


def test_prefetch_skipped_for_non_investigative_queries():
    executor = _FakeExecutor(result=ToolResult(success=True, data=[]))
    result = asyncio.run(prefetch_for_query(None, "thanks!", executor))
    assert result is None
    assert executor.calls == []  # no tool calls fired


def test_prefetch_fires_for_investigative_queries():
    monitors = [
        {"id": "m1", "type": "DBT_CORE_SOURCE_VALIDATION", "status": "FAIL"},
        {"id": "m2", "type": "FRESHNESS", "status": "PASS"},
    ]
    executor = _FakeExecutor(result=ToolResult(success=True, data={"monitors": monitors}))
    result = asyncio.run(prefetch_for_query(None, "why are my monitors failing", executor))

    assert result is not None
    assert "monitors" in result
    assert result["monitors"]["total"] == 2
    assert executor.calls == [("list_configured_monitors", {})]


def test_prefetch_returns_none_when_tool_fails():
    executor = _FakeExecutor(raises=RuntimeError("boom"))
    result = asyncio.run(prefetch_for_query(None, "are my monitors broken", executor))
    assert result is None  # all tasks failed → empty snapshot → None


def test_prefetch_respects_timeout():
    """A slow executor must not hang the chat loop — we time out and skip."""
    executor = _FakeExecutor(
        result=ToolResult(success=True, data=[]),
        sleep=10.0,  # well over the timeout
    )
    result = asyncio.run(
        prefetch_for_query(None, "is dbt connected", executor, timeout=0.05)
    )
    assert result is None


def test_prefetch_returns_none_when_tool_reports_failure_status():
    """A successfully-returned ToolResult with success=False still means no usable
    data — don't include the key."""
    executor = _FakeExecutor(result=ToolResult(success=False, error="auth expired"))
    result = asyncio.run(prefetch_for_query(None, "show failing monitors", executor))
    assert result is None


# -- render_snapshot_section --------------------------------------------------


def test_render_snapshot_section_returns_empty_string_for_none():
    assert render_snapshot_section(None) == ""
    assert render_snapshot_section({}) == ""


def test_render_snapshot_section_includes_total_and_breakdowns():
    snapshot = {
        "monitors": {
            "total": 7,
            "by_status": {"PASS": 4, "FAIL": 2, "ERROR": 1},
            "by_type": {"FRESHNESS": 5, "DBT_CORE_SOURCE_VALIDATION": 2},
        }
    }
    out = render_snapshot_section(snapshot)
    assert "Pre-loaded Snapshot" in out
    assert "Monitors configured: 7" in out or "Monitors configured**: 7" in out
    assert "PASS: 4" in out
    assert "FAIL: 2" in out
    assert "FRESHNESS: 5" in out


def test_render_snapshot_section_handles_partial_data():
    """If a future prefetch task adds a key but the current snapshot only has
    monitors, the renderer must not crash on missing keys."""
    snapshot = {"monitors": {"total": 0, "by_status": {}, "by_type": {}}}
    out = render_snapshot_section(snapshot)
    assert "Pre-loaded Snapshot" in out
    assert "Monitors configured" in out
