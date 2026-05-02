# Capability-Based Lineage Roles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dbt-zone-shaped data-plane layer scale with a capability-role model + endpoint classifier so the data-plane lineage canvas correctly represents any pipeline shape (ELT, ETL, reverse-ETL, ML, streaming) — not just dbt warehouses.

**Architecture:** Three-layer change. (1) Replace `DataPlaneLayer` enum with `DataPlaneRole` (7 capability roles: SOURCE/INGEST/STORE_RAW/TRANSFORM/STORE_SERVE/SERVE/ACTIVATE) in `zones.py`. No `OBSERVE` bucket — Pallisade IS the observability layer; third-party observability tools are not represented as lineage nodes. (2) Add `endpoints.py` with `classify_endpoint` returning SOURCE/INTERNAL/SINK/ORPHAN — drives layout anchoring and the "unused leaf" / "orphan" UI affordances. (3) Update `_semantic_topological_layout` to anchor sources at `x=0` and sinks at the rightmost column. Frontend `PipelineLayer` type union extends with new role values. The dbt zone classification (`DatasetZone`) remains as a sub-classification under `STORE_RAW`/`TRANSFORM`/`STORE_SERVE` but no longer drives canvas columns directly.

**Tech Stack:** Python 3.14 (pytest, dataclasses, enum), Next.js 15 + TypeScript, ReactFlow + dagre.

**Non-goals (explicitly out of scope, separate future plans):**
- Hightouch/Census/Polytomic adapters (this plan only adds platform-set membership detection; actual extraction adapters are follow-on work).
- ML-pipeline adapters (MLflow, Vertex, SageMaker).
- Identity-resolution improvements (cross-platform FQN merging).
- Streaming-source detection beyond `platform_domain` and the new `_REVERSE_ETL_PLATFORMS` set.
- Clarification chat surface for graph anomalies.
- Per-role SLA recommendations.
- Deprecating `FunctionalRole` / `PipelineLane` (the lane Pipeline Overview view is unchanged in this plan; only the data-plane view changes).

---

## File Structure

**New files:**
- `scanner/lineage/engine/endpoints.py` — endpoint classifier (`EndpointKind` enum, `EndpointClassification` dataclass, `classify_endpoint` function).
- `scanner/lineage/engine/tests/test_data_plane_role.py` — unit tests for the new role classifier.
- `scanner/lineage/engine/tests/test_endpoints.py` — unit tests for the endpoint classifier.

**Modified files:**
- `scanner/lineage/engine/zones.py` — replace `DataPlaneLayer` with `DataPlaneRole`; add `_REVERSE_ETL_PLATFORMS`; replace `classify_data_plane_layer` with `classify_data_plane_role`; update `_ZONE_TO_LAYER` → `_ZONE_TO_ROLE`.
- `scanner/lineage/engine/views.py` — update import; rewrite `_semantic_topological_layout` to consume role + endpoint anchors; update `build_data_plane` to compute `has_upstream` and emit role-derived `ViewNode.layer` strings.
- `scanner/lineage/engine/canonical.py` — extend `DOMAIN_TO_LAYER` and `LAYER_ORDER` with the new role-derived layer strings (SOURCE, ACTIVATION) so endpoint anchoring has consistent layer names everywhere.
- `scanner/lineage/engine/tests/test_views.py` — extend layout tests to cover endpoint anchoring.
- `components/pipeline/types.ts` — extend `PipelineLayer` type union, `LAYER_COLORS`, `LAYER_LABELS`.
- `components/lineage/types.ts` — extend `CATEGORY_LAYER_MAP`, `CATEGORY_VISUALS`, default filter sets.

---

## Task 1: Add `DataPlaneRole` enum and reverse-ETL platform set

**Files:**
- Modify: `scanner/lineage/engine/zones.py:240-257`

This task introduces the new enum alongside the old one without breaking callers. Replacement happens in Task 3.

- [ ] **Step 1: Read the current `DataPlaneLayer` enum and `_ZONE_TO_LAYER` block**

Run: `Read /Users/emilfabel/pallisade-copilot/scanner/lineage/engine/zones.py offset=238 limit=22`
Expected: see `class DataPlaneLayer(Enum)` and `_ZONE_TO_LAYER` mapping.

- [ ] **Step 2: Add `DataPlaneRole` enum and `_REVERSE_ETL_PLATFORMS` constant immediately above `DataPlaneLayer`**

Insert at `scanner/lineage/engine/zones.py:240` (just before the existing `class DataPlaneLayer(Enum):` line):

```python
# Reverse-ETL / activation platforms (data flows OUT of the warehouse to SaaS).
# Used by classify_data_plane_role to detect ACTIVATE role.
_REVERSE_ETL_PLATFORMS: frozenset = frozenset({
    "hightouch",
    "census",
    "polytomic",
    "rudderstack_reverse",
    "grouparoo",
})


class DataPlaneRole(Enum):
    """Capability roles for the data-plane view (left → right).

    Replaces DataPlaneLayer. The integer value drives column position;
    the enum name drives the frontend layer string.

    NOTE: There is no OBSERVE role. Pallisade IS the observability layer;
    third-party observability/monitoring tools (Elementary, Great Expectations,
    Monte Carlo, Soda, etc.) are not represented as lineage nodes.
    """
    SOURCE = 0       # External upstream: app DBs, SaaS sources, event streams, file drops
    INGEST = 1       # Connectors and pre-warehouse loaders (Fivetran, Airbyte, n8n)
    STORE_RAW = 2    # Raw/landing tables inside the warehouse
    TRANSFORM = 3    # Staging/intermediate transformations (dbt staging, Spark jobs)
    STORE_SERVE = 4  # Marts, analytics, feature stores ready for consumption
    SERVE = 5        # BI / semantic / dashboards / reports
    ACTIVATE = 6     # Reverse-ETL targets, ML inference endpoints, exports


_ROLE_TO_LAYER_NAME: dict = {
    DataPlaneRole.SOURCE.value: "SOURCE",
    DataPlaneRole.INGEST.value: "INGESTION",
    DataPlaneRole.STORE_RAW.value: "WAREHOUSE",
    DataPlaneRole.TRANSFORM.value: "TRANSFORMATION",
    DataPlaneRole.STORE_SERVE.value: "WAREHOUSE",
    DataPlaneRole.SERVE.value: "REPORTING",
    DataPlaneRole.ACTIVATE.value: "ACTIVATION",
}


def role_to_layer_name(role_value: int) -> str:
    """Map a DataPlaneRole integer to the frontend layer string."""
    return _ROLE_TO_LAYER_NAME.get(role_value, "WAREHOUSE")
```

