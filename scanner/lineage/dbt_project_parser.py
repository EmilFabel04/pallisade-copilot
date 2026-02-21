"""
Parse raw dbt project files into a manifest-like structure.

Instead of requiring a compiled manifest.json (which lives in target/ and is
gitignored), this module reads the raw SQL models and YAML schema files that
ARE committed to git and builds a pseudo-manifest that LiveDbtAdapter can
consume.

Supports:
- Extracting ref() and source() calls from SQL models
- Parsing schema.yml / sources.yml for source definitions
- Parsing dbt_project.yml for project config
"""

import logging
import re
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Regex patterns for Jinja ref/source calls
_REF_PATTERN = re.compile(
    r"""\{\{\s*ref\s*\(\s*['"](\w+)['"]\s*\)\s*\}\}""",
    re.IGNORECASE,
)
_SOURCE_PATTERN = re.compile(
    r"""\{\{\s*source\s*\(\s*['"](\w+)['"]\s*,\s*['"](\w+)['"]\s*\)\s*\}\}""",
    re.IGNORECASE,
)
_CONFIG_PATTERN = re.compile(
    r"""\{\{\s*config\s*\(([^)]*)\)\s*\}\}""",
    re.IGNORECASE | re.DOTALL,
)


def extract_refs(sql: str) -> List[str]:
    """Extract model names from {{ ref('model_name') }} calls."""
    return _REF_PATTERN.findall(sql)


def extract_sources(sql: str) -> List[Tuple[str, str]]:
    """Extract (source_name, table_name) from {{ source('src', 'table') }} calls."""
    return _SOURCE_PATTERN.findall(sql)


def extract_config(sql: str) -> Dict[str, str]:
    """Extract config kwargs from {{ config(...) }} block."""
    match = _CONFIG_PATTERN.search(sql)
    if not match:
        return {}
    config_str = match.group(1)
    result: Dict[str, str] = {}
    # Simple key=value parser for common dbt config params
    for kv in re.finditer(r"""(\w+)\s*=\s*['"]([\w_]+)['"]""", config_str):
        result[kv.group(1)] = kv.group(2)
    return result


def parse_schema_yaml(content: str) -> Dict[str, Any]:
    """
    Parse a dbt schema.yml / sources.yml file.

    Returns dict with:
        sources: list of source definitions
        models: list of model documentation
    """
    try:
        import yaml
    except ImportError:
        logger.warning("[DbtProjectParser] PyYAML not available")
        return {"sources": [], "models": []}

    try:
        data = yaml.safe_load(content)
    except Exception as e:
        logger.warning(f"[DbtProjectParser] Failed to parse YAML: {e}")
        return {"sources": [], "models": []}

    if not isinstance(data, dict):
        return {"sources": [], "models": []}

    return {
        "sources": data.get("sources", []),
        "models": data.get("models", []),
    }


