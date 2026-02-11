"""Built-in reference adapters for the lineage engine."""

from .transform_artifact import TransformArtifactAdapter
from .warehouse_catalog import WarehouseCatalogAdapter
from .bi_query import BIQueryAdapter

__all__ = [
    "TransformArtifactAdapter",
    "WarehouseCatalogAdapter",
    "BIQueryAdapter",
]
