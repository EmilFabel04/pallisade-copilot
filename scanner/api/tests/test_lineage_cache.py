"""Unit tests for the per-tenant lineage cache helpers."""

import pytest

from scanner.api.routers import _lineage_cache as cache


@pytest.fixture(autouse=True)
def _reset_cache_state():
    """Each test starts with empty module-level dicts."""
    cache._engine_stores.clear()
    cache._engine_collected_results_map.clear()
    cache._engine_tool_configs_map.clear()
    cache._run_registries.clear()
    yield


class TestCacheKey:
    def test_combines_org_and_stack(self):
        assert cache.cache_key("org_a", "stack_1") == "org_a:stack_1"

    def test_missing_stack_falls_back_to_default(self):
        assert cache.cache_key("org_a", None) == "org_a:default"
        assert cache.cache_key("org_a", "") == "org_a:default"

    def test_two_orgs_with_same_stack_are_distinct(self):
        assert cache.cache_key("org_a", "shared") != cache.cache_key("org_b", "shared")


class TestEngineStore:
    def test_returns_same_instance_for_same_principal(self):
        s1 = cache.get_engine_store("org_a", "s1")
        s2 = cache.get_engine_store("org_a", "s1")
        assert s1 is s2

    def test_isolates_distinct_orgs_with_same_stack(self):
        s_a = cache.get_engine_store("org_a", "shared")
        s_b = cache.get_engine_store("org_b", "shared")
        assert s_a is not s_b


class TestCollectedResults:
    def test_starts_with_empty_collected_shape(self):
        result = cache.get_collected_results("org_a", "s1")
        assert result == {
            "nodes": [],
            "edges": [],
            "dbt_manifest": None,
            "dbt_config": None,
            "schema_mapping": None,
        }

    def test_writes_to_one_org_do_not_appear_in_another(self):
        cache.get_collected_results("org_a", "s1")["nodes"].append({"id": "n1"})
        assert cache.get_collected_results("org_b", "s1")["nodes"] == []

    def test_returns_same_dict_object_for_same_principal(self):
        d1 = cache.get_collected_results("org_a", "s1")
        d2 = cache.get_collected_results("org_a", "s1")
        assert d1 is d2


class TestRunRegistry:
    def test_isolates_orgs(self):
        r_a = cache.get_run_registry("org_a", "s1")
        r_b = cache.get_run_registry("org_b", "s1")
        assert r_a is not r_b


class TestToolConfigs:
    def test_set_and_get_round_trip(self):
        cache.set_tool_configs("org_a", "s1", {"bigquery": {"project": "p"}})
        assert cache.get_tool_configs("org_a", "s1") == {"bigquery": {"project": "p"}}

    def test_get_returns_empty_dict_when_unset(self):
        assert cache.get_tool_configs("org_a", "s1") == {}

    def test_isolates_orgs(self):
        cache.set_tool_configs("org_a", "s1", {"bigquery": {"project": "p_a"}})
        cache.set_tool_configs("org_b", "s1", {"bigquery": {"project": "p_b"}})
        assert cache.get_tool_configs("org_a", "s1") == {"bigquery": {"project": "p_a"}}
        assert cache.get_tool_configs("org_b", "s1") == {"bigquery": {"project": "p_b"}}


class TestClearEngineCache:
    def test_only_clears_collected_results_for_target_principal(self):
        cache.get_collected_results("org_a", "s1")["nodes"].append({"id": "n1"})
        cache.get_collected_results("org_b", "s1")["nodes"].append({"id": "n2"})

        cache.clear_engine_cache("org_a", "s1")

        assert cache.get_collected_results("org_a", "s1")["nodes"] == []
        assert cache.get_collected_results("org_b", "s1")["nodes"] == [{"id": "n2"}]
