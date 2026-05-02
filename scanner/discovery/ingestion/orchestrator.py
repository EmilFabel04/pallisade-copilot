# scanner/discovery/ingestion/orchestrator.py
from typing import List, Optional, Tuple
from scanner.discovery.types import DatasetCandidate, DiscoveryError


class IngestionDiscoverer:
    def discover(self, base_url: str, hints: List[str]) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        return [], DiscoveryError(code='no_connectors_connected', message='ingestion discovery not yet implemented')