- [ ] **Step 3: Verify no syntax errors**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/python -c "from lineage.engine.zones import DataPlaneRole, _REVERSE_ETL_PLATFORMS, role_to_layer_name; print(list(DataPlaneRole), len(_REVERSE_ETL_PLATFORMS), role_to_layer_name(0))"`
Expected output: `[<DataPlaneRole.SOURCE: 0>, ..., <DataPlaneRole.ACTIVATE: 6>] 5 SOURCE`

- [ ] **Step 4: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/lineage/engine/zones.py
git commit -m "feat(lineage/engine): add DataPlaneRole capability enum"
```

---

## Task 2: Implement `classify_data_plane_role` (TDD)

**Files:**
- Create: `scanner/lineage/engine/tests/test_data_plane_role.py`
- Modify: `scanner/lineage/engine/zones.py:260-307` (replace `classify_data_plane_layer` body)

- [ ] **Step 1: Write the failing tests**

Create `/Users/emilfabel/pallisade-copilot/scanner/lineage/engine/tests/test_data_plane_role.py`:

```python
"""Tests for classify_data_plane_role — capability-based role classification."""

import pytest

from scanner.lineage.graph import (
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.zones import (
    DataPlaneRole,
    classify_data_plane_role,
)


def _node(
    name: str = "n",
    node_type: NodeType = NodeType.TABLE,
    platform: str = "bigquery",
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    schema: str = "",
    fqn: str = "",
    raw_metadata: dict = None,
) -> LineageNode:
    return LineageNode(
        id=f"node:{platform}:{name}",
        name=name,
        fqn=fqn or f"db.{schema}.{name}",
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        schema=schema,
        raw_metadata=raw_metadata or {},
    )


def test_external_source_no_upstream_not_warehouse_returns_source():
    n = _node(platform="postgres_app", platform_domain=PlatformDomain.APP)
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=False, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.SOURCE.value


def test_dbt_source_in_warehouse_returns_source():
    n = _node(
        platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
        raw_metadata={"dbt_resource_type": "source"},
    )
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=False, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.SOURCE.value


def test_fivetran_connector_returns_ingest():
    n = _node(platform="fivetran", platform_domain=PlatformDomain.INGESTION,
              node_type=NodeType.CONNECTOR)
    role = classify_data_plane_role(
        n, canonical_type="job",
        has_upstream_data_edges=False, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.INGEST.value


def test_raw_warehouse_table_returns_store_raw():
    n = _node(schema="raw", name="users")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.STORE_RAW.value


def test_dbt_staging_model_returns_transform():
    n = _node(schema="analytics_staging", name="stg_users")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.TRANSFORM.value


def test_mart_table_returns_store_serve():
    n = _node(schema="marts", name="dim_users")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.STORE_SERVE.value


def test_looker_dashboard_returns_serve():
    n = _node(platform="looker", platform_domain=PlatformDomain.BI,
              node_type=NodeType.DASHBOARD)
    role = classify_data_plane_role(
        n, canonical_type="semantic",
        has_upstream_data_edges=True, has_downstream_data_edges=False,
    )
    assert role == DataPlaneRole.SERVE.value


def test_hightouch_destination_returns_activate():
    n = _node(platform="hightouch", platform_domain=PlatformDomain.OTHER)
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=False,
    )
    assert role == DataPlaneRole.ACTIVATE.value


def test_explicit_activation_metadata_returns_activate():
    n = _node(platform="custom", raw_metadata={"activation_target": True})
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=False,
    )
    assert role == DataPlaneRole.ACTIVATE.value


def test_unknown_zone_leaf_returns_store_serve():
    n = _node(schema="custom", name="thing_table")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=False,
    )
    assert role == DataPlaneRole.STORE_SERVE.value


def test_unknown_zone_root_returns_store_raw():
    n = _node(schema="custom", name="thing_table")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=False, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.STORE_RAW.value


def test_unknown_zone_middle_returns_transform():
    n = _node(schema="custom", name="thing_table")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.TRANSFORM.value
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/test_data_plane_role.py -v`
Expected: 12 tests fail with `ImportError: cannot import name 'classify_data_plane_role' from 'scanner.lineage.engine.zones'`

- [ ] **Step 3: Replace `classify_data_plane_layer` with `classify_data_plane_role`**

In `scanner/lineage/engine/zones.py`, replace the entire `_ZONE_TO_LAYER` constant and `classify_data_plane_layer` function (currently lines 251-307) with:

```python
_ZONE_TO_ROLE: Dict[DatasetZone, int] = {
    DatasetZone.RAW: DataPlaneRole.STORE_RAW.value,
    DatasetZone.STAGING: DataPlaneRole.TRANSFORM.value,
    DatasetZone.INTERMEDIATE: DataPlaneRole.TRANSFORM.value,
    DatasetZone.MART: DataPlaneRole.STORE_SERVE.value,
    DatasetZone.ANALYTICS: DataPlaneRole.STORE_SERVE.value,
}


def classify_data_plane_role(
    node: LineageNode,
    canonical_type: str,
    has_upstream_data_edges: bool,
    has_downstream_data_edges: bool,
) -> int:
    """Classify a node into a capability role for the data-plane view.

    Returns an integer matching DataPlaneRole.<X>.value.

    Resolution order:
      1. ACTIVATE — reverse-ETL platform OR explicit activation_target metadata
      2. SERVE — semantic canonical type OR BI platform domain
      3. SOURCE — external upstream (no incoming edges, not a warehouse leaf
                  unless tagged as a dbt source)
      4. INGEST — connector platforms / ingestion domain
      5. Dataset role by zone (STORE_RAW / TRANSFORM / STORE_SERVE)
      6. Flow-driven fallback for unknown-zone datasets

    Note: There is no OBSERVE branch. Pallisade is the observability layer;
    third-party observability/monitoring tools should not appear as nodes.
    Any such node that does appear (e.g., from an Elementary dbt-test import)
    falls through to STORE_RAW or its dataset-zone classification.
    """
    rm = node.raw_metadata or {}
    platform = (node.platform or "").lower()

    # 1. ACTIVATE — reverse-ETL or explicit activation
    if platform in _REVERSE_ETL_PLATFORMS:
        return DataPlaneRole.ACTIVATE.value
    if rm.get("activation_target"):
        return DataPlaneRole.ACTIVATE.value

    # 2. SERVE — BI / semantic
    if canonical_type == "semantic":
        return DataPlaneRole.SERVE.value
    if node.platform_domain == PlatformDomain.BI:
        return DataPlaneRole.SERVE.value

    # 3. SOURCE — external upstream
    is_dbt_source = rm.get("dbt_resource_type") == "source"
    if canonical_type == "dataset" and not has_upstream_data_edges:
        if node.platform_domain != PlatformDomain.WAREHOUSE or is_dbt_source:
            return DataPlaneRole.SOURCE.value

    # 4. INGEST — connectors / loaders
    is_ingestion_domain = node.platform_domain == PlatformDomain.INGESTION
    is_ingestion_platform = (
        platform in INGESTION_PLATFORMS
        and node.platform_domain != PlatformDomain.WAREHOUSE
    )
    if is_ingestion_domain or is_ingestion_platform:
        return DataPlaneRole.INGEST.value

    # 5. Dataset by zone
    if canonical_type == "dataset":
        zone = classify_dataset_zone(node)
        zone_role = _ZONE_TO_ROLE.get(zone)
        if zone_role is not None:
            return zone_role

        # 6. Flow-driven fallback for UNKNOWN zone
        dbt_type = rm.get("dbt_resource_type", "")
        if dbt_type == "model":
            return DataPlaneRole.STORE_SERVE.value
        if not has_downstream_data_edges:
            return DataPlaneRole.STORE_SERVE.value
        if not has_upstream_data_edges:
            return DataPlaneRole.STORE_RAW.value
        return DataPlaneRole.TRANSFORM.value

    # Default: anything else lives in STORE_RAW
    return DataPlaneRole.STORE_RAW.value


# Backwards-compatibility alias for any in-flight imports.
# Remove in a follow-up cleanup once all callers updated.
classify_data_plane_layer = classify_data_plane_role
DataPlaneLayer = DataPlaneRole
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/test_data_plane_role.py -v`
Expected: 12 tests pass.

