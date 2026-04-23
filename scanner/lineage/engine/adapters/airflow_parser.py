"""
Airflow DAG File Parser — AST-based extraction of DAG structure.

Parses Airflow DAG Python files using the ``ast`` module (no code execution)
to extract DAGs, tasks, dependencies, and table references from operators.
"""

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Operators where we cannot infer table reads/writes
_OPAQUE_OPERATORS = {
    "PythonOperator",
    "BashOperator",
    "DummyOperator",
    "EmptyOperator",
    "ShortCircuitOperator",
    "BranchPythonOperator",
    "BranchDateTimeOperator",
    "TriggerDagRunOperator",
    "ExternalTaskSensor",
    "TimeSensor",
    "TimeDeltaSensor",
    "PythonSensor",
    "FileSensor",
    "HttpSensor",
    "SqlSensor",
    "EmailOperator",
    "SlackAPIPostOperator",
}

# Kwargs that hold SQL strings, ordered by precedence
_SQL_KWARGS = ("sql", "query", "configuration")

# Kwargs that hold destination table references
_DEST_TABLE_KWARGS = (
    "destination_dataset_table",
    "destination_table",
    "target_table",
    "table",
    "table_id",
    "schema_table",
)

# Kwargs that hold source table references
_SOURCE_TABLE_KWARGS = (
    "source_project_dataset_table",
    "source_table",
    "bucket_table",
)


@dataclass
class ParsedTask:
    """A single task extracted from a DAG file."""
    task_id: str
    operator_class: str
    sql: Optional[str] = None
    destination_table: Optional[str] = None
    source_tables: List[str] = field(default_factory=list)
    is_opaque: bool = False
    line_number: int = 0
    kwargs: Dict[str, str] = field(default_factory=dict)
    bash_command: Optional[str] = None  # BashOperator bash_command content


@dataclass
class ParsedDag:
    """A complete DAG extracted from a file."""
    dag_id: str
    file_path: str
    schedule: Optional[str] = None
    owner: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    description: Optional[str] = None
    tasks: Dict[str, ParsedTask] = field(default_factory=dict)
    dependencies: List[Tuple[str, str]] = field(default_factory=list)  # (upstream, downstream)


# ---------------------------------------------------------------------------
# SQL table extraction (lightweight regex, not a full parser)
# ---------------------------------------------------------------------------

_JINJA_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)

# Matches schema.table or project.schema.table patterns
_TABLE_REF_RE = re.compile(
    r"""
    (?:FROM|JOIN|INTO|TABLE|MERGE\s+INTO|UPDATE)\s+
    [`"\[]?                     # optional quoting
    ([\w*]+(?:\.[\w*]+){0,2})   # 1-3 dotted parts
    [`"\]]?                     # optional close quote
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _strip_jinja(sql: str) -> str:
    """Remove Jinja template expressions ({{ ... }}) from SQL."""
    return _JINJA_RE.sub("__JINJA__", sql)


def _extract_tables_from_sql(sql: str) -> Tuple[List[str], Optional[str]]:
    """
    Extract table references from a SQL string.

    Returns (source_tables, destination_table).
    The first INSERT INTO / CREATE TABLE / MERGE INTO target is the destination.
    All FROM / JOIN targets are source tables.
    """
    cleaned = _strip_jinja(sql)
    sources: List[str] = []
    dest: Optional[str] = None

    for match in _TABLE_REF_RE.finditer(cleaned):
        table = match.group(1).strip("`\"[]")
        # Skip placeholders
        if "__JINJA__" in table or table.startswith("__"):
            continue
        prefix = cleaned[max(0, match.start() - 30):match.start()].upper()
        is_write_ctx = any(kw in prefix for kw in ("INSERT", "INTO", "CREATE", "MERGE", "UPDATE"))
        if is_write_ctx and dest is None:
            dest = table
        elif not is_write_ctx:
            sources.append(table)
        else:
            # dest already set; false-positive write context → treat as source
            sources.append(table)

    # Deduplicate
    sources = list(dict.fromkeys(sources))
    return sources, dest


def _extract_sql_from_bq_configuration(config_ast: ast.Dict) -> Optional[str]:
    """Extract SQL from BigQuery configuration dict literal."""
    for key, val in zip(config_ast.keys, config_ast.values):
        key_str = _get_str_value(key)
        if key_str == "query" and isinstance(val, ast.Dict):
            for k2, v2 in zip(val.keys, val.values):
                k2_str = _get_str_value(k2)
                if k2_str == "query":
                    return _get_str_value(v2)
        elif key_str == "query" and isinstance(val, (ast.Constant, ast.Str)):
            return _get_str_value(val)
    return None


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _get_str_value(node: Optional[ast.AST]) -> Optional[str]:
    """Get a string value from an AST constant node."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _get_list_strs(node: ast.AST) -> List[str]:
    """Get a list of strings from an AST list node."""
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_get_str_value(e) for e in node.elts if _get_str_value(e)]
    return []


