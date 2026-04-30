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
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from scanner.lineage.graph import LineageGraph, LineageNode, NodeType, PlatformDomain

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Timestamp-pick result (used by volume + freshness inference and emitted as
# evidence when confidence is below threshold so the clarification engine can
# ask the user which column to use).
# ---------------------------------------------------------------------------

@dataclass
class TimestampPick:
    """Result of choosing a timestamp column for volume/freshness inference.

    Attributes:
        column: The chosen timestamp column name, or None if no candidate exists.
        candidates: ALL columns whose data type is timestamp/date-like.
        confidence:
            0.9 — strong match (loaded_at / ingested_at)
            0.7 — solid match (updated_at / modified_at)
            0.5 — weak match (any other timestamp column)
            0.0 — no candidates at all
    """

    column: Optional[str]
    candidates: List[str]
    confidence: float


# Strong / medium / weak preference patterns used to score the picker.
_PICK_STRONG = ("loaded", "ingested")
_PICK_MEDIUM = ("updated", "modified")

# Compare by .value strings to avoid dual-import enum identity mismatches
# (lineage.graph vs scanner.lineage.graph create separate enum classes)
_WAREHOUSE_DOMAIN_VALUE = "warehouse"
_WAREHOUSE_TYPE_VALUES = {"table", "view", "materialized_view"}

# Platforms that support SQL queries even outside the warehouse domain (e.g. Fivetran source DBs)
_QUERYABLE_PLATFORMS = {"postgres", "mysql", "sqlserver", "redshift", "snowflake", "bigquery"}

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


def _is_queryable_source(node: LineageNode) -> bool:
    """Check if a node is a queryable source DB (e.g. Postgres ingested via Fivetran)."""
    platform = (node.platform or "").lower()
    ntype = getattr(node.node_type, 'value', str(node.node_type))
    return platform in _QUERYABLE_PLATFORMS and ntype in _WAREHOUSE_TYPE_VALUES


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
    uniqueness: Optional[Dict[str, Any]] = None
    unsupported: bool = False
    skipped_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Graph traversal
# ---------------------------------------------------------------------------

def _find_warehouse_ancestor(node: LineageNode, graph: LineageGraph) -> Optional[LineageNode]:
    """Return the nearest warehouse TABLE/VIEW ancestor of *node* via BFS.

    Also matches queryable source DBs (e.g. Postgres tables ingested via Fivetran)
    so SLA discovery works for source databases too.
    """
    if _is_warehouse_node(node) or _is_queryable_source(node):
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

        if _is_warehouse_node(current_node) or _is_queryable_source(current_node):
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
      - SQL Server / Azure SQL: sys.dm_db_partition_stats + sys.tables (instant)

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

    # ── SQL Server / Azure SQL (tsql) ─────────────────────────────────
    elif dialect == "tsql":
        try:
            rows = adapter.execute_query(f"""
                SELECT SUM(p.rows) AS row_count,
                       MAX(o.modify_date) AS last_modified,
                       DATEDIFF(HOUR, MAX(o.modify_date), SYSUTCDATETIME()) AS hours_ago
                FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                JOIN sys.objects o ON t.object_id = o.object_id
                JOIN sys.partitions p ON t.object_id = p.object_id
                WHERE t.name = '{tbl}'
                  AND s.name = '{schema or "dbo"}'
                  AND p.index_id IN (0, 1)
            """)
            if rows and rows[0].get("row_count") is not None:
                r = rows[0]
                hours_ago = r.get("hours_ago")
                return {
                    "row_count": max(0, int(r["row_count"])),
                    "hours_since_update": float(hours_ago) if hours_ago is not None else 0,
                    "last_updated": r.get("last_modified"),
                }
        except Exception as e:
            logger.warning("[SLA Discovery] %s: SQL Server sys.tables failed: %s", table_fqn, e)

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

def _get_update_history(adapter: Any, table_fqn: str, limit: int = 30) -> Optional[List[float]]:
    """Query historical update timestamps and return intervals in hours.

    Uses warehouse-specific system tables to find past mutation events,
    then computes the hour-gaps between consecutive updates.

    Returns a list of interval-in-hours values (most recent first),
    or None if history is unavailable.
    """
    dialect = getattr(adapter, "dialect", "").lower()
    db, schema, tbl = _parse_fqn(adapter, table_fqn)

    timestamps_query: Optional[str] = None

    if dialect == "bigquery":
        # INFORMATION_SCHEMA.JOBS logs every mutation with creation_time.
        # Requires region prefix — try region-us, fall back to regionless.
        for region_prefix in (f"`region-us`.", f"`region-eu`.", ""):
            timestamps_query = f"""
                SELECT creation_time AS ts
                FROM {region_prefix}INFORMATION_SCHEMA.JOBS
                WHERE destination_table.table_id = '{tbl}'
                  AND destination_table.dataset_id = '{schema}'
                  AND statement_type IN ('INSERT', 'MERGE', 'CREATE_TABLE_AS_SELECT', 'COPY')
                  AND state = 'DONE'
                ORDER BY creation_time DESC
                LIMIT {limit}
            """
            try:
                rows = adapter.execute_query(timestamps_query)
                if rows and len(rows) >= 2:
                    return _timestamps_to_intervals(rows, "ts")
            except Exception:
                continue
        return None

    elif dialect == "snowflake":
        timestamps_query = f"""
            SELECT END_TIME AS ts
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE QUERY_TYPE IN ('INSERT', 'MERGE', 'COPY', 'CREATE_TABLE_AS_SELECT')
              AND DATABASE_NAME = '{db.upper()}'
              AND SCHEMA_NAME = '{schema.upper()}'
              AND QUERY_TEXT ILIKE '%{tbl}%'
              AND EXECUTION_STATUS = 'SUCCESS'
            ORDER BY END_TIME DESC
            LIMIT {limit}
        """

    elif dialect == "redshift":
        timestamps_query = f"""
            SELECT DISTINCT i.starttime AS ts
            FROM STL_INSERT i
            JOIN SVV_TABLE_INFO t ON i.tbl = t.table_id
            WHERE t."schema" = '{schema or "public"}'
              AND t."table" = '{tbl}'
            ORDER BY i.starttime DESC
            LIMIT {limit}
        """

    elif dialect == "postgres":
        # Postgres has no mutation history. Try to find a timestamp column
        # in the actual table and bucket by it to infer update cadence.
        return _infer_intervals_from_timestamp_column(adapter, table_fqn, limit)

    if not timestamps_query:
        return None

    try:
        rows = adapter.execute_query(timestamps_query)
        if rows and len(rows) >= 2:
            return _timestamps_to_intervals(rows, "ts")
    except Exception as e:
        logger.debug("[SLA Discovery] %s: update history query failed: %s", table_fqn, e)

    # Fallback for all dialects: try timestamp column scan
    return _infer_intervals_from_timestamp_column(adapter, table_fqn, limit)


def _timestamps_to_intervals(rows: List[Dict], key: str) -> Optional[List[float]]:
    """Convert a list of timestamp rows into intervals in hours."""
    from datetime import datetime, timezone

    timestamps = []
    for r in rows:
        ts = r.get(key) or r.get(key.upper())
        if ts is None:
            continue
        if isinstance(ts, str):
            # Parse ISO format
            for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z",
                        "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    ts = datetime.strptime(ts, fmt)
                    break
                except ValueError:
                    continue
            else:
                continue
        if hasattr(ts, 'timestamp'):
            timestamps.append(ts)

    if len(timestamps) < 2:
        return None

    # Sort descending (most recent first)
    timestamps.sort(reverse=True)

    intervals = []
    for i in range(len(timestamps) - 1):
        diff_hours = abs((timestamps[i] - timestamps[i + 1]).total_seconds()) / 3600
        if diff_hours > 0:
            intervals.append(round(diff_hours, 2))

    return intervals if intervals else None


def _pick_volume_timestamp_column(adapter: Any, table_fqn: str) -> TimestampPick:
    """Choose the best timestamp column for volume / freshness inference.

    Returns a :class:`TimestampPick` carrying the chosen column, the full list
    of timestamp/date-like candidates discovered on the table, and a confidence
    score the clarification engine consults before deciding whether to ask the
    user which column to use.

    Confidence model:
        0.9 — strong match (`loaded_at` / `ingested_at`)
        0.7 — solid match (`updated_at` / `modified_at`)
        0.5 — weak match (any other timestamp column)
        0.0 — no timestamp columns on the table at all
    """
    try:
        columns = adapter.get_columns(table_fqn)
    except Exception:
        return TimestampPick(column=None, candidates=[], confidence=0.0)

    if not columns:
        return TimestampPick(column=None, candidates=[], confidence=0.0)

    candidates: List[str] = []
    for c in columns:
        dtype = (getattr(c, "data_type", "") or "").lower()
        name = getattr(c, "name", None)
        if not name:
            continue
        if any(t in dtype for t in ("timestamp", "datetime", "date")):
            candidates.append(name)

    if not candidates:
        return TimestampPick(column=None, candidates=[], confidence=0.0)

    def _matches(col: str, patterns: tuple) -> bool:
        cl = col.lower()
        return any(p in cl for p in patterns)

    # Walk the preference order — strong first, then medium, then any timestamp.
    for col in candidates:
        if _matches(col, _PICK_STRONG):
            return TimestampPick(column=col, candidates=candidates, confidence=0.9)

    for col in candidates:
        if _matches(col, _PICK_MEDIUM):
            return TimestampPick(column=col, candidates=candidates, confidence=0.7)

    # No preferred match — pick the first timestamp column with low confidence.
    return TimestampPick(column=candidates[0], candidates=candidates, confidence=0.5)


def _infer_intervals_from_timestamp_column(adapter: Any, table_fqn: str, limit: int = 30) -> Optional[List[float]]:
    """Fallback: find a timestamp column in the table and bucket updates by it."""
    pick = _pick_volume_timestamp_column(adapter, table_fqn)
    if pick.column is None:
        return None

    ts_col = pick.column

    dialect = getattr(adapter, "dialect", "").lower()
    db, schema, tbl = _parse_fqn(adapter, table_fqn)

    if dialect == "bigquery":
        q = lambda c: f"`{c}`"
        quoted_table = f"`{db}`.`{schema}`.`{tbl}`"
        trunc_expr = f"TIMESTAMP_TRUNC(MAX({q(ts_col)}), HOUR)"
    elif dialect == "snowflake":
        q = lambda c: f'"{c}"'
        quoted_table = f'{db}.{schema}."{tbl}"'
        trunc_expr = f"DATE_TRUNC('HOUR', MAX({q(ts_col)}))"
    else:
        q = lambda c: f'"{c}"'
        quoted_table = f'"{schema}"."{tbl}"' if schema else f'"{tbl}"'
        trunc_expr = f"DATE_TRUNC('hour', MAX({q(ts_col)}))"

    # Group by date to get one data-point per day — avoids scanning every row
    if dialect == "bigquery":
        date_expr = f"DATE({q(ts_col)})"
    else:
        date_expr = f"CAST({q(ts_col)} AS DATE)"

    query = f"""
        SELECT {trunc_expr} AS ts
        FROM {quoted_table}
        GROUP BY {date_expr}
        ORDER BY ts DESC
        LIMIT {limit}
    """

    try:
        rows = adapter.execute_query(query)
        if rows and len(rows) >= 2:
            return _timestamps_to_intervals(rows, "ts")
    except Exception as e:
        logger.debug("[SLA Discovery] %s: timestamp column scan failed: %s", table_fqn, e)

    return None


def _compute_freshness(adapter: Any, table_fqn: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Compute freshness threshold purely from the data.

    Queries historical update timestamps from warehouse system tables
    (or timestamp columns in the data itself) to compute the real
    average update interval.  Thresholds are derived from that interval:
      warning = avg interval + 1 stddev (or 1.5x if < 3 data points)
      max     = avg interval + 2 stddev (or 2x if < 3 data points)
    """
    info = metadata
    if not info:
        return None

    hours_since = info.get("hours_since_update")
    last_updated = info.get("last_updated")

    # Try to get real update history from the warehouse
    intervals = _get_update_history(adapter, table_fqn)

    if intervals and len(intervals) >= 2:
        avg_interval = sum(intervals) / len(intervals)
        n = len(intervals)

        if n >= 3:
            variance = sum((x - avg_interval) ** 2 for x in intervals) / (n - 1)
            stddev = math.sqrt(variance)
        else:
            # Not enough data for stddev — use 50% of avg as proxy
            stddev = avg_interval * 0.5

        warning_hours = avg_interval + stddev
        max_hours = avg_interval + 2 * stddev

        # Round to nearest sensible interval
        if avg_interval < 2:
            warning_hours = round(warning_hours, 1)
            max_hours = round(max_hours, 1)
        elif avg_interval < 12:
            warning_hours = math.ceil(warning_hours)
            max_hours = math.ceil(max_hours)
        elif avg_interval < 48:
            warning_hours = math.ceil(warning_hours / 6) * 6
            max_hours = math.ceil(max_hours / 6) * 6
        else:
            warning_hours = math.ceil(warning_hours / 12) * 12
            max_hours = math.ceil(max_hours / 12) * 12

        if max_hours <= warning_hours:
            max_hours = warning_hours + max(1, round(avg_interval * 0.25))

        return {
            "enabled": True,
            "maxHours": max_hours,
            "warningHours": warning_hours,
            "lastModified": last_updated,
            "observedAgeHours": round(float(hours_since), 1) if hours_since is not None else None,
            "avgIntervalHours": round(avg_interval, 1),
            "dataPoints": n,
        }

    # Fallback: only a single snapshot available — use hours_since as
    # the best available estimate of the interval
    if hours_since is None:
        return None

    hours_since = float(hours_since)

    # With only one data point, warning=1.5x and max=2x is the best we can do
    warning_hours = round(hours_since * 1.5, 1)
    max_hours = round(hours_since * 2, 1)

    if max_hours <= warning_hours:
        max_hours = warning_hours + max(1, round(hours_since * 0.25, 1))

    return {
        "enabled": True,
        "maxHours": max_hours,
        "warningHours": warning_hours,
        "lastModified": last_updated,
        "observedAgeHours": round(hours_since, 1),
        "avgIntervalHours": round(hours_since, 1),
        "dataPoints": 1,
    }


def _get_daily_row_counts(adapter: Any, table_fqn: str, days: int = 30) -> Optional[List[int]]:
    """Return row counts per day for the most recent `days` days.

    Picks a timestamp column (preferring ingest/update patterns over created),
    then asks the warehouse to bucket rows by day. Skips the current day to
    avoid biasing min/max with a partial day.
    """
    pick = _pick_volume_timestamp_column(adapter, table_fqn)
    if pick.column is None:
        return None
    ts_col = pick.column

    dialect = getattr(adapter, "dialect", "").lower()
    db, schema, tbl = _parse_fqn(adapter, table_fqn)

    if dialect == "bigquery":
        q = lambda c: f"`{c}`"
        quoted_table = f"`{db}`.`{schema}`.`{tbl}`"
        date_expr = f"DATE({q(ts_col)})"
        lookback = f"{q(ts_col)} >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days + 1} DAY)"
        today_excl = f"{date_expr} < CURRENT_DATE()"
    elif dialect == "snowflake":
        q = lambda c: f'"{c}"'
        quoted_table = f'{db}.{schema}."{tbl}"'
        date_expr = f"CAST({q(ts_col)} AS DATE)"
        lookback = f"{q(ts_col)} >= DATEADD(day, -{days + 1}, CURRENT_TIMESTAMP())"
        today_excl = f"{date_expr} < CURRENT_DATE()"
    else:
        q = lambda c: f'"{c}"'
        quoted_table = f'"{schema}"."{tbl}"' if schema else f'"{tbl}"'
        date_expr = f"CAST({q(ts_col)} AS DATE)"
        lookback = f"{q(ts_col)} >= CURRENT_TIMESTAMP - INTERVAL '{days + 1} days'"
        today_excl = f"{date_expr} < CURRENT_DATE"

    query = f"""
        SELECT {date_expr} AS day, COUNT(*) AS row_count
        FROM {quoted_table}
        WHERE {lookback} AND {today_excl}
        GROUP BY day
        ORDER BY day DESC
        LIMIT {days}
    """

    try:
        rows = adapter.execute_query(query)
    except Exception as e:
        logger.debug("[SLA Discovery] %s: daily-volume scan failed: %s", table_fqn, e)
        return None

    counts: List[int] = []
    for r in rows or []:
        val = r.get("row_count") if isinstance(r, dict) else None
        if val is None:
            continue
        try:
            counts.append(int(val))
        except (TypeError, ValueError):
            continue
    return counts or None


def _round_volume(n: float, *, down: bool) -> int:
    """Round a row count to a human-friendly number of significant figures."""
    if n <= 0:
        return 0
    magnitude = 10 ** max(0, int(math.log10(n)) - 1)
    if down:
        return max(0, int(math.floor(n / magnitude) * magnitude))
    return int(math.ceil(n / magnitude) * magnitude)


def _compute_volume(
    adapter: Any,
    table_fqn: str,
    metadata: Optional[Dict[str, Any]] = None,
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Derive expected daily volume thresholds from historical row counts.

    Queries row counts per day for the last ~30 days via a timestamp column,
    then emits minRows/maxRows as `avg ± 2·stddev` (clamped and rounded) so
    the user sees expected daily ingest, not a static snapshot of total rows.
    Falls back to just currentRows when no timestamp column is usable.

    When ``pipeline_stack_id`` is supplied and the timestamp picker's
    confidence falls below ``CONFIG.confidence_threshold``, this function
    asks Next.js to create a ``timestamp_choice`` ContextRequest so the
    user can disambiguate. The discovery result is then marked
    ``tentative=True`` and carries a ``context_request_id`` the UI can
    surface.
    """
    count = metadata.get("row_count") if metadata else None
    if not count or count <= 0:
        return None

    result: Dict[str, Any] = {
        "enabled": True,
        "currentRows": int(count),
    }

    # Pick timestamp column up-front so we can both reuse it for daily counts
    # and inspect confidence to decide whether to emit a clarification.
    pick = _pick_volume_timestamp_column(adapter, table_fqn)

    # Best-effort: ask Next.js to create a ContextRequest if confidence is low
    # AND we know which pipeline stack to attach it to. Failures are silent —
    # discovery must keep working even if the clarification engine is down.
    clarification = _try_emit_timestamp_clarification(
        table_fqn=table_fqn,
        pick=pick,
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )
    if clarification and clarification.get("context_request_id") and not clarification.get("suppressed"):
        result["tentative"] = True
        result["context_request_id"] = clarification["context_request_id"]

    daily = _get_daily_row_counts(adapter, table_fqn)
    if not daily or len(daily) < 3:
        return result

    n = len(daily)
    avg = sum(daily) / n
    variance = sum((x - avg) ** 2 for x in daily) / (n - 1)
    stddev = math.sqrt(variance)

    # ±2σ window, clamped and rounded to human-friendly numbers.
    min_rows = _round_volume(max(0.0, avg - 2 * stddev), down=True)
    max_rows = _round_volume(avg + 2 * stddev, down=False)

    # Guarantee a non-degenerate window even on very stable tables.
    if max_rows <= min_rows:
        max_rows = _round_volume(avg * 1.5 + 1, down=False)
        min_rows = _round_volume(avg * 0.5, down=True)

    result.update({
        "expectedDailyRows": int(round(avg)),
        "minRows": int(min_rows),
        "maxRows": int(max_rows),
        "dataPoints": n,
    })
    return result


# ---------------------------------------------------------------------------
# Clarification emission helpers (Next.js round-trip)
# ---------------------------------------------------------------------------

def _try_emit_timestamp_clarification(
    *,
    table_fqn: str,
    pick: TimestampPick,
    pipeline_stack_id: Optional[str],
    organization_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Ask Next.js to create a ``timestamp_choice`` ContextRequest if confidence is low.

    Returns ``{'context_request_id': str, 'suppressed': bool}`` when an
    HTTP round-trip happened, or ``None`` when no emission was attempted
    (no pipeline scope, sufficient confidence, or the picker found no
    candidates at all — there is nothing to ask the user about in that
    last case).
    """
    # Lazy import — avoid import-time cycles between sla_discovery and the
    # clarifications package.
    try:
        from copilot.clarifications.config import CONFIG
    except ImportError:
        from scanner.copilot.clarifications.config import CONFIG

    if not pipeline_stack_id:
        return None
    if pick.confidence >= CONFIG.confidence_threshold:
        return None
    if not pick.candidates:
        # Nothing to disambiguate between — the user can't pick a column
        # that doesn't exist. Fall back silently.
        return None

    return _call_nextjs_create_context_request(
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
        kind="timestamp_choice",
        scope_type="node",
        scope_ref=table_fqn,
        payload={
            "table_fqn": table_fqn,
            "candidates": list(pick.candidates),
            "confidence": pick.confidence,
            "evidence": {
                "picked_column": pick.column,
                "picker": "sla_discovery._pick_volume_timestamp_column",
            },
        },
        priority="normal",
    )


def _call_nextjs_create_context_request(
    *,
    pipeline_stack_id: str,
    organization_id: Optional[str],
    kind: str,
    scope_type: str,
    scope_ref: str,
    payload: Dict[str, Any],
    priority: str = "normal",
) -> Optional[Dict[str, Any]]:
    """POST to Next.js /api/context-requests/create using internal-secret auth.

    Synchronous httpx — discovery itself is sync inside an async wrapper.
    Failures are swallowed: clarification emission is best-effort and
    must never break SLA discovery.
    """
    try:
        import httpx
    except ImportError:
        logger.debug("[Clarifications] httpx unavailable; skipping emit")
        return None

    base = (
        os.environ.get("NEXTJS_BASE_URL")
        or os.environ.get("INTERNAL_NEXTJS_URL")
        or "http://localhost:3000"
    )
    secret = os.environ.get("INTERNAL_API_SECRET", "pallisade-internal")
    if not organization_id:
        logger.debug(
            "[Clarifications] no organization_id available for table_fqn=%s; skipping emit",
            scope_ref,
        )
        return None

    body = {
        "pipelineStackId": pipeline_stack_id,
        "kind": kind,
        "scopeType": scope_type,
        "scopeRef": scope_ref,
        "payload": payload,
        "priority": priority,
    }

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                f"{base}/api/context-requests/create",
                headers={
                    "Content-Type": "application/json",
                    "X-Internal-Secret": secret,
                    "X-Organization-Id": organization_id,
                },
                json=body,
            )
        if resp.status_code >= 400:
            logger.warning(
                "[Clarifications] create failed (%s): %s",
                resp.status_code,
                resp.text[:200],
            )
            return None
        data = resp.json()
        return {
            "context_request_id": data.get("id"),
            "suppressed": bool(data.get("suppressed")),
        }
    except Exception as exc:
        logger.debug("[Clarifications] create POST raised: %s", exc)
        return None


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


def _compute_uniqueness(adapter: Any, table_fqn: str) -> Optional[Dict[str, Any]]:
    """Compute duplicate rate on detected PK columns.

    Uses APPROX_COUNT_DISTINCT where available (BigQuery, Snowflake)
    for performance on large tables. Falls back to exact COUNT(DISTINCT)
    for Postgres/Redshift.
    """
    # Step 1: Get columns and detect PK
    try:
        columns = adapter.get_columns(table_fqn)
    except Exception as e:
        logger.warning("[SLA Discovery] %s: uniqueness — get_columns failed: %s", table_fqn, e)
        return None

    if not columns:
        return None

    pk_cols, detection_method = _detect_pk_columns(columns)

    if not pk_cols:
        return {
            "enabled": False,
            "skipped": True,
            "reason": "no PK detected",
            "detectionMethod": "none",
        }

    # Step 2: Build dialect-aware query
    dialect = getattr(adapter, "dialect", "").lower()
    db, schema, tbl = _parse_fqn(adapter, table_fqn)

    # Quote identifiers
    if dialect == "bigquery":
        q = lambda c: f"`{c}`"
        quoted_table = f"`{db}`.`{schema}`.`{tbl}`"
    elif dialect == "snowflake":
        q = lambda c: f'"{c}"'
        quoted_table = f'{db}.{schema}."{tbl}"'
    else:
        q = lambda c: f'"{c}"'
        quoted_table = f'"{schema}"."{tbl}"' if schema else f'"{tbl}"'

    # Build the distinct expression — single column or composite
    if len(pk_cols) == 1:
        col_expr = q(pk_cols[0])
    else:
        # Composite PK: concat columns for distinct counting
        if dialect == "bigquery":
            col_expr = "CONCAT(" + ", '|', ".join(f"CAST({q(c)} AS STRING)" for c in pk_cols) + ")"
        elif dialect == "snowflake":
            col_expr = "CONCAT(" + ", '|', ".join(f"TO_VARCHAR({q(c)})" for c in pk_cols) + ")"
        else:
            col_expr = "CONCAT(" + " || '|' || ".join(f"CAST({q(c)} AS TEXT)" for c in pk_cols) + ")"

    # Approximate vs exact distinct
    approximate = True
    if dialect in ("bigquery", "snowflake"):
        distinct_expr = f"APPROX_COUNT_DISTINCT({col_expr})"
    elif dialect == "redshift":
        distinct_expr = f"APPROXIMATE COUNT(DISTINCT {col_expr})"
    else:
        # Postgres — no approximate built-in
        distinct_expr = f"COUNT(DISTINCT {col_expr})"
        approximate = False

    query = f"SELECT COUNT(*) as _total, {distinct_expr} as _distinct FROM {quoted_table}"

    try:
        rows = adapter.execute_query(query)
    except Exception as e:
        logger.warning("[SLA Discovery] %s: uniqueness query failed: %s: %s", table_fqn, type(e).__name__, e)
        return None

    if not rows:
        return None

    row = rows[0]
    total = int(row.get("_total", 0))
    distinct = int(row.get("_distinct", 0))

    if total == 0:
        return None

    duplicate_rate = round(1.0 - (distinct / total), 4)
    # Threshold: 1.5x current rate, floor at 1%
    suggested_threshold = round(max(duplicate_rate * 1.5, 0.01), 4)

    return {
        "enabled": True,
        "duplicateRate": duplicate_rate,
        "primaryKeyColumns": pk_cols,
        "detectionMethod": detection_method,
        "totalRows": total,
        "distinctRows": distinct,
        "approximate": approximate,
        "suggestedThreshold": suggested_threshold,
    }


def _compute_schema(adapter: Any, table_fqn: str) -> Optional[Dict[str, Any]]:
    """Compute schema enforcement suggestion and full column snapshot.

    Uses adapter.get_columns() to build a baseline snapshot of the
    table's column layout: name, type, nullable, ordinal position.
    Also checks for variant/json columns to suggest strictness level.
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

    # Build column snapshot sorted by ordinal position
    def _safe_ordinal(c: Any) -> int:
        val = getattr(c, "ordinal_position", None)
        try:
            return int(val) if val is not None else 0
        except (TypeError, ValueError):
            return 0

    col_snapshot = sorted(
        [
            {
                "name": c.name,
                "type": getattr(c, "data_type", "UNKNOWN"),
                "nullable": bool(getattr(c, "is_nullable", True)),
                "ordinal": _safe_ordinal(c),
            }
            for c in columns
        ],
        key=lambda x: x["ordinal"],
    )

    if has_flexible:
        return {
            "enabled": True,
            "strictness": "warn",
            "allowEvolution": True,
            "columnCount": col_count,
            "columns": col_snapshot,
        }

    return {
        "enabled": True,
        "strictness": "strict",
        "allowEvolution": False,
        "columnCount": col_count,
        "columns": col_snapshot,
    }


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def discover_sla_profile(
    node: LineageNode,
    graph: LineageGraph,
    adapter: Any,
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> DiscoveryResult:
    """Build an SLA profile for *node* by querying the actual table data.

    Queries the warehouse directly for:
    - Freshness: MAX(timestamp_col) or table metadata
    - Volume: row count
    - Quality: per-column null rates
    - Schema: column structure and types

    When ``pipeline_stack_id`` and ``organization_id`` are provided, low-
    confidence picks (currently the volume timestamp column) trigger a
    ``timestamp_choice`` ContextRequest creation in Next.js so the user can
    disambiguate. Without them, the clarification path is a no-op.
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
    volume = _compute_volume(
        adapter,
        table_fqn,
        metadata=metadata,
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )
    schema = _compute_schema(adapter, table_fqn)

    # Step 3: Quality — single-pass null rate scan across all columns
    quality = _compute_quality(adapter, table_fqn)

    # Step 4: Uniqueness — approximate distinct count on PK columns
    uniqueness = _compute_uniqueness(adapter, table_fqn)

    dimensions = [freshness, volume, quality, schema, uniqueness]
    discovered = sum(1 for x in dimensions if x is not None and x.get("enabled", True))
    logger.info(
        "[SLA Discovery] %s: %d/5 dimensions discovered (freshness=%s volume=%s quality=%s schema=%s uniqueness=%s)",
        table_fqn,
        discovered,
        "yes" if freshness else "no",
        "yes" if volume else "no",
        "yes" if quality else "no",
        "yes" if schema else "no",
        "yes" if uniqueness and uniqueness.get("enabled") else "no",
    )

    return DiscoveryResult(
        node_fqn=node.fqn,
        warehouse_ancestor_fqn=table_fqn,
        freshness=freshness,
        volume=volume,
        quality=quality,
        schema=schema,
        uniqueness=uniqueness,
    )


async def discover_sla_direct(
    table_fqn: str,
    adapter: Any,
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> DiscoveryResult:
    """Discover SLA profile directly from a table FQN — no lineage graph needed.

    Use this when the caller already knows the warehouse table FQN and has
    a connected adapter.  Skips the graph ancestor walk entirely.
    """
    logger.info("[SLA Discovery] Direct profiling %s", table_fqn)

    metadata = _get_table_metadata(adapter, table_fqn)
    logger.info("[SLA Discovery] %s: metadata=%s", table_fqn, metadata)

    freshness = _compute_freshness(adapter, table_fqn, metadata=metadata)
    volume = _compute_volume(
        adapter,
        table_fqn,
        metadata=metadata,
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )
    schema = _compute_schema(adapter, table_fqn)
    quality = _compute_quality(adapter, table_fqn)
    uniqueness = _compute_uniqueness(adapter, table_fqn)

    dimensions = [freshness, volume, quality, schema, uniqueness]
    discovered = sum(1 for x in dimensions if x is not None and x.get("enabled", True))
    logger.info(
        "[SLA Discovery] %s: %d/5 dimensions discovered (freshness=%s volume=%s quality=%s schema=%s uniqueness=%s)",
        table_fqn,
        discovered,
        "yes" if freshness else "no",
        "yes" if volume else "no",
        "yes" if quality else "no",
        "yes" if schema else "no",
        "yes" if uniqueness and uniqueness.get("enabled") else "no",
    )

    return DiscoveryResult(
        node_fqn=table_fqn,
        warehouse_ancestor_fqn=table_fqn,
        freshness=freshness,
        volume=volume,
        quality=quality,
        schema=schema,
        uniqueness=uniqueness,
    )


async def discover_sla_profiles_bulk(
    nodes: List[LineageNode],
    graph: LineageGraph,
    adapter_registry: Dict[str, Any],
    node_limit: int = 100,
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
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

        result = await discover_sla_profile(
            node,
            graph,
            adapter,
            pipeline_stack_id=pipeline_stack_id,
            organization_id=organization_id,
        )
        results.append(result)

    return results
