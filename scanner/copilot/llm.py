"""
Co-Pilot LLM Integration

Integrates with Anthropic Claude for AI-powered assistance.
Supports tool calling for executing actions against integrations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
import logging
import json
import os

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from .context_builder import CopilotContext
from .tools import get_tool_registry, ToolResult
from .tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A chat message."""
    role: str  # "user", "assistant", "system"
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None


@dataclass
class CopilotResponse:
    """Response from the co-pilot."""
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    stop_reason: str = ""


class CopilotLLM:
    """
    LLM integration for the co-pilot.
    
    Uses Anthropic Claude with tool calling to provide
    intelligent assistance for data pipeline questions.
    """
    
    # Available models
    MODELS = {
        "claude-sonnet": "claude-sonnet-4-20250514",
        "claude-opus": "claude-opus-4-20250514",
    }
    
    DEFAULT_MODEL = "claude-sonnet"
    
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
    ):
        """
        Initialize the LLM.
        
        Args:
            model: Model to use (claude-sonnet or claude-opus)
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        self.model_name = model
        self.model = self.MODELS.get(model, self.MODELS[self.DEFAULT_MODEL])
        
        if ANTHROPIC_AVAILABLE:
            self.client = anthropic.Anthropic(
                api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
            )
        else:
            self.client = None
            logger.warning("Anthropic SDK not available")
    
    def build_system_prompt(self, context: CopilotContext) -> str:
        """
        Build the system prompt with context about the user's stack.
        
        The prompt only includes information about what the user
        has actually connected.
        """
        prompt = """You are an expert data pipeline assistant for Pallisade, a data reliability platform. You help data engineers understand, debug, and optimize their data pipelines.

## Your Capabilities

You have access to tools that let you:
- Explore data lineage (upstream and downstream dependencies)
- Query warehouse tables and get statistics
- Check pipeline status (dbt, Airflow, Dagster, Prefect, Fivetran, etc.)
- Search for specific tables, models, or assets
- Analyze column-level lineage

## Important Guidelines

1. **Use tools proactively**: When a user asks about their data, use the available tools to get real information rather than guessing.

2. **Be specific**: When discussing tables or models, use their full names (database.schema.table).

3. **Explain your reasoning**: When debugging issues, explain the steps you're taking and why.

4. **Consider the full pipeline**: Issues often cascade from upstream. Always check upstream dependencies when debugging.

5. **Be concise**: Provide clear, actionable answers without unnecessary verbosity.

6. **Acknowledge limitations**: If you don't have access to certain information (e.g., a tool isn't available because the integration isn't connected), say so clearly.

