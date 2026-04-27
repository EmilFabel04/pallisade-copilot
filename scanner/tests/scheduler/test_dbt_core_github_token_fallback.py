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
def _mock_pg_connection(*, fetchall_results=None, fetchone_results=None):
    """Mock a psycopg connection. Each call to cursor.fetchall() and
    fetchone() consumes the next entry from the corresponding list."""
    fetchall_results = list(fetchall_results or [])
    fetchone_results = list(fetchone_results or [])

    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    cursor.executed = []

    def _exec(sql, params=()):
        cursor.executed.append((sql, params))

    def _fetchone():
        return fetchone_results.pop(0) if fetchone_results else None

    def _fetchall():
        return fetchall_results.pop(0) if fetchall_results else []

    cursor.execute.side_effect = _exec
    cursor.fetchone.side_effect = _fetchone
    cursor.fetchall.side_effect = _fetchall
    conn.cursor.return_value = cursor
    yield conn


def test_get_workspace_github_token_resolves_from_accesstoken_column():
    executor = TaskExecutor()

    with _mock_pg_connection(
        fetchall_results=[[("int_1", "ACTIVE", True, False, False)]],  # diag
        fetchone_results=[("ghp_columnToken", None, None)],            # main query
    ) as conn:
        with patch("scanner.scheduler.service._get_connection", return_value=conn):
            token = executor._get_workspace_github_token("org_test")

    assert token == "ghp_columnToken"


def test_get_workspace_github_token_resolves_from_config_json_when_column_null():
    """The actual production case: accessToken column is NULL but config has the token."""
    executor = TaskExecutor()

    with _mock_pg_connection(
        fetchall_results=[[("int_1", "ACTIVE", False, True, False)]],
        fetchone_results=[(None, {"access_token": "ghp_configToken"}, None)],
    ) as conn:
        with patch("scanner.scheduler.service._get_connection", return_value=conn):
            token = executor._get_workspace_github_token("org_test")

    assert token == "ghp_configToken"


def test_get_workspace_github_token_resolves_from_config_token_alias():
    executor = TaskExecutor()

    with _mock_pg_connection(
        fetchall_results=[[("int_1", "ACTIVE", False, True, False)]],
        fetchone_results=[(None, {"token": "ghp_aliasToken"}, None)],
    ) as conn:
        with patch("scanner.scheduler.service._get_connection", return_value=conn):
            token = executor._get_workspace_github_token("org_test")

    assert token == "ghp_aliasToken"


def test_get_workspace_github_token_resolves_from_plaintext_credentials_blob():
    executor = TaskExecutor()

    with _mock_pg_connection(
        fetchall_results=[[("int_1", "ACTIVE", False, False, True)]],
        fetchone_results=[(None, None, {"access_token": "ghp_credToken"})],
    ) as conn:
        with patch("scanner.scheduler.service._get_connection", return_value=conn):
            token = executor._get_workspace_github_token("org_test")

    assert token == "ghp_credToken"


def test_get_workspace_github_token_returns_none_when_no_integration():
    executor = TaskExecutor()

    with _mock_pg_connection(
        fetchall_results=[[]],          # no candidates
        fetchone_results=[None],        # main query also empty
    ) as conn:
        with patch("scanner.scheduler.service._get_connection", return_value=conn):
            token = executor._get_workspace_github_token("org_no_github")

    assert token is None


def test_get_workspace_github_token_returns_none_when_token_absent_everywhere():
    """Active integration row exists but no token in column, config, or credentials."""
    executor = TaskExecutor()

    with _mock_pg_connection(
        fetchall_results=[[("int_1", "ACTIVE", False, False, False)]],
        fetchone_results=[(None, None, None)],
    ) as conn:
        with patch("scanner.scheduler.service._get_connection", return_value=conn):
            token = executor._get_workspace_github_token("org_test")

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
