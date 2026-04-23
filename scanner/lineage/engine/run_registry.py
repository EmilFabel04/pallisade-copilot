"""
Run Registry — versioned extraction runs with atomic publish.

Each extraction creates a RunRecord identified by a UUID run_id.
The registry tracks run lifecycle (pending → running → completed → failed)
and stores artifacts per run. A single `current_run_id` pointer provides
atomic publish semantics: the frontend always reads from the current run,
which only updates when a new run succeeds.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RunStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RunArtifacts:
    """Artifacts produced during a run, stored under run_id."""

    graph_dict: Optional[Dict[str, Any]] = None
    views: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    diagnostics: Optional[Dict[str, Any]] = None
    reconciliation: Optional[Dict[str, Any]] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    bridge_result: Optional[Dict[str, Any]] = None
    producer_index: Optional[Dict[str, Any]] = None


@dataclass
class RunRecord:
    """A single extraction run."""

    run_id: str
    status: RunStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    tool_configs_summary: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    artifacts: RunArtifacts = field(default_factory=RunArtifacts)
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "tool_configs": self.tool_configs_summary,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "stats": self.artifacts.stats,
            "has_views": bool(self.artifacts.views),
        }


class RunRegistry:
    """In-memory registry of extraction runs with atomic current_run_id."""

    def __init__(self, max_history: int = 10):
        self._runs: Dict[str, RunRecord] = {}
        self._current_run_id: Optional[str] = None
        self._max_history = max_history

    @property
    def current_run_id(self) -> Optional[str]:
        return self._current_run_id

    @property
    def current_run(self) -> Optional[RunRecord]:
        if self._current_run_id:
            return self._runs.get(self._current_run_id)
        return None

    def start_run(self, tool_configs_summary: List[str]) -> str:
        """Create a new run in RUNNING state. Returns run_id."""
        run_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        record = RunRecord(
            run_id=run_id,
            status=RunStatus.RUNNING,
            created_at=now,
            started_at=now,
            tool_configs_summary=tool_configs_summary,
        )
        self._runs[run_id] = record
        self._evict_old_runs()
        logger.info(
            "[RunRegistry] Started run %s with tools: %s",
            run_id, tool_configs_summary,
        )
        return run_id

    def complete_run(self, run_id: str, artifacts: RunArtifacts) -> None:
        """Mark run as completed, store artifacts, atomically publish."""
        record = self._runs.get(run_id)
        if not record:
            logger.warning("[RunRegistry] complete_run: unknown run_id %s", run_id)
            return
        record.status = RunStatus.COMPLETED
        record.completed_at = datetime.now(timezone.utc)
        if record.started_at:
            record.duration_ms = int(
                (record.completed_at - record.started_at).total_seconds() * 1000
            )
        record.artifacts = artifacts
        # Atomic publish
        self._current_run_id = run_id
        logger.info(
            "[RunRegistry] Completed and published run %s (%dms)",
            run_id, record.duration_ms,
        )

    def fail_run(self, run_id: str, errors: List[str]) -> None:
        """Mark run as failed. Does NOT update current_run_id."""
        record = self._runs.get(run_id)
        if not record:
            return
        record.status = RunStatus.FAILED
        record.completed_at = datetime.now(timezone.utc)
        record.errors = errors
        if record.started_at:
            record.duration_ms = int(
                (record.completed_at - record.started_at).total_seconds() * 1000
            )
        logger.warning("[RunRegistry] Failed run %s: %s", run_id, errors)

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        return self._runs.get(run_id)

    def get_run_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Lightweight status dict for polling."""
        record = self._runs.get(run_id)
        if not record:
            return None
        return {
            "run_id": record.run_id,
            "status": record.status.value,
            "duration_ms": record.duration_ms,
            "errors": record.errors,
            "is_current": record.run_id == self._current_run_id,
        }

    def list_runs(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Return recent runs sorted by creation time desc."""
        sorted_runs = sorted(
            self._runs.values(), key=lambda r: r.created_at, reverse=True
        )
        return [r.to_dict() for r in sorted_runs[:limit]]

    def _evict_old_runs(self) -> None:
        """Remove oldest non-current runs to bound memory."""
        if len(self._runs) <= self._max_history:
            return
        sorted_runs = sorted(self._runs.values(), key=lambda r: r.created_at)
        to_remove = len(self._runs) - self._max_history
        removed = 0
        for record in sorted_runs:
            if removed >= to_remove:
                break
            if record.run_id != self._current_run_id:
                del self._runs[record.run_id]
                removed += 1
