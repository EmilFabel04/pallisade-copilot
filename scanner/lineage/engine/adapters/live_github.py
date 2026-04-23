"""
Live GitHub Adapter — represents a GitHub VCS integration as a lineage node
so version-control assets appear in the pipeline overview.

Emits a single SERVICE node with CP metadata:
  - managed_targets: list of tools whose code this GitHub instance manages
    (passed via config from the frontend, which knows which tools have
    GitHub attachments)
  - repositories: list of repos discovered via the GitHub API
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Set
from urllib.request import Request, urlopen
from urllib.error import URLError
import json as _json

from ...graph import (
    AssetKind,
    LineageEdge,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_REPO_FETCH_TIMEOUT = 10  # seconds
_MAX_REPOS = 100  # cap pages × per_page


class LiveGithubAdapter(BaseLineageAdapter):
    """Adapter that exposes a GitHub integration as a discoverable VCS asset."""

    def __init__(self, adapter_id: str = "live_github", **kwargs):
        self._id = adapter_id

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {Capability.DISCOVER_ASSETS}

    @staticmethod
    def _fetch_repos(token: str, owner: str) -> List[Dict[str, Any]]:
        """Fetch repos for owner/org via the GitHub API.

        Merges results from multiple endpoints to catch all accessible repos:
        1. /orgs/{owner}/repos or /users/{owner}/repos (public listing)
        2. /user/repos (authenticated — sees private repos the token can access)

        Returns a list of ``{"name": ..., "full_name": ..., "default_branch": ...}``
        dicts, capped at ``_MAX_REPOS``.  Fails silently on any error.
        """
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
        seen_full_names: Set[str] = set()
        repos: List[Dict[str, Any]] = []

        def _add_repo(r: Dict[str, Any]) -> None:
            fn = r.get("full_name", "")
            if fn in seen_full_names:
                return
            seen_full_names.add(fn)
            repos.append({
                "name": r.get("name", ""),
                "full_name": fn,
                "default_branch": r.get("default_branch", "main"),
                "private": r.get("private", False),
            })

        # Try org first, then user — the PAT may belong to either.
        # type=all includes private repos when the token has repo scope.
        for path in (f"/orgs/{owner}/repos", f"/users/{owner}/repos"):
            url = f"{_GITHUB_API}{path}?per_page=100&sort=updated&type=all"
            req = Request(url, headers=headers)
            try:
                with urlopen(req, timeout=_REPO_FETCH_TIMEOUT) as resp:
                    if resp.status != 200:
                        continue
                    data = _json.loads(resp.read())
            except (URLError, OSError, ValueError) as exc:
                logger.debug("[LiveGithub] repo list via %s failed: %s", path, exc)
                continue

            if not isinstance(data, list):
                continue

            for r in data[:_MAX_REPOS]:
                _add_repo(r)
            if repos:
                break  # success — no need to try the other public endpoint

        # ALWAYS also try /user/repos (authenticated endpoint) — it sees
        # private repos that /users/{owner}/repos may miss (e.g. OAuth tokens).
        url = f"{_GITHUB_API}/user/repos?per_page=100&sort=updated&affiliation=owner,collaborator,organization_member"
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=_REPO_FETCH_TIMEOUT) as resp:
                if resp.status == 200:
                    data = _json.loads(resp.read())
                    if isinstance(data, list):
                        before = len(repos)
                        for r in data[:_MAX_REPOS]:
                            # Filter to repos belonging to the target owner
                            r_owner = r.get("owner", {}).get("login", "")
                            if r_owner.lower() != owner.lower():
                                continue
                            _add_repo(r)
                        added = len(repos) - before
                        if added:
                            logger.info("[LiveGithub] /user/repos added %d extra repos for %s", added, owner)
        except (URLError, OSError, ValueError) as exc:
            logger.debug("[LiveGithub] /user/repos failed: %s", exc)

        logger.info("[LiveGithub] Fetched %d repos for %s: %s",
                    len(repos), owner, [r.get("full_name", "") for r in repos])
        return repos

    # Signature files → tool classification.  Checked against the repo's
    # root tree (recursive).  Order matters: first match wins per file.
    _TOOL_SIGNATURES: List[tuple] = [
        # (path pattern, tool_type)
        ("dbt_project.yml", "dbt"),
        ("dbt_project.yaml", "dbt"),
        ("models/", "dbt"),
        ("dags/", "airflow"),
        ("airflow.cfg", "airflow"),
        ("airflow/", "airflow"),
        ("dag_", "airflow"),           # dag_*.py at any level
        ("prefect.yaml", "prefect"),
        ("flows/", "prefect"),
        ("dagster.yaml", "dagster"),
        ("definitions.py", "dagster"),  # Dagster code locations
        ("repository.py", "dagster"),
        ("Dockerfile", "docker"),
        ("docker-compose", "docker"),
        ("terraform/", "terraform"),
        (".tf", "terraform"),
    ]

    @staticmethod
    def _classify_repo(token: str, repo_full: str, branch: str) -> List[str]:
        """Check a repo's file tree for tool-signature files.

        Returns a list of detected tool types (e.g. ["dbt", "airflow"]).
        Uses the Git Trees API with recursive=1 (single request, lightweight).
        Fails silently and returns [].
        """
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
        url = f"{_GITHUB_API}/repos/{repo_full}/git/trees/{branch}?recursive=1"
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=_REPO_FETCH_TIMEOUT) as resp:
                if resp.status != 200:
                    logger.info("[LiveGithub] Tree API returned %d for %s", resp.status, repo_full)
                    return []
                data = _json.loads(resp.read())
        except (URLError, OSError, ValueError) as exc:
            logger.info("[LiveGithub] Tree API failed for %s: %s", repo_full, exc)
            return []

        tree = data.get("tree", [])
        truncated = data.get("truncated", False)
        if truncated:
            logger.info("[LiveGithub] Tree truncated for %s (%d items), may miss signatures", repo_full, len(tree))
        if not isinstance(tree, list):
            return []

        # Collect all paths (just the path strings, not content)
        paths = [item.get("path", "") for item in tree]
        logger.debug("[LiveGithub] Tree for %s: %d items (truncated=%s)", repo_full, len(paths), truncated)

        detected: set = set()
        for path in paths:
            for sig, tool in LiveGithubAdapter._TOOL_SIGNATURES:
                if sig.endswith("/"):
                    # Directory marker: check if path starts with it or appears anywhere
                    if path.startswith(sig) or f"/{sig}" in path or path == sig.rstrip("/"):
                        detected.add(tool)
                else:
                    # File marker: check basename or full path
                    basename = path.rsplit("/", 1)[-1] if "/" in path else path
                    if basename == sig or basename.startswith(sig):
                        detected.add(tool)

        return sorted(detected)

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        namespace = config.get("namespace", "default")
        integration_id = config.get("integration_id")
        owner = config.get("owner") or config.get("org") or ""
        repo = config.get("repo") or ""
        token = config.get("access_token") or config.get("token") or ""
        name = f"GitHub ({owner})" if owner else "GitHub"

        logger.info(
            "[LiveGithub] discover_assets called: owner=%r, repo=%r, token=%s, "
            "managed_tools=%r, config_keys=%s",
            owner, repo, ("present" if token else "MISSING"),
            config.get("managed_tools", []),
            list(config.keys()),
        )

        asset_id = generate_asset_id("vcs", "github", namespace, "", owner or "github")

        raw_metadata: Dict[str, Any] = {}

        # managed_tools: injected by the frontend — it knows which tools
        # received GitHub attachments and passes them as config.managed_tools.
        managed_tools = config.get("managed_tools", [])
        if isinstance(managed_tools, list) and managed_tools:
            raw_metadata["managed_targets"] = [t.lower() for t in managed_tools]

        # Fetch repo list via GitHub API, classify each repo's contents,
        # and only keep repos that contain pipeline-relevant tool code.
        # Also include repos explicitly referenced in config.repos.
        config_repos_set: Set[str] = set()
        for cr in config.get("repos") or config.get("repositories") or []:
            if isinstance(cr, str):
                config_repos_set.add(cr.lower())

        # Normalize managed_tools for matching (e.g. "dbt_core" → also match "dbt")
        managed_tools_normalized: Set[str] = set()
        for mt in managed_tools:
            managed_tools_normalized.add(mt.lower())
            # "dbt_core" should match classification "dbt"
            managed_tools_normalized.add(mt.lower().replace("_core", "").replace("_cloud", ""))

        if token and owner:
            fetched_repos = self._fetch_repos(token, owner)
            if fetched_repos:
                # Two-pass classification:
                # Pass 1: classify all repos
                # Pass 2: include config repos first (authoritative), then
                #          only non-config repos that bring NEW tool types
                classified: List[tuple] = []  # (repo_dict, tools, is_config)
                logger.info("[LiveGithub] Classifying %d repos for %s", len(fetched_repos), owner)
                for r in fetched_repos:
                    r_full = r.get("full_name", "")
                    branch = r.get("default_branch", "main")
                    tools = self._classify_repo(token, r_full, branch)
                    if tools:
                        r["detected_tools"] = tools
                        is_config = r_full.lower() in config_repos_set
                        classified.append((r, tools, is_config))
                    else:
                        logger.debug("[LiveGithub] Repo %s → no pipeline tools detected", r_full)

                # Pass 2: config repos go first, track which tools are covered
                pipeline_repos = []
                covered_tools: Set[str] = set()
                # Config repos first (authoritative — always included)
                for r, tools, is_config in classified:
                    if is_config:
                        pipeline_repos.append(r)
                        covered_tools.update(tools)
                        logger.debug("[LiveGithub] Repo %s → tools: %s (config repo)", r.get("full_name"), tools)

                # Non-config repos: only if they bring a new managed tool type
                for r, tools, is_config in classified:
                    if is_config:
                        continue
                    managed_overlap = managed_tools_normalized & set(tools)
                    new_tools = managed_overlap - covered_tools
                    if new_tools or not managed_tools_normalized:
                        pipeline_repos.append(r)
                        covered_tools.update(tools)
                        logger.debug("[LiveGithub] Repo %s → tools: %s (new tools %s)", r.get("full_name"), tools, new_tools)
                    else:
                        logger.debug("[LiveGithub] Repo %s → excluded (tools %s covered)", r.get("full_name"), managed_overlap)
                raw_metadata["repositories"] = pipeline_repos
                logger.info(
                    "[LiveGithub] %d/%d repos contain pipeline code for %s",
                    len(pipeline_repos), len(fetched_repos), owner,
                )
            else:
                logger.info("[LiveGithub] No repos fetched for %s (token may lack scope)", owner)

        # Also store owner/repo for display purposes
        if owner:
            raw_metadata["owner"] = owner
        if repo:
            raw_metadata["repo"] = repo

        node = LineageNode(
            id=asset_id,
            name=name,
            fqn=f"github.{namespace}.{owner or 'github'}",
            node_type=NodeType.SOURCE,
            platform="github",
            platform_domain=PlatformDomain.OTHER,
            asset_kind=AssetKind.UNKNOWN,
            namespace=namespace,
            observed_at=datetime.utcnow(),
            sources=[self._id],
            integration_id=integration_id,
            canonical_type="service",
            raw_metadata=raw_metadata,
        )

        if managed_tools:
            logger.info(
                "[LiveGithub] CP metadata: managed_targets=%s", raw_metadata.get("managed_targets")
            )

        logger.info("[LiveGithub] Discovered VCS node: %s", name)
        return [node]

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        return []
