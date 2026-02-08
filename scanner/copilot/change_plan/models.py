"""
ChangePlan Domain Models

Models for structured change plans with patches, validation, and application tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import difflib
import uuid


class ValidationLevel(Enum):
    """Levels of validation for change plans."""
    STATIC = "static"      # Syntax, schema, lint
    CI = "ci"              # Tests, compilation
    SANDBOX = "sandbox"    # Shadow run, impact


class ValidationStatus(Enum):
    """Status of a validation run."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PatchType(Enum):
    """Types of file patches."""
    SQL_MODEL = "sql_model"           # dbt model changes
    YAML_CONFIG = "yaml_config"       # schema.yml, sources.yml
    PYTHON_SCRIPT = "python_script"   # Python transformations
    ORCHESTRATION = "orchestration"   # Airflow DAG, Dagster asset


class ChangePlanStatus(Enum):
    """Status of a change plan."""
    DRAFT = "draft"
    VALIDATING = "validating"
    VALIDATED = "validated"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class FilePatch:
    """A single file patch within a change plan."""
    file_path: str
    patch_type: PatchType
    new_content: str
    rationale: str
    original_content: Optional[str] = None
    rollback_steps: List[str] = field(default_factory=list)

    @property
    def diff(self) -> str:
        """Generate unified diff between original and new content."""
        if not self.original_content:
            # New file - show all lines as additions
            lines = self.new_content.splitlines(keepends=True)
            return ''.join(f'+{line}' for line in lines)

        original_lines = self.original_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f'a/{self.file_path}',
            tofile=f'b/{self.file_path}',
        )
        return ''.join(diff)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "file_path": self.file_path,
            "patch_type": self.patch_type.value,
            "original_content": self.original_content,
            "new_content": self.new_content,
            "diff": self.diff,
            "rationale": self.rationale,
            "rollback_steps": self.rollback_steps,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FilePatch":
        """Create from dictionary."""
        return cls(
            file_path=data["file_path"],
            patch_type=PatchType(data["patch_type"]),
            original_content=data.get("original_content"),
            new_content=data["new_content"],
            rationale=data.get("rationale", ""),
            rollback_steps=data.get("rollback_steps", []),
        )


