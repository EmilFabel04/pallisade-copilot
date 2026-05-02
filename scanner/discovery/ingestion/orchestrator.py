from __future__ import annotations
import logging
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from scanner.discovery.ingestion.base import PerDriverIngestionDiscoverer
from scanner.discovery.ingestion.fivetran import FivetranIngestionDiscoverer
from scanner.discovery.ingestion.airbyte import AirbyteIngestionDiscoverer
from scanner.discovery.ingestion.stitch import StitchIngestionDiscoverer
from scanner.discovery.types import DatasetCandidate, DiscoveryError

logger = logging.getLogger(__name__)


class IngestionDiscoverer:
    """Path 2 orchestrator — fans out to per-driver discoverers, merges candidates."""

    def __init__(
        self,
        drivers: Optional[List[PerDriverIngestionDiscoverer]] = None,
        org_id: Optional[str] = None,
        stack_id: Optional[str] = None,
    ) -> None:
        self._drivers = drivers or [
            FivetranIngestionDiscoverer(org_id=org_id, stack_id=stack_id),
            AirbyteIngestionDiscoverer(org_id=org_id, stack_id=stack_id),
            StitchIngestionDiscoverer(org_id=org_id, stack_id=stack_id),
        ]

    def discover(self, base_url: str, hints: List[str]) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        host = urlparse(base_url).hostname or ""
        if not host:
            return [], DiscoveryError(code='unknown', message='could not parse host from base_url')

        active_drivers = self._drivers
        if hints:
            active_drivers = [d for d in self._drivers if d.driver_id() in hints]

        all_candidates: List[DatasetCandidate] = []
        any_match = False
        for driver in active_drivers:
            try:
                matches = driver.find_matching_connectors(host=host)
            except Exception as e:
                logger.warning("ingestion driver %s failed: %s", driver.driver_id(), e)
                continue
            if matches:
                any_match = True
            for m in matches:
                try:
                    all_candidates.extend(driver.list_source_tables(m))
                except Exception as e:
                    logger.warning("listing tables for %s/%s failed: %s", driver.driver_id(), m.connector_id, e)

        if not any_match:
            return [], DiscoveryError(
                code='no_connectors_connected',
                message=f'no ingestion connectors found for host {host}',
            )
        return all_candidates, None
