"""
Canonical Identity Resolution for Cross-Tool Lineage

Provides a unified way to identify the same physical data asset
across multiple tools (warehouse, dbt, BI tools, etc.).

Canonical FQN format: {warehouse_type}:{database}.{schema}.{table}
Examples:
- bigquery:my-project.raw.customers
- snowflake:my_db.analytics.dim_orders
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set, Tuple
import hashlib
import re
import logging

logger = logging.getLogger(__name__)


@dataclass
class CanonicalIdentity:
    """Canonical identity for a data asset across tools."""

    canonical_fqn: str  # bigquery:project.dataset.table
    warehouse_type: str  # bigquery, snowflake, postgres, redshift
    database: str
    schema: str
    table: str

    # Discovery tracking
    discovered_by: List[str] = field(default_factory=list)
    discovery_metadata: Dict[str, Any] = field(default_factory=dict)

    # Confidence in the canonical mapping
    confidence: float = 1.0

    @property
    def node_id(self) -> str:
        """Generate a unique node ID from canonical FQN."""
        return hashlib.md5(self.canonical_fqn.lower().encode()).hexdigest()[:16]

    @classmethod
    def from_parts(
        cls,
        warehouse_type: str,
        database: str,
        schema: str,
        table: str,
        discovered_by: str = None,
    ) -> "CanonicalIdentity":
        """Create canonical identity from component parts."""
        # Normalize parts
        wh = warehouse_type.lower()
        db = database.lower() if database else ""
        sch = schema.lower() if schema else ""
        tbl = table.lower() if table else ""

        # Build canonical FQN
        fqn_parts = [p for p in [db, sch, tbl] if p]
        canonical_fqn = f"{wh}:{'.'.join(fqn_parts)}"

        return cls(
            canonical_fqn=canonical_fqn,
            warehouse_type=wh,
            database=db,
            schema=sch,
            table=tbl,
            discovered_by=[discovered_by] if discovered_by else [],
        )

    def matches(self, other: "CanonicalIdentity") -> bool:
        """Check if two identities refer to the same physical asset."""
        return self.canonical_fqn.lower() == other.canonical_fqn.lower()


class CanonicalResolver:
    """
    Resolves table references from various tools to canonical identities.

    Handles:
    - BigQuery: project.dataset.table or `project.dataset.table`
    - Snowflake: DATABASE.SCHEMA.TABLE (uppercase)
    - Postgres/Redshift: database.schema.table
    - dbt: source('source_name', 'table') or ref('model_name')
    - dbt manifest references: source.project.source_name.table_name
    """

    # Warehouse type detection patterns
    WAREHOUSE_PATTERNS = {
        "bigquery": [
            r"`[^`]+`",  # Backtick-quoted identifiers
            r"[a-z0-9-]+\.[a-z0-9_]+\.[a-z0-9_]+",  # project.dataset.table
        ],
        "snowflake": [
            r'"[^"]+"',  # Double-quoted identifiers
            r"[A-Z0-9_]+\.[A-Z0-9_]+\.[A-Z0-9_]+",  # UPPERCASE.NAMES
        ],
    }

    def __init__(
        self,
        default_warehouse: str = None,
        dbt_source_mappings: Dict[str, Dict[str, str]] = None,
        project_id: str = None,
    ):
        """
        Initialize the resolver.

        Args:
            default_warehouse: Default warehouse type when not inferrable
            dbt_source_mappings: Maps dbt source names to warehouse tables
                                 {"source_name.table": {"database": "x", "schema": "y", "table": "z"}}
            project_id: Default project/database for BigQuery
        """
        self.default_warehouse = default_warehouse or "bigquery"
        self.dbt_source_mappings = dbt_source_mappings or {}
        self.project_id = project_id

        # Cache resolved identities
        self._cache: Dict[str, CanonicalIdentity] = {}

    def resolve(
        self,
        reference: str,
        context: Dict[str, Any] = None,
        platform: str = None,
    ) -> Optional[CanonicalIdentity]:
        """
        Resolve any table reference to a canonical identity.

        Args:
            reference: Table reference (FQN, dbt ref, source name, etc.)
            context: Additional context (warehouse_type, database, schema defaults)
            platform: Platform that discovered this reference (bigquery, dbt, etc.)

        Returns:
            CanonicalIdentity or None if unresolvable
        """
        context = context or {}

        # Check cache
        cache_key = f"{platform}:{reference}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        identity = None

        # Try different resolution strategies
        if self._is_dbt_source_ref(reference):
            identity = self._resolve_dbt_source(reference, context, platform)
        elif self._is_dbt_model_ref(reference):
            identity = self._resolve_dbt_model(reference, context, platform)
        elif self._is_dbt_unique_id(reference):
            identity = self._resolve_dbt_unique_id(reference, context, platform)
        else:
            identity = self._resolve_fqn(reference, context, platform)

        if identity:
            self._cache[cache_key] = identity

        return identity

    def _is_dbt_source_ref(self, reference: str) -> bool:
        """Check if reference is a dbt source() call."""
        return reference.startswith("source(") or reference.startswith("source.")

    def _is_dbt_model_ref(self, reference: str) -> bool:
        """Check if reference is a dbt ref() call."""
        return reference.startswith("ref(") or reference.startswith("model.")

    def _is_dbt_unique_id(self, reference: str) -> bool:
        """Check if reference is a dbt unique_id format."""
        return any(
            reference.startswith(prefix)
            for prefix in ["source.", "model.", "seed.", "snapshot."]
        )

    def _resolve_dbt_source(
        self, reference: str, context: Dict, platform: str
    ) -> Optional[CanonicalIdentity]:
        """
        Resolve dbt source reference to warehouse table.

        Formats:
        - source('raw', 'customers') -> uses dbt_source_mappings
        - source.project.raw.customers -> parses directly
        """
        # Parse source reference
        if reference.startswith("source("):
            # source('source_name', 'table_name')
            match = re.match(r"source\(['\"]([^'\"]+)['\"],\s*['\"]([^'\"]+)['\"]\)", reference)
            if match:
                source_name, table_name = match.groups()
                mapping_key = f"{source_name}.{table_name}"
            else:
                return None
        elif reference.startswith("source."):
            # source.project.source_name.table_name
            parts = reference.split(".")
            if len(parts) >= 4:
                source_name = parts[2]
                table_name = parts[3]
                mapping_key = f"{source_name}.{table_name}"
            else:
                return None
        else:
            return None

        # Look up in source mappings
        if mapping_key in self.dbt_source_mappings:
            mapping = self.dbt_source_mappings[mapping_key]
            warehouse_type = context.get("warehouse_type", self.default_warehouse)

            return CanonicalIdentity.from_parts(
                warehouse_type=warehouse_type,
                database=mapping.get("database", self.project_id),
                schema=mapping.get("schema", source_name),
                table=mapping.get("table", table_name),
                discovered_by=platform,
            )

        # Fallback: use source_name as schema, table_name as table
        warehouse_type = context.get("warehouse_type", self.default_warehouse)
        database = context.get("database", self.project_id)

        return CanonicalIdentity.from_parts(
            warehouse_type=warehouse_type,
            database=database,
            schema=source_name,
            table=table_name,
            discovered_by=platform,
        )

    def _resolve_dbt_model(
        self, reference: str, context: Dict, platform: str
    ) -> Optional[CanonicalIdentity]:
        """
        Resolve dbt model reference to its materialization target.

        Uses context to determine target database/schema.
        """
        # Parse model reference
        if reference.startswith("ref("):
            match = re.match(r"ref\(['\"]([^'\"]+)['\"]\)", reference)
            model_name = match.group(1) if match else None
        elif reference.startswith("model."):
            parts = reference.split(".")
            model_name = parts[-1] if len(parts) >= 3 else None
        else:
            model_name = reference

        if not model_name:
            return None

        # Get target location from context
        warehouse_type = context.get("warehouse_type", self.default_warehouse)
        database = context.get("target_database", context.get("database", self.project_id))
        schema = context.get("target_schema", context.get("schema", ""))
        alias = context.get("alias", model_name)

        return CanonicalIdentity.from_parts(
            warehouse_type=warehouse_type,
            database=database,
            schema=schema,
            table=alias,
            discovered_by=platform,
        )

    def _resolve_dbt_unique_id(
        self, reference: str, context: Dict, platform: str
    ) -> Optional[CanonicalIdentity]:
        """Resolve dbt unique_id format references."""
        parts = reference.split(".")

        if reference.startswith("source.") and len(parts) >= 4:
            return self._resolve_dbt_source(reference, context, platform)
        elif reference.startswith("model.") and len(parts) >= 3:
            return self._resolve_dbt_model(reference, context, platform)
        elif reference.startswith("seed.") and len(parts) >= 3:
            # Seeds are similar to models
            return self._resolve_dbt_model(reference, context, platform)
        elif reference.startswith("snapshot.") and len(parts) >= 3:
            return self._resolve_dbt_model(reference, context, platform)

        return None

    def _resolve_fqn(
        self, reference: str, context: Dict, platform: str
    ) -> Optional[CanonicalIdentity]:
        """
        Resolve a fully qualified name to canonical identity.

        Handles various formats:
        - project.dataset.table (BigQuery)
        - database.schema.table (Snowflake/Postgres)
        - schema.table
        - table
        """
        # Clean up reference
        clean_ref = self._clean_reference(reference)

        # Parse into parts
        parts = clean_ref.split(".")

        # Determine warehouse type
        warehouse_type = context.get("warehouse_type") or self._infer_warehouse(reference)

        if len(parts) >= 3:
            database, schema, table = parts[-3], parts[-2], parts[-1]
        elif len(parts) == 2:
            database = context.get("database", self.project_id)
            schema, table = parts[0], parts[1]
        elif len(parts) == 1:
            database = context.get("database", self.project_id)
            schema = context.get("schema", "")
            table = parts[0]
        else:
            return None

        return CanonicalIdentity.from_parts(
            warehouse_type=warehouse_type,
            database=database,
            schema=schema,
            table=table,
            discovered_by=platform,
        )

    def _clean_reference(self, reference: str) -> str:
        """Remove quotes and brackets from reference."""
        # Remove backticks, double quotes, brackets
        clean = reference.replace("`", "").replace('"', "").replace("[", "").replace("]", "")
        # Normalize whitespace
        clean = " ".join(clean.split())
        return clean.strip()

    def _infer_warehouse(self, reference: str) -> str:
        """Infer warehouse type from reference format."""
        # BigQuery: backticks or lowercase with hyphens
        if "`" in reference or re.search(r"[a-z0-9-]+\.[a-z0-9_]+\.[a-z0-9_]+", reference):
            return "bigquery"

        # Snowflake: all uppercase or double quotes
        if reference.isupper() or '"' in reference:
            return "snowflake"

        return self.default_warehouse

    def match(self, ref1: str, ref2: str, context: Dict = None) -> bool:
        """
        Check if two references point to the same physical table.

        Args:
            ref1: First reference
            ref2: Second reference
            context: Resolution context

        Returns:
            True if they refer to the same table
        """
        context = context or {}

        identity1 = self.resolve(ref1, context)
        identity2 = self.resolve(ref2, context)

        if identity1 and identity2:
            return identity1.matches(identity2)

        return False

    def register_dbt_sources(self, sources: Dict[str, Any]) -> None:
        """
        Register dbt sources from manifest for resolution.

        Args:
            sources: dbt manifest sources section
        """
        for source_id, source_data in sources.items():
            # source_id format: source.project.source_name.table_name
            parts = source_id.split(".")
            if len(parts) >= 4:
                source_name = parts[2]
                table_name = parts[3]
                mapping_key = f"{source_name}.{table_name}"

                self.dbt_source_mappings[mapping_key] = {
                    "database": source_data.get("database"),
                    "schema": source_data.get("schema"),
                    "table": source_data.get("identifier", table_name),
                }

    def register_dbt_model_targets(self, models: Dict[str, Any]) -> None:
        """
        Register dbt model materialization targets.

        Args:
            models: dbt manifest nodes (models)
        """
        for model_id, model_data in models.items():
            if not model_id.startswith("model."):
                continue

            parts = model_id.split(".")
            if len(parts) >= 3:
                model_name = parts[-1]
                mapping_key = f"model.{model_name}"

                self.dbt_source_mappings[mapping_key] = {
                    "database": model_data.get("database"),
                    "schema": model_data.get("schema"),
                    "table": model_data.get("alias", model_name),
                }


def generate_canonical_node_id(canonical_fqn: str) -> str:
    """Generate a unique node ID from canonical FQN (standalone function)."""
    return hashlib.md5(canonical_fqn.lower().encode()).hexdigest()[:16]


def normalize_to_canonical_fqn(
    warehouse_type: str,
    database: str,
    schema: str,
    table: str,
) -> str:
    """Create canonical FQN from parts (standalone function)."""
    parts = [p.lower() for p in [database, schema, table] if p]
    return f"{warehouse_type.lower()}:{'.'.join(parts)}"


def normalize_with_hints(
    warehouse_type: str,
    database: str,
    schema: str,
    table: str,
    case_hint: str = "lower",
) -> str:
    """
    Create canonical FQN using adapter-provided case_hint.

    Args:
        warehouse_type: System identifier (e.g., "bigquery", "snowflake")
        database: Database/project name
        schema: Schema/dataset name
        table: Table/view name
        case_hint: One of "lower", "upper", "preserve" — provided by the adapter
                   based on its platform conventions, keeping vendor-specific
                   logic out of the core resolver.

    Returns:
        Canonical FQN string like "bigquery:my_project.raw.customers"
    """
    def _apply_hint(s: str) -> str:
        s = s.replace('`', '').replace('"', '').replace('[', '').replace(']', '').strip()
        if case_hint == "upper":
            return s.upper()
        elif case_hint == "lower":
            return s.lower()
        return s

    parts = [_apply_hint(p) for p in [database, schema, table] if p]
    return f"{_apply_hint(warehouse_type)}:{'.'.join(parts)}"