- [ ] **Step 5: Run the full zones-related test suite to confirm no regressions**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/ -v -k "zone or role or views or data_plane"`
Expected: all pre-existing tests still pass (alias preserves the old import path).

- [ ] **Step 6: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/lineage/engine/zones.py scanner/lineage/engine/tests/test_data_plane_role.py
git commit -m "feat(lineage/engine): implement classify_data_plane_role with capability roles"
```

---

## Task 3: Create `endpoints.py` module skeleton (TDD)

**Files:**
- Create: `scanner/lineage/engine/endpoints.py`
- Create: `scanner/lineage/engine/tests/test_endpoints.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/emilfabel/pallisade-copilot/scanner/lineage/engine/tests/test_endpoints.py`:

```python
"""Tests for endpoint classification."""

import pytest

from scanner.lineage.graph import LineageNode, NodeType, PlatformDomain
from scanner.lineage.engine.endpoints import (
    EndpointKind,
    EndpointClassification,
    classify_endpoint,
)


def _node(
    name: str = "n",
    platform: str = "bigquery",
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    raw_metadata: dict = None,
) -> LineageNode:
    return LineageNode(
        id=f"node:{platform}:{name}",
        name=name,
        fqn=f"db.s.{name}",
        node_type=NodeType.TABLE,
        platform=platform,
        platform_domain=platform_domain,
        raw_metadata=raw_metadata or {},
    )


def test_no_edges_returns_orphan():
    n = _node()
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=False, has_downstream=False)
    assert result.kind == EndpointKind.ORPHAN
    assert "no edges" in result.reason.lower()


def test_no_upstream_with_downstream_returns_source():
    n = _node()
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=False, has_downstream=True)
    assert result.kind == EndpointKind.SOURCE


def test_has_upstream_no_downstream_returns_sink():
    n = _node()
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=True, has_downstream=False)
    assert result.kind == EndpointKind.SINK


def test_both_edges_returns_internal():
    n = _node()
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=True, has_downstream=True)
    assert result.kind == EndpointKind.INTERNAL


def test_dbt_source_with_no_upstream_explicit_reason():
    n = _node(raw_metadata={"dbt_resource_type": "source"})
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=False, has_downstream=True)
    assert result.kind == EndpointKind.SOURCE
    assert "dbt source" in result.reason.lower()


def test_bi_node_with_no_downstream_high_confidence_sink():
    n = _node(platform="looker", platform_domain=PlatformDomain.BI)
    result = classify_endpoint(n, canonical_type="semantic",
                               has_upstream=True, has_downstream=False)
    assert result.kind == EndpointKind.SINK
    assert result.confidence >= 0.9


def test_warehouse_leaf_lower_confidence_sink():
    """A leaf table without a known terminal role: maybe unused, not a real sink."""
    n = _node(name="forgotten_table")
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=True, has_downstream=False)
    assert result.kind == EndpointKind.SINK
    assert result.confidence < 0.7  # lower confidence: could be unused, not terminal


def test_classification_serializable():
    n = _node()
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=True, has_downstream=True)
    d = result.to_dict()
    assert d["kind"] == "internal"
    assert "reason" in d
    assert "confidence" in d
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/test_endpoints.py -v`
Expected: 8 tests fail with `ModuleNotFoundError: No module named 'scanner.lineage.engine.endpoints'`

- [ ] **Step 3: Create the `endpoints.py` module**

Create `/Users/emilfabel/pallisade-copilot/scanner/lineage/engine/endpoints.py`:

