# SLA Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-discover SLA thresholds from warehouse history during lineage scans and surface them to users for confirmation.

**Architecture:** Discovery runs as a post-step in the lineage orchestrator. It traverses upstream lineage to find warehouse ancestors, queries their historical metadata via adapters, computes statistical thresholds, and returns `DiscoveryResult` objects. The Next.js API persists results as `PolicyProfile` + `PolicyAssignment` records with `assignmentType: 'auto_discovered'`, which the existing resolver chain handles at priority 5 (below user-defined, above defaults). The frontend shows results inline in `DataAssetDetailPanel`.

**Tech Stack:** Python (scanner), Prisma (schema), Next.js API routes (persistence + on-demand), React (UI)

**Spec:** `docs/superpowers/specs/2026-04-02-sla-discovery-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `scanner/lineage/sla_discovery.py` | Core discovery logic: ancestor resolution, statistical computation, result types |
| Create | `scanner/tests/test_sla_discovery.py` | Tests for discovery module |
| Modify | `scanner/adapters/base.py` | Four new abstract methods for historical queries |
| Modify | `scanner/adapters/bigquery.py` | Implement historical query methods for BigQuery |
| Modify | `scanner/adapters/snowflake.py` | Implement historical query methods for Snowflake |
| Modify | `scanner/monitors/policy_resolver.py:443-459` | Insert `auto_discovered` layer between branch and criticality_default |
| Modify | `scanner/tests/test_policy_resolver.py` | Tests for auto_discovered layer |
| Modify | `scanner/lineage/orchestrator.py:141-159` | Hook discovery into `extract_all()` after `compute_depths()` |
| Modify | `prisma/schema.prisma` | Add `slaDiscoveryNodeLimit` to Organization, add `auto_discovered` to PolicyAssignment |
| Modify | `types/sla.ts` | Update `SLAAssignmentType` and `EffectiveSLAPolicy.source` |
| Modify | `app/api/schedule/policies/resolve/route.ts:85-98` | Add `auto_discovered` to fallback indexing |
| Modify | `app/api/schedule/policies/assign/route.ts` | Handle `auto_discovered` assignment type |
| Create | `app/api/nodes/[nodeId]/sla/discover/route.ts` | On-demand discovery endpoint |
| Create | `app/api/lineage/discovery/route.ts` | Batch persistence endpoint for scan-time results |
| Modify | `components/lineage/DataAssetDetailPanel.tsx:1316-1361` | Discovery UI: empty state, confirmation, auto-discovered banner |
| Modify | `components/lineage/SlaProfileModal.tsx` | Add `auto_discovered` to source labels |

---

### Task 1: Prisma Schema — Add `slaDiscoveryNodeLimit` and Update Assignment Types

**Files:**
- Modify: `prisma/schema.prisma` (Organization model + PolicyAssignment unique constraint)

- [ ] **Step 1: Add `slaDiscoveryNodeLimit` to Organization model**

In `prisma/schema.prisma`, find the `Organization` model and add the field before the relations section:

```prisma
slaDiscoveryNodeLimit  Int  @default(100)
```

- [ ] **Step 2: Run migration**

```bash
cd /Users/emilfabel/pallisade-copilot && npx prisma migrate dev --name add-sla-discovery-node-limit
```

Expected: Migration created and applied successfully.

- [ ] **Step 3: Generate Prisma client**

```bash
npx prisma generate
```

Expected: Prisma client generated with new field.

- [ ] **Step 4: Commit**

```bash
git add prisma/ && git commit -m "feat: add slaDiscoveryNodeLimit to Organization model"
```

---

### Task 2: Update TypeScript SLA Types

**Files:**
- Modify: `types/sla.ts`

- [ ] **Step 1: Update `SLAAssignmentType`**

In `types/sla.ts`, find the `SLAAssignmentType` union (line ~100) and add `auto_discovered`:

```typescript
export type SLAAssignmentType = 'direct' | 'branch' | 'auto_discovered' | 'domain_default' | 'criticality_default';
```

- [ ] **Step 2: Update `EffectiveSLAPolicy.source` comment**

Find the `source` field in `EffectiveSLAPolicy` (line ~127) and update the comment:

```typescript
source: string;  // direct_override | direct_profile | imported_dbt | branch | auto_discovered | criticality_default | domain_default | builtin
```

- [ ] **Step 3: Run type check**

```bash
npx tsc --noEmit 2>&1 | grep -v vitest | grep "error" | head -5
```

Expected: No new errors.

- [ ] **Step 4: Commit**

```bash
git add types/sla.ts && git commit -m "feat: add auto_discovered to SLA assignment types"
```

---

### Task 3: Python Policy Resolver — Add `auto_discovered` Layer

**Files:**
- Modify: `scanner/monitors/policy_resolver.py:443-445`
- Test: `scanner/tests/test_policy_resolver.py`

- [ ] **Step 1: Write failing test for auto_discovered resolution**

Add to `scanner/tests/test_policy_resolver.py`, in the `TestResolutionPrecedence` class:

```python
def test_auto_discovered_used_when_no_direct_or_branch(self):
    """auto_discovered layer sits between branch and criticality_default."""
    profiles = _make_profiles(
        ("p1", "Auto-discovered: db.schema.t1", {
            "freshnessConfig": {"enabled": True, "maxHours": 6, "warningHours": 3},
        }),
    )
    assignments = [
        {
            "assignmentType": "auto_discovered",
            "nodeFqn": "db.schema.t1",
            "profileId": "p1",
        },
    ]
    policy = resolve_policy(
        node_fqn="db.schema.t1",
        node_domain="warehouse",
        node_criticality="medium",
        assignments=assignments,
        profiles=profiles,
    )
    assert policy.source == "auto_discovered"
    assert policy.freshness_max_hours == 6
    assert policy.freshness_warning_hours == 3

def test_direct_beats_auto_discovered(self):
    """direct_profile takes precedence over auto_discovered."""
    profiles = _make_profiles(
        ("p1", "User Profile", {
            "freshnessConfig": {"enabled": True, "maxHours": 2, "warningHours": 1},
        }),
        ("p2", "Auto-discovered: db.schema.t1", {
            "freshnessConfig": {"enabled": True, "maxHours": 12, "warningHours": 6},
        }),
    )
    assignments = [
        {"assignmentType": "direct", "nodeFqn": "db.schema.t1", "profileId": "p1"},
        {"assignmentType": "auto_discovered", "nodeFqn": "db.schema.t1", "profileId": "p2"},
    ]
    policy = resolve_policy(
        node_fqn="db.schema.t1",
        node_domain="warehouse",
        node_criticality="medium",
        assignments=assignments,
        profiles=profiles,
    )
    assert policy.source == "direct_profile"
    assert policy.freshness_max_hours == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/emilfabel/pallisade-copilot && python -m pytest scanner/tests/test_policy_resolver.py::TestResolutionPrecedence::test_auto_discovered_used_when_no_direct_or_branch -v
