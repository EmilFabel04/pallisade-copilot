"""
Platform Registry — Single Source of Truth

Every platform/tool known to the lineage engine is registered here.
All classification functions, sets, and mappings derive from this registry.
To add a new platform, add ONE entry to PLATFORM_REGISTRY.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, Optional

from ..graph import PlatformDomain


class ToolCategory(Enum):
    """Category of a tool in the data pipeline."""
    WAREHOUSE = "warehouse"
    INGESTION = "ingestion"
    TRANSFORMATION = "transformation"
    ORCHESTRATION = "orchestration"
    REPORTING = "reporting"
    INFRASTRUCTURE = "infrastructure"
    VERSION_CONTROL = "version_control"
    QUALITY = "quality"


@dataclass(frozen=True)
class PlatformInfo:
    """Metadata for a single platform/tool."""
    name: str
    category: ToolCategory
    domain: PlatformDomain
    is_warehouse: bool = False
    is_sql_engine: bool = False
    adapter_id: Optional[str] = None
    heuristic_order: int = 50
    aliases: tuple = ()


# ── The Registry ──────────────────────────────────────────────────────────

PLATFORM_REGISTRY: Dict[str, PlatformInfo] = {}


def _r(info: PlatformInfo) -> PlatformInfo:
    """Register a platform and its aliases."""
    PLATFORM_REGISTRY[info.name] = info
    for alias in info.aliases:
        PLATFORM_REGISTRY[alias] = info
    return info


# ── Warehouses ────────────────────────────────────────────────────────────
_r(PlatformInfo("bigquery",   ToolCategory.WAREHOUSE, PlatformDomain.WAREHOUSE, is_warehouse=True, is_sql_engine=True, adapter_id="live_warehouse",  heuristic_order=10))
_r(PlatformInfo("snowflake",  ToolCategory.WAREHOUSE, PlatformDomain.WAREHOUSE, is_warehouse=True, is_sql_engine=True, adapter_id="live_warehouse",  heuristic_order=11))
_r(PlatformInfo("postgres",   ToolCategory.WAREHOUSE, PlatformDomain.WAREHOUSE, is_warehouse=True, is_sql_engine=True, adapter_id="live_warehouse",  heuristic_order=12))
_r(PlatformInfo("redshift",   ToolCategory.WAREHOUSE, PlatformDomain.WAREHOUSE, is_warehouse=True, is_sql_engine=True, adapter_id="live_warehouse",  heuristic_order=13))
_r(PlatformInfo("databricks", ToolCategory.WAREHOUSE, PlatformDomain.WAREHOUSE, is_warehouse=True, is_sql_engine=True, adapter_id="live_databricks", heuristic_order=14))
_r(PlatformInfo("trino",      ToolCategory.WAREHOUSE, PlatformDomain.WAREHOUSE, is_warehouse=True, is_sql_engine=True, heuristic_order=15))
_r(PlatformInfo("duckdb",     ToolCategory.WAREHOUSE, PlatformDomain.WAREHOUSE, is_warehouse=True, is_sql_engine=True, heuristic_order=16))
_r(PlatformInfo("mysql",      ToolCategory.WAREHOUSE, PlatformDomain.WAREHOUSE, is_warehouse=True, is_sql_engine=True, heuristic_order=17))
_r(PlatformInfo("mssql",      ToolCategory.WAREHOUSE, PlatformDomain.WAREHOUSE, is_warehouse=True, is_sql_engine=True, heuristic_order=18))

# ── Transformation ────────────────────────────────────────────────────────
_r(PlatformInfo("dbt_core",   ToolCategory.TRANSFORMATION, PlatformDomain.TRANSFORM, adapter_id="live_dbt", heuristic_order=20, aliases=("dbt",)))
_r(PlatformInfo("dbt_cloud",  ToolCategory.TRANSFORMATION, PlatformDomain.TRANSFORM, adapter_id="live_dbt", heuristic_order=21))
_r(PlatformInfo("spark",      ToolCategory.TRANSFORMATION, PlatformDomain.TRANSFORM, heuristic_order=22))
_r(PlatformInfo("dataform",   ToolCategory.TRANSFORMATION, PlatformDomain.TRANSFORM, heuristic_order=23))
_r(PlatformInfo("sqlmesh",    ToolCategory.TRANSFORMATION, PlatformDomain.TRANSFORM, heuristic_order=24))

# ── Ingestion ─────────────────────────────────────────────────────────────
_r(PlatformInfo("fivetran",   ToolCategory.INGESTION, PlatformDomain.INGESTION, adapter_id="live_fivetran", heuristic_order=30))
_r(PlatformInfo("airbyte",    ToolCategory.INGESTION, PlatformDomain.INGESTION, adapter_id="live_airbyte",  heuristic_order=31))
_r(PlatformInfo("n8n",        ToolCategory.INGESTION, PlatformDomain.INGESTION, adapter_id="live_n8n",      heuristic_order=32))
_r(PlatformInfo("meltano",    ToolCategory.INGESTION, PlatformDomain.INGESTION, heuristic_order=33))
_r(PlatformInfo("stitch",     ToolCategory.INGESTION, PlatformDomain.INGESTION, heuristic_order=34))
_r(PlatformInfo("hevo",       ToolCategory.INGESTION, PlatformDomain.INGESTION, heuristic_order=35))
_r(PlatformInfo("matillion",  ToolCategory.INGESTION, PlatformDomain.INGESTION, heuristic_order=36))
_r(PlatformInfo("rivery",     ToolCategory.INGESTION, PlatformDomain.INGESTION, heuristic_order=37))
_r(PlatformInfo("singer",     ToolCategory.INGESTION, PlatformDomain.INGESTION, heuristic_order=38))

# ── Orchestration ─────────────────────────────────────────────────────────
_r(PlatformInfo("airflow",    ToolCategory.ORCHESTRATION, PlatformDomain.ORCHESTRATION, adapter_id="live_airflow", heuristic_order=40))
_r(PlatformInfo("dagster",    ToolCategory.ORCHESTRATION, PlatformDomain.ORCHESTRATION, adapter_id="live_dagster", heuristic_order=41))
_r(PlatformInfo("prefect",    ToolCategory.ORCHESTRATION, PlatformDomain.ORCHESTRATION, adapter_id="live_prefect", heuristic_order=42))
_r(PlatformInfo("flink",      ToolCategory.ORCHESTRATION, PlatformDomain.ORCHESTRATION, heuristic_order=43))

# ── Reporting / BI ────────────────────────────────────────────────────────
_r(PlatformInfo("looker",     ToolCategory.REPORTING, PlatformDomain.BI, adapter_id="live_looker",   heuristic_order=50))
_r(PlatformInfo("tableau",    ToolCategory.REPORTING, PlatformDomain.BI, adapter_id="live_tableau",  heuristic_order=51))
_r(PlatformInfo("powerbi",    ToolCategory.REPORTING, PlatformDomain.BI, adapter_id="live_powerbi",  heuristic_order=52))
_r(PlatformInfo("metabase",   ToolCategory.REPORTING, PlatformDomain.BI, adapter_id="live_metabase", heuristic_order=53))
_r(PlatformInfo("superset",   ToolCategory.REPORTING, PlatformDomain.BI, heuristic_order=54))
_r(PlatformInfo("mode",       ToolCategory.REPORTING, PlatformDomain.BI, heuristic_order=55))
_r(PlatformInfo("sigma",      ToolCategory.REPORTING, PlatformDomain.BI, heuristic_order=56))
_r(PlatformInfo("thoughtspot", ToolCategory.REPORTING, PlatformDomain.BI, heuristic_order=57))

# ── Quality ───────────────────────────────────────────────────────────────
_r(PlatformInfo("elementary", ToolCategory.QUALITY, PlatformDomain.OTHER, adapter_id="live_elementary", heuristic_order=60))

# ── Infrastructure ────────────────────────────────────────────────────────
_r(PlatformInfo("linux",        ToolCategory.INFRASTRUCTURE, PlatformDomain.OTHER, heuristic_order=70))
_r(PlatformInfo("linux_server", ToolCategory.INFRASTRUCTURE, PlatformDomain.OTHER, adapter_id="live_linux", heuristic_order=70))
_r(PlatformInfo("ssh",          ToolCategory.INFRASTRUCTURE, PlatformDomain.OTHER, adapter_id="live_linux", heuristic_order=71))

# ── Version Control ───────────────────────────────────────────────────────
_r(PlatformInfo("github", ToolCategory.VERSION_CONTROL, PlatformDomain.OTHER, adapter_id="live_github", heuristic_order=80))
_r(PlatformInfo("gitlab", ToolCategory.VERSION_CONTROL, PlatformDomain.OTHER, adapter_id="live_github", heuristic_order=81))

# ── Storage ───────────────────────────────────────────────────────────────
_r(PlatformInfo("storage", ToolCategory.INFRASTRUCTURE, PlatformDomain.OTHER, adapter_id="live_storage", heuristic_order=90))


# ── Derived sets (computed once at import time) ───────────────────────────

def _platforms_where(predicate) -> FrozenSet[str]:
    """Return frozenset of primary platform names matching a predicate."""
    seen = set()
    result = set()
    for name, info in PLATFORM_REGISTRY.items():
        if info.name in seen:
            continue
        seen.add(info.name)
        if predicate(info):
            result.add(info.name)
    return frozenset(result)


WAREHOUSE_PLATFORMS:     FrozenSet[str] = _platforms_where(lambda p: p.is_warehouse)
INGESTION_PLATFORMS:     FrozenSet[str] = _platforms_where(lambda p: p.category == ToolCategory.INGESTION)
TRANSFORM_PLATFORMS:     FrozenSet[str] = _platforms_where(lambda p: p.category == ToolCategory.TRANSFORMATION)
ORCHESTRATION_PLATFORMS: FrozenSet[str] = _platforms_where(lambda p: p.category == ToolCategory.ORCHESTRATION)
REPORTING_PLATFORMS:     FrozenSet[str] = _platforms_where(lambda p: p.category == ToolCategory.REPORTING)
INFRA_PLATFORMS:         FrozenSet[str] = _platforms_where(lambda p: p.category == ToolCategory.INFRASTRUCTURE)


# ── Lookup helpers ────────────────────────────────────────────────────────

def get_platform(name: str) -> Optional[PlatformInfo]:
    """Look up a platform by name (case-insensitive). Returns None if unknown."""
    return PLATFORM_REGISTRY.get(name.lower())


def get_category(name: str) -> Optional[ToolCategory]:
    """Get the category for a platform name. Returns None if unknown."""
    info = get_platform(name)
    return info.category if info else None


def get_domain(name: str) -> PlatformDomain:
    """Get the PlatformDomain for a platform name. Returns OTHER if unknown."""
    info = get_platform(name)
    return info.domain if info else PlatformDomain.OTHER


def get_adapter_id(name: str) -> Optional[str]:
    """Get the adapter ID for a platform name. Returns None if no adapter."""
    info = get_platform(name)
    return info.adapter_id if info else None


def get_heuristic_order(name: str) -> int:
    """Get extraction ordering for a platform. Returns 99 for unknown."""
    info = get_platform(name)
    return info.heuristic_order if info else 99
