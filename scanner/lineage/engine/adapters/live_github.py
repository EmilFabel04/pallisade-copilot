"""
Live GitHub Adapter — stub for future GitHub-based lineage discovery.

This adapter is a placeholder. GitHub lineage (e.g. code-level data asset
references, CI/CD pipeline discovery) is planned but not yet implemented.
"""

import logging
from typing import Any, Dict, List, Set

from ...graph import (
    LineageEdge,
    LineageNode,
)
from ..adapter import BaseLineageAdapter, Capability

logger = logging.getLogger(__name__)


class LiveGithubAdapter(BaseLineageAdapter):
    """Stub adapter for GitHub lineage (future feature)."""

    def __init__(self, adapter_id: str = "live_github", **kwargs):
        self._id = adapter_id

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {Capability.DISCOVER_ASSETS}

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        logger.info("[LiveGithub] GitHub adapter is a stub — no assets discovered")
        return []

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        return []
