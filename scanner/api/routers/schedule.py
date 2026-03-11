"""
Schedule API Router.

Provides the task execution endpoint called by Next.js
when a user triggers "Run Now" or the scheduler dispatches a task.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import structlog

logger = structlog.get_logger()

router = APIRouter(prefix="/schedule")


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class ExecuteTaskRequest(BaseModel):
    """Request body for task execution."""

    task_id: str = Field(..., description="Monitor ID")
    name: str = Field(..., description="Task name")
    task_mode: str = Field("structured", description="'prompt' or 'structured'")
    prompt: Optional[str] = Field(None, description="Prompt for prompt-mode tasks")
    monitor_type: Optional[str] = Field(None, description="Monitor kind")
    target_fqn: Optional[str] = Field(None, description="database.schema.table")
    config: Optional[Dict[str, Any]] = Field(None, description="Monitor config")
    integration_id: Optional[str] = Field(None, description="Warehouse integration ID")
    organization_id: Optional[str] = Field(None, description="Organization ID (fallback for integration lookup)")
    integration_config: Optional[Dict[str, Any]] = Field(
        None, description="Pre-fetched integration config (avoids DB lookup)"
    )


class ExecuteTaskResponse(BaseModel):
    """Result of task execution."""

    status: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    message: str = ""
    details: Optional[Dict[str, Any]] = None
    sql_executed: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/execute", response_model=ExecuteTaskResponse)
async def execute_task(request: ExecuteTaskRequest):
    """
    Execute a single scheduled task.

    Called by:
    - Next.js "Run Now" button
    - The background scheduler service

    Returns the execution result (status, value, message).
    """
    from scanner.scheduler.executor import TaskExecutor

    logger.info(
        "schedule_execute",
        task_id=request.task_id,
        task_name=request.name,
        task_mode=request.task_mode,
        monitor_type=request.monitor_type,
        target_fqn=request.target_fqn,
        has_config=bool(request.config),
        has_integration_config=bool(request.integration_config),
        has_integration_id=bool(request.integration_id),
    )

    executor = TaskExecutor()

    task_dict = {
        "id": request.task_id,
        "name": request.name,
        "taskMode": request.task_mode,
        "prompt": request.prompt,
        "monitorType": request.monitor_type,
        "targetFqn": request.target_fqn,
        "config": request.config,
        "integrationId": request.integration_id,
        "organizationId": request.organization_id,
        "integrationConfig": request.integration_config,
    }

    try:
        result = await executor.execute(task_dict)
    except Exception as e:
        logger.error(f"schedule_execute_error: {e}", task_id=request.task_id)
        raise HTTPException(status_code=500, detail=f"Execution failed: {e}")

    logger.info(
        "schedule_execute_result",
        task_id=request.task_id,
        status=result.get("status"),
        message=result.get("message", "")[:200],
    )
    return result
