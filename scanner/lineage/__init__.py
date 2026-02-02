"""
Pallisade Lineage & Impact Analysis System

A comprehensive, stack-aware lineage system that:
1. Builds dependency graphs from multiple sources (dbt, query history, FKs, BI tools)
2. Performs root cause analysis to deduplicate cascading issues
3. Calculates blast radius for impact analysis
4. Supports multiple SQL dialects and tech stacks
"""

from .graph import LineageGraph, LineageNode, LineageEdge
from .builder import LineageBuilder
from .parser import UniversalLineageParser, LineageInfo
from .parsers import (
    DbtManifestParser,
    SnowflakeQueryParser,
    BigQueryParser,
    SQLServerParser,
    ForeignKeyParser,
)
from .analyzer import ImpactAnalyzer, RootCauseAnalyzer
from .deduplicator import FindingDeduplicator

__all__ = [
    'LineageGraph',
    'LineageNode', 
    'LineageEdge',
    'LineageBuilder',
    'UniversalLineageParser',
    'LineageInfo',
    'DbtManifestParser',
    'SnowflakeQueryParser',
    'BigQueryParser',
    'SQLServerParser',
    'ForeignKeyParser',
    'ImpactAnalyzer',
    'RootCauseAnalyzer',
    'FindingDeduplicator',
]
