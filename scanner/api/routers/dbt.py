"""
dbt Discovery Router - Fetch models, tests, and metadata from dbt projects
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# Absolute paths that project_path must live under. Comma-separated env var.
# If unset, dbt Core config is disabled entirely (dbt Cloud still works).
def _allowed_project_roots() -> List[Path]:
    raw = os.environ.get("DBT_ALLOWED_PROJECT_ROOTS", "").strip()
    if not raw:
        return []
    out: List[Path] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            out.append(Path(entry).expanduser().resolve(strict=False))
        except Exception:
            continue
    return out


def _resolve_dbt_core_paths(config: Dict[str, Any]) -> Tuple[Optional[Path], Optional[str]]:
    """
    Validate dbt Core paths against the allow-list. Returns (manifest_path, error).
    Rejects any path outside of DBT_ALLOWED_PROJECT_ROOTS and any symlinked manifest.
    Error messages are intentionally coarse — don't reveal filesystem structure.
    """
    roots = _allowed_project_roots()
    if not roots:
        return None, "dbt Core is not enabled on this server (DBT_ALLOWED_PROJECT_ROOTS unset)."

    project_path_raw = config.get("project_path")
    if not project_path_raw or not isinstance(project_path_raw, str):
        return None, "project_path is required for dbt Core."

    try:
        project_path = Path(project_path_raw).expanduser().resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError):
        return None, "project_path is invalid."

    # Containment: project_path must equal or be under an allowed root.
    if not any(project_path == r or r in project_path.parents for r in roots):
        return None, "project_path is not in an allowed location."

    # Only permit a hardcoded relative manifest location inside the project.
    candidates = [
        project_path / "target" / "manifest.json",
        project_path / "manifest.json",
    ]
    for c in candidates:
        try:
            resolved = c.resolve(strict=True)
        except (FileNotFoundError, RuntimeError, OSError):
            continue
        # Re-check containment after resolving (defeats symlinks pointing outside).
        if not any(resolved == r or r in resolved.parents for r in roots):
            continue
        if not resolved.is_file():
            continue
        return resolved, None

    return None, "No manifest.json found under the project's target/ directory."


class DbtCoreConfig(BaseModel):
    """dbt Core project configuration."""
    project_path: Optional[str] = None  # Path to dbt project root
    manifest_path: Optional[str] = None  # Direct path to manifest.json
    profiles_dir: Optional[str] = None  # Path to profiles directory


class DbtCloudConfig(BaseModel):
    """dbt Cloud configuration."""
    api_key: str
    account_id: str
    project_id: Optional[str] = None


class DbtModelsRequest(BaseModel):
    """Request for dbt models."""
    config_type: str  # 'core' or 'cloud'
    config: Dict[str, Any]


def parse_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Parse a dbt manifest.json file and extract models."""
    try:
        with manifest_path.open("r") as f:
            manifest = json.load(f)

        models = []
        tests = []
        sources = []

        # Extract nodes (models, tests, seeds, etc.)
        for node_id, node in manifest.get('nodes', {}).items():
            resource_type = node.get('resource_type')

            if resource_type == 'model':
                models.append({
                    'name': node.get('name'),
                    'schema': node.get('schema'),
                    'database': node.get('database'),
                    'materialization': node.get('config', {}).get('materialized', 'view'),
                    'description': node.get('description', ''),
                    'path': node.get('path'),
                    'unique_id': node_id,
                    'depends_on': node.get('depends_on', {}).get('nodes', []),
                    'columns': list(node.get('columns', {}).keys()),
                })
            elif resource_type == 'test':
                tests.append({
                    'name': node.get('name'),
                    'test_type': node.get('test_metadata', {}).get('name', 'generic'),
                    'depends_on': node.get('depends_on', {}).get('nodes', []),
                })

        # Extract sources
        for source_id, source in manifest.get('sources', {}).items():
            sources.append({
                'name': source.get('name'),
                'source_name': source.get('source_name'),
                'schema': source.get('schema'),
                'database': source.get('database'),
                'description': source.get('description', ''),
            })

        return {
            'models': models,
            'tests': tests,
            'sources': sources,
            'metadata': manifest.get('metadata', {}),
        }
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raise HTTPException(status_code=400, detail="Could not read dbt manifest.")


