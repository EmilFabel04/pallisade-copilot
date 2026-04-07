"""
Driver loader — registers all integration drivers at startup.

Called once from scanner/api/app.py.  Uses lazy imports with try/except
so that missing optional dependencies don't prevent other drivers from
loading (same pattern as scanner/adapters/factory.py).
"""

from __future__ import annotations

import logging

from .registry import DriverRegistry

logger = logging.getLogger(__name__)

_loaded = False


def reset_loaded_flag() -> None:
    """Reset the _loaded flag (for testing after DriverRegistry.reset())."""
    global _loaded
    _loaded = False


def register_all_drivers() -> None:
    """Import and register every IntegrationDriver."""
    global _loaded
    if _loaded:
        return
    _loaded = True

    _register = DriverRegistry.register

    # ── Warehouses (DATA_PLANE) ────────────────────────────────────────
    try:
        from .warehouse.bigquery_driver import BigQueryDriver
        _register("BIGQUERY", BigQueryDriver)
    except Exception as e:
        logger.debug("BigQuery driver not loaded: %s", e)

    try:
        from .warehouse.snowflake_driver import SnowflakeDriver
        _register("SNOWFLAKE", SnowflakeDriver)
    except Exception as e:
        logger.debug("Snowflake driver not loaded: %s", e)

    try:
        from .warehouse.postgres_driver import PostgresDriver
        _register("POSTGRES", PostgresDriver)
    except Exception as e:
        logger.debug("Postgres driver not loaded: %s", e)

    try:
        from .warehouse.redshift_driver import RedshiftDriver
        _register("REDSHIFT", RedshiftDriver)
    except Exception as e:
        logger.debug("Redshift driver not loaded: %s", e)

    try:
        from .warehouse.databricks_driver import DatabricksDriver
        _register("DATABRICKS", DatabricksDriver)
    except Exception as e:
        logger.debug("Databricks driver not loaded: %s", e)

    try:
        from .warehouse.sqlserver_driver import SqlServerDriver
        _register("SQLSERVER", SqlServerDriver)
    except Exception as e:
        logger.debug("SQL Server driver not loaded: %s", e)

    try:
        from .warehouse.azure_sql_driver import AzureSqlDriver
        _register("AZURE_SQL", AzureSqlDriver)
    except Exception as e:
        logger.debug("Azure SQL driver not loaded: %s", e)

    try:
        from .warehouse.azure_synapse_driver import AzureSynapseDriver
        _register("AZURE_SYNAPSE", AzureSynapseDriver)
    except Exception as e:
        logger.debug("Azure Synapse driver not loaded: %s", e)

    try:
        from .warehouse.mysql_driver import MySqlDriver
        _register("MYSQL", MySqlDriver)
    except Exception as e:
        logger.debug("MySQL driver not loaded: %s", e)

    # ── Ingestion (DATA_PLANE) ─────────────────────────────────────────
    try:
        from .ingestion.fivetran_driver import FivetranDriver
        _register("FIVETRAN", FivetranDriver)
    except Exception as e:
        logger.debug("Fivetran driver not loaded: %s", e)

    try:
        from .ingestion.airbyte_driver import AirbyteDriver
        _register("AIRBYTE", AirbyteDriver)
    except Exception as e:
        logger.debug("Airbyte driver not loaded: %s", e)

    try:
        from .ingestion.stitch_driver import StitchDriver
        _register("STITCH", StitchDriver)
    except Exception as e:
        logger.debug("Stitch driver not loaded: %s", e)

    # ── Transformation / Orchestration (DATA_PLANE) ────────────────────
    try:
        from .transformation.dbt_cloud_driver import DbtCloudDriver
        _register("DBT_CLOUD", DbtCloudDriver)
    except Exception as e:
        logger.debug("dbt Cloud driver not loaded: %s", e)

    try:
        from .transformation.dbt_core_driver import DbtCoreDriver
        _register("DBT_CORE", DbtCoreDriver)
    except Exception as e:
        logger.debug("dbt Core driver not loaded: %s", e)

    try:
        from .transformation.airflow_driver import AirflowDriver
        _register("AIRFLOW", AirflowDriver)
    except Exception as e:
        logger.debug("Airflow driver not loaded: %s", e)

    try:
        from .transformation.dagster_driver import DagsterDriver
        _register("DAGSTER", DagsterDriver)
    except Exception as e:
        logger.debug("Dagster driver not loaded: %s", e)

    try:
        from .transformation.prefect_driver import PrefectDriver
        _register("PREFECT", PrefectDriver)
    except Exception as e:
        logger.debug("Prefect driver not loaded: %s", e)

    try:
        from .transformation.n8n_driver import N8nDriver
        _register("N8N", N8nDriver)
    except Exception as e:
        logger.debug("n8n driver not loaded: %s", e)

    # ── Reporting / BI (DATA_PLANE) ────────────────────────────────────
    try:
        from .reporting.looker_driver import LookerDriver
        _register("LOOKER", LookerDriver)
    except Exception as e:
        logger.debug("Looker driver not loaded: %s", e)

    try:
        from .reporting.tableau_driver import TableauDriver
        _register("TABLEAU", TableauDriver)
    except Exception as e:
        logger.debug("Tableau driver not loaded: %s", e)

    try:
        from .reporting.metabase_driver import MetabaseDriver
        _register("METABASE", MetabaseDriver)
    except Exception as e:
        logger.debug("Metabase driver not loaded: %s", e)

    try:
        from .reporting.powerbi_driver import PowerBiDriver
        _register("POWERBI", PowerBiDriver)
    except Exception as e:
        logger.debug("Power BI driver not loaded: %s", e)

    # ── Storage (DATA_PLANE) ───────────────────────────────────────────
    try:
        from .storage.s3_driver import S3Driver
        _register("AMAZON_S3", S3Driver)
    except Exception as e:
        logger.debug("S3 driver not loaded: %s", e)

    try:
        from .storage.gcs_driver import GcsDriver
        _register("GCS", GcsDriver)
    except Exception as e:
        logger.debug("GCS driver not loaded: %s", e)

    try:
        from .storage.adls_driver import AdlsDriver
        _register("ADLS", AdlsDriver)
    except Exception as e:
        logger.debug("ADLS driver not loaded: %s", e)

    # ── Version Control (CONTROL_PLANE) ────────────────────────────────
    try:
        from .vcs.github_driver import GitHubDriver
        _register("GITHUB", GitHubDriver)
    except Exception as e:
        logger.debug("GitHub driver not loaded: %s", e)

    try:
        from .vcs.github_issues_driver import GitHubIssuesDriver
        _register("GITHUB_ISSUES", GitHubIssuesDriver)
    except Exception as e:
        logger.debug("GitHub Issues driver not loaded: %s", e)

    try:
        from .vcs.gitlab_driver import GitLabDriver
        _register("GITLAB", GitLabDriver)
    except Exception as e:
        logger.debug("GitLab driver not loaded: %s", e)

    try:
        from .vcs.bitbucket_driver import BitbucketDriver
        _register("BITBUCKET", BitbucketDriver)
    except Exception as e:
        logger.debug("Bitbucket driver not loaded: %s", e)

    # ── Notifications (CONTROL_PLANE) ──────────────────────────────────
    try:
        from .notifications.slack_driver import SlackDriver
        _register("SLACK", SlackDriver)
    except Exception as e:
        logger.debug("Slack driver not loaded: %s", e)

    try:
        from .notifications.teams_driver import TeamsDriver
        _register("TEAMS", TeamsDriver)
    except Exception as e:
        logger.debug("Teams driver not loaded: %s", e)

    try:
        from .notifications.pagerduty_driver import PagerDutyDriver
        _register("PAGERDUTY", PagerDutyDriver)
    except Exception as e:
        logger.debug("PagerDuty driver not loaded: %s", e)

    try:
        from .notifications.opsgenie_driver import OpsGenieDriver
        _register("OPSGENIE", OpsGenieDriver)
    except Exception as e:
        logger.debug("OpsGenie driver not loaded: %s", e)

    # ── Ticketing / Project Management (CONTROL_PLANE) ─────────────────
    try:
        from .ticketing.jira_driver import JiraDriver
        _register("JIRA", JiraDriver)
    except Exception as e:
        logger.debug("Jira driver not loaded: %s", e)

    try:
        from .ticketing.linear_driver import LinearDriver
        _register("LINEAR", LinearDriver)
    except Exception as e:
        logger.debug("Linear driver not loaded: %s", e)

    try:
        from .ticketing.asana_driver import AsanaDriver
        _register("ASANA", AsanaDriver)
    except Exception as e:
        logger.debug("Asana driver not loaded: %s", e)

    # ── Infrastructure (CONTROL_PLANE) ─────────────────────────────────
    try:
        from .infrastructure.linux_server_driver import LinuxServerDriver
        _register("LINUX_SERVER", LinuxServerDriver)
    except Exception as e:
        logger.debug("Linux Server driver not loaded: %s", e)

    # ── Other (CONTROL_PLANE) ──────────────────────────────────────────
    try:
        from .other.custom_webhook_driver import CustomWebhookDriver
        _register("CUSTOM_WEBHOOK", CustomWebhookDriver)
    except Exception as e:
        logger.debug("Custom Webhook driver not loaded: %s", e)

    logger.info(
        "Loaded %d integration drivers (%d DATA_PLANE, %d CONTROL_PLANE)",
        len(DriverRegistry.list_supported()),
        len(DriverRegistry.list_data_plane()),
        len(DriverRegistry.list_control_plane()),
    )
