# Streaming v1 — Kafka + CDC + Narrow K8s Workload Monitoring

**Date:** 2026-04-21
**Status:** Design — awaiting implementation plan
**Scope:** First expansion of end-of-pipeline monitoring beyond warehouse tables and BI dashboards. Adds Kafka topics, consumer groups, Kafka Connect connectors (including Debezium CDC), and narrow Kubernetes workload health as monitored node types.
**Target ICP:** Fintech, SaaS, software, data-heavy companies running Kafka-API-compatible streaming infrastructure.
**Out of v1:** Stream processors (Flink/Spark/Materialize), real-time stores (Rockset/Pinot/ClickHouse), broad Kubernetes infra monitoring, ML model registries, Grafana as a BI type, full data-plane in-line consumption.

## Why this spec exists

Pallisade currently monitors data reliability at the warehouse layer (BigQuery, Snowflake, Postgres, Redshift) and treats BI dashboards (Looker, Metabase) as terminal consumers in lineage, but not as monitored surfaces. This leaves a substantial reliability gap for fintech and software customers whose revenue-critical data paths run through streaming infrastructure:

- Fraud detection, real-time balance, and payment processing pipelines in fintech run through Kafka.
- CDC from operational databases into the warehouse is often Debezium on Kafka Connect.
- A silent failure in a Connect worker, consumer group stall, or topic schema change today produces warehouse-layer symptoms (stale tables, volume anomalies) hours or days after the root cause.

Competing observability tools either sit in the data-team persona without streaming coverage (Monte Carlo, Elementary), or sit in the SRE persona with broad streaming coverage but no data-reliability framing (Datadog, New Relic). The wedge is **data-reliability-framed streaming observability for fintech** — topics and consumer groups as first-class monitored assets, with broker/connector pod health folded into the same narrative.

## In scope

- **Kafka brokers** (OSS Kafka, Confluent Cloud, Confluent Platform, AWS MSK, Redpanda — all Kafka-API-compatible)
- **Kafka Connect** (self-hosted, Confluent Platform, MSK Connect) — source, sink, and Debezium CDC connectors
- **Confluent-compatible Schema Registry** — topic schema versioning and drift detection
- **Narrow Kubernetes workloads** — only pods hosting the above, filtered by namespace and label selector. Not a separate user-facing node category; surfaced as an attribute on the streaming node
- **Streaming discovery** — one-shot discovery of topics, connectors, consumer groups with suggested SLA thresholds (matches `sla_discovery.py` UX for warehouse tables)
- **Streaming monitor execution** — scheduled via existing `app/api/schedule/` layer with new `MonitorKind` values
- **Sampled data-plane consumption** — opt-in per topic, default off, last-N message validation for schema conformance and payload quality
- **Copilot tools** — new tools for lag, connector status, and cross-lineage correlation

## Out of scope for v1

- **Stream processors**: Flink, Spark Streaming, ksqlDB, Materialize, RisingWave — added as pluggable adapters in phase 2 based on customer pull
- **Real-time OLAP stores**: Rockset, Pinot, Druid, ClickHouse — phase 2
- **Broad Kubernetes/infra monitoring** — pod CPU/memory for workloads not hosting streaming components, cluster events, node health, ingress. This is SRE territory and competing with Datadog/Grafana Cloud would dilute positioning. Stay focused on "your data pipeline's compute" only.
- **Full data-plane in-line consumption** — running as a persistent consumer processing every message is Confluent Health+/Datadog DSPM territory and carries operational + compliance overhead unacceptable for v1. We poll control plane and periodically sample.
- **ML model registries** (MLflow, Vertex AI, SageMaker, Databricks Unity Catalog) — deferred indefinitely; reassess after streaming v1 ships
- **Grafana as a BI node type** — tracked separately as a small follow-on ticket (1–2 days work, not spec-worthy)
- **SLA learning mode** — static defaults with user override in v1; percentile-based baseline learning over 7-day window in phase 2

## Architecture overview

