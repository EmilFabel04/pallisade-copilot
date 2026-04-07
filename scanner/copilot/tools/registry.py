"""
Co-Pilot Tool Registry

Decorator-based tool registration and ToolRegistry class.
"""

from typing import Dict, List, Optional, Set, Any
from .base import Tool, ToolParameter, ToolResult, ToolCategory

# Global registry populated by @register_tool at import time
_GLOBAL_REGISTRY: Dict[str, Tool] = {}


def register_tool(
    name: str,
    description: str,
    category: ToolCategory,
    parameters: Optional[List[ToolParameter]] = None,
    required_integrations: Optional[Set[str]] = None,
    alternative_integrations: Optional[Set[str]] = None,
    requires_confirmation: bool = False,
):
    """
    Decorator that registers a tool in the global registry.

    The decorated function is a no-op marker — execution is handled
    by ToolExecutor._execute_<name>() methods.
    """
    def decorator(fn):
        if name in _GLOBAL_REGISTRY:
            raise ValueError(f"Tool '{name}' already registered")
        _GLOBAL_REGISTRY[name] = Tool(
            name=name,
            description=description,
            category=category,
            parameters=parameters or [],
            required_integrations=required_integrations or set(),
            alternative_integrations=alternative_integrations or set(),
            requires_confirmation=requires_confirmation,
        )
        return fn
    return decorator


class ToolRegistry:
    """
    Registry of all available tools.

    Tools are organized by category and filtered based on
    what integrations the user has connected.
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._load_from_global_registry()

    def _load_from_global_registry(self):
        """Import category modules to trigger decorators, then copy registry."""
        _modules = (
            "lineage", "warehouse", "dbt", "orchestration", "ingestion",
            "reporting", "storage", "knowledge", "observability", "coverage",
            "actions", "github", "onboarding", "infrastructure",
        )
        # Try relative import first (works when running from scanner/ dir),
        # then absolute scanner.copilot.tools path (works when running from repo root).
        for prefix in ("copilot.tools", "scanner.copilot.tools"):
            try:
                import importlib
                for mod in _modules:
                    importlib.import_module(f"{prefix}.{mod}")
                break
            except ImportError:
                continue
        self._tools = dict(_GLOBAL_REGISTRY)

    def _register(self, tool: Tool) -> None:
        """Register a tool directly (for backward compatibility)."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> List[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_available_tools(self, user_integrations: Set[str]) -> List[Tool]:
        """Get tools available for the user's integrations."""
        return [
            tool for tool in self._tools.values()
            if tool.is_available(user_integrations)
        ]

    def get_tools_by_category(self, category: ToolCategory) -> List[Tool]:
        """Get all tools in a category."""
        return [
            tool for tool in self._tools.values()
            if tool.category == category
        ]

    def to_anthropic_tools(self, user_integrations: Set[str]) -> List[Dict[str, Any]]:
        """Convert available tools to Anthropic format."""
        available = self.get_available_tools(user_integrations)
        return [tool.to_anthropic_tool() for tool in available]

    def to_openai_tools(self, user_integrations: Set[str]) -> List[Dict[str, Any]]:
        """Convert available tools to OpenAI format."""
        available = self.get_available_tools(user_integrations)
        return [tool.to_openai_tool() for tool in available]

    @staticmethod
    def merge_mcp_tools(
        static_tools: List[Dict[str, Any]],
        mcp_tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge MCP-discovered tools with static registry tools."""
        return static_tools + mcp_tools
