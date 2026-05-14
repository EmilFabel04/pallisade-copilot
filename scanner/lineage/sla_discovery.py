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

try:
    from lineage.graph import LineageGraph, LineageNode, NodeType, PlatformDomain
except ImportError:
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


def _volume_dialect_clauses(adapter: Any, table_fqn: str, ts_col: str, days: int) -> Dict[str, str]:
    """Build dialect-specific SQL fragments for daily-volume queries.

    The column is wrapped in ``CAST(... AS TIMESTAMP)`` for the lookback
    comparison so DATETIME columns work on BigQuery (which refuses to
    compare DATETIME against TIMESTAMP) and TIMESTAMP_NTZ vs TIMESTAMP_TZ
    mismatches don't bite on Snowflake.
    """
    dialect = getattr(adapter, "dialect", "").lower()
    db, schema, tbl = _parse_fqn(adapter, table_fqn)

    if dialect == "bigquery":
        quoted_col = f"`{ts_col}`"
        quoted_table = f"`{db}`.`{schema}`.`{tbl}`"
        ts_cast = f"CAST({quoted_col} AS TIMESTAMP)"
        date_expr = f"DATE({ts_cast})"
        lookback = (
            f"{ts_cast} >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), "
            f"INTERVAL {days + 1} DAY)"
        )
        today_excl = f"{date_expr} < CURRENT_DATE()"
    elif dialect == "snowflake":
        quoted_col = f'"{ts_col}"'
        quoted_table = f'{db}.{schema}."{tbl}"'
        ts_cast = f"CAST({quoted_col} AS TIMESTAMP_NTZ)"
        date_expr = f"CAST({ts_cast} AS DATE)"
        lookback = (
            f"{ts_cast} >= DATEADD(day, -{days + 1}, "
            f"CAST(CURRENT_TIMESTAMP() AS TIMESTAMP_NTZ))"
        )
        today_excl = f"{date_expr} < CURRENT_DATE()"
    else:
        quoted_col = f'"{ts_col}"'
        quoted_table = f'"{schema}"."{tbl}"' if schema else f'"{tbl}"'
        ts_cast = f"CAST({quoted_col} AS TIMESTAMP)"
        date_expr = f"CAST({ts_cast} AS DATE)"
        lookback = (
            f"{ts_cast} >= CURRENT_TIMESTAMP - INTERVAL '{days + 1} days'"
        )
        today_excl = f"{date_expr} < CURRENT_DATE"

    return {
        "quoted_col": quoted_col,
        "quoted_table": quoted_table,
        "date_expr": date_expr,
        "lookback": lookback,
        "today_excl": today_excl,
    }


def _run_daily_count_query(
    adapter: Any, clauses: Dict[str, str], days: int, *, exclude_today: bool,
) -> Optional[List[int]]:
    """Execute a per-day COUNT(*) query. None on adapter exception."""
    where = clauses["lookback"]
    if exclude_today:
        where = f"{where} AND {clauses['today_excl']}"
    query = (
        f"SELECT {clauses['date_expr']} AS day, COUNT(*) AS row_count "
        f"FROM {clauses['quoted_table']} "
        f"WHERE {where} "
        f"GROUP BY day ORDER BY day DESC LIMIT {days}"
    )
    try:
        rows = adapter.execute_query(query)
    except Exception as e:
        logger.warning(
            "[SLA Discovery] daily-volume scan failed (exclude_today=%s): %s",
            exclude_today, e,
        )
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
    return counts


def _probe_volume_column(
    adapter: Any, clauses: Dict[str, str], ts_col: str,
) -> Optional[Dict[str, Any]]:
    """Sample the timestamp column once so we can explain *why* the daily
    query came back empty (all-null, all-today, data too old, etc.).

    Returns a dict with ``total_rows``, ``non_null_rows``, ``min_ts``,
    ``max_ts`` — or ``None`` if the probe itself fails.
    """
    query = (
        f"SELECT "
        f"COUNT(*) AS total_rows, "
        f"COUNT({clauses['quoted_col']}) AS non_null_rows, "
        f"MIN({clauses['quoted_col']}) AS min_ts, "
        f"MAX({clauses['quoted_col']}) AS max_ts "
        f"FROM {clauses['quoted_table']}"
    )
    try:
        rows = adapter.execute_query(query)
    except Exception as e:
        logger.warning(
            "[SLA Discovery] volume column probe failed (ts_col=%s): %s",
            ts_col, e,
        )
        return None
    if not rows:
        return None
    row = rows[0] if isinstance(rows, list) else rows
    return {
        "total_rows": int(row.get("total_rows") or 0),
        "non_null_rows": int(row.get("non_null_rows") or 0),
        "min_ts": row.get("min_ts"),
        "max_ts": row.get("max_ts"),
    }


