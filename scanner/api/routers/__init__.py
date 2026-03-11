"""
API Routers Module
"""

from .health import router as health_router
from .database import router as database_router
from .lineage import router as lineage_router
from .coverage import router as coverage_router
from .server import router as server_router
from .reporting import router as reporting_router

__all__ = [
    'health_router',
    'database_router',
    'lineage_router',
    'coverage_router',
    'server_router',
    'reporting_router',
]
