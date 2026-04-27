"""Tests for dbt manifest error messages — they must reflect what was actually
attempted, not generic "or connect a GitHub repo" boilerplate."""
import asyncio

import pytest
from unittest.mock import patch

from scanner.copilot.context_builder import (
    CopilotContext,
    IntegrationInfo,
    IntegrationLayer,
)
from scanner.copilot.tool_executor import ToolExecutor


def _ctx(integrations):
    return CopilotContext(
        org_id="org_test",
        integrations=integrations,
        integration_types={i.type.upper() for i in integrations if i.is_active},
    )


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _dbt_node(config):
    return IntegrationInfo(
        id="dbt_node",
        name="dbt Core",
        type="DBT_CORE",
        layer=IntegrationLayer.TRANSFORMATION,
        status="ACTIVE",
        config=config,
    )


def test_error_for_github_mode_with_no_token_mentions_github_connector():
    """
    When source_mode=github but no token is reachable (no dbt-config token AND
    no GITHUB integration), the error should say *that* — not "Manifest not
    found: ./target/manifest.json", which leaks an unrelated filesystem path.
    """
    dbt = _dbt_node({
        "source_mode": "github",
        "github_repo": "acme/analytics",
        "github_branch": "main",
    })
    executor = ToolExecutor(_ctx([dbt]))

    _, error = executor._get_dbt_adapter_with_manifest()

    assert error is not None
    assert error.success is False
    msg = error.error
    # Must NOT leak the misleading filesystem path or imply GitHub disconnect
    # generically — must be specific about *what was attempted and why it failed*.
    assert "./target/manifest.json" not in msg
    # Must call out GitHub mode explicitly and the lack of a token
    assert "github" in msg.lower()
    assert "token" in msg.lower() or "connect" in msg.lower()


def test_error_for_github_mode_with_token_but_empty_fetch(event_loop):
    """
    When source_mode=github, token + repo are set, but the GitHub fetch
    returns nothing (wrong path/branch, or repo has no dbt project), the
    error should name the repo/branch/path the user configured.
    """
    dbt = _dbt_node({
        "source_mode": "github",
        "github_repo": "acme/analytics",
        "github_branch": "develop",
        "dbt_project_path": "warehouse/dbt",
        "github_token": "ghp_xyz",
    })
    executor = ToolExecutor(_ctx([dbt]))

    async def empty_fetch(repo, token, branch, dbt_root):
        return {}

    with patch("lineage.github_reader.fetch_dbt_project_files", new=empty_fetch):
        _, error = executor._get_dbt_adapter_with_manifest()

    assert error is not None
    msg = error.error
    assert "./target/manifest.json" not in msg
    assert "acme/analytics" in msg
    assert "develop" in msg
    assert "warehouse/dbt" in msg


def test_error_for_upload_mode_with_no_manifest():
    """
    When source_mode=upload but no manifest blob is stored, the error must
    say so — not blame the filesystem or GitHub.
    """
    dbt = _dbt_node({
        "source_mode": "upload",
        # no "manifest" key
    })
    executor = ToolExecutor(_ctx([dbt]))

    _, error = executor._get_dbt_adapter_with_manifest()

    assert error is not None
    msg = error.error
    assert "./target/manifest.json" not in msg
    assert "upload" in msg.lower()
