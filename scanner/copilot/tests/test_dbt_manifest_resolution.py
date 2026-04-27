"""Tests for dbt manifest resolution and GitHub token fallback."""
import asyncio

import pytest
from unittest.mock import patch

from scanner.copilot.context_builder import (
    CopilotContext,
    IntegrationInfo,
    IntegrationLayer,
)
from scanner.copilot.tool_executor import ToolExecutor


def _make_context(integrations):
    return CopilotContext(
        org_id="org_test",
        integrations=integrations,
        integration_types={i.type.upper() for i in integrations if i.is_active},
    )


@pytest.fixture
def event_loop():
    """Provide a clean event loop for each test (Python 3.14 doesn't auto-create)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_resolve_dbt_manifest_falls_back_to_workspace_github_token(event_loop):
    """
    When dbt is configured for source_mode=github with a github_repo but no
    github_token in its own config, _resolve_dbt_manifest must fall back to
    the workspace-level GITHUB integration's access_token.
    """
    dbt_integration = IntegrationInfo(
        id="dbt_node",
        name="dbt Core",
        type="DBT_CORE",
        layer=IntegrationLayer.TRANSFORMATION,
        status="ACTIVE",
        config={
            "source_mode": "github",
            "github_repo": "acme/analytics",
            "github_branch": "main",
            "dbt_project_path": "",
            "warehouse_type": "bigquery",
            # NOTE: no github_token here — this is the bug
        },
    )
    github_integration = IntegrationInfo(
        id="gh_node",
        name="GitHub",
        type="GITHUB",
        layer=IntegrationLayer.VERSION_CONTROL,
        status="ACTIVE",
        config={"access_token": "ghp_workspace_token_xyz"},
    )

    context = _make_context([dbt_integration, github_integration])
    executor = ToolExecutor(context)

    fetched_token_holder = {}

    async def fake_fetch(repo, token, branch, dbt_root):
        fetched_token_holder["token"] = token
        fetched_token_holder["repo"] = repo
        fetched_token_holder["branch"] = branch
        return {"dbt_project.yml": "name: acme_analytics\n"}

    def fake_parse(files, project_name, warehouse_type):
        return {"nodes": {"model.acme.x": {"name": "x"}}, "sources": {}}

    with patch("lineage.github_reader.fetch_dbt_project_files", new=fake_fetch), \
         patch("lineage.dbt_project_parser.parse_dbt_project", new=fake_parse):
        manifest = executor._resolve_dbt_manifest(dbt_integration.config)

    assert manifest is not None, (
        "Expected _resolve_dbt_manifest to return a parsed manifest by falling "
        "back to the workspace GITHUB integration's access_token, but it returned None."
    )
    assert fetched_token_holder.get("token") == "ghp_workspace_token_xyz", (
        f"Expected fetch_dbt_project_files to receive the workspace github token, "
        f"got {fetched_token_holder.get('token')!r}"
    )
    assert fetched_token_holder.get("repo") == "acme/analytics"
    assert fetched_token_holder.get("branch") == "main"


def test_resolve_dbt_manifest_prefers_dbt_config_token_when_present(event_loop):
    """
    If the dbt config carries an explicit github_token (e.g. classic PAT for
    private repo), prefer it over the workspace GITHUB integration's token.
    """
    dbt_integration = IntegrationInfo(
        id="dbt_node",
        name="dbt Core",
        type="DBT_CORE",
        layer=IntegrationLayer.TRANSFORMATION,
        status="ACTIVE",
        config={
            "source_mode": "github",
            "github_repo": "acme/analytics",
            "github_branch": "main",
            "github_token": "explicit_pat_abc",
            "warehouse_type": "bigquery",
        },
    )
    github_integration = IntegrationInfo(
        id="gh_node",
        name="GitHub",
        type="GITHUB",
        layer=IntegrationLayer.VERSION_CONTROL,
        status="ACTIVE",
        config={"access_token": "ghp_workspace_token_xyz"},
    )

    context = _make_context([dbt_integration, github_integration])
    executor = ToolExecutor(context)

    fetched_token_holder = {}

    async def fake_fetch(repo, token, branch, dbt_root):
        fetched_token_holder["token"] = token
        return {"dbt_project.yml": "name: x\n"}

    def fake_parse(files, project_name, warehouse_type):
        return {"nodes": {"model.x.y": {"name": "y"}}, "sources": {}}

    with patch("lineage.github_reader.fetch_dbt_project_files", new=fake_fetch), \
         patch("lineage.dbt_project_parser.parse_dbt_project", new=fake_parse):
        executor._resolve_dbt_manifest(dbt_integration.config)

    assert fetched_token_holder.get("token") == "explicit_pat_abc", (
        "Explicit github_token in dbt config should win over workspace token."
    )


def test_resolve_dbt_manifest_returns_none_when_no_token_anywhere():
    """If there's no github_token anywhere, GitHub fetch should not be attempted."""
    dbt_integration = IntegrationInfo(
        id="dbt_node",
        name="dbt Core",
        type="DBT_CORE",
        layer=IntegrationLayer.TRANSFORMATION,
        status="ACTIVE",
        config={
            "source_mode": "github",
            "github_repo": "acme/analytics",
            "github_branch": "main",
            "warehouse_type": "bigquery",
        },
    )

    context = _make_context([dbt_integration])
    executor = ToolExecutor(context)

    fetched = {"called": False}

    async def fake_fetch(*args, **kwargs):
        fetched["called"] = True
        return {}

    with patch("lineage.github_reader.fetch_dbt_project_files", new=fake_fetch):
        result = executor._resolve_dbt_manifest(dbt_integration.config)

    assert result is None
    assert fetched["called"] is False, (
        "Should not attempt GitHub fetch with no token available."
    )
