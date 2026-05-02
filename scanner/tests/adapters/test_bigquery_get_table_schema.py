"""Unit tests for BigQueryAdapter.get_table_schema prefix-stripping."""

from unittest.mock import MagicMock, patch


def test_get_table_schema_strips_warehouse_prefix():
    """FQN with leading 'bigquery.' prefix must be stripped before calling get_columns."""
    from scanner.adapters.bigquery import BigQueryAdapter

    # Bypass __init__: get_table_schema only calls get_columns (patched below),
    # so adapter state is irrelevant. Avoids needing a real config dict that
    # would risk a real network call during construction.
    adapter = BigQueryAdapter.__new__(BigQueryAdapter)
    with patch.object(BigQueryAdapter, "get_columns") as mock_cols:
        mock_cols.return_value = []
        adapter.get_table_schema("bigquery.myproject.raw.water_meters")
        mock_cols.assert_called_once_with("myproject.raw.water_meters")


def test_get_table_schema_accepts_already_stripped_fqn():
    """FQN without leading 'bigquery.' prefix must be passed through unchanged."""
    from scanner.adapters.bigquery import BigQueryAdapter

    # Bypass __init__: get_table_schema only calls get_columns (patched below),
    # so adapter state is irrelevant. Avoids needing a real config dict that
    # would risk a real network call during construction.
    adapter = BigQueryAdapter.__new__(BigQueryAdapter)
    with patch.object(BigQueryAdapter, "get_columns") as mock_cols:
        mock_cols.return_value = []
        adapter.get_table_schema("myproject.raw.water_meters")
        mock_cols.assert_called_once_with("myproject.raw.water_meters")


def test_get_table_schema_returns_plain_dicts():
    """Return value must be a list of dicts with the canonical keys."""
    from scanner.adapters.bigquery import BigQueryAdapter
    from scanner.adapters.base import ColumnMetadata

    # Bypass __init__: get_table_schema only calls get_columns (patched below),
    # so adapter state is irrelevant. Avoids needing a real config dict that
    # would risk a real network call during construction.
    adapter = BigQueryAdapter.__new__(BigQueryAdapter)
    fake_col = ColumnMetadata(name="reading_at", data_type="TIMESTAMP", is_nullable=False)
    with patch.object(BigQueryAdapter, "get_columns", return_value=[fake_col]):
        result = adapter.get_table_schema("bigquery.myproject.raw.water_meters")

    assert result == [{"column_name": "reading_at", "data_type": "TIMESTAMP", "is_nullable": False}]
