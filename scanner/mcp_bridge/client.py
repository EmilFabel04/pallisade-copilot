"""
MCP Client Manager — manages per-session MCP server lifecycle.

Spawns MCP server subprocesses, discovers their tools, routes tool
calls, and ensures cleanup on session end.
"""

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional, Set

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import MCP_SERVERS, MCPServerConfig

logger = logging.getLogger(__name__)


class MCPClientManager:
    """
    Manages MCP server connections for a single chat session.

    Lifecycle:
      1. __init__() with integrations and optional lineage graph
      2. await start_servers() — spawns subprocesses for matching integrations
      3. await discover_tools() — lists tools from all running servers
      4. await call_tool() — routes prefixed tool calls to correct server
      5. await shutdown() — kills all subprocesses
    """

    def __init__(
        self,
        integrations: Optional[List[Any]] = None,
        engine_store: Optional[Any] = None,
        lineage_graph: Optional[Any] = None,
    ):
        self.integrations = integrations or []
        self.engine_store = engine_store
        self.lineage_graph = lineage_graph

        self._sessions: Dict[str, ClientSession] = {}
        self._exit_stack = AsyncExitStack()
        self._tools_cache: Dict[str, List[Dict]] = {}

    async def start_servers(self) -> None:
        """Start MCP servers based on connected integrations."""
        await self._exit_stack.__aenter__()

        # Collect integration types
        integration_types: Set[str] = set()
        integration_configs: Dict[str, Dict] = {}
        for integration in self.integrations:
            itype = (
                integration.type.upper()
                if hasattr(integration, "type")
                else str(integration.get("type", "")).upper()
            )
            integration_types.add(itype)
            config = (
                integration.config
                if hasattr(integration, "config")
                else integration.get("config", {})
            )
            integration_configs[itype] = config or {}

        # Start external MCP servers
        for server_name, server_cfg in MCP_SERVERS.items():
            if server_cfg.is_custom:
                continue  # Handle custom servers separately

            # Check if any user integration matches
            matching_types = server_cfg.supported_integration_types & integration_types
            if not matching_types:
                continue

            # Use the first matching integration's credentials
            first_type = next(iter(matching_types))
            credentials = integration_configs.get(first_type, {})

            try:
                await self._start_external_server(server_name, server_cfg, credentials)
            except Exception as e:
                logger.warning(f"Failed to start MCP server '{server_name}': {e}")

        # Start custom lineage server if graph data exists
        if self.engine_store or self.lineage_graph:
            try:
                await self._start_lineage_server()
            except Exception as e:
                logger.warning(f"Failed to start lineage MCP server: {e}")

    async def _start_external_server(
        self,
        server_name: str,
        server_cfg: MCPServerConfig,
        credentials: Dict[str, Any],
    ) -> None:
        """Start an external MCP server subprocess."""
        # Build environment variables from credentials
        env = dict(os.environ)
        mapped_vars = []
        for our_key, server_env_var in server_cfg.env_mapping.items():
            value = credentials.get(our_key)
            # Try alias if primary key not found (e.g. "host" for "base_url")
            if value is None and server_cfg.key_aliases.get(our_key):
                alias = server_cfg.key_aliases[our_key]
                value = credentials.get(alias)
                if value is not None:
                    logger.info(
                        f"MCP '{server_name}': using alias '{alias}' for '{our_key}'"
                    )
            if value is not None:
                env[server_env_var] = str(value)
                mapped_vars.append(server_env_var)
            else:
                logger.warning(
                    f"MCP '{server_name}': credential key '{our_key}' not found "
                    f"(needed for env var {server_env_var}). "
                    f"Available keys: {list(credentials.keys())}"
                )
        if mapped_vars:
            logger.info(f"MCP '{server_name}': set env vars {mapped_vars}")
        else:
            logger.warning(f"MCP '{server_name}': no credentials mapped — server will use defaults")

        # Build command (substitute placeholders from credentials)
        command = []
        for part in server_cfg.command:
            if part.startswith("{") and part.endswith("}"):
                key = part[1:-1]
                value = credentials.get(key, "")
                command.append(str(value))
            else:
                command.append(part)

        server_params = StdioServerParameters(
            command=command[0],
            args=command[1:] if len(command) > 1 else [],
            env=env,
        )

        try:
            stdio_transport = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read_stream, write_stream = stdio_transport
            session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            self._sessions[server_name] = session
            logger.info(f"MCP server '{server_name}' started successfully")
        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{server_name}': {e}")
            raise

    async def _start_lineage_server(self) -> None:
        """Start our custom lineage MCP server with graph data."""
        server_cfg = MCP_SERVERS.get("lineage")
        if not server_cfg:
            return

        # Serialize graph data for the lineage server
        graph_json = ""
        if self.engine_store and hasattr(self.engine_store, "graph") and self.engine_store.graph:
            graph_json = self.engine_store.graph.to_json()  # Already a JSON string
        elif self.lineage_graph:
            graph_json = self.lineage_graph.to_json()

        if not graph_json:
            logger.info("No lineage graph data available, skipping lineage MCP server")
            return

        # Pass graph data via environment variable (to_json() already returns a JSON string)
        env = dict(os.environ)
        env["PALLISADE_LINEAGE_GRAPH"] = graph_json

        server_params = StdioServerParameters(
            command=server_cfg.command[0],
            args=server_cfg.command[1:] if len(server_cfg.command) > 1 else [],
            env=env,
        )

        try:
            stdio_transport = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read_stream, write_stream = stdio_transport
            session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            self._sessions["lineage"] = session
            logger.info("Lineage MCP server started successfully")
        except Exception as e:
            logger.error(f"Failed to start lineage MCP server: {e}")
            raise

    async def discover_tools(self, format: str = "anthropic") -> List[Dict[str, Any]]:
        """
        Get all tools from running MCP servers, prefixed with server name.

        Returns tools in either Anthropic or OpenAI format.
        """
        all_tools: List[Dict[str, Any]] = []

        for server_name, session in self._sessions.items():
            try:
                result = await session.list_tools()
                server_cfg = MCP_SERVERS.get(server_name)
                prefix = server_cfg.tool_prefix if server_cfg else f"mcp_{server_name}"

                for tool in result.tools:
                    prefixed_name = f"{prefix}__{tool.name}"

                    if format == "anthropic":
                        all_tools.append({
                            "name": prefixed_name,
                            "description": f"[{server_name.upper()}] {tool.description or ''}",
                            "input_schema": tool.inputSchema or {
                                "type": "object",
                                "properties": {},
                            },
                        })
                    elif format == "openai":
                        all_tools.append({
                            "type": "function",
                            "function": {
                                "name": prefixed_name,
                                "description": f"[{server_name.upper()}] {tool.description or ''}",
                                "parameters": tool.inputSchema or {
                                    "type": "object",
                                    "properties": {},
                                },
                            },
                        })

                self._tools_cache[server_name] = [t.name for t in result.tools]
                logger.info(
                    f"Discovered {len(result.tools)} tools from MCP server '{server_name}'"
                )

            except Exception as e:
                logger.warning(f"Failed to discover tools from '{server_name}': {e}")

        return all_tools

    async def call_tool(
        self, prefixed_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Route a prefixed tool call to the correct MCP server.

        Parses "mcp_snowflake__execute_query" → server="snowflake", tool="execute_query"
        """
        server_name, tool_name = self._parse_prefixed_name(prefixed_name)

        session = self._sessions.get(server_name)
        if not session:
            return {
                "success": False,
                "error": f"MCP server '{server_name}' is not running",
            }

        try:
            result = await session.call_tool(tool_name, arguments)

            # Extract text content from MCP result
            content_parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    content_parts.append(content.text)
                elif hasattr(content, "data"):
                    content_parts.append(str(content.data))

            response_text = "\n".join(content_parts) if content_parts else ""

            # Try to parse as JSON for structured data
            try:
                data = json.loads(response_text)
            except (json.JSONDecodeError, TypeError):
                data = response_text

            return {"success": not result.isError, "data": data}

        except Exception as e:
            logger.error(f"MCP tool call failed ({prefixed_name}): {e}")
            return {"success": False, "error": str(e)}

    def _parse_prefixed_name(self, prefixed_name: str) -> tuple:
        """
        Parse a prefixed tool name into (server_name, tool_name).

        "mcp_snowflake__execute_query" → ("snowflake", "execute_query")
        "mcp_lineage__get_upstream" → ("lineage", "get_upstream")
        """
        # Find the server by matching tool_prefix
        for server_name, server_cfg in MCP_SERVERS.items():
            prefix = server_cfg.tool_prefix + "__"
            if prefixed_name.startswith(prefix):
                tool_name = prefixed_name[len(prefix):]
                return server_name, tool_name

        # Fallback: parse by convention mcp_{server}__{tool}
        if prefixed_name.startswith("mcp_"):
            rest = prefixed_name[4:]
            if "__" in rest:
                server_name, tool_name = rest.split("__", 1)
                return server_name, tool_name

        return "unknown", prefixed_name

    @property
    def active_servers(self) -> List[str]:
        """Return names of currently running MCP servers."""
        return list(self._sessions.keys())

    @property
    def has_servers(self) -> bool:
        """Check if any MCP servers are running."""
        return len(self._sessions) > 0

    async def shutdown(self) -> None:
        """Close all MCP sessions and terminate all subprocesses."""
        try:
            await self._exit_stack.aclose()
        except Exception as e:
            logger.warning(f"Error during MCP shutdown: {e}")
        finally:
            self._sessions.clear()
            self._tools_cache.clear()
            logger.info("All MCP servers shut down")