"""
        
        # Add context about user's stack
        prompt += context.to_system_prompt_context()
        
        # Add available tools info
        available_tools = context.available_tools
        if available_tools:
            prompt += "\n## Available Tools\n\n"
            prompt += f"You have access to these tools based on the user's connected integrations: {', '.join(available_tools)}\n"
        else:
            prompt += "\n## Note\n\nNo integrations are currently connected. Guide the user to connect their data tools first.\n"
        
        return prompt
    
    async def chat(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int = 5,
    ) -> CopilotResponse:
        """
        Send a message and get a response.
        
        Handles tool calling automatically, executing tools
        and continuing the conversation until the AI is done.
        
        Args:
            messages: Conversation history
            context: User's co-pilot context
            max_tool_iterations: Maximum tool call iterations to prevent infinite loops
            
        Returns:
            CopilotResponse with the final answer
        """
        if not self.client:
            return CopilotResponse(
                content="LLM not available. Please configure ANTHROPIC_API_KEY.",
                model=self.model,
            )
        
        # Build system prompt
        system = self.build_system_prompt(context)
        
        # Get available tools
        registry = get_tool_registry()
        tools = registry.to_anthropic_tools(context.integration_types)
        
        # Create tool executor
        executor = ToolExecutor(context)
        
        # Convert messages to Anthropic format
        anthropic_messages = self._convert_messages(messages)
        
        # Track total tokens
        total_input_tokens = 0
        total_output_tokens = 0
        all_tool_calls = []
        
        # Iterate until we get a final response
        for iteration in range(max_tool_iterations):
            try:
                # Call Claude
                response = self.client.messages.create(
                    model=self.model,
                    system=system,
                    messages=anthropic_messages,
                    tools=tools if tools else None,
                    max_tokens=4096,
                )
                
                # Track tokens
                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens
                
                # Check if we're done
                if response.stop_reason == "end_turn":
                    # Extract text content
                    text_content = ""
                    for block in response.content:
                        if hasattr(block, "text"):
                            text_content += block.text
                    
                    return CopilotResponse(
                        content=text_content,
                        tool_calls=all_tool_calls,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        model=self.model,
                        stop_reason=response.stop_reason,
                    )
                
                # Handle tool use
                if response.stop_reason == "tool_use":
                    # Process tool calls
                    tool_results = []
                    
                    for block in response.content:
                        if block.type == "tool_use":
                            tool_name = block.name
                            tool_input = block.input
                            tool_use_id = block.id
                            
                            logger.info(f"Executing tool: {tool_name}")
                            
                            # Execute the tool
                            result = await executor.execute(tool_name, tool_input)
                            
                            # Track tool call
                            all_tool_calls.append({
                                "tool": tool_name,
                                "input": tool_input,
                                "result": result.to_dict(),
                            })
                            
                            # Format result for Claude
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": json.dumps(result.data if result.success else {"error": result.error}),
                            })
                    
                    # Add assistant message with tool use
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": response.content,
                    })
                    
                    # Add tool results
                    anthropic_messages.append({
                        "role": "user",
                        "content": tool_results,
                    })
                    
                    # Continue loop
                    continue
                
                # Unexpected stop reason
                logger.warning(f"Unexpected stop reason: {response.stop_reason}")
                return CopilotResponse(
                    content="Unexpected response from AI.",
                    model=self.model,
                    stop_reason=response.stop_reason,
                )
                
            except Exception as e:
                logger.exception("Error in LLM chat")
                return CopilotResponse(
                    content=f"Error communicating with AI: {str(e)}",
                    model=self.model,
                )
        
        # Max iterations reached
        return CopilotResponse(
            content="I've been working on this for a while. Here's what I found so far based on the tool calls I made.",
            tool_calls=all_tool_calls,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            model=self.model,
            stop_reason="max_iterations",
        )
    
    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert our Message format to Anthropic format."""
        anthropic_messages = []
        
        for msg in messages:
            if msg.role == "system":
                # System messages are handled separately
                continue
            
            anthropic_msg = {
                "role": msg.role,
                "content": msg.content,
            }
            
            anthropic_messages.append(anthropic_msg)
        
        return anthropic_messages
    
    async def quick_answer(
        self,
        question: str,
        context: CopilotContext,
    ) -> str:
        """
        Get a quick answer to a simple question.
        
        For questions that don't need tool calling.
        """
        messages = [Message(role="user", content=question)]
        response = await self.chat(messages, context, max_tool_iterations=1)
        return response.content


class MockCopilotLLM(CopilotLLM):
    """
    Mock LLM for testing without API calls.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = None  # Disable real client
    
    async def chat(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int = 5,
    ) -> CopilotResponse:
        """Return a mock response."""
        last_message = messages[-1].content if messages else ""
        
        # Simple mock responses
        if "upstream" in last_message.lower():
            return CopilotResponse(
                content="Based on your lineage graph, I can see the upstream dependencies. Would you like me to trace them?",
                model="mock",
            )
        elif "downstream" in last_message.lower():
            return CopilotResponse(
                content="I can check the downstream impact for you. Which table or model would you like to analyze?",
                model="mock",
            )
        else:
            return CopilotResponse(
                content=f"I understand you're asking about: {last_message[:100]}... I can help you explore your data pipeline. What would you like to know?",
                model="mock",
            )
