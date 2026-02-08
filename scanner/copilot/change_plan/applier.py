"""
ChangePlan Applier

Applies validated ChangePlans by creating GitHub Pull Requests.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, List
import logging
import base64
import asyncio

from .models import (
    ChangePlan,
    ChangePlanStatus,
    FilePatch,
)

logger = logging.getLogger(__name__)


@dataclass
class ApplyResult:
    """Result of applying a change plan."""
    success: bool
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    branch_name: Optional[str] = None
    error: Optional[str] = None
    files_changed: int = 0


class ChangePlanApplier:
    """
    Applies validated ChangePlans via GitHub PRs.

    This class handles:
    1. Creating a feature branch
    2. Applying each patch to the repository
    3. Creating a Pull Request with the plan description
    4. Tracking the outcome
    """

    def __init__(
        self,
        github_token: str,
        github_api_base: str = "https://api.github.com",
    ):
        """
        Initialize the applier with GitHub credentials.

        Args:
            github_token: GitHub personal access token or OAuth token
            github_api_base: Base URL for GitHub API (for GHE support)
        """
        self.github_token = github_token
        self.github_api_base = github_api_base.rstrip('/')
        self._session = None

    async def _get_session(self):
        """Get or create an aiohttp session."""
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"token {self.github_token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Pallisade-Scout/1.0",
                }
            )
        return self._session

    async def close(self):
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def apply(
        self,
        plan: ChangePlan,
        repo_owner: str,
        repo_name: str,
        base_branch: str = "main",
    ) -> ApplyResult:
        """
        Apply a validated change plan by creating a GitHub PR.

        Args:
            plan: The validated change plan
            repo_owner: GitHub repository owner (username or org)
            repo_name: GitHub repository name
            base_branch: Branch to base the PR on (default: main)

        Returns:
            ApplyResult with PR details or error
        """
        if not plan.is_validated():
            return ApplyResult(
                success=False,
                error="Plan has not passed required validations",
            )

        if not plan.patches:
            return ApplyResult(
                success=False,
                error="Plan has no patches to apply",
            )

        try:
            plan.status = ChangePlanStatus.APPLYING

            # Step 1: Get the base branch SHA
            base_sha = await self._get_branch_sha(repo_owner, repo_name, base_branch)
            if not base_sha:
                return ApplyResult(
                    success=False,
                    error=f"Could not find branch '{base_branch}'",
                )

            # Step 2: Create a new branch
            branch_name = self._generate_branch_name(plan)
            branch_created = await self._create_branch(
                repo_owner, repo_name, branch_name, base_sha
            )
            if not branch_created:
                return ApplyResult(
                    success=False,
                    error=f"Could not create branch '{branch_name}'",
                )

            # Step 3: Apply each patch
            files_changed = 0
            for patch in plan.patches:
                patch_applied = await self._apply_patch(
                    repo_owner, repo_name, branch_name, patch
                )
                if patch_applied:
                    files_changed += 1
                else:
                    logger.warning(f"Failed to apply patch: {patch.file_path}")

            if files_changed == 0:
                return ApplyResult(
                    success=False,
                    error="No patches were successfully applied",
                    branch_name=branch_name,
                )

            # Step 4: Create Pull Request
            pr_result = await self._create_pr(
                repo_owner, repo_name, branch_name, base_branch, plan
            )

            if pr_result.get("success"):
                plan.status = ChangePlanStatus.APPLIED
                plan.pr_url = pr_result.get("url")
                plan.pr_number = pr_result.get("number")

                return ApplyResult(
                    success=True,
                    pr_url=pr_result.get("url"),
                    pr_number=pr_result.get("number"),
                    branch_name=branch_name,
                    files_changed=files_changed,
                )
            else:
                return ApplyResult(
                    success=False,
                    error=pr_result.get("error", "Failed to create PR"),
                    branch_name=branch_name,
                    files_changed=files_changed,
                )

        except Exception as e:
            logger.exception(f"Failed to apply change plan: {e}")
            plan.status = ChangePlanStatus.FAILED
            return ApplyResult(
                success=False,
                error=str(e),
            )

    def _generate_branch_name(self, plan: ChangePlan) -> str:
        """Generate a branch name for the change plan."""
        # Sanitize title for branch name
        import re
        safe_title = re.sub(r'[^a-zA-Z0-9-]', '-', plan.title.lower())
        safe_title = re.sub(r'-+', '-', safe_title).strip('-')[:40]
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return f"scout/{safe_title}-{timestamp}"

    async def _get_branch_sha(
        self,
        owner: str,
        repo: str,
        branch: str,
    ) -> Optional[str]:
        """Get the SHA of a branch."""
        session = await self._get_session()
        url = f"{self.github_api_base}/repos/{owner}/{repo}/git/ref/heads/{branch}"

        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("object", {}).get("sha")
            else:
                logger.error(f"Failed to get branch SHA: {response.status}")
                return None

    async def _create_branch(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        base_sha: str,
    ) -> bool:
        """Create a new branch from a base SHA."""
        session = await self._get_session()
        url = f"{self.github_api_base}/repos/{owner}/{repo}/git/refs"

        payload = {
            "ref": f"refs/heads/{branch_name}",
            "sha": base_sha,
        }

        async with session.post(url, json=payload) as response:
            if response.status == 201:
                return True
            else:
                error_text = await response.text()
                logger.error(f"Failed to create branch: {response.status} - {error_text}")
                return False

    async def _apply_patch(
        self,
        owner: str,
        repo: str,
        branch: str,
        patch: FilePatch,
    ) -> bool:
        """Apply a single patch to the repository."""
        session = await self._get_session()

        # First, try to get the existing file to get its SHA (for updates)
        file_sha = await self._get_file_sha(owner, repo, branch, patch.file_path)

        url = f"{self.github_api_base}/repos/{owner}/{repo}/contents/{patch.file_path}"

        # Encode content as base64
        content_bytes = patch.new_content.encode('utf-8')
        content_b64 = base64.b64encode(content_bytes).decode('utf-8')

        payload = {
            "message": f"Scout: {patch.rationale[:50] if patch.rationale else 'Update ' + patch.file_path}",
            "content": content_b64,
            "branch": branch,
        }

        if file_sha:
            payload["sha"] = file_sha

        async with session.put(url, json=payload) as response:
            if response.status in (200, 201):
                return True
            else:
                error_text = await response.text()
                logger.error(f"Failed to apply patch to {patch.file_path}: {response.status} - {error_text}")
                return False

    async def _get_file_sha(
        self,
        owner: str,
        repo: str,
        branch: str,
        file_path: str,
    ) -> Optional[str]:
        """Get the SHA of a file if it exists."""
        session = await self._get_session()
        url = f"{self.github_api_base}/repos/{owner}/{repo}/contents/{file_path}"
        params = {"ref": branch}

        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("sha")
            else:
                return None

    async def _create_pr(
        self,
        owner: str,
        repo: str,
        head_branch: str,
        base_branch: str,
        plan: ChangePlan,
    ) -> Dict[str, Any]:
        """Create a Pull Request."""
        session = await self._get_session()
        url = f"{self.github_api_base}/repos/{owner}/{repo}/pulls"

        payload = {
            "title": f"[Scout] {plan.title}",
            "body": plan.to_pr_body(),
            "head": head_branch,
            "base": base_branch,
        }

        async with session.post(url, json=payload) as response:
            if response.status == 201:
                data = await response.json()
                return {
                    "success": True,
                    "url": data.get("html_url"),
                    "number": data.get("number"),
                }
            else:
                error_text = await response.text()
                logger.error(f"Failed to create PR: {response.status} - {error_text}")
                return {
                    "success": False,
                    "error": f"GitHub API error: {response.status}",
                }


class ChangePlanStore:
    """
    In-memory store for change plans during a session.

    In production, this would be backed by the database (Prisma ChangePlan model).
    """

    def __init__(self):
        self._plans: Dict[str, ChangePlan] = {}

    def save(self, plan: ChangePlan) -> None:
        """Save a change plan."""
        self._plans[plan.id] = plan

    def get(self, plan_id: str) -> Optional[ChangePlan]:
        """Get a change plan by ID."""
        return self._plans.get(plan_id)

    def list(self) -> List[ChangePlan]:
        """List all change plans."""
        return list(self._plans.values())

    def delete(self, plan_id: str) -> bool:
        """Delete a change plan."""
        if plan_id in self._plans:
            del self._plans[plan_id]
            return True
        return False


# Global store instance for session-based storage
_store = ChangePlanStore()


def get_change_plan_store() -> ChangePlanStore:
    """Get the global change plan store."""
    return _store
