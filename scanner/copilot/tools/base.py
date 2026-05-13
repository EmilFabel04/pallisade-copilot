"""
Co-Pilot Tool Base Types

Dataclasses for tool definitions, parameters, results, and categories.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from enum import Enum


class ToolCategory(Enum):
    """Categories of tools."""
    LINEAGE = "lineage"
    WAREHOUSE = "warehouse"
    DBT = "dbt"
    ORCHESTRATION = "orchestration"
    INGESTION = "ingestion"
    REPORTING = "reporting"
    STORAGE = "storage"
    KNOWLEDGE = "knowledge"
    OBSERVABILITY = "observability"
    COVERAGE = "coverage"
    POLICY = "policy"
    CHANGE_PLAN = "change_plan"
    ONBOARDING = "onboarding"
    INFRASTRUCTURE = "infrastructure"


@dataclass
class ToolParameter:
    """A parameter for a tool."""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None
    items: Optional[Dict[str, Any]] = None


@dataclass
class Tool:
    """
    Definition of a tool available to the co-pilot.

    Tools map to specific functionality in the integration adapters.
    """
    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter] = field(default_factory=list)
    required_integrations: Set[str] = field(default_factory=set)
    alternative_integrations: Set[str] = field(default_factory=set)
    requires_confirmation: bool = False
    risk_level: Optional["RiskLevel"] = None
    artifact_spec: Optional["ArtifactSpec"] = None

    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Convert to Anthropic tool format."""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.type == "array" and param.items:
                prop["items"] = param.items
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        }

    def to_openai_tool(self) -> Dict[str, Any]:
        """Convert to OpenAI tool format."""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.type == "array" and param.items:
                prop["items"] = param.items
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        }

    def is_available(self, user_integrations: Set[str]) -> bool:
        """Check if this tool is available for the user's integrations."""
        upper_user = {u.upper() for u in user_integrations}

        if self.required_integrations:
            upper_req = {r.upper() for r in self.required_integrations}
            if not upper_req.issubset(upper_user):
                return False

        if self.alternative_integrations:
            upper_alt = {a.upper() for a in self.alternative_integrations}
            if not upper_alt & upper_user:
                return False

        return True


@dataclass
class ToolResult:
    """Result of executing a tool."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    # Side-channel for SSE events the executor wants the streaming loop in
    # llm.py to forward to the client (e.g. `typed_artefact`). The executor
    # appends here; llm.py drains and clears.
    stream_events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
        }


from enum import Enum as _Enum

# Re-export ArtifactSpec from artefacts.models so tool decorators can attach one
# without taking a direct dependency on the wider artefacts package.
from ..artifacts.models import ArtifactSpec  # noqa: F401


class RiskLevel(_Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
