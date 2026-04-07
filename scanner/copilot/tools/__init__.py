"""
Co-Pilot Tools Package

Re-exports all public symbols from the legacy tools.py module so that
existing imports (e.g. `from copilot.tools import ToolRegistry`) continue
to work while the package refactor is in progress.
"""

import importlib.util
import os as _os

# Load the legacy tools.py file that lives alongside this package directory.
_legacy_path = _os.path.join(_os.path.dirname(__file__), "..", "tools.py")
_legacy_path = _os.path.normpath(_legacy_path)

_spec = importlib.util.spec_from_file_location("copilot._tools_legacy", _legacy_path)
_legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_legacy)

# Re-export everything the rest of the codebase needs.
ToolCategory = _legacy.ToolCategory
ToolParameter = _legacy.ToolParameter
Tool = _legacy.Tool
ToolResult = _legacy.ToolResult
ToolRegistry = _legacy.ToolRegistry
get_tool_registry = _legacy.get_tool_registry

__all__ = [
    "ToolCategory",
    "ToolParameter",
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "get_tool_registry",
]
