"""Unit tests for PostgresAdapter.get_table_schema prefix-stripping."""

from unittest.mock import patch


def test_get_table_schema_strips_warehouse_prefix():
    """FQN with leading 'postgres.' prefix must be stripped before calling get_columns."""
    from scanner.adapters.postgres import PostgresAdapter

    # Bypass __init__: get_table_schema only calls get_columns (patched below),
    # so adapter state is irrelevant. Avoids needing a real config dict that
    # would risk a real network call during construction.
    adapter = PostgresAdapter.__new__(PostgresAdapter)
    with patch.object(PostgresAdapter, "get_columns") as mock_cols:
        mock_cols.return_value = []
        adapter.get_table_schema("postgres.public.my_table")
        mock_cols.assert_called_once_with("public.my_table")


def test_get_table_schema_accepts_already_stripped_fqn():
    """FQN without leading 'postgres.' prefix must be passed through unchanged."""
    from scanner.adapters.postgres import PostgresAdapter

    # Bypass __init__: get_table_schema only calls get_columns (patched below),
    # so adapter state is irrelevant. Avoids needing a real config dict that
    # would risk a real network call during construction.
    adapter = PostgresAdapter.__new__(PostgresAdapter)
    with patch.object(PostgresAdapter, "get_columns") as mock_cols:
        mock_cols.return_value = []
        adapter.get_table_schema("public.my_table")
        mock_cols.assert_called_once_with("public.my_table")


def test_get_table_schema_returns_plain_dicts():
    """Return value must be a list of dicts with the canonical keys."""
    from scanner.adapters.postgres import PostgresAdapter
    from scanner.adapters.base import ColumnMetadata

    # Bypass __init__: get_table_schema only calls get_columns (patched below),
    # so adapter state is irrelevant. Avoids needing a real config dict that
    # would risk a real network call during construction.
    adapter = PostgresAdapter.__new__(PostgresAdapter)
    fake_col = ColumnMetadata(name="created_at", data_type="timestamp", is_nullable=False)
    with patch.object(PostgresAdapter, "get_columns", return_value=[fake_col]):
        result = adapter.get_table_schema("postgres.public.my_table")

    assert result == [{"column_name": "created_at", "data_type": "timestamp", "is_nullable": False}]
