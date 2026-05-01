import pytest
from scanner.monitors.borderline import classify_severity, BorderlineConfig


def test_clear_when_z_below_lower_band():
    out = classify_severity(z_score=1.0, sensitivity_threshold=3.0)
    assert out == "clear"


def test_drastic_when_z_above_threshold():
    out = classify_severity(z_score=3.5, sensitivity_threshold=3.0)
    assert out == "drastic"


def test_borderline_inside_band():
    out = classify_severity(z_score=2.2, sensitivity_threshold=3.0)
    assert out == "borderline"


def test_negative_z_uses_abs():
    out = classify_severity(z_score=-2.5, sensitivity_threshold=3.0)
    assert out == "borderline"


def test_custom_lower_bound():
    cfg = BorderlineConfig(lower=2.0)
    assert classify_severity(z_score=1.8, sensitivity_threshold=3.0, config=cfg) == "clear"
    assert classify_severity(z_score=2.5, sensitivity_threshold=3.0, config=cfg) == "borderline"