```
Frontend (Next.js)                            Backend (FastAPI)
──────────────────────────                    ──────────────────────────────────
Pipeline page: new STREAMING layer            scanner/adapters/streaming/
Sources page: Kafka source card                 base.py              (new ABCs)
Lineage page: topic/connector/group nodes       kafka.py             (AdminClient + sampled consumer)
Detail panel: streaming-specific sections       kafka_connect.py     (Connect REST)
Schedule UI: reuses existing components         schema_registry.py   (Registry REST)
                                                k8s_workload.py      (K8s API reader)
                                              scanner/lineage/
                                                streaming_discovery.py (parallels sla_discovery.py)
                                              scanner/api/routers/
                                                streaming.py         (discovery endpoints)
                                              scanner/lineage/engine/adapters/
                                                live_kafka.py        (lineage nodes + edges)

Schema (Prisma)
──────────────────────────
MonitorKind enum: +18 new values (full list in "Schema changes" section below)
Monitor.targetFqn: parse-time extension to kafka://, kafka-connect://,
                   kafka-consumer-group:// prefixes (no column change)
MonitoringPlan.watchType: "streaming_health" convention (no schema change)
```

A new `StreamingAdapter` hierarchy sits as a sibling to the existing SQL-shaped `DatabaseAdapter` in `scanner/adapters/base.py`. Routing between warehouse and streaming discovery is gated in `scanner/api/routers/discovery.py` by node category.

Scheduled monitor execution piggybacks on the existing `schedule/` layer — new `MonitorKind` values produce new monitor rows that flow through the existing cron executor, alerting, and notification routing with zero changes to those paths.

## Node taxonomy and lineage

### New `PipelineLayer`: `STREAMING`

Added to `components/pipeline/types.ts:8` alongside `INGESTION`, `TRANSFORMATION`, `WAREHOUSE`, `REPORTING`. New entries in `LAYER_COLORS` and `LAYER_LABELS`. A new `STREAMING` layer is correct over folding into `INGESTION`: Kafka + Connect + stream processors are architecturally distinct from batch ETL and deserve their own lane in the pipeline view.

### Four new `UnifiedNodeCategory` values

Added to `components/lineage/types.ts:100-125`:

| Category | Represents | Layer |
|---|---|---|
| `streaming` | Kafka cluster as a platform tool node (parallels `warehouse`) | `STREAMING` |
| `topic` | A Kafka topic — the primary streaming data asset | `STREAMING` |
| `stream_connector` | Kafka Connect connector (source, sink, or Debezium CDC). Distinct from `connector` which means Fivetran/Airbyte | `STREAMING` |
| `consumer_group` | Kafka consumer group — the asset that has lag | `STREAMING` |

Corresponding entries in `CATEGORY_LAYER_MAP` and `CATEGORY_VISUALS`. Icons: `radio`, `rss`, `git-branch`, `users`.

### Stable ID convention

Extends the existing 5-field format from `scanner/lineage/graph.py:222-237`:

```
platform_domain | environment_scope | namespace | container | name
```

| Asset | platform_domain | namespace | container | name |
|---|---|---|---|---|
| Topic `fraud.transactions` on cluster `fraud-prod` | `streaming` | `fraud-prod` | `fraud` | `transactions` |
| Connector `mysql-orders-cdc` on same cluster | `streaming` | `fraud-prod` | `connect` | `mysql-orders-cdc` |
| Consumer group `fraud-scorer-v2` | `streaming` | `fraud-prod` | `consumers` | `fraud-scorer-v2` |
| Cluster node itself | `streaming` | `fraud-prod` | `` | `fraud-prod` |

`platform_domain = "streaming"` (not `"kafka"`) preserves cross-flavor dedup if Pulsar/Kinesis adapters are added later — they represent the same physical topic from the user's perspective.

### Lineage edges — using `LinePlane`

`UnifiedLineageEdge.plane: LinePlane` (types.ts:246) already exists as `'data' | 'control' | 'cross'` but is barely populated today. Streaming is where it earns its keep:

