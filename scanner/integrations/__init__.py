"""
Pallisade Pipeline Integrations

Deep integrations with data pipeline tools:
- dbt: Manifest parsing, test coverage, model health
- Airflow: DAG monitoring, task status, SLA tracking
- Fivetran: Connector status, sync health, freshness
- Prefect: Flow monitoring, deployment health
- Dagster: Asset monitoring, job health
- Airbyte: Connection monitoring
"""

from .dbt import DbtIntegration, DbtManifest, DbtModel, DbtTest, DbtSource
from .airflow import AirflowIntegration, AirflowDAG, AirflowTask, AirflowDAGRun
from .fivetran import FivetranIntegration, FivetranConnector

# New orchestration integrations
try:
    from .dagster import DagsterIntegration, DagsterAsset, DagsterRun
except ImportError:
    DagsterIntegration = None
    DagsterAsset = None
    DagsterRun = None

try:
    from .prefect import PrefectIntegration, PrefectFlow, PrefectFlowRun, PrefectDeployment
except ImportError:
    PrefectIntegration = None
    PrefectFlow = None
    PrefectFlowRun = None
    PrefectDeployment = None

try:
    from .n8n import N8nIntegration, N8nWorkflow, N8nExecution
except ImportError:
    N8nIntegration = None
    N8nWorkflow = None
    N8nExecution = None

__all__ = [
    # dbt
    'DbtIntegration',
    'DbtManifest',
    'DbtModel',
    'DbtTest',
    'DbtSource',
    # Airflow
    'AirflowIntegration',
    'AirflowDAG',
    'AirflowDAGRun',
    'AirflowTask',
    # Fivetran
    'FivetranIntegration',
    'FivetranConnector',
    # Dagster
    'DagsterIntegration',
    'DagsterAsset',
    'DagsterRun',
    # Prefect
    'PrefectIntegration',
    'PrefectFlow',
    'PrefectFlowRun',
    'PrefectDeployment',
    # n8n
    'N8nIntegration',
    'N8nWorkflow',
    'N8nExecution',
]