def _explain_empty_volume(probe: Optional[Dict[str, Any]], ts_col: str, days: int) -> str:
    """Translate a probe result into a human-readable disabled reason."""
    if probe is None:
        return (
            f"Daily-volume query against `{ts_col}` returned no rows and the "
            "diagnostic probe failed. Check warehouse permissions or pick a "
            "different timestamp column."
        )
    total = probe.get("total_rows") or 0
    non_null = probe.get("non_null_rows") or 0
    if total == 0:
        return f"Table is empty — no daily volume to learn from `{ts_col}`."
    if non_null == 0:
        return (
            f"All values in `{ts_col}` are NULL — pick a different timestamp "
            "column for daily volume bucketing."
        )
    max_ts = probe.get("max_ts")
    if max_ts is None:
        return (
            f"Daily-volume query against `{ts_col}` returned no rows "
            "(reason unclear). Pick a different timestamp column or disable "
            "volume monitoring."
        )
    return (
        f"`{ts_col}` has {non_null:,} non-null values but none fall within "
        f"the last {days} days (latest is {max_ts}). The data may be "
        "older than the lookback window or the column may carry placeholder "
        "values — pick a different timestamp column."
    )


def _get_daily_row_counts(
    adapter: Any, table_fqn: str, ts_col: str, days: int = 30,
) -> Dict[str, Any]:
    """Per-day COUNT(*) with a forgiving fallback and a diagnostic probe.

    Strategy:
    1. Strict pass excluding today — gives clean min/max for stable tables.
    2. If the strict pass is empty (common on newly-loaded tables where every
       row carries today's load timestamp), retry without ``today_excl`` so
       the table at least gets *some* daily history.
    3. If both passes are empty, run a one-shot probe to explain *why* —
       the user can then act on a specific reason instead of a generic
       "returned no data".

    Returns a dict the caller pattern-matches on::

        {"ok": True,  "counts": [...], "includesToday": False}
        {"ok": True,  "counts": [...], "includesToday": True}   # newly-loaded
        {"ok": False, "reason": "<actionable message>"}
    """
    clauses = _volume_dialect_clauses(adapter, table_fqn, ts_col, days)

    counts = _run_daily_count_query(adapter, clauses, days, exclude_today=True)
    if counts is None:
        # Adapter raised — surface the failure rather than silently degrade.
        return {
            "ok": False,
            "reason": (
                f"Daily-volume query against `{ts_col}` failed. Check "
                "warehouse permissions or pick a different timestamp column."
            ),
        }
    if counts:
        return {"ok": True, "counts": counts, "includesToday": False}

    # Strict pass empty — the table may have only just started loading and
    # every row carries today's date. Retry including today.
    counts = _run_daily_count_query(adapter, clauses, days, exclude_today=False)
    if counts:
        return {"ok": True, "counts": counts, "includesToday": True}

    # Both passes empty: find out why.
    probe = _probe_volume_column(adapter, clauses, ts_col)
    return {"ok": False, "reason": _explain_empty_volume(probe, ts_col, days)}


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
    timestamp_column: Optional[str] = None,
    pipeline_stack_id: Optional[str] = None,  # kept for legacy signature compat; UNUSED
    organization_id: Optional[str] = None,    # kept for legacy signature compat; UNUSED
) -> Optional[Dict[str, Any]]:
    """Derive expected daily volume thresholds from historical row counts.

    Volume monitoring is *daily by definition* in this platform — the
    monitor compares yesterday's row count against a learned daily window,
    so the discovery output mirrors that contract: daily values are the
    headline, ``currentRows`` is supplementary context only.

    The result always carries a ``timeColumn`` when daily computation
    succeeds; downstream wiring threads that into the running monitor's
    ``time_bucket_column`` so SLA thresholds and monitor checks measure
    the same thing.

    Returns ``{enabled: False, disabledReason}`` when daily volume cannot
    be computed (no timestamp column, query fails, or <3 days of history).
    Refusing to fall back to a static total is intentional — comparing a
    daily threshold against a lifetime total produces meaningless checks.

    When ``timestamp_column`` is supplied, it is used directly. Otherwise
    the picker ``_pick_volume_timestamp_column`` is called as a fallback so
    legacy direct callers continue to work. Clarification emission is NOT
    done here — that responsibility belongs to the caller (e.g.
    ``analyze_sla``).
    """
    logger.info(
        "[Clarifications] _compute_volume entered for %s (has_metadata=%s)",
        table_fqn, metadata is not None,
    )

    count = metadata.get("row_count") if metadata else None
    current_rows = int(count) if count is not None and count >= 0 else None

    # Resolve the timestamp column: use the supplied one if given, else fall
    # back to the picker (preserving legacy behaviour for direct callers).
    if timestamp_column is not None:
        ts_col: Optional[str] = timestamp_column
    else:
        pick = _pick_volume_timestamp_column(adapter, table_fqn)
        ts_col = pick.column

    if ts_col is None:
        return {
            "enabled": False,
            "disabledReason": (
                "No timestamp/date column found — daily volume cannot be "
                "computed. Add a column like loaded_at, updated_at, or "
                "created_at, or disable volume monitoring for this table."
            ),
            **({"currentRows": current_rows} if current_rows is not None else {}),
        }

    daily_result = _get_daily_row_counts(adapter, table_fqn, ts_col)
    if not daily_result.get("ok"):
        return {
            "enabled": False,
            "disabledReason": daily_result.get("reason") or (
                f"Daily-volume query against `{ts_col}` returned no rows."
            ),
            "timeColumn": ts_col,
            **({"currentRows": current_rows} if current_rows is not None else {}),
        }

    daily: List[int] = daily_result["counts"]
    includes_today = daily_result.get("includesToday", False)

    if len(daily) < 3:
        return {
            "enabled": False,
            "disabledReason": (
                f"Only {len(daily)} day(s) of history under `{ts_col}` — "
                "need at least 3 to learn a stable daily window. Re-run "
                "discovery once the table has more history."
            ),
            "timeColumn": ts_col,
            "dataPoints": len(daily),
            **({"currentRows": current_rows} if current_rows is not None else {}),
        }

    # When the latest bucket is today's partial day, drop it from the
    # statistics — a half-day count would bias both ``avg`` and ``stddev``
    # downward. ``daily`` is ordered DESC by day, so daily[0] is the newest.
    if includes_today and len(daily) > 3:
        stats_daily = daily[1:]
    else:
        stats_daily = daily

    n = len(stats_daily)
    avg = sum(stats_daily) / n
    variance = sum((x - avg) ** 2 for x in stats_daily) / (n - 1) if n > 1 else 0.0
    stddev = math.sqrt(variance)

    # ±2σ window, clamped and rounded to human-friendly numbers.
    min_rows = _round_volume(max(0.0, avg - 2 * stddev), down=True)
    max_rows = _round_volume(avg + 2 * stddev, down=False)

    # Guarantee a non-degenerate window even on very stable tables.
    if max_rows <= min_rows:
        max_rows = _round_volume(avg * 1.5 + 1, down=False)
        min_rows = _round_volume(avg * 0.5, down=True)

    result: Dict[str, Any] = {
        "enabled": True,
        "expectedDailyRows": int(round(avg)),
        "minRows": int(min_rows),
        "maxRows": int(max_rows),
        "timeColumn": ts_col,
        "dataPoints": n,
    }
    if includes_today:
        result["partialToday"] = True
    if current_rows is not None:
        result["currentRows"] = current_rows
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

    logger.info(
        "[Clarifications] picker for %s: column=%r confidence=%.2f candidates=%s "
        "(threshold=%.2f, pipeline_stack_id=%s)",
        table_fqn,
        pick.column,
        pick.confidence,
        pick.candidates,
        CONFIG.confidence_threshold,
        pipeline_stack_id,
    )

    if not pipeline_stack_id:
        logger.info("[Clarifications] skip emit for %s: no pipeline_stack_id", table_fqn)
        return None
    if pick.confidence >= CONFIG.confidence_threshold:
        logger.info(
            "[Clarifications] skip emit for %s: confidence %.2f ≥ threshold %.2f",
            table_fqn, pick.confidence, CONFIG.confidence_threshold,
        )
        return None
    if not pick.candidates:
        # Nothing to disambiguate between — the user can't pick a column
        # that doesn't exist. Fall back silently.
        logger.info("[Clarifications] skip emit for %s: no candidates", table_fqn)
        return None

    logger.info(
        "[Clarifications] emitting timestamp_choice for %s (confidence=%.2f, %d candidates)",
        table_fqn, pick.confidence, len(pick.candidates),
    )

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
    """Thin wrapper over the shared emit helper for backwards-compat.

    The body lives in ``copilot.clarifications.emit.emit_via_nextjs`` so other
    FastAPI modules (e.g. monitor evaluators) can reuse it.
    """
    try:
        from copilot.clarifications.emit import emit_via_nextjs
    except ImportError:
        from scanner.copilot.clarifications.emit import emit_via_nextjs  # type: ignore

    return emit_via_nextjs(
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
        kind=kind,
        scope_type=scope_type,
        scope_ref=scope_ref,
        payload=payload,
        priority=priority,
    )


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
    """DEPRECATED — wrapper around analyze_sla_profile + compute_sla_profile."""
    try:
        from lineage.sla_analysis import analyze_sla_profile
    except ImportError:
        from scanner.lineage.sla_analysis import analyze_sla_profile

    analysis = analyze_sla_profile(
        node, graph, adapter,
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )
    return compute_sla_profile(
        analysis.plan, graph, adapter,
        answers={},
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )


