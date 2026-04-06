# SLA Discovery: Uniqueness + Schema Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add uniqueness detection (duplicate rate on PK columns) and full schema snapshot to the existing one-shot SLA discovery flow, with frontend wiring into the SLA editor.

**Architecture:** Two new compute functions in `sla_discovery.py` feeding into the existing `DiscoveryResult` → `NodeDiscoveryResponse` → `SLAEditorPanel` pipeline. Uniqueness uses approximate `COUNT(DISTINCT)` per dialect. Schema snapshot enriches the existing `_compute_schema()` with full column metadata from `get_columns()`.

**Tech Stack:** Python (FastAPI, pytest), TypeScript/React (Next.js)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `scanner/lineage/sla_discovery.py` | Modify | Add `_detect_pk_columns()`, `_compute_uniqueness()`, enhance `_compute_schema()`, add `uniqueness` to `DiscoveryResult` |
| `scanner/api/routers/discovery.py` | Modify | Add `uniqueness` field to `NodeDiscoveryResponse`, map in endpoint |
| `scanner/tests/test_sla_discovery.py` | Modify | Add tests for PK detection, uniqueness compute, enhanced schema |
| `types/sla.ts` | Modify | Add `'uniqueness'` to `DOMAIN_SLA_SECTIONS.warehouse` |
| `components/lineage/DataAssetDetailPanel.tsx` | Modify | Add `uniqueness` to discovery result type and mapping |
| `components/lineage/SLAEditorPanel.tsx` | Modify | Add Uniqueness section to editor |

---

### Task 1: Add `_detect_pk_columns()` with tests

**Files:**
- Modify: `scanner/tests/test_sla_discovery.py`
- Modify: `scanner/lineage/sla_discovery.py`

- [ ] **Step 1: Write failing tests for PK detection**

Add to `scanner/tests/test_sla_discovery.py`:

```python
# ---------------------------------------------------------------------------
# _detect_pk_columns
# ---------------------------------------------------------------------------

class TestDetectPKColumns:

    def test_declared_pk_preferred(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("user_id", pk=False), _col("id", pk=False), _col("email", pk=True)]
        result = _detect_pk_columns(cols)
        assert result == (["email"], "declared_pk")

    def test_multiple_declared_pks(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("org_id", pk=True), _col("user_id", pk=True), _col("name")]
        result = _detect_pk_columns(cols)
        assert result == (["org_id", "user_id"], "declared_pk")

    def test_fallback_id_column(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("id"), _col("name"), _col("email")]
        result = _detect_pk_columns(cols)
        assert result == (["id"], "heuristic_id")

    def test_fallback_underscore_id_pattern(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("user_id"), _col("name"), _col("email")]
        result = _detect_pk_columns(cols)
        assert result == (["user_id"], "heuristic_id_suffix")

    def test_fallback_uuid(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("uuid"), _col("payload"), _col("created_at")]
        result = _detect_pk_columns(cols)
        assert result == (["uuid"], "heuristic_common_name")

    def test_fallback_guid(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("data"), _col("guid"), _col("ts")]
        result = _detect_pk_columns(cols)
        assert result == (["guid"], "heuristic_common_name")

    def test_no_pk_detected(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        cols = [_col("payload"), _col("metadata"), _col("created_at")]
        result = _detect_pk_columns(cols)
        assert result == ([], "none")

    def test_empty_columns(self):
        from scanner.lineage.sla_discovery import _detect_pk_columns
        result = _detect_pk_columns([])
        assert result == ([], "none")
```

Also add the `_col` helper at the top of the test file, near the existing `_mock_adapter`:

```python
def _col(name: str, dtype: str = "STRING", pk: bool = False, nullable: bool = True, ordinal: int = 0):
    """Build a mock ColumnMetadata."""
    c = MagicMock()
    c.name = name
    c.data_type = dtype
    c.is_primary_key = pk
    c.is_nullable = nullable
    c.ordinal_position = ordinal
    return c
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scanner && python -m pytest tests/test_sla_discovery.py::TestDetectPKColumns -v`
Expected: FAIL — `ImportError: cannot import name '_detect_pk_columns'`