```

Expected: FAIL — auto_discovered assignment type is not handled, falls through to builtin.

- [ ] **Step 3: Add `auto_discovered` layer to `resolve_policy()`**

In `scanner/monitors/policy_resolver.py`, after line 443 (the branch profile layer append) and before line 445 (`# Layer 5: Criticality default`), insert:

```python
    # Layer 5: Auto-discovered (from warehouse history analysis)
    auto_discovered_assignments = [
        a for a in assignments
        if a.get("assignmentType") == "auto_discovered"
        and a.get("nodeFqn") == node_fqn
    ]
    if auto_discovered_assignments:
        ad = auto_discovered_assignments[0]
        profile = profiles.get(ad.get("profileId", ""), {})
        pid = ad.get("profileId")
        pname = profile.get("name")
        profile_fields = _extract_all_fields_from_profile(profile)
        if profile_fields:
            layers.append(("auto_discovered", profile_fields, pid, pname))
```

Update the comment on the next layer from `# Layer 5:` to `# Layer 6:`, and shift all subsequent layer comments by one.

Also update the docstring source comment on the `EffectivePolicy` dataclass (line ~36):

```python
source: str = "builtin"  # direct_override | direct_profile | imported_dbt | branch | auto_discovered | criticality_default | domain_default | builtin
```

And update the module docstring resolution chain to include auto_discovered between branch and criticality_default.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest scanner/tests/test_policy_resolver.py -v
```

Expected: All tests pass including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add scanner/monitors/policy_resolver.py scanner/tests/test_policy_resolver.py && git commit -m "feat: add auto_discovered layer to policy resolver chain"
```

---

### Task 4: TypeScript Resolve Route — Add `auto_discovered` to Fallback

**Files:**
- Modify: `app/api/schedule/policies/resolve/route.ts:85-98`

- [ ] **Step 1: Add `auto_discovered` index to fallback resolution**

In `app/api/schedule/policies/resolve/route.ts`, after the existing `directByFqn`, `critDefaults`, `domainDefaults` Maps (around line 88), add:

```typescript
const autoDiscoveredByFqn = new Map<string, typeof assignments[0]>();
```

In the `for (const a of assignments)` loop (around line 90), add an additional branch:

```typescript
} else if (a.assignmentType === 'auto_discovered' && a.nodeFqn) {
  autoDiscoveredByFqn.set(a.nodeFqn, a);
}
```

- [ ] **Step 2: Add `auto_discovered` resolution step**

In the resolution chain `for (const node of nodes)` loop, after the direct assignment check (around line 138) and before the criticality_default check, add:

```typescript
const autoDiscovered = autoDiscoveredByFqn.get(node.fqn);
if (autoDiscovered) {
  const profile = profileMap[autoDiscovered.profileId];
  policies[node.fqn] = {
    source: 'auto_discovered',
    profileId: autoDiscovered.profileId,
    profileName: profile?.name || null,
    status: 'assigned',
    ...configFromProfile(profile),
  };
  continue;
}
```

- [ ] **Step 3: Run type check**

```bash
npx tsc --noEmit 2>&1 | grep -v vitest | grep "error" | head -5
```

Expected: No new errors.

- [ ] **Step 4: Commit**

```bash
git add app/api/schedule/policies/resolve/route.ts && git commit -m "feat: add auto_discovered to TypeScript policy resolver fallback"
```

---

### Task 5: Adapter Base — Add Historical Query Method Stubs

**Files:**
- Modify: `scanner/adapters/base.py`

- [ ] **Step 1: Add four new method stubs to `DatabaseAdapter`**

In `scanner/adapters/base.py`, after the existing `detect_timestamp_column` method (around line 438), add:

```python
def get_freshness_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
    """Return modification timestamps over the lookback window.

    Returns:
        List of dicts with key 'timestamp' (datetime).
    """
    raise NotImplementedError(f"{type(self).__name__} does not support get_freshness_history")

def get_row_count_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
    """Return daily row counts over the lookback window.

    Returns:
        List of dicts with keys 'date' (date) and 'row_count' (int).
    """
    raise NotImplementedError(f"{type(self).__name__} does not support get_row_count_history")

def get_daily_null_rates(self, table: str, timestamp_column: str, days: int = 30) -> List[Dict[str, Any]]:
    """Return daily null rates over the lookback window, partitioned by timestamp_column.

    Returns:
        List of dicts with keys 'date' (date) and 'null_rate' (float, 0.0-1.0).
    """
    raise NotImplementedError(f"{type(self).__name__} does not support get_daily_null_rates")

def get_schema_change_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
    """Return schema changes over the lookback window.

    Returns:
        List of dicts with keys 'date' (date), 'change_type' ('added'|'removed'),
        and 'column_name' (str).
    """
    raise NotImplementedError(f"{type(self).__name__} does not support get_schema_change_history")
```

Add `List, Dict` to the imports from `typing` if not already present.

- [ ] **Step 2: Commit**

```bash
git add scanner/adapters/base.py && git commit -m "feat: add historical query method stubs to DatabaseAdapter"
```

---

### Task 6: BigQuery Adapter — Implement Historical Query Methods

**Files:**
- Modify: `scanner/adapters/bigquery.py`

- [ ] **Step 1: Implement `get_freshness_history`**

Add to `BigQueryAdapter` class:

```python
def get_freshness_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
    """Query INFORMATION_SCHEMA.TABLE_STORAGE_TIMELINE for modification timestamps."""
    parts = table.replace("`", "").split(".")
    if len(parts) == 3:
        project, dataset, tbl = parts
    elif len(parts) == 2:
        project, dataset, tbl = self.project, parts[0], parts[1]
    else:
        project, dataset, tbl = self.project, self.dataset, parts[0]

    query = f"""
        SELECT DISTINCT DATE(storage_last_modified_time) as mod_date,
               MAX(storage_last_modified_time) as timestamp
        FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLE_STORAGE_TIMELINE`
        WHERE table_name = '{tbl}'
          AND storage_last_modified_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        GROUP BY mod_date
        ORDER BY mod_date
    """
    rows = self.query(query)
    return [{"timestamp": row["timestamp"]} for row in rows]
```

- [ ] **Step 2: Implement `get_row_count_history`**

```python
def get_row_count_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
    """Query INFORMATION_SCHEMA.TABLE_STORAGE_TIMELINE for daily row counts."""
    parts = table.replace("`", "").split(".")
    if len(parts) == 3:
        project, dataset, tbl = parts
    elif len(parts) == 2:
        project, dataset, tbl = self.project, parts[0], parts[1]
    else:
        project, dataset, tbl = self.project, self.dataset, parts[0]

    query = f"""
        SELECT DATE(storage_last_modified_time) as date,
               MAX(total_rows) as row_count
        FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLE_STORAGE_TIMELINE`
        WHERE table_name = '{tbl}'
          AND storage_last_modified_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        GROUP BY date
        ORDER BY date
    """
    rows = self.query(query)
    return [{"date": row["date"], "row_count": int(row["row_count"])} for row in rows]
