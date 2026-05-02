from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List
from scanner.discovery.types import DatasetCandidate


@dataclass(frozen=True)
class ConnectorMatch:
    driver_id: str             # 'fivetran' | 'airbyte' | 'stitch'
    connector_id: str          # ingestion tool's internal ID for this connector
    source_host: str           # the matched host
    raw_config: dict           # the connector's full config (for tests / diagnostics / table listing)


class PerDriverIngestionDiscoverer(ABC):
    """Per-driver adapter for Path 2 (ingestion-anchored discovery).

    Each driver (Fivetran, Airbyte, Stitch, ...) stores connector configs in a
    structurally different shape; this ABC provides the uniform interface the
    orchestrator depends on.
    """

    @abstractmethod
    def driver_id(self) -> str: ...

    @abstractmethod
    def find_matching_connectors(self, host: str) -> List[ConnectorMatch]: ...

    @abstractmethod
    def list_source_tables(self, match: ConnectorMatch) -> List[DatasetCandidate]: ...
