# scanner/discovery/source_discovery.py
from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional, Protocol, Tuple

from scanner.discovery.types import DatasetCandidate, DiscoveryError, DiscoveryResult, PathName

logger = logging.getLogger(__name__)


class _PathDiscoverer(Protocol):
    def discover(self, **kwargs: Any) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]: ...


class SourceDiscoveryOrchestrator:
    def __init__(
        self,
        probe_discoverer: _PathDiscoverer,
        warehouse_discoverer: _PathDiscoverer,
        ingestion_discoverer: _PathDiscoverer,
    ):
        self._probe = probe_discoverer
        self._warehouse = warehouse_discoverer
        self._ingestion = ingestion_discoverer

    async def discover(
        self,
        base_url: str,
        endpoint: str,
        auth: Dict[str, Any],
        warehouse_hints: Optional[List[str]] = None,
        ingestion_hints: Optional[List[str]] = None,
    ) -> DiscoveryResult:
        loop = asyncio.get_running_loop()

        async def _run(path: PathName, fn, **kwargs):
            try:
                candidates, error = await loop.run_in_executor(None, lambda: fn(**kwargs))
                return path, candidates, error
            except Exception as e:
                logger.exception("discovery path %s raised", path)
                return path, [], DiscoveryError(code='unknown', message=str(e))

        results = await asyncio.gather(
            _run('probe', self._probe.discover, base_url=base_url, endpoint=endpoint, auth=auth),
            _run('warehouse', self._warehouse.discover, hints=warehouse_hints or []),
            _run('ingestion', self._ingestion.discover, base_url=base_url, hints=ingestion_hints or []),
        )

        candidates_by_path: Dict[PathName, List[DatasetCandidate]] = {}
        errors_by_path: Dict[PathName, Optional[DiscoveryError]] = {}
        for path, candidates, error in results:
            candidates_by_path[path] = candidates
            errors_by_path[path] = error

        return DiscoveryResult(candidates_by_path=candidates_by_path, errors_by_path=errors_by_path)