```

- [ ] **Step 3: Implement `get_daily_null_rates`**

```python
def get_daily_null_rates(self, table: str, timestamp_column: str, days: int = 30) -> List[Dict[str, Any]]:
    """Query daily null rates partitioned by timestamp column."""
    parts = table.replace("`", "").split(".")
    if len(parts) == 3:
        project, dataset, tbl = parts
    elif len(parts) == 2:
        project, dataset, tbl = self.project, parts[0], parts[1]
    else:
        project, dataset, tbl = self.project, self.dataset, parts[0]

    # Get non-timestamp columns
    cols_query = f"""
        SELECT column_name FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
        WHERE table_name = '{tbl}' AND column_name != '{timestamp_column}'
    """
    col_rows = self.query(cols_query)
    columns = [r["column_name"] for r in col_rows]
    if not columns:
        return []

    null_exprs = " + ".join(f"COUNTIF(`{c}` IS NULL)" for c in columns)
    total_expr = f"COUNT(*) * {len(columns)}"

    query = f"""
        SELECT DATE(`{timestamp_column}`) as date,
               SAFE_DIVIDE({null_exprs}, {total_expr}) as null_rate
        FROM `{project}.{dataset}.{tbl}`
        WHERE `{timestamp_column}` >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        GROUP BY date
        ORDER BY date
    """
    rows = self.query(query)
    return [{"date": row["date"], "null_rate": float(row["null_rate"] or 0)} for row in rows]
```

- [ ] **Step 4: Implement `get_schema_change_history`**

```python
def get_schema_change_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
    """Query INFORMATION_SCHEMA.COLUMN_FIELD_PATHS for schema changes.

    BigQuery doesn't have a direct schema change history view. We compare
    the current schema against what we can infer from TABLE_STORAGE_TIMELINE.
    For V1, return an empty list (no changes detected = strict schema suggestion).
    """
    # BigQuery INFORMATION_SCHEMA doesn't track column-level change history.
    # TABLE_STORAGE_TIMELINE tracks storage changes but not schema diffs.
    # Return empty — discovery will suggest strict/no-evolution (safe default).
    return []
```

- [ ] **Step 5: Commit**

```bash
git add scanner/adapters/bigquery.py && git commit -m "feat: implement historical query methods in BigQuery adapter"
```

---

### Task 7: Snowflake Adapter — Implement Historical Query Methods

**Files:**
- Modify: `scanner/adapters/snowflake.py`

- [ ] **Step 1: Implement `get_freshness_history`**

```python
def get_freshness_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
    """Query ACCOUNT_USAGE.TABLE_STORAGE_METRICS for modification timestamps."""
    parts = table.split(".")
    if len(parts) == 3:
        db, schema, tbl = parts
    elif len(parts) == 2:
        db, schema, tbl = self.database, parts[0], parts[1]
    else:
        db, schema, tbl = self.database, self.schema, parts[0]

    query = f"""
        SELECT DISTINCT DATE(ACTIVE_BYTES_TIMESTAMP) as mod_date,
               MAX(ACTIVE_BYTES_TIMESTAMP) as timestamp
        FROM {db}.INFORMATION_SCHEMA.TABLE_STORAGE_METRICS
        WHERE TABLE_NAME = '{tbl.upper()}' AND TABLE_SCHEMA = '{schema.upper()}'
          AND ACTIVE_BYTES_TIMESTAMP >= DATEADD(DAY, -{days}, CURRENT_TIMESTAMP())
        GROUP BY mod_date
        ORDER BY mod_date
    """
    rows = self.query(query)
    return [{"timestamp": row["TIMESTAMP"]} for row in rows]
```

- [ ] **Step 2: Implement `get_row_count_history`**

```python
def get_row_count_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
    """Query ACCOUNT_USAGE.TABLE_STORAGE_METRICS for daily row counts."""
    parts = table.split(".")
    if len(parts) == 3:
        db, schema, tbl = parts
    elif len(parts) == 2:
        db, schema, tbl = self.database, parts[0], parts[1]
    else:
        db, schema, tbl = self.database, self.schema, parts[0]

    query = f"""
        SELECT DATE(ACTIVE_BYTES_TIMESTAMP) as DATE,
               MAX(ROW_COUNT) as ROW_COUNT
        FROM {db}.INFORMATION_SCHEMA.TABLE_STORAGE_METRICS
        WHERE TABLE_NAME = '{tbl.upper()}' AND TABLE_SCHEMA = '{schema.upper()}'
          AND ACTIVE_BYTES_TIMESTAMP >= DATEADD(DAY, -{days}, CURRENT_TIMESTAMP())
        GROUP BY DATE
        ORDER BY DATE
    """
    rows = self.query(query)
    return [{"date": row["DATE"], "row_count": int(row["ROW_COUNT"])} for row in rows]
```

- [ ] **Step 3: Implement `get_daily_null_rates`**

```python
def get_daily_null_rates(self, table: str, timestamp_column: str, days: int = 30) -> List[Dict[str, Any]]:
    """Query daily null rates partitioned by timestamp column."""
    parts = table.split(".")
    if len(parts) == 3:
        db, schema, tbl = parts
    elif len(parts) == 2:
        db, schema, tbl = self.database, parts[0], parts[1]
    else:
        db, schema, tbl = self.database, self.schema, parts[0]

    # Get non-timestamp columns
    cols_query = f"""
        SELECT COLUMN_NAME FROM {db}.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = '{tbl.upper()}' AND TABLE_SCHEMA = '{schema.upper()}'
          AND COLUMN_NAME != '{timestamp_column.upper()}'
    """
    col_rows = self.query(cols_query)
    columns = [r["COLUMN_NAME"] for r in col_rows]
    if not columns:
        return []

    null_exprs = " + ".join(f'COUNT(CASE WHEN "{c}" IS NULL THEN 1 END)' for c in columns)
    total_expr = f"COUNT(*) * {len(columns)}"

    query = f"""
        SELECT DATE("{timestamp_column}") as DATE,
               DIV0({null_exprs}, {total_expr}) as NULL_RATE
        FROM {db}.{schema}.{tbl}
        WHERE "{timestamp_column}" >= DATEADD(DAY, -{days}, CURRENT_TIMESTAMP())
        GROUP BY DATE
        ORDER BY DATE
    """
    rows = self.query(query)
    return [{"date": row["DATE"], "null_rate": float(row["NULL_RATE"] or 0)} for row in rows]
```

- [ ] **Step 4: Implement `get_schema_change_history`**

```python
def get_schema_change_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
    """Snowflake ACCOUNT_USAGE.COLUMNS tracks column history but with 45-min latency.
    For V1, return empty list (safe default: strict schema suggestion)."""
    return []