```python
"""
Endpoint Classification

Classifies nodes as SOURCE / INTERNAL / SINK / ORPHAN based on graph topology
and node metadata. Drives layout anchoring (sources pinned left, sinks pinned
right) and frontend affordances (orphan warnings, sink visuals).

Distinct from DataPlaneRole:
  - DataPlaneRole answers "what does this asset represent?" (semantic)
  - EndpointKind answers "is this terminal in the graph?" (structural)

A node can be both — e.g., a Hightouch destination has role=ACTIVATE and
kind=SINK. A leaf warehouse table has role=STORE_SERVE and kind=SINK with
LOWER confidence (it might be unused rather than truly terminal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

from ..graph import LineageNode, PlatformDomain


class EndpointKind(Enum):
    """Structural role of a node in the graph."""
    SOURCE = "source"      # No upstream — anchors leftmost in layout
    INTERNAL = "internal"  # Has both upstream and downstream
    SINK = "sink"          # No downstream — anchors rightmost in layout
    ORPHAN = "orphan"      # No edges at all — extraction/integration gap


_TERMINAL_DOMAINS = frozenset({PlatformDomain.BI})

_ACTIVATION_PLATFORMS = frozenset({
    "hightouch", "census", "polytomic", "rudderstack_reverse", "grouparoo",
})


@dataclass
class EndpointClassification:
    """Result of endpoint classification."""
    kind: EndpointKind
    reason: str            # Human-readable explanation
    confidence: float      # 0.0 - 1.0; lower = clarification candidate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "reason": self.reason,
            "confidence": self.confidence,
        }


def classify_endpoint(
    node: LineageNode,
    canonical_type: str,
    has_upstream: bool,
    has_downstream: bool,
) -> EndpointClassification:
    """Classify a node by its position in the graph topology.

    Confidence reflects how certain we are this is a true endpoint rather
    than an extraction gap or an unused leaf:
      - SOURCE confidence high when the node platform is non-warehouse OR
        explicitly tagged as a dbt source
      - SOURCE confidence lower when it's a warehouse table with no upstream
        (could be an extraction gap)
      - SINK confidence high when the node is a known terminal (BI, activation)
      - SINK confidence lower when it's just a leaf warehouse table
        (could be unused, not truly terminal)
    """
    rm = node.raw_metadata or {}
    platform = (node.platform or "").lower()

    # ORPHAN
    if not has_upstream and not has_downstream:
        return EndpointClassification(
            kind=EndpointKind.ORPHAN,
            reason="no edges in either direction (likely extraction gap)",
            confidence=0.5,
        )

    # SOURCE
    if not has_upstream and has_downstream:
        if rm.get("dbt_resource_type") == "source":
            return EndpointClassification(
                kind=EndpointKind.SOURCE,
                reason="explicit dbt source declaration",
                confidence=0.95,
            )
        if node.platform_domain != PlatformDomain.WAREHOUSE:
            return EndpointClassification(
                kind=EndpointKind.SOURCE,
                reason=f"non-warehouse platform '{platform}' with no upstream",
                confidence=0.85,
            )
        return EndpointClassification(
            kind=EndpointKind.SOURCE,
            reason="warehouse leaf with no upstream (may be extraction gap)",
            confidence=0.55,
        )

    # SINK
    if has_upstream and not has_downstream:
        if canonical_type == "semantic" or node.platform_domain in _TERMINAL_DOMAINS:
            return EndpointClassification(
                kind=EndpointKind.SINK,
                reason="terminal BI / semantic node",
                confidence=0.95,
            )
        if platform in _ACTIVATION_PLATFORMS or rm.get("activation_target"):
            return EndpointClassification(
                kind=EndpointKind.SINK,
                reason="activation/reverse-ETL target",
                confidence=0.95,
            )
        return EndpointClassification(
            kind=EndpointKind.SINK,
            reason="leaf warehouse asset (may be unused, not truly terminal)",
            confidence=0.50,
        )

    # INTERNAL
    return EndpointClassification(
        kind=EndpointKind.INTERNAL,
        reason="node has both upstream and downstream edges",
        confidence=1.0,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/test_endpoints.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/lineage/engine/endpoints.py scanner/lineage/engine/tests/test_endpoints.py
git commit -m "feat(lineage/engine): add endpoint classifier module"
```

---

## Task 4: Update `_semantic_topological_layout` to use roles + endpoint anchors (TDD)

**Files:**
- Modify: `scanner/lineage/engine/views.py:46-59` (imports)
- Modify: `scanner/lineage/engine/views.py:3283-3361` (function body)
- Modify: `scanner/lineage/engine/tests/test_views.py` (extend tests)

- [ ] **Step 1: Add a failing test for endpoint anchoring**

Append to `/Users/emilfabel/pallisade-copilot/scanner/lineage/engine/tests/test_views.py` (at end of file):

```python


# ── Capability-role + endpoint-anchored layout tests ──────────────────────

def test_semantic_layout_anchors_source_at_layer_zero():
    """A source-endpoint node must end up at the leftmost column."""
    from scanner.lineage.engine.views import _semantic_topological_layout, ViewNode, ViewEdge
    from scanner.lineage.graph import LineageGraph

    # Build a graph: source_table → mart_table → looker_dashboard
    nodes = [
        ViewNode(
            id="src", name="src", canonical_type="dataset",
            original_type="table", platform="postgres_app",
            platform_domain="app", layer="SOURCE", cluster_id="db.app",
            x=0, y=0, inferred=False, needs_mapping=False,
            metadata={"fqn": "app.public.users"},
        ),
        ViewNode(
            id="mart", name="dim_users", canonical_type="dataset",
            original_type="table", platform="bigquery",
            platform_domain="warehouse", layer="WAREHOUSE", cluster_id="bq.marts",
            x=0, y=0, inferred=False, needs_mapping=False,
            metadata={"fqn": "bq.marts.dim_users"},
        ),
        ViewNode(
            id="dash", name="exec_dash", canonical_type="semantic",
            original_type="dashboard", platform="looker",
            platform_domain="bi", layer="REPORTING", cluster_id="looker",
            x=0, y=0, inferred=False, needs_mapping=False,
            metadata={"fqn": "looker.exec_dash"},
        ),
    ]
    edges = [
        ViewEdge(id="e1", source_id="src", target_id="mart",
                 canonical_type="derives", original_type="depends_on",
                 confidence=1.0, inferred=False, evidence_count=1),
        ViewEdge(id="e2", source_id="mart", target_id="dash",
                 canonical_type="serves", original_type="references",
                 confidence=1.0, inferred=False, evidence_count=1),
    ]

    # Empty graph (test fixture doesn't need full LineageGraph)
    graph = LineageGraph()
    positions = _semantic_topological_layout(nodes, edges, graph)

    # Source must be at x=0
    assert positions["src"][0] == 0
    # Dashboard must be rightmost
    max_x = max(p[0] for p in positions.values())
    assert positions["dash"][0] == max_x
    # Mart must be between
    assert 0 < positions["mart"][0] < max_x


def test_semantic_layout_uses_role_when_role_is_diverse():
    """When nodes have multiple roles, role drives column position."""
    from scanner.lineage.engine.views import _semantic_topological_layout, ViewNode, ViewEdge
    from scanner.lineage.graph import LineageGraph

    nodes = [
        ViewNode(id="a", name="a", canonical_type="dataset", original_type="table",
                 platform="bigquery", platform_domain="warehouse",
                 layer="WAREHOUSE", cluster_id="bq.raw", x=0, y=0,
                 inferred=False, needs_mapping=False,
                 metadata={"fqn": "bq.raw.events"}),
        ViewNode(id="b", name="b", canonical_type="dataset", original_type="table",
                 platform="bigquery", platform_domain="warehouse",
                 layer="WAREHOUSE", cluster_id="bq.marts", x=0, y=0,
                 inferred=False, needs_mapping=False,
                 metadata={"fqn": "bq.marts.dim_events"}),
    ]
    edges = [
        ViewEdge(id="e", source_id="a", target_id="b",
                 canonical_type="derives", original_type="depends_on",
                 confidence=1.0, inferred=False, evidence_count=1),
    ]
    graph = LineageGraph()
    positions = _semantic_topological_layout(nodes, edges, graph)

    # a (raw) should be left of b (mart)
    assert positions["a"][0] < positions["b"][0]
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/test_views.py::test_semantic_layout_anchors_source_at_layer_zero lineage/engine/tests/test_views.py::test_semantic_layout_uses_role_when_role_is_diverse -v`
Expected: tests fail because layout is not yet endpoint-anchored — likely the dashboard or source ends up not at the extremes.

