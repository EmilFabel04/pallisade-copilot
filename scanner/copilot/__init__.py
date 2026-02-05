"""
Pallisade Co-Pilot Module

Stack-agnostic, lineage-aware AI co-pilot for data pipelines.
Dynamically adapts to whatever tools the user has integrated.
"""

from .context_builder import CopilotContextBuilder, CopilotContext
from .tools import ToolRegistry, Tool, ToolResult
from .tool_executor import ToolExecutor
from .llm import CopilotLLM
from .knowledge import KnowledgeBase, get_knowledge_base

__all__ = [
    'CopilotContextBuilder',
    'CopilotContext',
    'ToolRegistry',
    'Tool',
    'ToolResult',
    'ToolExecutor',
    'CopilotLLM',
    'KnowledgeBase',
    'get_knowledge_base',
]
