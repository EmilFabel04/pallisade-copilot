# Lineage: Any-Pipeline Support — Design Spec

**Date:** 2026-05-02
**Status:** Phase 1 spec'd + planned; Phase 2 spec'd + queued
**Owner:** Emil Fabel
**Companion plan:** `docs/superpowers/plans/2026-05-02-capability-based-lineage-roles.md`

---

## 1. North-Star Goal

Pallisade's data-plane lineage canvas should faithfully represent **any pipeline shape** a customer brings to the platform — ELT, ETL, reverse-ETL, streaming, and ML — mapping every asset the data flows through, anchored at its true source and its true sink, regardless of warehouse choice, naming convention, or transformation tool.

A pipeline is "fully supported" when:

1. **Origin is correct.** The leftmost column shows the customer's actual sources (app DBs, SaaS sources, event streams, file drops) — not landing tables.
2. **Termination is correct.** The rightmost column shows where data is consumed (dashboards, activation targets, ML serving, exports) — not "any leaf table."
3. **Every persisted asset appears.** No silent drops; nothing collapsed unless explicitly chosen.
4. **Position is flow-driven.** A node's column reflects its capability role + its actual edges, not its name prefix.

**Note on observability tools:** Pallisade IS the observability layer. Third-party observability/monitoring tools (Elementary, Great Expectations, Monte Carlo, Soda, Anomalo, Sifflet, Bigeye, Datafold) are not represented as lineage nodes — Pallisade replaces them, doesn't coexist with them. Their configurations may be imported as monitor seeds, but they do not appear as data-flow assets.

---

## 2. Why the Current State Falls Short

The existing data-plane view (`scanner/lineage/engine/views.py:build_data_plane`) uses `DataPlaneLayer` (`zones.py:240`), a 7-bucket scale shaped by dbt zone conventions: `INGESTION → RAW → STAGING → INTERMEDIATE → MART → SERVING → REPORTING`.

This scale fits ELT pipelines built on dbt. It misrepresents:

