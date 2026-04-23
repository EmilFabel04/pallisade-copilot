"""Storage tool definitions."""

from .registry import register_tool
from .base import ToolCategory, ToolParameter


@register_tool(
    name="list_storage_objects",
    description=(
        "List objects/files in a cloud storage bucket or container. Shows paths, sizes, "
        "and last modified times. Useful for understanding data landing zones and "
        "tracking raw data files in the lineage."
    ),
    category=ToolCategory.LINEAGE,
    parameters=[
        ToolParameter("path", "string", "Bucket/container path (e.g., 's3://bucket/prefix/' or 'gs://bucket/path/' or 'abfss://container@account/')"),
        ToolParameter("limit", "integer", "Maximum objects to return", required=False, default=50),
    ],
    alternative_integrations={"AMAZON_S3", "GCS", "ADLS"},
)
def _meta_list_storage_objects():
    pass


@register_tool(
    name="get_storage_object_metadata",
    description=(
        "Get metadata for a specific storage object: size, content type, last modified, "
        "partitioning info. Useful for understanding data formats and freshness of raw files."
    ),
    category=ToolCategory.LINEAGE,
    parameters=[
        ToolParameter("path", "string", "Full object path (e.g., 's3://bucket/path/file.parquet')"),
    ],
    alternative_integrations={"AMAZON_S3", "GCS", "ADLS"},
)
def _meta_get_storage_object_metadata():
    pass


@register_tool(
    name="list_storage_buckets",
    description="List all accessible buckets/containers in the connected cloud storage account. Shows bucket names, regions, and creation dates.",
    category=ToolCategory.LINEAGE,
    parameters=[],
    alternative_integrations={"AMAZON_S3", "GCS", "ADLS"},
)
def _meta_list_storage_buckets():
    pass
