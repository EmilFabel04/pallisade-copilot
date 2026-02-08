"""
ChangePlan Module

Provides structured change plan creation, validation, and application
for data pipeline fixes.
"""

from .models import (
    ValidationLevel,
    ValidationStatus,
    PatchType,
    ChangePlanStatus,
    FilePatch,
    ValidationResult,
    ImpactAnalysis,
    ChangePlan,
)

from .validators import (
    BaseValidator,
    StaticValidator,
    CIValidator,
    SandboxValidator,
    get_validator,
)

from .applier import (
    ApplyResult,
    ChangePlanApplier,
    ChangePlanStore,
    get_change_plan_store,
)

__all__ = [
    # Models
    "ValidationLevel",
    "ValidationStatus",
    "PatchType",
    "ChangePlanStatus",
    "FilePatch",
    "ValidationResult",
    "ImpactAnalysis",
    "ChangePlan",
    # Validators
    "BaseValidator",
    "StaticValidator",
    "CIValidator",
    "SandboxValidator",
    "get_validator",
    # Applier
    "ApplyResult",
    "ChangePlanApplier",
    "ChangePlanStore",
    "get_change_plan_store",
]
