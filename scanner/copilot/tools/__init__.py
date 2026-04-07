"""
Co-Pilot Tool Registry Package

Re-exports all public names for backward compatibility.
Old import: from copilot.tools import ToolRegistry, Tool, ...
New import: from copilot.tools.registry import ToolRegistry
            from copilot.tools.base import Tool, ToolParameter, ...
"""

from .base import Tool, ToolParameter, ToolResult, ToolCategory
from .registry import ToolRegistry, register_tool, _GLOBAL_REGISTRY

# Global registry instance
_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry."""
    return _registry