**Data plane edges** (`plane: 'data'`):
```
source_table (MySQL)
  → stream_connector (Debezium source)       edgeType: captured_by
  → topic (fraud.transactions)               edgeType: publishes_to
  → consumer_group (fraud-scorer-v2)         edgeType: consumed_by
  → stream_connector (BigQuery sink)         edgeType: feeds
  → warehouse_table (fraud.transactions_raw) edgeType: materializes_to
```

**Control plane edges** (`plane: 'control'`):
```
streaming (cluster)
  → topic                edgeType: contains
  → consumer_group       edgeType: contains
  → stream_connector     edgeType: hosts
```

**Cross-plane edges** (`plane: 'cross'`) — used in visualizations that show "this control-plane failure caused that data-plane staleness." Engine support already exists.

### Kubernetes workloads are attributes, not nodes

Pods backing brokers and connectors **do not** get their own node category. They are surfaced as an attribute on the streaming node via a new optional field:

```ts
hostWorkloads?: Array<{
  namespace: string;
  kind: 'Deployment' | 'StatefulSet' | 'Pod';
  name: string;
  status: 'Healthy' | 'Degraded' | 'Failed';
  restartsLast24h: number;
  lastIncident?: string;
}>;
```

Rationale: making pods first-class nodes floods the graph (one Connect cluster can host 50 connectors across 3 pods), blurs positioning into SRE territory, and doesn't match how data-team users think about streaming. Host health is cause-attribution evidence, not a monitored asset.

## Monitor catalog

### Topic monitors

| Monitor | What it measures | Source |
|---|---|---|
| `STREAM_FRESHNESS` | Time since last produced message | `max(timestamp)` from sampled messages |
| `STREAM_THROUGHPUT_LOW` | msgs/sec below floor | AdminClient log-end-offset sampling |
| `STREAM_THROUGHPUT_HIGH` | msgs/sec spike (backlog risk) | Same, upper bound |
| `STREAM_SCHEMA_DRIFT` | Registered schema version changed | Schema Registry version compare |
| `STREAM_PARTITION_IMBALANCE` | Uneven partition distribution | Per-partition offset deltas |
| `STREAM_DLQ_GROWTH` | Dead-letter topic growing | Throughput monitor scoped to DLQ naming convention |
| `STREAM_PAYLOAD_QUALITY` | Null rate / schema conformance | Sampled consumer, opt-in per topic |

### Consumer group monitors

| Monitor | What it measures | Source |
|---|---|---|
| `STREAM_LAG` | Messages behind log end | `listConsumerGroupOffsets` vs log end offsets |
| `STREAM_LAG_TIME` | Time behind (lag ÷ throughput) | Derived from above |
| `STREAM_STALL` | Lag not decreasing for X minutes | Time series of lag samples |
| `STREAM_REBALANCE_RATE` | Rebalances per hour above baseline | Generation ID change count |
| `STREAM_MEMBER_LOSS` | Active member count dropped | Membership count over time |

### Connector monitors

| Monitor | What it measures | Source |
|---|---|---|
| `STREAM_CONNECTOR_FAILURE` | State ≠ RUNNING | Connect REST `GET /connectors/{name}/status` |
| `STREAM_TASK_FAILURE` | Any task FAILED | Same, tasks[] |
| `STREAM_CDC_SNAPSHOT_STUCK` | Debezium snapshot stopped progressing | Debezium JMX / Connect task metrics |
| `STREAM_SINK_LAG` | Sink connector behind destination | `GET /connectors/{name}/offsets` vs log end |

### Host workload monitors (folded into streaming node's `monitorStatus`)

| Monitor | What it measures |
|---|---|
| `STREAM_HOST_POD_UNHEALTHY` | Pod is CrashLoopBackOff / OOMKilled / NotReady |
| `STREAM_HOST_RESTART_ANOMALY` | Restart count spikes above baseline |

## SLA discovery

New module `scanner/lineage/streaming_discovery.py` parallels the warehouse `sla_discovery.py`. Single entry point:

```python
def discover_streaming_profile(node: LineageNode) -> StreamingSLAProfile:
    if node.category == 'topic':
        compute_freshness(topic)          # inter-arrival p95
        compute_throughput(topic)         # p10/p95 of offset deltas
        compute_schema(topic)             # current Registry version
        compute_partition_balance(topic)
        if opt_in(topic):
            compute_payload_quality(topic)  # sampled null rate
    elif node.category == 'consumer_group':
        compute_lag_baseline(group)       # current lag × safety multiplier
        compute_stall_window(group)       # default: 5min warn, 15min fail
        compute_rebalance_baseline(group)
    elif node.category == 'stream_connector':
        compute_connector_liveness(conn)
        compute_task_health_baseline(conn)
        if is_debezium(conn):
            compute_snapshot_expectations(conn)
    return StreamingSLAProfile(...)
```

### Discovery mode: immediate only (v1)

Single-observation baseline with reasonable defaults. Current lag × 2 for warn, × 4 for fail. Current throughput ± 50%/200% for bounds. User edits thresholds in the existing `SLAEditorPanel.tsx` — same UX as warehouse SLA discovery today.

Learning mode (7-day percentile-based baseline refinement) is explicitly phase 2.

### Monitor cadences

| Monitor category | Cadence | Rationale |
|---|---|---|
| Connector status, task failures, pod health | 1 min | Binary signals, cheap, high-stakes |
| Consumer group lag | 1 min | Canonical streaming health metric |
| Topic throughput, freshness | 5 min | Smoothing — avoids noise |
| Schema drift | 15 min | Schemas rarely change |
| Payload quality (sampled consume) | 15 min | Expensive, broker-load-sensitive |
| K8s pod status | 1 min | Bundled with streaming node primary check |

All alerts use **3-consecutive-failure debouncing** before firing to prevent flapping. User can override cadences in `MonitorGroupSettingsModal.tsx`.

## Adapter architecture

### Parallel hierarchy

```
scanner/adapters/
  base.py                       # existing DatabaseAdapter, unchanged
  bigquery.py, snowflake.py ... # existing warehouse adapters, unchanged
  streaming/
    __init__.py
    base.py                     # new ABCs: StreamingAdapter, KafkaConnectAdapter,
                                #           SchemaRegistryAdapter, K8sWorkloadAdapter
    kafka.py                    # Kafka AdminClient + sampled consumer
    kafka_connect.py            # Kafka Connect REST client
    schema_registry.py          # Confluent-compat Schema Registry REST client
    k8s_workload.py             # Narrow K8s API reader (filtered)
```

Not a subtype of `DatabaseAdapter` because the SQL-shaped interface (`execute_query`, `get_columns`, `get_table_freshness`) does not fit streaming. Unification happens at the registry/factory layer, not the base class.

### `StreamingAdapter` interface (primary)

```python
class StreamingAdapter(ABC):
    # Discovery
    @abstractmethod
    def list_topics(self) -> List[TopicMetadata]: ...
    @abstractmethod
    def list_consumer_groups(self) -> List[ConsumerGroupMetadata]: ...
    @abstractmethod
    def list_connectors(self) -> List[ConnectorMetadata]: ...

    # Health / metrics (control plane)
    @abstractmethod
    def get_topic_metrics(self, topic: str) -> TopicMetrics: ...
    @abstractmethod
    def get_consumer_group_lag(self, group: str) -> ConsumerGroupLag: ...
    @abstractmethod
    def get_connector_status(self, connector: str) -> ConnectorStatus: ...

    # Schema
    @abstractmethod
    def get_topic_schema(self, topic: str) -> Optional[TopicSchema]: ...

    # Sampled data plane (caller gates on per-topic opt-in config)
    @abstractmethod
    def sample_messages(self, topic: str, n: int = 100, from_end: bool = True) -> List[SampledMessage]: ...

    # Connection health
    @abstractmethod
    def test_connection(self) -> ConnectionTestResult: ...
```

`KafkaConnectAdapter`, `SchemaRegistryAdapter`, and `K8sWorkloadAdapter` are narrower siblings with their own abstract methods. The discovery module composes these — a Kafka cluster can have an optional Connect cluster, optional Schema Registry, and optional K8s workloads.