- [ ] **Step 3: Update `_semantic_topological_layout` to use roles + endpoint anchoring**

In `scanner/lineage/engine/views.py`, first update the imports at line 42-59 to add the new symbols:

```python
from .zones import (
    ActorCapability,
    DatasetZone,
    DataPlaneRole,
    FunctionalRole,
    PipelineLane,
    LANE_ORDER,
    INFRA_PLATFORMS,
    INGESTION_PLATFORMS,
    ORCHESTRATION_PLATFORMS,
    REPORTING_PLATFORMS,
    TRANSFORM_PLATFORMS,
    WAREHOUSE_PLATFORMS,
    assign_lane,
    classify_actor_capability,
    classify_data_plane_role,
    classify_dataset_zone,
    resolve_functional_role,
    role_to_layer_name,
)
from .endpoints import EndpointKind, EndpointClassification, classify_endpoint
```

Then replace the body of `_semantic_topological_layout` (currently `views.py:3283-3361`) with:

```python
def _semantic_topological_layout(
    nodes: List[ViewNode],
    edges: List[ViewEdge],
    graph: LineageGraph,
) -> Dict[str, Tuple[float, float]]:
    """
    Compute layered layout using capability-role assignment + endpoint anchoring
    + topological refinement.

    Algorithm:
      1. Assign each node a capability role (DataPlaneRole, 0-7) using metadata
      2. Classify each node's endpoint kind (source / internal / sink / orphan)
      3. Anchor source-endpoints at column 0; anchor sink-endpoints at the
         rightmost column among non-anchored nodes
      4. If only one role represented (no diversity), fall back to pure topo sort
      5. Enforce edge consistency: source layer < target layer
      6. Within each layer, sort by (cluster_id, topo_order, name)
      7. Convert to pixel positions
    """
    if not nodes:
        return {}

    node_ids = {n.id for n in nodes}
    node_map = {n.id: n for n in nodes}

    # Build degree maps for role classification + endpoint detection
    in_degree: Dict[str, int] = {n.id: 0 for n in nodes}
    out_degree: Dict[str, int] = {n.id: 0 for n in nodes}
    for e in edges:
        if e.source_id in node_ids and e.target_id in node_ids:
            out_degree[e.source_id] = out_degree.get(e.source_id, 0) + 1
            in_degree[e.target_id] = in_degree.get(e.target_id, 0) + 1

    # Step 1: Assign capability role to each node
    role_layer: Dict[str, int] = {}
    for vn in nodes:
        graph_node = graph.nodes.get(vn.id)
        has_up = in_degree.get(vn.id, 0) > 0
        has_down = out_degree.get(vn.id, 0) > 0
        if graph_node:
            ct = graph_node.canonical_type or map_node_type(graph_node).value
            role_layer[vn.id] = classify_data_plane_role(
                graph_node, ct,
                has_upstream_data_edges=has_up,
                has_downstream_data_edges=has_down,
            )
        else:
            # ViewNode without backing graph node — derive from canonical_type
            if vn.canonical_type == "semantic":
                role_layer[vn.id] = DataPlaneRole.SERVE.value
            elif not has_up and has_down:
                role_layer[vn.id] = DataPlaneRole.SOURCE.value
            elif has_up and not has_down:
                role_layer[vn.id] = DataPlaneRole.STORE_SERVE.value
            else:
                role_layer[vn.id] = DataPlaneRole.STORE_RAW.value

    # Step 2: Classify endpoint kind
    endpoint_kind: Dict[str, EndpointKind] = {}
    for vn in nodes:
        graph_node = graph.nodes.get(vn.id)
        has_up = in_degree.get(vn.id, 0) > 0
        has_down = out_degree.get(vn.id, 0) > 0
        if graph_node:
            ct = graph_node.canonical_type or map_node_type(graph_node).value
            cls = classify_endpoint(graph_node, ct, has_up, has_down)
        else:
            # Pure topology fallback for nodes without graph entry
            if not has_up and not has_down:
                cls_kind = EndpointKind.ORPHAN
            elif not has_up and has_down:
                cls_kind = EndpointKind.SOURCE
            elif has_up and not has_down:
                cls_kind = EndpointKind.SINK
            else:
                cls_kind = EndpointKind.INTERNAL
            cls = EndpointClassification(kind=cls_kind, reason="topology only", confidence=0.7)
        endpoint_kind[vn.id] = cls.kind

    # Step 3: Anchor sources at layer 0, sinks at max layer (computed below)
    # Diversity check first — if no role diversity, fall back to pure topo
    if len(set(role_layer.values())) <= 1:
        return _topological_layout(nodes, edges)

    # Step 4: Edge-consistency pass — push targets forward when source >= target
    changed = True
    iterations = 0
    while changed and iterations < 20:
        changed = False
        iterations += 1
        for e in edges:
            if e.source_id in role_layer and e.target_id in role_layer:
                if role_layer[e.source_id] >= role_layer[e.target_id]:
                    role_layer[e.target_id] = role_layer[e.source_id] + 1
                    changed = True

    # Step 5: Apply endpoint anchors AFTER edge consistency
    # Sources stay at their assigned layer (already 0 if classified SOURCE).
    # Sinks get pushed to the rightmost layer among non-orphan nodes.
    non_orphan_layers = [
        role_layer[nid] for nid, k in endpoint_kind.items()
        if k != EndpointKind.ORPHAN
    ]
    max_layer = max(non_orphan_layers) if non_orphan_layers else 0

    for nid, kind in endpoint_kind.items():
        if kind == EndpointKind.SINK:
            # Pin sinks to the rightmost layer among in-flow nodes
            role_layer[nid] = max_layer
        elif kind == EndpointKind.SOURCE:
            # Pin pure sources to layer 0 (only if not already there)
            role_layer[nid] = 0

    # Step 6: Compute topo order for intra-layer sorting
    topo_order = _compute_topo_order(nodes, edges)

    # Step 7: Group by layer, sort within
    by_layer: Dict[int, List[str]] = defaultdict(list)
    for nid, layer in role_layer.items():
        by_layer[layer].append(nid)

    for layer in by_layer:
        by_layer[layer].sort(key=lambda nid: (
            node_map[nid].cluster_id or "",
            topo_order.get(nid, 999),
            node_map[nid].name,
        ))

    # Step 8: Convert to pixel positions
    positions: Dict[str, Tuple[float, float]] = {}
    for layer_idx, layer in enumerate(sorted(by_layer.keys())):
        for node_idx, nid in enumerate(by_layer[layer]):
            positions[nid] = (layer_idx * LAYER_SPACING_X, node_idx * NODE_SPACING_Y)

    return positions
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/test_views.py::test_semantic_layout_anchors_source_at_layer_zero lineage/engine/tests/test_views.py::test_semantic_layout_uses_role_when_role_is_diverse -v`
Expected: 2 tests pass.

