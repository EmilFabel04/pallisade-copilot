"""Unit tests for SnowflakeAdapter.get_table_schema prefix-stripping."""

from unittest.mock import MagicMock, patch


def test_get_table_schema_strips_warehouse_prefix():
    """FQN with leading 'snowflake.' prefix must be stripped before calling get_columns."""
    from scanner.adapters.snowflake import SnowflakeAdapter

    # Bypass __init__: get_table_schema only calls get_columns (patched below),
    # so adapter state is irrelevant. Avoids needing a real config dict that
    # would risk a real network call during construction.
    adapter = SnowflakeAdapter.__new__(SnowflakeAdapter)
    with patch.object(SnowflakeAdapter, "get_columns") as mock_cols:
        mock_cols.return_value = []
        adapter.get_table_schema("snowflake.MYDB.PUBLIC.water_meters")
        mock_cols.assert_called_once_with("MYDB.PUBLIC.water_meters")


def test_get_table_schema_accepts_already_stripped_fqn():
    """FQN without leading 'snowflake.' prefix must be passed through unchanged."""
    from scanner.adapters.snowflake import SnowflakeAdapter

    # Bypass __init__: get_table_schema only calls get_columns (patched below),
    # so adapter state is irrelevant. Avoids needing a real config dict that
    # would risk a real network call during construction.
    adapter = SnowflakeAdapter.__new__(SnowflakeAdapter)
    with patch.object(SnowflakeAdapter, "get_columns") as mock_cols:
        mock_cols.return_value = []
        adapter.get_table_schema("MYDB.PUBLIC.water_meters")
        mock_cols.assert_called_once_with("MYDB.PUBLIC.water_meters")


def test_get_table_schema_returns_plain_dicts():
    """Return value must be a list of dicts with the canonical keys."""
    from scanner.adapters.snowflake import SnowflakeAdapter
    from scanner.adapters.base import ColumnMetadata

    # Bypass __init__: get_table_schema only calls get_columns (patched below),
    # so adapter state is irrelevant. Avoids needing a real config dict that
    # would risk a real network call during construction.
    adapter = SnowflakeAdapter.__new__(SnowflakeAdapter)
    fake_col = ColumnMetadata(name="reading_at", data_type="TIMESTAMP_NTZ", is_nullable=False)
    with patch.object(SnowflakeAdapter, "get_columns", return_value=[fake_col]):
        result = adapter.get_table_schema("snowflake.MYDB.PUBLIC.water_meters")

    assert result == [{"column_name": "reading_at", "data_type": "TIMESTAMP_NTZ", "is_nullable": False}]