- **Reverse-ETL** — Hightouch/Census destinations have nowhere to land; bucketed as `REPORTING` (wrong) or orphaned.
- **ETL without a dbt staircase** — a single Spark transform from source to mart looks like a flat misclassified line.
- **Streaming** — Kafka topics get classified as `RAW` (they're sources, not landing tables); materialised outputs land based on naming alone.
- **ML pipelines** — feature stores and model registries fall through to `MART` or `UNKNOWN`.

Beyond representation, **extraction coverage** is the second axis of fragility:

- No adapters for: Hightouch, Census, Polytomic, MLflow, Vertex, SageMaker, Kafka, Flink (only via OpenLineage if the customer emits events).
- Identity-resolution gaps cause cross-platform islands (same logical table seen by dbt + Fivetran + Looker can show as three nodes).

**Both axes — model and coverage — must improve to deliver the goal.** This spec sequences the work into two phases.

---

## 3. Phase 1 — In Scope (this round)

Captured in: `docs/superpowers/plans/2026-05-02-capability-based-lineage-roles.md`

### 3.1 Capability-role data model

Replace `DataPlaneLayer` with `DataPlaneRole` (7 buckets):

| Role | Position | Meaning |
|---|---|---|
| `SOURCE` | 0 | External upstream — app DBs, SaaS sources, event streams, file drops |
| `INGEST` | 1 | Connectors / pre-warehouse loaders (Fivetran, Airbyte, n8n) |
| `STORE_RAW` | 2 | Raw / landing tables inside the warehouse |
| `TRANSFORM` | 3 | Staging / intermediate transformations (dbt staging, Spark jobs) |
| `STORE_SERVE` | 4 | Marts, analytics, feature stores ready for consumption |
| `SERVE` | 5 | BI / semantic / dashboards / reports |
| `ACTIVATE` | 6 | Reverse-ETL targets, ML inference, exports |

**No `OBSERVE` role.** Pallisade IS the observability layer; third-party observability/monitoring tools are not represented as lineage nodes. Including such a bucket would frame Pallisade as a peer/aggregator instead of the layer that replaces them.

The dbt-zone `DatasetZone` enum is **retained** as a sub-classification under `STORE_RAW` / `TRANSFORM` / `STORE_SERVE` for warehouse-internal granularity, but no longer drives canvas columns directly.

### 3.2 Endpoint classifier (new module: `endpoints.py`)

Returns `EndpointKind ∈ {SOURCE, INTERNAL, SINK, ORPHAN}` with `reason` and `confidence`.

- **SOURCE** — anchors leftmost; high confidence when dbt source or non-warehouse, lower when warehouse-leaf-with-no-upstream (could be extraction gap).
- **SINK** — anchors rightmost; high confidence when BI/activation, lower for plain warehouse leaves (could be unused).
- **ORPHAN** — drives a future "needs clarification" UI affordance (separate spec).

### 3.3 Layout — endpoint-anchored topological sort

`_semantic_topological_layout` (views.py:3283) updated to:

1. Classify each node's `DataPlaneRole`.
2. Classify each node's `EndpointKind`.
3. Run edge-consistency pass (target layer ≥ source + 1).
4. After consistency: pin `EndpointKind.SOURCE` nodes to layer 0; pin `EndpointKind.SINK` nodes to the rightmost in-flow layer.
5. Within layer, sort by `(cluster_id, topo_order, name)`.

### 3.4 Frontend layer extension

`PipelineLayer` type union extended with `'SOURCE' | 'ACTIVATION'`. `LAYER_COLORS`, `LAYER_LABELS`, `CATEGORY_LAYER_MAP`, default filter Sets all extended. Filter bar surfaces the new toggles automatically.

### 3.5 Phase 1 explicitly excludes

- New extraction adapters (Hightouch, Census, Polytomic, MLflow, Vertex, SageMaker, Kafka, Flink direct).
- Identity-resolution improvements.
- Clarification chat surface for orphans / low-confidence classifications.
- Per-role SLA recommendations.
- Deprecating `FunctionalRole` / `PipelineLane` (the lane Pipeline Overview view is unchanged).
- Any OBSERVE / OBSERVABILITY classification — Pallisade IS the observability layer (see section 1).

---

## 4. Phase 2 — Deferred (separate plan, spec'd here)

To be captured in: `docs/superpowers/plans/2026-05-XX-lineage-extraction-coverage.md` (not yet written)

### 4.1 Adapter coverage (highest ROI first)

| Adapter | Effort | Pipeline shape unblocked |
|---|---|---|
| `live_hightouch.py` | ~1 day — REST API: list destinations + sync configs | Reverse-ETL |
| `live_census.py` | ~1 day — REST API similar shape | Reverse-ETL |
| `live_kafka.py` | ~2 days — topic metadata + Schema Registry | Streaming sources |
| `live_mlflow.py` | ~3-4 days — experiments, models, registry | ML pipelines |
| `live_vertex.py` / `live_sagemaker.py` | ~3-4 days each | ML pipelines (cloud-hosted) |
| `live_polytomic.py` | ~1 day | Reverse-ETL (smaller customer base) |

Sequence: Hightouch + Census first (largest unblocked customer set), then Kafka, then ML adapters as customer demand surfaces.

### 4.2 OpenLineage-first hardening

OpenLineage consumer (`openlineage.py`, `live_openlineage.py`) already exists. Phase 2 hardens it:

- **Endpoint receiver** — HTTP endpoint that accepts OL events live (vs batch ingest). Allows customers with OL emitters to flow data without per-tool adapters.
- **Column-lineage extraction** from OL `columnLineage` facets — currently partially handled.
- **Run metadata enrichment** — feed OL run events into health/freshness signals.

This step alone covers most of cases 2 (Spark ETL) and 3 (Flink streaming) without writing per-tool adapters, provided the customer has OL emitters configured.

### 4.3 Identity-resolution service

Extract the cross-platform FQN merging logic from `reconciler.py` into a callable service (`identity.py`) with:

- `resolve(candidate_fqn, platform, hints) → canonical_id`
- Used by both ingest-time adapters and a future clarification chat.
- Persists manual overrides as graph metadata with `{evidence, source: "user_clarification", confirmed_at, ttl}`.

### 4.4 Clarification chat (separate spec)

A second clarification surface (distinct from the existing `feat-clarification-layer` SLA chat). Driven by:

- `EndpointKind.ORPHAN` nodes
- Low-confidence `EndpointClassification` (warehouse-leaf-with-no-upstream, leaf-warehouse-asset)
- Inferred ghost nodes (high count, no schema entry)
- Cross-platform identity candidates (FQN match score 0.5–0.9)

Each prompt = one anomaly + small choice set → one persisted graph patch through the existing reconciler.

### 4.5 Phase 2 explicitly excludes (Phase 3+)

- Custom-script discovery (Lambda, Cloud Run, internal Python) — depends on repo-crawl + dynamic SQL parsing.
- BI tools beyond Tableau/Looker/Metabase/Power BI (Mode, Hex, Sigma, Retool).
- Catalog integrations (DataHub, Atlan, OpenMetadata) — would be import sources, not extraction targets.

---

## 5. Promise Matrix — What Works After Each Phase

For each pipeline shape from the user's vision:

| Pipeline shape | Phase 1 only | Phase 2 (adapters) | Phase 3+ (custom-code coverage) |
|---|---|---|---|
| **dbt-shaped ELT** | ✅ Already worked; cleaner now | ✅ | ✅ |
| **ETL without dbt** (Spark, Talend) | ⚠️ Works only if OL events emitted | ✅ Works (OL hardening + adapters) | ✅ |
| **Reverse-ETL** (Hightouch / Census) | ❌ ACTIVATE column exists but empty without adapter | ✅ Full round-trip visible | ✅ |
| **Streaming** (Kafka / Flink) | ⚠️ Works only if OL events emitted | ✅ Native Kafka adapter + OL Flink | ✅ |
| **ML pipelines** (MLflow / Vertex) | ❌ No nodes in graph | ✅ Once ML adapters land | ✅ |
| **Reverse-ETL with custom Python** | ❌ | ⚠️ Partial — OL if instrumented | ✅ Repo crawl + SQL parse |
| **Internal Lambda ingest** | ❌ | ❌ | ✅ Repo crawl |

(Note: pipelines with third-party observability tooling are not a separate row — Pallisade replaces those tools, so they're never expected to appear as lineage nodes.)

**Phase 1 alone delivers:** dbt-ELT (improved) + OL-emitting ETL/streaming customers (immediate).
**Phase 1 + Phase 2 delivers:** all in-scope shapes (ELT, ETL, reverse-ETL, streaming, ML) modulo OL-emission requirement for streaming and in-flight ETL.
**Phase 3+ delivers:** custom-code coverage where the customer has bespoke ingestion outside any standard tool.

---

## 6. Decision Log

**Why split the model from the extraction.**
The model change (Phase 1) is invariant — every adapter that lands later populates the same role/endpoint structure. Without it, adapters would have to encode their own positioning logic. With it, adapters are pure metadata producers and the canvas handles representation. Building extraction first would create cleanup churn when the model lands.

**Why not deprecate `FunctionalRole` / `PipelineLane`.**
The lane Pipeline Overview view answers a different question (tool/integration topology) than the Data Plane (asset topology). Both are first-class. Phase 1 changes only the data-plane layout; the lane view keeps its existing classification stack.

**Why OpenLineage hardening sits in Phase 2, not Phase 1.**
The OL consumer already exists and works for the common emitters. Hardening (live HTTP endpoint, column-lineage facet, run metadata) is incremental coverage, not a model gap. It belongs with the adapter work because all three serve the same goal: more nodes in the graph for the new model to position.

**Why ML adapters are deferred behind reverse-ETL.**
Customer demand is heavier on reverse-ETL (Hightouch/Census ship in nearly every modern stack); ML pipelines vary too much per shop to template. Reverse-ETL adapters also exercise the `ACTIVATE` role end-to-end, which is the riskier of the two new role buckets.

**Why there is no OBSERVE / OBSERVABILITY role.**
Pallisade IS the observability layer. Including a bucket for third-party observability tools (Elementary, Great Expectations, Monte Carlo, Soda, etc.) would frame Pallisade as a peer or aggregator of those tools rather than the layer that replaces them. Adapters for tools like Elementary may still exist for *monitor seeding* (extracting dbt test definitions to bootstrap Pallisade monitors), but their outputs are never first-class lineage nodes — they feed Pallisade's own monitor system instead. This is consistent with the related rule that Pallisade is monitor-only and never moves customer data: both are "Pallisade is the X layer, not a participant in X" framings.

---

## 7. Acceptance Criteria

### Phase 1 done when:

- [ ] `DataPlaneRole` enum + `classify_data_plane_role` shipping with tests
- [ ] `endpoints.py` module shipping with tests
- [ ] `_semantic_topological_layout` anchors sources at column 0, sinks at rightmost
- [ ] Frontend renders `SOURCE` and `ACTIVATION` layers with distinct colors
- [ ] Filter bar surfaces the two new toggles
- [ ] All existing tests pass; no visual regression for current dbt-ELT customer pipelines
- [ ] No `DataPlaneRole.OBSERVE` / `OBSERVABILITY` references appear anywhere in code or types
- [ ] No `DataPlaneLayer` / `classify_data_plane_layer` references remain

### Phase 2 done when (per-adapter, independently):

- [ ] At least one reverse-ETL adapter (Hightouch) shipping; ACTIVATE column populated end-to-end for a real pipeline
- [ ] OpenLineage HTTP receiver shipping with column-lineage facet support
- [ ] Identity-resolution service extracted from reconciler with public API
- [ ] At least one ML adapter (MLflow) shipping

### "Any pipeline" claim defensible when:

- All Phase 1 + Phase 2 acceptance criteria met
- A net-new customer with one of the five vision shapes can connect their stack and see correct lineage end-to-end without manual node mapping

---

## 8. Out of Scope (to prevent scope creep)

- Visualisation beyond the data-plane canvas (Pipeline Overview, lane view) — separate work.
- Lineage *enrichment* via the copilot (asking the LLM to fill gaps) — deferred until Phase 2 lands and we can measure actual residual gaps.
- Streaming-specific UI affordances (windowing, watermarks, throughput) — separate spec if/when streaming adoption justifies.
- Cost / impact analysis derived from lineage — separate spec.
- Multi-environment merging logic (dev/staging/prod) — Phase 2 adapter work surfaces this; address when it concretely breaks for a customer.