- [ ] **Step 5: Run all view tests to verify no regressions**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/test_views.py -v`
Expected: all tests pass (existing layout-determinism tests still produce the same shape; only changes are in capability roles and anchoring, which preserve the relative ordering).

- [ ] **Step 6: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/lineage/engine/views.py scanner/lineage/engine/tests/test_views.py
git commit -m "feat(lineage/engine): use capability roles + endpoint anchoring in data-plane layout"
```

---

## Task 5: Update `build_data_plane` to emit role-derived `ViewNode.layer` strings

**Files:**
- Modify: `scanner/lineage/engine/views.py` around line 2954 (the `layer = get_layer(node)` line in `build_data_plane`).

The data-plane view currently sets `ViewNode.layer` from `get_layer(node)` which uses `DOMAIN_TO_LAYER` (canonical.py). That returns coarse domain-based strings (`WAREHOUSE`, `INGESTION`, etc.) which don't expose the new `SOURCE`/`ACTIVATION` roles to the frontend. After this task, `ViewNode.layer` reflects the actual capability role for each node.

- [ ] **Step 1: Read the current `build_data_plane` body around line 2940-2970**

Run: `Read /Users/emilfabel/pallisade-copilot/scanner/lineage/engine/views.py offset=2940 limit=60`
Expected: confirm `for node in sorted(...):` loop and the `layer = get_layer(node)` line.

- [ ] **Step 2: Add a failing test for role-derived layer strings**

Append to `/Users/emilfabel/pallisade-copilot/scanner/lineage/engine/tests/test_views.py`:

```python


def test_data_plane_emits_role_based_layer_strings():
    """build_data_plane should set ViewNode.layer to capability-role names."""
    from scanner.lineage.engine.views import ViewBuilder
    from scanner.lineage.engine.canonical import canonicalize_graph_in_place
    from scanner.lineage.graph import (
        LineageGraph, LineageNode, LineageEdge, NodeType, EdgeType,
        PlatformDomain, Evidence, LineageLevel, LinePlane,
    )

    g = LineageGraph()

    # External app source (no upstream)
    src = LineageNode(
        id="src", name="users", fqn="app.public.users",
        node_type=NodeType.TABLE, platform="postgres_app",
        platform_domain=PlatformDomain.APP, schema="public",
    )
    # Hightouch destination (activation)
    activate = LineageNode(
        id="act", name="sf_contacts", fqn="hightouch.sf_contacts",
        node_type=NodeType.TABLE, platform="hightouch",
        platform_domain=PlatformDomain.OTHER,
    )
    # Mart in between
    mart = LineageNode(
        id="mart", name="dim_users", fqn="bq.marts.dim_users",
        node_type=NodeType.TABLE, platform="bigquery",
        platform_domain=PlatformDomain.WAREHOUSE, schema="marts",
    )

    for n in (src, mart, activate):
        g.add_node(n)

    g.add_edge(LineageEdge(
        id="e1", source_id="src", target_id="mart",
        edge_type=EdgeType.DERIVED_FROM, level=LineageLevel.TABLE,
        plane=LinePlane.DATA, confidence=1.0,
        evidence=[Evidence(adapter_id="t", source_ref="t")],
    ))
    g.add_edge(LineageEdge(
        id="e2", source_id="mart", target_id="act",
        edge_type=EdgeType.DERIVED_FROM, level=LineageLevel.TABLE,
        plane=LinePlane.DATA, confidence=1.0,
        evidence=[Evidence(adapter_id="t", source_ref="t")],
    ))

    canonicalize_graph_in_place(g.nodes, g.edges)

    view = ViewBuilder(g).build_data_plane()
    layers = {n.id: n.layer for n in view.nodes}

    assert layers["src"] == "SOURCE"
    assert layers["act"] == "ACTIVATION"
    assert layers["mart"] == "WAREHOUSE"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/test_views.py::test_data_plane_emits_role_based_layer_strings -v`
Expected: fails — current `layer = get_layer(node)` produces `OTHER`/`APP`/`WAREHOUSE` not `SOURCE`/`ACTIVATION`.

- [ ] **Step 4: Update `build_data_plane` to compute role and use it for layer string**

In `scanner/lineage/engine/views.py`, locate the `# Step 3: Build node list` comment in `build_data_plane` (currently around line 2941). The lines that follow are:

```python
        # Step 3: Build node list
        view_nodes: List[ViewNode] = []
        node_id_set: Set[str] = set()
        unmapped: List[Dict[str, Any]] = []

        for node in sorted(self.graph.nodes.values(), key=lambda n: n.fqn):
```

Insert the degree pre-computation block immediately after the three list/set initializations and immediately before the `for node in sorted(...)` loop:

```python
        # Pre-compute upstream/downstream degree among the candidate dataset/
        # semantic node set so we can classify capability role per node.
        candidate_ids: Set[str] = {
            n.id for n in self.graph.nodes.values()
            if (n.canonical_type or map_node_type(n).value) in selected_types
        }
        in_deg: Dict[str, int] = {nid: 0 for nid in candidate_ids}
        out_deg: Dict[str, int] = {nid: 0 for nid in candidate_ids}
        for e in self.graph.edges.values():
            sid = airflow_remap.get(e.source_id, e.source_id)
            tid = airflow_remap.get(e.target_id, e.target_id)
            sid = inferred_remap.get(sid, sid)
            tid = inferred_remap.get(tid, tid)
            if sid in candidate_ids:
                out_deg[sid] = out_deg.get(sid, 0) + 1
            if tid in candidate_ids:
                in_deg[tid] = in_deg.get(tid, 0) + 1
```

Then in the existing node-build loop, replace `layer = get_layer(node)` with:

```python
            # Capability role drives layer string (replaces domain-based mapping)
            role_value = classify_data_plane_role(
                node, ct,
                has_upstream_data_edges=in_deg.get(node.id, 0) > 0,
                has_downstream_data_edges=out_deg.get(node.id, 0) > 0,
            )
            layer = role_to_layer_name(role_value)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/test_views.py::test_data_plane_emits_role_based_layer_strings -v`
Expected: passes.

- [ ] **Step 6: Run all view tests to confirm no regressions**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/test_views.py -v`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/lineage/engine/views.py scanner/lineage/engine/tests/test_views.py
git commit -m "feat(lineage/engine): emit capability-role layer strings from build_data_plane"
```

---

## Task 6: Extend `DOMAIN_TO_LAYER` and `LAYER_ORDER` in `canonical.py`

