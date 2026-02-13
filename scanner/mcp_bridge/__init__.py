"""
MCP (Model Context Protocol) integration for Pallisade Co-Pilot.

Provides dynamic, on-demand access to data warehouses, dbt, Airflow,
and the lineage engine via MCP servers — both external open-source
servers and our custom Lineage Engine MCP server.
"""

from .client import MCPClientManager
from .config import MCP_SERVERS, MCPServerConfig

__all__ = ["MCPClientManager", "MCP_SERVERS", "MCPServerConfig"]