def _get_call_name(node: ast.Call) -> Optional[str]:
    """Get the simple name of a Call node's function."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _get_keyword_value(call: ast.Call, name: str) -> Optional[ast.AST]:
    """Get the value of a keyword argument from a Call node."""
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _get_keyword_str(call: ast.Call, name: str) -> Optional[str]:
    """Get a string keyword argument from a Call node."""
    val = _get_keyword_value(call, name)
    return _get_str_value(val)


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------

def _resolve_shift_chain(node: ast.AST) -> List[str]:
    """
    Resolve a chain like ``a >> b >> c`` to variable names.

    ``a >> b >> c`` parses as ``BinOp(BinOp(a, >>, b), >>, c)``.
    Returns the ordered list of variable names.
    """
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.BinOp):
        left = _resolve_shift_chain(node.left)
        right = _resolve_shift_chain(node.right)
        return left + right
    if isinstance(node, (ast.List, ast.Tuple)):
        names = []
        for elt in node.elts:
            names.extend(_resolve_shift_chain(elt))
        return names
    return []


class _DagVisitor(ast.NodeVisitor):
    """Walk an AST to extract DAG definitions, tasks, and dependencies."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.import_aliases: Dict[str, str] = {}  # local_name -> class name
        self.dags: Dict[str, ParsedDag] = {}
        self.tasks: Dict[str, ParsedTask] = {}  # var_name -> ParsedTask
        self.task_var_to_id: Dict[str, str] = {}  # var_name -> task_id
        self.deps: List[Tuple[str, str]] = []  # (upstream_var, downstream_var)
        self._current_dag_id: Optional[str] = None

    # --- Imports ---

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[-1]
            self.import_aliases[name] = alias.name.split(".")[-1]
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            local = alias.asname or alias.name
            self.import_aliases[local] = alias.name
        self.generic_visit(node)

    # --- With statement (with DAG(...) as dag:) ---

    def visit_With(self, node: ast.With):
        for item in node.items:
            if isinstance(item.context_expr, ast.Call):
                call_name = _get_call_name(item.context_expr)
                if call_name == "DAG":
                    dag = self._parse_dag_call(item.context_expr)
                    if dag:
                        self._current_dag_id = dag.dag_id
                        self.dags[dag.dag_id] = dag
        self.generic_visit(node)
        self._current_dag_id = None

    # --- Assignments ---

    def visit_Assign(self, node: ast.Assign):
        if isinstance(node.value, ast.Call):
            call_name = _get_call_name(node.value)
            if call_name == "DAG":
                dag = self._parse_dag_call(node.value)
                if dag and node.targets:
                    self.dags[dag.dag_id] = dag
                    self._current_dag_id = dag.dag_id
            elif call_name and call_name != "DAG":
                # Potential task assignment
                task = self._parse_task_call(node.value, call_name)
                if task and node.targets:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.tasks[target.id] = task
                            self.task_var_to_id[target.id] = task.task_id
        self.generic_visit(node)

    # --- @dag and @task decorators (TaskFlow API) ---

    def visit_FunctionDef(self, node: ast.FunctionDef):
        for dec in node.decorator_list:
            dec_name = None
            dec_call = None  # The Call node, if decorator has parentheses
            if isinstance(dec, ast.Name):
                dec_name = dec.id
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    dec_name = dec.func.id
                elif isinstance(dec.func, ast.Attribute):
                    dec_name = dec.func.attr
                dec_call = dec
            elif isinstance(dec, ast.Attribute):
                dec_name = dec.attr

            if dec_name == "dag":
                # @dag or @dag(...) decorator — defines a DAG
                dag = self._parse_dag_decorator(node, dec_call)
                if dag:
                    self._current_dag_id = dag.dag_id
                    self.dags[dag.dag_id] = dag
                    # Visit the function body so @task functions inside are captured
                    self.generic_visit(node)
                    self._current_dag_id = None
                    return

            if dec_name == "task":
                task = ParsedTask(
                    task_id=node.name,
                    operator_class="@task",
                    is_opaque=True,
                    line_number=node.lineno,
                )
                self.tasks[node.name] = task
                self.task_var_to_id[node.name] = node.name
                break
        self.generic_visit(node)

    def _parse_dag_decorator(
        self, func_node: ast.FunctionDef, dec_call: Optional[ast.Call],
    ) -> Optional[ParsedDag]:
        """Parse a @dag(...) decorator to create a ParsedDag."""
        dag_id = func_node.name  # Default: function name is the dag_id
        schedule = None
        description = None
        tags: List[str] = []
        owner = None

        if dec_call:
            # @dag("my_dag") — first positional arg is dag_id
            if dec_call.args:
                explicit_id = _get_str_value(dec_call.args[0])
                if explicit_id:
                    dag_id = explicit_id
            # @dag(dag_id="my_dag")
            kwarg_id = _get_keyword_str(dec_call, "dag_id")
            if kwarg_id:
                dag_id = kwarg_id

            schedule = (
                _get_keyword_str(dec_call, "schedule")
                or _get_keyword_str(dec_call, "schedule_interval")
            )
            description = _get_keyword_str(dec_call, "description")

            tags_node = _get_keyword_value(dec_call, "tags")
            tags = _get_list_strs(tags_node) if tags_node else []

            default_args_node = _get_keyword_value(dec_call, "default_args")
            if isinstance(default_args_node, ast.Dict):
                for k, v in zip(default_args_node.keys, default_args_node.values):
                    if _get_str_value(k) == "owner":
                        owner = _get_str_value(v)
                        break

        return ParsedDag(
            dag_id=dag_id,
            file_path=self.file_path,
            schedule=schedule,
            owner=owner,
            tags=tags,
            description=description,
        )

    # --- Expressions (a >> b, set_downstream, etc.) ---

    def visit_Expr(self, node: ast.Expr):
        val = node.value
        # a >> b >> c (BinOp with RShift/LShift)
        if isinstance(val, ast.BinOp):
            self._process_shift(val)
        # a.set_downstream(b) or a.set_upstream(b)
        elif isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute):
            method = val.func.attr
            obj = val.func.value
            if method == "set_downstream" and isinstance(obj, ast.Name) and val.args:
                targets = _resolve_shift_chain(val.args[0])
                for t in targets:
                    self.deps.append((obj.id, t))
            elif method == "set_upstream" and isinstance(obj, ast.Name) and val.args:
                targets = _resolve_shift_chain(val.args[0])
                for t in targets:
                    self.deps.append((t, obj.id))
        self.generic_visit(node)

    def _process_shift(self, node: ast.BinOp):
        """Flatten a >> b >> c or a << b into dependency pairs."""
        if isinstance(node.op, ast.RShift):
            chain = _resolve_shift_chain(node)
            for i in range(len(chain) - 1):
                self.deps.append((chain[i], chain[i + 1]))
        elif isinstance(node.op, ast.LShift):
            chain = _resolve_shift_chain(node)
            for i in range(len(chain) - 1):
                self.deps.append((chain[i + 1], chain[i]))

    # --- DAG parsing ---

    def _parse_dag_call(self, call: ast.Call) -> Optional[ParsedDag]:
        """Parse a DAG(...) constructor call."""
        dag_id = None
        # First positional arg is dag_id
        if call.args:
            dag_id = _get_str_value(call.args[0])
        if not dag_id:
            dag_id = _get_keyword_str(call, "dag_id")
        if not dag_id:
            return None

        schedule = (
            _get_keyword_str(call, "schedule")
            or _get_keyword_str(call, "schedule_interval")
        )
        description = _get_keyword_str(call, "description")

        tags_node = _get_keyword_value(call, "tags")
        tags = _get_list_strs(tags_node) if tags_node else []

        # Try to get owner from default_args
        owner = None
        default_args_node = _get_keyword_value(call, "default_args")
        if isinstance(default_args_node, ast.Dict):
            for k, v in zip(default_args_node.keys, default_args_node.values):
                if _get_str_value(k) == "owner":
                    owner = _get_str_value(v)
                    break

        return ParsedDag(
            dag_id=dag_id,
            file_path=self.file_path,
            schedule=schedule,
            owner=owner,
            tags=tags,
            description=description,
        )

    # --- Task parsing ---

    def _parse_task_call(self, call: ast.Call, class_name: str) -> Optional[ParsedTask]:
        """Parse a potential task constructor call (e.g., XxxOperator(...))."""
        task_id = _get_keyword_str(call, "task_id")
        if not task_id:
            return None

        resolved_class = self.import_aliases.get(class_name, class_name)
        is_opaque = resolved_class in _OPAQUE_OPERATORS or class_name in _OPAQUE_OPERATORS

        sql = None
        dest_table = None
        source_tables: List[str] = []

        if not is_opaque:
            # Extract SQL from kwargs
            for kw_name in _SQL_KWARGS:
                val_node = _get_keyword_value(call, kw_name)
                if val_node is None:
                    continue
                if isinstance(val_node, (ast.Constant,)):
                    sql = _get_str_value(val_node)
                    if sql:
                        break
                elif isinstance(val_node, ast.Dict) and kw_name == "configuration":
                    sql = _extract_sql_from_bq_configuration(val_node)
                    if sql:
                        # Also try to extract destination from configuration
                        dest_table = self._extract_dest_from_bq_config(val_node)
                        break

            # Extract destination table from kwargs
            if not dest_table:
                for kw_name in _DEST_TABLE_KWARGS:
                    dest_table = _get_keyword_str(call, kw_name)
                    if dest_table:
                        break

            # Extract source tables from kwargs
            for kw_name in _SOURCE_TABLE_KWARGS:
                src = _get_keyword_str(call, kw_name)
                if src:
                    source_tables.append(src)

            # If SQL found, extract table refs from it
            if sql:
                sql_sources, sql_dest = _extract_tables_from_sql(sql)
                source_tables.extend(sql_sources)
                if not dest_table and sql_dest:
                    dest_table = sql_dest

        # Extract bash_command from BashOperator (for orchestrated tool detection)
        bash_command = None
        if resolved_class in ("BashOperator", "BashSensor"):
            bash_command = _get_keyword_str(call, "bash_command")

        return ParsedTask(
            task_id=task_id,
            operator_class=resolved_class,
            sql=sql,
            destination_table=dest_table,
            source_tables=list(dict.fromkeys(source_tables)),  # dedup
            is_opaque=is_opaque,
            line_number=call.lineno,
            bash_command=bash_command,
        )

    def _extract_dest_from_bq_config(self, config_ast: ast.Dict) -> Optional[str]:
        """Extract destination table from BQ configuration dict."""
        for key, val in zip(config_ast.keys, config_ast.values):
            key_str = _get_str_value(key)
            if key_str == "query" and isinstance(val, ast.Dict):
                for k2, v2 in zip(val.keys, val.values):
                    k2_str = _get_str_value(k2)
                    if k2_str == "destinationTable" and isinstance(v2, ast.Dict):
                        parts = []
                        for k3, v3 in zip(v2.keys, v2.values):
                            k3_str = _get_str_value(k3)
                            v3_str = _get_str_value(v3)
                            if k3_str in ("projectId", "datasetId", "tableId") and v3_str:
                                parts.append(v3_str)
                        if parts:
                            return ".".join(parts)
            elif key_str == "destinationTable":
                return _get_str_value(val)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_dag_file(content: str, file_path: str = "<unknown>") -> List[ParsedDag]:
    """
    Parse a single Airflow DAG file and return extracted DAGs.

    Args:
        content: Python source code of the DAG file.
        file_path: File path for error reporting.

    Returns:
        List of ParsedDag objects found in the file.
    """
    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError as e:
        logger.warning(f"[AirflowParser] Syntax error in {file_path}: {e}")
        return []

    visitor = _DagVisitor(file_path)
    visitor.visit(tree)

    # Assign tasks and dependencies to their DAGs
    dags = list(visitor.dags.values())
    if not dags:
        logger.info(f"[AirflowParser] No DAGs found in {file_path} (imports: {list(visitor.import_aliases.keys())[:10]})")
        return []

    # If only one DAG, all tasks belong to it
    target_dag = dags[0] if len(dags) == 1 else None

    for var_name, task in visitor.tasks.items():
        dag = target_dag or (dags[0] if dags else None)
        if dag:
            dag.tasks[task.task_id] = task

    # Resolve variable-name deps to task_id deps
    for upstream_var, downstream_var in visitor.deps:
        up_id = visitor.task_var_to_id.get(upstream_var)
        down_id = visitor.task_var_to_id.get(downstream_var)
        if up_id and down_id and target_dag:
            target_dag.dependencies.append((up_id, down_id))

    return dags


def parse_dag_files(files: Dict[str, str]) -> List[ParsedDag]:
    """
    Parse multiple DAG files.

    Args:
        files: Mapping of filename → Python source content.

    Returns:
        All DAGs found across all files.
    """
    all_dags: List[ParsedDag] = []
    for file_path, content in files.items():
        if not file_path.endswith(".py"):
            continue
        try:
            dags = parse_dag_file(content, file_path)
            all_dags.extend(dags)
        except Exception as e:
            logger.warning(f"[AirflowParser] Failed to parse {file_path}: {e}")
    logger.info(f"[AirflowParser] Parsed {len(files)} files, found {len(all_dags)} DAGs")
    return all_dags
