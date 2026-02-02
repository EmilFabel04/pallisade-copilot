"""
Stack-specific lineage parsers.

Each parser extracts lineage information from a specific platform or tool.
"""

from .base import BaseParser
from .dbt import DbtManifestParser
from .snowflake import SnowflakeQueryParser
from .bigquery import BigQueryParser
from .sqlserver import SQLServerParser
from .foreign_keys import ForeignKeyParser
from .sql_parser import SQLLineageParser

__all__ = [
    'BaseParser',
    'DbtManifestParser',
    'SnowflakeQueryParser',
    'BigQueryParser',
    'SQLServerParser',
    'ForeignKeyParser',
    'SQLLineageParser',
]

