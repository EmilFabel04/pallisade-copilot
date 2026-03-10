"""
Lineage Investigator — Context-Accumulating Extraction

Replaces the parallel-independent adapter model with a sequential,
investigative process that examines tools in data-flow order.
Each tool's findings enrich a shared InvestigationContext, enabling
richer cross-tool correlation as the investigation progresses.

Investigation Order (data flows left to right):
  WAREHOUSE → INGESTION → TRANSFORMATION → ORCHESTRATION → REPORTING
  → INFRASTRUCTURE → VERSION_CONTROL → QUALITY
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..graph import (
    EdgeType,
    Evidence,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    LinePlane,
    PlatformDomain,
)
from .adapter import AdapterRegistry
from .bridge import BridgeRuleEngine
from .ids import generate_edge_id
from .platforms import (
    PLATFORM_REGISTRY,
    ToolCategory,
    WAREHOUSE_PLATFORMS,
)
from .planner import PlannerInput, plan_heuristic, plan_with_llm
from .resolver import ResolverConfig, ResolverPipeline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Derived constants (from platform registry)
# ---------------------------------------------------------------------------

TOOL_TYPE_TO_CATEGORY: Dict[str, ToolCategory] = {
    name: info.category
    for name, info in PLATFORM_REGISTRY.items()
    if name == info.name  # exclude aliases
}

INVESTIGATION_ORDER: Dict[ToolCategory, int] = {
    ToolCategory.WAREHOUSE: 1,
    ToolCategory.INGESTION: 2,
    ToolCategory.TRANSFORMATION: 3,
    ToolCategory.ORCHESTRATION: 4,
    ToolCategory.REPORTING: 5,
    ToolCategory.INFRASTRUCTURE: 6,
    ToolCategory.VERSION_CONTROL: 7,
    ToolCategory.QUALITY: 8,
}

TOOL_TO_ADAPTER: Dict[str, str] = {
    name: info.adapter_id
    for name, info in PLATFORM_REGISTRY.items()
    if info.adapter_id and name == info.name  # exclude aliases
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TableRecord:
    """A table discovered during investigation."""
    canonical_fqn: str
    name: str
    database: str = ""
    schema: str = ""
    warehouse_type: str = "unknown"
    discovered_by: List[str] = field(default_factory=list)
    written_by: List[str] = field(default_factory=list)
    read_by: List[str] = field(default_factory=list)
    node_id: Optional[str] = None
    columns: List[Dict[str, Any]] = field(default_factory=list)
    row_count: Optional[int] = None


@dataclass
class ConnectionRecord:
    """A discovered tool-to-tool connection."""
    source_tool: str
    target_tool: str
    connection_type: str
    evidence_summary: str
    confidence: float = 0.0
    evidence_refs: List[str] = field(default_factory=list)


@dataclass
class UnresolvedReference:
    """A table/asset reference not yet matched."""
    reference: str
    source_tool: str
    reference_type: str  # table_read, table_write
    context: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolved_to: Optional[str] = None


@dataclass
class ToolProfile:
    """Profile of what a tool does in the pipeline."""
    tool_type: str
    category: ToolCategory
    integration_id: Optional[str] = None
    tables_written: List[str] = field(default_factory=list)
    tables_read: List[str] = field(default_factory=list)
    schedules: List[Dict[str, Any]] = field(default_factory=list)
    connection_strings: List[Dict[str, Any]] = field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    extraction_success: bool = False
    extraction_error: Optional[str] = None
    extraction_duration_ms: int = 0


@dataclass
class ToolConfig:
    """Configuration for a single tool to investigate."""
    tool_type: str
    config: Dict[str, Any]
    integration_id: Optional[str] = None
    layer: Optional[str] = None
    adapter_type: Optional[str] = None

    @property
    def category(self) -> ToolCategory:
        return TOOL_TYPE_TO_CATEGORY.get(
            self.tool_type.lower(), ToolCategory.WAREHOUSE,
        )

    @property
    def investigation_order(self) -> int:
        return INVESTIGATION_ORDER.get(self.category, 99)


# ---------------------------------------------------------------------------
# InvestigationContext — the detective's notebook
# ---------------------------------------------------------------------------

@dataclass
class InvestigationContext:
    """
    Stateful knowledge base accumulated during investigation.

    Acts as the 'detective's notebook' — each tool examination adds to it,
    and subsequent examinations can reference prior findings.
    """
    table_inventory: Dict[str, TableRecord] = field(default_factory=dict)
    connections: List[ConnectionRecord] = field(default_factory=list)
    unresolved: List[UnresolvedReference] = field(default_factory=list)
    tool_profiles: Dict[str, ToolProfile] = field(default_factory=dict)
    all_nodes: List[LineageNode] = field(default_factory=list)
    all_edges: List[LineageEdge] = field(default_factory=list)
    correlation_edges: List[LineageEdge] = field(default_factory=list)
    log: List[Dict[str, Any]] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # ------- mutations -------

    def register_table(
        self, canonical_fqn: str, name: str, database: str, schema: str,
        warehouse_type: str, discovered_by: str, node_id: str = None,
        columns: List = None, row_count: int = None,
    ) -> TableRecord:
        if canonical_fqn in self.table_inventory:
            rec = self.table_inventory[canonical_fqn]
            if discovered_by not in rec.discovered_by:
                rec.discovered_by.append(discovered_by)
            if columns and len(columns) > len(rec.columns):
                rec.columns = columns
            if row_count and not rec.row_count:
                rec.row_count = row_count
            # Keep the first node_id (warehouse's) — don't overwrite with
            # dbt/n8n node IDs that represent the same physical table
            if node_id and not rec.node_id:
                rec.node_id = node_id
            return rec

        rec = TableRecord(
            canonical_fqn=canonical_fqn, name=name,
            database=database, schema=schema,
            warehouse_type=warehouse_type,
            discovered_by=[discovered_by], node_id=node_id,
            columns=columns or [], row_count=row_count,
        )
        self.table_inventory[canonical_fqn] = rec
        return rec

    def find_table(
        self, name: str, schema: str = None, database: str = None,
    ) -> Optional[TableRecord]:
        """Find a table by name, with optional schema/database qualifiers."""
        name_lower = name.lower().strip()
        candidates: List[TableRecord] = []
        for rec in self.table_inventory.values():
            if rec.name.lower() != name_lower:
                continue
            if schema and rec.schema and rec.schema.lower() != schema.lower():
                continue
            if database and rec.database and rec.database.lower() != database.lower():
                continue
            candidates.append(rec)
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            # Prefer the one with most qualifiers matching
            return candidates[0]
        return None

    def find_table_fuzzy(self, ref: str) -> Optional[TableRecord]:
        """Try to find a table from a dot-qualified reference string."""
        parts = ref.replace("`", "").replace('"', "").replace("[", "").replace("]", "").split(".")
        name = parts[-1] if parts else ref
        schema = parts[-2] if len(parts) > 1 else None
        database = parts[-3] if len(parts) > 2 else None
        return self.find_table(name, schema, database)

    def add_unresolved(self, reference: str, source_tool: str, ref_type: str, context: Dict = None):
        self.unresolved.append(UnresolvedReference(
            reference=reference, source_tool=source_tool,
            reference_type=ref_type, context=context or {},
        ))

    def record_connection(
        self, source_tool: str, target_tool: str, connection_type: str,
        evidence_summary: str, confidence: float = 0.8, evidence_refs: List[str] = None,
    ):
        self.connections.append(ConnectionRecord(
            source_tool=source_tool, target_tool=target_tool,
            connection_type=connection_type,
            evidence_summary=evidence_summary,
            confidence=confidence, evidence_refs=evidence_refs or [],
        ))

    def log_step(self, tool_type: str, message: str, level: str = "info"):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "tool": tool_type,
            "message": message,
            "level": level,
        }
        self.log.append(entry)
        getattr(logger, level, logger.info)(f"[Investigator:{tool_type}] {message}")

    # ------- investigation summary (semantic answers) -------

    def build_summary(self) -> Dict[str, Any]:
        """
        Generate a semantic investigation summary answering key questions:
        - Where does the data come from?
        - Where does it flow?
        - Where/when does it get transformed?
        - Are there reports?
        - Does the pipeline look healthy?
        """
        summary: Dict[str, Any] = {}

        # 1. Where does data come from?
        ingestion_tools = [
            p for p in self.tool_profiles.values()
            if p.category == ToolCategory.INGESTION and p.extraction_success
        ]
        written_tables = []
        for rec in self.table_inventory.values():
            if rec.written_by:
                written_tables.append({
                    "table": rec.canonical_fqn,
                    "written_by": rec.written_by,
                })
        summary["data_sources"] = {
            "ingestion_tools": [t.tool_type for t in ingestion_tools],
            "tables_loaded": written_tables,
            "answer": self._answer_data_sources(ingestion_tools, written_tables),
        }

        # 2. Where does it flow? (warehouse → transformation → reporting)
        flow_stages = []
        for cat in [ToolCategory.WAREHOUSE, ToolCategory.INGESTION,
                     ToolCategory.TRANSFORMATION, ToolCategory.REPORTING]:
            tools = [
                p.tool_type for p in self.tool_profiles.values()
                if p.category == cat and p.extraction_success
            ]
            if tools:
                flow_stages.append({"stage": cat.value, "tools": tools})
        summary["data_flow"] = {
            "stages": flow_stages,
            "connections": [
                {"from": c.source_tool, "to": c.target_tool, "type": c.connection_type}
                for c in self.connections
            ],
            "answer": self._answer_data_flow(flow_stages),
        }

        # 3. Where/when does it get transformed?
        transform_tools = [
            p for p in self.tool_profiles.values()
            if p.category == ToolCategory.TRANSFORMATION and p.extraction_success
        ]
        schedules = []
        for p in self.tool_profiles.values():
            schedules.extend(p.schedules)
        summary["transformation"] = {
            "tools": [t.tool_type for t in transform_tools],
            "model_count": sum(t.node_count for t in transform_tools),
            "schedules": schedules[:10],  # cap at 10
            "answer": self._answer_transformation(transform_tools, schedules),
        }

        # 4. Are there reports?
        reporting_tools = [
            p for p in self.tool_profiles.values()
            if p.category == ToolCategory.REPORTING and p.extraction_success
        ]
        summary["reporting"] = {
            "tools": [t.tool_type for t in reporting_tools],
            "asset_count": sum(t.node_count for t in reporting_tools),
            "answer": self._answer_reporting(reporting_tools),
        }

        # 5. Does the pipeline look healthy?
        total = len(self.tool_profiles)
        succeeded = len([p for p in self.tool_profiles.values() if p.extraction_success])
        failed = [p for p in self.tool_profiles.values() if not p.extraction_success]
        unresolved = [u for u in self.unresolved if not u.resolved]
        summary["health"] = {
            "tools_succeeded": succeeded,
            "tools_failed": len(failed),
            "failed_tools": [p.tool_type for p in failed],
            "unresolved_references": len(unresolved),
            "total_tables": len(self.table_inventory),
            "total_connections": len(self.connections),
            "answer": self._answer_health(succeeded, total, failed, unresolved),
        }

        return summary

    def _answer_data_sources(self, ingestion_tools, written_tables) -> str:
        if not ingestion_tools and not written_tables:
            return "No ingestion tools detected. Data may be loaded manually or via untracked processes."
        parts = []
        if ingestion_tools:
            tools = ", ".join(t.tool_type for t in ingestion_tools)
            parts.append(f"Data is ingested by {tools}")
        if written_tables:
            table_list = ", ".join(t["table"] for t in written_tables[:5])
            writers = set()
            for t in written_tables:
                writers.update(t["written_by"])
            parts.append(f"loading into {len(written_tables)} tables ({table_list}{'...' if len(written_tables) > 5 else ''})")
        return ". ".join(parts) + "." if parts else ""

    def _answer_data_flow(self, flow_stages) -> str:
        if not flow_stages:
            return "No data flow stages detected."
        stage_names = " → ".join(s["stage"] for s in flow_stages)
        return f"Data flows through: {stage_names}."

    def _answer_transformation(self, transform_tools, schedules) -> str:
        if not transform_tools:
            return "No transformation layer detected."
        tools = ", ".join(t.tool_type for t in transform_tools)
        model_count = sum(t.node_count for t in transform_tools)
        msg = f"Data is transformed by {tools} ({model_count} models/assets)"
        if schedules:
            sched_str = schedules[0].get("schedule", "unknown")
            msg += f". Runs on schedule: {sched_str}"
        return msg + "."

    def _answer_reporting(self, reporting_tools) -> str:
        if not reporting_tools:
            return "No reporting/BI tools detected."
        tools = ", ".join(t.tool_type for t in reporting_tools)
        total = sum(t.node_count for t in reporting_tools)
        return f"Reports are served by {tools} ({total} dashboards/reports)."

    def _answer_health(self, succeeded, total, failed, unresolved) -> str:
        if total == 0:
            return "No tools were examined."
        ratio = succeeded / total
        msg = f"{succeeded}/{total} tools extracted successfully"
        if failed:
            msg += f". Failed: {', '.join(p.tool_type for p in failed)}"
        if unresolved:
            msg += f". {len(unresolved)} table references could not be resolved"
        if ratio >= 0.8 and not unresolved:
            msg += ". Pipeline looks healthy"
        elif ratio < 0.5:
            msg += ". Pipeline has significant gaps"
        return msg + "."

    # ------- serialization -------

    def to_dict(self) -> Dict[str, Any]:
        profiles = self.tool_profiles
        succeeded = sum(1 for v in profiles.values() if v.extraction_success)
        failed = sum(1 for v in profiles.values() if v.extraction_error)
        total_duration = sum(v.extraction_duration_ms for v in profiles.values())

        return {
            "table_count": len(self.table_inventory),
            "connection_count": len(self.connections),
            "unresolved_count": len([u for u in self.unresolved if not u.resolved]),
            "extraction_summary": {
                "adapters_total": len(profiles),
                "adapters_succeeded": succeeded,
                "adapters_failed": failed,
                "total_duration_ms": total_duration,
            },
            "tool_profiles": {
                k: {
                    "tool_type": v.tool_type,
                    "category": v.category.value,
                    "tables_written": len(v.tables_written),
                    "tables_read": len(v.tables_read),
                    "node_count": v.node_count,
                    "edge_count": v.edge_count,
                    "success": v.extraction_success,
                    "error": v.extraction_error,
                    "duration_ms": v.extraction_duration_ms,
                }
                for k, v in profiles.items()
            },
            "connections": [
                {
                    "source": c.source_tool, "target": c.target_tool,
                    "type": c.connection_type, "confidence": c.confidence,
                    "evidence": c.evidence_summary,
                }
                for c in self.connections
            ],
            "summary": self.build_summary(),
            "log": self.log,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ---------------------------------------------------------------------------
# CorrelationEngine — algorithmic cross-tool pattern matching
# ---------------------------------------------------------------------------

class CorrelationEngine:
    """
    After each adapter extraction, compares new findings against accumulated
    context and creates correlation edges.

    Strategies (run in order):
      1. Table reference matching (case-normalized FQN)
      2. Connection string matching (host:port:db → warehouse instance)
      3. Schedule alignment (cron/frequency comparison)
      4. Retry previously-unresolved references
      5. Infrastructure hosting detection
    """

    def __init__(self, context: InvestigationContext):
        self.ctx = context

    def correlate(
        self,
        new_nodes: List[LineageNode],
        new_edges: List[LineageEdge],
        tool_type: str,
        tool_category: ToolCategory,
    ) -> List[LineageEdge]:
        edges: List[LineageEdge] = []
        edges.extend(self._correlate_table_references(new_nodes, new_edges, tool_type))
        edges.extend(self._correlate_connection_strings(new_nodes, tool_type))
        edges.extend(self._correlate_schedules(new_nodes, tool_type))
        edges.extend(self._retry_unresolved(tool_type))
        edges.extend(self._correlate_infrastructure(new_nodes, tool_type, tool_category))
        return edges

    # ---- strategy 1: table references (three-phase) ----

    def _correlate_table_references(
        self, nodes: List[LineageNode], edges: List[LineageEdge], tool_type: str,
    ) -> List[LineageEdge]:
        """
        Three-phase correlation:
          A. Match adapter TABLE nodes against inventory by canonical FQN
          B. Bridge edges: for matched tables, redirect adapter edges to warehouse nodes
          C. Match phantom TABLE refs in CROSS edges against inventory
        """
        corr_edges: List[LineageEdge] = []
        adapter_node_ids = {n.id for n in nodes}

        # Pre-register warehouse TABLE nodes (main loop also does this,
        # but this ensures correctness when correlate() is called directly)
        for node in nodes:
            if node.platform_domain == PlatformDomain.WAREHOUSE:
                canonical = _build_canonical(node)
                if canonical:
                    self.ctx.register_table(
                        canonical_fqn=canonical, name=node.name,
                        database=node.database or "", schema=node.schema or "",
                        warehouse_type=_resolve_warehouse_type(node) or tool_type,
                        discovered_by=tool_type, node_id=node.id,
                    )

        # --- Phase A: Match adapter TABLE nodes against inventory ---
        # Maps adapter_table_node_id → warehouse_table_node_id
        node_id_bridge: Dict[str, str] = {}

        for node in nodes:
            if node.platform_domain != PlatformDomain.WAREHOUSE:
                continue

            canonical = _build_canonical(node)
            if not canonical:
                continue

            match = self.ctx.table_inventory.get(canonical)
            if not match or not match.node_id:
                continue

            # Skip self-match (same node ID means same adapter registered it)
            if match.node_id == node.id:
                continue

            node_id_bridge[node.id] = match.node_id
            self.ctx.log_step(
                tool_type,
                f"Table match: {node.name} ({canonical}) → "
                f"warehouse node {match.node_id[:8]}",
            )

        # --- Phase B: Bridge edges through matched TABLE nodes ---
        for edge in edges:
            src_bridge = node_id_bridge.get(edge.source_id)
            tgt_bridge = node_id_bridge.get(edge.target_id)

            if src_bridge and tgt_bridge:
                # Both endpoints map to warehouse nodes — create one
                # fully-bridged edge instead of two partial ones.
                source_ref = f"investigator:bridge:{tool_type}:{edge.discovered_from}"
                corr_edges.append(_make_correlation_edge(
                    src_bridge, tgt_bridge,
                    edge.edge_type, 0.85, source_ref,
                    f"Bridge: {tool_type} both endpoints match warehouse tables",
                ))
                self._record_table_connection(
                    tool_type, src_bridge, is_write=False,
                )
                self._record_table_connection(
                    tool_type, tgt_bridge, is_write=True,
                )
            elif src_bridge:
                # Edge: adapter_table → something
                # Bridge: warehouse_table → something
                source_ref = f"investigator:bridge:{tool_type}:{edge.discovered_from}"
                corr_edges.append(_make_correlation_edge(
                    src_bridge, edge.target_id,
                    edge.edge_type, 0.85, source_ref,
                    f"Bridge: {tool_type} reads from warehouse table",
                ))
                self._record_table_connection(
                    tool_type, src_bridge, is_write=False,
                )
            elif tgt_bridge:
                # Edge: something → adapter_table
                # Bridge: something → warehouse_table
                source_ref = f"investigator:bridge:{tool_type}:{edge.discovered_from}"
                corr_edges.append(_make_correlation_edge(
                    edge.source_id, tgt_bridge,
                    edge.edge_type, 0.85, source_ref,
                    f"Bridge: {tool_type} writes to warehouse table",
                ))
                self._record_table_connection(
                    tool_type, tgt_bridge, is_write=True,
                )

        # --- Phase C: Match phantom TABLE refs in CROSS edges ---
        for edge in edges:
            if edge.plane != LinePlane.CROSS:
                continue

            # Identify phantom end: node ID not in adapter's node set
            phantom_id = None
            real_id = None
            is_write = False

            if edge.source_id not in adapter_node_ids and edge.target_id in adapter_node_ids:
                phantom_id = edge.source_id
                real_id = edge.target_id
                is_write = False  # phantom is source → task reads from table
            elif edge.target_id not in adapter_node_ids and edge.source_id in adapter_node_ids:
                phantom_id = edge.target_id
                real_id = edge.source_id
                is_write = True  # phantom is target → task writes to table

            if not phantom_id or not real_id:
                continue

            # Skip if already bridged in Phase B
            if phantom_id in node_id_bridge:
                continue

            # Parse table ref from discovered_from
            table_ref = _parse_table_ref_from_source(edge.discovered_from)
            if not table_ref:
                continue

            match = self.ctx.find_table_fuzzy(table_ref)
            if match and match.node_id:
                if is_write:
                    src, tgt = real_id, match.node_id
                    edge_type = EdgeType.WRITES_TO
                else:
                    src, tgt = match.node_id, real_id
                    edge_type = EdgeType.READS_FROM

                source_ref = f"investigator:phantom:{tool_type}:{table_ref}"
                corr_edges.append(_make_correlation_edge(
                    src, tgt, edge_type, 0.80, source_ref,
                    f"{tool_type} {'writes to' if is_write else 'reads from'} {match.canonical_fqn}",
                ))
                self._record_table_connection(tool_type, match.node_id, is_write)
            else:
                self.ctx.add_unresolved(
                    reference=table_ref, source_tool=tool_type,
                    ref_type="table_write" if is_write else "table_read",
                    context={"node_id": real_id, "phantom_id": phantom_id},
                )

        # --- Fallback: metadata-based table refs (for future adapters) ---
        for node in nodes:
            if node.platform_domain == PlatformDomain.WAREHOUSE:
                continue
            table_refs = _extract_table_refs(node)
            for ref, is_write in table_refs:
                match = self.ctx.find_table_fuzzy(ref)
                if match and match.node_id:
                    if is_write:
                        src, tgt = node.id, match.node_id
                    else:
                        src, tgt = match.node_id, node.id
                    edge_type = EdgeType.WRITES_TO if is_write else EdgeType.READS_FROM
                    source_ref = f"investigator:metadata:{tool_type}:{ref}"
                    corr_edges.append(_make_correlation_edge(
                        src, tgt, edge_type, 0.85, source_ref,
                        f"{tool_type} {node.name} {'writes to' if is_write else 'reads from'} {match.canonical_fqn}",
                    ))
                    self._record_table_connection(tool_type, match.node_id, is_write)
                else:
                    self.ctx.add_unresolved(
                        reference=ref, source_tool=tool_type,
                        ref_type="table_write" if is_write else "table_read",
                        context={"node_id": node.id, "node_name": node.name},
                    )

        return corr_edges

    def _record_table_connection(
        self, tool_type: str, warehouse_node_id: str, is_write: bool,
    ):
        """Record a tool-to-tool connection via a shared warehouse table."""
        # Find the warehouse tool that owns this table
        warehouse_tool = "unknown"
        for rec in self.ctx.table_inventory.values():
            if rec.node_id == warehouse_node_id and rec.discovered_by:
                warehouse_tool = rec.discovered_by[0]
                if is_write and tool_type not in rec.written_by:
                    rec.written_by.append(tool_type)
                elif not is_write and tool_type not in rec.read_by:
                    rec.read_by.append(tool_type)
                break

        conn_type = "writes_to" if is_write else "reads_from"
        self.ctx.record_connection(
            source_tool=tool_type if is_write else warehouse_tool,
            target_tool=warehouse_tool if is_write else tool_type,
            connection_type=conn_type,
            evidence_summary=f"{tool_type} {conn_type.replace('_', ' ')} {warehouse_tool}",
            confidence=0.85,
        )

    # ---- strategy 2: connection strings ----

    def _correlate_connection_strings(
        self, nodes: List[LineageNode], tool_type: str,
    ) -> List[LineageEdge]:
        for node in nodes:
            conn_info = _extract_connection_info(node)
            if not conn_info:
                continue
            for prof_key, profile in self.ctx.tool_profiles.items():
                if profile.category != ToolCategory.WAREHOUSE:
                    continue
                for known_conn in profile.connection_strings:
                    if _connection_matches(conn_info, known_conn):
                        self.ctx.record_connection(
                            source_tool=tool_type, target_tool=profile.tool_type,
                            connection_type="connects_to",
                            evidence_summary=(
                                f"{tool_type} connects to {profile.tool_type} "
                                f"via {conn_info.get('host', '?')}:{conn_info.get('port', '?')}"
                            ),
                            confidence=0.9,
                        )
                        self.ctx.log_step(
                            tool_type,
                            f"Connection string match: connects to {profile.tool_type}",
                        )
        return []

    # ---- strategy 3: schedule alignment ----

    def _correlate_schedules(
        self, nodes: List[LineageNode], tool_type: str,
    ) -> List[LineageEdge]:
        for node in nodes:
            schedule = (
                node.raw_metadata.get("schedule")
                or node.raw_metadata.get("schedule_interval")
            )
            if not schedule:
                continue
            for prof_key, profile in self.ctx.tool_profiles.items():
                for known_sched in profile.schedules:
                    score = _schedule_alignment_score(schedule, known_sched)
                    if score > 0.7:
                        self.ctx.record_connection(
                            source_tool=tool_type, target_tool=profile.tool_type,
                            connection_type="orchestrates",
                            evidence_summary=(
                                f"{tool_type} schedule '{schedule}' aligns with "
                                f"{profile.tool_type} (score: {score:.0%})"
                            ),
                            confidence=score * 0.8,
                        )
        return []

    # ---- strategy 4: retry unresolved ----

    def _retry_unresolved(self, current_tool: str) -> List[LineageEdge]:
        edges: List[LineageEdge] = []
        for unresolved in self.ctx.unresolved:
            if unresolved.resolved:
                continue
            match = self.ctx.find_table_fuzzy(unresolved.reference)
            if not match or not match.node_id:
                continue
            unresolved.resolved = True
            unresolved.resolved_to = match.canonical_fqn

            original_node_id = unresolved.context.get("node_id")
            if not original_node_id:
                continue

            is_write = unresolved.reference_type == "table_write"
            edge_type = EdgeType.WRITES_TO if is_write else EdgeType.READS_FROM
            src = original_node_id if is_write else match.node_id
            tgt = match.node_id if is_write else original_node_id

            source_ref = f"investigator:resolved:{unresolved.source_tool}:{unresolved.reference}"
            edges.append(_make_correlation_edge(
                src, tgt, edge_type, 0.75, source_ref,
                f"Resolved: {unresolved.source_tool} ref '{unresolved.reference}' → {match.canonical_fqn}",
            ))
            self.ctx.log_step(
                current_tool,
                f"Resolved ref from {unresolved.source_tool}: "
                f"'{unresolved.reference}' → {match.canonical_fqn}",
            )
        return edges

    # ---- strategy 5: infrastructure hosting ----

    def _correlate_infrastructure(
        self, nodes: List[LineageNode], tool_type: str, category: ToolCategory,
    ) -> List[LineageEdge]:
        if category != ToolCategory.INFRASTRUCTURE:
            return []
        for node in nodes:
            hosted_services = (
                node.raw_metadata.get("running_services", [])
                + node.raw_metadata.get("hosted_tools", [])
            )
            for service in hosted_services:
                service_lower = service.lower()
                for prof_key, profile in self.ctx.tool_profiles.items():
                    if profile.tool_type.lower() in service_lower:
                        self.ctx.record_connection(
                            source_tool=profile.tool_type,
                            target_tool=tool_type,
                            connection_type="hosted_on",
                            evidence_summary=f"{profile.tool_type} runs on {node.name}",
                            confidence=0.8,
                        )
        return []


# ---------------------------------------------------------------------------
# LineageInvestigator — the orchestrator
# ---------------------------------------------------------------------------

@dataclass
class InvestigationResult:
    success: bool
    context: InvestigationContext
    graph: Optional[LineageGraph] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    duration_ms: int = 0


class LineageInvestigator:
    """
    Sequential, context-accumulating lineage extraction orchestrator.

    Usage::

        investigator = LineageInvestigator()
        result = investigator.run([
            ToolConfig(tool_type="bigquery", config={...}),
            ToolConfig(tool_type="dbt_cloud", config={...}),
            ToolConfig(tool_type="n8n", config={...}),
        ])
    """

    def __init__(
        self,
        registry: Optional[AdapterRegistry] = None,
        resolver_config: Optional[ResolverConfig] = None,
    ):
        from .adapter import create_default_registry
        self.registry = registry or create_default_registry()
        self.resolver_config = resolver_config or ResolverConfig()

    def run(self, tool_configs: List[ToolConfig]) -> InvestigationResult:
        start = time.time()
        context = InvestigationContext(started_at=datetime.utcnow())
        correlation_engine = CorrelationEngine(context)
        errors: List[str] = []

        # Phase 1 — sort by investigation order
        sorted_configs = sorted(tool_configs, key=lambda tc: tc.investigation_order)
        tool_names = [tc.tool_type for tc in sorted_configs]
        context.log_step("investigator", f"Investigation plan: {tool_names}")

        # Pre-compute destination warehouse info for ingestion adapters
        # so Fivetran/Airbyte can generate FQNs that match warehouse nodes.
        _WAREHOUSE_TOOLS = {"bigquery", "snowflake", "postgres", "redshift"}
        _dest_warehouse_info: Dict[str, Any] = {}
        for tc in sorted_configs:
            tl = tc.tool_type.lower()
            if tl in _WAREHOUSE_TOOLS:
                cfg = tc.config or {}
                if not _dest_warehouse_info:
                    # Build nested destination_config that adapters expect
                    dest_cfg: Dict[str, Any] = {"platform": tl}
                    # BigQuery keys
                    for k in ("project_id", "project"):
                        if cfg.get(k):
                            dest_cfg["project_id"] = cfg[k]
                            break
                    # Database (Snowflake/Postgres/Redshift)
                    if cfg.get("database"):
                        dest_cfg["database"] = cfg["database"]
                    # Schema / dataset
                    for k in ("dataset", "default_dataset", "schema"):
                        if cfg.get(k):
                            dest_cfg["dataset"] = cfg[k]
                            break
                    # Snowflake-specific
                    for k in ("account", "region"):
                        if cfg.get(k):
                            dest_cfg[k] = cfg[k]
                    # Postgres/Redshift-specific
                    for k in ("host", "port"):
                        if cfg.get(k):
                            dest_cfg[k] = cfg[k]
                    _dest_warehouse_info = {
                        "destination_config": dest_cfg,
                    }
                break  # use first warehouse found

        # Categories that don't contribute to data lineage
        _SKIP_CATEGORIES: set = set()  # No categories fully skipped
        # Discovery-only: creates nodes with CP metadata but no data lineage
        _DISCOVERY_ONLY_CATEGORIES = {ToolCategory.INFRASTRUCTURE, ToolCategory.VERSION_CONTROL}

        # Phase 2 — sequential extraction with correlation
        for tc in sorted_configs:
            tool_type = tc.tool_type.lower()
            category = tc.category

            if category in _SKIP_CATEGORIES:
                context.log_step(tool_type, f"Skipping {tool_type} ({category.value}) — not part of data lineage")
                continue

            # Infrastructure: discovery only (creates nodes for services/hosts, no lineage)
            if category in _DISCOVERY_ONLY_CATEGORIES:
                try:
                    adapter_type = tc.adapter_type or TOOL_TO_ADAPTER.get(tool_type)
                    if adapter_type:
                        adapter_id = f"{adapter_type}_{tc.integration_id or 'default'}"
                        adapter = self.registry.create(adapter_type, adapter_id)
                        adapter_config = _build_adapter_config(tc)
                        nodes = adapter.discover_assets(adapter_config)
                        context.all_nodes.extend(nodes)
                        context.log_step(tool_type, f"Discovery-only: {len(nodes)} nodes (infrastructure)")
                        context.tool_profiles[tool_type] = ToolProfile(
                            tool_type=tool_type, category=category,
                            integration_id=tc.integration_id,
                            node_count=len(nodes), extraction_success=True,
                        )
                    else:
                        context.log_step(tool_type, f"No adapter for {tool_type}, skipping")
                except Exception as exc:
                    context.log_step(tool_type, f"Discovery failed: {exc}", "warning")
                continue

            context.log_step(tool_type, f"Beginning investigation ({category.value})")

            profile = ToolProfile(
                tool_type=tool_type, category=category,
                integration_id=tc.integration_id,
            )

            try:
                step_start = time.time()

                adapter_type = tc.adapter_type or TOOL_TO_ADAPTER.get(tool_type)
                if not adapter_type:
                    context.log_step(tool_type, f"No adapter for {tool_type}, skipping", "warning")
                    profile.extraction_error = f"No adapter for {tool_type}"
                    context.tool_profiles[tool_type] = profile
                    continue

                adapter_id = f"{adapter_type}_{tc.integration_id or 'default'}"
                adapter = self.registry.create(adapter_type, adapter_id)
                adapter_config = _build_adapter_config(tc)

                # Inject destination warehouse info into ingestion adapters
                if tool_type in ("fivetran", "airbyte") and _dest_warehouse_info:
                    adapter_config.update(_dest_warehouse_info)

                nodes = adapter.discover_assets(adapter_config)
                edges = adapter.extract_lineage(adapter_config)

                profile.node_count = len(nodes)
                profile.edge_count = len(edges)
                profile.extraction_success = True
                profile.extraction_duration_ms = int((time.time() - step_start) * 1000)

                context.log_step(
                    tool_type,
                    f"Extracted {len(nodes)} nodes, {len(edges)} edges "
                    f"in {profile.extraction_duration_ms}ms",
                )

                # Register warehouse tables in inventory
                for node in nodes:
                    if node.platform_domain == PlatformDomain.WAREHOUSE:
                        canonical = _build_canonical(node)
                        if canonical:
                            context.register_table(
                                canonical_fqn=canonical, name=node.name,
                                database=node.database or "",
                                schema=node.schema or "",
                                warehouse_type=_resolve_warehouse_type(node) or tool_type,
                                discovered_by=tool_type, node_id=node.id,
                                columns=node.columns, row_count=node.row_count,
                            )

                # Enrich tool profile
                _update_tool_profile(profile, nodes, edges)

                # Run correlation engine
                corr_edges = correlation_engine.correlate(nodes, edges, tool_type, category)
                unresolved_count = len([u for u in context.unresolved if not u.resolved])
                context.log_step(
                    tool_type,
                    f"Correlation: {len(corr_edges)} new edges, "
                    f"{unresolved_count} unresolved refs remaining",
                )

                # Absorb into context
                context.all_nodes.extend(nodes)
                context.all_edges.extend(edges)
                context.correlation_edges.extend(corr_edges)
                context.tool_profiles[tool_type] = profile

            except Exception as exc:
                import traceback
                traceback.print_exc()
                error_msg = f"{tool_type}: {exc}"
                errors.append(error_msg)
                profile.extraction_error = str(exc)
                context.tool_profiles[tool_type] = profile
                context.log_step(tool_type, f"Failed: {exc}", "error")

        # Phase 3 — final pass on unresolved references
        context.log_step("investigator", "Running final unresolved reference pass")
        final_edges = correlation_engine._retry_unresolved("final_pass")
        context.correlation_edges.extend(final_edges)
        resolved_count = len([u for u in context.unresolved if u.resolved])
        remaining = len([u for u in context.unresolved if not u.resolved])
        context.log_step(
            "investigator",
            f"Final pass: {resolved_count} resolved, {remaining} still unresolved",
        )

        # Phase 4 — resolve + dedup via existing pipeline
        all_edges = context.all_edges + context.correlation_edges
        pipeline = ResolverPipeline(self.resolver_config)
        graph = pipeline.resolve(list(context.all_nodes), list(all_edges))
        graph.built_at = datetime.utcnow()

        context.completed_at = datetime.utcnow()
        duration_ms = int((time.time() - start) * 1000)

        context.log_step(
            "investigator",
            f"Investigation complete: {len(graph.nodes)} nodes, {len(graph.edges)} edges, "
            f"{len(context.connections)} tool connections in {duration_ms}ms",
        )

        return InvestigationResult(
            success=len(errors) < len(sorted_configs),
            context=context,
            graph=graph,
            stats={
                "total_nodes": len(graph.nodes),
                "total_edges": len(graph.edges),
                "tools_examined": len(context.tool_profiles),
                "tools_succeeded": len([p for p in context.tool_profiles.values() if p.extraction_success]),
                "tables_discovered": len(context.table_inventory),
                "connections_found": len(context.connections),
                "correlations_created": len(context.correlation_edges),
                "unresolved_remaining": remaining,
            },
            errors=errors,
            duration_ms=duration_ms,
        )

    async def run_with_llm(
        self,
        tool_configs: List[ToolConfig],
        use_llm_planner: bool = True,
        use_llm_reconciler: bool = True,
        llm_provider: str = "anthropic",
        llm_model: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        last_diagnostics: Optional[Dict[str, Any]] = None,
    ) -> InvestigationResult:
        """
        Enhanced investigation with LLM-in-the-loop.

        1. LLM planner determines adapter execution order
        2. Standard investigation runs with that order
        3. Deterministic bridge rules fix structural gaps
        4. LLM reconciler reviews graph and proposes patches
        5. Patches are validated and applied

        Falls back to heuristic ordering and deterministic-only
        bridge rules if LLM calls fail.
        """
        from .canonical import canonicalize_graph_in_place
        from .reconciler import ReconcilerConfig, ReconciliationEngine

        # Phase 1: Plan extraction order
        if use_llm_planner:
            try:
                integrations = [
                    {
                        "tool_type": tc.tool_type,
                        "integration_id": tc.integration_id,
                        "layer": tc.layer,
                    }
                    for tc in tool_configs
                ]
                planner_input = PlannerInput(
                    integrations=integrations,
                    last_diagnostics=last_diagnostics,
                )
                plan = await plan_with_llm(
                    planner_input,
                    provider=llm_provider,
                    model=llm_model,
                    api_key=llm_api_key,
                )
                logger.info(
                    "[Investigator] LLM planner order: %s",
                    plan.plan,
                )
                # Reorder tool_configs to match plan
                tool_map = {tc.tool_type.lower(): tc for tc in tool_configs}
                reordered = []
                for tool_name in plan.plan:
                    tc = tool_map.pop(tool_name, None)
                    if tc:
                        reordered.append(tc)
                # Append any not in plan (shouldn't happen but safety)
                reordered.extend(tool_map.values())
                tool_configs = reordered
            except Exception as e:
                logger.warning(
                    "[Investigator] LLM planner failed, using heuristic: %s", e,
                )
        else:
            plan = plan_heuristic([
                {"tool_type": tc.tool_type} for tc in tool_configs
            ])

        # Phase 2: Run standard investigation (uses the ordered configs)
        result = self.run(tool_configs)

        if not result.graph:
            return result

        # Phase 3: Apply deterministic bridge rules
        bridge_engine = BridgeRuleEngine(result.graph)
        bridge_result = bridge_engine.apply_all()
        if bridge_result.total_changes > 0:
            logger.info(
                "[Investigator] Bridge rules: +%d nodes, +%d edges",
                len(bridge_result.added_nodes),
                len(bridge_result.added_edges),
            )
            result.stats["bridge_nodes_added"] = len(bridge_result.added_nodes)
            result.stats["bridge_edges_added"] = len(bridge_result.added_edges)
            result.stats["bridge_rules"] = bridge_result.rules_applied

        # Phase 4: LLM reconciliation pass
        reconciliation_result = None
        if use_llm_reconciler:
            try:
                recon_config = ReconcilerConfig(
                    provider=llm_provider,
                    model=llm_model or "claude-sonnet-4-20250514",
                    api_key=llm_api_key,
                )
                recon_engine = ReconciliationEngine(recon_config)
                reconciliation_result = await recon_engine.reconcile(result.graph)

                if reconciliation_result.success:
                    logger.info(
                        "[Investigator] Reconciliation applied: %s",
                        reconciliation_result.applied,
                    )
                    result.stats["reconciliation"] = reconciliation_result.to_dict()
                else:
                    logger.warning(
                        "[Investigator] Reconciliation failed: %s",
                        reconciliation_result.validation_errors,
                    )
            except Exception as e:
                logger.warning(
                    "[Investigator] LLM reconciler failed: %s", e,
                )
        else:
            # Re-canonicalize after bridge rules (bridge adds nodes/edges
            # that need canonical types applied)
            canonicalize_graph_in_place(result.graph.nodes, result.graph.edges)

        # Store planner info in stats
        result.stats["planner"] = plan.to_dict() if hasattr(plan, "to_dict") else {"source": "heuristic"}

        return result


# ---------------------------------------------------------------------------
# Pure helper functions (module-level, no state)
# ---------------------------------------------------------------------------

def _resolve_warehouse_type(node: LineageNode) -> str:
    """Determine the actual warehouse type for a node, regardless of which adapter created it."""
    platform = (node.platform or "").lower()
    if platform in WAREHOUSE_PLATFORMS:
        return platform
    # dbt/airflow nodes know their target warehouse
    wh_type = (node.raw_metadata.get("warehouse_type") or "").lower()
    if wh_type in WAREHOUSE_PLATFORMS:
        return wh_type
    return ""


def _build_canonical(node: LineageNode) -> Optional[str]:
    """
    Build platform-agnostic canonical FQN: 'db.schema.name' (all lowercase).

    Unlike the old version that used node.platform as prefix, this produces
    the same FQN regardless of which adapter discovered the table, enabling
    cross-tool matching (e.g., dbt source matches BigQuery table).
    """
    if not node.name:
        return None
    parts = [
        p.lower().strip()
        for p in [node.database or "", node.schema or "", node.name]
        if p and p.strip()
    ]
    return ".".join(parts) if parts else None


def _parse_table_ref_from_source(discovered_from: str) -> Optional[str]:
    """
    Extract table reference from an edge's discovered_from field.

    Patterns handled:
      "n8n:workflow:{id}:node:{name}:writes:{table_ref}"
      "n8n:workflow:{id}:node:{name}:reads:{table_ref}"
      "airflow:dag:{id}:task:{name}:{reads|writes}:{table_ref}"
      "openlineage:run:{id}:input:{table_ref}"
      "openlineage:run:{id}:output:{table_ref}"
    """
    if not discovered_from:
        return None
    parts = discovered_from.split(":")
    for i, part in enumerate(parts):
        if part in ("reads", "writes", "input", "output") and i + 1 < len(parts):
            ref = ":".join(parts[i + 1:])
            # Clean up common SQL identifier quoting
            ref = ref.replace("`", "").replace('"', "").replace("[", "").replace("]", "")
            return ref if ref else None
    return None


def _extract_table_refs(node: LineageNode) -> List[Tuple[str, bool]]:
    """Extract (table_ref, is_write) from a node's raw_metadata."""
    refs: List[Tuple[str, bool]] = []
    meta = node.raw_metadata

    for inp in meta.get("inputs", []):
        refs.append((inp, False))
    for out in meta.get("outputs", []):
        refs.append((out, True))
    for ref in meta.get("table_references", []):
        refs.append((ref, False))

    # DB node params (n8n, Airflow)
    table = meta.get("table") or meta.get("tableName")
    if table:
        schema_name = meta.get("schema") or meta.get("schemaName") or ""
        full_ref = f"{schema_name}.{table}" if schema_name else table
        operation = (meta.get("operation") or "select").lower()
        is_write = operation in ("insert", "update", "upsert", "delete", "create")
        refs.append((full_ref, is_write))

    return refs


