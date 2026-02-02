"""
Database Discovery Router - Fetch tables, schemas, and metadata from connected databases
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionConfig(BaseModel):
    """Database connection configuration."""
    connection_type: str  # bigquery, snowflake, postgres, redshift, sqlserver
    connection_config: Dict[str, Any]


def get_adapter(connection_type: str, config: Dict[str, Any]):
    """Get the appropriate database adapter."""
    from scanner.adapters.bigquery import BigQueryAdapter
    from scanner.adapters.snowflake import SnowflakeAdapter
    from scanner.adapters.postgres import PostgresAdapter
    from scanner.adapters.redshift import RedshiftAdapter
    from scanner.adapters.sqlserver import SQLServerAdapter
    
    adapters = {
        'bigquery': BigQueryAdapter,
        'snowflake': SnowflakeAdapter,
        'postgres': PostgresAdapter,
        'redshift': RedshiftAdapter,
        'sqlserver': SQLServerAdapter,
    }
    
    adapter_class = adapters.get(connection_type)
    if not adapter_class:
        raise ValueError(f"Unsupported connection type: {connection_type}")
    
    return adapter_class(config)


@router.post("/tables")
async def get_tables(config: ConnectionConfig) -> Dict[str, Any]:
    """
    Fetch tables from a database connection.
    
    Supports: BigQuery, Snowflake, PostgreSQL, Redshift, SQL Server
    """
    try:
        connection_type = config.connection_type.lower()
        conn_config = config.connection_config
        
        logger.info(f"Fetching tables for {connection_type}")
        
        # Handle BigQuery specifically
        if connection_type == 'bigquery':
            return await get_bigquery_tables(conn_config)
        
        # Handle other databases
        adapter = get_adapter(connection_type, conn_config)
        
        if not adapter.connect():
            return {"success": False, "tables": [], "error": "Failed to connect to database"}
        
        try:
            # Get schemas/databases
            schemas = conn_config.get('schemas', [])
            if not schemas:
                schemas = ['public']  # Default for Postgres-like DBs
            
            all_tables = []
            database = conn_config.get('database', '')
            
            for schema in schemas:
                tables = adapter.get_tables(schema=schema)
                for table in tables:
                    # Parse table name
                    parts = table.split('.') if isinstance(table, str) else [table.get('name', '')]
                    table_name = parts[-1] if parts else table
                    
                    # Get metadata if possible
                    try:
                        metadata = adapter.get_table_metadata(table)
                        all_tables.append({
                            "name": table_name,
                            "schema": schema,
                            "database": database,
                            "columns": len(metadata.columns) if metadata.columns else None,
                            "rowCount": metadata.row_count,
                        })
                    except Exception:
                        all_tables.append({
                            "name": table_name,
                            "schema": schema,
                            "database": database,
                        })
            
            return {
                "success": True,
                "tables": all_tables,
                "schemas": schemas,
                "source": "live",
            }
        finally:
            adapter.disconnect()
            
    except Exception as e:
        logger.error(f"Error fetching tables: {e}")
        return {
            "success": False,
            "tables": [],
            "error": str(e),
        }


async def get_bigquery_tables(config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch tables from BigQuery using configured datasets."""
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
        
        project_id = config.get('project_id')
        credentials_json = config.get('credentials') or config.get('credentials_json')
        datasets = config.get('datasets', [])
        location = config.get('location', 'US')
        
        if not project_id:
            return {"success": False, "tables": [], "error": "project_id is required"}
        
        logger.info(f"Connecting to BigQuery project: {project_id}, datasets: {datasets}")
        
        # Parse credentials if string
        if isinstance(credentials_json, str):
            try:
                credentials_json = json.loads(credentials_json)
            except json.JSONDecodeError:
                pass
        
        # Create client
        if credentials_json and isinstance(credentials_json, dict):
            credentials = service_account.Credentials.from_service_account_info(credentials_json)
            client = bigquery.Client(project=project_id, credentials=credentials, location=location)
        else:
            # Use default credentials
            client = bigquery.Client(project=project_id, location=location)
        
        all_tables: List[Dict[str, Any]] = []
        found_datasets: List[str] = []
        
        # If no datasets specified, discover them
        if not datasets:
            try:
                discovered = list(client.list_datasets())
                datasets = [d.dataset_id for d in discovered]
                logger.info(f"Discovered datasets: {datasets}")
            except Exception as e:
                logger.warning(f"Could not list datasets: {e}")
                datasets = []
        
        # Fetch tables from each dataset
        for dataset_id in datasets:
            try:
                logger.info(f"Listing tables in dataset: {dataset_id}")
                dataset_ref = client.dataset(dataset_id)
                tables = list(client.list_tables(dataset_ref))
                found_datasets.append(dataset_id)
                
                logger.info(f"Found {len(tables)} tables in {dataset_id}")
                
                # First, try to get accurate row counts from INFORMATION_SCHEMA
                row_counts = {}
                try:
                    query = f"""
                        SELECT table_name, total_rows
                        FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.TABLE_STORAGE`
                    """
                    results = client.query(query).result()
                    for row in results:
                        row_counts[row.table_name] = row.total_rows
                    logger.info(f"Got row counts from INFORMATION_SCHEMA for {len(row_counts)} tables")
                except Exception as e:
                    logger.warning(f"Could not query INFORMATION_SCHEMA for {dataset_id}: {e}")
                
                for table in tables:
                    # Get table metadata
                    try:
                        full_table = client.get_table(table.reference)
                        # Determine table type
                        table_type = "TABLE"
                        if full_table.table_type == "VIEW":
                            table_type = "VIEW"
                        elif full_table.table_type == "MATERIALIZED_VIEW":
                            table_type = "MATERIALIZED VIEW"
                        elif full_table.table_type == "EXTERNAL":
                            table_type = "EXTERNAL"
                        
                        # Get row count - prefer INFORMATION_SCHEMA, fall back to num_rows
                        # Views don't have row counts (they're virtual), so return None for them
                        if table_type == "VIEW":
                            row_count = None  # Views don't store rows
                        else:
                            row_count = row_counts.get(table.table_id)
                            if row_count is None:
                                row_count = full_table.num_rows
                        
                        logger.info(f"Table {table.table_id}: type={table_type}, rows={row_count}, cols={len(full_table.schema) if full_table.schema else 0}")
                        
                        all_tables.append({
                            "name": table.table_id,
                            "dataset": dataset_id,
                            "schema": dataset_id,
                            "database": project_id,
                            "columns": len(full_table.schema) if full_table.schema else None,
                            "rowCount": row_count,
                            "type": table_type,
                        })
                    except Exception as e:
                        logger.warning(f"Could not get metadata for {table.table_id}: {e}")
                        all_tables.append({
                            "name": table.table_id,
                            "dataset": dataset_id,
                            "schema": dataset_id,
                            "database": project_id,
                            "type": "TABLE",
                        })
                        
            except Exception as e:
                logger.error(f"Error listing tables in dataset {dataset_id}: {e}")
        
        client.close()
        
        logger.info(f"Total tables found: {len(all_tables)}")
        
        return {
            "success": True,
            "tables": all_tables,
            "datasets": found_datasets,
            "source": "live",
        }
        
    except ImportError:
        logger.error("google-cloud-bigquery not installed")
        return {
            "success": False,
            "tables": [],
            "error": "BigQuery client not installed. Run: pip install google-cloud-bigquery",
        }
    except Exception as e:
        logger.error(f"BigQuery error: {e}")
        return {
            "success": False,
            "tables": [],
            "error": str(e),
        }


@router.post("/test-connection")
async def test_connection(config: ConnectionConfig) -> Dict[str, Any]:
    """Test a database connection."""
    try:
        connection_type = config.connection_type.lower()
        conn_config = config.connection_config
        
        if connection_type == 'bigquery':
            # Test BigQuery connection
            from google.cloud import bigquery
            from google.oauth2 import service_account
            
            project_id = conn_config.get('project_id')
            credentials_json = conn_config.get('credentials') or conn_config.get('credentials_json')
            
            if isinstance(credentials_json, str):
                credentials_json = json.loads(credentials_json)
            
            if credentials_json:
                credentials = service_account.Credentials.from_service_account_info(credentials_json)
                client = bigquery.Client(project=project_id, credentials=credentials)
            else:
                client = bigquery.Client(project=project_id)
            
            # Test query
            list(client.query("SELECT 1").result())
            client.close()
            
            return {"success": True, "message": f"Connected to BigQuery project: {project_id}"}
        
        # Test other databases
        adapter = get_adapter(connection_type, conn_config)
        success, message = adapter.test_connection()
        adapter.disconnect()
        
        return {"success": success, "message": message}
        
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return {"success": False, "message": str(e)}
