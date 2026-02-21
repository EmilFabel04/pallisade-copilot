"""
Live Storage Adapter — represents cloud storage (S3/GCS/ADLS) as lineage endpoints.

Storage objects are primarily source/sink nodes. They appear at the edges of
the lineage graph — ingestion tools read from them, pipelines write to them.
Cross-plane edges are created when naming conventions or config link storage
locations to warehouse external tables.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, generate_edge_id

logger = logging.getLogger(__name__)

# Map storage provider to platform name
_PROVIDER_MAP = {
    "s3": "aws_s3",
    "gcs": "gcp_gcs",
    "adls": "azure_adls",
    "azure": "azure_adls",
}


class LiveStorageAdapter(BaseLineageAdapter):
    """
    Adapter that discovers cloud storage buckets/containers and key prefixes
    as lineage endpoint nodes.

    Config keys:
        namespace: Cloud account or project identifier
        integration_id: Pallisade integration ID
        provider: "s3" | "gcs" | "adls"
        storage_config: Dict with provider-specific credentials
        known_mappings: Optional list of {prefix: str, table_fqn: str} for
            explicit storage→warehouse table links
    """

    def __init__(self, adapter_id: str = "live_storage", **kwargs):
        self._id = adapter_id

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TABLE_LINEAGE,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover storage buckets and known prefixes."""
        client = self._get_client(config)
        if not client:
            return []

        provider = config.get("provider", "s3")
        platform = _PROVIDER_MAP.get(provider, provider)
        namespace = config.get("namespace", provider)
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        try:
            buckets = client.list_buckets()
        except Exception as e:
            logger.error(f"[LiveStorage] Failed to list buckets: {e}")
            buckets = []

        for bucket in buckets:
            bucket_name = bucket if isinstance(bucket, str) else bucket.get("name", "")
            if not bucket_name:
                continue

            asset_id = generate_asset_id(
                "ingestion", platform, namespace, "", bucket_name,
            )
            nodes.append(LineageNode(
                id=asset_id,
                name=bucket_name,
                fqn=f"{platform}.{namespace}.{bucket_name}",
                node_type=NodeType.SOURCE,
                platform=platform,
                platform_domain=PlatformDomain.INGESTION,
                asset_kind=AssetKind.FILE,
                namespace=namespace,
                observed_at=now,
                sources=[self._id],
                integration_id=integration_id,
                raw_metadata={
                    "provider": provider,
                    "bucket": bucket_name,
                },
            ))

        logger.info(f"[LiveStorage] Discovered {len(nodes)} storage assets")
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """
        Extract lineage from known storage→warehouse mappings.

        Explicit mappings in config take priority. Without them, storage
        nodes are endpoints with no outgoing edges (other adapters like
        Fivetran/Airbyte create the connecting edges).
        """
        provider = config.get("provider", "s3")
        platform = _PROVIDER_MAP.get(provider, provider)
        namespace = config.get("namespace", provider)
        known_mappings = config.get("known_mappings", [])
        now = datetime.utcnow()
        edges: List[LineageEdge] = []

        for mapping in known_mappings:
            prefix = mapping.get("prefix", "")
            table_fqn = mapping.get("table_fqn", "")
            bucket = mapping.get("bucket", "")
            if not prefix or not table_fqn:
                continue

            # Storage source node
            source_name = bucket or prefix.split("/")[0]
            storage_asset_id = generate_asset_id(
                "ingestion", platform, namespace, "", source_name,
            )

            # Warehouse target node
            parts = table_fqn.split(".")
            table_name = parts[-1] if parts else table_fqn
            schema_name = parts[-2] if len(parts) > 1 else ""
            db_name = parts[-3] if len(parts) > 2 else ""
            container = f"{db_name}.{schema_name}"
            table_asset_id = generate_asset_id(
                "warehouse", platform, namespace, container, table_name,
            )

            source_ref = f"storage:{platform}:{source_name}:maps_to:{table_fqn}"
            edges.append(self._make_edge(
                storage_asset_id, table_asset_id,
                EdgeType.POPULATES, LineageLevel.TABLE,
                confidence=0.9,
                source_ref=source_ref,
                now=now,
                plane=LinePlane.CROSS,
            ))

        logger.info(f"[LiveStorage] Extracted {len(edges)} edges from mappings")
        return edges

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        if config.get("client"):
            return config["client"]

        provider = config.get("provider", "s3")
        storage_config = config.get("storage_config", {})

        try:
            if provider == "s3":
                from scanner.integrations.storage import S3Client
                return S3Client(storage_config)
            elif provider == "gcs":
                from scanner.integrations.storage import GCSClient
                return GCSClient(storage_config)
            elif provider in ("adls", "azure"):
                from scanner.integrations.storage import ADLSClient
                return ADLSClient(storage_config)
        except ImportError:
            pass

        logger.warning(f"[LiveStorage] Could not create client for {provider}")
        return None

    # ------------------------------------------------------------------
    # Edge helper
    # ------------------------------------------------------------------

    def _make_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        level: LineageLevel,
        confidence: float,
        source_ref: str,
        now: datetime,
        plane: LinePlane = LinePlane.CROSS,
    ) -> LineageEdge:
        ev = Evidence(
            adapter_id=self._id,
            source_ref=source_ref,
            observed_at=now,
        )
        edge_id = generate_edge_id(
            source_id, target_id,
            edge_type.value, level.value,
            source_ref,
        )
        return LineageEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            lineage_level=level,
            confidence=confidence,
            discovered_from=source_ref,
            discovered_at=now,
            evidence=[ev],
            plane=plane,
        )
