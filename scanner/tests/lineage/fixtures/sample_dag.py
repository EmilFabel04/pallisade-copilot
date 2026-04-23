"""
Sample Airflow DAG file for testing the parser.

Contains various patterns: BQ operators, PythonOperator, >> dependencies,
TaskFlow API, transfer operators, and Jinja templates.
"""
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.operators.bigquery import (
    BigQueryInsertJobOperator,
    BigQueryExecuteQueryOperator,
)
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator
from datetime import datetime

default_args = {
    "owner": "data-team",
    "retries": 2,
}

with DAG(
    "etl_pipeline",
    schedule="@daily",
    default_args=default_args,
    tags=["etl", "production"],
    description="Daily ETL pipeline for analytics",
) as dag:

    extract_raw = BigQueryInsertJobOperator(
        task_id="extract_raw",
        configuration={
            "query": {
                "query": "SELECT * FROM `project.raw.events` WHERE date = '{{ ds }}'",
                "destinationTable": {
                    "projectId": "project",
                    "datasetId": "staging",
                    "tableId": "events_staging",
                },
                "writeDisposition": "WRITE_TRUNCATE",
            }
        },
    )

    transform_data = BigQueryExecuteQueryOperator(
        task_id="transform_data",
        sql="INSERT INTO project.analytics.user_events SELECT * FROM project.staging.events_staging JOIN project.raw.users ON events_staging.user_id = users.id",
    )

    load_to_gcs = GCSToBigQueryOperator(
        task_id="load_to_gcs",
        destination_dataset_table="project.raw.external_data",
        source_project_dataset_table="other_project.exports.daily_dump",
    )

    run_python_checks = PythonOperator(
        task_id="run_python_checks",
        python_callable=lambda: print("checks done"),
    )

    extract_raw >> transform_data >> run_python_checks
    load_to_gcs >> transform_data
