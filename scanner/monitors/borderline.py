"""Classify a z-scored monitor result as clear/borderline/drastic."""
from dataclasses import dataclass
from copilot.clarifications.config import CONFIG as CLARIFICATION_CONFIG


@dataclass(frozen=True)
class BorderlineConfig:
    lower: float = CLARIFICATION_CONFIG.borderline_band_lower


DEFAULT = BorderlineConfig()


def classify_severity(
    *,
    z_score: float,
    sensitivity_threshold: float,
    config: BorderlineConfig = DEFAULT,
) -> str:
    """Return 'clear' | 'borderline' | 'drastic'."""
    abs_z = abs(z_score)
    if abs_z < config.lower:
        return "clear"
    if abs_z >= sensitivity_threshold:
        return "drastic"
    return "borderline"
