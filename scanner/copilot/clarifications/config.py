"""Configuration constants for the clarification engine."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ClarificationConfig:
    # Picker assigns 0.9 for strong matches (loaded_at, ingested_at), 0.7 for
    # medium (updated_at, modified_at), 0.5 for weak, 0.0 for none. Threshold
    # 0.85 = only strong matches skip the popup; most real-world tables that
    # lack a canonical loaded_at will trigger a clarification.
    confidence_threshold: float = 0.85
    dismiss_decay_days: int = 14
    borderline_band_lower: float = 1.5
    list_page_size: int = 50


CONFIG = ClarificationConfig()