@router.post("/dbt/models")
async def get_dbt_models(request: DbtModelsRequest) -> Dict[str, Any]:
    """
    Fetch models from a dbt project.

    Supports: dbt Core (via manifest.json) and dbt Cloud (via API)
    """
    try:
        config_type = request.config_type.lower()
        config = request.config

        if config_type == 'core':
            manifest_path, err = _resolve_dbt_core_paths(config)
            if err or manifest_path is None:
                logger.warning("dbt Core manifest resolution refused")
                return {
                    'success': False,
                    'models': [],
                    'error': err or 'No manifest available.',
                }

            logger.info("Reading dbt manifest (path elided)")
            result = parse_manifest(manifest_path)

            return {
                'success': True,
                'models': result['models'],
                'tests': result['tests'],
                'sources': result['sources'],
                'source': 'manifest',
            }

        elif config_type == 'cloud':
            # dbt Cloud - fetch via API
            import httpx

            api_key = config.get('api_key')
            account_id = config.get('account_id')
            project_id = config.get('project_id')

            if not api_key or not account_id:
                return {
                    'success': False,
                    'models': [],
                    'error': 'dbt Cloud requires api_key and account_id',
                }

            headers = {
                'Authorization': f'Token {api_key}',
                'Content-Type': 'application/json',
            }

            base_url = 'https://cloud.getdbt.com/api/v2'

            # Get runs to find latest successful run with manifest
            async with httpx.AsyncClient() as client:
                # Get jobs for the project
                jobs_url = f"{base_url}/accounts/{account_id}/jobs/"
                if project_id:
                    jobs_url += f"?project_id={project_id}"

                jobs_response = await client.get(jobs_url, headers=headers, timeout=30)

                if jobs_response.status_code != 200:
                    return {
                        'success': False,
                        'models': [],
                        'error': f'dbt Cloud API error: {jobs_response.status_code}',
                    }

                jobs_data = jobs_response.json()
                jobs = jobs_data.get('data', [])

                if not jobs:
                    return {
                        'success': False,
                        'models': [],
                        'error': 'No jobs found in dbt Cloud project',
                    }

                # Get the most recent run from any job
                all_models = []
                for job in jobs[:5]:  # Check first 5 jobs
                    job_id = job.get('id')
                    runs_url = f"{base_url}/accounts/{account_id}/runs/?job_definition_id={job_id}&limit=1&order_by=-created_at"

                    runs_response = await client.get(runs_url, headers=headers, timeout=30)
                    if runs_response.status_code != 200:
                        continue

                    runs = runs_response.json().get('data', [])
                    if not runs:
                        continue

                    run = runs[0]
                    run_id = run.get('id')

                    # Get artifacts (manifest)
                    artifact_url = f"{base_url}/accounts/{account_id}/runs/{run_id}/artifacts/manifest.json"
                    artifact_response = await client.get(artifact_url, headers=headers, timeout=30)

                    if artifact_response.status_code == 200:
                        manifest = artifact_response.json()
                        for node_id, node in manifest.get('nodes', {}).items():
                            if node.get('resource_type') == 'model':
                                all_models.append({
                                    'name': node.get('name'),
                                    'schema': node.get('schema'),
                                    'database': node.get('database'),
                                    'materialization': node.get('config', {}).get('materialized', 'view'),
                                    'description': node.get('description', ''),
                                })
                        break  # Found models, stop searching

                return {
                    'success': True,
                    'models': all_models,
                    'source': 'cloud',
                }

        else:
            return {
                'success': False,
                'models': [],
                'error': f'Unknown config type: {config_type}. Use "core" or "cloud".',
            }

    except Exception as e:
        logger.error(f"dbt models fetch failed: {e}")
        return {
            'success': False,
            'models': [],
            'error': str(e),
        }


@router.post("/dbt/test-connection")
async def test_dbt_connection(request: DbtModelsRequest) -> Dict[str, Any]:
    """Test connection to dbt project or dbt Cloud."""
    try:
        config_type = request.config_type.lower()
        config = request.config

        if config_type == 'core':
            manifest_path, err = _resolve_dbt_core_paths(config)
            if err or manifest_path is None:
                return {
                    'success': False,
                    'error': err or 'Could not locate a valid dbt manifest.',
                }
            try:
                with manifest_path.open("r") as f:
                    manifest = json.load(f)
                model_count = len([
                    n for n in manifest.get('nodes', {}).values()
                    if n.get('resource_type') == 'model'
                ])
                return {
                    'success': True,
                    'message': f'Found manifest with {model_count} models',
                }
            except Exception:
                # Intentionally opaque — don't confirm path existence / contents.
                return {
                    'success': False,
                    'error': 'Could not parse dbt manifest.',
                }

        elif config_type == 'cloud':
            import httpx

            api_key = config.get('api_key')
            account_id = config.get('account_id')

            if not api_key or not account_id:
                return {
                    'success': False,
                    'error': 'Missing api_key or account_id',
                }

            headers = {'Authorization': f'Token {api_key}'}

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f'https://cloud.getdbt.com/api/v2/accounts/{account_id}/',
                    headers=headers,
                    timeout=10
                )

                if response.status_code == 200:
                    return {
                        'success': True,
                        'message': 'Successfully connected to dbt Cloud',
                    }
                else:
                    return {
                        'success': False,
                        'error': f'dbt Cloud API returned {response.status_code}',
                    }

        return {'success': False, 'error': 'Unknown config type'}

    except Exception as e:
        return {'success': False, 'error': str(e)}
