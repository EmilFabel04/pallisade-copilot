"""
OpenLineage Event Consumer

Consumes OpenLineage events from Airflow, Dagster, Spark, etc.
and updates the unified lineage graph.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
import json
import hashlib

from lineage.graph import LineageGraph, LineageNode, LineageEdge, NodeType, EdgeType

logger = logging.getLogger(__name__)


@dataclass
class OpenLineageDataset:
    """Represents an OpenLineage dataset (input or output)."""
    namespace: str
    name: str
    facets: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def qualified_name(self) -> str:
        """Get fully qualified name."""
        return f"{self.namespace}.{self.name}"
    
    @property
    def schema_facet(self) -> Optional[Dict[str, Any]]:
        """Get schema facet if present."""
        return self.facets.get("schema")
    
    @property
    def columns(self) -> List[Dict[str, str]]:
        """Get columns from schema facet."""
        schema = self.schema_facet
        if schema and "fields" in schema:
            return [
                {"name": f.get("name"), "type": f.get("type")}
                for f in schema["fields"]
            ]
        return []


@dataclass
class OpenLineageJob:
    """Represents an OpenLineage job."""
    namespace: str
    name: str
    facets: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def qualified_name(self) -> str:
        """Get fully qualified name."""
        return f"{self.namespace}.{self.name}"
    
    @property
    def sql_facet(self) -> Optional[str]:
        """Get SQL from facets."""
        sql = self.facets.get("sql")
        if sql and isinstance(sql, dict):
            return sql.get("query")
        return None


@dataclass
class OpenLineageRun:
    """Represents an OpenLineage run."""
    run_id: str
    facets: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def nominal_time(self) -> Optional[datetime]:
        """Get nominal start time."""
        facet = self.facets.get("nominalTime")
        if facet and "nominalStartTime" in facet:
            try:
                return datetime.fromisoformat(facet["nominalStartTime"].replace("Z", "+00:00"))
            except:
                pass
        return None
    
    @property
    def error_message(self) -> Optional[str]:
        """Get error message if run failed."""
        facet = self.facets.get("errorMessage")
        if facet and isinstance(facet, dict):
            return facet.get("message")
        return None


@dataclass
class OpenLineageEvent:
    """An OpenLineage event."""
    event_type: str  # START, COMPLETE, FAIL, ABORT
    event_time: datetime
    job: OpenLineageJob
    run: OpenLineageRun
    inputs: List[OpenLineageDataset] = field(default_factory=list)
    outputs: List[OpenLineageDataset] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenLineageEvent":
        """Create from dictionary (e.g., from JSON)."""
        job_data = data.get("job", {})
        run_data = data.get("run", {})
        
        return cls(
            event_type=data.get("eventType", "UNKNOWN"),
            event_time=datetime.fromisoformat(
                data.get("eventTime", datetime.now().isoformat()).replace("Z", "+00:00")
            ),
            job=OpenLineageJob(
                namespace=job_data.get("namespace", ""),
                name=job_data.get("name", ""),
                facets=job_data.get("facets", {}),
            ),
            run=OpenLineageRun(
                run_id=run_data.get("runId", ""),
                facets=run_data.get("facets", {}),
            ),
            inputs=[
                OpenLineageDataset(
                    namespace=ds.get("namespace", ""),
                    name=ds.get("name", ""),
                    facets=ds.get("facets", {}),
                )
                for ds in data.get("inputs", [])
            ],
            outputs=[
                OpenLineageDataset(
                    namespace=ds.get("namespace", ""),
                    name=ds.get("name", ""),
                    facets=ds.get("facets", {}),
                )
                for ds in data.get("outputs", [])
            ],
        )


class OpenLineageConsumer:
    """
    Consumes OpenLineage events and updates the lineage graph.
    
    OpenLineage is a standard for data lineage metadata.
    Tools like Airflow, Dagster, and Spark can emit these events.
    """
    
    def __init__(self, db_session=None):
        self.db = db_session
    
    async def process_event(
        self,
        event_data: Dict[str, Any],
        org_id: str,
    ) -> bool:
        """
        Process an incoming OpenLineage event.
        
        Args:
            event_data: The raw event data (JSON)
            org_id: Organization ID
            
        Returns:
            True if processed successfully
        """
        try:
            # Parse event
            event = OpenLineageEvent.from_dict(event_data)
            
            logger.info(
                f"Processing OpenLineage event: {event.event_type} "
                f"for job {event.job.qualified_name}"
            )
            
            # Store raw event
            await self._store_event(event, org_id)
            
            # Only process COMPLETE events for lineage
            # (START and FAIL don't have final lineage info)
            if event.event_type == "COMPLETE":
                await self._update_lineage(event, org_id)
            
            return True
            
        except Exception as e:
            logger.exception(f"Error processing OpenLineage event: {e}")
            return False
    
    async def _store_event(
        self,
        event: OpenLineageEvent,
        org_id: str,
    ) -> None:
        """Store the raw event in the database."""
        if not self.db:
            return
        
        # TODO: Insert into LineageEvent table
        # await self.db.execute(
        #     """
        #     INSERT INTO "LineageEvent" (
        #         id, "eventType", "eventTime", "jobNamespace", "jobName",
        #         "runId", inputs, outputs, "jobFacets", "runFacets",
        #         "organizationId", "createdAt"
        #     ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        #     """,
        #     generate_id(),
        #     event.event_type,
        #     event.event_time,
        #     event.job.namespace,
        #     event.job.name,
        #     event.run.run_id,
        #     json.dumps([ds.__dict__ for ds in event.inputs]),
        #     json.dumps([ds.__dict__ for ds in event.outputs]),
        #     json.dumps(event.job.facets),
        #     json.dumps(event.run.facets),
        #     org_id,
        #     datetime.now(),
        # )
        pass
    
    async def _update_lineage(
        self,
        event: OpenLineageEvent,
        org_id: str,
    ) -> None:
        """Update the lineage graph from an event."""
        
        # Create/update nodes for inputs
        for input_ds in event.inputs:
            await self._upsert_node(
                input_ds,
                org_id,
                node_type=NodeType.TABLE,
            )
        
        # Create/update nodes for outputs
        for output_ds in event.outputs:
            await self._upsert_node(
                output_ds,
                org_id,
                node_type=NodeType.TABLE,
            )
        
        # Create job node
        job_node_id = await self._upsert_job_node(event.job, org_id)
        
        # Create edges: inputs -> job
        for input_ds in event.inputs:
            await self._upsert_edge(
                source_id=self._node_id(input_ds.namespace, input_ds.name),
                target_id=job_node_id,
                edge_type=EdgeType.READS_FROM,
                org_id=org_id,
            )
        
        # Create edges: job -> outputs
        for output_ds in event.outputs:
            await self._upsert_edge(
                source_id=job_node_id,
                target_id=self._node_id(output_ds.namespace, output_ds.name),
                edge_type=EdgeType.WRITES_TO,
                org_id=org_id,
            )
        
        # Create direct edges: inputs -> outputs (for simpler lineage view)
        for input_ds in event.inputs:
            for output_ds in event.outputs:
                await self._upsert_edge(
                    source_id=self._node_id(input_ds.namespace, input_ds.name),
                    target_id=self._node_id(output_ds.namespace, output_ds.name),
                    edge_type=EdgeType.DERIVED_FROM,
                    org_id=org_id,
                    transformation=event.job.sql_facet,
                )
    
    async def _upsert_node(
        self,
        dataset: OpenLineageDataset,
        org_id: str,
        node_type: NodeType = NodeType.TABLE,
    ) -> str:
        """Create or update a lineage node."""
        node_id = self._node_id(dataset.namespace, dataset.name)
        
        # Parse name to extract database/schema/table
        parts = dataset.name.split(".")
        database = parts[0] if len(parts) >= 1 else None
        schema = parts[1] if len(parts) >= 2 else None
        table_name = parts[-1]
        
        # Extract platform from namespace
        platform = self._extract_platform(dataset.namespace)
        
        # TODO: Upsert to database
        # await self.db.execute(...)
        
        return node_id
    
    async def _upsert_job_node(
        self,
        job: OpenLineageJob,
        org_id: str,
    ) -> str:
        """Create or update a job node."""
        node_id = self._node_id(job.namespace, job.name)
        
        # Determine node type from namespace
        node_type = NodeType.TASK
        if "airflow" in job.namespace.lower():
            node_type = NodeType.TASK
        elif "dagster" in job.namespace.lower():
            node_type = NodeType.PIPELINE
        elif "spark" in job.namespace.lower():
            node_type = NodeType.PIPELINE
        
        # TODO: Upsert to database
        
        return node_id
    
    async def _upsert_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        org_id: str,
        transformation: Optional[str] = None,
    ) -> None:
        """Create or update a lineage edge."""
        edge_id = self._edge_id(source_id, target_id)
        
        # TODO: Upsert to database
        pass
    
    def _node_id(self, namespace: str, name: str) -> str:
        """Generate a stable node ID."""
        return hashlib.md5(f"{namespace}.{name}".encode()).hexdigest()[:16]
    
    def _edge_id(self, source_id: str, target_id: str) -> str:
        """Generate a stable edge ID."""
        return hashlib.md5(f"{source_id}->{target_id}".encode()).hexdigest()[:16]
    
    def _extract_platform(self, namespace: str) -> str:
        """Extract platform name from namespace."""
        namespace_lower = namespace.lower()
        
        if "snowflake" in namespace_lower:
            return "snowflake"
        elif "bigquery" in namespace_lower:
            return "bigquery"
        elif "postgres" in namespace_lower:
            return "postgres"
        elif "redshift" in namespace_lower:
            return "redshift"
        elif "airflow" in namespace_lower:
            return "airflow"
        elif "dagster" in namespace_lower:
            return "dagster"
        elif "spark" in namespace_lower:
            return "spark"
        else:
            return "unknown"
    
    def event_to_graph(self, event: OpenLineageEvent) -> LineageGraph:
        """
        Convert an OpenLineage event to a LineageGraph fragment.
        
        Useful for testing or visualization.
        """
        graph = LineageGraph()
        
        # Add input nodes
        for input_ds in event.inputs:
            node = LineageNode(
                id=self._node_id(input_ds.namespace, input_ds.name),
                name=input_ds.name,
                fqn=input_ds.qualified_name,
                node_type=NodeType.TABLE,
                platform=self._extract_platform(input_ds.namespace),
                columns=[
                    {"name": c["name"], "type": c.get("type")}
                    for c in input_ds.columns
                ],
            )
            graph.add_node(node)
        
        # Add output nodes
        for output_ds in event.outputs:
            node = LineageNode(
                id=self._node_id(output_ds.namespace, output_ds.name),
                name=output_ds.name,
                fqn=output_ds.qualified_name,
                node_type=NodeType.TABLE,
                platform=self._extract_platform(output_ds.namespace),
                columns=[
                    {"name": c["name"], "type": c.get("type")}
                    for c in output_ds.columns
                ],
            )
            graph.add_node(node)
        
        # Add job node
        job_node = LineageNode(
            id=self._node_id(event.job.namespace, event.job.name),
            name=event.job.name,
            fqn=event.job.qualified_name,
            node_type=NodeType.TASK,
            platform=self._extract_platform(event.job.namespace),
            description=event.job.sql_facet,
        )
        graph.add_node(job_node)
        
        # Add edges
        for input_ds in event.inputs:
            edge = LineageEdge(
                id=self._edge_id(
                    self._node_id(input_ds.namespace, input_ds.name),
                    job_node.id
                ),
                source_id=self._node_id(input_ds.namespace, input_ds.name),
                target_id=job_node.id,
                edge_type=EdgeType.READS_FROM,
                discovered_from="openlineage",
            )
            graph.add_edge(edge)
        
        for output_ds in event.outputs:
            edge = LineageEdge(
                id=self._edge_id(job_node.id, self._node_id(output_ds.namespace, output_ds.name)),
                source_id=job_node.id,
                target_id=self._node_id(output_ds.namespace, output_ds.name),
                edge_type=EdgeType.WRITES_TO,
                discovered_from="openlineage",
            )
            graph.add_edge(edge)
        
        return graph
