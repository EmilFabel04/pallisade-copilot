"""
Shared Dependencies for API Routers

Common utilities, validation, and authentication logic.
"""

import os
import sys
import logging
from typing import Optional
from functools import lru_cache
from pathlib import Path

import structlog

# Load environment variables from .env file (parent directory)
try:
    from dotenv import load_dotenv
    # Try multiple locations for .env
    env_paths = [
        Path(__file__).parent.parent.parent / ".env",  # /scanner/../.env
        Path(__file__).parent.parent / ".env",  # /scanner/.env
        Path.cwd() / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path, override=False)
except ImportError:
    pass  # dotenv not installed, rely on system environment

logger = structlog.get_logger()


# ===========================================
# Configuration
# ===========================================

class Settings:
    """Application settings from environment variables."""

    DEV_SHARED_SECRET = "dev-insecure-secret-do-not-use-in-production"

    def __init__(self):
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.version = "2.0.0"
        self.encryption_key = os.getenv("ENCRYPTION_KEY", "")

        allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "")
        self.allowed_origins = [o.strip() for o in allowed_origins_raw.split(",") if o.strip()]

        shared_secret_env = os.getenv("SCANNER_SHARED_SECRET", "")

        is_prod = self.environment == "production"

        if is_prod:
            if not shared_secret_env:
                raise RuntimeError(
                    "SCANNER_SHARED_SECRET must be set in production (min 32 bytes)"
                )
            if len(shared_secret_env) < 32:
                raise RuntimeError(
                    "SCANNER_SHARED_SECRET must be at least 32 bytes in production"
                )
            if not self.allowed_origins or self.allowed_origins == ["*"]:
                raise RuntimeError(
                    "ALLOWED_ORIGINS must be an explicit comma-separated list in production (not '*' or empty)"
                )
            self.shared_secret = shared_secret_env
        else:
            self.shared_secret = shared_secret_env or self.DEV_SHARED_SECRET
            if not self.allowed_origins:
                self.allowed_origins = ["*"]


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# ===========================================
# Logging Setup
# ===========================================

def setup_logging():
    """Configure structured logging with console-friendly output in development."""
    settings = get_settings()
    
    # Set up standard logging
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    
    # Choose renderer based on environment
    if settings.environment == "development":
        # Human-readable console output for development
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.rich_traceback
        )
    else:
        # JSON for production (easier to parse in log aggregators)
        renderer = structlog.processors.JSONRenderer()
    
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Log startup message
    startup_logger = structlog.get_logger("pallisade.startup")
    startup_logger.info(
        "logging_configured",
        environment=settings.environment,
        log_level=settings.log_level,
        renderer="console" if settings.environment == "development" else "json"
    )


# ===========================================
# Common Utilities
# ===========================================

def calculate_drr_score(findings: list) -> int:
    """
    Calculate Data Reliability Rating score based on findings.
    
    Returns a score from 0-100 where 100 is perfect.
    """
    if not findings:
        return 100
    
    # Weight by severity
    severity_weights = {
        'critical': 25,
        'high': 15,
        'medium': 8,
        'low': 3,
        'info': 1,
    }
    
    total_deduction = 0
    for finding in findings:
        severity = finding.get('severity', 'medium').lower()
        weight = severity_weights.get(severity, 5)
        total_deduction += weight
    
    # Cap at 0
    score = max(0, 100 - total_deduction)
    return score


def parse_table_name(full_name: str) -> tuple:
    """
    Parse a fully qualified table name into schema and table.
    
    Args:
        full_name: Table name like 'schema.table' or just 'table'
        
    Returns:
        Tuple of (schema, table)
    """
    parts = full_name.split('.')
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None, parts[-1]
