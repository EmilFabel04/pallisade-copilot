"""
Enterprise Database Adapters for Pallisade

Provides a unified interface for connecting to and querying various databases
with support for deep statistics, query history, and data sampling.
"""

from .base import (
    DatabaseAdapter,
    TableMetadata,
    ColumnMetadata,
    ColumnStats,
    QueryHistoryEntry,
    AdapterCapabilities,
)
from .factory import AdapterFactory, get_adapter

__all__ = [
    'DatabaseAdapter',
    'TableMetadata',
    'ColumnMetadata', 
    'ColumnStats',
    'QueryHistoryEntry',
    'AdapterCapabilities',
    'AdapterFactory',
    'get_adapter',
]