### Auth configuration

Unified auth schema stored in the integration record; matches the existing pattern for warehouse credentials:

```python
@dataclass
class KafkaAuthConfig:
    mechanism: Literal[
        "PLAINTEXT", "SASL_PLAIN",
        "SASL_SCRAM_SHA_256", "SASL_SCRAM_SHA_512",
        "SASL_OAUTHBEARER",   # Confluent Cloud, Okta
        "SASL_GSSAPI",        # Kerberos (rare, fintech)
        "SSL_MUTUAL",         # mTLS
        "AWS_MSK_IAM",        # MSK
    ]
    username: Optional[str] = None
    password_secret_ref: Optional[str] = None
    client_cert_secret_ref: Optional[str] = None
    client_key_secret_ref: Optional[str] = None
    ca_cert_secret_ref: Optional[str] = None
    oauth_config: Optional[OAuthConfig] = None
    aws_region: Optional[str] = None
```

`_secret_ref` fields follow the existing secret-handling pattern for warehouse creds. Adapters resolve refs at connect time and never receive raw credentials from the DB.

### Library choices

| Component | Library | Rationale |
|---|---|---|
| Kafka client | `confluent-kafka-python` (wraps `librdkafka`) | Every Kafka-API-compatible broker works; supports all auth mechanisms including `SASL_OAUTHBEARER` for Confluent Cloud; matches what customers already run in production |
| Kafka Connect / Schema Registry | `httpx` | REST APIs, async, likely already in the scanner's deps |
| Kubernetes | `kubernetes` (official client) | Filters at API level by namespace + label selector; never lists whole cluster |

Trade-off: `librdkafka` is a native dependency. Linux/macOS wheels are strong; Windows server deploys (already not targeted) would be blocked. `kafka-python` is a pure-Python fallback but lacks `SASL_OAUTHBEARER` and is materially slower.

### Connection management

`StreamingConnectionManager` owns per-integration live connections (AdminClient, Consumer, httpx clients). Initialized on first use, cached until cred rotation or integration update. Prevents broker-side rate limits from reconnect storms.

### Failure mode matrix

Per-component degradation — no single-point whole-integration failure unless the broker itself is unreachable:

| Failure | Still works | Degraded |
|---|---|---|
| Schema Registry unreachable | Everything else | No schema drift detection |
| Kafka Connect unreachable | Topics, consumer groups, schema | Connector health |
| K8s API unreachable | Everything else | No pod health attribute |
| Kafka broker unreachable | Nothing — hard fail, alert immediately | — |

## UI and data flow

### Touched frontend files

| File | Change |
|---|---|
| `components/pipeline/types.ts` | Add `STREAMING` to `PipelineLayer`, color + label entries |
| `components/lineage/types.ts` | Add 4 new categories, `hostWorkloads` field, streaming-specific optional fields (lag, throughput, partitions) |
| `components/lineage/UnifiedNodes.tsx` | Icon + render for topic/connector/consumer_group/streaming |
| `components/lineage/LineageFilterBar.tsx` | Streaming layer toggle + connector-status filter pill |
| `components/lineage/DataAssetDetailPanel.tsx` | Branch by category → new streaming sections (see below) |
| `components/sources/SourceCard.tsx` + wizard | New Kafka/streaming source card with connection wizard |
| `components/schedule/*` | **No UI changes** — new monitor kinds flow through existing components |
| `app/api/streaming/*` | New proxy routes for discovery, test-connection |

### Source connection wizard

1. **Sources page → "Add Source" → "Streaming"** (new card). Same modal pattern as adding BigQuery today.
2. Wizard form:
   - Cluster name (display)
   - Bootstrap servers
   - Auth mechanism dropdown → conditional fields (SASL / mTLS / OAuth / IAM)
   - Optional: Kafka Connect URL + auth
   - Optional: Schema Registry URL + auth
   - Optional: K8s context (namespace + label selector, dropdown prefills common conventions)
