"""
GitHub-based dbt project reader for lineage enrichment.

Reads dbt_project.yml and generate_schema_name.sql from a connected
GitHub repo to build schema mappings that improve cross-tool edge matching.
"""

import base64
import json
import logging
import re
from typing import Any, Dict, List, Optional

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


async def fetch_dbt_manifest(
    repo: str,
    token: str,
    branch: str = "main",
    dbt_root: str = "",
    manifest_path: str = "target/manifest.json",
) -> Optional[Dict[str, Any]]:
    """
    Fetch and parse manifest.json from a GitHub repository.

    Tries the specified path, then common alternatives:
    1. {dbt_root}/{manifest_path} (user-specified)
    2. {dbt_root}/target/manifest.json (standard dbt output)
    3. manifest.json (repo root)
    """
    prefix = f"{dbt_root}/" if dbt_root and not dbt_root.endswith("/") else (dbt_root or "")

    # Build list of candidate paths (deduplicated, ordered by priority)
    candidates: List[str] = []
    primary = f"{prefix}{manifest_path}".lstrip("/")
    candidates.append(primary)

    # Standard dbt output location
    standard = f"{prefix}target/manifest.json".lstrip("/")
    if standard not in candidates:
        candidates.append(standard)

    # Repo root fallback
    if "manifest.json" not in candidates:
        candidates.append("manifest.json")

    for path in candidates:
        logger.debug(f"[GitHub] Trying manifest at: {path}")
        content = await fetch_github_file(repo, path, token, branch)
        if content:
            try:
                manifest = json.loads(content)
                if isinstance(manifest, dict) and ("nodes" in manifest or "sources" in manifest):
                    logger.info(f"[GitHub] Found dbt manifest at {path} ({len(manifest.get('nodes', {}))} nodes)")
                    return manifest
                else:
                    logger.warning(f"[GitHub] File at {path} is JSON but doesn't look like a dbt manifest")
            except json.JSONDecodeError as e:
                logger.warning(f"[GitHub] File at {path} is not valid JSON: {e}")

    logger.warning(f"[GitHub] No dbt manifest found in {repo} (tried: {candidates})")
    return None


async def fetch_dbt_project_files(
    repo: str,
    token: str,
    branch: str = "main",
    dbt_root: str = "",
) -> Dict[str, str]:
    """
    Fetch raw dbt project files (SQL models, YAML configs) from a GitHub repo.

    Uses the Git Trees API for recursive directory listing, then fetches
    content for .sql and .yml/.yaml files within the dbt project root.

    Returns:
        Dict mapping relative file paths to their content,
        e.g. {"models/staging/stg_orders.sql": "SELECT ...", "models/schema.yml": "..."}
    """
    import aiohttp

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Pallisade-Lineage/1.0",
    }
    api_base = "https://api.github.com"
    files: Dict[str, str] = {}

    try:
        async with aiohttp.ClientSession() as session:
            # Get the tree recursively for the branch
            tree_url = f"{api_base}/repos/{repo}/git/trees/{branch}?recursive=1"
            async with session.get(tree_url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"[GitHub] Failed to get tree for {repo}@{branch}: {resp.status}")
                    return {}
                tree_data = await resp.json()

            tree_items = tree_data.get("tree", [])
            prefix = f"{dbt_root}/" if dbt_root and not dbt_root.endswith("/") else (dbt_root or "")

            # Filter to relevant files within the dbt root
            relevant_files: List[str] = []
            for item in tree_items:
                if item.get("type") != "blob":
                    continue
                path = item.get("path", "")
                # Must be within dbt root
                if prefix and not path.startswith(prefix):
                    continue
                lower = path.lower()
                # Only SQL and YAML files
                if lower.endswith((".sql", ".yml", ".yaml")):
                    # Skip target/ and dbt_packages/ directories
                    rel = path[len(prefix):] if prefix else path
                    rel_parts = rel.split("/")
                    if any(p in ("target", "dbt_packages", "dbt_modules", ".git", "logs") for p in rel_parts):
                        continue
                    relevant_files.append(path)

            logger.info(f"[GitHub] Found {len(relevant_files)} dbt project files in {repo}")

            # Fetch each file's content (batch with limited concurrency)
            import asyncio
            semaphore = asyncio.Semaphore(10)

            async def fetch_one(path: str) -> Optional[tuple]:
                async with semaphore:
                    content = await fetch_github_file(repo, path, token, branch)
                    if content is not None:
                        # Store with relative path (strip dbt_root prefix)
                        rel = path[len(prefix):] if prefix else path
                        return (rel, content)
                    return None

            results = await asyncio.gather(*[fetch_one(p) for p in relevant_files])
            for result in results:
                if result:
                    files[result[0]] = result[1]

    except Exception as e:
        logger.error(f"[GitHub] Failed to fetch dbt project files: {e}")

    logger.info(f"[GitHub] Fetched {len(files)} dbt project files from {repo}")
    return files


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
