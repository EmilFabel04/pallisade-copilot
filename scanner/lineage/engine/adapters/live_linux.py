"""
Live Linux Server Adapter — represents a monitored Linux server as a lineage
node so infrastructure assets appear in the graph.

This is a discovery-only adapter: it creates a single node per server and
does not extract lineage edges.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Set

from ...graph import (
    AssetKind,
    LineageEdge,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id

logger = logging.getLogger(__name__)


class LiveLinuxAdapter(BaseLineageAdapter):
    """Adapter that exposes a Linux server as a discoverable infrastructure asset."""

    def __init__(self, adapter_id: str = "live_linux", **kwargs):
        self._id = adapter_id

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {Capability.DISCOVER_ASSETS}

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        hostname = config.get("hostname") or config.get("host") or "unknown-server"
        namespace = config.get("namespace", "default")
        integration_id = config.get("integration_id")

        asset_id = generate_asset_id("infrastructure", "linux", namespace, "", hostname)

        node = LineageNode(
            id=asset_id,
            name=hostname,
            fqn=f"linux.{namespace}.{hostname}",
            node_type=NodeType.DATASET,
            platform="linux",
            platform_domain=PlatformDomain.OTHER,
            asset_kind=AssetKind.UNKNOWN,
            namespace=namespace,
            observed_at=datetime.utcnow(),
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "running_services": config.get("running_services", []),
                "hosted_tools": config.get("hosted_tools", []),
            },
        )

        logger.info(f"[LiveLinux] Discovered server node: {hostname}")
        return [node]

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        return []