3. **Test Connection** — per-component green checks; each independently passable.
4. **Discover Assets** — runs `StreamingDiscovery.discover_cluster()`, returns topics + connectors + groups with suggested SLAs (matches warehouse discovery UX).
5. User selects assets to monitor, saves; assets appear in lineage.

### Detail panel sections (by category)

**Topic:**
```
Overview            partitions, replication, retention, current msg/sec
Consumer groups     list with live lag, color-coded vs SLA
Schema              current Avro/JSON/Protobuf version, last change, subjects
Upstream            CDC source connector + source DB
Downstream          consumer groups, sink connectors, warehouse targets
Host workloads      broker pods: status, restarts, last incident
Monitors & alerts   existing shared component
```

**Consumer group:**
```
Overview            member count, assignment strategy, last rebalance
Lag timeline        chart over last 24h
Topics consumed     linked topics
Rebalance history   last 10 rebalances
Host workloads      consumer-app pods (if K8s-discoverable)
Monitors & alerts   shared component
```

**Connector:**
```
Overview            type, plugin class, state, config summary
Tasks               per-task state, errors, restarts
Source/target       sink destination or CDC source DB (cross-layer links)
Snapshot progress   Debezium-only: phase, captured tables, ETA
Host workloads      Connect worker pods
Monitors & alerts   shared component
```

### Data flow: detail-panel load

```
Frontend: GET /api/streaming/discover/topic/:id
  → Next.js proxy
  → FastAPI: /api/v1/streaming/discover/topic/:id
  → StreamingDiscovery.discover_topic(topic_id)
      ├─ KafkaAdapter.get_topic_metrics(topic)       # parallel
      ├─ SchemaRegistryAdapter.get_latest_schema()   # parallel
      ├─ KafkaAdapter.sample_messages(topic, n=100)  # gated on opt-in
      ├─ K8sAdapter.get_workloads(label=broker)      # parallel
      └─ EngineStore.get_lineage_neighbors(topic_id)
  → returns StreamingTopicProfile DTO
  → React Query caches, panel renders
```

Fan-out via `asyncio.gather`, target ~200–500ms with warm connection pool.

### Real-time updates

React Query refetch every 10s for lag chart and throughput values. No websockets — matches existing polling pattern for warehouse monitor statuses; cron-driven monitors are the source of truth for alerting.

### Degraded UI states

- Schema Registry unavailable → Schema section shows "Schema Registry not configured or unreachable" with reconnect link
- K8s adapter not configured → Host workloads section hidden entirely (not empty, omitted)
- Connect unreachable → Connector pages show banner; topic/group detail still works
- Broker unreachable → Banner on detail panel: "Cluster unreachable — last checked 2m ago"

### Copilot integration

New tools in `scanner/copilot/tool_executor.py`:

- `check_consumer_lag(group)`
- `get_topic_metrics(topic)`
- `get_connector_status(name)`
- `get_task_statuses(name)`

Enable answers like:
- "Is my fraud topic lagging?"
- "Why did the Salesforce sink break yesterday?"
- "Show me freshness for all topics feeding the fraud model"

These wrap the same adapters — no new tool surface, just copilot wrappers.

## Schema changes (Prisma)

Minimal. No table additions.

**Additions to `MonitorKind` enum:**
- `STREAM_FRESHNESS`
- `STREAM_THROUGHPUT_LOW`
- `STREAM_THROUGHPUT_HIGH`
- `STREAM_SCHEMA_DRIFT`
- `STREAM_PARTITION_IMBALANCE`
- `STREAM_DLQ_GROWTH`
- `STREAM_PAYLOAD_QUALITY`
- `STREAM_LAG`
- `STREAM_LAG_TIME`
- `STREAM_STALL`
- `STREAM_REBALANCE_RATE`
- `STREAM_MEMBER_LOSS`
- `STREAM_CONNECTOR_FAILURE`
- `STREAM_TASK_FAILURE`
- `STREAM_CDC_SNAPSHOT_STUCK`
- `STREAM_SINK_LAG`
- `STREAM_HOST_POD_UNHEALTHY`
- `STREAM_HOST_RESTART_ANOMALY`

