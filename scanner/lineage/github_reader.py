"""
GitHub-based dbt project reader for lineage enrichment.

Reads dbt_project.yml and generate_schema_name.sql from a connected
GitHub repo to build schema mappings that improve cross-tool edge matching.
"""

import base64
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def fetch_github_file(
    repo: str, path: str, token: str, branch: str = "main"
) -> Optional[str]:
    """Fetch a single file from GitHub. Returns content string or None."""
    import aiohttp

    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Pallisade-Lineage/1.0",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params={"ref": branch}) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("type") != "file":
                    return None
                return base64.b64decode(data.get("content", "")).decode("utf-8")
    except Exception as e:
        logger.debug(f"[GitHub] Failed to fetch {path}: {e}")
        return None


async def read_dbt_project_config(
    repo: str, token: str, branch: str = "main", dbt_root: str = ""
) -> Dict[str, Any]:
    """
    Read dbt_project.yml and generate_schema_name macro from a GitHub repo.

    Returns dict with project config and detected schema pattern.
    """
    result: Dict[str, Any] = {
        "project_name": "",
        "model_paths": ["models"],
        "schema_override": None,
        "custom_schema_pattern": None,
        "vars": {},
    }

    prefix = f"{dbt_root}/" if dbt_root else ""

    # Read dbt_project.yml
    project_content = await fetch_github_file(
        repo, f"{prefix}dbt_project.yml", token, branch
    )
    if project_content:
        try:
            import yaml
            project = yaml.safe_load(project_content)
            result["project_name"] = project.get("name", "")
            result["model_paths"] = project.get("model-paths", project.get("source-paths", ["models"]))
            result["vars"] = project.get("vars", {})
            logger.info(f"[GitHub] Read dbt_project.yml: project={result['project_name']}")
        except Exception as e:
            logger.warning(f"[GitHub] Failed to parse dbt_project.yml: {e}")

    # Read generate_schema_name macro (common locations)
    for macro_path in [
        f"{prefix}macros/generate_schema_name.sql",
        f"{prefix}macros/get_custom_schema.sql",
        f"{prefix}macros/overrides/generate_schema_name.sql",
    ]:
        macro_content = await fetch_github_file(repo, macro_path, token, branch)
        if macro_content:
            result["schema_override"] = macro_content
            result["custom_schema_pattern"] = _detect_schema_pattern(macro_content)
            logger.info(f"[GitHub] Found schema macro: pattern={result['custom_schema_pattern']}")
            break

    return result


def _detect_schema_pattern(macro_sql: str) -> Optional[str]:
    """
    Detect the custom schema naming pattern from a generate_schema_name macro.

    Returns:
        "ignore_default" — always uses custom_schema_name (ignores target.schema prefix)
        "prefix_default" — returns target.schema ~ '_' ~ custom_schema_name
        "default_dbt"    — standard dbt behavior
    """
    lower = macro_sql.lower()

    # Pattern: just returns custom_schema_name without target.schema
    if re.search(r"\{\{\s*custom_schema_name\s*(\|\s*trim\s*)?\}\}", lower):
        # Check if target.schema is NOT used in the output
        lines_after_custom = lower.split("custom_schema_name", 1)[-1]
        if "target.schema" not in lines_after_custom[:200]:
            return "ignore_default"

    # Pattern: target.schema ~ '_' ~ custom_schema_name
    if re.search(r"target\.schema\s*~\s*['\"]_['\"]\s*~\s*custom_schema_name", lower):
        return "prefix_default"

    return "default_dbt"


def build_schema_mapping(
    manifest: Dict[str, Any],
    project_config: Dict[str, Any],
    warehouse_type: str = "bigquery",
) -> Dict[str, str]:
    """
    Build model_name -> actual_warehouse_schema mapping.

    Uses the manifest's schema as truth. When a generate_schema_name override
    is detected, applies the pattern to derive the correct warehouse schema.

    Returns:
        {"stg_customers": "analytics", ...}
    """
    mapping: Dict[str, str] = {}
    pattern = project_config.get("custom_schema_pattern")

    for key, node in manifest.get("nodes", {}).items():
        if not key.startswith("model."):
            continue
        name = node.get("alias") or node.get("name", "")
        manifest_schema = node.get("schema", "")
        custom_schema = node.get("config", {}).get("schema", "")

        if pattern == "ignore_default" and custom_schema:
            # The macro just uses custom_schema directly (no target.schema prefix)
            mapping[name] = custom_schema
        elif pattern == "prefix_default" and custom_schema:
            # The macro combines target.schema + custom_schema
            target_schema = manifest.get("metadata", {}).get("target_schema", "")
            mapping[name] = f"{target_schema}_{custom_schema}" if target_schema else custom_schema
        else:
            # Standard behavior — manifest schema is already resolved
            mapping[name] = manifest_schema

    return mapping