@dataclass
class ValidationResult:
    """Result of a validation run."""
    level: ValidationLevel
    status: ValidationStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> Optional[float]:
        """Duration of validation in seconds."""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "level": self.level.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "errors": self.errors,
            "warnings": self.warnings,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationResult":
        """Create from dictionary."""
        return cls(
            level=ValidationLevel(data["level"]),
            status=ValidationStatus(data["status"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            errors=data.get("errors", []),
            warnings=data.get("warnings", []),
            details=data.get("details", {}),
        )


@dataclass
class ImpactAnalysis:
    """Analysis of the impact of a change plan."""
    affected_tables: List[str] = field(default_factory=list)
    downstream_dependencies: List[str] = field(default_factory=list)
    stakeholders: List[str] = field(default_factory=list)
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH
    expected_data_changes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "affected_tables": self.affected_tables,
            "downstream_dependencies": self.downstream_dependencies,
            "stakeholders": self.stakeholders,
            "risk_level": self.risk_level,
            "expected_data_changes": self.expected_data_changes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImpactAnalysis":
        """Create from dictionary."""
        return cls(
            affected_tables=data.get("affected_tables", []),
            downstream_dependencies=data.get("downstream_dependencies", []),
            stakeholders=data.get("stakeholders", []),
            risk_level=data.get("risk_level", "LOW"),
            expected_data_changes=data.get("expected_data_changes", ""),
        )


@dataclass
class ChangePlan:
    """
    A structured change plan with patches, validation, and application tracking.

    ChangePlans are versioned, validated, and applied through GitHub PRs.
    """
    id: str
    title: str
    description: str = ""
    root_cause: str = ""
    version: int = 1
    patches: List[FilePatch] = field(default_factory=list)
    validations: Dict[ValidationLevel, ValidationResult] = field(default_factory=dict)
    impact_analysis: Optional[ImpactAnalysis] = None
    status: ChangePlanStatus = ChangePlanStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str = "scout"
    session_id: Optional[str] = None
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None

    @classmethod
    def create(cls, title: str, **kwargs) -> "ChangePlan":
        """Factory method to create a new ChangePlan with a generated ID."""
        return cls(
            id=f"cp_{uuid.uuid4().hex[:12]}",
            title=title,
            **kwargs
        )

    def add_patch(self, patch: FilePatch) -> None:
        """Add a patch to the plan."""
        self.patches.append(patch)
        self.updated_at = datetime.utcnow()

    def set_validation(self, result: ValidationResult) -> None:
        """Set validation result for a level."""
        self.validations[result.level] = result
        self.updated_at = datetime.utcnow()

        # Update status based on validation
        if result.status == ValidationStatus.FAILED:
            self.status = ChangePlanStatus.FAILED
        elif all(
            v.status == ValidationStatus.PASSED
            for v in self.validations.values()
        ):
            if len(self.validations) >= 2:  # At least STATIC and CI
                self.status = ChangePlanStatus.VALIDATED

    def is_validated(self) -> bool:
        """Check if the plan has passed required validations."""
        required = {ValidationLevel.STATIC}  # Minimum required
        for level in required:
            if level not in self.validations:
                return False
            if self.validations[level].status != ValidationStatus.PASSED:
                return False
        return True

    def to_llm_context(self) -> str:
        """Format for injection into LLM system prompt."""
        lines = [
            f"### Active Change Plan: {self.title}",
            f"**ID:** {self.id} (v{self.version})",
            f"**Status:** {self.status.value}",
        ]

        if self.root_cause:
            lines.append(f"**Root Cause:** {self.root_cause}")

        if self.patches:
            lines.append(f"\n**Patches ({len(self.patches)}):**")
            for patch in self.patches:
                lines.append(f"- `{patch.file_path}` ({patch.patch_type.value})")

        if self.validations:
            lines.append(f"\n**Validation Status:**")
            for level, result in self.validations.items():
                lines.append(f"- {level.value}: {result.status.value}")
                if result.errors:
                    lines.append(f"  Errors: {', '.join(result.errors[:3])}")

        return '\n'.join(lines)

    def to_pr_body(self) -> str:
        """Generate GitHub PR description."""
        lines = [
            "## Summary",
            self.description or self.title,
            "",
        ]

        if self.root_cause:
            lines.extend([
                "## Root Cause",
                self.root_cause,
                "",
            ])

        lines.extend([
            "## Changes",
        ])
        for patch in self.patches:
            lines.append(f"- **{patch.file_path}** ({patch.patch_type.value})")
            lines.append(f"  - {patch.rationale}")

        if self.impact_analysis:
            lines.extend([
                "",
                "## Impact Analysis",
                f"- **Risk Level:** {self.impact_analysis.risk_level}",
            ])
            if self.impact_analysis.affected_tables:
                lines.append(f"- **Affected Tables:** {', '.join(self.impact_analysis.affected_tables)}")
            if self.impact_analysis.downstream_dependencies:
                lines.append(f"- **Downstream:** {', '.join(self.impact_analysis.downstream_dependencies)}")

        if self.validations:
            lines.extend([
                "",
                "## Validation Results",
            ])
            for level, result in self.validations.items():
                emoji = "✅" if result.status == ValidationStatus.PASSED else "❌"
                lines.append(f"- {emoji} **{level.value}**: {result.status.value}")

        # Rollback steps from patches
        rollback_steps = []
        for patch in self.patches:
            rollback_steps.extend(patch.rollback_steps)

        if rollback_steps:
            lines.extend([
                "",
                "## Rollback Steps",
            ])
            for i, step in enumerate(rollback_steps, 1):
                lines.append(f"{i}. {step}")

        lines.extend([
            "",
            "---",
            f"🤖 Generated by [Pallisade Scout](https://pallisade.io) | Plan ID: `{self.id}`",
        ])

        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "root_cause": self.root_cause,
            "patches": [p.to_dict() for p in self.patches],
            "validations": {k.value: v.to_dict() for k, v in self.validations.items()},
            "impact_analysis": self.impact_analysis.to_dict() if self.impact_analysis else None,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "session_id": self.session_id,
            "pr_url": self.pr_url,
            "pr_number": self.pr_number,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChangePlan":
        """Create from dictionary."""
        validations = {}
        for level_str, result_data in data.get("validations", {}).items():
            level = ValidationLevel(level_str)
            validations[level] = ValidationResult.from_dict(result_data)

        return cls(
            id=data["id"],
            version=data.get("version", 1),
            title=data["title"],
            description=data.get("description", ""),
            root_cause=data.get("root_cause", ""),
            patches=[FilePatch.from_dict(p) for p in data.get("patches", [])],
            validations=validations,
            impact_analysis=ImpactAnalysis.from_dict(data["impact_analysis"]) if data.get("impact_analysis") else None,
            status=ChangePlanStatus(data.get("status", "draft")),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
            created_by=data.get("created_by", "scout"),
            session_id=data.get("session_id"),
            pr_url=data.get("pr_url"),
            pr_number=data.get("pr_number"),
        )