**Files:**
- Modify: `scanner/lineage/engine/canonical.py:140-161`

Currently `DOMAIN_TO_LAYER` and `LAYER_ORDER` only know about INGESTION/WAREHOUSE/TRANSFORMATION/REPORTING/etc. The new role-derived layers (SOURCE, ACTIVATION) need to appear in `LAYER_ORDER` so any downstream code that uses `get_layer_order(layer)` returns sensible values for them.

`get_layer` itself (canonical.py:254) is unchanged — it's still domain-driven and used only by Pipeline Overview / lane view, not the data plane (which now uses `role_to_layer_name`).

- [ ] **Step 1: Read the current mappings**

Run: `Read /Users/emilfabel/pallisade-copilot/scanner/lineage/engine/canonical.py offset=140 limit=22`
Expected: see `DOMAIN_TO_LAYER` and `LAYER_ORDER` dictionaries.

- [ ] **Step 2: Extend `LAYER_ORDER` with the new layers**

In `scanner/lineage/engine/canonical.py`, replace the `LAYER_ORDER` dict (currently lines 152-161) with:

```python
# Layer ordering for deterministic layout (left → right)
# Includes both domain-derived layers (used by lane Pipeline Overview)
# and capability-role-derived layers (used by data-plane view).
LAYER_ORDER: Dict[str, int] = {
    "SOURCE": 0,
    "INGESTION": 1,
    "ORCHESTRATION": 2,
    "WAREHOUSE": 3,
    "TRANSFORMATION": 4,
    "REPORTING": 5,
    "ACTIVATION": 6,
    "STORAGE": 7,
    "VERSION_CONTROL": 8,
    "INFRASTRUCTURE": 9,
}
```

Note that the relative order of pre-existing layers (INGESTION < WAREHOUSE < TRANSFORMATION < REPORTING) is preserved; SOURCE is inserted at the front and ACTIVATION after REPORTING.

- [ ] **Step 3: Run all engine tests to verify no regressions in lane-overview or data-plane positioning**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/ -v`
Expected: all tests pass. Pay attention to `test_views.py` and `test_lane_overview.py`.

- [ ] **Step 4: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/lineage/engine/canonical.py
git commit -m "feat(lineage/engine): extend LAYER_ORDER with role-derived layers"
```

---

## Task 7: Extend frontend `PipelineLayer` type union and color map

**Files:**
- Modify: `components/pipeline/types.ts:8` (`PipelineLayer` type union)
- Modify: `components/pipeline/types.ts:17-44` (`LAYER_COLORS`)
- Modify: `components/pipeline/types.ts:45-63` (`LAYER_LABELS`)

- [ ] **Step 1: Read the current `PipelineLayer` type and color map**

Run: `Read /Users/emilfabel/pallisade-copilot/components/pipeline/types.ts offset=1 limit=70`
Expected: see the `PipelineLayer` type union and `LAYER_COLORS` / `LAYER_LABELS` records.

- [ ] **Step 2: Extend the `PipelineLayer` type union**

In `components/pipeline/types.ts`, replace line 8:

Old:
```typescript
export type PipelineLayer = 'INGESTION' | 'TRANSFORMATION' | 'WAREHOUSE' | 'REPORTING' | 'STORAGE' | 'VERSION_CONTROL' | 'ORCHESTRATION' | 'INFRASTRUCTURE' | 'NOTIFICATIONS' | 'UNCATEGORIZED';
```

New:
```typescript
export type PipelineLayer = 'SOURCE' | 'INGESTION' | 'TRANSFORMATION' | 'WAREHOUSE' | 'REPORTING' | 'ACTIVATION' | 'STORAGE' | 'VERSION_CONTROL' | 'ORCHESTRATION' | 'INFRASTRUCTURE' | 'NOTIFICATIONS' | 'UNCATEGORIZED';
```

- [ ] **Step 3: Add color entries for the new layers in `LAYER_COLORS`**

Find the `LAYER_COLORS` const (starts at line 17). Add two entries — one of the existing entries (e.g., `WAREHOUSE`) shows the format. Insert immediately above the closing `};`:

```typescript
  SOURCE: '#10b981',          // emerald — external upstream
  ACTIVATION: '#f59e0b',      // amber — reverse-ETL / activation targets
```

