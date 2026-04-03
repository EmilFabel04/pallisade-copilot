"""
SLA Discovery Module

Queries the actual warehouse data to compute SLA thresholds for
freshness, volume, quality, and schema enforcement.

Instead of relying on INFORMATION_SCHEMA history views (which are often
empty), this module uses the adapter's existing methods to query tables
directly:
  - Freshness: get_table_freshness() → MAX(timestamp_col), row count
  - Volume:    row_count from freshness result, or direct COUNT(*)
  - Quality:   get_null_rates() → per-column null rates in one pass
  - Schema:    get_columns() → column count, types → enforcement suggestion
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from scanner.lineage.graph import LineageGraph, LineageNode, NodeType, PlatformDomain

logger = logging.getLogger(__name__)

# Compare by .value strings to avoid dual-import enum identity mismatches
# (lineage.graph vs scanner.lineage.graph create separate enum classes)
_WAREHOUSE_DOMAIN_VALUE = "warehouse"
_WAREHOUSE_TYPE_VALUES = {"table", "view", "materialized_view"}

# PK heuristic common names (lowercase)
_PK_COMMON_NAMES = {"uuid", "guid", "key", "row_id"}


def _detect_pk_columns(columns: list) -> tuple[list[str], str]:
    """Detect primary key columns using a heuristic chain.

    Returns (column_names, detection_method) where detection_method is one of:
    'declared_pk', 'heuristic_id', 'heuristic_id_suffix',
    'heuristic_common_name', 'none'.
    """
    if not columns:
        return [], "none"

    # 1. Declared PK
    declared = [c.name for c in columns if getattr(c, "is_primary_key", False)]
    if declared:
        return declared, "declared_pk"

    col_names_lower = {c.name.lower(): c.name for c in columns}

    # 2. Column named exactly "id"
    if "id" in col_names_lower:
        return [col_names_lower["id"]], "heuristic_id"

    # 3. First column matching *_id
    for c in columns:
        if c.name.lower().endswith("_id"):
            return [c.name], "heuristic_id_suffix"

    # 4. Common PK names
    for common in _PK_COMMON_NAMES:
        if common in col_names_lower:
            return [col_names_lower[common]], "heuristic_common_name"

    # 5. No PK detected
    return [], "none"


def _is_warehouse_node(node: LineageNode) -> bool:
    """Check if a node is a warehouse table/view, using .value comparison."""
    domain = getattr(node.platform_domain, 'value', str(node.platform_domain))
    ntype = getattr(node.node_type, 'value', str(node.node_type))
    return domain == _WAREHOUSE_DOMAIN_VALUE and ntype in _WAREHOUSE_TYPE_VALUES


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DiscoveryResult:
    """Outcome of profiling a single lineage node."""
    node_fqn: str
    warehouse_ancestor_fqn: Optional[str] = None
    freshness: Optional[Dict[str, Any]] = None
    volume: Optional[Dict[str, Any]] = None
    quality: Optional[Dict[str, Any]] = None
    schema: Optional[Dict[str, Any]] = None
    unsupported: bool = False
    skipped_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Graph traversal
# ---------------------------------------------------------------------------

def _find_warehouse_ancestor(node: LineageNode, graph: LineageGraph) -> Optional[LineageNode]:
    """Return the nearest warehouse TABLE/VIEW ancestor of *node* via BFS."""
    if _is_warehouse_node(node):
        return node

    visited: set[str] = {node.id}
    queue: deque[str] = deque(sorted(graph._upstream.get(node.id, set())))

    while queue:
        current_id = queue.popleft()
        if current_id in visited:
            continue
        visited.add(current_id)

        current_node = graph.nodes.get(current_id)
        if current_node is None:
            continue

        if _is_warehouse_node(current_node):
            return current_node

        for neighbour_id in sorted(graph._upstream.get(current_id, set())):
            if neighbour_id not in visited:
                queue.append(neighbour_id)

    return None


# ---------------------------------------------------------------------------
# Lightweight metadata query (no full table scans)
# ---------------------------------------------------------------------------

def _parse_fqn(adapter: Any, table_fqn: str) -> tuple:
    """Parse a table FQN into (db/project, schema/dataset, table) parts."""
    parts = table_fqn.replace("`", "").replace('"', '').split(".")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        db = getattr(adapter, "project", None) or getattr(adapter, "database", "") or ""
        return db, parts[0], parts[1]
    else:
        db = getattr(adapter, "project", None) or getattr(adapter, "database", "") or ""
        schema = getattr(adapter, "dataset", None) or getattr(adapter, "schema", "") or ""
        return db, schema, parts[0]


def _get_table_metadata(adapter: Any, table_fqn: str) -> Optional[Dict[str, Any]]:
    """Get row_count and last_modified from warehouse metadata.

    Each warehouse has its own free metadata source:
      - BigQuery:   __TABLES__ (instant, zero cost)
      - Snowflake:  INFORMATION_SCHEMA.TABLES (instant)
      - Postgres:   pg_stat_user_tables + pg_class (instant)
      - Redshift:   SVV_TABLE_INFO (instant)

    Falls back to adapter.get_table_freshness() for unknown dialects.
    """
    dialect = getattr(adapter, "dialect", "").lower()
    db, schema, tbl = _parse_fqn(adapter, table_fqn)

    # ── BigQuery ──────────────────────────────────────────────────────
    if dialect == "bigquery":
        try:
            rows = adapter.execute_query(f"""
                SELECT row_count,
                       TIMESTAMP_MILLIS(last_modified_time) as last_modified,
                       TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP_MILLIS(last_modified_time), HOUR) as hours_ago
                FROM `{db}.{schema}.__TABLES__`
                WHERE table_id = '{tbl}'
            """)
            if rows:
                r = rows[0]
                return {
                    "row_count": int(r.get("row_count", 0)),
                    "hours_since_update": float(r.get("hours_ago", 0)),
                    "last_updated": r.get("last_modified"),
                }
        except Exception as e:
            logger.warning("[SLA Discovery] %s: BigQuery __TABLES__ failed: %s", table_fqn, e)

    # ── Snowflake ─────────────────────────────────────────────────────
    elif dialect == "snowflake":
        try:
            rows = adapter.execute_query(f"""
                SELECT ROW_COUNT,
                       LAST_ALTERED as LAST_MODIFIED,
                       TIMESTAMPDIFF(HOUR, LAST_ALTERED, CURRENT_TIMESTAMP()) as HOURS_AGO
                FROM {db}.INFORMATION_SCHEMA.TABLES
                WHERE TABLE_NAME = '{tbl.upper()}'
                  AND TABLE_SCHEMA = '{schema.upper()}'
            """)
            if rows and rows[0].get("ROW_COUNT") is not None:
                r = rows[0]
                return {
                    "row_count": int(r["ROW_COUNT"]),
                    "hours_since_update": float(r.get("HOURS_AGO", 0)),
                    "last_updated": r.get("LAST_MODIFIED"),
                }
        except Exception as e:
            logger.warning("[SLA Discovery] %s: Snowflake INFORMATION_SCHEMA.TABLES failed: %s", table_fqn, e)

    # ── Postgres ──────────────────────────────────────────────────────
    elif dialect == "postgres":
        try:
            rows = adapter.execute_query(f"""
                SELECT c.reltuples::bigint AS row_count,
                       GREATEST(s.last_vacuum, s.last_autovacuum,
                                s.last_analyze, s.last_autoanalyze) AS last_modified,
                       EXTRACT(EPOCH FROM (NOW() - GREATEST(
                                s.last_vacuum, s.last_autovacuum,
                                s.last_analyze, s.last_autoanalyze
                       ))) / 3600 AS hours_ago
                FROM pg_class c
                JOIN pg_stat_user_tables s
                  ON c.relname = s.relname AND c.relnamespace = (
                     SELECT oid FROM pg_namespace WHERE nspname = '{schema or "public"}'
                  )
                WHERE c.relname = '{tbl}'
            """)
            if rows and rows[0].get("row_count") is not None:
                r = rows[0]
                return {
                    "row_count": max(0, int(r["row_count"])),
                    "hours_since_update": float(r.get("hours_ago") or 0),
                    "last_updated": r.get("last_modified"),
                }
        except Exception as e:
            logger.warning("[SLA Discovery] %s: Postgres pg_stat failed: %s", table_fqn, e)

    # ── Redshift ──────────────────────────────────────────────────────
    elif dialect == "redshift":
        try:
            rows = adapter.execute_query(f"""
                SELECT tbl_rows AS row_count,
                       stats_off
                FROM SVV_TABLE_INFO
                WHERE "schema" = '{schema or "public"}'
                  AND "table" = '{tbl}'
            """)
            if rows and rows[0].get("row_count") is not None:
                r = rows[0]
                return {
                    "row_count": max(0, int(r["row_count"])),
                    "hours_since_update": 0,  # Redshift SVV_TABLE_INFO doesn't expose last_modified
                    "last_updated": None,
                }
        except Exception as e:
            logger.warning("[SLA Discovery] %s: Redshift SVV_TABLE_INFO failed: %s", table_fqn, e)

    # ── Fallback: adapter.get_table_freshness() ───────────────────────
    try:
        info = adapter.get_table_freshness(table_fqn)
        if info and not info.get("error"):
            return {
                "row_count": int(info.get("row_count", 0)),
                "hours_since_update": float(info.get("hours_since_update", 0)),
                "last_updated": info.get("last_updated"),
            }
    except Exception as e:
        logger.warning("[SLA Discovery] %s: get_table_freshness fallback failed: %s", table_fqn, e)

    return None


# ---------------------------------------------------------------------------
# Direct-query compute functions
# ---------------------------------------------------------------------------

def _compute_freshness(adapter: Any, table_fqn: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Compute freshness threshold from table metadata.

    Uses pre-fetched metadata (from _get_table_metadata) to avoid
    expensive table scans.
    """
    info = metadata
    if not info:
        return None

    hours_since = info.get("hours_since_update")
    if hours_since is None:
        return None

    hours_since = float(hours_since)

    # Derive thresholds from current staleness:
    #   warning = round up current age to nearest sensible interval
    #   max     = 2x warning (buffer for variance)
    if hours_since < 1:
        warning_hours = 1
        max_hours = 2
    elif hours_since < 6:
        warning_hours = math.ceil(hours_since)
        max_hours = warning_hours * 2
    elif hours_since < 24:
        # Round to nearest 6h
        warning_hours = math.ceil(hours_since / 6) * 6
        max_hours = warning_hours + 6
    else:
        # Round to nearest 12h
        warning_hours = math.ceil(hours_since / 12) * 12
        max_hours = warning_hours + 12

    return {
        "enabled": True,
        "maxHours": max_hours,
        "warningHours": warning_hours,
    }