```

- [ ] **Step 5: Commit**

```bash
git add scanner/adapters/snowflake.py && git commit -m "feat: implement historical query methods in Snowflake adapter"
```

---

### Task 8: Core Discovery Module — `sla_discovery.py`

**Files:**
- Create: `scanner/lineage/sla_discovery.py`
- Create: `scanner/tests/test_sla_discovery.py`

- [ ] **Step 1: Write tests for `_find_warehouse_ancestor`**

Create `scanner/tests/test_sla_discovery.py`:

```python
"""Tests for SLA discovery — ancestor resolution and statistical computation."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from scanner.lineage.graph import (
    LineageGraph,
    LineageNode,
    LineageEdge,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.sla_discovery import (
    DiscoveryResult,
    _find_warehouse_ancestor,
    _compute_freshness,
    _compute_volume,
    _compute_quality,
    _compute_schema,
)


def _make_node(fqn: str, platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
               node_type: NodeType = NodeType.TABLE, **kwargs) -> LineageNode:
    return LineageNode(
        id=fqn, name=fqn.split(".")[-1], fqn=fqn,
        node_type=node_type, platform_domain=platform_domain, **kwargs,
    )


def _make_graph(*nodes_and_edges) -> LineageGraph:
    """Build a graph from nodes and (source_fqn, target_fqn) edge tuples."""
    g = LineageGraph()
    nodes = [x for x in nodes_and_edges if isinstance(x, LineageNode)]
    edges = [x for x in nodes_and_edges if isinstance(x, tuple)]
    for n in nodes:
        g.add_node(n)
    for src, tgt in edges:
        g.add_edge(LineageEdge(
            id=f"{src}->{tgt}", source_id=src, target_id=tgt,
            edge_type="depends_on",
        ))
    return g


class TestFindWarehouseAncestor:
    def test_warehouse_node_returns_self(self):
        node = _make_node("db.schema.orders", PlatformDomain.WAREHOUSE, NodeType.TABLE)
        graph = _make_graph(node)
        result = _find_warehouse_ancestor(node, graph)
        assert result is node

    def test_view_returns_self(self):
        node = _make_node("db.schema.v_orders", PlatformDomain.WAREHOUSE, NodeType.VIEW)
        graph = _make_graph(node)
        result = _find_warehouse_ancestor(node, graph)
        assert result is node

    def test_dbt_model_finds_upstream_table(self):
        table = _make_node("db.schema.raw_orders", PlatformDomain.WAREHOUSE, NodeType.TABLE)
        model = _make_node("db.schema.stg_orders", PlatformDomain.TRANSFORM, NodeType.MODEL)
        graph = _make_graph(table, model, (table.id, model.id))
        result = _find_warehouse_ancestor(model, graph)
        assert result is table

    def test_no_warehouse_ancestor_returns_none(self):
        dag = _make_node("airflow.dag1", PlatformDomain.ORCHESTRATION, NodeType.TASK)
        graph = _make_graph(dag)
        result = _find_warehouse_ancestor(dag, graph)
        assert result is None

    def test_finds_nearest_ancestor(self):
        t1 = _make_node("db.schema.raw", PlatformDomain.WAREHOUSE, NodeType.TABLE)
        t2 = _make_node("db.schema.staging", PlatformDomain.WAREHOUSE, NodeType.TABLE)
        model = _make_node("db.schema.final", PlatformDomain.TRANSFORM, NodeType.MODEL)
        # raw -> staging -> final
        graph = _make_graph(t1, t2, model, (t1.id, t2.id), (t2.id, model.id))
        result = _find_warehouse_ancestor(model, graph)
        assert result is t2  # nearest


class TestComputeFreshness:
    def test_basic_freshness(self):
        adapter = MagicMock()
        now = datetime.utcnow()
        # 4-hour intervals over 30 days
        timestamps = [{"timestamp": now - timedelta(hours=4 * i)} for i in range(180)]
        adapter.get_freshness_history.return_value = timestamps

        result = _compute_freshness(adapter, "db.schema.orders")
        assert result is not None
        assert result["enabled"] is True
        assert result["maxHours"] >= 1
        assert result["warningHours"] >= 1

    def test_empty_history_returns_none(self):
        adapter = MagicMock()
        adapter.get_freshness_history.return_value = []
        result = _compute_freshness(adapter, "db.schema.orders")
        assert result is None

    def test_not_implemented_returns_none(self):
        adapter = MagicMock()
        adapter.get_freshness_history.side_effect = NotImplementedError
        result = _compute_freshness(adapter, "db.schema.orders")
        assert result is None


class TestComputeVolume:
    def test_basic_volume(self):
        adapter = MagicMock()
        # 30 days of ~10000 rows with some variance
        history = [{"date": date.today() - timedelta(days=i), "row_count": 10000 + (i * 10)} for i in range(30)]
        adapter.get_row_count_history.return_value = history

        result = _compute_volume(adapter, "db.schema.orders")
        assert result is not None
        assert result["enabled"] is True
        assert result["minRows"] >= 0
        assert result["maxRows"] > result["minRows"]

    def test_insufficient_history_returns_none(self):
        adapter = MagicMock()
        adapter.get_row_count_history.return_value = [
            {"date": date.today() - timedelta(days=i), "row_count": 100} for i in range(3)
        ]
        result = _compute_volume(adapter, "db.schema.orders")
        assert result is None  # fewer than 7 data points

    def test_not_implemented_returns_none(self):
        adapter = MagicMock()
        adapter.get_row_count_history.side_effect = NotImplementedError
        result = _compute_volume(adapter, "db.schema.orders")
        assert result is None


class TestComputeQuality:
    def test_basic_quality(self):
        adapter = MagicMock()
        history = [{"date": date.today() - timedelta(days=i), "null_rate": 0.02 + (i * 0.001)} for i in range(30)]
        adapter.get_daily_null_rates.return_value = history

        result = _compute_quality(adapter, "db.schema.orders", "created_at")
        assert result is not None
        assert result["enabled"] is True
        assert 0 < result["maxNullRate"] <= 0.5

    def test_insufficient_history_returns_none(self):
        adapter = MagicMock()
        adapter.get_daily_null_rates.return_value = [
            {"date": date.today(), "null_rate": 0.05},
        ]
        result = _compute_quality(adapter, "db.schema.orders", "created_at")
        assert result is None

    def test_not_implemented_returns_none(self):
        adapter = MagicMock()
        adapter.get_daily_null_rates.side_effect = NotImplementedError
        result = _compute_quality(adapter, "db.schema.orders", "created_at")
        assert result is None

    def test_caps_at_50_percent(self):
        adapter = MagicMock()
        # Very high null rates — should cap at 0.5
        history = [{"date": date.today() - timedelta(days=i), "null_rate": 0.9} for i in range(30)]
        adapter.get_daily_null_rates.return_value = history

        result = _compute_quality(adapter, "db.schema.orders", "created_at")
        assert result is not None
        assert result["maxNullRate"] == 0.5


class TestComputeSchema:
    def test_no_changes_suggests_strict(self):
        adapter = MagicMock()
        adapter.get_schema_change_history.return_value = []
        result = _compute_schema(adapter, "db.schema.orders")
        assert result is not None
        assert result["strictness"] == "strict"
        assert result["allowEvolution"] is False

    def test_additions_suggest_warn(self):
        adapter = MagicMock()
        adapter.get_schema_change_history.return_value = [
            {"date": date.today(), "change_type": "added", "column_name": "new_col"},
        ]
        result = _compute_schema(adapter, "db.schema.orders")
        assert result["strictness"] == "warn"
        assert result["allowEvolution"] is True

    def test_removals_suggest_warn(self):
        adapter = MagicMock()
        adapter.get_schema_change_history.return_value = [
            {"date": date.today(), "change_type": "removed", "column_name": "old_col"},
        ]
        result = _compute_schema(adapter, "db.schema.orders")
        assert result["strictness"] == "warn"
        assert result["allowEvolution"] is True

    def test_not_implemented_returns_none(self):
        adapter = MagicMock()
        adapter.get_schema_change_history.side_effect = NotImplementedError
        result = _compute_schema(adapter, "db.schema.orders")
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest scanner/tests/test_sla_discovery.py -v 2>&1 | head -20
```

Expected: ImportError — module doesn't exist yet.

- [ ] **Step 3: Implement `scanner/lineage/sla_discovery.py`**

Create `scanner/lineage/sla_discovery.py`:

```python
"""
SLA Discovery — compute suggested SLA thresholds from warehouse history.

