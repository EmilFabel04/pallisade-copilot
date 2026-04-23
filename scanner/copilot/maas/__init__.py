"""
MAAS — Multi-Agent Architecture System for Pallisade Copilot.

Delegates narrow tasks to RunPod-hosted specialist models (SQL, Logs),
verifies their JSON output deterministically, and uses GPT-5 for tool execution
and final narration.

Enable via COPILOT_MAAS_ENABLED=true environment variable.
"""

from .config import MAASConfig, get_maas_config, is_maas_enabled
from .orchestrator import MAASOrchestrator
from .evidence_store import EvidenceStore

__all__ = [
    "MAASConfig",
    "get_maas_config",
    "is_maas_enabled",
    "MAASOrchestrator",
    "EvidenceStore",
]
