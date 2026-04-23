"""
Platform Registry — Single Source of Truth

Every platform/tool known to the lineage engine is registered here.
All classification functions, sets, and mappings derive from this registry.
To add a new platform, add ONE entry to platform_registry.yaml.

DESIGN RULE: Observed usage beats theoretical capability.
A platform splits into multiple roles ONLY when:
  1. Discovered assets / metadata provide evidence of that role
  2. Each role group has meaningful content (assets/jobs/nodes)
  3. Role membership is evidence-backed, not just capability-based
PlatformInfo.capabilities is an ELIGIBILITY HINT, not proof of active usage.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, FrozenSet, Optional, Tuple

import yaml

from ..graph import PlatformDomain

logger = logging.getLogger(__name__)


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
    """Metadata for a single platform/tool.

    ``category`` is the PRIMARY role — what this platform is known for.
    ``capabilities`` are ELIGIBILITY HINTS for additional roles the platform
    CAN serve.  They are NOT proof of active usage — only gate which
    observations are attempted.  Splitting requires observed evidence.
    """
    name: str
    category: ToolCategory
    domain: PlatformDomain
    capabilities: Tuple[ToolCategory, ...] = ()
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


# ── YAML loader ──────────────────────────────────────────────────────────

_REGISTRY_PATH = Path(__file__).parent / "platform_registry.yaml"


def _load_registry() -> None:
    """Load platform definitions from platform_registry.yaml."""
    try:
        raw = yaml.safe_load(_REGISTRY_PATH.read_text())
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load platform registry from {_REGISTRY_PATH}: {exc}"
        ) from exc

    platforms = raw.get("platforms") or {}
    for name, entry in platforms.items():
        _r(PlatformInfo(
            name=name,
            category=ToolCategory(entry["category"]),
            domain=PlatformDomain(entry["domain"]),
            capabilities=tuple(ToolCategory(c) for c in entry.get("capabilities", [])),
            is_warehouse=entry.get("is_warehouse", False),
            is_sql_engine=entry.get("is_sql_engine", False),
            adapter_id=entry.get("adapter_id"),
            heuristic_order=entry.get("heuristic_order", 50),
            aliases=tuple(entry.get("aliases", [])),
        ))


_load_registry()


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


def _has_category_or_capability(cat: ToolCategory):
    """Predicate: platform's primary category OR eligible capabilities include cat."""
    return lambda p: p.category == cat or cat in p.capabilities


WAREHOUSE_PLATFORMS:     FrozenSet[str] = _platforms_where(lambda p: p.is_warehouse)
INGESTION_PLATFORMS:     FrozenSet[str] = _platforms_where(_has_category_or_capability(ToolCategory.INGESTION))
TRANSFORM_PLATFORMS:     FrozenSet[str] = _platforms_where(_has_category_or_capability(ToolCategory.TRANSFORMATION))
ORCHESTRATION_PLATFORMS: FrozenSet[str] = _platforms_where(_has_category_or_capability(ToolCategory.ORCHESTRATION))
REPORTING_PLATFORMS:     FrozenSet[str] = _platforms_where(_has_category_or_capability(ToolCategory.REPORTING))
INFRA_PLATFORMS:         FrozenSet[str] = _platforms_where(lambda p: p.category == ToolCategory.INFRASTRUCTURE)


# ── Lookup helpers ────────────────────────────────────────────────────────

def get_platform(name: str) -> Optional[PlatformInfo]:
    """Look up a platform by name (case-insensitive). Returns None if unknown."""
    return PLATFORM_REGISTRY.get(name.lower())


def get_category(name: str) -> Optional[ToolCategory]:
    """Get the PRIMARY category for a platform name. Returns None if unknown."""
    info = get_platform(name)
    return info.category if info else None


def get_all_categories(name: str) -> Tuple[ToolCategory, ...]:
    """Return primary + eligible secondary capabilities.

    ELIGIBILITY ONLY — does not imply the platform is actively serving
    these roles.  Use observed evidence to determine actual usage.
    """
    info = get_platform(name)
    if not info:
        return ()
    return (info.category,) + info.capabilities


def has_capability(name: str, cap: ToolCategory) -> bool:
    """Check if platform is ELIGIBLE for this capability.

    Does NOT imply active usage — only that the platform can serve this role
    when observed evidence confirms it.
    """
    return cap in get_all_categories(name)


def is_multi_role(name: str) -> bool:
    """True if the platform has declared additional capability eligibility.

    This is an eligibility check, not an observed-usage check.
    A True result means the platform CAN serve multiple roles, not that it IS.
    """
    info = get_platform(name)
    return bool(info and info.capabilities)


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
