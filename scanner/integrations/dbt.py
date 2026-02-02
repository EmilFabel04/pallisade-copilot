"""
dbt Integration - Deep Analysis

Parses dbt artifacts to provide:
- Model lineage and dependencies
- Test coverage analysis
- Source freshness configuration
- Documentation completeness
- Model performance metrics

Supports:
- dbt Core (local files)
- dbt Cloud (API)
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class DbtResourceType(Enum):
    """Types of dbt resources."""
    MODEL = "model"
    SOURCE = "source"
    SEED = "seed"
    SNAPSHOT = "snapshot"
    TEST = "test"
    EXPOSURE = "exposure"
    METRIC = "metric"
    MACRO = "macro"


class DbtMaterialization(Enum):
    """dbt materialization types."""
    TABLE = "table"
    VIEW = "view"
    INCREMENTAL = "incremental"
    EPHEMERAL = "ephemeral"


@dataclass
class DbtColumn:
    """A column in a dbt model."""
    name: str
    description: Optional[str] = None
    data_type: Optional[str] = None
    tests: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def has_description(self) -> bool:
        return bool(self.description and self.description.strip())
    
    @property
    def is_tested(self) -> bool:
        return len(self.tests) > 0


@dataclass
class DbtModel:
    """A dbt model."""
    unique_id: str
    name: str
    database: Optional[str] = None
    schema: Optional[str] = None
    alias: Optional[str] = None
    description: Optional[str] = None
    materialization: DbtMaterialization = DbtMaterialization.VIEW
    columns: List[DbtColumn] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)  # upstream models
    tags: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    path: Optional[str] = None
    raw_sql: Optional[str] = None
    compiled_sql: Optional[str] = None
    
    @property
    def full_name(self) -> str:
        """Get fully qualified table name."""
        parts = [p for p in [self.database, self.schema, self.alias or self.name] if p]
        return '.'.join(parts)
    
    @property
    def has_description(self) -> bool:
        return bool(self.description and self.description.strip())
    
    @property
    def documented_columns(self) -> int:
        return sum(1 for c in self.columns if c.has_description)
    
    @property
    def tested_columns(self) -> int:
        return sum(1 for c in self.columns if c.is_tested)
    
    @property
    def documentation_coverage(self) -> float:
        """Percentage of columns with descriptions."""
        if not self.columns:
            return 1.0 if self.has_description else 0.0
        return self.documented_columns / len(self.columns)
    
    @property
    def test_coverage(self) -> float:
        """Percentage of columns with tests."""
        if not self.columns:
            return 0.0
        return self.tested_columns / len(self.columns)


@dataclass
class DbtSource:
    """A dbt source."""
    unique_id: str
    name: str
    source_name: str
    database: Optional[str] = None
    schema: Optional[str] = None
    description: Optional[str] = None
    loader: Optional[str] = None
    columns: List[DbtColumn] = field(default_factory=list)
    freshness: Optional[Dict[str, Any]] = None
    loaded_at_field: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def full_name(self) -> str:
        parts = [p for p in [self.database, self.schema, self.name] if p]
        return '.'.join(parts)
    
    @property
    def has_freshness_config(self) -> bool:
        return self.freshness is not None and self.loaded_at_field is not None
    
    @property
    def freshness_warn_hours(self) -> Optional[int]:
        if not self.freshness:
            return None
        warn = self.freshness.get('warn_after', {})
        count = warn.get('count', 0)
        period = warn.get('period', 'hour')
        
        multipliers = {'minute': 1/60, 'hour': 1, 'day': 24}
        return int(count * multipliers.get(period, 1))
    
    @property
    def freshness_error_hours(self) -> Optional[int]:
        if not self.freshness:
            return None
        error = self.freshness.get('error_after', {})
        count = error.get('count', 0)
        period = error.get('period', 'hour')
        
        multipliers = {'minute': 1/60, 'hour': 1, 'day': 24}
        return int(count * multipliers.get(period, 1))


@dataclass
class DbtTest:
    """A dbt test."""
    unique_id: str
    name: str
    test_type: str  # generic, singular
    column_name: Optional[str] = None
    model_name: Optional[str] = None
    test_metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    severity: str = "error"  # warn or error
    
    @property
    def is_schema_test(self) -> bool:
        return self.test_type == "generic"


@dataclass
class DbtExposure:
    """A dbt exposure (downstream consumer)."""
    unique_id: str
    name: str
    type: str  # dashboard, notebook, ml, application, analysis
    owner: Optional[Dict[str, str]] = None
    description: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    url: Optional[str] = None
    maturity: Optional[str] = None  # high, medium, low


@dataclass
class DbtManifest:
    """Parsed dbt manifest.json."""
    models: Dict[str, DbtModel] = field(default_factory=dict)
    sources: Dict[str, DbtSource] = field(default_factory=dict)
    tests: Dict[str, DbtTest] = field(default_factory=dict)
    exposures: Dict[str, DbtExposure] = field(default_factory=dict)
    macros: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    dbt_version: Optional[str] = None
    project_name: Optional[str] = None
    generated_at: Optional[datetime] = None
    
    @property
    def total_models(self) -> int:
        return len(self.models)
    
    @property
    def total_sources(self) -> int:
        return len(self.sources)
    
    @property
    def total_tests(self) -> int:
        return len(self.tests)
    
    @property
    def documented_models(self) -> int:
        return sum(1 for m in self.models.values() if m.has_description)
    
    @property
    def documentation_coverage(self) -> float:
        if not self.models:
            return 0.0
        return self.documented_models / len(self.models)
    
    @property
    def sources_with_freshness(self) -> int:
        return sum(1 for s in self.sources.values() if s.has_freshness_config)
    
    @property
    def freshness_coverage(self) -> float:
        if not self.sources:
            return 0.0
        return self.sources_with_freshness / len(self.sources)
    
    def get_model_by_name(self, name: str) -> Optional[DbtModel]:
        """Find model by name."""
        for model in self.models.values():
            if model.name == name:
                return model
        return None
    
    def get_upstream_models(self, model_name: str) -> List[DbtModel]:
        """Get all upstream dependencies of a model."""
        model = self.get_model_by_name(model_name)
        if not model:
            return []
        
        upstream = []
        for dep_id in model.depends_on:
            if dep_id in self.models:
                upstream.append(self.models[dep_id])
        return upstream
    
    def get_downstream_models(self, model_name: str) -> List[DbtModel]:
        """Get all models that depend on this model."""
        target_id = None
        for uid, model in self.models.items():
            if model.name == model_name:
                target_id = uid
                break
        
        if not target_id:
            return []
        
        downstream = []
        for model in self.models.values():
            if target_id in model.depends_on:
                downstream.append(model)
        return downstream
    
    def get_tests_for_model(self, model_name: str) -> List[DbtTest]:
        """Get all tests for a model."""
        return [t for t in self.tests.values() if t.model_name == model_name]
    
    def get_untested_models(self) -> List[DbtModel]:
        """Get models with no tests."""
        tested_models = set(t.model_name for t in self.tests.values() if t.model_name)
        return [m for m in self.models.values() if m.name not in tested_models]
    
    def get_undocumented_models(self) -> List[DbtModel]:
        """Get models without descriptions."""
        return [m for m in self.models.values() if not m.has_description]


class DbtIntegration:
    """
    Deep dbt integration for Pallisade.
    
    Capabilities:
    - Parse manifest.json for model metadata
    - Analyze test coverage
    - Check documentation completeness
    - Extract source freshness SLOs
    - Build lineage graph
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize dbt integration.
        
        Config options:
            project_dir: Path to dbt project
            manifest_path: Direct path to manifest.json
            target_path: Path to target/ directory (default: target/)
            
        For dbt Cloud:
            api_key: dbt Cloud API key
            account_id: Account ID
            project_id: Project ID
        """
        self.config = config or {}
        self.manifest: Optional[DbtManifest] = None
    
    def load_manifest(self, manifest_path: Optional[str] = None) -> DbtManifest:
        """
        Load and parse dbt manifest.json.
        
        Args:
            manifest_path: Path to manifest.json (optional if set in config)
            
        Returns:
            Parsed DbtManifest
        """
        path = manifest_path or self.config.get('manifest_path')
        
        if not path:
            # Try default locations
            project_dir = self.config.get('project_dir', '.')
            target_path = self.config.get('target_path', 'target')
            path = os.path.join(project_dir, target_path, 'manifest.json')
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"Manifest not found: {path}")
        
        with open(path, 'r') as f:
            raw = json.load(f)
        
        self.manifest = self._parse_manifest(raw)
        return self.manifest
    
    def _parse_manifest(self, raw: Dict[str, Any]) -> DbtManifest:
        """Parse raw manifest JSON into structured objects."""
        manifest = DbtManifest()
        
        # Metadata
        metadata = raw.get('metadata', {})
        manifest.dbt_version = metadata.get('dbt_version')
        manifest.project_name = metadata.get('project_name')
        
        if 'generated_at' in metadata:
            try:
                manifest.generated_at = datetime.fromisoformat(
                    metadata['generated_at'].replace('Z', '+00:00')
                )
            except Exception:
                pass
        
        # Parse nodes
        nodes = raw.get('nodes', {})
        for node_id, node in nodes.items():
            resource_type = node.get('resource_type')
            
            if resource_type == 'model':
                manifest.models[node_id] = self._parse_model(node_id, node)
            elif resource_type == 'test':
                manifest.tests[node_id] = self._parse_test(node_id, node)
        
        # Parse sources
        sources = raw.get('sources', {})
        for source_id, source in sources.items():
            manifest.sources[source_id] = self._parse_source(source_id, source)
        
        # Parse exposures
        exposures = raw.get('exposures', {})
        for exp_id, exposure in exposures.items():
            manifest.exposures[exp_id] = self._parse_exposure(exp_id, exposure)
        
        return manifest
    
    def _parse_model(self, node_id: str, node: Dict) -> DbtModel:
        """Parse a model node."""
        # Parse columns
        columns = []
        for col_name, col_data in node.get('columns', {}).items():
            columns.append(DbtColumn(
                name=col_name,
                description=col_data.get('description'),
                data_type=col_data.get('data_type'),
                tests=col_data.get('tests', []),
                meta=col_data.get('meta', {}),
            ))
        
        # Get materialization
        config = node.get('config', {})
        mat_str = config.get('materialized', 'view')
        try:
            materialization = DbtMaterialization(mat_str)
        except ValueError:
            materialization = DbtMaterialization.VIEW
        
        # Get dependencies
        depends_on = node.get('depends_on', {}).get('nodes', [])
        
        return DbtModel(
            unique_id=node_id,
            name=node.get('name', ''),
            database=node.get('database'),
            schema=node.get('schema'),
            alias=node.get('alias'),
            description=node.get('description'),
            materialization=materialization,
            columns=columns,
            depends_on=depends_on,
            tags=node.get('tags', []),
            meta=node.get('meta', {}),
            path=node.get('path'),
            raw_sql=node.get('raw_sql'),
            compiled_sql=node.get('compiled_sql'),
        )
    
    def _parse_source(self, source_id: str, source: Dict) -> DbtSource:
        """Parse a source node."""
        columns = []
        for col_name, col_data in source.get('columns', {}).items():
            columns.append(DbtColumn(
                name=col_name,
                description=col_data.get('description'),
                data_type=col_data.get('data_type'),
                meta=col_data.get('meta', {}),
            ))
        
        return DbtSource(
            unique_id=source_id,
            name=source.get('name', ''),
            source_name=source.get('source_name', ''),
            database=source.get('database'),
            schema=source.get('schema'),
            description=source.get('description'),
            loader=source.get('loader'),
            columns=columns,
            freshness=source.get('freshness'),
            loaded_at_field=source.get('loaded_at_field'),
            meta=source.get('meta', {}),
        )
    
    def _parse_test(self, test_id: str, test: Dict) -> DbtTest:
        """Parse a test node."""
        # Determine test type and extract info
        test_metadata = test.get('test_metadata', {})
        
        return DbtTest(
            unique_id=test_id,
            name=test.get('name', ''),
            test_type='generic' if test_metadata else 'singular',
            column_name=test.get('column_name'),
            model_name=test.get('attached_node', '').split('.')[-1] if test.get('attached_node') else None,
            test_metadata=test_metadata,
            tags=test.get('tags', []),
            severity=test.get('config', {}).get('severity', 'error'),
        )
    
    def _parse_exposure(self, exp_id: str, exposure: Dict) -> DbtExposure:
        """Parse an exposure node."""
        return DbtExposure(
            unique_id=exp_id,
            name=exposure.get('name', ''),
            type=exposure.get('type', 'application'),
            owner=exposure.get('owner'),
            description=exposure.get('description'),
            depends_on=exposure.get('depends_on', {}).get('nodes', []),
            url=exposure.get('url'),
            maturity=exposure.get('maturity'),
        )
    
    def analyze_test_coverage(self) -> Dict[str, Any]:
        """
        Analyze test coverage across the dbt project.
        
        Returns:
            Dict with coverage metrics and gaps
        """
        if not self.manifest:
            raise ValueError("Manifest not loaded. Call load_manifest() first.")
        
        total_models = len(self.manifest.models)
        tested_models = set()
        untested_columns: List[Dict] = []
        
        # Find tested models
        for test in self.manifest.tests.values():
            if test.model_name:
                tested_models.add(test.model_name)
        
        # Find untested columns
        for model in self.manifest.models.values():
            model_tests = self.manifest.get_tests_for_model(model.name)
            tested_cols = set(t.column_name for t in model_tests if t.column_name)
            
            for col in model.columns:
                if col.name not in tested_cols:
                    untested_columns.append({
                        'model': model.name,
                        'column': col.name,
                        'data_type': col.data_type,
                    })
        
        # Calculate metrics
        model_coverage = len(tested_models) / total_models if total_models > 0 else 0
        
        # Test breakdown by type
        test_types = {}
        for test in self.manifest.tests.values():
            test_name = test.test_metadata.get('name', 'singular')
            test_types[test_name] = test_types.get(test_name, 0) + 1
        
        return {
            'total_models': total_models,
            'tested_models': len(tested_models),
            'untested_models': total_models - len(tested_models),
            'model_coverage_pct': round(model_coverage * 100, 1),
            'total_tests': len(self.manifest.tests),
            'test_breakdown': test_types,
            'untested_columns': untested_columns[:50],  # Limit output
            'untested_models': [m.name for m in self.manifest.get_untested_models()],
        }
    
    def analyze_documentation(self) -> Dict[str, Any]:
        """
        Analyze documentation coverage.
        
        Returns:
            Dict with documentation metrics and gaps
        """
        if not self.manifest:
            raise ValueError("Manifest not loaded. Call load_manifest() first.")
        
        undocumented_models = []
        undocumented_columns = []
        
        for model in self.manifest.models.values():
            if not model.has_description:
                undocumented_models.append(model.name)
            
            for col in model.columns:
                if not col.has_description:
                    undocumented_columns.append({
                        'model': model.name,
                        'column': col.name,
                    })
        
        return {
            'total_models': len(self.manifest.models),
            'documented_models': self.manifest.documented_models,
            'undocumented_models': undocumented_models,
            'model_doc_coverage_pct': round(self.manifest.documentation_coverage * 100, 1),
            'undocumented_columns': undocumented_columns[:50],
        }
    
    def analyze_freshness_config(self) -> Dict[str, Any]:
        """
        Analyze source freshness configuration.
        
        Returns:
            Dict with freshness SLO configs and gaps
        """
        if not self.manifest:
            raise ValueError("Manifest not loaded. Call load_manifest() first.")
        
        sources_with_freshness = []
        sources_without_freshness = []
        
        for source in self.manifest.sources.values():
            if source.has_freshness_config:
                sources_with_freshness.append({
                    'source': source.source_name,
                    'table': source.name,
                    'loaded_at_field': source.loaded_at_field,
                    'warn_hours': source.freshness_warn_hours,
                    'error_hours': source.freshness_error_hours,
                })
            else:
                sources_without_freshness.append({
                    'source': source.source_name,
                    'table': source.name,
                })
        
        return {
            'total_sources': len(self.manifest.sources),
            'sources_with_freshness': len(sources_with_freshness),
            'freshness_coverage_pct': round(self.manifest.freshness_coverage * 100, 1),
            'configured_sources': sources_with_freshness,
            'unconfigured_sources': sources_without_freshness,
        }
    
    def get_lineage(self, model_name: str) -> Dict[str, Any]:
        """
        Get lineage for a specific model.
        
        Args:
            model_name: Name of the model
            
        Returns:
            Dict with upstream and downstream dependencies
        """
        if not self.manifest:
            raise ValueError("Manifest not loaded. Call load_manifest() first.")
        
        model = self.manifest.get_model_by_name(model_name)
        if not model:
            raise ValueError(f"Model not found: {model_name}")
        
        upstream = self.manifest.get_upstream_models(model_name)
        downstream = self.manifest.get_downstream_models(model_name)
        
        # Find source dependencies
        source_deps = []
        for dep_id in model.depends_on:
            if dep_id in self.manifest.sources:
                source_deps.append(self.manifest.sources[dep_id])
        
        # Find exposures using this model
        exposures_using = []
        for exposure in self.manifest.exposures.values():
            for dep in exposure.depends_on:
                if model_name in dep:
                    exposures_using.append(exposure)
                    break
        
        return {
            'model': model.name,
            'full_name': model.full_name,
            'materialization': model.materialization.value,
            'upstream_models': [m.name for m in upstream],
            'downstream_models': [m.name for m in downstream],
            'source_dependencies': [s.full_name for s in source_deps],
            'used_by_exposures': [e.name for e in exposures_using],
            'total_upstream': len(upstream) + len(source_deps),
            'total_downstream': len(downstream) + len(exposures_using),
        }
    
    def generate_test_recommendations(self) -> List[Dict[str, Any]]:
        """
        Generate test recommendations for untested models/columns.
        
        Returns:
            List of recommended tests with priority
        """
        if not self.manifest:
            raise ValueError("Manifest not loaded. Call load_manifest() first.")
        
        recommendations = []
        
        for model in self.manifest.models.values():
            model_tests = self.manifest.get_tests_for_model(model.name)
            tested_cols = set(t.column_name for t in model_tests if t.column_name)
            
            # Check for primary key columns without unique test
            for col in model.columns:
                col_lower = col.name.lower()
                
                # Likely primary key
                if col_lower in ('id', 'pk') or col_lower.endswith('_id'):
                    if col.name not in tested_cols:
                        recommendations.append({
                            'model': model.name,
                            'column': col.name,
                            'test': 'unique',
                            'priority': 'high',
                            'reason': 'Likely primary key column',
                        })
                
                # Likely foreign key
                if col_lower.endswith('_id') and col_lower != 'id':
                    recommendations.append({
                        'model': model.name,
                        'column': col.name,
                        'test': 'relationships',
                        'priority': 'medium',
                        'reason': 'Likely foreign key column',
                    })
                
                # Timestamp columns
                if 'timestamp' in col_lower or 'date' in col_lower or col_lower.endswith('_at'):
                    if col.name not in tested_cols:
                        recommendations.append({
                            'model': model.name,
                            'column': col.name,
                            'test': 'not_null',
                            'priority': 'medium',
                            'reason': 'Timestamp column',
                        })
        
        # Sort by priority
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        recommendations.sort(key=lambda x: priority_order.get(x['priority'], 2))
        
        return recommendations[:100]  # Limit output
    
    # =========================================================================
    # DEBUG METHODS
    # =========================================================================
    
    def get_model_sql(self, model_name: str) -> Dict[str, Any]:
        """
        Get raw and compiled SQL for a model.
        
        Args:
            model_name: Name of the model
            
        Returns:
            Dict with raw_sql, compiled_sql, and model metadata
        """
        if not self.manifest:
            raise ValueError("Manifest not loaded. Call load_manifest() first.")
        
        model = self.manifest.get_model_by_name(model_name)
        if not model:
            raise ValueError(f"Model not found: {model_name}")
        
        return {
            'model': model.name,
            'full_name': model.full_name,
            'path': model.path,
            'materialization': model.materialization.value,
            'raw_sql': model.raw_sql,
            'compiled_sql': model.compiled_sql,
            'database': model.database,
            'schema': model.schema,
            'alias': model.alias,
        }
    
    def get_test_results(self, model_name: str = None) -> Dict[str, Any]:
        """
        Get test results for a model or all models.
        
        Args:
            model_name: Optional model name to filter results
            
        Returns:
            Dict with test results summary and details
        """
        if not self.manifest:
            raise ValueError("Manifest not loaded. Call load_manifest() first.")
        
        tests = []
        if model_name:
            tests = self.manifest.get_tests_for_model(model_name)
        else:
            tests = list(self.manifest.tests.values())
        
        results = {
            'total_tests': len(tests),
            'by_type': {},
            'by_severity': {},
            'tests': [],
        }
        
        for test in tests:
            # Count by type
            test_type = test.test_metadata.get('name', 'singular')
            results['by_type'][test_type] = results['by_type'].get(test_type, 0) + 1
            
            # Count by severity
            results['by_severity'][test.severity] = results['by_severity'].get(test.severity, 0) + 1
            
            # Add test details
            results['tests'].append({
                'name': test.name,
                'type': test.test_type,
                'test_name': test_type,
                'model': test.model_name,
                'column': test.column_name,
                'severity': test.severity,
                'tags': test.tags,
            })
        
        return results
    
    def get_model_dependencies(self, model_name: str, include_sources: bool = True) -> Dict[str, Any]:
        """
        Get direct dependencies for a model.
        
        Args:
            model_name: Name of the model
            include_sources: Whether to include source dependencies
            
        Returns:
            Dict with direct upstream and downstream dependencies
        """
        if not self.manifest:
            raise ValueError("Manifest not loaded. Call load_manifest() first.")
        
        model = self.manifest.get_model_by_name(model_name)
        if not model:
            raise ValueError(f"Model not found: {model_name}")
        
        # Direct upstream models
        direct_upstream = []
        source_deps = []
        
        for dep_id in model.depends_on:
            if dep_id in self.manifest.models:
                upstream_model = self.manifest.models[dep_id]
                direct_upstream.append({
                    'name': upstream_model.name,
                    'full_name': upstream_model.full_name,
                    'type': 'model',
                    'materialization': upstream_model.materialization.value,
                })
            elif include_sources and dep_id in self.manifest.sources:
                source = self.manifest.sources[dep_id]
                source_deps.append({
                    'name': source.name,
                    'full_name': source.full_name,
                    'type': 'source',
                    'source_name': source.source_name,
                    'has_freshness': source.has_freshness_config,
                })
        
        # Direct downstream models
        target_id = None
        for uid, m in self.manifest.models.items():
            if m.name == model_name:
                target_id = uid
                break
        
        direct_downstream = []
        if target_id:
            for m in self.manifest.models.values():
                if target_id in m.depends_on:
                    direct_downstream.append({
                        'name': m.name,
                        'full_name': m.full_name,
                        'type': 'model',
                        'materialization': m.materialization.value,
                    })
        
        return {
            'model': model_name,
            'full_name': model.full_name,
            'upstream_models': direct_upstream,
            'source_dependencies': source_deps,
            'downstream_models': direct_downstream,
            'total_upstream': len(direct_upstream) + len(source_deps),
            'total_downstream': len(direct_downstream),
        }


# =============================================================================
# DBT CLOUD API CLIENT
# =============================================================================

class DbtCloudClient:
    """
    dbt Cloud API client for enterprise monitoring.
    
    Monitors:
    - Job run history and failures
    - Environment health
    - Model execution times
    - Run metadata
    """
    
    API_URL = "https://cloud.getdbt.com/api/v2"
    
    def __init__(self, api_key: str, account_id: int):
        """
        Initialize dbt Cloud client.
        
        Args:
            api_key: dbt Cloud service token or user API key
            account_id: dbt Cloud account ID
        """
        self.api_key = api_key
        self.account_id = account_id
        self._client = None
    
    def _get_client(self):
        """Get HTTP client."""
        if self._client is None:
            import httpx
            self._client = httpx.Client(
                base_url=self.API_URL,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=60.0,
            )
        return self._client
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make request to dbt Cloud API."""
        client = self._get_client()
        
        response = client.request(
            method,
            endpoint.lstrip('/'),
            **kwargs
        )
        
        if response.status_code >= 400:
            raise Exception(f"dbt Cloud API error: {response.status_code} - {response.text}")
        
        return response.json()
    
    def test_connection(self) -> tuple:
        """Test connection to dbt Cloud."""
        try:
            data = self._request("GET", f"/accounts/{self.account_id}/")
            account = data.get("data", {})
            return True, f"Connected to {account.get('name', 'dbt Cloud')}"
        except Exception as e:
            return False, str(e)
    
    # =========================================================================
    # PROJECT METHODS
    # =========================================================================
    
    def get_projects(self) -> List[Dict]:
        """Get all projects in the account."""
        data = self._request("GET", f"/accounts/{self.account_id}/projects/")
        return data.get("data", [])
    
    def get_project(self, project_id: int) -> Dict:
        """Get project details."""
        data = self._request("GET", f"/accounts/{self.account_id}/projects/{project_id}/")
        return data.get("data", {})
    
    # =========================================================================
    # JOB METHODS
    # =========================================================================
    
    def get_jobs(self, project_id: int = None) -> List[Dict]:
        """Get all jobs, optionally filtered by project."""
        params = {}
        if project_id:
            params["project_id"] = project_id
        
        data = self._request(
            "GET",
            f"/accounts/{self.account_id}/jobs/",
            params=params
        )
        return data.get("data", [])
    
    def get_job(self, job_id: int) -> Dict:
        """Get job details."""
        data = self._request("GET", f"/accounts/{self.account_id}/jobs/{job_id}/")
        return data.get("data", {})
    
    def get_job_runs(self, job_id: int, limit: int = 10) -> List[Dict]:
        """Get recent runs for a job."""
        data = self._request(
            "GET",
            f"/accounts/{self.account_id}/runs/",
            params={"job_definition_id": job_id, "limit": limit, "order_by": "-id"}
        )
        return data.get("data", [])
    
    # =========================================================================
    # RUN METHODS
    # =========================================================================
    
    def get_runs(self, limit: int = 50, status: str = None) -> List[Dict]:
        """
        Get recent runs across all jobs.
        
        Args:
            limit: Max runs to return
            status: Filter by status (Success, Error, Running, Queued, Cancelled)
        """
        params = {"limit": limit, "order_by": "-id"}
        if status:
            params["status"] = status
        
        data = self._request(
            "GET",
            f"/accounts/{self.account_id}/runs/",
            params=params
        )
        return data.get("data", [])
    
    def get_run(self, run_id: int) -> Dict:
        """Get run details."""
        data = self._request("GET", f"/accounts/{self.account_id}/runs/{run_id}/")
        return data.get("data", {})
    
    def get_run_artifact(self, run_id: int, artifact: str = "manifest.json") -> Dict:
        """
        Get artifact from a run (manifest.json, run_results.json, catalog.json).
        """
        data = self._request(
            "GET",
            f"/accounts/{self.account_id}/runs/{run_id}/artifacts/{artifact}"
        )
        return data
    
    # =========================================================================
    # ENVIRONMENT METHODS
    # =========================================================================
    
    def get_environments(self, project_id: int = None) -> List[Dict]:
        """Get all environments."""
        params = {}
        if project_id:
            params["project_id"] = project_id
        
        data = self._request(
            "GET",
            f"/accounts/{self.account_id}/environments/",
            params=params
        )
        return data.get("data", [])
    
    # =========================================================================
    # DEBUG METHODS
    # =========================================================================
    
    def get_run_logs(self, run_id: int) -> Dict[str, Any]:
        """
        Get execution logs for a dbt Cloud run.
        
        Args:
            run_id: The run ID
            
        Returns:
            Dict with run details and logs
        """
        # Get run details
        run = self.get_run(run_id)
        
        # Get run steps (contains log output)
        try:
            steps_data = self._request(
                "GET",
                f"/accounts/{self.account_id}/runs/{run_id}/steps/"
            )
            steps = steps_data.get("data", [])
        except Exception:
            steps = []
        
        # Try to get debug logs artifact
        debug_logs = None
        try:
            debug_logs = self._request(
                "GET",
                f"/accounts/{self.account_id}/runs/{run_id}/artifacts/dbt.log"
            )
        except Exception:
            pass  # Debug logs may not be available
        
        return {
            'run_id': run_id,
            'job_id': run.get('job_definition_id'),
            'status': run.get('status_humanized'),
            'status_code': run.get('status'),
            'started_at': run.get('started_at'),
            'finished_at': run.get('finished_at'),
            'duration_seconds': run.get('duration'),
            'trigger': run.get('trigger_humanized'),
            'error_message': run.get('status_message'),
            'steps': [
                {
                    'name': step.get('name'),
                    'status': step.get('status_humanized'),
                    'logs': step.get('logs'),
                    'truncated': step.get('logs_truncated', False),
                    'duration_seconds': step.get('duration'),
                }
                for step in steps
            ],
            'debug_logs': debug_logs,
        }
    
    def get_model_run_results(self, run_id: int, model_name: str = None) -> Dict[str, Any]:
        """
        Get detailed run results for models from a specific run.
        
        Args:
            run_id: The run ID
            model_name: Optional model name to filter results
            
        Returns:
            Dict with model execution details
        """
        try:
            results = self.get_run_artifact(run_id, "run_results.json")
        except Exception as e:
            raise ValueError(f"Could not retrieve run_results.json: {e}")
        
        model_results = []
        for result in results.get("results", []):
            unique_id = result.get("unique_id", "")
            node_name = unique_id.split(".")[-1] if unique_id else ""
            
            # Filter by model name if provided
            if model_name and node_name != model_name:
                continue
            
            model_results.append({
                'unique_id': unique_id,
                'name': node_name,
                'status': result.get('status'),
                'execution_time': result.get('execution_time'),
                'rows_affected': result.get('adapter_response', {}).get('rows_affected'),
                'message': result.get('message'),
                'timing': result.get('timing', []),
                'thread_id': result.get('thread_id'),
            })
        
        return {
            'run_id': run_id,
            'elapsed_time': results.get('elapsed_time'),
            'generated_at': results.get('metadata', {}).get('generated_at'),
            'dbt_version': results.get('metadata', {}).get('dbt_version'),
            'models': model_results,
            'total_models': len(model_results),
        }
    
    def get_test_results(self, run_id: int) -> Dict[str, Any]:
        """
        Get test results from a specific dbt Cloud run.
        
        Args:
            run_id: The run ID
            
        Returns:
            Dict with test execution results
        """
        try:
            results = self.get_run_artifact(run_id, "run_results.json")
        except Exception as e:
            raise ValueError(f"Could not retrieve run_results.json: {e}")
        
        test_results = {
            'run_id': run_id,
            'total_tests': 0,
            'passed': 0,
            'failed': 0,
            'warned': 0,
            'skipped': 0,
            'tests': [],
        }
        
        for result in results.get("results", []):
            unique_id = result.get("unique_id", "")
            
            # Filter for tests only
            if not unique_id.startswith("test."):
                continue
            
            status = result.get("status", "").lower()
            test_results['total_tests'] += 1
            
            if status == "pass":
                test_results['passed'] += 1
            elif status == "fail":
                test_results['failed'] += 1
            elif status == "warn":
                test_results['warned'] += 1
            elif status == "skip":
                test_results['skipped'] += 1
            
            test_results['tests'].append({
                'unique_id': unique_id,
                'name': unique_id.split(".")[-1],
                'status': status,
                'execution_time': result.get('execution_time'),
                'message': result.get('message'),
                'failures': result.get('failures', 0),
            })
        
        return test_results
    
    def get_recent_failures(self, job_id: int = None, limit: int = 10) -> Dict[str, Any]:
        """
        Get recent failed runs with error details.
        
        Args:
            job_id: Optional job ID to filter by
            limit: Number of failures to return
            
        Returns:
            Dict with recent failure details
        """
        # Get failed runs
        params = {"limit": limit * 2, "status": "20", "order_by": "-id"}  # 20 = Error
        if job_id:
            params["job_definition_id"] = job_id
        
        data = self._request(
            "GET",
            f"/accounts/{self.account_id}/runs/",
            params=params
        )
        
        runs = data.get("data", [])[:limit]
        
        failures = []
        for run in runs:
            run_id = run.get("id")
            
            # Get basic failure info
            failure = {
                'run_id': run_id,
                'job_id': run.get('job_definition_id'),
                'job_name': run.get('job', {}).get('name', 'Unknown'),
                'status_message': run.get('status_message'),
                'started_at': run.get('started_at'),
                'finished_at': run.get('finished_at'),
                'duration_seconds': run.get('duration'),
                'trigger': run.get('trigger_humanized'),
            }
            
            # Try to get more detailed error info
            try:
                steps = self._request(
                    "GET",
                    f"/accounts/{self.account_id}/runs/{run_id}/steps/"
                ).get("data", [])
                
                # Find failed step
                for step in steps:
                    if step.get("status") == 20:  # Failed
                        failure['failed_step'] = step.get('name')
                        failure['step_logs'] = step.get('logs', '')[:1000]  # Truncate
                        break
            except Exception:
                pass
            
            failures.append(failure)
        
        return {
            'total_failures': len(failures),
            'job_id': job_id,
            'failures': failures,
        }


