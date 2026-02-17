"""
Task Executor.

Handles execution of both prompt-based and structured monitor tasks.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Optional

import structlog

from scanner.monitors.executor import MonitorExecutor, MONITOR_REGISTRY
from scanner.monitors.base import MonitorResult

logger = structlog.get_logger()

# Warehouse pipeline node tool types (lowercase, matching PipelineNode.toolType)
_WAREHOUSE_TOOL_TYPES = ("bigquery", "snowflake", "postgres", "redshift")


def _get_encryption_key() -> bytes:
    """Get the AES-256 encryption key (mirrors lib/crypto.ts getEncryptionKey)."""
    key_hex = os.environ.get("ENCRYPTION_KEY", "")
    if key_hex:
        return bytes.fromhex(key_hex)
    # Development fallback — matches the TypeScript scryptSync('pallisade-dev-key', 'salt', 32)
    return hashlib.scrypt(b"pallisade-dev-key", salt=b"salt", n=16384, r=8, p=1, dklen=32)


def _decrypt(encrypted_hex: str) -> str:
    """Decrypt AES-256-GCM data produced by lib/crypto.ts encrypt().

    Format: iv_hex (32 chars) + auth_tag_hex (32 chars) + ciphertext_hex
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _get_encryption_key()
    iv = bytes.fromhex(encrypted_hex[:32])
    auth_tag = bytes.fromhex(encrypted_hex[32:64])
    ciphertext = bytes.fromhex(encrypted_hex[64:])

    aesgcm = AESGCM(key)
    # GCM tag is appended to ciphertext for the cryptography library
    plaintext = aesgcm.decrypt(iv, ciphertext + auth_tag, None)
    return plaintext.decode("utf-8")


def _get_query_func(integration_config: Dict[str, Any], dialect: str):
    """Build a warehouse query function from integration config.

    Creates the adapter, calls connect(), and returns the bound execute_query method.
    """
    if dialect == "bigquery":
        from scanner.adapters.bigquery import BigQueryAdapter

        adapter = BigQueryAdapter(integration_config)
        adapter.connect()
        return adapter.execute_query, "bigquery"
    elif dialect == "snowflake":
        from scanner.adapters.snowflake import SnowflakeAdapter

        adapter = SnowflakeAdapter(integration_config)
        adapter.connect()
        return adapter.execute_query, "snowflake"
    elif dialect in ("postgres", "postgresql", "redshift"):
        from scanner.adapters.postgres import PostgresAdapter

        adapter = PostgresAdapter(integration_config)
        adapter.connect()
        return adapter.execute_query, "postgres"
    else:
        raise ValueError(f"Unsupported dialect: {dialect}")


def _detect_dialect(integration_type: str) -> str:
    """Map integration type to SQL dialect."""
    mapping = {
        "bigquery": "bigquery",
        "snowflake": "snowflake",
        "postgres": "postgres",
        "postgresql": "postgres",
        "redshift": "redshift",
    }
    return mapping.get(integration_type.lower(), "postgres")