Runs after lineage graph construction. For each eligible node, traverses
upstream to find the nearest warehouse table ancestor, queries historical
metadata, and returns suggested freshness/volume/quality/schema thresholds.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean, stdev
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.adapters.base import DatabaseAdapter
    from scanner.lineage.graph import LineageGraph, LineageNode

from scanner.lineage.graph import PlatformDomain, NodeType

logger = logging.getLogger(__name__)

MIN_DATA_POINTS = 7  # Minimum observations needed for statistical thresholds


@dataclass
class DiscoveryResult:
    node_fqn: str
    warehouse_ancestor_fqn: Optional[str] = None
    freshness: Optional[Dict[str, Any]] = None
    volume: Optional[Dict[str, Any]] = None
    quality: Optional[Dict[str, Any]] = None
    schema: Optional[Dict[str, Any]] = None
    unsupported: bool = False
    skipped_reason: Optional[str] = None


def _find_warehouse_ancestor(node: "LineageNode", graph: "LineageGraph") -> Optional["LineageNode"]:
    """BFS upstream to find the nearest warehouse table/view ancestor."""
    if (node.platform_domain == PlatformDomain.WAREHOUSE
            and node.node_type in (NodeType.TABLE, NodeType.VIEW)):
        return node

    visited = {node.id}
    queue = deque()

    # Seed with immediate upstream neighbors, sorted for determinism
    upstream_ids = sorted(graph._upstream.get(node.id, set()))
    for uid in upstream_ids:
        if uid not in visited:
            visited.add(uid)
            queue.append(uid)

    while queue:
        current_id = queue.popleft()
        candidate = graph.nodes.get(current_id)
        if candidate is None:
            continue

        if (candidate.platform_domain == PlatformDomain.WAREHOUSE
                and candidate.node_type in (NodeType.TABLE, NodeType.VIEW)):
            return candidate

        next_ids = sorted(graph._upstream.get(current_id, set()))
        for uid in next_ids:
            if uid not in visited:
                visited.add(uid)
                queue.append(uid)

    return None


def _compute_freshness(adapter: "DatabaseAdapter", table_fqn: str) -> Optional[Dict[str, Any]]:
    """Compute freshness thresholds from historical modification timestamps."""
    try:
        history = adapter.get_freshness_history(table_fqn)
    except (NotImplementedError, Exception) as e:
        logger.debug(f"[SLA Discovery] Freshness history unavailable for {table_fqn}: {e}")
        return None

    if not history or len(history) < 2:
        return None

    # Sort timestamps and compute intervals in hours
    timestamps = sorted(h["timestamp"] for h in history if h.get("timestamp"))
    if len(timestamps) < 2:
        return None

    intervals = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds() / 3600
        if delta > 0:
            intervals.append(delta)

    if not intervals:
        return None

    mean_hours = mean(intervals)
    sorted_intervals = sorted(intervals)
    p95_idx = int(len(sorted_intervals) * 0.95)
    p95_hours = sorted_intervals[min(p95_idx, len(sorted_intervals) - 1)]

    # maxHours = p95 + 20% buffer, rounded up, minimum 1
    max_hours = max(1, math.ceil(p95_hours * 1.2))
    warning_hours = max(1, math.ceil(mean_hours))

    return {
        "enabled": True,
        "maxHours": max_hours,
        "warningHours": warning_hours,
    }


def _compute_volume(adapter: "DatabaseAdapter", table_fqn: str) -> Optional[Dict[str, Any]]:
    """Compute volume thresholds from historical row counts."""
    try:
        history = adapter.get_row_count_history(table_fqn)
    except (NotImplementedError, Exception) as e:
        logger.debug(f"[SLA Discovery] Row count history unavailable for {table_fqn}: {e}")
        return None

    if not history or len(history) < MIN_DATA_POINTS:
        return None

    counts = [h["row_count"] for h in history if h.get("row_count") is not None]
    if len(counts) < MIN_DATA_POINTS:
        return None

    avg = mean(counts)
    sd = stdev(counts) if len(counts) > 1 else 0

    min_rows = max(0, int(avg - 2 * sd))
    max_rows = int(avg + 2 * sd)

    # Detect consistent growth for growthRateThreshold
    growth_rate = None
    if len(counts) >= 7:
        daily_rates = []
        for i in range(1, len(counts)):
            if counts[i - 1] > 0:
                daily_rates.append((counts[i] - counts[i - 1]) / counts[i - 1])
        if daily_rates and all(r > 0 for r in daily_rates):
            growth_rate = round(mean(daily_rates) * 2, 4)

    result: Dict[str, Any] = {
        "enabled": True,
        "minRows": min_rows,
        "maxRows": max_rows,
    }
    if growth_rate is not None:
        result["growthRateThreshold"] = growth_rate

    return result


def _compute_quality(
    adapter: "DatabaseAdapter", table_fqn: str, timestamp_column: str
) -> Optional[Dict[str, Any]]:
    """Compute quality thresholds from daily null rates."""
    try:
        history = adapter.get_daily_null_rates(table_fqn, timestamp_column)
    except (NotImplementedError, Exception) as e:
        logger.debug(f"[SLA Discovery] Daily null rates unavailable for {table_fqn}: {e}")
        return None

    if not history or len(history) < MIN_DATA_POINTS:
        return None

    rates = [h["null_rate"] for h in history if h.get("null_rate") is not None]
    if len(rates) < MIN_DATA_POINTS:
        return None

    avg = mean(rates)
    sd = stdev(rates) if len(rates) > 1 else 0

    max_null_rate = min(0.5, round(avg + 2 * sd, 4))

    return {
        "enabled": True,
        "maxNullRate": max_null_rate,
    }


def _compute_schema(adapter: "DatabaseAdapter", table_fqn: str) -> Optional[Dict[str, Any]]:
    """Compute schema thresholds from schema change history."""
    try:
        history = adapter.get_schema_change_history(table_fqn)
    except (NotImplementedError, Exception) as e:
        logger.debug(f"[SLA Discovery] Schema change history unavailable for {table_fqn}: {e}")
        return None

    if not history:
        # No changes = strict
        return {"enabled": True, "strictness": "strict", "allowEvolution": False}

    has_removals = any(h.get("change_type") == "removed" for h in history)
    has_additions = any(h.get("change_type") == "added" for h in history)

    if has_removals or has_additions:
        return {"enabled": True, "strictness": "warn", "allowEvolution": True}

    return {"enabled": True, "strictness": "strict", "allowEvolution": False}


