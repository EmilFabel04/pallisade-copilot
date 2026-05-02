# scanner/discovery/warehouse/warehouse_discoverer.py
from typing import List, Optional, Tuple
from scanner.discovery.types import DatasetCandidate, DiscoveryError


class WarehouseDiscoverer:
    def discover(self, hints: List[str]) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        if not hints:
            return [], DiscoveryError(code='no_warehouse_hint', message='no warehouse hints provided')
        return [], None  # Task 4 fills this in
