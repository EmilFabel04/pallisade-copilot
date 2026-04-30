"""Configuration constants for the clarification engine."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ClarificationConfig:
    confidence_threshold: float = 0.7
    dismiss_decay_days: int = 14
    borderline_band_lower: float = 1.5
    list_page_size: int = 50


CONFIG = ClarificationConfig()
