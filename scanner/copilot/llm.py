"""
Co-Pilot LLM Integration

Integrates with Anthropic Claude and OpenAI GPT for AI-powered assistance.
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

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

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
    
    Uses Anthropic Claude or OpenAI GPT with tool calling to provide
    intelligent assistance for data pipeline questions.
    """
    
    # Available models by provider
    MODELS = {
        # Anthropic
        "claude-sonnet": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
        "claude-opus": {"provider": "anthropic", "model": "claude-opus-4-20250514"},
        # OpenAI
        "gpt-4o": {"provider": "openai", "model": "gpt-4o"},
        "gpt-4o-mini": {"provider": "openai", "model": "gpt-4o-mini"},
        "gpt-4-turbo": {"provider": "openai", "model": "gpt-4-turbo"},
        "o3-mini": {"provider": "openai", "model": "o3-mini"},
    }
    
    DEFAULT_MODEL = "gpt-4o"  # OpenAI as default to avoid rate limits
    
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
    ):
        """
        Initialize the LLM.
        
        Args:
            model: Model to use (claude-sonnet, claude-opus, gpt-4o, gpt-4o-mini, etc.)
            api_key: API key (defaults to ANTHROPIC_API_KEY or OPENAI_API_KEY env var)
        """
        self.model_name = model
        model_config = self.MODELS.get(model, self.MODELS[self.DEFAULT_MODEL])
        self.provider = model_config["provider"]
        self.model = model_config["model"]
        
        self.anthropic_client = None
        self.openai_client = None
        
        if self.provider == "anthropic":
            if ANTHROPIC_AVAILABLE:
                self.anthropic_client = anthropic.Anthropic(
                    api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
                )
            else:
                logger.warning("Anthropic SDK not available")
        elif self.provider == "openai":
            if OPENAI_AVAILABLE:
                self.openai_client = openai.OpenAI(
                    api_key=api_key or os.environ.get("OPENAI_API_KEY")
                )
            else:
                logger.warning("OpenAI SDK not available")
    
    def build_system_prompt(self, context: CopilotContext) -> str:
        """
        Build the system prompt with context about the user's stack.
        
        The prompt only includes information about what the user
        has actually connected.
        """
        prompt = """You are an expert data pipeline assistant for Pallisade, a data reliability platform. You help data engineers understand, debug, and optimize their data pipelines.

## Your Capabilities

You have access to tools that let you:
- **Query the warehouse directly** using `query_warehouse` - execute SELECT queries to get actual data, counts, timestamps, etc.
- **Get table statistics** using `get_table_stats` - row counts, size, last updated time
- Explore data lineage (upstream and downstream dependencies)
- Search for specific tables, models, or assets
- Analyze column-level lineage

## Conversation Context

You have access to the full conversation history. Use this to:
- **Remember what was discussed** - Reference previous queries, tables, or findings without asking the user to repeat themselves
- **Build on previous analysis** - If you already queried a schema or table, use that information in subsequent responses
- **Maintain context** - When the user says "that table" or "those results", they mean data from your previous responses

## Smart Analysis Guidelines

1. **ALWAYS GET SCHEMA FIRST**: Before writing ANY query that references columns:
   - FIRST run: SELECT column_name, data_type FROM `project.dataset.INFORMATION_SCHEMA.COLUMNS` WHERE table_name = 'tablename'
   - THEN use the actual column names from the result
   - NEVER guess column names like "product_id" - always verify first!

2. **BigQuery INFORMATION_SCHEMA syntax** (CRITICAL):
   - Tables in a dataset: SELECT table_name FROM `project.dataset.INFORMATION_SCHEMA.TABLES`
   - Columns in a table: SELECT column_name, data_type FROM `project.dataset.INFORMATION_SCHEMA.COLUMNS` WHERE table_name = 'tablename'
   - List all datasets: SELECT schema_name FROM `project.INFORMATION_SCHEMA.SCHEMATA`
   - NOTE: The backticks are required! The dataset name goes BEFORE INFORMATION_SCHEMA.

3. **USE THE CONNECTED DATASETS**: The user has connected specific datasets (shown below in "User's Data Stack"). When they refer to "raw dataset", "analytics dataset", etc., they mean the datasets listed in their integrations.

4. **ALWAYS use warehouse tools first**: When a user asks about their data, use `query_warehouse` to get ACTUAL data. DO NOT ask the user for information you can query yourself.

5. **Workflow for answering data questions**:
   a. First, discover what tables exist: query INFORMATION_SCHEMA.TABLES
   b. Then, get the schema: query INFORMATION_SCHEMA.COLUMNS for the relevant table
   c. Finally, write your query using the ACTUAL column names from step b

6. **Be specific**: Use fully qualified table names with backticks: `project.dataset.table`

7. **Be concise**: Provide clear, actionable answers.

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
        max_tool_iterations: int = 15,
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
        if self.provider == "anthropic":
            return await self._chat_anthropic(messages, context, max_tool_iterations)
        elif self.provider == "openai":
            return await self._chat_openai(messages, context, max_tool_iterations)
        else:
            return CopilotResponse(
                content=f"Unknown provider: {self.provider}",
                model=self.model,
            )
    
    async def _chat_anthropic(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int,
    ) -> CopilotResponse:
        """Handle chat with Anthropic Claude."""
        if not self.anthropic_client:
            return CopilotResponse(
                content="Anthropic not available. Please configure ANTHROPIC_API_KEY or switch to OpenAI.",
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
                response = self.anthropic_client.messages.create(
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
                logger.exception("Error in Anthropic chat")
                return CopilotResponse(
                    content=f"Error communicating with AI: {str(e)}",
                    model=self.model,
                )
        
        return self._build_max_iterations_response(all_tool_calls, total_input_tokens, total_output_tokens)
    
    async def _chat_openai(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int,
    ) -> CopilotResponse:
        """Handle chat with OpenAI GPT."""
        if not self.openai_client:
            return CopilotResponse(
                content="OpenAI not available. Please configure OPENAI_API_KEY or switch to Anthropic.",
                model=self.model,
            )
        
        # Build system prompt
        system = self.build_system_prompt(context)
        
        # Get available tools in OpenAI format
        registry = get_tool_registry()
        tools = registry.to_openai_tools(context.integration_types)
        
        # Create tool executor
        executor = ToolExecutor(context)
        
        # Convert messages to OpenAI format
        openai_messages = self._convert_messages_openai(messages, system)
        
        # Track total tokens
        total_input_tokens = 0
        total_output_tokens = 0
        all_tool_calls = []
        
        # Check if this is a reasoning model (o1, o3) that uses different params
        is_reasoning_model = self.model.startswith('o1') or self.model.startswith('o3')
        
        # Iterate until we get a final response
        for iteration in range(max_tool_iterations):
            try:
                # Build API call params - reasoning models use max_completion_tokens
                api_params = {
                    "model": self.model,
                    "messages": openai_messages,
                }
                
                if is_reasoning_model:
                    api_params["max_completion_tokens"] = 4096
                    # Reasoning models don't support tools yet
                else:
                    api_params["max_tokens"] = 4096
                    if tools:
                        api_params["tools"] = tools
                
                # Call OpenAI
                response = self.openai_client.chat.completions.create(**api_params)
                
                # Track tokens
                if response.usage:
                    total_input_tokens += response.usage.prompt_tokens
                    total_output_tokens += response.usage.completion_tokens
                
                message = response.choices[0].message
                finish_reason = response.choices[0].finish_reason
                
                # Check if we're done
                if finish_reason == "stop":
                    return CopilotResponse(
                        content=message.content or "",
                        tool_calls=all_tool_calls,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        model=self.model,
                        stop_reason=finish_reason,
                    )
                
                # Handle tool calls
                if finish_reason == "tool_calls" and message.tool_calls:
                    # Add assistant message with tool calls
                    openai_messages.append({
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                }
                            }
                            for tc in message.tool_calls
                        ]
                    })
                    
                    # Execute each tool
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        try:
                            tool_input = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            tool_input = {}
                        
                        logger.info(f"Executing tool: {tool_name}")
                        
                        # Execute the tool
                        result = await executor.execute(tool_name, tool_input)
                        
                        # Track tool call
                        all_tool_calls.append({
                            "tool": tool_name,
                            "input": tool_input,
                            "result": result.to_dict(),
                        })
                        
                        # Add tool result
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result.data if result.success else {"error": result.error}),
                        })
                    
                    # Continue loop
                    continue
                
                # Unexpected finish reason
                logger.warning(f"Unexpected finish reason: {finish_reason}")
                return CopilotResponse(
                    content=message.content or "Unexpected response from AI.",
                    model=self.model,
                    stop_reason=finish_reason or "unknown",
                )
                
            except Exception as e:
                logger.exception("Error in OpenAI chat")
                return CopilotResponse(
                    content=f"Error communicating with AI: {str(e)}",
                    model=self.model,
                )
        
        return self._build_max_iterations_response(all_tool_calls, total_input_tokens, total_output_tokens)
    
    def _build_max_iterations_response(
        self, 
        all_tool_calls: List[Dict], 
        total_input_tokens: int, 
        total_output_tokens: int
    ) -> CopilotResponse:
        """Build response when max iterations reached."""
        logger.warning(f"Max tool iterations reached")
        
        # Try to summarize the results
        summary_parts = ["Here's what I found from the tool calls:\n"]
        for tc in all_tool_calls:
            result = tc.get("result", {})
            if result.get("success") and result.get("data"):
                data = result["data"]
                if tc["tool"] == "query_warehouse" and "rows" in data:
                    row_count = data.get("row_count", len(data.get("rows", [])))
                    if row_count == 1 and data["rows"]:
                        summary_parts.append(f"- Query `{data.get('sql', 'SQL')[:50]}...`: {data['rows'][0]}")
                    else:
                        summary_parts.append(f"- Query returned {row_count} rows")
                elif tc["tool"] == "get_table_stats" and data:
                    summary_parts.append(f"- Table stats: {data}")
        
        summary = "\n".join(summary_parts) if len(summary_parts) > 1 else "I gathered some information but ran out of iterations. Please try asking a more specific question."
        
        return CopilotResponse(
            content=summary,
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
    
    def _convert_messages_openai(self, messages: List[Message], system: str) -> List[Dict[str, Any]]:
        """Convert our Message format to OpenAI format."""
        openai_messages = [{"role": "system", "content": system}]
        
        for msg in messages:
            if msg.role == "system":
                continue
            
            openai_messages.append({
                "role": msg.role,
                "content": msg.content,
            })
        
        return openai_messages
    
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