- [ ] **Step 3: Implement `_detect_pk_columns()`**

Add to `scanner/lineage/sla_discovery.py` after the `_WAREHOUSE_TYPE_VALUES` constants (around line 33):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scanner && python -m pytest tests/test_sla_discovery.py::TestDetectPKColumns -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add scanner/lineage/sla_discovery.py scanner/tests/test_sla_discovery.py
git commit -m "feat(sla-discovery): add _detect_pk_columns with heuristic chain"
```

---

### Task 2: Add `_compute_uniqueness()` with tests

**Files:**
- Modify: `scanner/tests/test_sla_discovery.py`
- Modify: `scanner/lineage/sla_discovery.py`

- [ ] **Step 1: Write failing tests for uniqueness compute**

Add to `scanner/tests/test_sla_discovery.py`:

```python
# ---------------------------------------------------------------------------
# _compute_uniqueness
# ---------------------------------------------------------------------------

class TestComputeUniqueness:

    def test_zero_duplicates(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("id", pk=True), _col("name")]
        # APPROX_COUNT_DISTINCT returns 1000, COUNT(*) returns 1000
        adapter.execute_query.return_value = [{"_total": 1000, "_distinct": 1000}]
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result is not None
        assert result["enabled"] is True
        assert result["duplicateRate"] == 0.0
        assert result["primaryKeyColumns"] == ["id"]
        assert result["totalRows"] == 1000
        assert result["distinctRows"] == 1000

    def test_some_duplicates(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("id"), _col("name")]
        adapter.execute_query.return_value = [{"_total": 1000, "_distinct": 970}]
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result is not None
        assert result["duplicateRate"] == pytest.approx(0.03, abs=0.001)
        assert result["detectionMethod"] == "heuristic_id"
        assert result["approximate"] is True

    def test_no_pk_skips(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("payload"), _col("metadata")]
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result is not None
        assert result["enabled"] is False
        assert result["skipped"] is True
        assert "no PK" in result["reason"]

    def test_query_failure_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("id")]
        adapter.execute_query.side_effect = Exception("timeout")
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result is None

    def test_get_columns_failure_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.side_effect = Exception("access denied")
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result is None

    def test_postgres_uses_exact_count(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "postgres"
        adapter.get_columns.return_value = [_col("id")]
        adapter.execute_query.return_value = [{"_total": 500, "_distinct": 500}]
        result = _compute_uniqueness(adapter, "public.table")
        assert result is not None
        assert result["approximate"] is False

    def test_threshold_suggestion(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("id")]
        # 2% duplicate rate → threshold should be max(0.02 * 1.5, 0.01) = 0.03
        adapter.execute_query.return_value = [{"_total": 1000, "_distinct": 980}]
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result["suggestedThreshold"] == pytest.approx(0.03, abs=0.001)

    def test_threshold_floor(self):
        from scanner.lineage.sla_discovery import _compute_uniqueness
        adapter = MagicMock()
        adapter.dialect = "bigquery"
        adapter.get_columns.return_value = [_col("id")]
        # 0% duplicate rate → threshold floor at 0.01
        adapter.execute_query.return_value = [{"_total": 1000, "_distinct": 1000}]
        result = _compute_uniqueness(adapter, "proj.ds.table")
        assert result["suggestedThreshold"] == pytest.approx(0.01, abs=0.001)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scanner && python -m pytest tests/test_sla_discovery.py::TestComputeUniqueness -v`
Expected: FAIL — `ImportError: cannot import name '_compute_uniqueness'`

- [ ] **Step 3: Implement `_compute_uniqueness()`**

Add to `scanner/lineage/sla_discovery.py` after `_compute_quality()` (around line 396):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scanner && python -m pytest tests/test_sla_discovery.py::TestComputeUniqueness -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add scanner/lineage/sla_discovery.py scanner/tests/test_sla_discovery.py
git commit -m "feat(sla-discovery): add _compute_uniqueness with approximate distinct"
```

---

### Task 3: Enhance `_compute_schema()` for full column snapshot + tests

**Files:**
- Modify: `scanner/tests/test_sla_discovery.py`
- Modify: `scanner/lineage/sla_discovery.py`

- [ ] **Step 1: Write failing tests for enhanced schema**

Add to `scanner/tests/test_sla_discovery.py`, replacing the existing `TestComputeSchema` class:

```python
class TestComputeSchema:

    def test_standard_columns_suggest_strict(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = _mock_adapter(columns=[("id", "INT64"), ("name", "STRING"), ("ts", "TIMESTAMP")])
        result = _compute_schema(adapter, "db.schema.table")
        assert result is not None
        assert result["strictness"] == "strict"
        assert result["allowEvolution"] is False
        assert result["columnCount"] == 3

    def test_json_columns_suggest_warn(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = _mock_adapter(columns=[("id", "INT64"), ("payload", "JSON"), ("ts", "TIMESTAMP")])
        result = _compute_schema(adapter, "db.schema.table")
        assert result is not None
        assert result["strictness"] == "warn"
        assert result["allowEvolution"] is True

    def test_variant_columns_suggest_warn(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = _mock_adapter(columns=[("id", "INT64"), ("data", "VARIANT")])
        result = _compute_schema(adapter, "db.schema.table")
        assert result is not None
        assert result["strictness"] == "warn"
        assert result["allowEvolution"] is True

    def test_exception_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = MagicMock()
        adapter.get_columns.side_effect = Exception("access denied")
        result = _compute_schema(adapter, "db.schema.table")
        assert result is None

    def test_empty_columns_returns_none(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = MagicMock()
        adapter.get_columns.return_value = []
        result = _compute_schema(adapter, "db.schema.table")
        assert result is None

    # --- New: column snapshot tests ---

    def test_columns_list_populated(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = _mock_adapter(columns=[("id", "INT64"), ("name", "STRING"), ("ts", "TIMESTAMP")])
        # Set ordinal and nullable on the mocks
        for i, col in enumerate(adapter.get_columns.return_value):
            col.ordinal_position = i + 1
            col.is_nullable = i > 0  # id not nullable, rest nullable
        result = _compute_schema(adapter, "db.schema.table")
        assert "columns" in result
        assert len(result["columns"]) == 3
        assert result["columns"][0] == {"name": "id", "type": "INT64", "nullable": False, "ordinal": 1}
        assert result["columns"][1] == {"name": "name", "type": "STRING", "nullable": True, "ordinal": 2}
        assert result["columns"][2] == {"name": "ts", "type": "TIMESTAMP", "nullable": True, "ordinal": 3}

    def test_columns_sorted_by_ordinal(self):
        from scanner.lineage.sla_discovery import _compute_schema
        adapter = _mock_adapter(columns=[("b_col", "STRING"), ("a_col", "INT64")])
        cols = adapter.get_columns.return_value
        cols[0].ordinal_position = 2
        cols[0].is_nullable = True
        cols[1].ordinal_position = 1
        cols[1].is_nullable = False
        result = _compute_schema(adapter, "db.schema.table")
        assert result["columns"][0]["name"] == "a_col"
        assert result["columns"][1]["name"] == "b_col"
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd scanner && python -m pytest tests/test_sla_discovery.py::TestComputeSchema::test_columns_list_populated tests/test_sla_discovery.py::TestComputeSchema::test_columns_sorted_by_ordinal -v`
Expected: FAIL — `KeyError: 'columns'`

- [ ] **Step 3: Enhance `_compute_schema()` implementation**

Replace the `_compute_schema` function in `scanner/lineage/sla_discovery.py` (lines 398-434):

```python
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
    col_snapshot = sorted(
        [
            {
                "name": c.name,
                "type": getattr(c, "data_type", "UNKNOWN"),
                "nullable": getattr(c, "is_nullable", True),
                "ordinal": getattr(c, "ordinal_position", 0),
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
```

- [ ] **Step 4: Run all schema tests to verify they pass**

Run: `cd scanner && python -m pytest tests/test_sla_discovery.py::TestComputeSchema -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add scanner/lineage/sla_discovery.py scanner/tests/test_sla_discovery.py
git commit -m "feat(sla-discovery): enhance _compute_schema with full column snapshot"
```

---

### Task 4: Wire uniqueness into `DiscoveryResult` and `discover_sla_profile()`

**Files:**
- Modify: `scanner/lineage/sla_discovery.py:46-55` (DiscoveryResult)
- Modify: `scanner/lineage/sla_discovery.py:441-495` (discover_sla_profile)

- [ ] **Step 1: Add `uniqueness` field to `DiscoveryResult`**

In `scanner/lineage/sla_discovery.py`, update the `DiscoveryResult` dataclass (line 46):

```python
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
```

- [ ] **Step 2: Call `_compute_uniqueness()` in `discover_sla_profile()`**

Update `discover_sla_profile()` — add the uniqueness call after the quality scan, and include it in the result and logging:

```python
async def discover_sla_profile(
    node: LineageNode,
    graph: LineageGraph,
    adapter: Any,
) -> DiscoveryResult:
    """Build an SLA profile for *node* by querying the actual table data."""
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
```

- [ ] **Step 3: Run all tests to verify nothing broke**

Run: `cd scanner && python -m pytest tests/test_sla_discovery.py -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add scanner/lineage/sla_discovery.py
git commit -m "feat(sla-discovery): wire uniqueness into DiscoveryResult and discover_sla_profile"
```

---

### Task 5: Wire uniqueness into `NodeDiscoveryResponse` and endpoint

**Files:**
- Modify: `scanner/api/routers/discovery.py:31-40` (NodeDiscoveryResponse)
- Modify: `scanner/api/routers/discovery.py:189-198` (endpoint return)

- [ ] **Step 1: Add `uniqueness` to response model and endpoint**

In `scanner/api/routers/discovery.py`, update `NodeDiscoveryResponse`:

```python
class NodeDiscoveryResponse(BaseModel):
    """Response with discovered SLA profile suggestions."""
    node_fqn: str
    warehouse_ancestor_fqn: Optional[str] = None
    freshness: Optional[Dict[str, Any]] = None
    volume: Optional[Dict[str, Any]] = None
    quality: Optional[Dict[str, Any]] = None
    schema_profile: Optional[Dict[str, Any]] = None
    uniqueness: Optional[Dict[str, Any]] = None
    unsupported: bool = False
    skipped_reason: Optional[str] = None
```

Update the return statement at line 189:

```python
    return NodeDiscoveryResponse(
        node_fqn=result.node_fqn,
        warehouse_ancestor_fqn=result.warehouse_ancestor_fqn,
        freshness=result.freshness,
        volume=result.volume,
        quality=result.quality,
        schema_profile=result.schema,
        uniqueness=result.uniqueness,
        unsupported=result.unsupported,
        skipped_reason=result.skipped_reason,
    )
```

- [ ] **Step 2: Commit**

```bash
git add scanner/api/routers/discovery.py
git commit -m "feat(sla-discovery): add uniqueness to NodeDiscoveryResponse"
```

---

### Task 6: Frontend — add uniqueness to discovery result type and mapping

**Files:**
- Modify: `components/lineage/DataAssetDetailPanel.tsx:401-406` (type)
- Modify: `components/lineage/DataAssetDetailPanel.tsx:423-428` (mapping)
- Modify: `components/lineage/DataAssetDetailPanel.tsx:1393-1410` (confirmation UI)
- Modify: `components/lineage/DataAssetDetailPanel.tsx:1414-1418` (defaults mapping)
- Modify: `types/sla.ts:177` (DOMAIN_SLA_SECTIONS)

- [ ] **Step 1: Add `'uniqueness'` to DOMAIN_SLA_SECTIONS**

In `types/sla.ts` line 177, add `'uniqueness'` to the warehouse sections:

```typescript
export const DOMAIN_SLA_SECTIONS: Record<SLADomain, string[]> = {
  warehouse: ['freshness', 'schema', 'volume', 'anomaly', 'quality', 'uniqueness'],
  ingestion: ['freshness', 'ingestion'],
  bi: ['bi', 'freshness'],
  orchestration: ['orchestration'],
  transform: ['transform', 'freshness', 'schema'],
};
```

- [ ] **Step 2: Update discovery result type**

In `DataAssetDetailPanel.tsx`, update the `discoveryResult` state type (around line 401):

```typescript
  const [discoveryResult, setDiscoveryResult] = useState<{
    freshness?: { enabled: boolean; maxHours: number; warningHours: number };
    volume?: { enabled: boolean; minRows: number; maxRows: number };
    quality?: { enabled: boolean; maxNullRate: number };
    schema?: { enabled: boolean; strictness: string; allowEvolution: boolean; columnCount: number; columns?: { name: string; type: string; nullable: boolean; ordinal: number }[] };
    uniqueness?: { enabled: boolean; duplicateRate: number; primaryKeyColumns: string[]; detectionMethod: string; totalRows: number; distinctRows: number; approximate: boolean; suggestedThreshold: number; skipped?: boolean; reason?: string };
  } | null>(null);
```

- [ ] **Step 3: Update API response mapping**

In `DataAssetDetailPanel.tsx`, update the `setDiscoveryResult` call (around line 423):

```typescript
        setDiscoveryResult({
          freshness: r.freshness || undefined,
          volume: r.volume || undefined,
          quality: r.quality || undefined,
          schema: r.schema_profile || r.schema || undefined,
          uniqueness: r.uniqueness || undefined,
        });
```

- [ ] **Step 4: Add uniqueness to confirmation UI**

In `DataAssetDetailPanel.tsx`, after the schema row in the confirmation UI (after line 1409):

```tsx
                {discoveryResult.uniqueness && discoveryResult.uniqueness.enabled && (
                  <div className="flex justify-between"><span className="text-[var(--muted)]">Uniqueness</span><span className="text-[var(--text)]">{(discoveryResult.uniqueness.duplicateRate * 100).toFixed(1)}% dup rate ({discoveryResult.uniqueness.primaryKeyColumns.join(', ')})</span></div>
                )}
                {discoveryResult.uniqueness && !discoveryResult.uniqueness.enabled && (
                  <div className="flex justify-between"><span className="text-[var(--muted)]">Uniqueness</span><span className="text-[var(--text-faint)]">skipped — {discoveryResult.uniqueness.reason}</span></div>
                )}
```

- [ ] **Step 5: Add uniqueness to defaults mapping**

In `DataAssetDetailPanel.tsx`, add after the schema mapping (around line 1418):

```typescript
                  if (discoveryResult?.uniqueness) defaults.uniquenessConfig = discoveryResult.uniqueness;
```

- [ ] **Step 6: Commit**

```bash
git add types/sla.ts components/lineage/DataAssetDetailPanel.tsx
git commit -m "feat(sla-discovery): wire uniqueness + enhanced schema into frontend discovery flow"
```

---

### Task 7: Frontend — add Uniqueness and Schema columns sections to SLAEditorPanel

**Files:**
- Modify: `components/lineage/SLAEditorPanel.tsx`

- [ ] **Step 1: Add Uniqueness section after Quality section**

In `SLAEditorPanel.tsx`, after the Quality section closing `</div>` (around line 447), add:

```tsx
          {/* Uniqueness section */}
          {applicableSections.includes('uniqueness') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Uniqueness</h4>
              {getVal('uniquenessConfig', 'skipped') ? (
                <p className="text-[11px] text-[var(--text-faint)]">
                  Skipped — {getVal('uniquenessConfig', 'reason') || 'no PK detected'}
                </p>
              ) : (
                <>
                  {getVal('uniquenessConfig', 'duplicateRate') != null && (
                    <div className="text-[11px] text-[var(--muted)] space-y-0.5">
                      <p>Duplicate rate: <span className={`font-medium ${getVal('uniquenessConfig', 'duplicateRate') > 0 ? 'text-amber-400' : 'text-[var(--text)]'}`}>{(getVal('uniquenessConfig', 'duplicateRate') * 100).toFixed(2)}%</span></p>
                      <p>PK columns: <span className="text-[var(--text)] font-mono">{(getVal('uniquenessConfig', 'primaryKeyColumns') || []).join(', ')}</span></p>
                      <p>Detection: <span className="text-[var(--text)]">{getVal('uniquenessConfig', 'detectionMethod')}</span>
                        {getVal('uniquenessConfig', 'approximate') && <span className="text-[var(--text-faint)]"> (approx)</span>}
                      </p>
                      <p>Rows: <span className="text-[var(--text)]">{Number(getVal('uniquenessConfig', 'distinctRows') || 0).toLocaleString()} distinct / {Number(getVal('uniquenessConfig', 'totalRows') || 0).toLocaleString()} total</span></p>
                    </div>
                  )}
                  <NumberInput
                    label="Max duplicate rate"
                    value={(() => { const v = getVal('uniquenessConfig', 'maxDuplicateRate') ?? getVal('uniquenessConfig', 'suggestedThreshold'); return v != null ? Math.round(v * 100 * 100) / 100 : undefined; })()}
                    onChange={(v) => setVal('uniquenessConfig', 'maxDuplicateRate', v / 100)}
                    suffix="%"
                    min={0}
                    max={100}
                    placeholder={hasDiscovery ? '' : 'e.g. 1'}
                  />
                </>
              )}
            </div>
          )}
```

- [ ] **Step 2: Add collapsible column list to Schema section**

In `SLAEditorPanel.tsx`, update the Schema section (around line 368) to include a column list after the strictness select:

```tsx
          {/* Schema section */}
          {applicableSections.includes('schema') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Schema</h4>
              <StrictnessSelect
                label="Strictness"
                value={getVal('schemaConfig', 'strictness') || 'warn'}
                onChange={(v) => setVal('schemaConfig', 'strictness', v)}
              />
              {getVal('schemaConfig', 'columnCount') != null && (
                <p className="text-[11px] text-[var(--muted)]">
                  Columns: <span className="text-[var(--text)] font-medium">{getVal('schemaConfig', 'columnCount')}</span>
                </p>
              )}
              {getVal('schemaConfig', 'columns') && (
                <details className="mt-1">
                  <summary className="text-[10px] text-[var(--muted)] cursor-pointer hover:text-[var(--text)]">
                    Column snapshot ({(getVal('schemaConfig', 'columns') as any[]).length} columns)
                  </summary>
                  <div className="mt-1 space-y-0.5 max-h-40 overflow-y-auto">
                    {(getVal('schemaConfig', 'columns') as { name: string; type: string; nullable: boolean; ordinal: number }[]).map((col) => (
                      <div key={col.name} className="flex justify-between text-[10px] font-mono">
                        <span className="text-[var(--muted)] truncate mr-2">{col.name}</span>
                        <span className="text-[var(--text)] whitespace-nowrap">{col.type}{col.nullable ? '' : ' NOT NULL'}</span>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          )}
```

- [ ] **Step 3: Commit**

```bash
git add components/lineage/SLAEditorPanel.tsx
git commit -m "feat(sla-discovery): add Uniqueness section and Schema column snapshot to SLA editor"
```

---

### Task 8: Run full test suite and verify

**Files:** None (verification only)

- [ ] **Step 1: Run all SLA discovery tests**

Run: `cd scanner && python -m pytest tests/test_sla_discovery.py -v`
Expected: All tests pass (existing + new)

- [ ] **Step 2: Run TypeScript type check**

Run: `npx tsc --noEmit`
Expected: No new type errors

- [ ] **Step 3: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: address any test/type fixups from uniqueness + schema snapshot"
```