class TaskExecutor:
    """Executes a scheduled task (structured monitor or LLM prompt)."""

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task and return the result dict.

        Returns:
            Dict with keys: status, value, threshold, message, details, sql_executed
        """
        task_mode = task.get("taskMode", "structured")

        if task_mode == "prompt":
            return await self._execute_prompt(task)
        else:
            return await self._execute_structured(task)

    async def _execute_structured(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Run a structured monitor check."""
        monitor_type = task.get("monitorType", "").lower()
        target_fqn = task.get("targetFqn", "")
        config = task.get("config") or {}

        logger.info(
            "[Executor] _execute_structured",
            monitor_type=monitor_type,
            target_fqn=target_fqn,
            config_keys=list(config.keys()) if isinstance(config, dict) else str(config),
            has_integration_config=bool(task.get("integrationConfig")),
            has_integration_id=bool(task.get("integrationId")),
            has_org_id=bool(task.get("organizationId")),
        )

        if not monitor_type or not target_fqn:
            logger.warning("[Executor] Missing monitorType or targetFqn")
            return {
                "status": "ERROR",
                "message": "Missing monitorType or targetFqn for structured task",
            }

        # Parse FQN: database.schema.table
        parts = target_fqn.split(".")
        if len(parts) < 3:
            logger.warning(f"[Executor] Invalid FQN: {target_fqn}")
            return {
                "status": "ERROR",
                "message": f"Invalid target FQN format: {target_fqn} (expected database.schema.table)",
            }

        database, schema, table = parts[0], parts[1], ".".join(parts[2:])

        # Get the monitor class
        monitor_cls = MONITOR_REGISTRY.get(monitor_type)
        if not monitor_cls:
            logger.warning(f"[Executor] Unknown monitor type: {monitor_type}, registry keys: {list(MONITOR_REGISTRY.keys())}")
            return {
                "status": "ERROR",
                "message": f"Unknown monitor type: {monitor_type}",
            }

        # Create monitor instance from config
        # All monitors accept a single `config` dict parameter
        monitor = monitor_cls(config=config) if config else monitor_cls()

        # Get warehouse query function — use pre-fetched config or look up by ID/org
        integration_config = task.get("integrationConfig") or await self._get_integration_config(
            task.get("integrationId"), task.get("organizationId")
        )

        if not integration_config:
            logger.warning("[Executor] No integration config resolved")
            return {
                "status": "ERROR",
                "message": "No warehouse integration configured for this task. Connect a warehouse integration or select one when creating the task.",
            }

        integration_type = integration_config.get("type", "postgres")
        dialect = _detect_dialect(integration_type)
        logger.info(f"[Executor] Using dialect={dialect}, type={integration_type}")

        try:
            query_func, sql_dialect = _get_query_func(integration_config, dialect)

            # Auto-detect timestamp column for freshness monitors
            if hasattr(monitor, "needs_column_discovery") and monitor.needs_column_discovery:
                from scanner.monitors.freshness import discover_timestamp_column

                discovered = discover_timestamp_column(
                    query_func, database, schema, table, sql_dialect
                )
                if discovered:
                    monitor.timestamp_column = discovered
                else:
                    return {
                        "status": "ERROR",
                        "message": f"No timestamp/datetime columns found in {target_fqn}. "
                        f"Specify a timestamp_column in the monitor config.",
                    }

            executor = MonitorExecutor(query_func=query_func, dialect=sql_dialect)
            result: MonitorResult = executor.run_monitor(
                monitor, database, schema, table
            )
            return result.to_dict()
        except Exception as e:
            logger.error(f"[Executor] Structured task failed: {e}")
            return {
                "status": "ERROR",
                "message": f"Execution failed: {str(e)}",
            }

    async def _execute_prompt(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Run an LLM prompt-based check."""
        prompt = task.get("prompt", "")
        if not prompt:
            return {
                "status": "ERROR",
                "message": "No prompt provided for prompt-based task",
            }

        try:
            from scanner.copilot.llm import CopilotLLM

            llm = CopilotLLM()

            # Build a system message that instructs the LLM to act as a monitor
            system_msg = (
                "You are a data quality monitor. Execute the user's check instruction "
                "against the data pipeline. After analysis, respond with a JSON object "
                "containing: {\"status\": \"PASS\"|\"WARN\"|\"FAIL\", \"message\": \"explanation\", "
                "\"details\": {}}. Only respond with valid JSON."
            )

            # Get integration config for warehouse access
            integration_config = task.get("integrationConfig") or await self._get_integration_config(
                task.get("integrationId"), task.get("organizationId")
            )

            # Build context with available tools
            result = await llm.chat(
                message=prompt,
                system_prompt=system_msg,
                integrations=[integration_config] if integration_config else [],
            )

            # Try to parse LLM response as JSON for structured result
            response_text = result.get("message", "")
            try:
                parsed = json.loads(response_text)
                return {
                    "status": parsed.get("status", "PASS").upper(),
                    "message": parsed.get("message", response_text),
                    "details": parsed.get("details", {}),
                }
            except json.JSONDecodeError:
                # LLM didn't return JSON — treat as informational PASS
                return {
                    "status": "PASS",
                    "message": response_text[:500],
                    "details": {"raw_response": response_text},
                }

        except Exception as e:
            logger.error(f"[Executor] Prompt task failed: {e}")
            return {
                "status": "ERROR",
                "message": f"Prompt execution failed: {str(e)}",
            }

    async def _get_integration_config(
        self, integration_id: Optional[str], organization_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Fetch warehouse connection config.

        Uses PipelineNode (where credentials live) rather than Integration.
        If organization_id is provided, auto-discovers the first connected
        warehouse node in the org's pipeline stack.
        """
        if not integration_id and not organization_id:
            return None

        try:
            from scanner.scheduler.service import _get_connection

            conn = _get_connection()
            try:
                with conn.cursor() as cur:
                    if integration_id:
                        # Look up specific pipeline node by integration ID
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType", pn.config
                            FROM "PipelineNode" pn
                            WHERE pn."integrationId" = %s
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            LIMIT 1
                            """,
                            (integration_id,),
                        )
                    else:
                        # Auto-discover: find first connected warehouse node in the org
                        tool_types = list(_WAREHOUSE_TOOL_TYPES)
                        cur.execute(
                            """
                            SELECT pn.id, pn.name, pn."toolType", pn.config
                            FROM "PipelineNode" pn
                            JOIN "PipelineStack" ps ON pn."stackId" = ps.id
                            WHERE ps."organizationId" = %s
                              AND pn."toolType" = ANY(%s)
                              AND pn.status IN ('CONNECTED', 'HEALTHY', 'WARNING')
                            ORDER BY pn."createdAt" ASC
                            LIMIT 1
                            """,
                            (organization_id, tool_types),
                        )

                    row = cur.fetchone()
                    if not row:
                        logger.warning("[Executor] No warehouse pipeline node found")
                        return None

                    node_id, node_name, tool_type, raw_config = row
                    config = raw_config or {}
                    if isinstance(config, str):
                        config = json.loads(config)

                    # Decrypt credentials (same as lib/crypto.ts)
                    credentials: Dict[str, Any] = {}
                    if isinstance(config, dict) and "encrypted" in config:
                        try:
                            decrypted = _decrypt(config["encrypted"])
                            credentials = json.loads(decrypted)
                        except Exception as e:
                            logger.warning(f"[Executor] Failed to decrypt config for {node_name}: {e}")
                            return None
                    elif isinstance(config, dict):
                        credentials = {k: v for k, v in config.items() if k != "_cached"}

                    result = {
                        "id": node_id,
                        "name": node_name,
                        "type": tool_type,
                        **credentials,
                    }

                    # Field mapping: username → user (same as copilot/chat/route.ts)
                    upper_type = tool_type.upper() if tool_type else ""
                    if upper_type in ("SNOWFLAKE", "POSTGRES", "REDSHIFT"):
                        if "username" in result and "user" not in result:
                            result["user"] = result.pop("username")

                    logger.info(
                        "[Executor] Resolved warehouse config",
                        node=node_name,
                        type=tool_type,
                    )
                    return result
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[Executor] Failed to fetch integration config: {e}")
            return None
