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
from .intent import classify_intent, IntentResult, Intent, ScoredIntent
from .root_cause import resolve_fix_owner, OwnerDecision, OwnerSystem
from .response_builder import build_answer_contract

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
    'classify_intent',
    'IntentResult',
    'Intent',
    'ScoredIntent',
    'resolve_fix_owner',
    'OwnerDecision',
    'OwnerSystem',
    'build_answer_contract',
]
