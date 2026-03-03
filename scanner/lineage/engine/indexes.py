"""
Producer Index — answers "who writes to this dataset?"

For each dataset node in the canonical graph, identifies the producing
job(s) and the service(s) that run those jobs.  Built after
canonicalization + bridge in the extraction pipeline (step 5.5) and
stored in RunArtifacts so the copilot and UI can look up provenance
without traversing the full graph.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..graph import LineageGraph

logger = logging.getLogger(__name__)


@dataclass
class ProducerRef:
    """A single producer of a dataset."""

    job_id: str
    job_name: str
    service_id: Optional[str] = None
    service_name: Optional[str] = None
    platform: str = ""
    integration_id: Optional[str] = None
    confidence: float = 1.0
    evidence_refs: List[str] = field(default_factory=list)  # edge IDs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jobId": self.job_id,
            "jobName": self.job_name,
            "serviceId": self.service_id,
            "serviceName": self.service_name,
            "platform": self.platform,
            "integrationId": self.integration_id,
            "confidence": self.confidence,
            "evidenceRefs": self.evidence_refs,
        }


@dataclass
class ProducerIndex:
    """Index: dataset_id -> list of ProducerRefs."""

    producers_by_dataset: Dict[str, List[ProducerRef]] = field(
        default_factory=dict,
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            dataset_id: [p.to_dict() for p in producers]
            for dataset_id, producers in self.producers_by_dataset.items()
        }

    @property
    def total_datasets(self) -> int:
        return len(self.producers_by_dataset)

    @property
    def total_producers(self) -> int:
        return sum(len(p) for p in self.producers_by_dataset.values())


def build_producer_index(graph: LineageGraph) -> ProducerIndex:
    """Build the producer index from a canonicalized graph.

    Algorithm:
    1. Find all "runs" edges (service → job) to build a service lookup.
    2. Find all "writes" edges targeting a dataset node.
    3. The source of that writes edge is the producing job.
    4. Look up the job's service via the runs lookup.
    5. Assemble ProducerRef with confidence from the writes edge.
    """
    index = ProducerIndex()

    # Pre-build: service → job lookup via "runs" canonical edges
    service_for_job: Dict[str, str] = {}  # job_id → service_id
    for edge in graph.edges.values():
        if edge.canonical_edge_type == "runs":
            target = graph.nodes.get(edge.target_id)
            if target and target.canonical_type == "job":
                service_for_job[edge.target_id] = edge.source_id

    # Find "writes" edges targeting datasets
    for edge in graph.edges.values():
        if edge.canonical_edge_type != "writes":
            continue
        target = graph.nodes.get(edge.target_id)
        source = graph.nodes.get(edge.source_id)
        if not target or not source:
            continue
        if target.canonical_type != "dataset":
            continue
        if source.canonical_type != "job":
            logger.debug(
                "[ProducerIndex] Skipping writes edge %s: source %s is %s, not job",
                edge.id, source.id, source.canonical_type,
            )
            continue

        # Find the service that runs this job
        service_id = service_for_job.get(source.id)
        service_node = graph.nodes.get(service_id) if service_id else None

        ref = ProducerRef(
            job_id=source.id,
            job_name=source.name,
            service_id=service_id,
            service_name=service_node.name if service_node else None,
            platform=source.platform or "",
            integration_id=source.integration_id,
            confidence=edge.confidence,
            evidence_refs=[edge.id],
        )

        if target.id not in index.producers_by_dataset:
            index.producers_by_dataset[target.id] = []
        index.producers_by_dataset[target.id].append(ref)

    logger.info(
        "[ProducerIndex] Built: %d datasets with %d total producers",
        index.total_datasets, index.total_producers,
    )
    return index
