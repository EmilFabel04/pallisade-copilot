"""
Universal SQL Parser for Lineage Extraction
Uses sqlglot to parse SQL from any dialect and extract table dependencies.
"""

from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
import re

try:
    import sqlglot
    from sqlglot import exp
    SQLGLOT_AVAILABLE = True
except ImportError:
    SQLGLOT_AVAILABLE = False


@dataclass
class LineageInfo:
    """Represents lineage extracted from a single SQL statement"""
    sources: List[str]  # Tables read from (SELECT, JOIN)
    targets: List[str]  # Tables written to (INSERT, CREATE, MERGE)
    sql: str
    statement_type: str = "unknown"
    columns: Dict[str, List[str]] = field(default_factory=dict)  # Column-level lineage


@dataclass  
class ParseResult:
    """Result of parsing multiple SQL statements"""
    lineage_infos: List[LineageInfo]
    errors: List[str]
    dialect: str
    total_statements: int
    successful_parses: int


class UniversalLineageParser:
    """
    Universal SQL parser that extracts lineage from any SQL dialect.
    
    Supported dialects:
    - snowflake, bigquery, databricks, redshift
    - postgres, mysql, duckdb, trino, spark
    - sqlite, oracle, mssql, and more
    """
    
    # Mapping of common dialect names to sqlglot dialect names
    DIALECT_MAP = {
        'snowflake': 'snowflake',
        'bigquery': 'bigquery', 
        'databricks': 'databricks',
        'spark': 'spark',
        'redshift': 'redshift',
        'postgres': 'postgres',
        'postgresql': 'postgres',
        'mysql': 'mysql',
        'duckdb': 'duckdb',
        'trino': 'trino',
        'presto': 'presto',
        'sqlite': 'sqlite',
        'oracle': 'oracle',
        'mssql': 'tsql',
        'sqlserver': 'tsql',
    }
    
    # Statement types that create/modify tables
    WRITE_STATEMENTS = {
        'CREATE', 'CREATE_TABLE', 'CREATE_TABLE_AS_SELECT', 'CTAS',
        'INSERT', 'INSERT_INTO', 'MERGE', 'UPDATE', 'DELETE',
        'CREATE_VIEW', 'CREATE_MATERIALIZED_VIEW'
    }
    
    def __init__(self, default_dialect: str = 'snowflake'):
        """Initialize parser with default dialect"""
        if not SQLGLOT_AVAILABLE:
            raise ImportError("sqlglot is required for lineage parsing. Install with: pip install sqlglot")
        
        self.default_dialect = self._normalize_dialect(default_dialect)
    
    def _normalize_dialect(self, dialect: str) -> str:
        """Normalize dialect name to sqlglot format"""
        dialect_lower = dialect.lower().strip()
        return self.DIALECT_MAP.get(dialect_lower, dialect_lower)
    
    def _normalize_table_name(self, table: exp.Table) -> str:
        """Extract fully qualified table name"""
        parts = []
        
        if table.catalog:
            parts.append(table.catalog)
        if table.db:
            parts.append(table.db)
        if table.name:
            parts.append(table.name)
            
        return '.'.join(parts) if parts else str(table)
    
    def _is_temp_table(self, table_name: str) -> bool:
        """Check if table is a temporary/CTE table"""
        lower = table_name.lower()
        return (
            lower.startswith('_') or
            lower.startswith('temp_') or
            lower.startswith('tmp_') or
            '#' in lower  # SQL Server temp tables
        )
    
    def parse_query(self, sql: str, dialect: Optional[str] = None) -> LineageInfo:
        """
        Parse a single SQL query and extract lineage.
        
        Args:
            sql: SQL query string
            dialect: SQL dialect (snowflake, bigquery, postgres, etc.)
            
        Returns:
            LineageInfo with source and target tables
        """
        dialect = self._normalize_dialect(dialect or self.default_dialect)
        
        sources: Set[str] = set()
        targets: Set[str] = set()
        statement_type = "unknown"
        
        try:
            # Parse SQL
            parsed = sqlglot.parse(sql, dialect=dialect)
            
            if not parsed:
                return LineageInfo(sources=[], targets=[], sql=sql, statement_type="parse_error")
            
            for statement in parsed:
                if statement is None:
                    continue
                    
                # Determine statement type
                statement_type = type(statement).__name__.upper()
                
                # Find target tables (CREATE, INSERT, MERGE)
                target_found = False
                
                # CREATE TABLE ... AS SELECT
                if isinstance(statement, exp.Create):
                    target_table = statement.this
                    if isinstance(target_table, exp.Table):
                        targets.add(self._normalize_table_name(target_table))
                        target_found = True
                    elif isinstance(target_table, exp.Schema):
                        # CREATE TABLE schema.table
                        table = target_table.this
                        if isinstance(table, exp.Table):
                            targets.add(self._normalize_table_name(table))
                            target_found = True
                
                # INSERT INTO
                elif isinstance(statement, exp.Insert):
                    target_table = statement.this
                    if isinstance(target_table, exp.Table):
                        targets.add(self._normalize_table_name(target_table))
                        target_found = True
                
                # MERGE INTO
                elif isinstance(statement, exp.Merge):
                    target_table = statement.this
                    if isinstance(target_table, exp.Table):
                        targets.add(self._normalize_table_name(target_table))
                        target_found = True
                
                # UPDATE
                elif isinstance(statement, exp.Update):
                    target_table = statement.this
                    if isinstance(target_table, exp.Table):
                        targets.add(self._normalize_table_name(target_table))
                        target_found = True
                
                # Find all source tables (FROM, JOIN, subqueries)
                for table in statement.find_all(exp.Table):
                    table_name = self._normalize_table_name(table)
                    
                    # Skip if it's the target table or a temp table
                    if table_name not in targets and not self._is_temp_table(table_name):
                        sources.add(table_name)
                
                # Handle CTEs - remove CTE names from sources
                for cte in statement.find_all(exp.CTE):
                    cte_name = cte.alias
                    if cte_name:
                        sources.discard(cte_name)
                        sources.discard(str(cte_name))
            
        except Exception as e:
            # If parsing fails, try regex fallback
            sources, targets = self._regex_fallback(sql)
            statement_type = "regex_fallback"
        
        return LineageInfo(
            sources=list(sources),
            targets=list(targets),
            sql=sql,
            statement_type=statement_type
        )
    
    def _regex_fallback(self, sql: str) -> Tuple[Set[str], Set[str]]:
        """
        Fallback regex-based extraction when sqlglot fails.
        Less accurate but handles malformed SQL.
        """
        sources = set()
        targets = set()
        
        # Clean SQL
        sql_clean = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)  # Remove comments
        sql_clean = re.sub(r'/\*.*?\*/', '', sql_clean, flags=re.DOTALL)
        sql_clean = ' '.join(sql_clean.split())  # Normalize whitespace
        
        # Find target (CREATE TABLE ... AS, INSERT INTO, MERGE INTO)
        create_match = re.search(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|MATERIALIZED\s+VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)',
            sql_clean, re.IGNORECASE
        )
        if create_match:
            targets.add(create_match.group(1))
        
        insert_match = re.search(r'INSERT\s+(?:INTO\s+)?([^\s(]+)', sql_clean, re.IGNORECASE)
        if insert_match:
            targets.add(insert_match.group(1))
        
        merge_match = re.search(r'MERGE\s+INTO\s+([^\s]+)', sql_clean, re.IGNORECASE)
        if merge_match:
            targets.add(merge_match.group(1))
        
        # Find sources (FROM, JOIN)
        from_matches = re.findall(r'FROM\s+([^\s,()]+)', sql_clean, re.IGNORECASE)
        join_matches = re.findall(r'JOIN\s+([^\s,()]+)', sql_clean, re.IGNORECASE)
        
        for table in from_matches + join_matches:
            table = table.strip('`"[]')
            if table.upper() not in ('SELECT', 'WHERE', 'GROUP', 'ORDER', 'HAVING'):
                if table not in targets:
                    sources.add(table)
        
        return sources, targets
    
    def parse_queries(self, queries: List[str], dialect: Optional[str] = None) -> ParseResult:
        """
        Parse multiple SQL queries and extract lineage from all.
        
        Args:
            queries: List of SQL query strings
            dialect: SQL dialect
            
        Returns:
            ParseResult with all lineage info
        """
        dialect = self._normalize_dialect(dialect or self.default_dialect)
        
        lineage_infos = []
        errors = []
        successful = 0
        
        for sql in queries:
            try:
                info = self.parse_query(sql, dialect)
                if info.sources or info.targets:
                    lineage_infos.append(info)
                    successful += 1
            except Exception as e:
                errors.append(f"Error parsing query: {str(e)[:100]}")
        
        return ParseResult(
            lineage_infos=lineage_infos,
            errors=errors,
            dialect=dialect,
            total_statements=len(queries),
            successful_parses=successful
        )
    
    def extract_tables_from_sql(self, sql: str, dialect: Optional[str] = None) -> Dict[str, List[str]]:
        """
        Simple method to extract all tables from SQL.
        
        Returns:
            Dict with 'sources' and 'targets' keys
        """
        info = self.parse_query(sql, dialect)
        return {
            'sources': info.sources,
            'targets': info.targets
        }


# Convenience function
def parse_sql_lineage(sql: str, dialect: str = 'snowflake') -> LineageInfo:
    """Quick function to parse SQL and extract lineage"""
    parser = UniversalLineageParser(dialect)
    return parser.parse_query(sql, dialect)