async def discover_sla_profile(
    node: "LineageNode",
    graph: "LineageGraph",
    adapter: "DatabaseAdapter",
) -> DiscoveryResult:
    """Compute suggested SLA thresholds for a single node."""
    ancestor = _find_warehouse_ancestor(node, graph)
    if ancestor is None:
        return DiscoveryResult(
            node_fqn=node.fqn,
            unsupported=True,
            skipped_reason="no_warehouse_ancestor",
        )

    table_fqn = ancestor.fqn
    freshness = _compute_freshness(adapter, table_fqn)
    volume = _compute_volume(adapter, table_fqn)
    schema = _compute_schema(adapter, table_fqn)

    # Quality requires a timestamp column — use discover_timestamp_column
    quality = None
    try:
        from scanner.monitors.freshness import discover_timestamp_column
        ts_col = discover_timestamp_column(
            query_func=adapter.query,
            database=ancestor.database or "",
            schema=ancestor.schema or "",
            table=ancestor.name,
            dialect=ancestor.dialect or "bigquery",
        )
        if ts_col:
            quality = _compute_quality(adapter, table_fqn, ts_col)
    except Exception as e:
        logger.debug(f"[SLA Discovery] Timestamp column discovery failed for {table_fqn}: {e}")

    return DiscoveryResult(
        node_fqn=node.fqn,
        warehouse_ancestor_fqn=table_fqn,
        freshness=freshness,
        volume=volume,
        quality=quality,
        schema=schema,
    )


async def discover_sla_profiles_bulk(
    nodes: List["LineageNode"],
    graph: "LineageGraph",
    adapter_registry: Dict[str, "DatabaseAdapter"],
    node_limit: int = 100,
) -> List[DiscoveryResult]:
    """Batch discovery for all eligible nodes after a lineage scan.

    Prioritizes by criticality (critical first), then depth (sources first).
    Caps at node_limit to bound warehouse query cost.
    """
    CRITICALITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    eligible = sorted(
        nodes,
        key=lambda n: (CRITICALITY_ORDER.get(n.criticality, 3), n.depth),
    )[:node_limit]

    results: List[DiscoveryResult] = []
    for node in eligible:
        # Find the right adapter for this node's platform
        platform = (node.platform or "").lower()
        adapter = adapter_registry.get(platform)
        if not adapter:
            # Try to find adapter via integration_id or fall back
            adapter = next(iter(adapter_registry.values()), None)
        if not adapter:
            results.append(DiscoveryResult(
                node_fqn=node.fqn, unsupported=True,
                skipped_reason="no_adapter",
            ))
            continue

        result = await discover_sla_profile(node, graph, adapter)
        results.append(result)

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest scanner/tests/test_sla_discovery.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add scanner/lineage/sla_discovery.py scanner/tests/test_sla_discovery.py && git commit -m "feat: add SLA discovery module with statistical threshold computation"
```

---

### Task 9: Hook Discovery into Lineage Orchestrator

**Files:**
- Modify: `scanner/lineage/orchestrator.py:141-159`

- [ ] **Step 1: Add `discovery_results` field to `OrchestrationResult`**

In `scanner/lineage/orchestrator.py`, add to the `OrchestrationResult` dataclass (around line 49-59):

```python
discovery_results: List[Any] = field(default_factory=list)
```

- [ ] **Step 2: Hook discovery into `extract_all()`**

After line 142 (`self.graph.built_at = datetime.utcnow()`) and before line 144 (`duration_ms = ...`), insert:

```python
            # Step 6: SLA Discovery (optional)
            discovery_results = []
            try:
                from scanner.lineage.sla_discovery import discover_sla_profiles_bulk
                discovery_results = await discover_sla_profiles_bulk(
                    nodes=list(self.graph.nodes.values()),
                    graph=self.graph,
                    adapter_registry=self._adapter_registry,
                )
                logger.info(
                    f"[SLA Discovery] Discovered {sum(1 for r in discovery_results if not r.unsupported and not r.skipped_reason)} "
                    f"profiles out of {len(discovery_results)} nodes"
                )
            except Exception as e:
                logger.warning(f"[SLA Discovery] Discovery failed (non-fatal): {e}")
```

Update the `return OrchestrationResult(...)` call to include:

```python
discovery_results=discovery_results,
```

- [ ] **Step 3: Verify `_adapter_registry` exists**

Check that the orchestrator has an `_adapter_registry` attribute. If not, it needs to be built from the integration configs during `__init__`. Search for how adapters are currently accessed in the orchestrator — they may be created per-extraction. If adapters are created inline per extraction, pass the ones that were created during the scan.

If `_adapter_registry` doesn't exist, build it from the extractors:

```python
# In extract_all(), after _extract_from_all_tools():
self._adapter_registry = {}
for result in self.extraction_results:
    if hasattr(result, 'adapter') and result.adapter:
        platform = (result.platform or "").lower()
        self._adapter_registry[platform] = result.adapter
```

- [ ] **Step 4: Commit**

```bash
git add scanner/lineage/orchestrator.py && git commit -m "feat: hook SLA discovery into lineage orchestrator"
```

---

### Task 10: Batch Persistence Route — Save Discovery Results

**Files:**
- Create: `app/api/lineage/discovery/route.ts`

- [ ] **Step 1: Create the persistence endpoint**

Create `app/api/lineage/discovery/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

interface DiscoveryResultPayload {
  nodeFqn: string;
  warehouseAncestorFqn?: string | null;
  freshness?: Record<string, any> | null;
  volume?: Record<string, any> | null;
  quality?: Record<string, any> | null;
  schema?: Record<string, any> | null;
  unsupported?: boolean;
  skippedReason?: string | null;
}

