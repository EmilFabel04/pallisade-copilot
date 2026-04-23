"""Tests for SQL specialist dialect adaptation."""

from unittest.mock import MagicMock

from copilot.maas.specialists.sql import SQLSpecialist, DIALECT_RULES


class TestSQLSpecialistDialect:
    """Verify only the target dialect's rules are injected into the prompt."""

    def test_bigquery_rules_in_prompt(self):
        specialist = SQLSpecialist(MagicMock())
        messages = specialist.build_messages(
            "## Schema\n- table: col1", "count orders",
            warehouse_type="bigquery",
        )
        system = messages[0]["content"]
        assert "backtick" in system.lower()
        assert "SAFE_CAST" in system
        assert "UNNEST" in system
        # No cross-contamination from other dialects
        assert "DATEADD" not in system
        assert "GETDATE" not in system

    def test_snowflake_rules_in_prompt(self):
        specialist = SQLSpecialist(MagicMock())
        messages = specialist.build_messages(
            "## Schema\n- table: col1", "count orders",
            warehouse_type="snowflake",
        )
        system = messages[0]["content"]
        assert "DATEADD" in system
        assert "backtick" not in system.lower()
        assert "SAFE_CAST" not in system

    def test_databricks_rules_in_prompt(self):
        specialist = SQLSpecialist(MagicMock())
        messages = specialist.build_messages(
            "## Schema\n- table: col1", "count orders",
            warehouse_type="databricks",
        )
        system = messages[0]["content"]
        assert "catalog.schema.table" in system
        assert "try_cast" in system
        # Databricks rules mention "no backticks" — that's correct guidance
        assert "SAFE_CAST" not in system
        assert "DATEADD" not in system

    def test_postgres_rules_in_prompt(self):
        specialist = SQLSpecialist(MagicMock())
        messages = specialist.build_messages(
            "## Schema\n- table: col1", "count orders",
            warehouse_type="postgres",
        )
        system = messages[0]["content"]
        assert "NOW()" in system
        assert "INTERVAL" in system
        assert "backtick" not in system.lower()

    def test_redshift_rules_in_prompt(self):
        specialist = SQLSpecialist(MagicMock())
        messages = specialist.build_messages(
            "## Schema\n- table: col1", "count orders",
            warehouse_type="redshift",
        )
        system = messages[0]["content"]
        assert "GETDATE()" in system
        assert "backtick" not in system.lower()

    def test_unknown_warehouse_fallback(self):
        specialist = SQLSpecialist(MagicMock())
        messages = specialist.build_messages(
            "## Schema\n- table: col1", "count orders",
            warehouse_type="unknown_db",
        )
        system = messages[0]["content"]
        assert "unknown_db" in system
        assert "Use correct syntax" in system

    def test_all_dialects_have_rules(self):
        """Every supported dialect must have an entry in DIALECT_RULES."""
        expected = {"bigquery", "databricks", "snowflake", "postgres", "redshift"}
        assert set(DIALECT_RULES.keys()) == expected

    def test_warehouse_field_instruction(self):
        """Prompt must tell the model to set warehouse to the target type."""
        specialist = SQLSpecialist(MagicMock())
        for wh in ["bigquery", "snowflake", "postgres"]:
            messages = specialist.build_messages("schema", "test", warehouse_type=wh)
            system = messages[0]["content"]
            assert f'"{wh}"' in system
