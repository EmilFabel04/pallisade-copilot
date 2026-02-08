"""
Factory for creating observability clients.

Creates the appropriate client based on integration type.
"""

from typing import Dict, Any, Optional
import logging

from .base import ObservabilityClient

logger = logging.getLogger(__name__)

# Mapping of integration types to client classes
# Clients are imported lazily to avoid import errors if dependencies are missing
CLIENT_TYPES = {
    "MONTE_CARLO": "monte_carlo.MonteCarloClient",
    "BIGEYE": "bigeye.BigeyeClient",
    "SODA": "soda.SodaClient",
    "ELEMENTARY": "elementary.ElementaryClient",
}

# Set of all observability integration types
OBSERVABILITY_TYPES = set(CLIENT_TYPES.keys())


def create_observability_client(
    integration_type: str,
    config: Dict[str, Any],
) -> Optional[ObservabilityClient]:
    """
    Create an observability client for the given integration type.

    Args:
        integration_type: Type of integration (MONTE_CARLO, BIGEYE, etc.)
        config: Configuration dictionary for the client

    Returns:
        ObservabilityClient instance or None if type not supported
    """
    integration_type = integration_type.upper()

    if integration_type not in CLIENT_TYPES:
        logger.warning(f"Unknown observability integration type: {integration_type}")
        return None

    client_path = CLIENT_TYPES[integration_type]
    module_name, class_name = client_path.rsplit(".", 1)

    try:
        # Lazy import of client class
        if integration_type == "MONTE_CARLO":
            from .monte_carlo import MonteCarloClient
            return MonteCarloClient(config)

        elif integration_type == "BIGEYE":
            from .bigeye import BigeyeClient
            return BigeyeClient(config)

        elif integration_type == "SODA":
            from .soda import SodaClient
            return SodaClient(config)

        elif integration_type == "ELEMENTARY":
            from .elementary import ElementaryClient
            return ElementaryClient(config)

    except ImportError as e:
        logger.error(f"Failed to import {integration_type} client: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to create {integration_type} client: {e}")
        return None

    return None


def is_observability_type(integration_type: str) -> bool:
    """Check if an integration type is an observability tool."""
    return integration_type.upper() in OBSERVABILITY_TYPES