def _extract_connection_info(node: LineageNode) -> Optional[Dict[str, Any]]:
    meta = node.raw_metadata
    host = meta.get("host") or meta.get("hostname") or meta.get("server")
    if host:
        return {
            "host": host,
            "port": meta.get("port"),
            "database": meta.get("database") or meta.get("db"),
        }
    return None


def _connection_matches(a: Dict, b: Dict) -> bool:
    if a.get("host") and b.get("host"):
        hosts_eq = a["host"].lower() == b["host"].lower()
        ports_eq = not a.get("port") or not b.get("port") or str(a["port"]) == str(b["port"])
        return hosts_eq and ports_eq
    return False


def _schedule_alignment_score(s1: Any, s2: Dict) -> float:
    a = str(s1).lower()
    b = str(s2.get("schedule", "")).lower()
    if a == b:
        return 1.0
    if "daily" in a and "daily" in b:
        return 0.8
    if "0 * * * *" in a and "0 * * * *" in b:
        return 0.7
    return 0.0


def _make_correlation_edge(
    source_id: str, target_id: str, edge_type: EdgeType,
    confidence: float, source_ref: str, snippet: str,
) -> LineageEdge:
    ev = Evidence(
        adapter_id="investigator",
        source_ref=source_ref,
        observed_at=datetime.utcnow(),
        snippet=snippet[:200],
    )
    edge_id = generate_edge_id(
        source_id, target_id,
        edge_type.value, LineageLevel.TABLE.value,
        source_ref,
    )
    return LineageEdge(
        id=edge_id, source_id=source_id, target_id=target_id,
        edge_type=edge_type, lineage_level=LineageLevel.TABLE,
        confidence=confidence, discovered_from=source_ref,
        discovered_at=datetime.utcnow(), evidence=[ev],
        plane=LinePlane.CROSS,
        inferred=True,
    )


