"""
BigQuery lineage parser.

Extracts lineage from:
- INFORMATION_SCHEMA.JOBS
- INFORMATION_SCHEMA.VIEWS
- Data Catalog lineage API (if enabled)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from .base import BaseParser
from .sql_parser import SQLLineageParser
from ..graph import LineageGraph, LineageNode, LineageEdge, NodeType, EdgeType


class BigQueryParser(BaseParser):
    """
    Extract lineage from BigQuery metadata.
    
    Uses:
    1. INFORMATION_SCHEMA.JOBS for query history
    2. INFORMATION_SCHEMA.VIEWS for view definitions
    3. Data Catalog Lineage API (if available)
    """
    
    PLATFORM = "bigquery"
    DIALECT = "bigquery"
    
    # Common BigQuery regions to try if region is set to 'auto'
    COMMON_REGIONS = [
        "us",           # Multi-region US
        "eu",           # Multi-region EU
        "us-central1",  # Iowa
        "us-east1",     # South Carolina
        "us-west1",     # Oregon
        "europe-west1", # Belgium
        "europe-west2", # London
        "asia-east1",   # Taiwan
        "asia-northeast1", # Tokyo
    ]
    
    def __init__(
        self, 
        client, 
        project_id: str, 
        region: str = "us",
        days_back: int = 30,
        enable_data_catalog: bool = True,
        selected_datasets: Optional[List[str]] = None,
        **kwargs
    ):
        """
        Initialize BigQuery lineage parser.
        
        Args:
            client: BigQuery client instance
            project_id: GCP project ID
            region: BigQuery region for INFORMATION_SCHEMA queries.
                   Use 'auto' to try common regions automatically.
                   Common values: 'us', 'eu', 'us-central1', etc.
            days_back: Number of days of job history to analyze
            enable_data_catalog: Whether to use Data Catalog Lineage API
            selected_datasets: Optional list of datasets to include. If None, all datasets are included.
        """
        super().__init__(**kwargs)
        self.client = client
        self.project_id = project_id
        self.region = region
        self.days_back = days_back
        self.enable_data_catalog = enable_data_catalog
        self.selected_datasets = selected_datasets  # Filter to specific datasets if provided
        self.sql_parser = SQLLineageParser(dialect="bigquery")
        self._detected_region: Optional[str] = None
    
    def parse(self) -> LineageGraph:
        """Build lineage from BigQuery metadata."""
        try:
            print(f"📊 BigQuery lineage: project={self.project_id}, region={self.region}")
            
            # Discover datasets and tables
            self._discover_objects()
            tables_count = len(self.graph.nodes)
            views_count = len([n for n in self.graph.nodes.values() if n.node_type in (NodeType.VIEW, NodeType.MATERIALIZED_VIEW)])
            print(f"   Found {tables_count} objects ({views_count} views)")
            
            # Parse job history from INFORMATION_SCHEMA
            edges_before = len(self.graph.edges)
            self._parse_job_history()
            job_edges = len(self.graph.edges) - edges_before
            print(f"   Job history: +{job_edges} edges")
            
            # Parse view dependencies
            edges_before = len(self.graph.edges)
            self._parse_views()
            view_edges = len(self.graph.edges) - edges_before
            print(f"   View definitions: +{view_edges} edges")
            
            # Parse Data Catalog Lineage API (if enabled)
            if self.enable_data_catalog:
                edges_before = len(self.graph.edges)
                self._parse_data_catalog_lineage()
                catalog_edges = len(self.graph.edges) - edges_before
                if catalog_edges > 0:
                    print(f"   Data Catalog API: +{catalog_edges} edges")
            
            self.graph.compute_depths()
            self.graph.built_at = datetime.utcnow()
            
            print(f"✅ BigQuery parser: {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges total")
            
        except Exception as e:
            self.add_error(f"Failed to parse BigQuery lineage: {e}")
            import traceback
            traceback.print_exc()
        
        return self.graph
    
    def _discover_objects(self) -> None:
        """Discover all tables across datasets."""
        try:
            # List all datasets
            all_datasets = list(self.client.list_datasets(self.project_id))
            
            # Filter to selected datasets if specified
            if self.selected_datasets:
                datasets = [d for d in all_datasets if d.dataset_id in self.selected_datasets]
                print(f"   Filtering to {len(datasets)} of {len(all_datasets)} datasets: {self.selected_datasets}")
            else:
                datasets = all_datasets
            
            for dataset_ref in datasets:
                dataset_id = dataset_ref.dataset_id
                
                # List tables in dataset
                tables = list(self.client.list_tables(f"{self.project_id}.{dataset_id}"))
                
                for table_ref in tables:
                    table = self.client.get_table(table_ref)
                    
                    fqn = f"{self.project_id}.{dataset_id}.{table.table_id}"
                    
                    # Determine type
                    if table.table_type == "VIEW":
                        node_type = NodeType.VIEW
                    elif table.table_type == "MATERIALIZED_VIEW":
                        node_type = NodeType.MATERIALIZED_VIEW
                    elif table.table_type == "EXTERNAL":
                        node_type = NodeType.SOURCE
                    else:
                        node_type = NodeType.TABLE
                    
                    node = self.create_table_node(
                        fqn=fqn,
                        database=self.project_id,
                        schema=dataset_id,
                        table=table.table_id,
                        node_type=node_type,
                        row_count=table.num_rows,
                        description=table.description,
                    )
                    node.last_updated = table.modified
                    
                    # Add columns
                    columns = []
                    for field in table.schema:
                        columns.append({
                            "name": field.name,
                            "data_type": field.field_type,
                            "description": field.description,
                            "mode": field.mode,
                        })
                    node.columns = columns
                    
                    self.graph.add_node(node)
                    
        except Exception as e:
            self.add_error(f"Failed to discover objects: {e}")
    
    def _get_regions_to_try(self) -> List[str]:
        """Get list of regions to try for INFORMATION_SCHEMA queries."""
        if self.region == "auto":
            return self.COMMON_REGIONS
        return [self.region]
    
    def _build_jobs_query(self, region: str) -> str:
        """Build the INFORMATION_SCHEMA.JOBS query for a specific region."""
        return f"""
            SELECT
                job_id,
                query,
                destination_table.project_id as dest_project,
                destination_table.dataset_id as dest_dataset,
                destination_table.table_id as dest_table,
                referenced_tables,
                creation_time
            FROM `{self.project_id}.region-{region}.INFORMATION_SCHEMA.JOBS`
            WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {self.days_back} DAY)
            AND job_type = 'QUERY'
            AND state = 'DONE'
            AND error_result IS NULL
            AND destination_table.table_id IS NOT NULL
            ORDER BY creation_time DESC
            LIMIT 10000
        """

    def _parse_job_history(self) -> None:
        """Parse INFORMATION_SCHEMA.JOBS for lineage with multi-region support."""
        regions_to_try = self._get_regions_to_try()
        job_count = 0

        for region in regions_to_try:
            try:
                query = self._build_jobs_query(region)
                results = self.client.query(query).result()

                # If we got results, mark this as the detected region
                if self._detected_region is None:
                    self._detected_region = region
                    print(f"📍 Using BigQuery region: {region}")

                for row in results:
                    dest_table = row.dest_table
                    if not dest_table:
                        continue

                    target_fqn = f"{row.dest_project}.{row.dest_dataset}.{dest_table}"
                    target_id = self.generate_node_id(target_fqn)

                    # Process referenced tables
                    for ref_table in (row.referenced_tables or []):
                        source_fqn = f"{ref_table['project_id']}.{ref_table['dataset_id']}.{ref_table['table_id']}"
                        source_id = self.generate_node_id(source_fqn)

                        if source_id in self.graph.nodes and target_id in self.graph.nodes:
                            edge = self.create_edge(
                                source_id=source_id,
                                target_id=target_id,
                                edge_type=EdgeType.DERIVED_FROM,
                                discovered_from="job_history",
                            )
                            self.graph.add_edge(edge)
                            job_count += 1

                # If not in auto mode, don't try other regions
                if self.region != "auto":
                    break

            except Exception as e:
                error_msg = str(e)
                # Permission errors apply to all regions — stop immediately
                if "Access Denied" in error_msg or "403" in error_msg:
                    self.add_error(
                        f"No permission to query INFORMATION_SCHEMA.JOBS "
                        f"(needs bigquery.jobs.list). Skipping job history. "
                        f"View-definition lineage will still work."
                    )
                    return
                # If the region doesn't exist, try the next one
                if "Not found" in error_msg or "Invalid region" in error_msg:
                    if self.region == "auto":
                        continue  # Try next region
                    else:
                        self.add_error(f"Region '{region}' not found. Try 'auto' for auto-detection.")
                else:
                    self.add_error(f"Failed to parse job history in region {region}: {e}")
                    if self.region != "auto":
                        break

        if job_count == 0 and self.region == "auto":
            self.add_error("No job history found in any common region. Check project permissions.")
    
    def _parse_views(self) -> None:
        """Parse view definitions for dependencies with column-level lineage."""
        try:
            # Get all view definitions
            views_found = 0
            for node in list(self.graph.nodes.values()):
                if node.node_type not in (NodeType.VIEW, NodeType.MATERIALIZED_VIEW):
                    continue
                views_found += 1
                
                try:
                    table = self.client.get_table(node.fqn)
                    view_query = table.view_query or table.mview_query
                    
                    if view_query:
                        print(f"   Parsing view: {node.fqn}")
                        # Use column-level lineage parsing
                        lineage_result = self.sql_parser.parse_with_columns(view_query)
                        
                        sources = lineage_result.get("source_tables", set())
                        column_lineage = lineage_result.get("column_lineage", [])
                        print(f"      Sources found: {sources}")
                        
                        for source_fqn in sources:
                            # Try to match the source to existing nodes
                            # The SQL parser returns normalized lowercase names
                            source_id = self.generate_node_id(source_fqn)
                            
                            # Also try matching without project prefix (just dataset.table)
                            source_id_short = None
                            if '.' in source_fqn:
                                parts = source_fqn.split('.')
                                if len(parts) >= 2:
                                    # Try dataset.table format
                                    short_name = '.'.join(parts[-2:])
                                    source_id_short = self.generate_node_id(f"{self.project_id}.{short_name}")
                            
                            matched_id = None
                            if source_id in self.graph.nodes:
                                matched_id = source_id
                            elif source_id_short and source_id_short in self.graph.nodes:
                                matched_id = source_id_short
                            else:
                                # Try finding by FQN suffix match
                                for nid, n in self.graph.nodes.items():
                                    if n.fqn.lower().endswith(source_fqn.lower()) or source_fqn.lower().endswith(n.fqn.lower().split('.')[-1]):
                                        matched_id = nid
                                        break
                            
                            if matched_id:
                                print(f"      -> Matched {source_fqn} to node")
                                # Extract column mappings for this source table
                                columns_from_source = [
                                    col for col in column_lineage 
                                    if col.get("source_table") and 
                                    source_fqn.lower().endswith(col["source_table"])
                                ]
                                
                                # Build column mapping list
                                column_mapping = []
                                for col in columns_from_source:
                                    mapping = {
                                        "source": col.get("source_column"),
                                        "target": col.get("target_column"),
                                    }
                                    if col.get("transform"):
                                        mapping["transform"] = col["transform"][:200]
                                    column_mapping.append(mapping)
                                
                                edge = self.create_edge(
                                    source_id=matched_id,  # Use matched_id instead of source_id
                                    target_id=node.id,
                                    edge_type=EdgeType.DEPENDS_ON,
                                    transformation=view_query[:500],
                                    discovered_from="view_definition",
                                )
                                
                                # Add column lineage to edge metadata
                                if column_mapping:
                                    edge.columns = column_mapping
                                
                                self.graph.add_edge(edge)
                            else:
                                print(f"      -> No match for {source_fqn}")
                except Exception as e:
                    print(f"      Error processing view {node.fqn}: {e}")
                    continue
            
            if views_found == 0:
                print("   No views found in the graph")
                    
        except Exception as e:
            self.add_error(f"Failed to parse views: {e}")

    def _parse_data_catalog_lineage(self) -> None:
        """
        Parse lineage from Google Cloud Data Catalog Lineage API.
        
        This provides authoritative lineage information that supplements
        the INFORMATION_SCHEMA.JOBS data. It captures lineage from:
        - BigQuery jobs
        - Dataflow pipelines
        - Dataproc jobs
        - Custom integrations
        """
        try:
            # Try to import the Data Catalog Lineage client
            try:
                from google.cloud import datacatalog_lineage_v1
            except ImportError:
                # Library not installed, skip silently
                print("ℹ️ Data Catalog Lineage API not available (install google-cloud-datacatalog-lineage)")
                return
            
            # Determine the location to use
            location = self._detected_region or self.region
            if location == "auto":
                location = "us"  # Default to US for Data Catalog
            
            # Convert region format (e.g., "us-central1" stays as-is, "us" stays as-is)
            lineage_location = location
            
            # Create the lineage client
            lineage_client = datacatalog_lineage_v1.LineageClient()
            
            # Parent resource for lineage queries
            parent = f"projects/{self.project_id}/locations/{lineage_location}"
            
            edge_count = 0
            
            # Search for lineage links related to BigQuery tables
            for node in list(self.graph.nodes.values()):
                try:
                    # Build the BigQuery table resource name for Data Catalog
                    # Format: //bigquery.googleapis.com/projects/{project}/datasets/{dataset}/tables/{table}
                    bq_resource = f"//bigquery.googleapis.com/projects/{self.project_id}/datasets/{node.schema}/tables/{node.table}"
                    
                    # Search for links where this table is the target (upstream lineage)
                    target_request = datacatalog_lineage_v1.SearchLinksRequest(
                        parent=parent,
                        target=datacatalog_lineage_v1.EntityReference(
                            fully_qualified_name=bq_resource
                        ),
                    )
                    
                    try:
                        target_links = lineage_client.search_links(request=target_request)
                        
                        for link in target_links:
                            # Extract source table info from the link
                            source_fqn = self._parse_bq_resource_to_fqn(link.source.fully_qualified_name)
                            
                            if source_fqn:
                                source_id = self.generate_node_id(source_fqn)
                                
                                if source_id in self.graph.nodes:
                                    # Check if edge already exists
                                    edge_key = f"{source_id}_{node.id}"
                                    if edge_key not in self.graph.edges:
                                        edge = self.create_edge(
                                            source_id=source_id,
                                            target_id=node.id,
                                            edge_type=EdgeType.DERIVED_FROM,
                                            discovered_from="data_catalog_lineage",
                                        )
                                        self.graph.add_edge(edge)
                                        edge_count += 1
                    except Exception:
                        # Individual link search failed, continue
                        continue
                        
                    # Search for links where this table is the source (downstream lineage)
                    source_request = datacatalog_lineage_v1.SearchLinksRequest(
                        parent=parent,
                        source=datacatalog_lineage_v1.EntityReference(
                            fully_qualified_name=bq_resource
                        ),
                    )
                    
                    try:
                        source_links = lineage_client.search_links(request=source_request)
                        
                        for link in source_links:
                            # Extract target table info from the link
                            target_fqn = self._parse_bq_resource_to_fqn(link.target.fully_qualified_name)
                            
                            if target_fqn:
                                target_id = self.generate_node_id(target_fqn)
                                
                                if target_id in self.graph.nodes:
                                    # Check if edge already exists
                                    edge_key = f"{node.id}_{target_id}"
                                    if edge_key not in self.graph.edges:
                                        edge = self.create_edge(
                                            source_id=node.id,
                                            target_id=target_id,
                                            edge_type=EdgeType.DERIVED_FROM,
                                            discovered_from="data_catalog_lineage",
                                        )
                                        self.graph.add_edge(edge)
                                        edge_count += 1
                    except Exception:
                        # Individual link search failed, continue
                        continue
                        
                except Exception:
                    # Skip tables that fail
                    continue
            
            if edge_count > 0:
                print(f"📊 Data Catalog Lineage API: added {edge_count} edges")
                
        except Exception as e:
            # Don't fail the whole parse if Data Catalog fails
            self.add_error(f"Data Catalog Lineage API error (non-fatal): {e}")

    def _parse_bq_resource_to_fqn(self, resource_name: str) -> Optional[str]:
        """
        Convert a BigQuery resource name to a fully qualified table name.
        
        Input: //bigquery.googleapis.com/projects/{project}/datasets/{dataset}/tables/{table}
        Output: {project}.{dataset}.{table}
        """
        if not resource_name or "bigquery.googleapis.com" not in resource_name:
            return None
        
        try:
            # Parse the resource name
            parts = resource_name.split("/")
            
            # Find project, dataset, and table
            project = None
            dataset = None
            table = None
            
            for i, part in enumerate(parts):
                if part == "projects" and i + 1 < len(parts):
                    project = parts[i + 1]
                elif part == "datasets" and i + 1 < len(parts):
                    dataset = parts[i + 1]
                elif part == "tables" and i + 1 < len(parts):
                    table = parts[i + 1]
            
            if project and dataset and table:
                return f"{project}.{dataset}.{table}"
            
            return None
            
        except Exception:
            return None