// POST /api/lineage/discovery — Persist discovery results from a lineage scan
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const body = await request.json();
    const { results } = body as { results: DiscoveryResultPayload[] };

    if (!results || results.length === 0) {
      return NextResponse.json({ persisted: 0 });
    }

    let persisted = 0;

    for (const result of results) {
      // Skip unsupported or skipped nodes
      if (result.unsupported || result.skippedReason) continue;

      // Must have at least one config section
      const hasConfig = result.freshness || result.volume || result.quality || result.schema;
      if (!hasConfig) continue;

      const profileName = `Auto-discovered: ${result.nodeFqn}`;

      // Upsert PolicyProfile
      const profile = await prisma.policyProfile.upsert({
        where: {
          organizationId_name: { organizationId, name: profileName },
        },
        create: {
          organizationId,
          name: profileName,
          description: `Auto-discovered from warehouse history for ${result.nodeFqn}`,
          isBuiltIn: true,
          freshnessConfig: result.freshness || undefined,
          volumeConfig: result.volume || undefined,
          qualityConfig: result.quality || undefined,
          schemaConfig: result.schema || undefined,
        },
        update: {
          freshnessConfig: result.freshness || undefined,
          volumeConfig: result.volume || undefined,
          qualityConfig: result.quality || undefined,
          schemaConfig: result.schema || undefined,
          updatedAt: new Date(),
        },
      });

      // Upsert PolicyAssignment
      await prisma.policyAssignment.upsert({
        where: {
          organizationId_assignmentType_nodeFqn: {
            organizationId,
            assignmentType: 'auto_discovered',
            nodeFqn: result.nodeFqn,
          },
        },
        create: {
          organizationId,
          profileId: profile.id,
          assignmentType: 'auto_discovered',
          nodeFqn: result.nodeFqn,
        },
        update: {
          profileId: profile.id,
        },
      });

      persisted++;
    }

    return NextResponse.json({ persisted });
  } catch (error: any) {
    console.error('[Discovery] Error persisting results:', error);
    return NextResponse.json({ error: error.message || 'Failed' }, { status: 500 });
  }
}
```

- [ ] **Step 2: Verify Prisma unique constraints support `auto_discovered`**

Check that the `PolicyAssignment` model's `@@unique` on `(organizationId, assignmentType, nodeFqn)` will work with the new assignment type. The existing Prisma schema should already support any string value for `assignmentType`.

- [ ] **Step 3: Run type check**

```bash
npx tsc --noEmit 2>&1 | grep -v vitest | grep "error" | head -5
```

Expected: No new errors.

- [ ] **Step 4: Commit**

```bash
git add app/api/lineage/discovery/route.ts && git commit -m "feat: add batch persistence endpoint for SLA discovery results"
```

---

### Task 11: On-Demand Discovery Route

**Files:**
- Create: `app/api/nodes/[nodeId]/sla/discover/route.ts`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p app/api/nodes/\[nodeId\]/sla/discover
```

- [ ] **Step 2: Create the on-demand discovery endpoint**

Create `app/api/nodes/[nodeId]/sla/discover/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// POST /api/nodes/[nodeId]/sla/discover — On-demand SLA discovery for a single node
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ nodeId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const { nodeId } = await params;

    // Look up the lineage node
    const node = await prisma.lineageNode.findFirst({
      where: { id: nodeId, organizationId },
      include: { integration: true },
    });

    if (!node) {
      return NextResponse.json({ error: 'Node not found' }, { status: 404 });
    }

    // Check if node already has a user-defined profile
    const existingAssignment = await prisma.policyAssignment.findFirst({
      where: {
        organizationId,
        nodeFqn: node.name,
        assignmentType: { in: ['direct', 'imported_dbt'] },
      },
    });

    if (existingAssignment) {
      return NextResponse.json({ reason: 'user_defined' }, { status: 422 });
    }

    // Proxy to FastAPI scanner for discovery computation
    const scannerUrl = process.env.SCANNER_API_URL || 'http://localhost:8000';
    try {
      const res = await fetch(`${scannerUrl}/api/v1/discovery/node`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nodeFqn: node.name,
          nodeId: node.id,
          platform: node.platform,
          database: node.database,
          schema: node.schema,
          tableName: node.tableName,
          integrationId: node.integrationId,
        }),
        signal: AbortSignal.timeout(30000),
      });

      if (res.ok) {
        const data = await res.json();
        return NextResponse.json({ status: 'ok', result: data });
      }

      const errorData = await res.json().catch(() => ({}));
      if (errorData.reason === 'no_warehouse_ancestor') {
        return NextResponse.json({ reason: 'no_warehouse_ancestor' }, { status: 422 });
      }

      return NextResponse.json({ error: 'Discovery failed' }, { status: 500 });
    } catch {
      return NextResponse.json({ error: 'Scanner unavailable' }, { status: 503 });
    }
  } catch (error: any) {
    console.error('[Discovery] On-demand error:', error);
    return NextResponse.json({ error: error.message || 'Failed' }, { status: 500 });
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add "app/api/nodes/[nodeId]/sla/discover/route.ts" && git commit -m "feat: add on-demand SLA discovery endpoint"
```

---

### Task 12: Update `SlaProfileModal` Source Labels

**Files:**
- Modify: `components/lineage/SlaProfileModal.tsx`

- [ ] **Step 1: Add `auto_discovered` to `SOURCE_LABELS`**

In `components/lineage/SlaProfileModal.tsx`, add to the `SOURCE_LABELS` object:

```typescript
auto_discovered: { label: 'Auto-discovered', color: 'text-cyan-400', bg: 'bg-cyan-500/15' },
```

- [ ] **Step 2: Commit**

```bash
git add components/lineage/SlaProfileModal.tsx && git commit -m "feat: add auto_discovered source label to SlaProfileModal"
```

---

### Task 13: Update `DataAssetDetailPanel` — Discovery UI

**Files:**
- Modify: `components/lineage/DataAssetDetailPanel.tsx:1316-1361`

- [ ] **Step 1: Add discovery state and handler**

At the top of the `DataAssetDetailPanel` component function, add state for discovery:

```typescript
const [discoveryState, setDiscoveryState] = useState<'idle' | 'loading' | 'confirm' | 'unsupported'>('idle');
const [discoveryResult, setDiscoveryResult] = useState<{
  freshness?: { enabled: boolean; maxHours: number; warningHours: number };
  volume?: { enabled: boolean; minRows: number; maxRows: number };
  quality?: { enabled: boolean; maxNullRate: number };
  schema?: { enabled: boolean; strictness: string; allowEvolution: boolean };
} | null>(null);

const handleDiscover = async () => {
  setDiscoveryState('loading');
  try {
    const res = await fetch(`/api/nodes/${node.id}/sla/discover`, { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      setDiscoveryResult(data.result);
      setDiscoveryState('confirm');
    } else if (res.status === 422) {
      const data = await res.json();
      if (data.reason === 'no_warehouse_ancestor') {
        setDiscoveryState('unsupported');
      } else {
        setDiscoveryState('idle');
      }
    } else {
      setDiscoveryState('idle');
      toast.error('Discovery failed');
    }
  } catch {
    setDiscoveryState('idle');
    toast.error('Discovery failed');
  }
};

const handleAcceptDiscovery = async () => {
  if (!discoveryResult) return;
  try {
    // Create a profile and assignment via the assign endpoint
    const res = await fetch('/api/schedule/policies/assign', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        profileId: `auto-discovered-${node.id}`,
        assignmentType: 'auto_discovered',
        nodeFqns: [node.fullName || node.name],
      }),
    });
    if (res.ok) {
      toast.success('SLA profile applied');
      setDiscoveryState('idle');
      setDiscoveryResult(null);
    }
  } catch {
    toast.error('Failed to apply profile');
  }
};
```

- [ ] **Step 2: Replace the Data SLA section rendering**

Replace the existing Data SLA section (lines 1316-1361) with:

