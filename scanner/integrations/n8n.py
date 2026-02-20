"""
n8n Workflow Automation Integration

Monitor n8n workflows and executions:
- Workflow status and active/inactive state
- Execution history and failures
- Node-level execution details and errors
- Workflow structure analysis

Supports:
- n8n REST API v1 (self-hosted and cloud)
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """n8n execution statuses."""
    SUCCESS = "success"
    ERROR = "error"
    WAITING = "waiting"
    RUNNING = "running"
    NEW = "new"


@dataclass
class N8nNode:
    """A node in an n8n workflow."""
    name: str
    type: str  # e.g., "n8n-nodes-base.httpRequest"
    position: List[int] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)

    @property
    def short_type(self) -> str:
        """Get short type name, e.g., 'httpRequest' from 'n8n-nodes-base.httpRequest'."""
        return self.type.split(".")[-1] if "." in self.type else self.type


@dataclass
class N8nWorkflow:
    """An n8n workflow."""
    id: str
    name: str
    active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    tags: List[Dict[str, str]] = field(default_factory=list)
    nodes: List[N8nNode] = field(default_factory=list)
    node_count: int = 0


@dataclass
class N8nExecution:
    """An n8n workflow execution."""
    id: str
    workflow_id: str
    workflow_name: str = ""
    status: ExecutionStatus = ExecutionStatus.NEW
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    mode: str = "manual"  # manual, webhook, trigger, etc.
    error_message: Optional[str] = None
    error_node: Optional[str] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class N8nIntegration:
    """
    n8n workflow automation integration for Pallisade.

    Capabilities:
    - List and monitor workflows
    - Track execution status
    - Analyze execution failures with node-level detail
    - Understand workflow structure (nodes and connections)
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.base_url = (
            config.get("base_url") or config.get("host") or ""
        ).rstrip("/")
        self.api_url = f"{self.base_url}/api/v1"

        self._client = httpx.Client(timeout=30)
        self._client.headers["X-N8N-API-KEY"] = config.get("api_key", "")
        self._client.headers["Accept"] = "application/json"

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make an authenticated request to n8n API."""
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        response = self._client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()

    def test_connection(self) -> tuple:
        """Test connection to n8n."""
        try:
            self._request("GET", "/workflows", params={"limit": 1})
            return True, "n8n connected successfully"
        except Exception as e:
            return False, str(e)

    def get_workflows(
        self, active_only: bool = False, limit: int = 100
    ) -> List[N8nWorkflow]:
        """Get list of workflows."""
        params: Dict[str, Any] = {"limit": limit}
        if active_only:
            params["active"] = "true"

        try:
            result = self._request("GET", "/workflows", params=params)
            workflows = []
            for wf in result.get("data", []):
                nodes = self._parse_nodes(wf.get("nodes", []))
                workflows.append(
                    N8nWorkflow(
                        id=str(wf.get("id", "")),
                        name=wf.get("name", ""),
                        active=wf.get("active", False),
                        created_at=self._parse_datetime(wf.get("createdAt")),
                        updated_at=self._parse_datetime(wf.get("updatedAt")),
                        tags=[
                            {"id": t.get("id", ""), "name": t.get("name", "")}
                            for t in wf.get("tags", [])
                        ],
                        nodes=nodes,
                        node_count=len(nodes),
                    )
                )
            return workflows
        except Exception as e:
            logger.error(f"Failed to get n8n workflows: {e}")
            return []

    def get_workflow(self, workflow_id: str) -> Optional[N8nWorkflow]:
        """Get a single workflow with full node details."""
        try:
            wf = self._request("GET", f"/workflows/{workflow_id}")
            nodes = self._parse_nodes(wf.get("nodes", []))
            return N8nWorkflow(
                id=str(wf.get("id", "")),
                name=wf.get("name", ""),
                active=wf.get("active", False),
                created_at=self._parse_datetime(wf.get("createdAt")),
                updated_at=self._parse_datetime(wf.get("updatedAt")),
                tags=[
                    {"id": t.get("id", ""), "name": t.get("name", "")}
                    for t in wf.get("tags", [])
                ],
                nodes=nodes,
                node_count=len(nodes),
            )
        except Exception as e:
            logger.error(f"Failed to get n8n workflow {workflow_id}: {e}")
            return None

    def get_executions(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[N8nExecution]:
        """Get execution history."""
        params: Dict[str, Any] = {"limit": limit}
        if workflow_id:
            params["workflowId"] = workflow_id
        if status:
            params["status"] = status

        try:
            result = self._request("GET", "/executions", params=params)
            executions = []
            for ex in result.get("data", []):
                error_msg = None
                error_node = None

                # Extract error info from execution data
                exec_data = ex.get("data", {})
                if exec_data and isinstance(exec_data, dict):
                    result_data = exec_data.get("resultData", {})
                    error_info = result_data.get("error", {})
                    if error_info:
                        error_msg = error_info.get("message", str(error_info))
                        error_node = error_info.get("node")

                try:
                    exec_status = ExecutionStatus(ex.get("status", "new"))
                except ValueError:
                    exec_status = ExecutionStatus.NEW

                executions.append(
                    N8nExecution(
                        id=str(ex.get("id", "")),
                        workflow_id=str(ex.get("workflowId", "")),
                        workflow_name=ex.get("workflowData", {}).get("name", ""),
                        status=exec_status,
                        started_at=self._parse_datetime(ex.get("startedAt")),
                        finished_at=self._parse_datetime(ex.get("stoppedAt")),
                        mode=ex.get("mode", "manual"),
                        error_message=error_msg,
                        error_node=error_node,
                    )
                )
            return executions
        except Exception as e:
            logger.error(f"Failed to get n8n executions: {e}")
            return []

    def get_execution_details(self, execution_id: str) -> Dict[str, Any]:
        """Get full execution details including per-node execution data."""
        try:
            ex = self._request("GET", f"/executions/{execution_id}")

            node_results = []
            error_info = {}
            exec_data = ex.get("data", {})
            if exec_data and isinstance(exec_data, dict):
                result_data = exec_data.get("resultData", {})
                run_data = result_data.get("runData", {})

                for node_name, node_runs in run_data.items():
                    if isinstance(node_runs, list) and len(node_runs) > 0:
                        last_run = node_runs[-1]
                        items_count = 0
                        if last_run.get("data"):
                            main_data = last_run["data"].get("main", [[]])
                            if main_data and isinstance(main_data, list) and len(main_data) > 0:
                                items_count = len(main_data[0]) if main_data[0] else 0

                        node_results.append(
                            {
                                "node_name": node_name,
                                "status": last_run.get("executionStatus", "unknown"),
                                "start_time": last_run.get("startTime"),
                                "execution_time_ms": last_run.get("executionTime"),
                                "error": last_run.get("error"),
                                "items_count": items_count,
                            }
                        )

                error_info = result_data.get("error", {})

            try:
                exec_status = ExecutionStatus(ex.get("status", "new")).value
            except ValueError:
                exec_status = "unknown"

            return {
                "execution_id": str(ex.get("id", "")),
                "workflow_id": str(ex.get("workflowId", "")),
                "workflow_name": ex.get("workflowData", {}).get("name", ""),
                "status": exec_status,
                "mode": ex.get("mode", "manual"),
                "started_at": ex.get("startedAt"),
                "finished_at": ex.get("stoppedAt"),
                "node_results": node_results,
                "error": {
                    "message": error_info.get("message"),
                    "node": error_info.get("node"),
                }
                if error_info
                else None,
                "total_nodes_executed": len(node_results),
            }
        except Exception as e:
            logger.error(f"Failed to get n8n execution details {execution_id}: {e}")
            return {"execution_id": execution_id, "error": str(e)}

    def get_recent_failures(
        self, workflow_id: Optional[str] = None, limit: int = 10
    ) -> Dict[str, Any]:
        """Get recent failed executions with error details."""
        executions = self.get_executions(
            workflow_id=workflow_id, status="error", limit=limit
        )

        failures = []
        for ex in executions:
            failures.append(
                {
                    "execution_id": ex.id,
                    "workflow_id": ex.workflow_id,
                    "workflow_name": ex.workflow_name,
                    "started_at": ex.started_at.isoformat()
                    if ex.started_at
                    else None,
                    "finished_at": ex.finished_at.isoformat()
                    if ex.finished_at
                    else None,
                    "duration_seconds": ex.duration_seconds,
                    "mode": ex.mode,
                    "error_message": ex.error_message,
                    "error_node": ex.error_node,
                }
            )

        return {
            "total_failures": len(failures),
            "workflow_id": workflow_id,
            "failures": failures,
        }

    def _parse_nodes(self, raw_nodes: List[Dict[str, Any]]) -> List[N8nNode]:
        """Parse node data from workflow response."""
        return [
            N8nNode(
                name=n.get("name", ""),
                type=n.get("type", ""),
                position=n.get("position", []),
                parameters=n.get("parameters", {}),
            )
            for n in raw_nodes
        ]

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        """Parse datetime string from n8n API."""
        if not value:
            return None
        try:
            if "T" in str(value):
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return datetime.fromisoformat(str(value))
        except Exception:
            return None

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
