"""
Deterministic verifier for CodeFix specialist output.

Checks patch validity, size bounds, and runs static validation.
"""

from typing import List
from dataclasses import dataclass
import logging

from ..schemas import CodeFixResponse

logger = logging.getLogger(__name__)

VALID_PATCH_TYPES = {
    "sql_model", "yaml_config", "python_script", "orchestration", "text_file",
}

# Size bounds to prevent blowing token limits or DB payload sizes
MAX_PATCH_CONTENT_CHARS = 50_000
MAX_TOTAL_PATCH_CHARS = 200_000


@dataclass
class PatchVerificationResult:
    passed: bool
    errors: List[str]
    warnings: List[str]


class PatchVerifier:
    """
    Deterministic verifier for CodeFix specialist output.

    Checks:
    1. All patches have non-empty file_path and new_content
    2. patch_type is valid
    3. Size bounds per file and total
    4. Unified diff markers present when original_content exists
    5. Rollback steps are present
    """

    async def verify(self, response: CodeFixResponse) -> PatchVerificationResult:
        errors: List[str] = []
        warnings: List[str] = []

        if not response.patches:
            errors.append("No patches provided")
            return PatchVerificationResult(
                passed=False, errors=errors, warnings=warnings
            )

        total_chars = 0

        for i, patch in enumerate(response.patches):
            # 1. Non-empty fields
            if not patch.file_path:
                errors.append(f"patches[{i}]: empty file_path")
            if not patch.new_content:
                errors.append(f"patches[{i}]: empty new_content")
                continue

            # 2. Valid patch_type
            if patch.patch_type not in VALID_PATCH_TYPES:
                errors.append(
                    f"patches[{i}]: invalid patch_type '{patch.patch_type}'. "
                    f"Must be one of: {sorted(VALID_PATCH_TYPES)}"
                )

            # 3. Size bounds per file
            content_len = len(patch.new_content)
            if content_len > MAX_PATCH_CONTENT_CHARS:
                errors.append(
                    f"patches[{i}]: new_content is {content_len} chars, "
                    f"exceeds max {MAX_PATCH_CONTENT_CHARS}"
                )
            total_chars += content_len

            # 4. Diff format (when original_content exists)
            if patch.original_content and patch.diff:
                if not any(
                    marker in patch.diff for marker in ["+++", "---", "@@"]
                ):
                    warnings.append(
                        f"patches[{i}]: diff does not look like unified diff format"
                    )

        # 3b. Total size bound
        if total_chars > MAX_TOTAL_PATCH_CHARS:
            errors.append(
                f"Total patch content is {total_chars} chars, "
                f"exceeds max {MAX_TOTAL_PATCH_CHARS}"
            )

        # 5. Rollback steps
        if not response.validation.rollback_steps:
            warnings.append("No rollback steps provided")

        # 6. Try constructing FilePatch objects and running StaticValidator
        if not errors:
            static_errors, static_warnings = await self._run_static_validation(
                response
            )
            errors.extend(static_errors)
            warnings.extend(static_warnings)

        return PatchVerificationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    async def _run_static_validation(
        self, response: CodeFixResponse
    ) -> tuple:
        """Attempt to run static validation via the change_plan module."""
        errors: List[str] = []
        warnings: List[str] = []

        try:
            from copilot.change_plan.models import FilePatch, PatchType, ChangePlan
            from copilot.change_plan.validators import StaticValidator

            file_patches = []
            for patch in response.patches:
                try:
                    fp = FilePatch(
                        file_path=patch.file_path,
                        patch_type=PatchType(patch.patch_type),
                        new_content=patch.new_content,
                        original_content=patch.original_content,
                        rationale=patch.rationale,
                        rollback_steps=response.validation.rollback_steps,
                    )
                    file_patches.append(fp)
                except (ValueError, KeyError) as e:
                    errors.append(f"Failed to build FilePatch: {e}")

            if file_patches:
                plan = ChangePlan.create(
                    title="MAAS verification", patches=file_patches
                )
                validator = StaticValidator()
                result = await validator.validate(plan)
                if hasattr(result, "errors") and result.errors:
                    errors.extend(result.errors)
                if hasattr(result, "warnings") and result.warnings:
                    warnings.extend(result.warnings)

        except ImportError:
            logger.debug(
                "[MAAS/PatchVerifier] change_plan module not available, "
                "skipping static validation"
            )
        except Exception as e:
            warnings.append(f"Static validation failed: {e}")

        return errors, warnings