class DbtCloudScanner:
    """
    Enterprise-grade dbt Cloud scanner.
    
    Monitors:
    1. Job health (success rates, failures)
    2. Run duration trends
    3. Model execution times
    4. Test results
    5. Documentation coverage
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize scanner with dbt Cloud credentials.
        
        Config:
            api_key: dbt Cloud API key
            account_id: Account ID
        """
        self.client = DbtCloudClient(
            api_key=config.get("api_key"),
            account_id=config.get("account_id"),
        )
        
        # Thresholds
        self.thresholds = {
            "success_rate_warning": config.get("success_rate_warning", 0.9),
            "success_rate_critical": config.get("success_rate_critical", 0.75),
            "run_duration_warning_minutes": config.get("run_duration_warning_minutes", 60),
            "consecutive_failures": config.get("consecutive_failures", 2),
        }
    
    def scan(self) -> Dict[str, Any]:
        """
        Run full dbt Cloud health scan.
        
        Returns:
            Dict with findings, metrics, and health score
        """
        findings = []
        metrics = {
            "jobs_scanned": 0,
            "healthy_jobs": 0,
            "failing_jobs": 0,
            "recent_runs_scanned": 0,
            "failed_runs_24h": 0,
            "avg_run_duration_minutes": 0,
        }
        
        # 1. Scan Jobs
        logger.info("Scanning dbt Cloud jobs...")
        job_findings = self._scan_jobs()
        findings.extend(job_findings["findings"])
        metrics.update(job_findings["metrics"])
        
        # 2. Analyze Recent Runs
        logger.info("Analyzing recent dbt Cloud runs...")
        run_findings = self._scan_runs()
        findings.extend(run_findings["findings"])
        metrics.update(run_findings["metrics"])
        
        # 3. Check Latest Run Artifacts (test results)
        logger.info("Checking latest run artifacts...")
        artifact_findings = self._scan_artifacts()
        findings.extend(artifact_findings["findings"])
        
        # Calculate health score
        critical_count = sum(1 for f in findings if f.get("severity") == "critical")
        high_count = sum(1 for f in findings if f.get("severity") == "high")
        medium_count = sum(1 for f in findings if f.get("severity") == "medium")
        
        health_score = max(0, 100 - (critical_count * 25) - (high_count * 10) - (medium_count * 3))
        
        return {
            "scan_type": "dbt_cloud",
            "status": "critical" if critical_count > 0 else "warning" if high_count > 0 else "healthy",
            "health_score": health_score,
            "findings": findings,
            "metrics": metrics,
            "scanned_at": datetime.now().isoformat(),
        }
    
    def _scan_jobs(self) -> Dict:
        """Scan all jobs for health issues."""
        findings = []
        metrics = {
            "jobs_scanned": 0,
            "healthy_jobs": 0,
            "failing_jobs": 0,
        }
        
        try:
            jobs = self.client.get_jobs()
            metrics["jobs_scanned"] = len(jobs)
            
            for job in jobs:
                job_id = job.get("id")
                job_name = job.get("name", "Unknown")
                project_id = job.get("project_id")
                
                # Get recent runs for this job
                runs = self.client.get_job_runs(job_id, limit=10)
                
                if not runs:
                    continue
                
                # Calculate success rate
                success_count = sum(1 for r in runs if r.get("status") == 10)  # 10 = Success
                success_rate = success_count / len(runs)
                
                # Check for consecutive failures
                consecutive_failures = 0
                for run in runs:
                    if run.get("status") == 20:  # 20 = Error
                        consecutive_failures += 1
                    else:
                        break
                
                if consecutive_failures >= self.thresholds["consecutive_failures"]:
                    metrics["failing_jobs"] += 1
                    findings.append({
                        "type": "job_failing",
                        "severity": "critical" if consecutive_failures >= 3 else "high",
                        "title": f"dbt Job Failing: {job_name}",
                        "description": f"Job '{job_name}' has failed {consecutive_failures} consecutive times.",
                        "resource": f"job/{job_id}",
                        "resource_type": "dbt_cloud_job",
                        "suggested_fix": {
                            "type": "manual",
                            "action": "Check dbt Cloud run logs for error details",
                        },
                    })
                elif success_rate < self.thresholds["success_rate_critical"]:
                    metrics["failing_jobs"] += 1
                    findings.append({
                        "type": "low_success_rate",
                        "severity": "high",
                        "title": f"Low Success Rate: {job_name}",
                        "description": f"Job '{job_name}' has only {success_rate*100:.0f}% success rate over last 10 runs.",
                        "resource": f"job/{job_id}",
                        "resource_type": "dbt_cloud_job",
                    })
                elif success_rate < self.thresholds["success_rate_warning"]:
                    findings.append({
                        "type": "success_rate_warning",
                        "severity": "medium",
                        "title": f"Declining Success Rate: {job_name}",
                        "description": f"Job '{job_name}' has {success_rate*100:.0f}% success rate over last 10 runs.",
                        "resource": f"job/{job_id}",
                        "resource_type": "dbt_cloud_job",
                    })
                else:
                    metrics["healthy_jobs"] += 1
                
                # Check run duration trends
                durations = []
                for run in runs:
                    if run.get("duration"):
                        durations.append(run["duration"] / 60)  # Convert to minutes
                
                if durations:
                    avg_duration = sum(durations) / len(durations)
                    if avg_duration > self.thresholds["run_duration_warning_minutes"]:
                        findings.append({
                            "type": "long_running_job",
                            "severity": "medium",
                            "title": f"Long Running Job: {job_name}",
                            "description": f"Job '{job_name}' has average duration of {avg_duration:.0f} minutes.",
                            "resource": f"job/{job_id}",
                            "resource_type": "dbt_cloud_job",
                        })
                        
        except Exception as e:
            logger.error(f"Error scanning jobs: {e}")
            findings.append({
                "type": "scan_error",
                "severity": "medium",
                "title": "Job Scan Error",
                "description": f"Could not complete job scan: {str(e)}",
            })
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_runs(self) -> Dict:
        """Analyze recent runs across all jobs."""
        findings = []
        metrics = {
            "recent_runs_scanned": 0,
            "failed_runs_24h": 0,
        }
        
        try:
            # Get failed runs from last 24 hours
            failed_runs = self.client.get_runs(limit=50, status="20")  # 20 = Error
            
            # Filter to last 24 hours
            from datetime import timezone
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            
            recent_failures = []
            for run in failed_runs:
                finished_at = run.get("finished_at")
                if finished_at:
                    try:
                        run_time = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                        if run_time > cutoff:
                            recent_failures.append(run)
                    except Exception:
                        pass
            
            metrics["failed_runs_24h"] = len(recent_failures)
            
            if len(recent_failures) > 5:
                findings.append({
                    "type": "many_failed_runs",
                    "severity": "high",
                    "title": f"High Number of Failed Runs ({len(recent_failures)} in 24h)",
                    "description": f"There have been {len(recent_failures)} failed dbt runs in the last 24 hours.",
                    "resource_type": "dbt_cloud_runs",
                })
                
        except Exception as e:
            logger.error(f"Error scanning runs: {e}")
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_artifacts(self) -> Dict:
        """Check latest run artifacts for issues."""
        findings = []
        
        try:
            # Get latest successful run
            runs = self.client.get_runs(limit=5, status="10")  # 10 = Success
            
            if runs:
                latest_run = runs[0]
                run_id = latest_run.get("id")
                
                # Try to get run_results.json
                try:
                    results = self.client.get_run_artifact(run_id, "run_results.json")
                    
                    # Check for test failures
                    test_failures = []
                    for result in results.get("results", []):
                        if result.get("status") == "fail":
                            test_failures.append({
                                "node": result.get("unique_id"),
                                "message": result.get("message", ""),
                            })
                    
                    if test_failures:
                        findings.append({
                            "type": "dbt_test_failures",
                            "severity": "high",
                            "title": f"dbt Tests Failing ({len(test_failures)} tests)",
                            "description": f"The latest successful run had {len(test_failures)} failing tests.",
                            "resource": f"run/{run_id}",
                            "resource_type": "dbt_cloud_run",
                            "details": {"failures": test_failures[:5]},
                        })
                except Exception:
                    # Artifact may not be available
                    pass
                    
        except Exception as e:
            logger.error(f"Error scanning artifacts: {e}")
        
        return {"findings": findings, "metrics": {}}