def _build_adapter_config(tc: ToolConfig) -> Dict[str, Any]:
    """Wrap raw config into the format each adapter expects."""
    config = dict(tc.config)
    config["integration_id"] = tc.integration_id
    tool_lower = tc.tool_type.lower()

    if tool_lower in ("bigquery", "snowflake", "postgres", "redshift"):
        config["platform"] = tool_lower
        config.setdefault("connection_config", tc.config)
    elif tool_lower in ("dbt_cloud", "dbt_core"):
        config.setdefault("warehouse_type", "bigquery")
    elif tool_lower == "n8n":
        config.setdefault("n8n_config", tc.config)
    elif tool_lower == "fivetran":
        config.setdefault("fivetran_config", tc.config)
    elif tool_lower == "airbyte":
        config.setdefault("airbyte_config", tc.config)
    elif tool_lower == "looker":
        config.setdefault("looker_config", tc.config)
    elif tool_lower == "tableau":
        config.setdefault("tableau_config", tc.config)
    elif tool_lower == "powerbi":
        config.setdefault("powerbi_config", tc.config)
    elif tool_lower == "metabase":
        config.setdefault("metabase_config", tc.config)
    elif tool_lower == "airflow":
        # source_mode takes priority: user may have BOTH host and github_repo
        # in config but chose a specific mode in the UI.
        source_mode = (tc.config.get("source_mode") or "").lower()
        base_url = tc.config.get("base_url") or tc.config.get("host") or tc.config.get("url")

        if source_mode == "api" or (base_url and source_mode not in ("github", "static")):
            config["mode"] = "api"
            config["base_url"] = base_url
            config.setdefault("username", tc.config.get("username") or tc.config.get("user"))
            config.setdefault("password", tc.config.get("password"))
        else:
            config["mode"] = "static"
            config.setdefault("dag_directory", tc.config.get("dag_directory", "dags"))
    elif tool_lower in ("linux_server", "ssh"):
        config.setdefault("hostname", tc.config.get("host") or tc.config.get("hostname"))
    elif tool_lower in ("github", "gitlab"):
        pass  # stub adapter, no special config needed

    return config


def _update_tool_profile(
    profile: ToolProfile, nodes: List[LineageNode], edges: List[LineageEdge],
) -> None:
    for node in nodes:
        schedule = (
            node.raw_metadata.get("schedule")
            or node.raw_metadata.get("schedule_interval")
        )
        if schedule:
            profile.schedules.append({"schedule": schedule, "node": node.name})

        host = (
            node.raw_metadata.get("host")
            or node.raw_metadata.get("hostname")
        )
        if host:
            profile.connection_strings.append({
                "host": host,
                "port": node.raw_metadata.get("port"),
                "database": node.raw_metadata.get("database"),
            })

    for edge in edges:
        if edge.edge_type in (EdgeType.WRITES_TO, EdgeType.POPULATES):
            profile.tables_written.append(edge.target_id)
        elif edge.edge_type in (EdgeType.READS_FROM, EdgeType.DERIVED_FROM):
            profile.tables_read.append(edge.source_id)
