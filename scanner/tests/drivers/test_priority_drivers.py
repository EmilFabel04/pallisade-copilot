"""Tests for priority drivers (BigQuery, Snowflake, dbt Cloud, Airflow, Fivetran)."""

import pytest
from scanner.drivers.base import GraphDomain, IntegrationLayer


class TestBigQueryDriver:
    def test_identity(self):
        from scanner.drivers.warehouse.bigquery_driver import BigQueryDriver
        d = BigQueryDriver()
        assert d.id() == "bigquery"
        assert d.integration_type() == "BIGQUERY"
        assert d.layer() == IntegrationLayer.WAREHOUSE
        assert d.graph_domain() == GraphDomain.DATA_PLANE

    def test_validate_config_missing_project(self):
        from scanner.drivers.warehouse.bigquery_driver import BigQueryDriver
        d = BigQueryDriver()
        result = d.validate_config({})
        assert not result.valid
        assert any("project_id" in e for e in result.errors)

    def test_validate_config_valid(self):
        from scanner.drivers.warehouse.bigquery_driver import BigQueryDriver
        d = BigQueryDriver()
        result = d.validate_config({"project_id": "my-proj", "credentials_json": "{}"})
        assert result.valid

    def test_capabilities(self):
        from scanner.drivers.warehouse.bigquery_driver import BigQueryDriver
        d = BigQueryDriver()
        caps = d.capabilities()
        assert caps.can_query is True
        assert caps.can_extract_metadata is True
        assert caps.can_extract_lineage is True
        assert caps.can_fetch_logs is True

    def test_events_emitted(self):
        from scanner.drivers.warehouse.bigquery_driver import BigQueryDriver
        d = BigQueryDriver()
        events = d.events_emitted()
        assert "extraction.completed" in events
        assert "extraction.failed" in events

    def test_recommended_monitors(self):
        from scanner.drivers.warehouse.bigquery_driver import BigQueryDriver
        d = BigQueryDriver()
        monitors = d.recommended_monitors()
        assert "freshness" in monitors
        assert "volume" in monitors

    def test_contract_schema(self):
        from scanner.drivers.warehouse.bigquery_driver import BigQueryDriver
        d = BigQueryDriver()
        schema = d.contract_schema()
        assert schema is not None
        assert "maxQueryCostUsd" in schema.get("properties", {})


class TestSnowflakeDriver:
    def test_identity(self):
        from scanner.drivers.warehouse.snowflake_driver import SnowflakeDriver
        d = SnowflakeDriver()
        assert d.id() == "snowflake"
        assert d.graph_domain() == GraphDomain.DATA_PLANE

    def test_validate_config_missing_account(self):
        from scanner.drivers.warehouse.snowflake_driver import SnowflakeDriver
        d = SnowflakeDriver()
        result = d.validate_config({})
        assert not result.valid
        assert any("account" in e for e in result.errors)


class TestDbtCloudDriver:
    def test_identity(self):
        from scanner.drivers.transformation.dbt_cloud_driver import DbtCloudDriver
        d = DbtCloudDriver()
        assert d.id() == "dbt_cloud"
        assert d.layer() == IntegrationLayer.TRANSFORMATION
        assert d.graph_domain() == GraphDomain.DATA_PLANE

    def test_validate_config(self):
        from scanner.drivers.transformation.dbt_cloud_driver import DbtCloudDriver
        d = DbtCloudDriver()
        result = d.validate_config({"api_token": "tok", "account_id": "123"})
        assert result.valid

    def test_extract_metadata_with_manifest(self):
        from scanner.drivers.transformation.dbt_cloud_driver import DbtCloudDriver
        d = DbtCloudDriver()
        manifest = {
            "nodes": {
                "model.proj.users": {"resource_type": "model", "name": "users"},
                "model.proj.orders": {"resource_type": "model", "name": "orders"},
                "test.proj.t1": {"resource_type": "test", "name": "t1"},
            },
            "sources": {
                "source.proj.raw.events": {"name": "events"},
            },
        }
        summaries = d.extract_metadata({"manifest": manifest})
        model_summary = next((s for s in summaries if s.asset_type == "model"), None)
        assert model_summary is not None
        assert model_summary.count == 2


class TestAirflowDriver:
    def test_identity(self):
        from scanner.drivers.transformation.airflow_driver import AirflowDriver
        d = AirflowDriver()
        assert d.id() == "airflow"
        assert d.layer() == IntegrationLayer.ORCHESTRATION
        assert d.graph_domain() == GraphDomain.DATA_PLANE

    def test_validate_config(self):
        from scanner.drivers.transformation.airflow_driver import AirflowDriver
        d = AirflowDriver()
        result = d.validate_config({})
        assert not result.valid


class TestFivetranDriver:
    def test_identity(self):
        from scanner.drivers.ingestion.fivetran_driver import FivetranDriver
        d = FivetranDriver()
        assert d.id() == "fivetran"
        assert d.layer() == IntegrationLayer.INGESTION
        assert d.graph_domain() == GraphDomain.DATA_PLANE

    def test_validate_config(self):
        from scanner.drivers.ingestion.fivetran_driver import FivetranDriver
        d = FivetranDriver()
        result = d.validate_config({})
        assert not result.valid
        result = d.validate_config({"api_key": "k", "api_secret": "s"})
        assert result.valid