def parse_dbt_project(
    files: Dict[str, str],
    project_name: str = "",
    default_database: str = "",
    default_schema: str = "",
    warehouse_type: str = "bigquery",
) -> Dict[str, Any]:
    """
    Parse raw dbt project files into a manifest-compatible dict.

    Args:
        files: mapping of relative file paths to their content
               e.g. {"models/staging/stg_orders.sql": "SELECT ...", "models/schema.yml": "..."}
        project_name: dbt project name (from dbt_project.yml or user input)
        default_database: default database for models without explicit config
        default_schema: default schema for models without explicit config
        warehouse_type: target warehouse type

    Returns:
        Dict compatible with LiveDbtAdapter's expected manifest format:
        {
            "nodes": {"model.project.name": {...}, ...},
            "sources": {"source.project.src.table": {...}, ...},
            "metadata": {"dbt_version": "project_parser", ...},
        }
    """
    # Try to read dbt_project.yml first
    for path, content in files.items():
        if PurePosixPath(path).name == "dbt_project.yml":
            try:
                import yaml
                proj = yaml.safe_load(content)
                if isinstance(proj, dict):
                    project_name = project_name or proj.get("name", "")
            except Exception:
                pass
            break

    if not project_name:
        project_name = "dbt_project"

    nodes: Dict[str, Any] = {}
    sources: Dict[str, Any] = {}
    model_docs: Dict[str, Dict] = {}  # model name → doc from schema.yml

    # --- Pass 1: Parse all YAML files for source definitions + model docs ---
    for path, content in files.items():
        lower = path.lower()
        if not (lower.endswith(".yml") or lower.endswith(".yaml")):
            continue
        if PurePosixPath(path).name == "dbt_project.yml":
            continue  # Already handled above

        parsed = parse_schema_yaml(content)

        # Source definitions
        for source_def in parsed.get("sources", []):
            if not isinstance(source_def, dict):
                continue
            source_name = source_def.get("name", "")
            source_db = source_def.get("database", default_database)
            source_schema = source_def.get("schema", source_name)
            source_desc = source_def.get("description", "")

            for table_def in source_def.get("tables", []):
                if not isinstance(table_def, dict):
                    continue
                table_name = table_def.get("name", "")
                if not table_name:
                    continue

                unique_id = f"source.{project_name}.{source_name}.{table_name}"
                sources[unique_id] = {
                    "resource_type": "source",
                    "unique_id": unique_id,
                    "name": table_def.get("identifier", table_name),
                    "identifier": table_def.get("identifier", table_name),
                    "source_name": source_name,
                    "database": source_db,
                    "schema": source_schema,
                    "description": table_def.get("description", source_desc),
                    "tags": table_def.get("tags", []),
                    "meta": table_def.get("meta", {}),
                    "columns": {
                        c["name"]: c
                        for c in table_def.get("columns", [])
                        if isinstance(c, dict) and c.get("name")
                    },
                }

        # Model documentation (enriches SQL models)
        for model_doc in parsed.get("models", []):
            if not isinstance(model_doc, dict):
                continue
            name = model_doc.get("name", "")
            if name:
                model_docs[name] = model_doc

    # --- Pass 2: Parse all SQL files as models ---
    for path, content in files.items():
        if not path.lower().endswith(".sql"):
            continue

        # Skip macros and tests
        path_parts = PurePosixPath(path).parts
        if any(p in ("macros", "tests", "analyses", "snapshots") for p in path_parts):
            continue

        model_name = PurePosixPath(path).stem
        refs = extract_refs(content)
        srcs = extract_sources(content)
        config = extract_config(content)

        # Build depends_on
        depends_on_nodes: List[str] = []
        for ref_name in refs:
            depends_on_nodes.append(f"model.{project_name}.{ref_name}")
        for src_name, tbl_name in srcs:
            depends_on_nodes.append(f"source.{project_name}.{src_name}.{tbl_name}")

        # Determine schema from config or path
        model_schema = config.get("schema", default_schema)
        materialized = config.get("materialized", "view")

        # Get doc enrichment from schema.yml
        doc = model_docs.get(model_name, {})

        unique_id = f"model.{project_name}.{model_name}"
        nodes[unique_id] = {
            "resource_type": "model",
            "unique_id": unique_id,
            "name": model_name,
            "alias": config.get("alias", model_name),
            "database": default_database,
            "schema": model_schema,
            "description": doc.get("description", ""),
            "tags": doc.get("tags", []),
            "meta": doc.get("meta", {}),
            "config": {
                "materialized": materialized,
                "schema": config.get("schema", ""),
            },
            "depends_on": {"nodes": depends_on_nodes},
            "columns": {
                c["name"]: c
                for c in doc.get("columns", [])
                if isinstance(c, dict) and c.get("name")
            },
            "raw_sql": content,
        }

    logger.info(
        f"[DbtProjectParser] Parsed {len(nodes)} models, {len(sources)} sources "
        f"from {sum(1 for p in files if p.endswith('.sql'))} SQL files"
    )

    return {
        "nodes": nodes,
        "sources": sources,
        "metadata": {
            "dbt_version": "project_parser",
            "project_name": project_name,
            "generated_at": None,
        },
    }


def parse_dbt_project_zip(
    zip_bytes: bytes,
    project_name: str = "",
    default_database: str = "",
    default_schema: str = "",
    warehouse_type: str = "bigquery",
) -> Dict[str, Any]:
    """
    Parse a zip file containing a dbt project.

    Extracts SQL and YAML files from the zip and delegates to parse_dbt_project().
    """
    import io
    import zipfile

    files: Dict[str, str] = {}

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                lower = name.lower()
                # Only extract relevant files
                if lower.endswith((".sql", ".yml", ".yaml")):
                    try:
                        content = zf.read(name).decode("utf-8")
                        # Strip common root directory prefix
                        # e.g. "my-dbt-project/models/x.sql" → "models/x.sql"
                        files[name] = content
                    except (UnicodeDecodeError, KeyError):
                        continue
    except zipfile.BadZipFile:
        logger.error("[DbtProjectParser] Invalid zip file")
        return {"nodes": {}, "sources": {}, "metadata": {}}

    # Strip common root directory prefix
    if files:
        paths = list(files.keys())
        # Find common prefix
        parts_list = [PurePosixPath(p).parts for p in paths]
        if len(parts_list) > 1:
            common_parts: List[str] = []
            for level_parts in zip(*parts_list):
                if len(set(level_parts)) == 1:
                    common_parts.append(level_parts[0])
                else:
                    break
            if common_parts:
                prefix_len = len("/".join(common_parts)) + 1
                files = {p[prefix_len:]: c for p, c in files.items() if len(p) > prefix_len}

    logger.info(f"[DbtProjectParser] Extracted {len(files)} files from zip")

    return parse_dbt_project(
        files=files,
        project_name=project_name,
        default_database=default_database,
        default_schema=default_schema,
        warehouse_type=warehouse_type,
    )