def _resolve_volume_timestamp(plan: Any, answers: Dict[str, Any]) -> Optional[str]:
    """Pick the timestamp column for volume computation.

    Precedence: any answer carrying a 'column' key, else plan.volume_timestamp_pick.column.
    """
    for value in answers.values():
        if isinstance(value, dict) and value.get("column"):
            return value["column"]
    pick = plan.volume_timestamp_pick or {}
    return pick.get("column")


def compute_sla(
    plan: Any,
    adapter: Any,
    *,
    answers: Optional[Dict[str, Any]] = None,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> DiscoveryResult:
    """Phase 2: run dimension SQL using the analyzed plan + user answers.

    Takes an ``AnalysisPlan`` (from ``analyze_sla``) and a ``{request_id: answer}``
    dict produced by the clarification engine, then runs the actual dimension
    computations against the warehouse.
    """
    if plan.unsupported:
        return DiscoveryResult(
            node_fqn=plan.table_fqn,
            warehouse_ancestor_fqn=plan.warehouse_ancestor_fqn,
            unsupported=True,
            skipped_reason=plan.skipped_reason,
        )

    chosen_ts = _resolve_volume_timestamp(plan, answers or {})
    metadata = {"row_count": plan.row_count} if plan.row_count is not None else None

    volume = _compute_volume(
        adapter,
        plan.table_fqn,
        metadata=metadata,
        timestamp_column=chosen_ts,
    )
    freshness = _compute_freshness(adapter, plan.table_fqn, metadata=metadata)
    schema = _compute_schema(adapter, plan.table_fqn)
    quality = _compute_quality(adapter, plan.table_fqn)
    uniqueness = _compute_uniqueness(adapter, plan.table_fqn)

    return DiscoveryResult(
        node_fqn=plan.table_fqn,
        warehouse_ancestor_fqn=plan.warehouse_ancestor_fqn,
        freshness=freshness,
        volume=volume,
        quality=quality,
        schema=schema,
        uniqueness=uniqueness,
    )


def compute_sla_profile(
    plan: Any,  # AnalysisPlan duck-typed; avoid module-level cycle
    graph: Any,
    adapter: Any,
    *,
    answers: Optional[Dict[str, Any]] = None,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> DiscoveryResult:
    """Graph variant — ``graph`` accepted for symmetry; warehouse ancestor is on plan."""
    return compute_sla(
        plan,
        adapter,
        answers=answers,
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )


def compute_sla_bulk(
    plans: List[tuple],  # (plan, platform, answers)
    adapters: Dict[str, Any],
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> List[DiscoveryResult]:
    """Bulk compute: run phase 2 for multiple plans.

    Simple loop wrapper — takes a list of (plan, platform_key, answers) tuples
    and returns a list of DiscoveryResults, one per plan.
    """
    results: List[DiscoveryResult] = []
    for plan, platform, answers in plans:
        adapter = adapters.get(platform)
        if adapter is None:
            results.append(
                DiscoveryResult(
                    node_fqn=plan.table_fqn,
                    warehouse_ancestor_fqn=plan.warehouse_ancestor_fqn,
                    unsupported=True,
                    skipped_reason=f"No adapter for platform '{platform}'.",
                )
            )
            continue
        results.append(
            compute_sla(
                plan,
                adapter,
                answers=answers,
                pipeline_stack_id=pipeline_stack_id,
                organization_id=organization_id,
            )
        )
    return results


async def discover_sla_direct(
    table_fqn: str,
    adapter: Any,
    *,
    pipeline_stack_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> DiscoveryResult:
    """DEPRECATED — thin wrapper around analyze + compute with empty answers.

    Kept during rollout so legacy callers still work. New callers should call
    `analyze_sla` followed by `compute_sla` directly so they can surface any
    `awaiting_clarifications` state to the user. Will be removed once the
    cutover deploy confirms zero hits to this path.
    """
    # Lazy-import to mirror sla_analysis.py's circular-import workaround.
    try:
        from lineage.sla_analysis import analyze_sla
    except ImportError:
        from scanner.lineage.sla_analysis import analyze_sla

    logger.info("[SLA Discovery] Direct (deprecated wrapper) profiling %s", table_fqn)
    analysis = analyze_sla(
        table_fqn=table_fqn,
        adapter=adapter,
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
    )
    return compute_sla(
        analysis.plan,
        adapter,
        answers={},
        pipeline_stack_id=pipeline_stack_id,
        organization_id=organization_id,
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
    """DEPRECATED — wrapper that loops over discover_sla_profile."""
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