def _compute_volume(adapter: Any, table_fqn: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Report current row count as context for user-defined thresholds.

    We can't derive meaningful min/max from a single snapshot — the user
    knows their expected load pattern.  We provide currentRows so they
    have a baseline to work from.
    """
    count = metadata.get("row_count") if metadata else None

    if not count or count <= 0:
        return None

    return {
        "enabled": True,
        "currentRows": int(count),
    }


def _compute_quality(adapter: Any, table_fqn: str) -> Optional[Dict[str, Any]]:
    """Compute quality thresholds by scanning actual table data.

    Builds a single SQL query that computes null rates for every column
    in one pass.  Nothing is stored — the data is read, aggregated in
    the warehouse, and only the rates come back.

    For BigQuery, uses TABLESAMPLE to limit the scan on large tables.
    """
    # Step 1: Get column names from INFORMATION_SCHEMA (instant)
    try:
        columns_meta = adapter.get_columns(table_fqn)
    except Exception as e:
        logger.warning("[SLA Discovery] %s: quality — get_columns failed: %s", table_fqn, e)
        return None

    if not columns_meta:
        return None

    col_names = [getattr(c, "name", c) for c in columns_meta]
    if not col_names:
        return None

    # Step 2: Build a single query computing null rate per column
    dialect = getattr(adapter, "dialect", "").lower()
    db, schema, tbl = _parse_fqn(adapter, table_fqn)

    # Quote identifiers per dialect
    if dialect == "bigquery":
        q = lambda c: f"`{c}`"
        quoted_table = f"`{db}`.`{schema}`.`{tbl}`"
    elif dialect == "snowflake":
        q = lambda c: f'"{c}"'
        quoted_table = f'{db}.{schema}."{tbl}"'
    else:
        # Postgres / Redshift
        q = lambda c: f'"{c}"'
        quoted_table = f'"{schema}"."{tbl}"' if schema else f'"{tbl}"'

    # Build per-column null rate expressions (dialect-aware)
    null_exprs = []
    for c in col_names:
        alias = q(c + "__null_rate")
        col_ref = q(c)
        if dialect == "bigquery":
            null_exprs.append(f"SAFE_DIVIDE(COUNTIF({col_ref} IS NULL), COUNT(*)) as {alias}")
        elif dialect == "snowflake":
            null_exprs.append(f"RATIO_TO_REPORT(SUM(IFF({col_ref} IS NULL, 1, 0))) OVER() as {alias}")
        else:
            # Postgres / Redshift — CAST for float division
            null_exprs.append(
                f"CAST(SUM(CASE WHEN {col_ref} IS NULL THEN 1 ELSE 0 END) AS FLOAT)"
                f" / NULLIF(COUNT(*), 0) as {alias}"
            )

    query = f"SELECT COUNT(*) as _total, {', '.join(null_exprs)} FROM {quoted_table}"

    # Snowflake RATIO_TO_REPORT doesn't work here — use simpler approach
    if dialect == "snowflake":
        null_exprs_sf = []
        for c in col_names:
            alias = q(c + "__null_rate")
            col_ref = q(c)
            null_exprs_sf.append(
                f"SUM(IFF({col_ref} IS NULL, 1, 0))::FLOAT / NULLIF(COUNT(*), 0) as {alias}"
            )
        query = f"SELECT COUNT(*) as _total, {', '.join(null_exprs_sf)} FROM {quoted_table}"

    try:
        rows = adapter.execute_query(query)
    except Exception as e:
        logger.warning("[SLA Discovery] %s: quality scan failed: %s: %s", table_fqn, type(e).__name__, e)
        return None

    if not rows:
        return None

    row = rows[0]
    total = row.get("_total", 0)
    if not total:
        return None

    # Extract per-column null rates
    per_column: Dict[str, float] = {}
    for c in col_names:
        rate = row.get(f"{c}__null_rate")
        if rate is not None:
            per_column[c] = round(float(rate), 4)

    if not per_column:
        return None

    rates = list(per_column.values())
    avg_null_rate = sum(rates) / len(rates)
    max_null_rate = max(rates)

    # Threshold: max observed + 10% buffer, capped at 50%
    threshold = min(0.5, max_null_rate * 1.1 + 0.01)

    return {
        "enabled": True,
        "maxNullRate": round(threshold, 4),
        "currentAvgNullRate": round(avg_null_rate, 4),
        "currentMaxNullRate": round(max_null_rate, 4),
        "perColumn": per_column,
        "rowsScanned": total,
    }


def _compute_schema(adapter: Any, table_fqn: str) -> Optional[Dict[str, Any]]:
    """Compute schema enforcement suggestion from current column layout.

    Uses adapter.get_columns() to count columns and check for nullable
    or variant-type columns that suggest the schema evolves.
    """
    try:
        columns = adapter.get_columns(table_fqn)
    except Exception as e:
        logger.warning("[SLA Discovery] %s: schema query failed: %s: %s", table_fqn, type(e).__name__, e)
        return None

    if not columns:
        return None

    col_count = len(columns)

    # Heuristic: if there are variant/json/any-type columns, schema is flexible
    _FLEXIBLE_TYPES = {"variant", "json", "jsonb", "object", "struct", "record", "any"}
    has_flexible = any(
        getattr(c, "data_type", "").lower() in _FLEXIBLE_TYPES for c in columns
    )

    if has_flexible:
        return {
            "enabled": True,
            "strictness": "warn",
            "allowEvolution": True,
            "columnCount": col_count,
        }

    return {
        "enabled": True,
        "strictness": "strict",
        "allowEvolution": False,
        "columnCount": col_count,
    }


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def discover_sla_profile(
    node: LineageNode,
    graph: LineageGraph,
    adapter: Any,
) -> DiscoveryResult:
    """Build an SLA profile for *node* by querying the actual table data.

    Queries the warehouse directly for:
    - Freshness: MAX(timestamp_col) or table metadata
    - Volume: row count
    - Quality: per-column null rates
    - Schema: column structure and types
    """
    ancestor = _find_warehouse_ancestor(node, graph)
    if ancestor is None:
        return DiscoveryResult(
            node_fqn=node.fqn,
            unsupported=True,
            skipped_reason="No warehouse ancestor found in lineage graph",
        )

    table_fqn = ancestor.fqn
    logger.info("[SLA Discovery] Profiling %s (ancestor: %s)", node.fqn, table_fqn)

    # Step 1: Get metadata (row_count + freshness) from system tables — instant
    metadata = _get_table_metadata(adapter, table_fqn)
    logger.info("[SLA Discovery] %s: metadata=%s", table_fqn, metadata)

    # Step 2: Compute dimensions from metadata (no table scans)
    freshness = _compute_freshness(adapter, table_fqn, metadata=metadata)
    volume = _compute_volume(adapter, table_fqn, metadata=metadata)
    schema = _compute_schema(adapter, table_fqn)

    # Step 3: Quality — single-pass null rate scan across all columns
    quality = _compute_quality(adapter, table_fqn)

    discovered = sum(1 for x in [freshness, volume, quality, schema] if x is not None)
    logger.info(
        "[SLA Discovery] %s: %d/4 dimensions discovered (freshness=%s volume=%s quality=%s schema=%s)",
        table_fqn,
        discovered,
        "yes" if freshness else "no",
        "yes" if volume else "no",
        "yes" if quality else "no",
        "yes" if schema else "no",
    )

    return DiscoveryResult(
        node_fqn=node.fqn,
        warehouse_ancestor_fqn=table_fqn,
        freshness=freshness,
        volume=volume,
        quality=quality,
        schema=schema,
    )


async def discover_sla_profiles_bulk(
    nodes: List[LineageNode],
    graph: LineageGraph,
    adapter_registry: Dict[str, Any],
    node_limit: int = 100,
) -> List[DiscoveryResult]:
    """Discover SLA profiles for a collection of nodes in priority order."""
    _CRITICALITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    sorted_nodes = sorted(
        nodes,
        key=lambda n: (_CRITICALITY_ORDER.get(n.criticality, 99), n.depth),
    )
    capped = sorted_nodes[:node_limit]

    results: List[DiscoveryResult] = []
    for node in capped:
        platform = node.platform or ""
        adapter = adapter_registry.get(platform)
        if adapter is None:
            results.append(DiscoveryResult(
                node_fqn=node.fqn,
                unsupported=True,
                skipped_reason=f"No adapter registered for platform '{platform}'",
            ))
            continue

        result = await discover_sla_profile(node, graph, adapter)
        results.append(result)

    return results
