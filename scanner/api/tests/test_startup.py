"""Tests for Settings validation at startup."""

import pytest
from unittest.mock import patch

from scanner.api.dependencies import Settings


class TestSettingsProd:
    def test_prod_missing_shared_secret_raises(self):
        with patch.dict("os.environ", {"ENVIRONMENT": "production"}, clear=True):
            with pytest.raises(RuntimeError, match="SCANNER_SHARED_SECRET"):
                Settings()

    def test_prod_short_shared_secret_raises(self):
        env = {"ENVIRONMENT": "production", "SCANNER_SHARED_SECRET": "tooshort", "ALLOWED_ORIGINS": "https://app.example.com"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="SCANNER_SHARED_SECRET.*32"):
                Settings()

    def test_prod_wildcard_origins_raises(self):
        env = {"ENVIRONMENT": "production", "SCANNER_SHARED_SECRET": "a" * 64, "ALLOWED_ORIGINS": "*"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
                Settings()

    def test_prod_unset_origins_raises(self):
        env = {"ENVIRONMENT": "production", "SCANNER_SHARED_SECRET": "a" * 64}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
                Settings()

    def test_prod_valid_config_succeeds(self):
        env = {
            "ENVIRONMENT": "production",
            "SCANNER_SHARED_SECRET": "a" * 64,
            "ALLOWED_ORIGINS": "https://app.example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            s = Settings()
            assert s.shared_secret == "a" * 64
            assert s.allowed_origins == ["https://app.example.com"]

    def test_dev_missing_shared_secret_uses_default(self):
        with patch.dict("os.environ", {"ENVIRONMENT": "development"}, clear=True):
            s = Settings()
            assert s.shared_secret == "dev-insecure-secret-do-not-use-in-production"


class TestLoopbackCheck:
    def test_prod_non_loopback_raises(self):
        from scanner.api.app import enforce_loopback_in_production
        with pytest.raises(RuntimeError, match="loopback"):
            enforce_loopback_in_production(environment="production", host="0.0.0.0")

    def test_prod_loopback_v4_passes(self):
        from scanner.api.app import enforce_loopback_in_production
        enforce_loopback_in_production(environment="production", host="127.0.0.1")  # no raise

    def test_prod_loopback_v6_passes(self):
        from scanner.api.app import enforce_loopback_in_production
        enforce_loopback_in_production(environment="production", host="::1")

    def test_dev_non_loopback_allowed(self):
        from scanner.api.app import enforce_loopback_in_production
        enforce_loopback_in_production(environment="development", host="0.0.0.0")