(If TypeScript complains about Record<PipelineLayer, string> being non-exhaustive, that means the type union update from Step 2 didn't take — go fix that first.)

- [ ] **Step 4: Add label entries in `LAYER_LABELS`**

Find `LAYER_LABELS` (starts around line 45). Add immediately above the closing `};`:

```typescript
  SOURCE: 'Sources',
  ACTIVATION: 'Activation',
```

- [ ] **Step 5: Run TypeScript type-check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit`
Expected: no errors related to PipelineLayer. Other unrelated TS errors that pre-existed are out of scope.

- [ ] **Step 6: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add components/pipeline/types.ts
git commit -m "feat(frontend): extend PipelineLayer with SOURCE / ACTIVATION"
```

---

## Task 8: Extend `CATEGORY_LAYER_MAP` and default filter sets in lineage `types.ts`

**Files:**
- Modify: `components/lineage/types.ts:337-359` (`CATEGORY_LAYER_MAP`, related visuals)
- Modify: `components/lineage/types.ts:560-590` (default filter `layers` arrays)
- Modify: `components/lineage/types.ts:725-750` (defaultLineageFilters layer set)

- [ ] **Step 1: Read the current category map and filter defaults**

Run: `Read /Users/emilfabel/pallisade-copilot/components/lineage/types.ts offset=336 limit=80`
Run: `Read /Users/emilfabel/pallisade-copilot/components/lineage/types.ts offset=555 limit=40`
Run: `Read /Users/emilfabel/pallisade-copilot/components/lineage/types.ts offset=720 limit=30`

- [ ] **Step 2: Update `CATEGORY_LAYER_MAP` for the new layer values**

Two precise edits to `components/lineage/types.ts`:

**Edit A** — change line 348 from:
```typescript
  source: 'INGESTION',  // dbt sources are upstream
```
To:
```typescript
  source: 'SOURCE',  // external upstream — anchored leftmost in data plane
```

**Edit B** — add two new entries inside the same `CATEGORY_LAYER_MAP` object (immediately after the `source:` line, before the closing `}`):

```typescript
  activation: 'ACTIVATION',   // reverse-ETL targets (Hightouch, Census, ML serving)
  reverse_etl: 'ACTIVATION',  // legacy/alt key seen in some adapter outputs
```

If TypeScript complains that `'activation'` / `'reverse_etl'` are not valid `UnifiedNodeCategory` values, also extend that union type — find `export type UnifiedNodeCategory` (search `grep -n "export type UnifiedNodeCategory" components/lineage/types.ts`) and append `| 'activation' | 'reverse_etl'`.

- [ ] **Step 3: Extend the default filter `layers` arrays**

In each of the existing filter preset objects in `components/lineage/types.ts` (around line 560-590, the "End-to-end" / "Dataset only" / etc. presets), update the `layers:` arrays to include the new layer values where appropriate:

```typescript
  // End-to-end preset — show everything
  layers: ['SOURCE', 'INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING',
           'ACTIVATION', 'ORCHESTRATION', 'VERSION_CONTROL',
           'INFRASTRUCTURE', 'STORAGE'],
```

For more focused presets (e.g., "Dataset only"), include `'SOURCE'` and `'ACTIVATION'` if they're data-plane-relevant.

- [ ] **Step 4: Extend the `defaultLineageFilters` layer Set**

Around line 730 in `components/lineage/types.ts`, find:

```typescript
layers: new Set(['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'ORCHESTRATION', 'VERSION_CONTROL', 'INFRASTRUCTURE', 'STORAGE']),
```

Replace with:

```typescript
layers: new Set(['SOURCE', 'INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'ACTIVATION', 'ORCHESTRATION', 'VERSION_CONTROL', 'INFRASTRUCTURE', 'STORAGE']),
```

- [ ] **Step 5: Run TypeScript type-check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit 2>&1 | grep -E "components/(lineage|pipeline)/types\.ts" | head -20`
Expected: no errors specific to these files. Pre-existing unrelated errors are out of scope.

- [ ] **Step 6: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add components/lineage/types.ts
git commit -m "feat(frontend): wire SOURCE/ACTIVATION into lineage filters"
```

---

## Task 9: Manual UI verification

**Files:** none modified — verification only.

- [ ] **Step 1: Start the dev server**

Run: `cd /Users/emilfabel/pallisade-copilot && npm run dev`
Expected: server starts on `http://localhost:3000`. Leave running in a separate terminal.

- [ ] **Step 2: Open the lineage page in a browser and load a pipeline**

Navigate to `http://localhost:3000/dashboard/lineage`. Select a pipeline profile that has data-plane content (BigQuery / dbt / Looker is typical).

- [ ] **Step 3: Verify the data-plane view renders**

Expected:
- Nodes that previously appeared in `WAREHOUSE` are still grouped together visually.
- Any dbt-source datasets now show with `SOURCE` color (emerald) on the leftmost column.
- BI dashboards still render in `REPORTING` color on the right.
- No console errors related to undefined layer keys.

- [ ] **Step 4: Verify the filter bar shows new toggles**

Expected:
- The `LineageFilterBar` toggle list now includes "Sources" and "Activation" alongside the existing filters.
- Toggling each preset shows/hides the corresponding nodes.

- [ ] **Step 5: Verify nothing visibly regressed for an existing customer-shape pipeline**

Toggle the "End-to-end" preset and confirm:
- The same nodes appear as before.
- Edges connect the same way.
- Layout is left-to-right with no obvious overlapping clusters.

- [ ] **Step 6: Stop the dev server**

In the dev-server terminal: Ctrl-C.

- [ ] **Step 7: Commit any visual-tweak fixes if needed**

If the manual verification surfaced any small adjustments (e.g., color contrast, label wording), commit them now. Otherwise no commit needed.

```bash
# Only if changes were made:
cd /Users/emilfabel/pallisade-copilot
git add components/lineage/ components/pipeline/
git commit -m "fix(frontend): tweak lineage layer visuals after manual review"
```

---

## Task 10: Final cleanup — remove backwards-compat alias

**Files:**
- Modify: `scanner/lineage/engine/zones.py` (remove the alias added in Task 2)

The alias `classify_data_plane_layer = classify_data_plane_role` was added as a safety net in Task 2 Step 3. By this point all internal callers should be using the new name. Remove the alias to avoid confusion.

- [ ] **Step 1: Confirm no remaining callers of the old name**

Run: `cd /Users/emilfabel/pallisade-copilot && grep -rn "classify_data_plane_layer\|DataPlaneLayer\b" scanner/ components/ 2>/dev/null | grep -v ".pyc" | grep -v ".worktrees" | grep -v ".claude/"`
Expected: only the alias-definition lines themselves in `scanner/lineage/engine/zones.py` should match. If any other call sites remain, fix them to use `classify_data_plane_role` / `DataPlaneRole` first.

- [ ] **Step 2: Remove the alias lines**

In `scanner/lineage/engine/zones.py`, delete the two alias lines added at the end of Task 2 Step 3:

```python
# Backwards-compatibility alias for any in-flight imports.
# Remove in a follow-up cleanup once all callers updated.
classify_data_plane_layer = classify_data_plane_role
DataPlaneLayer = DataPlaneRole
```

- [ ] **Step 3: Run the full engine test suite**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest lineage/engine/tests/ -v`
Expected: all tests pass.

- [ ] **Step 4: Run the broader test suite to catch any cross-module imports**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && venv/bin/pytest -v -k "not slow"`
Expected: all tests pass. If any fail with `ImportError` or `AttributeError` mentioning `DataPlaneLayer` or `classify_data_plane_layer`, update those callers to the new names and re-run.

- [ ] **Step 5: Commit**

```bash
cd /Users/emilfabel/pallisade-copilot
git add scanner/lineage/engine/zones.py
git commit -m "chore(lineage/engine): remove DataPlaneLayer alias (use DataPlaneRole)"
```

---

## Verification Checklist (run before declaring done)

- [ ] All new tests pass: `cd scanner && venv/bin/pytest lineage/engine/tests/test_data_plane_role.py lineage/engine/tests/test_endpoints.py -v`
- [ ] All existing engine tests pass: `cd scanner && venv/bin/pytest lineage/engine/tests/ -v`
- [ ] TypeScript type-checks: `npx tsc --noEmit` (no new errors in `components/lineage/` or `components/pipeline/`)
- [ ] Dev-server lineage page renders without console errors
- [ ] Filter bar shows Sources and Activation toggles
- [ ] No remaining references to `DataPlaneLayer` or `classify_data_plane_layer` outside `.pyc` / `.worktrees`
- [ ] Each task committed independently — `git log --oneline -12` shows ten commits with the prefixes `feat(lineage/engine)`, `feat(frontend)`, `chore(lineage/engine)`

---

## Rollback Plan

If any task introduces a regression that blocks downstream work and can't be fixed within the task:

1. `git revert <commit-sha>` for the offending task's commit.
2. The plan is structured so each task is independently revertable — Task 4 can be reverted without affecting Tasks 1-3, and Task 7 can be reverted without affecting backend changes.
3. The Task 10 alias-removal commit is the only one with a non-local impact; if reverted, restore the alias.