```tsx
{/* ─── Data SLA ────────────────────────────── */}
<div className="border-t border-[var(--subtle-border)] pt-3">
  <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Data SLA</label>

  {/* Confirmation UI after discovery */}
  {discoveryState === 'confirm' && discoveryResult && (
    <div className="mt-2 p-3 rounded-lg border border-cyan-500/30 bg-cyan-500/10">
      <p className="text-[12px] font-medium text-cyan-300 mb-2">Suggested SLA Profile</p>
      <p className="text-[10px] text-[var(--muted)] mb-3">Based on 30 days of warehouse history</p>
      <div className="space-y-1.5 text-[12px]">
        {discoveryResult.freshness && (
          <div className="flex justify-between"><span className="text-[var(--muted)]">Freshness</span><span className="text-[var(--text)]">max {discoveryResult.freshness.maxHours}h, warn {discoveryResult.freshness.warningHours}h</span></div>
        )}
        {discoveryResult.volume && (
          <div className="flex justify-between"><span className="text-[var(--muted)]">Volume</span><span className="text-[var(--text)]">{discoveryResult.volume.minRows.toLocaleString()} – {discoveryResult.volume.maxRows.toLocaleString()} rows</span></div>
        )}
        {discoveryResult.quality && (
          <div className="flex justify-between"><span className="text-[var(--muted)]">Quality</span><span className="text-[var(--text)]">null rate ≤{Math.round(discoveryResult.quality.maxNullRate * 100)}%</span></div>
        )}
        {discoveryResult.schema && (
          <div className="flex justify-between"><span className="text-[var(--muted)]">Schema</span><span className="text-[var(--text)]">{discoveryResult.schema.strictness}, {discoveryResult.schema.allowEvolution ? 'evolution ok' : 'no evolution'}</span></div>
        )}
      </div>
      <div className="flex gap-2 mt-3">
        <button onClick={handleAcceptDiscovery} className="px-3 py-1 text-[11px] font-medium rounded bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30">Accept</button>
        <button onClick={() => { onEditSLA?.(node.id); setDiscoveryState('idle'); }} className="px-3 py-1 text-[11px] font-medium rounded bg-[var(--overlay-bg)] text-[var(--muted)] hover:text-[var(--text)]">Edit & Accept</button>
        <button onClick={() => { setDiscoveryState('idle'); setDiscoveryResult(null); }} className="px-3 py-1 text-[11px] font-medium rounded text-[var(--muted)] hover:text-[var(--text)]">Dismiss</button>
      </div>
    </div>
  )}

  {/* Loading state */}
  {discoveryState === 'loading' && (
    <div className="mt-2 p-2.5 rounded-lg border border-dashed border-[var(--subtle-border)] bg-[var(--overlay-faint)] flex items-center gap-2">
      <div className="w-3.5 h-3.5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
      <span className="text-[12px] text-[var(--muted)]">Analyzing warehouse history...</span>
    </div>
  )}

  {/* Discovery unsupported */}
  {discoveryState === 'unsupported' && (
    <div className="mt-2 p-2.5 rounded-lg border border-dashed border-[var(--subtle-border)] bg-[var(--overlay-faint)]">
      <p className="text-[12px] text-[var(--muted)]">No SLA profile assigned</p>
      <p className="text-[11px] text-[var(--text-faint)] mt-1">Discovery not available — no upstream warehouse table found.</p>
      {onEditSLA && (
        <button onClick={() => onEditSLA(node.id)} className="mt-1.5 text-[11px] text-slate-400 hover:text-slate-300 hover:underline flex items-center gap-1">
          <Plus className="w-3 h-3" /> Assign manually
        </button>
      )}
    </div>
  )}

  {/* Assigned state (existing or auto-discovered) */}
  {discoveryState === 'idle' && slaInfo && slaInfo.status !== 'none' && (
    <div className="mt-2 p-2.5 rounded-lg border border-slate-500/30 bg-slate-500/10">
      {slaInfo.source === 'auto_discovered' && (
        <div className="mb-2 p-2 rounded bg-cyan-500/10 border border-cyan-500/20">
          <p className="text-[11px] text-cyan-400">Auto-discovered from data. Edit to make user-defined.</p>
        </div>
      )}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-slate-400" />
          <span className="text-[13px] font-medium text-slate-300">
            {slaInfo.profileName || 'Data SLA Assigned'}
          </span>
        </div>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-500/20 text-slate-300 capitalize">
          {slaInfo.status}
        </span>
      </div>
      {onEditSLA && (
        <button onClick={() => onEditSLA(node.id)} className="mt-2 text-[11px] text-slate-400 hover:text-slate-300 hover:underline flex items-center gap-1">
          Edit Data SLA
        </button>
      )}
    </div>
  )}

  {/* Empty state — no profile */}
  {discoveryState === 'idle' && (!slaInfo || slaInfo.status === 'none') && (
    <div className="mt-2 p-2.5 rounded-lg border border-dashed border-[var(--subtle-border)] bg-[var(--overlay-faint)]">
      <p className="text-[12px] text-[var(--muted)]">No SLA profile assigned</p>
      <div className="flex gap-2 mt-1.5">
        <button onClick={handleDiscover} className="text-[11px] text-cyan-400 hover:text-cyan-300 hover:underline flex items-center gap-1">
          Discover from data
        </button>
        {onEditSLA && (
          <button onClick={() => onEditSLA(node.id)} className="text-[11px] text-slate-400 hover:text-slate-300 hover:underline flex items-center gap-1">
            <Plus className="w-3 h-3" /> Assign manually
          </button>
        )}
      </div>
    </div>
  )}
</div>
```

- [ ] **Step 3: Verify imports**

Ensure `useState` and `toast` (from sonner) are imported. `Plus` and `ShieldCheck` should already be imported from lucide-react.

- [ ] **Step 4: Run type check**

```bash
npx tsc --noEmit 2>&1 | grep -v vitest | grep "error" | head -5
```

Expected: No new errors.

- [ ] **Step 5: Commit**

```bash
git add components/lineage/DataAssetDetailPanel.tsx && git commit -m "feat: add SLA discovery UI to DataAssetDetailPanel"
```

---

### Task 14: Update Assign Route — Handle `auto_discovered` Type

**Files:**
- Modify: `app/api/schedule/policies/assign/route.ts`

- [ ] **Step 1: Add `auto_discovered` branch to the assign handler**

In `app/api/schedule/policies/assign/route.ts`, after the existing `if (assignmentType === 'direct')` block, add:

```typescript
if (assignmentType === 'auto_discovered') {
  if (!nodeFqns || nodeFqns.length === 0) {
    return NextResponse.json({ error: 'nodeFqns required for auto_discovered assignments' }, { status: 400 });
  }

  for (const fqn of nodeFqns) {
    const assignment = await prisma.policyAssignment.upsert({
      where: {
        organizationId_assignmentType_nodeFqn: {
          organizationId,
          assignmentType: 'auto_discovered',
          nodeFqn: fqn,
        },
      },
      create: {
        organizationId,
        profileId: resolvedProfileId,
        assignmentType: 'auto_discovered',
        nodeFqn: fqn,
      },
      update: {
        profileId: resolvedProfileId,
      },
    });
    created.push(assignment);
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/api/schedule/policies/assign/route.ts && git commit -m "feat: handle auto_discovered assignment type in assign route"
```
