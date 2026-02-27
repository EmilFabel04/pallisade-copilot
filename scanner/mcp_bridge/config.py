"""
MCP server registry — maps integration types to external MCP server configs.

Each config specifies:
- The subprocess command to start the server
- Which Pallisade integration types it handles
- How to map our credential keys to the server's expected env vars
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server type."""

    name: str
    command: List[str]
    supported_integration_types: Set[str]
    tool_prefix: str
    env_mapping: Dict[str, str] = field(default_factory=dict)
    # Fallback keys: if a primary key isn't found, try these alternatives
    # e.g. pipeline nodes store Airflow URL as "host" but adapters expect "base_url"
    key_aliases: Dict[str, str] = field(default_factory=dict)
    is_custom: bool = False

    def matches_integration(self, integration_type: str) -> bool:
        """Check if this server handles the given integration type."""
        if not self.supported_integration_types:
            return False
        return integration_type.upper() in self.supported_integration_types


# ---------------------------------------------------------------------------
# External MCP servers (open-source, installed as packages)
# ---------------------------------------------------------------------------

MCP_SERVERS: Dict[str, MCPServerConfig] = {
    # --- Warehouse servers ---
    "snowflake": MCPServerConfig(
        name="snowflake",
        command=["python", "-m", "mcp_snowflake"],
        supported_integration_types={"SNOWFLAKE"},
        tool_prefix="mcp_snowflake",
        env_mapping={
            "account": "SNOWFLAKE_ACCOUNT",
            "username": "SNOWFLAKE_USER",
            "password": "SNOWFLAKE_PASSWORD",
            "warehouse": "SNOWFLAKE_WAREHOUSE",
            "database": "SNOWFLAKE_DATABASE",
            "role": "SNOWFLAKE_ROLE",
        },
    ),
    "bigquery": MCPServerConfig(
        name="bigquery",
        command=["mcp-server-bigquery"],
        supported_integration_types={"BIGQUERY"},
        tool_prefix="mcp_bigquery",
        env_mapping={
            "project_id": "BIGQUERY_PROJECT",
            "location": "BIGQUERY_LOCATION",
            "credentials_json": "BIGQUERY_KEY_FILE",
        },
        key_aliases={"credentials_json": "credentials"},
    ),
    "postgres": MCPServerConfig(
        name="postgres",
        command=["postgres-mcp"],
        supported_integration_types={"POSTGRES", "REDSHIFT"},
        tool_prefix="mcp_postgres",
        env_mapping={
            "connection_string": "DATABASE_URI",
        },
    ),
    # --- Transformation servers ---
    "dbt": MCPServerConfig(
        name="dbt",
        command=["dbt-mcp"],
        supported_integration_types={"DBT_CLOUD", "DBT_CORE"},
        tool_prefix="mcp_dbt",
        env_mapping={
            "api_key": "DBT_CLOUD_SERVICE_TOKEN",
            "account_id": "DBT_CLOUD_ACCOUNT_ID",
            "project_dir": "DBT_PROJECT_DIR",
            "github_token": "DBT_GITHUB_TOKEN",
            "github_repo": "DBT_GITHUB_REPO",
            "github_branch": "DBT_GITHUB_BRANCH",
        },
    ),
    # --- Orchestration servers ---
    "airflow": MCPServerConfig(
        name="airflow",
        command=["python", "-m", "mcp_bridge.servers.airflow_server"],
        supported_integration_types={"AIRFLOW"},
        tool_prefix="mcp_airflow",
        env_mapping={
            "base_url": "AIRFLOW_API_URL",
            "username": "AIRFLOW_USERNAME",
            "password": "AIRFLOW_PASSWORD",
            "api_key": "AIRFLOW_AUTH_TOKEN",
        },
        key_aliases={"base_url": "host"},
    ),
    # --- Custom Pallisade servers ---
    "lineage": MCPServerConfig(
        name="lineage",
        command=["python", "-m", "mcp_bridge.servers.lineage_server"],
        supported_integration_types=set(),  # Always available when graph exists
        tool_prefix="mcp_lineage",
        env_mapping={},
        is_custom=True,
    ),
}


def get_servers_for_integration(integration_type: str) -> List[MCPServerConfig]:
    """Return all MCP server configs that support the given integration type."""
    return [
        cfg for cfg in MCP_SERVERS.values()
        if cfg.matches_integration(integration_type)
    ]
