"""
SQL Lineage Parser

Extracts table references from SQL queries to build lineage.
Supports multiple SQL dialects through pattern-based parsing.
"""

import re
from typing import Dict, List, Set, Tuple, Any, Optional
from .base import BaseParser
from ..graph import LineageGraph, LineageNode, EdgeType, NodeType


class SQLLineageParser(BaseParser):
    """
    Parse SQL queries to extract table lineage.
    
    This is a dialect-aware parser that can handle:
    - Snowflake
    - BigQuery
    - PostgreSQL
    - SQL Server / Azure SQL
    - Redshift
    - Databricks
    """
    
    PLATFORM = "query_history"
    
    # Dialect-specific patterns
    DIALECT_PATTERNS = {
        "snowflake": {
            "identifier": r'(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_$]*))',
            "schema_sep": r"\.",
            "comment_single": "--",
            "comment_multi_start": "/*",
            "comment_multi_end": "*/",
        },
        "bigquery": {
            "identifier": r'(?:`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*))',
            "schema_sep": r"\.",
            "comment_single": "--",
            "comment_multi_start": "/*",
            "comment_multi_end": "*/",
        },
        "postgres": {
            "identifier": r'(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_$]*))',
            "schema_sep": r"\.",
            "comment_single": "--",
            "comment_multi_start": "/*",
            "comment_multi_end": "*/",
        },
        "tsql": {
            "identifier": r'(?:\[([^\]]+)\]|"([^"]+)"|([A-Za-z_][A-Za-z0-9_$@#]*))',
            "schema_sep": r"\.",
            "comment_single": "--",
            "comment_multi_start": "/*",
            "comment_multi_end": "*/",
        },
        "redshift": {
            "identifier": r'(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_$]*))',
            "schema_sep": r"\.",
            "comment_single": "--",
            "comment_multi_start": "/*",
            "comment_multi_end": "*/",
        },
    }
    
    def __init__(self, dialect: str = "snowflake", queries: List[Dict[str, Any]] = None, **kwargs):
        super().__init__(**kwargs)
        self.dialect = dialect.lower()
        self.DIALECT = dialect
        self.queries = queries or []
        self.patterns = self.DIALECT_PATTERNS.get(self.dialect, self.DIALECT_PATTERNS["postgres"])
        
        # Build table reference pattern
        ident = self.patterns["identifier"]
        sep = self.patterns["schema_sep"]
        # Match: table, schema.table, or database.schema.table
        self.table_pattern = re.compile(
            rf'(?:{ident}{sep})?(?:{ident}{sep})?{ident}',
            re.IGNORECASE
        )
    
    def parse(self) -> LineageGraph:
        """Parse all queries and build lineage."""
        for query_info in self.queries:
            try:
                sql = query_info.get("query_text", "")
                target = query_info.get("target_table")  # For INSERT/CREATE
                timestamp = query_info.get("timestamp")
                
                self._parse_query(sql, target, timestamp)
            except Exception as e:
                self.add_error(f"Failed to parse query: {e}")
        
        self.graph.compute_depths()
        return self.graph
    
    def parse_single(self, sql: str, target_table: str = None) -> Tuple[Set[str], Optional[str]]:
        """
        Parse a single SQL query.
        
        Returns:
            Tuple of (source_tables, target_table)
        """
        # Remove comments
        sql = self._remove_comments(sql)
        
        # Detect query type and target
        target, sources = self._extract_tables(sql)
        
        if target_table:
            target = target_table
        
        return sources, target
    
    def parse_with_columns(self, sql: str, target_table: str = None) -> Dict[str, Any]:
        """
        Parse a single SQL query with column-level lineage.
        
        Returns:
            Dict containing:
            - source_tables: Set of source table names
            - target_table: Target table name (if any)
            - column_lineage: List of column mappings
              Each mapping: {target_column, source_table, source_column, transform}
        """
        # Remove comments
        sql = self._remove_comments(sql)
        
        # Detect query type and target
        target, sources = self._extract_tables(sql)
        
        if target_table:
            target = target_table
        
        # Extract column lineage
        column_lineage = self._extract_column_lineage(sql, sources)
        
        return {
            "source_tables": sources,
            "target_table": target,
            "column_lineage": column_lineage,
        }
    
    def _extract_column_lineage(self, sql: str, source_tables: Set[str]) -> List[Dict[str, Any]]:
        """
        Extract column-level lineage from SQL SELECT clause.
        
        Returns list of column mappings:
        [
            {
                "target_column": "customer_name",
                "source_table": "customers",
                "source_column": "name",
                "transform": "UPPER(customers.name)",
                "is_direct": False  # True if no transformation
            },
            ...
        ]
        """
        column_lineage = []
        
        try:
            # Find the main SELECT clause
            select_match = re.search(
                r'\bSELECT\s+((?:(?!FROM\s+(?!.*\bSELECT\b)).)*?)\s+FROM\b',
                sql,
                re.IGNORECASE | re.DOTALL
            )
            
            if not select_match:
                return column_lineage
            
            select_clause = select_match.group(1)
            
            # Handle SELECT *
            if select_clause.strip() == '*':
                return column_lineage
            
            # Split by comma, but respect parentheses for function calls
            columns = self._split_select_columns(select_clause)
            
            # Build table alias map
            alias_map = self._build_alias_map(sql)
            
            for col_expr in columns:
                col_expr = col_expr.strip()
                if not col_expr or col_expr == '*':
                    continue
                
                # Parse column expression
                mapping = self._parse_column_expression(col_expr, source_tables, alias_map)
                if mapping:
                    column_lineage.append(mapping)
                    
        except Exception:
            # Column lineage extraction failed, return empty list
            pass
        
        return column_lineage
    
    def _split_select_columns(self, select_clause: str) -> List[str]:
        """Split SELECT columns by comma, respecting parentheses and nested calls."""
        columns = []
        current = ""
        paren_depth = 0
        
        for char in select_clause:
            if char == '(':
                paren_depth += 1
                current += char
            elif char == ')':
                paren_depth -= 1
                current += char
            elif char == ',' and paren_depth == 0:
                columns.append(current.strip())
                current = ""
            else:
                current += char
        
        if current.strip():
            columns.append(current.strip())
        
        return columns
    
    def _build_alias_map(self, sql: str) -> Dict[str, str]:
        """Build a map of table aliases to full table names."""
        alias_map = {}
        
        # Pattern: table_name AS alias or table_name alias
        pattern = r'\b(?:FROM|JOIN)\s+([^\s,;()]+)\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*)\b'
        
        for match in re.finditer(pattern, sql, re.IGNORECASE):
            table_name = self._normalize_table_name(match.group(1))
            alias = match.group(2).lower()
            
            if table_name and alias and alias.upper() not in ('ON', 'AND', 'OR', 'WHERE', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'CROSS', 'FULL'):
                alias_map[alias] = table_name
        
        return alias_map
    
    def _parse_column_expression(
        self, 
        expr: str, 
        source_tables: Set[str],
        alias_map: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """
        Parse a single column expression to extract lineage.
        
        Handles:
        - Simple column: column_name
        - Qualified column: table.column_name
        - Aliased: expression AS alias
        - Functions: UPPER(column)
        """
        # Check for AS alias
        target_column = None
        as_match = re.search(r'\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$', expr, re.IGNORECASE)
        if as_match:
            target_column = as_match.group(1).lower()
            expr = expr[:as_match.start()].strip()
        
        # Check for qualified column reference (table.column)
        qual_match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\.([A-Za-z_][A-Za-z0-9_]*)\s*$', expr)
        
        if qual_match:
            # Direct column reference
            table_ref = qual_match.group(1).lower()
            source_column = qual_match.group(2).lower()
            
            # Resolve alias to table name
            source_table = alias_map.get(table_ref, table_ref)
            
            if not target_column:
                target_column = source_column
            
            return {
                "target_column": target_column,
                "source_table": source_table,
                "source_column": source_column,
                "transform": None,
                "is_direct": True,
            }
        
        # Check for simple column reference (no table prefix)
        simple_match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*$', expr)
        if simple_match:
            source_column = simple_match.group(1).lower()
            
            if not target_column:
                target_column = source_column
            
            # Can't determine source table without prefix
            return {
                "target_column": target_column,
                "source_table": None,
                "source_column": source_column,
                "transform": None,
                "is_direct": True,
            }
        
        # Expression with transformation (function call, arithmetic, etc.)
        # Extract column references from within the expression
        column_refs = self._extract_column_refs_from_expr(expr, alias_map)
        
        if column_refs and not target_column:
            # Use the last part of expression or first column as target
            target_column = f"expr_{len(column_refs)}"
        
        if column_refs:
            # Take the first column reference as the primary source
            first_ref = column_refs[0]
            return {
                "target_column": target_column,
                "source_table": first_ref.get("table"),
                "source_column": first_ref.get("column"),
                "transform": expr,
                "is_direct": False,
                "all_sources": column_refs,  # All referenced columns
            }
        
        return None
    
    def _extract_column_refs_from_expr(
        self, 
        expr: str, 
        alias_map: Dict[str, str]
    ) -> List[Dict[str, str]]:
        """Extract all column references from an expression."""
        refs = []
        
        # Pattern for qualified columns (table.column)
        qual_pattern = r'\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b'
        
        for match in re.finditer(qual_pattern, expr):
            table_ref = match.group(1).lower()
            column = match.group(2).lower()
            
            # Skip function names
            if table_ref.upper() in ('CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN'):
                continue
            
            source_table = alias_map.get(table_ref, table_ref)
            refs.append({"table": source_table, "column": column})
        
        return refs
    
    def _parse_query(self, sql: str, target_override: str = None, 
                     timestamp: Any = None) -> None:
        """Parse a query and add to graph."""
        sources, target = self.parse_single(sql, target_override)
        
        if not sources:
            return
        
        # Ensure all source nodes exist
        for source_fqn in sources:
            if self.generate_node_id(source_fqn) not in self.graph.nodes:
                node = self.create_table_node(source_fqn)
                self.graph.add_node(node)
        
        # If we have a target, create edges
        if target:
            target_id = self.generate_node_id(target)
            if target_id not in self.graph.nodes:
                node = self.create_table_node(target)
                self.graph.add_node(node)
            
            for source_fqn in sources:
                source_id = self.generate_node_id(source_fqn)
                edge = self.create_edge(
                    source_id=source_id,
                    target_id=target_id,
                    edge_type=EdgeType.DERIVED_FROM,
                )
                self.graph.add_edge(edge)
    
    def _remove_comments(self, sql: str) -> str:
        """Remove SQL comments."""
        # Remove multi-line comments
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        # Remove single-line comments
        sql = re.sub(r'--[^\n]*', '', sql)
        return sql
    
    def _extract_tables(self, sql: str) -> Tuple[Optional[str], Set[str]]:
        """
        Extract target and source tables from SQL.
        
        Returns:
            (target_table, set of source_tables)
        """
        sql_upper = sql.upper().strip()
        target = None
        sources = set()
        
        # Detect query type
        if sql_upper.startswith("CREATE"):
            target = self._extract_create_target(sql)
            sources = self._extract_from_tables(sql)
        elif sql_upper.startswith("INSERT"):
            target = self._extract_insert_target(sql)
            sources = self._extract_from_tables(sql)
        elif sql_upper.startswith("MERGE"):
            target = self._extract_merge_target(sql)
            sources = self._extract_from_tables(sql)
        elif sql_upper.startswith("UPDATE"):
            target = self._extract_update_target(sql)
            sources = self._extract_from_tables(sql)
        elif sql_upper.startswith("SELECT"):
            # SELECT without target - just extract sources
            sources = self._extract_from_tables(sql)
        elif sql_upper.startswith("WITH"):
            # CTE - extract final SELECT sources
            sources = self._extract_from_tables(sql)
            # Check if it ends with INSERT/CREATE
            if "INSERT INTO" in sql_upper:
                target = self._extract_insert_target(sql)
            elif "CREATE" in sql_upper:
                target = self._extract_create_target(sql)
        
        return target, sources
    
    def _extract_create_target(self, sql: str) -> Optional[str]:
        """Extract target table from CREATE statement."""
        patterns = [
            r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?(?:TABLE|VIEW|MATERIALIZED\s+VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return self._normalize_table_name(match.group(1))
        return None
    
    def _extract_insert_target(self, sql: str) -> Optional[str]:
        """Extract target table from INSERT statement."""
        pattern = r'INSERT\s+(?:INTO\s+)?([^\s(]+)'
        match = re.search(pattern, sql, re.IGNORECASE)
        if match:
            return self._normalize_table_name(match.group(1))
        return None
    
    def _extract_merge_target(self, sql: str) -> Optional[str]:
        """Extract target table from MERGE statement."""
        pattern = r'MERGE\s+(?:INTO\s+)?([^\s]+)'
        match = re.search(pattern, sql, re.IGNORECASE)
        if match:
            return self._normalize_table_name(match.group(1))
        return None
    
    def _extract_update_target(self, sql: str) -> Optional[str]:
        """Extract target table from UPDATE statement."""
        pattern = r'UPDATE\s+([^\s]+)'
        match = re.search(pattern, sql, re.IGNORECASE)
        if match:
            return self._normalize_table_name(match.group(1))
        return None
    
    def _extract_from_tables(self, sql: str) -> Set[str]:
        """Extract all source tables from FROM/JOIN clauses."""
        tables = set()
        
        # Pattern for FROM and JOIN
        # Handles: FROM table, FROM table alias, FROM table AS alias
        from_pattern = r'\b(?:FROM|JOIN)\s+([^\s,;()]+)(?:\s+(?:AS\s+)?[A-Za-z_][A-Za-z0-9_]*)?'
        
        for match in re.finditer(from_pattern, sql, re.IGNORECASE):
            table_ref = match.group(1)
            
            # Skip subqueries and CTEs
            if table_ref.upper() in ('SELECT', 'WITH', '('):
                continue
            
            # Skip common keywords that might be matched
            keywords = {'LATERAL', 'UNNEST', 'GENERATE_SERIES', 'VALUES', 'TABLE'}
            if table_ref.upper() in keywords:
                continue
            
            table_name = self._normalize_table_name(table_ref)
            if table_name:
                tables.add(table_name)
        
        return tables
    
    def _normalize_table_name(self, name: str) -> Optional[str]:
        """Normalize a table name, removing quotes and brackets."""
        if not name:
            return None
        
        # Remove quotes, brackets, backticks
        name = re.sub(r'[\[\]"`]', '', name)
        
        # Skip if it looks like a function or keyword
        if '(' in name or name.upper() in ('SELECT', 'FROM', 'WHERE', 'AND', 'OR'):
            return None
        
        return name.lower().strip()


class SnowflakeQueryHistoryParser(SQLLineageParser):
    """Parse Snowflake query history for lineage."""
    
    PLATFORM = "snowflake"
    
    def __init__(self, connection, days_back: int = 30, **kwargs):
        super().__init__(dialect="snowflake", **kwargs)
        self.connection = connection
        self.days_back = days_back
    
    def parse(self) -> LineageGraph:
        """Fetch query history and parse for lineage."""
        try:
            cursor = self.connection.cursor()
            
            # Query for DDL and DML statements
            query = f"""
                SELECT 
                    query_id,
                    query_text,
                    query_type,
                    database_name,
                    schema_name,
                    start_time,
                    user_name
                FROM snowflake.account_usage.query_history
                WHERE start_time >= DATEADD(day, -{self.days_back}, CURRENT_TIMESTAMP())
                AND query_type IN ('CREATE_TABLE', 'CREATE_TABLE_AS_SELECT', 
                                   'INSERT', 'MERGE', 'UPDATE', 'CREATE_VIEW')
                AND execution_status = 'SUCCESS'
                ORDER BY start_time DESC
                LIMIT 10000
            """
            
            cursor.execute(query)
            
            for row in cursor.fetchall():
                query_text = row[1]
                database = row[3]
                schema = row[4]
                
                # Add context for relative table references
                self.queries.append({
                    "query_text": query_text,
                    "database": database,
                    "schema": schema,
                    "timestamp": row[5],
                })
            
            cursor.close()
            
        except Exception as e:
            self.add_error(f"Failed to fetch query history: {e}")
        
        return super().parse()