**`Monitor.targetFqn`**: extended to accept `kafka://cluster/topic`, `kafka-connect://cluster/connector`, `kafka-consumer-group://cluster/group` format strings. No column change; parse-time convention.

**`MonitoringPlan.watchType`**: new convention value `"streaming_health"`. No schema change.

## Security and compliance considerations

- **Payload sampling is opt-in per topic, default off.** UI surfaces a warning: "reads actual message content — leave off for topics with sensitive data." Non-negotiable for fintech customers with PCI/PII data.
- **Credentials never leave the adapter layer.** All auth config uses `_secret_ref` pointers; raw values resolved at connect time.
- **Dedicated consumer group naming.** Sampled consumption uses consumer groups prefixed `pallisade-sample-` with `enable.auto.commit=false` and seek-to-end/beginning — never interferes with customer consumer groups or offsets.
- **K8s access uses minimum RBAC.** List/get on pods + deployments + statefulsets in configured namespace only. No secrets access, no cluster-wide permissions.

## Future phases (explicitly not v1)

- **Phase 2a** — Stream processors: Flink, Spark Streaming, Materialize, RisingWave. Each a new adapter implementing a narrower interface focused on job/query health.
- **Phase 2b** — Real-time OLAP: Rockset, Pinot, Druid, ClickHouse. Primarily a new warehouse-like adapter focused on ingestion lag and query latency.
- **Phase 2c** — SLA learning mode: 7-day percentile-based threshold refinement.
- **Phase 3** — Additional broker platforms: Pulsar, Kinesis (already have `KINESIS` in `DatabaseType` enum from original design). Pulsar requires a distinct adapter; Kinesis partially reuses the Kafka shape via the KCL compatibility surface.
- **Separately tracked, not a phase of streaming** — Grafana as a BI node type (small ticket), ML model registry integrations (MLflow/Vertex/SageMaker — reassess after streaming v1 ships).

## Risks and trade-offs

| Risk | Mitigation |
|---|---|
| Native `librdkafka` dependency complicates deployment | Linux/macOS wheels are well-maintained; Windows server was never targeted; document build-from-source fallback |
| Consumer-group-based sampling could theoretically interfere with customer consumers | Dedicated `pallisade-sample-` prefix, `auto.commit=false`, explicit seeks — no offset persistence |
| K8s access breadth — customers may resist handing over cluster access | Namespace + label scoped; K8s is optional; without it, only host workload health is degraded |
| Broker-side rate limits from AdminClient polling at 1-min cadence | Connection reuse via `StreamingConnectionManager`; one AdminClient call fans out to multiple metrics |
| Alert flapping from noisy metrics (lag oscillation, partition imbalance during rebalances) | 3-consecutive-failure debouncing before fire |
| Debezium snapshot detection requires JMX exposure, which many deployments disable | Fall back to Connect task metrics API; further fall back to snapshot-phase flag; document trade-off |

## Acceptance criteria

Shippable when:

1. User can add a Kafka cluster (any of: OSS, Confluent Cloud, Confluent Platform, MSK, Redpanda) via the Sources page connection wizard.
2. After connection, `StreamingDiscovery.discover_cluster()` returns a list of topics, consumer groups, and connectors with suggested SLA thresholds.
3. Discovered assets appear in the lineage page within the `STREAMING` layer with correct edges to upstream/downstream warehouse tables.
4. User can select assets for monitoring; monitors execute on their configured cadence via the existing schedule layer.
5. Monitor failures produce alerts through existing notification routing, with streaming-appropriate messages.
6. Topic, consumer group, and connector detail panels render streaming-specific sections with live data.
7. Opt-in payload sampling on a topic reads last-N messages and validates against Schema Registry schema; opt-out is the default.
8. Copilot can answer "is my fraud topic lagging?" using the new tools.
9. Each failure mode in the matrix (Registry/Connect/K8s unreachable) produces the documented degraded UI state and does not block other sections.
