"""
ChangePlan Validators

Validation implementations for static analysis, CI, and sandbox testing.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging
import re

# Try to import yaml, fallback to None if not available
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    yaml = None
    YAML_AVAILABLE = False

from .models import (
    ChangePlan,
    FilePatch,
    PatchType,
    ValidationLevel,
    ValidationStatus,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class BaseValidator(ABC):
    """Abstract base class for validators."""

    @property
    @abstractmethod
    def level(self) -> ValidationLevel:
        """The validation level this validator handles."""
        pass

    @abstractmethod
    async def validate(self, plan: ChangePlan) -> ValidationResult:
        """
        Validate a change plan.

        Args:
            plan: The change plan to validate

        Returns:
            ValidationResult with status and any errors/warnings
        """
        pass


class StaticValidator(BaseValidator):
    """
    Level A: Static analysis validation.

    Performs:
    - SQL syntax validation
    - YAML schema validation
    - Basic Python linting
    - Jinja template validation for dbt models
    """

    @property
    def level(self) -> ValidationLevel:
        return ValidationLevel.STATIC

    async def validate(self, plan: ChangePlan) -> ValidationResult:
        """Run static validation on all patches."""
        started_at = datetime.utcnow()
        errors: List[str] = []
        warnings: List[str] = []
        details: Dict[str, Any] = {"patches_checked": 0, "passed": 0, "failed": 0}

        for patch in plan.patches:
            details["patches_checked"] += 1
            patch_errors, patch_warnings = self._validate_patch(patch)

            if patch_errors:
                errors.extend(patch_errors)
                details["failed"] += 1
            else:
                details["passed"] += 1

            warnings.extend(patch_warnings)

        status = ValidationStatus.PASSED if not errors else ValidationStatus.FAILED

        return ValidationResult(
            level=self.level,
            status=status,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            errors=errors,
            warnings=warnings,
            details=details,
        )

    def _validate_patch(self, patch: FilePatch) -> tuple[List[str], List[str]]:
        """Validate a single patch."""
        errors: List[str] = []
        warnings: List[str] = []

        if patch.patch_type == PatchType.SQL_MODEL:
            errs, warns = self._validate_sql(patch)
            errors.extend(errs)
            warnings.extend(warns)

        elif patch.patch_type == PatchType.YAML_CONFIG:
            errs, warns = self._validate_yaml(patch)
            errors.extend(errs)
            warnings.extend(warns)

        elif patch.patch_type == PatchType.PYTHON_SCRIPT:
            errs, warns = self._validate_python(patch)
            errors.extend(errs)
            warnings.extend(warns)

        return errors, warnings

    def _validate_sql(self, patch: FilePatch) -> tuple[List[str], List[str]]:
        """Validate SQL/dbt model syntax."""
        errors: List[str] = []
        warnings: List[str] = []
        content = patch.new_content

        # Check for basic SQL syntax issues
        # Count parentheses
        open_parens = content.count('(')
        close_parens = content.count(')')
        if open_parens != close_parens:
            errors.append(f"{patch.file_path}: Unbalanced parentheses ({open_parens} open, {close_parens} close)")

        # Check for Jinja syntax if it's a dbt model
        if '{{' in content or '{%' in content:
            jinja_errs, jinja_warns = self._validate_jinja(content, patch.file_path)
            errors.extend(jinja_errs)
            warnings.extend(jinja_warns)

        # Check for common SQL keywords
        content_upper = content.upper()
        if 'SELECT' not in content_upper and 'INSERT' not in content_upper:
            warnings.append(f"{patch.file_path}: No SELECT or INSERT statement found")

        # Check for dangerous operations (should probably not be in a model)
        dangerous_keywords = ['DROP TABLE', 'TRUNCATE', 'DELETE FROM']
        for keyword in dangerous_keywords:
            if keyword in content_upper:
                warnings.append(f"{patch.file_path}: Contains '{keyword}' - verify this is intentional")

        # Check for ref() and source() calls in dbt models
        if '.sql' in patch.file_path.lower():
            ref_pattern = r'\{\{\s*ref\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)\s*\}\}'
            source_pattern = r'\{\{\s*source\s*\(\s*[\'"]([^\'"]+)[\'"],\s*[\'"]([^\'"]+)[\'"]\s*\)\s*\}\}'

            refs = re.findall(ref_pattern, content)
            sources = re.findall(source_pattern, content)

            if not refs and not sources and '{{' in content:
                # Has Jinja but no refs or sources - might be missing dependencies
                warnings.append(f"{patch.file_path}: No ref() or source() calls found - verify dependencies")

        return errors, warnings

    def _validate_jinja(self, content: str, file_path: str) -> tuple[List[str], List[str]]:
        """Validate Jinja template syntax."""
        errors: List[str] = []
        warnings: List[str] = []

        # Check for balanced Jinja blocks
        open_expr = content.count('{{')
        close_expr = content.count('}}')
        if open_expr != close_expr:
            errors.append(f"{file_path}: Unbalanced Jinja expressions ({{ count: {open_expr}, }} count: {close_expr})")

        open_stmt = content.count('{%')
        close_stmt = content.count('%}')
        if open_stmt != close_stmt:
            errors.append(f"{file_path}: Unbalanced Jinja statements ({{% count: {open_stmt}, %}} count: {close_stmt})")

        # Check for matching if/endif, for/endfor, etc.
        if_count = len(re.findall(r'\{%\s*if\s+', content))
        endif_count = len(re.findall(r'\{%\s*endif\s*%\}', content))
        if if_count != endif_count:
            errors.append(f"{file_path}: Unbalanced if/endif blocks ({if_count} if, {endif_count} endif)")

        for_count = len(re.findall(r'\{%\s*for\s+', content))
        endfor_count = len(re.findall(r'\{%\s*endfor\s*%\}', content))
        if for_count != endfor_count:
            errors.append(f"{file_path}: Unbalanced for/endfor blocks ({for_count} for, {endfor_count} endfor)")

        return errors, warnings

    def _validate_yaml(self, patch: FilePatch) -> tuple[List[str], List[str]]:
        """Validate YAML syntax."""
        errors: List[str] = []
        warnings: List[str] = []
        content = patch.new_content

        if YAML_AVAILABLE:
            try:
                yaml.safe_load(content)
            except yaml.YAMLError as e:
                errors.append(f"{patch.file_path}: YAML syntax error - {str(e)}")
        else:
            # YAML module not available, do basic validation
            # Check for common YAML issues
            lines = content.split('\n')
            for i, line in enumerate(lines, 1):
                if '\t' in line:
                    warnings.append(f"{patch.file_path}:{i}: Contains tabs - YAML prefers spaces")

        return errors, warnings

    def _validate_python(self, patch: FilePatch) -> tuple[List[str], List[str]]:
        """Validate Python syntax."""
        errors: List[str] = []
        warnings: List[str] = []
        content = patch.new_content

        try:
            compile(content, patch.file_path, 'exec')
        except SyntaxError as e:
            errors.append(f"{patch.file_path}:{e.lineno}: Python syntax error - {e.msg}")

        return errors, warnings


class CIValidator(BaseValidator):
    """
    Level B: CI validation.

    Performs:
    - dbt compile on changed models
    - Runs affected tests
    - Checks for circular dependencies
    """

    def __init__(self, context: Optional[Any] = None):
        """
        Initialize CI validator.

        Args:
            context: CopilotContext with integration adapters
        """
        self.context = context

    @property
    def level(self) -> ValidationLevel:
        return ValidationLevel.CI

    async def validate(self, plan: ChangePlan) -> ValidationResult:
        """Run CI validation on the change plan."""
        started_at = datetime.utcnow()
        errors: List[str] = []
        warnings: List[str] = []
        details: Dict[str, Any] = {}

        # Check if dbt is available
        dbt_available = self._check_dbt_available()
        if not dbt_available:
            warnings.append("dbt not connected - skipping compile check")
            return ValidationResult(
                level=self.level,
                status=ValidationStatus.SKIPPED,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                errors=errors,
                warnings=warnings,
                details={"reason": "dbt not available"},
            )

        # Compile affected models
        sql_patches = [p for p in plan.patches if p.patch_type == PatchType.SQL_MODEL]
        for patch in sql_patches:
            compile_result = await self._compile_model(patch)
            if not compile_result["success"]:
                errors.append(f"{patch.file_path}: Compilation failed - {compile_result.get('error', 'Unknown error')}")
            else:
                details[f"compiled_{patch.file_path}"] = True

        # Run tests for affected models
        test_results = await self._run_affected_tests(plan)
        details["tests_run"] = test_results.get("tests_run", 0)
        details["tests_passed"] = test_results.get("tests_passed", 0)
        details["tests_failed"] = test_results.get("tests_failed", 0)

        if test_results.get("tests_failed", 0) > 0:
            errors.extend(test_results.get("failed_tests", []))

        status = ValidationStatus.PASSED if not errors else ValidationStatus.FAILED

        return ValidationResult(
            level=self.level,
            status=status,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            errors=errors,
            warnings=warnings,
            details=details,
        )

    def _check_dbt_available(self) -> bool:
        """Check if dbt adapter is available."""
        if not self.context:
            return False

        # Check for dbt integrations
        for integration in getattr(self.context, 'integrations', []):
            if integration.type.upper() in ('DBT_CLOUD', 'DBT_CORE'):
                return True

        return False

    async def _compile_model(self, patch: FilePatch) -> Dict[str, Any]:
        """Compile a dbt model to verify SQL validity."""
        # This would call dbt compile via the adapter
        # For now, return success as a stub
        return {"success": True}

    async def _run_affected_tests(self, plan: ChangePlan) -> Dict[str, Any]:
        """Run tests affected by the changes."""
        # This would run dbt test --select for affected models
        # For now, return empty results as a stub
        return {
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "failed_tests": [],
        }


class SandboxValidator(BaseValidator):
    """
    Level C: Sandbox validation.

    Performs:
    - Shadow run with LIMIT/sample data
    - Compare output schema before/after
    - Estimate row count impact
    """

    def __init__(self, context: Optional[Any] = None):
        """
        Initialize sandbox validator.

        Args:
            context: CopilotContext with warehouse adapters
        """
        self.context = context

    @property
    def level(self) -> ValidationLevel:
        return ValidationLevel.SANDBOX

    async def validate(self, plan: ChangePlan) -> ValidationResult:
        """Run sandbox validation on the change plan."""
        started_at = datetime.utcnow()
        errors: List[str] = []
        warnings: List[str] = []
        details: Dict[str, Any] = {}

        # Check if warehouse is available
        warehouse_available = self._check_warehouse_available()
        if not warehouse_available:
            warnings.append("No warehouse connected - skipping sandbox validation")
            return ValidationResult(
                level=self.level,
                status=ValidationStatus.SKIPPED,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                errors=errors,
                warnings=warnings,
                details={"reason": "warehouse not available"},
            )

        # Run shadow queries for SQL models
        sql_patches = [p for p in plan.patches if p.patch_type == PatchType.SQL_MODEL]
        for patch in sql_patches:
            shadow_result = await self._run_shadow_query(patch)
            if not shadow_result["success"]:
                errors.append(f"{patch.file_path}: Shadow run failed - {shadow_result.get('error', 'Unknown error')}")
            else:
                details[f"shadow_{patch.file_path}"] = {
                    "row_count": shadow_result.get("row_count", 0),
                    "columns": shadow_result.get("columns", []),
                }

        # Schema comparison
        if plan.impact_analysis and plan.impact_analysis.affected_tables:
            for table in plan.impact_analysis.affected_tables:
                schema_result = await self._compare_schema(table, plan)
                if schema_result.get("schema_changed"):
                    warnings.append(f"{table}: Schema will change - {schema_result.get('changes', 'Unknown changes')}")
                    details[f"schema_change_{table}"] = schema_result

        status = ValidationStatus.PASSED if not errors else ValidationStatus.FAILED

        return ValidationResult(
            level=self.level,
            status=status,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            errors=errors,
            warnings=warnings,
            details=details,
        )

    def _check_warehouse_available(self) -> bool:
        """Check if a warehouse adapter is available."""
        if not self.context:
            return False

        for integration in getattr(self.context, 'integrations', []):
            if integration.type.upper() in ('SNOWFLAKE', 'BIGQUERY', 'POSTGRES', 'REDSHIFT'):
                return True

        return False

    async def _run_shadow_query(self, patch: FilePatch) -> Dict[str, Any]:
        """Run a shadow query with LIMIT to test SQL validity."""
        # This would run the SQL with LIMIT 100 to verify it works
        # For now, return success as a stub
        return {
            "success": True,
            "row_count": 0,
            "columns": [],
        }

    async def _compare_schema(self, table: str, plan: ChangePlan) -> Dict[str, Any]:
        """Compare schema before and after changes."""
        # This would compare the current table schema with what the change would produce
        # For now, return no changes as a stub
        return {
            "schema_changed": False,
            "changes": None,
        }


def get_validator(level: ValidationLevel, context: Optional[Any] = None) -> BaseValidator:
    """
    Factory function to get a validator for a validation level.

    Args:
        level: The validation level
        context: Optional CopilotContext for validators that need it

    Returns:
        Appropriate validator instance
    """
    validators = {
        ValidationLevel.STATIC: StaticValidator(),
        ValidationLevel.CI: CIValidator(context),
        ValidationLevel.SANDBOX: SandboxValidator(context),
    }

    validator = validators.get(level)
    if not validator:
        raise ValueError(f"Unknown validation level: {level}")

    return validator
