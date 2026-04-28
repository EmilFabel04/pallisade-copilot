"""Per-tenant in-memory caches for the lineage engine.

All four caches are keyed by a compound ``(org_id, stack_id)`` key. The
``org_id`` MUST come from ``request.state.principal.organization_id``
(set by ``ActingPrincipalMiddleware``) — never from a query parameter,
body field, or header. Two organizations using the same ``stack_id``
value cannot collide because the org prefix makes the key unique.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from scanner.lineage.engine.run_registry import RunRegistry
    from scanner.lineage.engine.store import GraphStore


# ---------------------------------------------------------------------------
# Module-level cache dicts
# ---------------------------------------------------------------------------

_engine_stores: Dict[str, "GraphStore"] = {}
_run_registries: Dict[str, "RunRegistry"] = {}
_engine_collected_results_map: Dict[str, Dict[str, Any]] = {}
_engine_tool_configs_map: Dict[str, Dict[str, Any]] = {}


def _empty_collected() -> Dict[str, Any]:
    return {
        "nodes": [],
        "edges": [],
        "dbt_manifest": None,
        "dbt_config": None,
        "schema_mapping": None,
    }


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def cache_key(org_id: str, stack_id: Optional[str]) -> str:
    """Compose the compound cache key. ``stack_id`` defaults to ``"default"``."""
    return f"{org_id}:{stack_id or 'default'}"


def get_engine_store(org_id: str, stack_id: Optional[str]) -> "GraphStore":
    """Return the GraphStore for this principal, creating it if needed."""
    key = cache_key(org_id, stack_id)
    if key not in _engine_stores:
        try:
            from lineage.engine.store import GraphStore
        except ImportError:
            from scanner.lineage.engine.store import GraphStore
        _engine_stores[key] = GraphStore()
    return _engine_stores[key]


def get_run_registry(org_id: str, stack_id: Optional[str]) -> "RunRegistry":
    """Return the RunRegistry for this principal, creating it if needed."""
    key = cache_key(org_id, stack_id)
    if key not in _run_registries:
        try:
            from lineage.engine.run_registry import RunRegistry
        except ImportError:
            from scanner.lineage.engine.run_registry import RunRegistry
        _run_registries[key] = RunRegistry()
    return _run_registries[key]


def get_collected_results(org_id: str, stack_id: Optional[str]) -> Dict[str, Any]:
    """Return the adapter-output bucket for this principal."""
    key = cache_key(org_id, stack_id)
    if key not in _engine_collected_results_map:
        _engine_collected_results_map[key] = _empty_collected()
    return _engine_collected_results_map[key]


def get_tool_configs(org_id: str, stack_id: Optional[str]) -> Dict[str, Any]:
    """Return cached tool configs for this principal (empty dict if unset)."""
    key = cache_key(org_id, stack_id)
    return _engine_tool_configs_map.get(key, {})


def set_tool_configs(
    org_id: str, stack_id: Optional[str], configs: Dict[str, Any]
) -> None:
    """Replace the tool-configs entry for this principal."""
    key = cache_key(org_id, stack_id)
    _engine_tool_configs_map[key] = configs


def clear_engine_cache(org_id: str, stack_id: Optional[str]) -> None:
    """Reset the collected-results bucket for this principal.

    Note: this only clears the adapter-output accumulator. Callers that
    also need to wipe the resolved graph and run registry must reset
    those on the returned ``GraphStore`` and ``RunRegistry`` themselves
    (see ``engine_clear_cache`` in ``lineage.py``).
    """
    key = cache_key(org_id, stack_id)
    _engine_collected_results_map[key] = _empty_collected()
