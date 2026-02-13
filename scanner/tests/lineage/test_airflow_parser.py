"""Tests for the Airflow DAG file AST parser."""

import os
import pytest

from scanner.lineage.engine.adapters.airflow_parser import (
    ParsedDag,
    ParsedTask,
    parse_dag_file,
    parse_dag_files,
    _extract_tables_from_sql,
    _strip_jinja,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return f.read()


# ---------------------------------------------------------------------------
# parse_dag_file — basic DAG detection
# ---------------------------------------------------------------------------

class TestParseDag:
    def test_parse_simple_dag(self):
        content = _read_fixture("sample_dag.py")
        dags = parse_dag_file(content, "sample_dag.py")
        assert len(dags) == 1
        dag = dags[0]
        assert dag.dag_id == "etl_pipeline"
        assert dag.schedule == "@daily"
        # owner is in a variable reference (default_args=default_args),
        # which AST parser can't resolve without code execution
        assert dag.owner is None
        assert set(dag.tags) == {"etl", "production"}
        assert dag.description == "Daily ETL pipeline for analytics"

    def test_parse_task_count(self):
        content = _read_fixture("sample_dag.py")
        dags = parse_dag_file(content, "sample_dag.py")
        dag = dags[0]
        assert len(dag.tasks) == 4
        assert "extract_raw" in dag.tasks
        assert "transform_data" in dag.tasks
        assert "load_to_gcs" in dag.tasks
        assert "run_python_checks" in dag.tasks

    def test_parse_task_dependencies(self):
        content = _read_fixture("sample_dag.py")
        dags = parse_dag_file(content, "sample_dag.py")
        dag = dags[0]
        deps = dag.dependencies
        # extract_raw >> transform_data >> run_python_checks
        assert ("extract_raw", "transform_data") in deps
        assert ("transform_data", "run_python_checks") in deps
        # load_to_gcs >> transform_data
        assert ("load_to_gcs", "transform_data") in deps

    def test_parse_bq_operator_sql(self):
        content = _read_fixture("sample_dag.py")
        dags = parse_dag_file(content, "sample_dag.py")
        dag = dags[0]
        task = dag.tasks["extract_raw"]
        assert task.sql is not None
        assert "project.raw.events" in task.sql

    def test_parse_bq_destination_from_config(self):
        content = _read_fixture("sample_dag.py")
        dags = parse_dag_file(content, "sample_dag.py")
        dag = dags[0]
        task = dag.tasks["extract_raw"]
        assert task.destination_table == "project.staging.events_staging"

    def test_parse_opaque_operator(self):
        content = _read_fixture("sample_dag.py")
        dags = parse_dag_file(content, "sample_dag.py")
        dag = dags[0]
        task = dag.tasks["run_python_checks"]
        assert task.is_opaque is True
        assert task.sql is None
        assert task.source_tables == []
        assert task.destination_table is None

    def test_parse_transfer_operator_tables(self):
        content = _read_fixture("sample_dag.py")
        dags = parse_dag_file(content, "sample_dag.py")
        dag = dags[0]
        task = dag.tasks["load_to_gcs"]
        assert task.destination_table == "project.raw.external_data"
        assert "other_project.exports.daily_dump" in task.source_tables


# ---------------------------------------------------------------------------
# Inline DAG patterns
# ---------------------------------------------------------------------------

class TestInlineDagPatterns:
    def test_dag_assignment(self):
        code = '''
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

dag = DAG("my_dag", schedule="@hourly")

t1 = PythonOperator(task_id="t1", python_callable=lambda: None, dag=dag)
'''
        dags = parse_dag_file(code, "inline.py")
        assert len(dags) == 1
        assert dags[0].dag_id == "my_dag"
        assert dags[0].schedule == "@hourly"

    def test_taskflow_api(self):
        code = '''
from airflow.decorators import task
from airflow import DAG

with DAG("taskflow_dag") as dag:
    @task
    def extract():
        return 42

    @task()
    def transform(data):
        return data * 2
'''
        dags = parse_dag_file(code, "taskflow.py")
        assert len(dags) == 1
        dag = dags[0]
        assert "extract" in dag.tasks
        assert "transform" in dag.tasks
        assert dag.tasks["extract"].operator_class == "@task"
        assert dag.tasks["extract"].is_opaque is True

    def test_dag_decorator_basic(self):
        """@dag decorator should create a DAG with function name as dag_id."""
        code = '''
from airflow.decorators import dag, task

@dag(schedule="@daily")
def my_pipeline():
    @task
    def extract():
        return 42

    @task()
    def transform(data):
        return data * 2
'''
        dags = parse_dag_file(code, "dag_decorator.py")
        assert len(dags) == 1
        dag = dags[0]
        assert dag.dag_id == "my_pipeline"
        assert dag.schedule == "@daily"
        assert "extract" in dag.tasks
        assert "transform" in dag.tasks

    def test_dag_decorator_explicit_id(self):
        """@dag with explicit dag_id kwarg should use that instead of function name."""
        code = '''
from airflow.decorators import dag, task

@dag(dag_id="custom_dag_id", schedule="@hourly", tags=["prod", "etl"])
def my_func():
    @task
    def step1():
        pass
'''
        dags = parse_dag_file(code, "explicit_id.py")
        assert len(dags) == 1
        dag = dags[0]
        assert dag.dag_id == "custom_dag_id"
        assert dag.schedule == "@hourly"
        assert set(dag.tags) == {"prod", "etl"}
        assert "step1" in dag.tasks

    def test_dag_decorator_no_parens(self):
        """@dag without parentheses should still work."""
        code = '''
from airflow.decorators import dag, task

@dag
def simple_dag():
    @task
    def do_work():
        pass
'''
        dags = parse_dag_file(code, "no_parens.py")
        assert len(dags) == 1
        assert dags[0].dag_id == "simple_dag"
        assert "do_work" in dags[0].tasks

    def test_dag_decorator_with_operators(self):
        """@dag can contain both @task and traditional operators."""
        code = '''
from airflow.decorators import dag, task
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator

@dag(schedule="@daily")
def mixed_dag():
    bq_task = BigQueryInsertJobOperator(
        task_id="run_query",
        configuration={
            "query": {
                "query": "INSERT INTO project.analytics.output SELECT * FROM project.raw.input",
            }
        },
    )

    @task
    def notify():
        pass
'''
        dags = parse_dag_file(code, "mixed.py")
        assert len(dags) == 1
        dag = dags[0]
        assert "run_query" in dag.tasks
        assert "notify" in dag.tasks
        assert dag.tasks["run_query"].sql is not None
        assert "project.raw.input" in dag.tasks["run_query"].sql

    def test_lshift_dependencies(self):
        code = '''
from airflow import DAG
from airflow.operators.python import PythonOperator

with DAG("lshift_dag") as dag:
    a = PythonOperator(task_id="a", python_callable=lambda: None)
    b = PythonOperator(task_id="b", python_callable=lambda: None)
    b << a
'''
        dags = parse_dag_file(code, "lshift.py")
        dag = dags[0]
        assert ("a", "b") in dag.dependencies

    def test_syntax_error_returns_empty(self):
        code = "def broken(:\n  pass"
        dags = parse_dag_file(code, "broken.py")
        assert dags == []


# ---------------------------------------------------------------------------
# SQL table extraction
# ---------------------------------------------------------------------------

class TestSqlTableExtraction:
    def test_simple_select(self):
        sources, dest = _extract_tables_from_sql("SELECT * FROM my_schema.my_table")
        assert "my_schema.my_table" in sources
        assert dest is None

    def test_insert_into(self):
        sql = "INSERT INTO target.table SELECT * FROM source.table1 JOIN source.table2 ON t1.id = t2.id"
        sources, dest = _extract_tables_from_sql(sql)
        assert dest == "target.table"
        assert "source.table1" in sources
        assert "source.table2" in sources

    def test_create_table_as(self):
        sql = "CREATE TABLE analytics.summary AS SELECT * FROM raw.events"
        sources, dest = _extract_tables_from_sql(sql)
        assert dest == "analytics.summary"
        assert "raw.events" in sources

    def test_jinja_stripped(self):
        sql = "SELECT * FROM {{ params.schema }}.events WHERE date = '{{ ds }}'"
        stripped = _strip_jinja(sql)
        assert "{{ params.schema }}" not in stripped
        assert "__JINJA__" in stripped

    def test_three_part_table_ref(self):
        sources, dest = _extract_tables_from_sql(
            "SELECT * FROM project.dataset.table"
        )
        assert "project.dataset.table" in sources


# ---------------------------------------------------------------------------
# parse_dag_files (multi-file)
# ---------------------------------------------------------------------------

class TestParseDagFiles:
    def test_parse_multiple_files(self):
        files = {
            "dag1.py": '''
from airflow import DAG
with DAG("dag_one") as dag:
    pass
''',
            "dag2.py": '''
from airflow import DAG
with DAG("dag_two") as dag:
    pass
''',
            "readme.txt": "not a python file",
        }
        dags = parse_dag_files(files)
        assert len(dags) == 2
        dag_ids = {d.dag_id for d in dags}
        assert dag_ids == {"dag_one", "dag_two"}

    def test_skips_non_py_files(self):
        files = {"config.yaml": "key: value"}
        dags = parse_dag_files(files)
        assert dags == []
