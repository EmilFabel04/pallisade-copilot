"""
Tests for scanner.lineage.engine.indexes

Covers:
- ProducerIndex from small graph (service → job → dataset)
- Evidence pointers preserved
- Confidence matches writes edge
- No producers for dataset with only reads edges
- Serialization round-trip
"""

import pytest

from scanner.lineage.graph import (
    EdgeType,
    Evidence,
    LineageEdge,
    LineageGraph,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.canonical import canonicalize_graph_in_place
from scanner.lineage.engine.indexes import build_producer_index, ProducerIndex, ProducerRef


# ---- Helpers ----

def _make_node(
    name: str,
    node_type: NodeType,
    platform: str,
    platform_domain: PlatformDomain,
    **kwargs,
) -> LineageNode:
    return LineageNode(
        id=f"node:{platform}:{name}",
        name=name,
        fqn=kwargs.get("fqn", name),
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        database=kwargs.get("database"),
        schema=kwargs.get("schema"),
        integration_id=kwargs.get("integration_id"),
    )


def _make_edge(
    source_id: str,
    target_id: str,
    edge_type: EdgeType,
    confidence: float = 1.0,
) -> LineageEdge:
    return LineageEdge(
        id=f"edge:{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        confidence=confidence,
        evidence=[Evidence(adapter_id="test", source_ref="fixture")],
    )


# ---- Fixtures ----

@pytest.fixture
def fivetran_graph() -> LineageGraph:
    """Fivetran service → connector job → raw.orders dataset."""
    graph = LineageGraph()

    service = _make_node(
        "fivetran_prod", NodeType.PIPELINE, "fivetran",
        PlatformDomain.INGESTION,
    )
    service.canonical_type = "service"

    connector = _make_node(
        "salesforce_sync", NodeType.CONNECTOR, "fivetran",
        PlatformDomain.INGESTION, integration_id="ft_001",
    )

    dataset = _make_node(
        "orders", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE, database="raw", schema="salesforce",
        fqn="raw.salesforce.orders",
    )

    graph.add_node(service)
    graph.add_node(connector)
    graph.add_node(dataset)

    # service → connector (runs)
    runs_edge = _make_edge(service.id, connector.id, EdgeType.TRIGGERS)
    runs_edge.canonical_edge_type = "runs"
    graph.add_edge(runs_edge)

    # connector → dataset (writes)
    writes_edge = _make_edge(
        connector.id, dataset.id, EdgeType.SYNCS_TO, confidence=0.95,
    )
    writes_edge.canonical_edge_type = "writes"
    graph.add_edge(writes_edge)

    canonicalize_graph_in_place(graph.nodes, graph.edges)
    return graph


# ---- Tests ----

class TestBuildProducerIndex:
    def test_basic_producer(self, fivetran_graph):
        """Correct job_name, service_name, and platform for a single producer."""
        index = build_producer_index(fivetran_graph)
        assert index.total_datasets == 1
        assert index.total_producers == 1

        dataset_id = "node:bigquery:orders"
        assert dataset_id in index.producers_by_dataset
        producer = index.producers_by_dataset[dataset_id][0]
        assert producer.job_name == "salesforce_sync"
        assert producer.service_name == "fivetran_prod"
        assert producer.platform == "fivetran"
        assert producer.integration_id == "ft_001"

    def test_confidence_matches_writes_edge(self, fivetran_graph):
        """Producer confidence should match the writes edge confidence."""
        index = build_producer_index(fivetran_graph)
        producer = list(index.producers_by_dataset.values())[0][0]
        assert producer.confidence == 0.95

    def test_evidence_refs_point_to_writes_edge(self, fivetran_graph):
        """Evidence refs should contain the writes edge ID."""
        index = build_producer_index(fivetran_graph)
        producer = list(index.producers_by_dataset.values())[0][0]
        assert len(producer.evidence_refs) == 1
        assert "edge:" in producer.evidence_refs[0]

    def test_no_producers_for_reads_only_dataset(self):
        """A dataset with only incoming reads (no writes) has no producers."""
        graph = LineageGraph()
        dataset = _make_node(
            "events", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, fqn="raw.events",
        )
        dashboard = _make_node(
            "dashboard", NodeType.DASHBOARD, "looker",
            PlatformDomain.BI,
        )
        graph.add_node(dataset)
        graph.add_node(dashboard)
        edge = _make_edge(dataset.id, dashboard.id, EdgeType.READS_FROM)
        graph.add_edge(edge)
        canonicalize_graph_in_place(graph.nodes, graph.edges)

        index = build_producer_index(graph)
        assert index.total_producers == 0
        assert index.total_datasets == 0

    def test_multiple_producers_for_one_dataset(self):
        """A dataset written to by two jobs should have two producers."""
        graph = LineageGraph()

        job1 = _make_node(
            "job_a", NodeType.CONNECTOR, "fivetran",
            PlatformDomain.INGESTION,
        )
        job2 = _make_node(
            "job_b", NodeType.TASK, "airflow",
            PlatformDomain.ORCHESTRATION,
        )
        dataset = _make_node(
            "shared_table", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, fqn="raw.shared_table",
        )
        graph.add_node(job1)
        graph.add_node(job2)
        graph.add_node(dataset)

        e1 = _make_edge(job1.id, dataset.id, EdgeType.SYNCS_TO, confidence=0.9)
        e1.canonical_edge_type = "writes"
        e2 = _make_edge(job2.id, dataset.id, EdgeType.WRITES_TO, confidence=0.8)
        e2.canonical_edge_type = "writes"
        graph.add_edge(e1)
        graph.add_edge(e2)

        canonicalize_graph_in_place(graph.nodes, graph.edges)

        index = build_producer_index(graph)
        assert index.total_datasets == 1
        assert index.total_producers == 2

        producers = index.producers_by_dataset[dataset.id]
        platforms = {p.platform for p in producers}
        assert "fivetran" in platforms
        assert "airflow" in platforms

    def test_service_not_found_gracefully(self):
        """When there is no runs edge to a service, service fields are None."""
        graph = LineageGraph()

        job = _make_node(
            "orphan_job", NodeType.TASK, "airflow",
            PlatformDomain.ORCHESTRATION,
        )
        dataset = _make_node(
            "target", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE, fqn="raw.target",
        )
        graph.add_node(job)
        graph.add_node(dataset)

        edge = _make_edge(job.id, dataset.id, EdgeType.WRITES_TO)
        edge.canonical_edge_type = "writes"
        graph.add_edge(edge)

        canonicalize_graph_in_place(graph.nodes, graph.edges)

        index = build_producer_index(graph)
        assert index.total_producers == 1
        producer = list(index.producers_by_dataset.values())[0][0]
        assert producer.service_id is None
        assert producer.service_name is None

    def test_serialization_round_trip(self, fivetran_graph):
        """to_dict() returns correct shape with camelCase keys."""
        index = build_producer_index(fivetran_graph)
        d = index.to_dict()
        assert isinstance(d, dict)
        for dataset_id, producers in d.items():
            assert isinstance(producers, list)
            for p in producers:
                assert "jobId" in p
                assert "jobName" in p
                assert "confidence" in p
                assert "evidenceRefs" in p
                assert "platform" in p

    def test_empty_graph(self):
        """Empty graph produces empty index."""
        graph = LineageGraph()
        index = build_producer_index(graph)
        assert index.total_datasets == 0
        assert index.total_producers == 0
        assert index.to_dict() == {}
