"""Tests that the system prompt context exposes enough dbt/orchestrator config
for the LLM to investigate without asking the user."""
from scanner.copilot.context_builder import (
    CopilotContext,
    IntegrationInfo,
    IntegrationLayer,
)


def _ctx(integrations):
    return CopilotContext(
        org_id="org_test",
        integrations=integrations,
        integration_types={i.type.upper() for i in integrations if i.is_active},
    )


def test_system_prompt_exposes_dbt_github_source_config():
    """
    When dbt Core is connected in github source_mode, the system prompt must
    surface source_mode, github_repo, github_branch, and dbt_project_path so the
    LLM can investigate the dbt setup directly instead of asking the user.
    """
    dbt = IntegrationInfo(
        id="dbt_node",
        name="dbt Core",
        type="DBT_CORE",
        layer=IntegrationLayer.TRANSFORMATION,
        status="ACTIVE",
        config={
            "source_mode": "github",
            "github_repo": "acme/analytics",
            "github_branch": "develop",
            "dbt_project_path": "warehouse/dbt",
            "warehouse_type": "bigquery",
        },
    )

    prompt = _ctx([dbt]).to_system_prompt_context()

    assert "github" in prompt.lower()
    assert "acme/analytics" in prompt, "Expected github_repo in prompt"
    assert "develop" in prompt, "Expected github_branch in prompt"
    assert "warehouse/dbt" in prompt, "Expected dbt_project_path in prompt"
    # Source mode should be visible so LLM understands which fetch path applies
    assert "source_mode" in prompt or "Source mode" in prompt or "Source: " in prompt


def test_system_prompt_exposes_dbt_upload_source_config():
    """For source_mode=upload (manifest blob), at least surface the mode."""
    dbt = IntegrationInfo(
        id="dbt_node",
        name="dbt Core",
        type="DBT_CORE",
        layer=IntegrationLayer.TRANSFORMATION,
        status="ACTIVE",
        config={
            "source_mode": "upload",
            "warehouse_type": "snowflake",
        },
    )

    prompt = _ctx([dbt]).to_system_prompt_context()

    assert "upload" in prompt.lower(), "Expected source_mode=upload to appear"


def test_system_prompt_exposes_airflow_github_source_config():
    """
    Airflow's github source_mode (DAG files in a repo) needs the same kind
    of visibility — repo, branch, dag_directory.
    """
    af = IntegrationInfo(
        id="af_node",
        name="Airflow",
        type="AIRFLOW",
        layer=IntegrationLayer.ORCHESTRATION,
        status="ACTIVE",
        config={
            "source_mode": "github",
            "github_repo": "acme/data-platform",
            "github_branch": "main",
            "dag_directory": "airflow/dags",
        },
    )

    prompt = _ctx([af]).to_system_prompt_context()

    assert "acme/data-platform" in prompt
    assert "airflow/dags" in prompt


def test_system_prompt_does_not_leak_secrets():
    """Tokens, passwords, and access_tokens must NEVER appear in the system prompt."""
    dbt = IntegrationInfo(
        id="dbt_node",
        name="dbt Core",
        type="DBT_CORE",
        layer=IntegrationLayer.TRANSFORMATION,
        status="ACTIVE",
        config={
            "source_mode": "github",
            "github_repo": "acme/analytics",
            "github_token": "ghp_super_secret_must_not_leak",
        },
    )
    gh = IntegrationInfo(
        id="gh_node",
        name="GitHub",
        type="GITHUB",
        layer=IntegrationLayer.VERSION_CONTROL,
        status="ACTIVE",
        config={
            "access_token": "ghp_another_secret",
            "owner": "acme",
        },
    )

    prompt = _ctx([dbt, gh]).to_system_prompt_context()

    assert "ghp_super_secret_must_not_leak" not in prompt
    assert "ghp_another_secret" not in prompt
