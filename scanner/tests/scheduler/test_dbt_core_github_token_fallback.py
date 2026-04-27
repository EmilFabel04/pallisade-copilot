"""Tests that the dbt Core monitor runner falls back to the workspace
GITHUB integration's access token when the dbt config has no github_token
of its own.

Failing context: a user with the dbt Core integration in GitHub mode and
a separately-connected GitHub OAuth integration would see their
DBT_CORE_SOURCE_VALIDATION / DBT_CORE_REF_INTEGRITY monitors fail with
'dbt_core GitHub mode missing token or repo.' because the runner only
looked at the dbt config — never at the workspace-level OAuth token.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from scanner.scheduler.executor import TaskExecutor


@contextmanager
def _mock_pg_connection(rows):
    """Yield a context manager whose cursor.execute records the SQL/args
    and whose fetchone returns the next row from `rows` (a list)."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    cursor.executed = []

    def _exec(sql, params=()):
        cursor.executed.append((sql, params))

    def _fetchone():
        return rows.pop(0) if rows else None

    cursor.execute.side_effect = _exec
    cursor.fetchone.side_effect = _fetchone
    conn.cursor.return_value = cursor
    yield conn


def test_get_workspace_github_token_returns_token_from_active_github_integration():
    executor = TaskExecutor()

    rows = [("ghp_workspaceTokenAbc",)]
    with _mock_pg_connection(rows) as conn:
        with patch("scanner.scheduler.service._get_connection", return_value=conn):
            token = executor._get_workspace_github_token("org_test")

    assert token == "ghp_workspaceTokenAbc"
    # Sanity: query must filter by org and type=GITHUB (not just take any token).
    sql, params = conn.cursor.return_value.executed[0]
    assert "GITHUB" in sql
    assert "organizationId" in sql
    assert params == ("org_test",)


def test_get_workspace_github_token_returns_none_when_no_integration():
    executor = TaskExecutor()

    rows = []  # no row → fetchone returns None
    with _mock_pg_connection(rows) as conn:
        with patch("scanner.scheduler.service._get_connection", return_value=conn):
            token = executor._get_workspace_github_token("org_no_github")

    assert token is None


def test_get_workspace_github_token_returns_none_for_missing_org_id():
    executor = TaskExecutor()
    # No org id → don't even try to query the DB.
    with patch("scanner.scheduler.service._get_connection") as mock_conn:
        token = executor._get_workspace_github_token(None)

    assert token is None
    mock_conn.assert_not_called()


def test_dbt_core_github_mode_uses_workspace_token_when_dbt_config_lacks_one():
    """The behaviour change: in github mode, when the dbt integration config
    has no github_token, the runner must consult _get_workspace_github_token
    BEFORE raising 'dbt_core GitHub mode missing token or repo.'"""
    executor = TaskExecutor()

    captured = {}

    async def _fake_fetch(*, repo, token, branch, dbt_root):
        captured["repo"] = repo
        captured["token"] = token
        captured["branch"] = branch
        captured["dbt_root"] = dbt_root
        return ({}, None)  # no project files, no fallback manifest

    integration_config = {
        "source_mode": "github",
        "github_repo": "EmilFabel04/pallisade-test-pipeline",
        "github_branch": "main",
        # Intentionally omit github_token / github.token — exercising the bug
    }
    task = {"organizationId": "org_with_github_oauth"}

    # The executor does `from scanner.lineage.github_reader import ...`
    # inside the function body. The fresh import resolves the (now-patched)
    # attribute on the source module, so patching there is correct.
    from contextlib import ExitStack
    with ExitStack() as stack:
        mock_helper = stack.enter_context(
            patch.object(executor, "_get_workspace_github_token", return_value="ghp_workspaceTokenAbc")
        )
        # Patch on the fully-qualified path the executor actually uses.
        stack.enter_context(
            patch("scanner.lineage.github_reader.fetch_dbt_project_files_with_fallback",
                  side_effect=_fake_fetch)
        )
        # The runner will reach _resolve_warehouse_adapter_for_dbt after
        # trying to parse the (empty) project, which will fail with a
        # different error. We only care that _fake_fetch was reached with
        # the workspace token.
        try:
            executor._create_dbt_core_validation_client(integration_config, task)
        except (ValueError, Exception):
            pass

    mock_helper.assert_called_once_with("org_with_github_oauth")
    # Most important assertion: github_reader actually saw the workspace token
    # (not None, not "" — proving fallback worked).
    assert captured.get("token") == "ghp_workspaceTokenAbc"
    assert captured.get("repo") == "EmilFabel04/pallisade-test-pipeline"
