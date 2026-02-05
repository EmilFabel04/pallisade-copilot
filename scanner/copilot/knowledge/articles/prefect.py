"""Prefect knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

PREFECT_ARTICLES = [
    KnowledgeArticle(
        id="prefect-flow-failures",
        title="Debugging Prefect Flow Failures",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["prefect", "flow", "failure", "debugging", "task", "retry"],
        tools=["PREFECT"],
        summary="How to debug Prefect flow and task failures: reading logs, retry strategies, and common error patterns.",
        content="""## Debugging Prefect Flow Failures

### Debugging Workflow
1. Prefect UI → Flow Runs → Click failed run
2. Check the **Logs** tab for error details
3. Look at **Task Runs** to find which task failed
4. Check **Events** for infrastructure issues

### Common Failures

**Task Timeout**
- Task exceeded configured timeout
- Fix: Increase `timeout_seconds` on the task decorator or optimize the task

**Infrastructure Error**
- Worker/agent can't connect to Prefect API
- Check: `PREFECT_API_URL` and `PREFECT_API_KEY` environment variables
- Verify network connectivity from worker to Prefect Cloud/Server

**Dependency Not Found**
- Flow uses a package not installed in the execution environment
- Fix: Use Prefect deployments with proper `requirements.txt` or Docker image

### Retry Configuration
```python
@task(retries=3, retry_delay_seconds=60)
def my_task():
    ...

@flow(retries=1)
def my_flow():
    ...
```

### Recovery
- Re-run failed flow from UI
- Prefect doesn't support "resume from failure" — the entire flow re-runs
- Design tasks to be idempotent for safe retries
""",
    ),
    KnowledgeArticle(
        id="prefect-best-practices",
        title="Prefect Best Practices",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["prefect", "flow", "task", "deployment", "scheduling", "best-practices"],
        tools=["PREFECT"],
        summary="Best practices for Prefect: flow design, task granularity, deployments, and scheduling patterns.",
        content="""## Prefect Best Practices

### Flow Design
- Flows are the top-level orchestration unit
- Tasks are reusable, cacheable units of work within flows
- Keep flows focused: one flow per pipeline or data domain

### Task Best Practices
- Use `@task` for any work you want to track, retry, or cache
- Set `retries` and `retry_delay_seconds` on flaky tasks (API calls, external systems)
- Use `cache_key_fn` and `cache_expiration` for expensive computations
- Keep tasks idempotent for safe retries

### Deployments
- Use `flow.serve()` for simple scheduling
- Use `flow.deploy()` with work pools for production
- Docker-based work pools for consistent environments
- Include `requirements.txt` in deployment for dependency management

### Scheduling
```python
from prefect import flow
from prefect.schedules import CronSchedule

@flow
def daily_pipeline():
    ...

if __name__ == "__main__":
    daily_pipeline.serve(
        name="daily-pipeline",
        cron="0 6 * * *",  # 6 AM daily
    )
```
""",
    ),
]
