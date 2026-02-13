"""Apache Airflow knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

AIRFLOW_ARTICLES = [
    KnowledgeArticle(
        id="airflow-dag-failure-debugging",
        title="Debugging Airflow DAG Failures",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["airflow", "dag", "failure", "debugging", "logs", "task-instance"],
        tools=["AIRFLOW"],
        summary="Step-by-step guide to debugging Airflow DAG and task failures: reading logs, common error patterns, and recovery.",
        content="""## Debugging Airflow DAG Failures

### Debugging Workflow
1. **Check the Airflow UI** → DAGs → Click failed DAG → Grid/Graph view
2. **Click the failed task instance** → View Log
3. **Read the full log** — error is usually near the bottom
4. Check `airflow tasks test <dag_id> <task_id> <execution_date>` to reproduce locally

### Common Failure Patterns

**Import Errors (DAG won't load)**
- DAG file has syntax error or missing import
- Check: Airflow UI → DAGs → Import Errors section
- Fix: Check Python syntax, verify packages are installed in Airflow environment

**Task Timeout**
- Task exceeded `execution_timeout`
- Fix: Increase timeout or optimize the task. Check for upstream delays.

**Dependency Failures**
- Upstream task failed → downstream skipped
- Fix: Fix the upstream task first. Use `trigger_rule='all_done'` if downstream should run regardless.

**Resource Errors**
- Worker ran out of memory or disk
- Fix: Increase worker resources, optimize task (process data in chunks)

**Connection Errors**
- Database/API connection failed
- Check: Admin → Connections → Test connection
- Fix: Verify credentials, check network/firewall rules

### Recovery
- **Clear and retry**: Click task → Clear → Confirm (re-runs from that point)
- **Mark success**: Skip a task and continue downstream
- **Backfill**: `airflow dags backfill <dag_id> -s <start_date> -e <end_date>`
""",
    ),
    KnowledgeArticle(
        id="airflow-task-timeout-issues",
        title="Fixing Airflow Task Timeouts",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["airflow", "timeout", "execution-timeout", "dagrun-timeout", "sensor"],
        tools=["AIRFLOW"],
        summary="How to fix Airflow task and sensor timeouts: tuning execution_timeout, sensor poke intervals, and reschedule mode.",
        content="""## Fixing Airflow Task Timeouts

### Task Execution Timeout
- Set per task: `execution_timeout=timedelta(hours=2)`
- Default: None (no timeout — dangerous for stuck tasks)
- Recommendation: Always set a timeout on production tasks

### Sensor Timeouts
Sensors are the #1 cause of Airflow worker pool exhaustion.

**Problem**: `poke` mode sensors occupy a worker slot while waiting.
**Fix**: Use `mode='reschedule'` — sensor releases the slot between checks.
```python
FileSensor(
    task_id='wait_for_file',
    filepath='/data/file.csv',
    mode='reschedule',       # Releases worker between checks
    poke_interval=300,       # Check every 5 minutes
    timeout=3600,            # Give up after 1 hour
)
```

### DAGRun Timeout
- `dagrun_timeout` on the DAG itself — kills the entire run if it takes too long
- Useful for SLA enforcement

### Pool Sizing
If tasks queue for a long time, increase the pool:
- Admin → Pools → Increase slots for the relevant pool
- Default pool has 128 slots

### Stuck Tasks
- Tasks showing "running" but actually dead (zombie tasks)
- Airflow detects these via heartbeat. Increase `scheduler_zombie_task_threshold` if needed.
- Manual fix: Mark task as failed in UI, then clear to retry
""",
    ),
    KnowledgeArticle(
        id="airflow-dag-design",
        title="Airflow DAG Design Best Practices",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["airflow", "dag", "design", "best-practices", "idempotent", "backfill"],
        tools=["AIRFLOW"],
        summary="Best practices for Airflow DAG design: idempotency, task granularity, dependencies, and backfill support.",
        content="""## Airflow DAG Design Best Practices

### Core Principles
1. **Idempotent tasks**: Running a task twice produces the same result. Use `INSERT OVERWRITE` or `MERGE`, not `INSERT`.
2. **Atomic tasks**: Each task is self-contained. If it fails, it can be safely retried.
3. **No side effects between tasks**: Don't rely on shared state. Use XCom sparingly.

### Task Granularity
- **Too granular**: 100 tasks for one table → slow scheduling, hard to debug
- **Too coarse**: 1 task for entire pipeline → can't retry partial failures
- **Right size**: 1 task per logical data transformation step

### DAG Configuration
```python
default_args = {
    'owner': 'data-team',
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(hours=2),
    'email_on_failure': True,
}

dag = DAG(
    'daily_pipeline',
    schedule_interval='@daily',
    start_date=datetime(2024, 1, 1),
    catchup=False,          # Set True only if you need backfill
    max_active_runs=1,      # Prevent parallel runs
    dagrun_timeout=timedelta(hours=6),
)
```

### Backfill Support
- Use `{{ ds }}` (execution date) template, not `datetime.now()`
- `WHERE date = '{{ ds }}'` ensures idempotent backfills
- Test with: `airflow dags backfill my_dag -s 2024-01-01 -e 2024-01-07`

### Dynamic DAGs
- Generate tasks programmatically from config (YAML/JSON)
- Keep DAG file parse time < 30s (don't hit APIs during DAG parsing)
""",
    ),
    KnowledgeArticle(
        id="airflow-scheduler-issues",
        title="Airflow Scheduler Troubleshooting",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["airflow", "scheduler", "stuck", "not-scheduling", "parsing", "performance"],
        tools=["AIRFLOW"],
        summary="How to fix Airflow scheduler issues: DAGs not appearing, slow parsing, scheduler lag, and database bottlenecks.",
        content="""## Airflow Scheduler Troubleshooting

### DAGs Not Appearing
- Check file is in `dags_folder` with correct permissions
- Check for import errors: Airflow UI → DAGs → Import Errors
- File must have a top-level DAG object or `@dag` decorator
- Scheduler scans files every `dag_dir_list_interval` seconds (default 300)

### Slow DAG Parsing
- **Symptom**: New DAGs take minutes to appear
- **Causes**: Heavy imports at top of file, API calls during parse, too many DAG files
- **Fixes**:
  - Move heavy imports inside task functions
  - Use `.airflowignore` to exclude non-DAG files
  - Reduce `dag_dir_list_interval` and `min_file_process_interval`

### Scheduler Lag
- **Symptom**: Tasks start minutes/hours after scheduled time
- **Causes**: Too many DAGs, database bottleneck, insufficient scheduler resources
- **Fixes**:
  - Increase `scheduler_heartbeat_sec` (faster scheduling loops)
  - Increase `parsing_processes` for multi-core parsing
  - Use multiple schedulers (Airflow 2.0+ supports HA)
  - Optimize metadata database (PostgreSQL recommended over SQLite)

### Database Performance
- Use PostgreSQL (not SQLite) for production
- Run `airflow db clean` periodically to remove old records
- Index frequently queried columns in task_instance table
""",
    ),
    KnowledgeArticle(
        id="airflow-api-auth-401",
        title="Fixing Airflow REST API 401 Unauthorized Errors",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["airflow", "api", "auth", "401", "unauthorized", "basic-auth", "rest-api", "docker", "docker-compose"],
        tools=["AIRFLOW"],
        summary="How to fix 401 Unauthorized errors when accessing the Airflow REST API. Covers enabling basic auth, Docker Compose config, and common auth pitfalls.",
        content="""## Fixing Airflow REST API 401 Unauthorized

### Symptom
API calls to Airflow endpoints like `/api/v1/dags` or `/api/v1/dagRuns` return
`401 UNAUTHORIZED`, even though the Airflow web UI login works fine with the
same username/password.

### Root Cause
Airflow 2.x separates **web UI auth** from **REST API auth**. By default, the
REST API auth backend may deny programmatic requests or only support
session-based auth (cookies), which doesn't work for tools like MCP servers.

### Fix: Enable Basic Auth for the REST API

**Docker Compose** — add this environment variable to ALL Airflow services
(webserver, scheduler, worker, triggerer):

```yaml
environment:
  AIRFLOW__API__AUTH_BACKENDS: 'airflow.api.auth.backend.basic_auth'
```

**airflow.cfg** — set in the `[api]` section:

```ini
[api]
auth_backends = airflow.api.auth.backend.basic_auth
```

Then restart all Airflow services.

### Verifying the Fix
Test with curl:
```bash
curl -u username:password http://localhost:8080/api/v1/dags
```
You should get a JSON response with your DAGs instead of a 401 error.

### Multiple Auth Backends
You can enable both session auth (for the UI) and basic auth (for API) together:
```yaml
AIRFLOW__API__AUTH_BACKENDS: 'airflow.api.auth.backend.session,airflow.api.auth.backend.basic_auth'
```

### Common Pitfalls
- **Setting it on webserver only**: The env var must be on ALL Airflow services, not just the webserver
- **Airflow 2.x default**: Some Docker images default to `deny_all` or `session` only
- **Typo in backend name**: It must be exactly `airflow.api.auth.backend.basic_auth`
- **User doesn't exist**: The username/password must match an existing Airflow user. Create one with:
  `airflow users create --username admin --password admin --role Admin --firstname Admin --lastname User --email admin@example.com`

### Debugging Steps (for the AI assistant)
When you encounter a 401 from Airflow:
1. Use GitHub tools to find the user's `docker-compose.yml` or `airflow.cfg`
2. Check if `AIRFLOW__API__AUTH_BACKENDS` or `auth_backends` is set
3. If missing, tell the user to add it with the exact setting above
4. If present, verify the value is correct and includes `basic_auth`
""",
    ),
]
