# Custom Source Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `Custom Source` integration type to Pallisade. A customer admin uses a 5-step wizard to register a web-hosted application (e.g. MyCiti for municipal water sensors) as a first-class pipeline source. Pallisade probes the source on a schedule, computes the standard monitoring metrics, and surfaces it in lineage and monitors identically to a warehouse table — never moving, loading, or persisting customer rows.

**Architecture:** A new `IntegrationLayer.SOURCE` and `IntegrationType.CUSTOM_SOURCE` taxonomy. `CustomSourceDriver` (composes over a new `HttpProbeAdapter`) registers in the existing driver loader. Probes run on their own schedule (separate from the monitor scheduler), persist `MetricBundle`s to a new `CustomSourceProbeRun` table, and the standard monitors (freshness / volume / null / schema-drift) read from that table when they fire. Storage rule (project-wide): derived metrics only — never persist raw rows.

**Tech Stack:** Python 3.11 (FastAPI / `scanner/`), Next.js 15 (App Router, TypeScript, React Server Components), PostgreSQL via Prisma, `requests` library for HTTP, `datasketch` (HyperLogLog) for column fingerprints, pytest for backend tests.

**Spec reference:** `docs/superpowers/specs/2026-04-30-custom-source-integration-design.md`

**Branch / worktree:** Run on a new feature branch `feat/custom-source-integration` off `main`.

---

## Phase 1: Taxonomy & Database

### Task 1: Add `IntegrationLayer.SOURCE` enum value

**Files:**
- Modify: `scanner/drivers/base.py` (lines 38-50)

- [ ] **Step 1: Add the new enum value at the top of the layer list**

```python
class IntegrationLayer(Enum):
    """Logical layer for UI grouping."""
    SOURCE = "SOURCE"
    WAREHOUSE = "WAREHOUSE"
    INGESTION = "INGESTION"
    TRANSFORMATION = "TRANSFORMATION"
    ORCHESTRATION = "ORCHESTRATION"
    REPORTING = "REPORTING"
    STORAGE = "STORAGE"
    VERSION_CONTROL = "VERSION_CONTROL"
    NOTIFICATIONS = "NOTIFICATIONS"
    TICKETING = "TICKETING"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    OTHER = "OTHER"
```

- [ ] **Step 2: Verify nothing imports `IntegrationLayer` and pattern-matches on members**

Run: `grep -rn "IntegrationLayer\." scanner/ --include="*.py" | grep -v "_test.py" | grep -v "tests/"`
Expected: scan results for visual confirmation — every reference is `IntegrationLayer.SOMETHING` value lookup, not exhaustive `match` statements. If any `match` statement on this enum exists with no `case _:` default, add a `case IntegrationLayer.SOURCE: ...` branch.

- [ ] **Step 3: Commit**

```bash
git add scanner/drivers/base.py
git commit -m "feat(drivers): add IntegrationLayer.SOURCE for operational data sources"
```

---

### Task 2: Add `CUSTOM_SOURCE` to Prisma `IntegrationType` enum

**Files:**
- Modify: `prisma/schema.prisma` (around line 1798)

- [ ] **Step 1: Add the enum value under a new SOURCE group, before `// CLOUD STORAGE`**

```prisma
  // ===========================================
  // SOURCE (Layer: SOURCE) — operational sources
  // ===========================================
  CUSTOM_SOURCE // Customer-configured web-hosted source (REST API)

  // ===========================================
  // CLOUD STORAGE
  // ===========================================
```

- [ ] **Step 2: Generate the Prisma client**

Run: `cd /Users/emilfabel/pallisade-copilot && npx prisma generate`
Expected: `✔ Generated Prisma Client (...) to ./node_modules/@prisma/client in <X>ms`

- [ ] **Step 3: Verify enum value is in the generated client**

Run: `grep "CUSTOM_SOURCE" node_modules/.prisma/client/index.d.ts | head -3`
Expected: at least one match showing `CUSTOM_SOURCE: "CUSTOM_SOURCE"` in the `IntegrationType` typing.

- [ ] **Step 4: Commit**

```bash
git add prisma/schema.prisma
git commit -m "feat(prisma): add CUSTOM_SOURCE IntegrationType enum value"
```

---

### Task 3: Add `CustomSourceProbeRun` Prisma model + migration

**Files:**
- Modify: `prisma/schema.prisma` (append model at end of file, before any existing trailing enums; place near `MonitorRun`)

- [ ] **Step 1: Add the model**

```prisma
model CustomSourceProbeRun {
  id            String   @id @default(cuid())
  integrationId String
  datasetId     String   // matches dataset.id from Integration.config

  // Outcome
  status        ProbeRunStatus
  errorCode     String?  // e.g. "auth_failed", "timeout", "response_too_large"
  errorMessage  String?

  // Derived metrics (raw rows are NEVER persisted)
  rowCount         Int?
  latestTimestamp  DateTime?
  columnSchema     Json?   // [{ name, data_type, is_nullable }, ...]
  nullCounts       Json?   // { columnName: int, ... }
  distinctCounts   Json?   // { columnName: int, ... }
  valueFingerprints Json?  // { columnName: base64-encoded HLL bytes, ... }
  minMaxNumeric    Json?   // { columnName: [min, max], ... }

  // Timing
  probedAt    DateTime  @default(now())
  durationMs  Int?

  // Relations
  integration Integration @relation(fields: [integrationId], references: [id], onDelete: Cascade)

  @@index([integrationId, datasetId, probedAt])
  @@index([probedAt])
}

enum ProbeRunStatus {
  SUCCESS
  FAILED
}
```

- [ ] **Step 2: Add the back-relation on `Integration`**

Find the `model Integration {` block in `prisma/schema.prisma` and add a relation field alongside the existing relations:

```prisma
  customSourceProbeRuns CustomSourceProbeRun[]
```

- [ ] **Step 3: Add `nextProbeAt` and `probeSchedule` fields on `Integration`**

In the same `Integration` block, add:

```prisma
  nextProbeAt   DateTime? // For CUSTOM_SOURCE only; null otherwise
  probeSchedule String?   // "hourly" | "every_6h" | "daily" | "weekly" | null
```

- [ ] **Step 4: Push schema to dev DB**

This repo uses `prisma db push` (not `prisma migrate`). There is no `prisma/migrations/` directory and the project explicitly adopted db-push (see commit `0abd61b` "adopt db push workflow"). Do NOT run `prisma migrate dev` or `prisma migrate deploy`.

Run: `npx prisma db push`
Expected: `🚀 Your database is now in sync with your Prisma schema.` Plus regenerated client output.

- [ ] **Step 5: Regenerate Prisma client (if `db push` did not already)**

Run: `npx prisma generate`
Expected: `✔ Generated Prisma Client (...)` — `db push` usually regenerates automatically; this is a belt-and-braces step.

- [ ] **Step 6: Verify the new model is in the generated client**

Run: `grep "CustomSourceProbeRun\|ProbeRunStatus" node_modules/.prisma/client/index.d.ts | head -5`
Expected: matches showing both `CustomSourceProbeRun` and `ProbeRunStatus` exported.

- [ ] **Step 7: Commit**

```bash
git add prisma/schema.prisma
git commit -m "feat(prisma): add CustomSourceProbeRun model + Integration probe schedule fields"
```

---

## Phase 2: HttpProbeAdapter

The HTTP probe adapter sits in `scanner/adapters/` alongside `DatabaseAdapter`. Deliberately not a `DatabaseAdapter` subclass — the SQL surface (quote_identifier, etc.) doesn't apply.

### Task 4: `MetricBundle` dataclass

**Files:**
- Create: `scanner/adapters/http_probe.py`
- Create: `scanner/tests/adapters/test_http_probe.py`

- [ ] **Step 1: Write failing test for `MetricBundle` shape**

```python
# scanner/tests/adapters/test_http_probe.py
from datetime import datetime, timezone
from scanner.adapters.http_probe import MetricBundle


def test_metric_bundle_holds_only_derived_metrics():
    """Sanity: MetricBundle never holds row data."""
    bundle = MetricBundle(
        probed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        row_count=42,
        latest_timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
        column_schema=[{"name": "id", "data_type": "int", "is_nullable": False}],
        null_counts={"id": 0},
        distinct_counts={"id": 42},
        value_fingerprints={"id": b"\x00" * 8},
        min_max_numeric={"id": (1.0, 42.0)},
    )
    assert bundle.row_count == 42
    assert "rows" not in bundle.__dict__
    assert "data" not in bundle.__dict__
```

- [ ] **Step 2: Run test, see ImportError**

Run: `cd /Users/emilfabel/pallisade-copilot && pytest scanner/tests/adapters/test_http_probe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.adapters.http_probe'`

- [ ] **Step 3: Write minimal implementation**

```python
# scanner/adapters/http_probe.py
"""
HttpProbeAdapter — probes HTTP-accessible data sources to compute
monitoring metrics. NEVER returns or persists raw rows.

Used by CustomSourceDriver to back the SOURCE-layer integration type.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class MetricBundle:
    """Derived monitoring metrics from a single probe run.

    Contains aggregates and column-level metadata only — never raw rows.
    """
    probed_at: datetime
    row_count: int
    latest_timestamp: Optional[datetime]
    column_schema: List[Dict[str, Any]]  # [{name, data_type, is_nullable}, ...]
    null_counts: Dict[str, int]
    distinct_counts: Dict[str, int]
    value_fingerprints: Dict[str, bytes]  # column -> HLL serialized
    min_max_numeric: Dict[str, Tuple[float, float]]
```

- [ ] **Step 4: Run test, see PASS**

Run: `pytest scanner/tests/adapters/test_http_probe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/adapters/http_probe.py scanner/tests/adapters/test_http_probe.py
git commit -m "feat(adapters): add MetricBundle dataclass for HTTP probe results"
```

---

### Task 5: `HttpProbeAdapter` skeleton + bearer-auth happy path

**Files:**
- Modify: `scanner/adapters/http_probe.py`
- Modify: `scanner/tests/adapters/test_http_probe.py`

- [ ] **Step 1: Add failing test for bearer-auth probe**

Append to `scanner/tests/adapters/test_http_probe.py`:

```python
import responses
from scanner.adapters.http_probe import HttpProbeAdapter


@responses.activate
def test_probe_with_bearer_auth_computes_metrics():
    """A successful bearer-auth probe returns a MetricBundle."""
    responses.add(
        responses.GET,
        "https://api.example.com/v1/readings",
        json=[
            {"id": 1, "sensor": "A", "reading_at": "2026-04-30T12:00:00Z", "value": 10.0},
            {"id": 2, "sensor": "B", "reading_at": "2026-04-30T13:00:00Z", "value": 20.0},
            {"id": 3, "sensor": None, "reading_at": "2026-04-30T14:00:00Z", "value": 30.0},
        ],
        status=200,
    )

    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "test-token"},
    )
    bundle = adapter.probe({
        "endpoint": "/readings",
        "timestamp_column": "reading_at",
    })

    assert bundle.row_count == 3
    assert bundle.null_counts["sensor"] == 1
    assert bundle.null_counts["id"] == 0
    assert bundle.column_schema  # non-empty
    assert bundle.latest_timestamp is not None
    # Authorization header was sent
    sent_auth = responses.calls[0].request.headers.get("Authorization")
    assert sent_auth == "Bearer test-token"
```

- [ ] **Step 2: Run test, see ImportError on `HttpProbeAdapter`**

Run: `pytest scanner/tests/adapters/test_http_probe.py::test_probe_with_bearer_auth_computes_metrics -v`
Expected: FAIL — `ImportError: cannot import name 'HttpProbeAdapter'`

- [ ] **Step 3: Implement minimal `HttpProbeAdapter`**

Append to `scanner/adapters/http_probe.py`:

```python
import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 30
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MiB
_MAX_ROWS = 50_000


class ProbeError(RuntimeError):
    """Probe failed. `code` is a stable string for the alert layer."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class HttpProbeAdapter:
    """Probes an HTTP endpoint and returns a MetricBundle. Never returns rows."""

    def __init__(self, base_url: str, auth: Dict[str, Any]):
        self.base_url = base_url.rstrip("/")
        self.auth = auth or {}

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        kind = self.auth.get("kind")
        secret = self.auth.get("secret", "")
        if kind == "bearer":
            session.headers["Authorization"] = f"Bearer {secret}"
        elif kind == "api_key":
            header_name = self.auth.get("header_name") or "X-API-Key"
            session.headers[header_name] = secret
        elif kind == "basic":
            username = self.auth.get("username", "")
            session.auth = (username, secret)
        else:
            raise ProbeError("invalid_auth", f"unsupported auth kind: {kind!r}")
        return session

    def probe(self, dataset_config: Dict[str, Any]) -> MetricBundle:
        endpoint = dataset_config["endpoint"]
        timestamp_column = dataset_config.get("timestamp_column")

        url = f"{self.base_url}{endpoint}"
        session = self._build_session()

        try:
            resp = session.get(url, timeout=_DEFAULT_TIMEOUT_SEC, stream=True)
        except requests.Timeout:
            raise ProbeError("timeout", f"request timed out after {_DEFAULT_TIMEOUT_SEC}s")
        except requests.RequestException as exc:
            raise ProbeError("network_error", str(exc))

        if resp.status_code == 401 or resp.status_code == 403:
            raise ProbeError("auth_failed", f"HTTP {resp.status_code}")
        if not (200 <= resp.status_code < 300):
            raise ProbeError("http_error", f"HTTP {resp.status_code}")

        # Read with size cap
        content = resp.raw.read(_MAX_RESPONSE_BYTES + 1, decode_content=True)
        if len(content) > _MAX_RESPONSE_BYTES:
            raise ProbeError("response_too_large", f"response exceeded {_MAX_RESPONSE_BYTES} bytes")

        import json as _json
        try:
            payload = _json.loads(content)
        except _json.JSONDecodeError as exc:
            raise ProbeError("malformed_json", str(exc))

        # JSON root navigation
        json_root = dataset_config.get("json_root")
        if json_root:
            for part in json_root.split("."):
                if not isinstance(payload, dict) or part not in payload:
                    raise ProbeError("json_root_not_found", f"path {json_root!r} missing")
                payload = payload[part]

        if not isinstance(payload, list):
            raise ProbeError("not_array", "expected JSON array of objects")

        return self._compute_metrics(payload, timestamp_column)

    def _compute_metrics(
        self, rows: List[Dict[str, Any]], timestamp_column: Optional[str],
    ) -> MetricBundle:
        if len(rows) > _MAX_ROWS:
            raise ProbeError("too_many_rows", f"more than {_MAX_ROWS} rows")

        row_count = len(rows)

        # Determine schema from first non-empty row
        column_schema: List[Dict[str, Any]] = []
        if rows:
            sample = rows[0]
            for col_name, value in sample.items():
                column_schema.append({
                    "name": col_name,
                    "data_type": _infer_type(value),
                    "is_nullable": True,  # JSON has no nullability concept
                })

        null_counts: Dict[str, int] = {col["name"]: 0 for col in column_schema}
        latest_ts: Optional[datetime] = None

        for row in rows:
            for col in column_schema:
                name = col["name"]
                if row.get(name) is None:
                    null_counts[name] += 1
            if timestamp_column:
                ts_val = row.get(timestamp_column)
                if isinstance(ts_val, str):
                    parsed = _parse_iso8601(ts_val)
                    if parsed and (latest_ts is None or parsed > latest_ts):
                        latest_ts = parsed

        return MetricBundle(
            probed_at=datetime.now(timezone.utc),
            row_count=row_count,
            latest_timestamp=latest_ts,
            column_schema=column_schema,
            null_counts=null_counts,
            distinct_counts={},        # filled in Task 9
            value_fingerprints={},     # filled in Task 9
            min_max_numeric={},        # filled in Task 9
        )


def _infer_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _parse_iso8601(value: str) -> Optional[datetime]:
    try:
        # Handle trailing Z
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None
```

- [ ] **Step 4: Run test, see PASS**

Run: `pytest scanner/tests/adapters/test_http_probe.py -v`
Expected: PASS for both tests.

- [ ] **Step 5: Commit**

```bash
git add scanner/adapters/http_probe.py scanner/tests/adapters/test_http_probe.py
git commit -m "feat(adapters): HttpProbeAdapter skeleton with bearer auth"
```

---

### Task 6: API key + basic auth + auth-failure handling

**Files:**
- Modify: `scanner/tests/adapters/test_http_probe.py` (add tests)

- [ ] **Step 1: Add failing tests for the other auth shapes and 401**

Append to `scanner/tests/adapters/test_http_probe.py`:

```python
@responses.activate
def test_probe_with_api_key_uses_default_header():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        json=[{"id": 1}], status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "api_key", "secret": "abc123"},
    )
    adapter.probe({"endpoint": "/readings"})
    assert responses.calls[0].request.headers.get("X-API-Key") == "abc123"


@responses.activate
def test_probe_with_api_key_custom_header_name():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        json=[{"id": 1}], status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "api_key", "secret": "abc", "header_name": "X-Auth"},
    )
    adapter.probe({"endpoint": "/readings"})
    assert responses.calls[0].request.headers.get("X-Auth") == "abc"


@responses.activate
def test_probe_with_basic_auth_sends_authorization_header():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        json=[{"id": 1}], status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "basic", "username": "user", "secret": "pw"},
    )
    adapter.probe({"endpoint": "/readings"})
    auth_header = responses.calls[0].request.headers.get("Authorization", "")
    assert auth_header.startswith("Basic ")


@responses.activate
def test_probe_raises_auth_failed_on_401():
    from scanner.adapters.http_probe import ProbeError
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        status=401,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "bad"},
    )
    import pytest
    with pytest.raises(ProbeError) as exc:
        adapter.probe({"endpoint": "/readings"})
    assert exc.value.code == "auth_failed"
```

- [ ] **Step 2: Run new tests**

Run: `pytest scanner/tests/adapters/test_http_probe.py -v`
Expected: PASS for all four new tests (the implementation in Task 5 already supports them).

- [ ] **Step 3: Commit**

```bash
git add scanner/tests/adapters/test_http_probe.py
git commit -m "test(adapters): cover api_key, basic, and 401-auth-failure paths"
```

---

### Task 7: Size cap, row cap, timeout, malformed-JSON tests

**Files:**
- Modify: `scanner/tests/adapters/test_http_probe.py`

- [ ] **Step 1: Add tests for the cap and error paths**

Append to `scanner/tests/adapters/test_http_probe.py`:

```python
@responses.activate
def test_probe_raises_on_response_too_large():
    from scanner.adapters.http_probe import ProbeError
    big_body = "x" * (11 * 1024 * 1024)  # 11 MiB of garbage
    responses.add(
        responses.GET, "https://api.example.com/v1/big",
        body=big_body, status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "t"},
    )
    import pytest
    with pytest.raises(ProbeError) as exc:
        adapter.probe({"endpoint": "/big"})
    assert exc.value.code == "response_too_large"


@responses.activate
def test_probe_raises_too_many_rows():
    from scanner.adapters.http_probe import ProbeError
    huge = [{"id": i} for i in range(50_001)]
    responses.add(
        responses.GET, "https://api.example.com/v1/many",
        json=huge, status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "t"},
    )
    import pytest
    with pytest.raises(ProbeError) as exc:
        adapter.probe({"endpoint": "/many"})
    assert exc.value.code == "too_many_rows"


@responses.activate
def test_probe_raises_malformed_json():
    from scanner.adapters.http_probe import ProbeError
    responses.add(
        responses.GET, "https://api.example.com/v1/bad",
        body="not json {{", status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "t"},
    )
    import pytest
    with pytest.raises(ProbeError) as exc:
        adapter.probe({"endpoint": "/bad"})
    assert exc.value.code == "malformed_json"


@responses.activate
def test_probe_raises_on_non_array_payload():
    from scanner.adapters.http_probe import ProbeError
    responses.add(
        responses.GET, "https://api.example.com/v1/object",
        json={"hello": "world"}, status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "t"},
    )
    import pytest
    with pytest.raises(ProbeError) as exc:
        adapter.probe({"endpoint": "/object"})
    assert exc.value.code == "not_array"


def test_probe_raises_timeout(monkeypatch):
    from scanner.adapters.http_probe import ProbeError
    import requests as _requests

    def _raise_timeout(*a, **kw):
        raise _requests.Timeout()

    monkeypatch.setattr(_requests.Session, "get", _raise_timeout)
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "t"},
    )
    import pytest
    with pytest.raises(ProbeError) as exc:
        adapter.probe({"endpoint": "/x"})
    assert exc.value.code == "timeout"
```

- [ ] **Step 2: Run tests**

Run: `pytest scanner/tests/adapters/test_http_probe.py -v`
Expected: all tests PASS (the Task 5 implementation handles every error path; this task is purely test coverage).

- [ ] **Step 3: Commit**

```bash
git add scanner/tests/adapters/test_http_probe.py
git commit -m "test(adapters): cover size/row caps, timeout, malformed JSON, non-array payload"
```

---

### Task 8: JSON root + cursor-param navigation tests

**Files:**
- Modify: `scanner/tests/adapters/test_http_probe.py`

- [ ] **Step 1: Add tests**

Append:

```python
@responses.activate
def test_probe_navigates_json_root():
    responses.add(
        responses.GET, "https://api.example.com/v1/wrapped",
        json={"data": {"items": [{"id": 1}, {"id": 2}]}},
        status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "t"},
    )
    bundle = adapter.probe({"endpoint": "/wrapped", "json_root": "data.items"})
    assert bundle.row_count == 2


@responses.activate
def test_probe_raises_on_missing_json_root():
    from scanner.adapters.http_probe import ProbeError
    responses.add(
        responses.GET, "https://api.example.com/v1/wrapped",
        json={"data": {}}, status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "t"},
    )
    import pytest
    with pytest.raises(ProbeError) as exc:
        adapter.probe({"endpoint": "/wrapped", "json_root": "data.items"})
    assert exc.value.code == "json_root_not_found"


@responses.activate
def test_probe_passes_cursor_param_when_configured():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        json=[], status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "t"},
    )
    adapter.probe({
        "endpoint": "/readings",
        "cursor_param": "since",
        "cursor_value": "2026-04-30T00:00:00Z",
    })
    assert "since=2026-04-30T00%3A00%3A00Z" in responses.calls[0].request.url
```

- [ ] **Step 2: Run tests, see the cursor-param test fail**

Run: `pytest scanner/tests/adapters/test_http_probe.py -v`
Expected: the JSON-root tests PASS (handled in Task 5). The cursor-param test FAILS — implementation does not yet pass query params.

- [ ] **Step 3: Add cursor-param support in `HttpProbeAdapter.probe`**

Modify `scanner/adapters/http_probe.py` — replace the `resp = session.get(url, ...)` line and the lines immediately around it with:

```python
        params: Dict[str, Any] = {}
        cursor_param = dataset_config.get("cursor_param")
        cursor_value = dataset_config.get("cursor_value")
        if cursor_param and cursor_value is not None:
            params[cursor_param] = cursor_value

        try:
            resp = session.get(url, params=params or None, timeout=_DEFAULT_TIMEOUT_SEC, stream=True)
        except requests.Timeout:
            raise ProbeError("timeout", f"request timed out after {_DEFAULT_TIMEOUT_SEC}s")
        except requests.RequestException as exc:
            raise ProbeError("network_error", str(exc))
```

- [ ] **Step 4: Run tests**

Run: `pytest scanner/tests/adapters/test_http_probe.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/adapters/http_probe.py scanner/tests/adapters/test_http_probe.py
git commit -m "feat(adapters): add cursor-param query support to HttpProbeAdapter"
```

---

### Task 9: HLL fingerprints, distinct counts, min/max numeric

**Files:**
- Modify: `scanner/adapters/http_probe.py`
- Modify: `scanner/requirements.txt` (add `datasketch`)
- Modify: `scanner/tests/adapters/test_http_probe.py`

- [ ] **Step 1: Add `datasketch` to requirements**

Open `scanner/requirements.txt` and append `datasketch>=1.6.0` on its own line.

- [ ] **Step 2: Install**

Run: `cd /Users/emilfabel/pallisade-copilot && scanner/venv/bin/pip install 'datasketch>=1.6.0'`
Expected: success.

- [ ] **Step 3: Add failing test for distinct counts and fingerprints**

Append to `scanner/tests/adapters/test_http_probe.py`:

```python
@responses.activate
def test_probe_computes_distinct_counts_and_min_max():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        json=[
            {"id": 1, "sensor": "A", "value": 10.0},
            {"id": 2, "sensor": "A", "value": 20.0},
            {"id": 3, "sensor": "B", "value": 30.0},
        ],
        status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "t"},
    )
    bundle = adapter.probe({"endpoint": "/readings"})

    # Distinct counts (HLL is approximate but should be exact for small N)
    assert bundle.distinct_counts["sensor"] == 2
    assert bundle.distinct_counts["id"] == 3
    # Min/max for numeric columns
    assert bundle.min_max_numeric["value"] == (10.0, 30.0)
    assert bundle.min_max_numeric["id"] == (1.0, 3.0)
    # No min/max for string columns
    assert "sensor" not in bundle.min_max_numeric
    # Fingerprints exist for every column
    assert "sensor" in bundle.value_fingerprints
    assert "id" in bundle.value_fingerprints
    assert "value" in bundle.value_fingerprints
    # Fingerprints are bytes (HLL serialized)
    assert isinstance(bundle.value_fingerprints["sensor"], bytes)
```

- [ ] **Step 4: Run, see FAIL on `distinct_counts["sensor"]`**

Run: `pytest scanner/tests/adapters/test_http_probe.py::test_probe_computes_distinct_counts_and_min_max -v`
Expected: FAIL — `distinct_counts` is empty.

- [ ] **Step 5: Implement HLL + min/max in `_compute_metrics`**

In `scanner/adapters/http_probe.py`, replace `_compute_metrics` with:

```python
    def _compute_metrics(
        self, rows: List[Dict[str, Any]], timestamp_column: Optional[str],
    ) -> MetricBundle:
        if len(rows) > _MAX_ROWS:
            raise ProbeError("too_many_rows", f"more than {_MAX_ROWS} rows")

        from datasketch import HyperLogLog

        row_count = len(rows)

        column_schema: List[Dict[str, Any]] = []
        if rows:
            sample = rows[0]
            for col_name, value in sample.items():
                column_schema.append({
                    "name": col_name,
                    "data_type": _infer_type(value),
                    "is_nullable": True,
                })

        null_counts: Dict[str, int] = {col["name"]: 0 for col in column_schema}
        hlls: Dict[str, Any] = {col["name"]: HyperLogLog(p=12) for col in column_schema}
        numeric_min_max: Dict[str, Tuple[float, float]] = {}
        latest_ts: Optional[datetime] = None

        for row in rows:
            for col in column_schema:
                name = col["name"]
                value = row.get(name)
                if value is None:
                    null_counts[name] += 1
                    continue
                hlls[name].update(str(value).encode("utf-8"))
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    fv = float(value)
                    cur = numeric_min_max.get(name)
                    if cur is None:
                        numeric_min_max[name] = (fv, fv)
                    else:
                        numeric_min_max[name] = (min(cur[0], fv), max(cur[1], fv))
            if timestamp_column:
                ts_val = row.get(timestamp_column)
                if isinstance(ts_val, str):
                    parsed = _parse_iso8601(ts_val)
                    if parsed and (latest_ts is None or parsed > latest_ts):
                        latest_ts = parsed

        distinct_counts = {name: int(hll.count()) for name, hll in hlls.items()}
        fingerprints: Dict[str, bytes] = {}
        for name, hll in hlls.items():
            buf = bytearray()
            hll.serialize(buf)
            fingerprints[name] = bytes(buf)

        return MetricBundle(
            probed_at=datetime.now(timezone.utc),
            row_count=row_count,
            latest_timestamp=latest_ts,
            column_schema=column_schema,
            null_counts=null_counts,
            distinct_counts=distinct_counts,
            value_fingerprints=fingerprints,
            min_max_numeric=numeric_min_max,
        )
```

- [ ] **Step 6: Run tests**

Run: `pytest scanner/tests/adapters/test_http_probe.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add scanner/adapters/http_probe.py scanner/requirements.txt scanner/tests/adapters/test_http_probe.py
git commit -m "feat(adapters): HLL fingerprints, distinct counts, min/max numeric"
```

---

## Phase 3: CustomSourceDriver

### Task 10: Create `source/` driver package and `CustomSourceDriver` skeleton

**Files:**
- Create: `scanner/drivers/source/__init__.py` (empty)
- Create: `scanner/drivers/source/custom_source_driver.py`
- Create: `scanner/tests/drivers/test_custom_source_driver.py`

- [ ] **Step 1: Create the empty package init**

```python
# scanner/drivers/source/__init__.py
```

(File is just empty.)

- [ ] **Step 2: Write failing test for identity + validate_config**

```python
# scanner/tests/drivers/test_custom_source_driver.py
from scanner.drivers.source.custom_source_driver import CustomSourceDriver
from scanner.drivers.base import GraphDomain, IntegrationLayer


def test_driver_identity():
    d = CustomSourceDriver()
    assert d.id() == "custom_source"
    assert d.integration_type() == "CUSTOM_SOURCE"
    assert d.layer() == IntegrationLayer.SOURCE
    assert d.graph_domain() == GraphDomain.DATA_PLANE


def test_validate_config_requires_base_url_and_auth_and_datasets():
    d = CustomSourceDriver()
    res = d.validate_config({})
    assert not res.valid
    assert any("base_url" in e for e in res.errors)
    assert any("auth.kind" in e for e in res.errors)
    assert any("datasets" in e for e in res.errors)


def test_validate_config_requires_https():
    d = CustomSourceDriver()
    res = d.validate_config({
        "name": "x",
        "base_url": "http://insecure.example.com",
        "auth": {"kind": "bearer", "secret_ref": "s"},
        "datasets": [{"id": "d", "endpoint": "/r", "timestamp_column": "t"}],
    })
    assert not res.valid
    assert any("https" in e.lower() for e in res.errors)


def test_validate_config_passes_minimal_valid_input():
    d = CustomSourceDriver()
    res = d.validate_config({
        "name": "MyCiti",
        "base_url": "https://portal.example.com/api/v1",
        "auth": {"kind": "bearer", "secret_ref": "secret-id"},
        "datasets": [{
            "id": "water",
            "endpoint": "/readings",
            "timestamp_column": "reading_at",
        }],
    })
    assert res.valid
```

- [ ] **Step 3: Run, see ImportError**

Run: `pytest scanner/tests/drivers/test_custom_source_driver.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 4: Implement skeleton**

```python
# scanner/drivers/source/custom_source_driver.py
"""
Custom Source IntegrationDriver — registers an arbitrary HTTP-accessible
data source as a SOURCE-layer integration. Composes over HttpProbeAdapter.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from ..base import (
    AssetSummary,
    ConfigValidation,
    ConnectionResult,
    DriverCapabilities,
    GraphDomain,
    IntegrationDriver,
    IntegrationLayer,
)

logger = logging.getLogger(__name__)


class CustomSourceDriver(IntegrationDriver):
    def id(self) -> str:
        return "custom_source"

    def integration_type(self) -> str:
        return "CUSTOM_SOURCE"

    def layer(self) -> IntegrationLayer:
        return IntegrationLayer.SOURCE

    def graph_domain(self) -> GraphDomain:
        return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors: List[str] = []

        if not config.get("base_url"):
            errors.append("base_url is required")
        else:
            if not config["base_url"].lower().startswith("https://"):
                errors.append("base_url must use https:// scheme (TLS required)")

        auth = config.get("auth") or {}
        if not auth.get("kind"):
            errors.append("auth.kind is required (bearer | api_key | basic)")
        elif auth["kind"] not in ("bearer", "api_key", "basic"):
            errors.append(f"auth.kind must be one of bearer | api_key | basic, got {auth['kind']!r}")

        datasets = config.get("datasets") or []
        if not datasets:
            errors.append("at least one dataset is required")
        for i, ds in enumerate(datasets):
            if not ds.get("id"):
                errors.append(f"datasets[{i}].id is required")
            if not ds.get("endpoint"):
                errors.append(f"datasets[{i}].endpoint is required")
            if not ds.get("timestamp_column"):
                errors.append(f"datasets[{i}].timestamp_column is required")

        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        # Implemented in Task 11
        return ConnectionResult(ok=False, message="not yet implemented")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_query=False,
            can_extract_metadata=True,
            can_extract_lineage=True,
            can_health_check=True,
            supported_monitors=["freshness", "volume", "null_check", "schema_change"],
        )

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "volume", "null_check", "schema_change"]
```

- [ ] **Step 5: Run tests, see PASS**

Run: `pytest scanner/tests/drivers/test_custom_source_driver.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scanner/drivers/source/ scanner/tests/drivers/test_custom_source_driver.py
git commit -m "feat(drivers): CustomSourceDriver skeleton with validate_config"
```

---

### Task 11: `test_connection` and `extract_metadata`

**Files:**
- Modify: `scanner/drivers/source/custom_source_driver.py`
- Modify: `scanner/tests/drivers/test_custom_source_driver.py`

- [ ] **Step 1: Write failing tests**

Append to test file:

```python
import responses
from scanner.drivers.source.custom_source_driver import CustomSourceDriver


@responses.activate
def test_test_connection_ok_when_first_dataset_responds():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        json=[{"id": 1}], status=200,
    )
    d = CustomSourceDriver()
    config = {
        "base_url": "https://api.example.com/v1",
        "auth": {"kind": "bearer", "secret": "t"},
        "datasets": [{"id": "x", "endpoint": "/readings", "timestamp_column": "id"}],
    }
    result = d.test_connection(config)
    assert result.ok is True


@responses.activate
def test_test_connection_fails_on_401():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        status=401,
    )
    d = CustomSourceDriver()
    config = {
        "base_url": "https://api.example.com/v1",
        "auth": {"kind": "bearer", "secret": "bad"},
        "datasets": [{"id": "x", "endpoint": "/readings", "timestamp_column": "id"}],
    }
    result = d.test_connection(config)
    assert result.ok is False
    assert "auth" in result.message.lower() or "401" in result.message


def test_extract_metadata_returns_one_summary_per_dataset():
    d = CustomSourceDriver()
    config = {
        "base_url": "https://api.example.com/v1",
        "auth": {"kind": "bearer", "secret": "t"},
        "datasets": [
            {"id": "water", "endpoint": "/water", "timestamp_column": "t"},
            {"id": "air", "endpoint": "/air", "timestamp_column": "t"},
        ],
    }
    summaries = d.extract_metadata(config)
    assert len(summaries) == 2
    assert any(s.asset_type == "dataset" and "water" in s.sample_names for s in summaries)
```

- [ ] **Step 2: Run, see FAIL**

Run: `pytest scanner/tests/drivers/test_custom_source_driver.py -v`
Expected: FAIL on `test_connection` (returns dummy) and `extract_metadata` (returns []).

- [ ] **Step 3: Implement both methods**

In `scanner/drivers/source/custom_source_driver.py`, replace `test_connection` and add `extract_metadata`:

```python
    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        from scanner.adapters.http_probe import HttpProbeAdapter, ProbeError
        from datetime import datetime
        import time

        datasets = config.get("datasets") or []
        if not datasets:
            return ConnectionResult(ok=False, message="no datasets configured")

        adapter = HttpProbeAdapter(
            base_url=config["base_url"],
            auth=config["auth"],
        )

        first = datasets[0]
        start = time.time()
        try:
            adapter.probe({
                "endpoint": first["endpoint"],
                "timestamp_column": first.get("timestamp_column"),
                "json_root": first.get("json_root"),
            })
            latency = int((time.time() - start) * 1000)
            return ConnectionResult(
                ok=True,
                message=f"Connected; first dataset {first['id']!r} returned data",
                connected_at=datetime.utcnow(),
                latency_ms=latency,
            )
        except ProbeError as exc:
            latency = int((time.time() - start) * 1000)
            return ConnectionResult(
                ok=False,
                message=f"connection failed ({exc.code}): {exc.message}",
                latency_ms=latency,
            )

    def extract_metadata(self, config: Dict[str, Any]) -> List[AssetSummary]:
        datasets = config.get("datasets") or []
        return [
            AssetSummary(
                asset_type="dataset",
                count=1,
                sample_names=[ds.get("id", "<unnamed>")],
            )
            for ds in datasets
        ]
```

- [ ] **Step 4: Run tests**

Run: `pytest scanner/tests/drivers/test_custom_source_driver.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/drivers/source/custom_source_driver.py scanner/tests/drivers/test_custom_source_driver.py
git commit -m "feat(drivers): CustomSourceDriver test_connection and extract_metadata"
```

---

### Task 12: `_extract_lineage_impl` — emit nodes and `lands_in` edges

**Files:**
- Modify: `scanner/drivers/source/custom_source_driver.py`
- Modify: `scanner/tests/drivers/test_custom_source_driver.py`

- [ ] **Step 1: Write failing tests**

Append to test file:

```python
def test_extract_lineage_emits_one_node_per_dataset_no_edges_without_lands_in():
    d = CustomSourceDriver()
    config = {
        "platform_label": "MyCiti",
        "base_url": "https://api.example.com/v1",
        "auth": {"kind": "bearer", "secret_ref": "s"},
        "datasets": [
            {"id": "water", "endpoint": "/w", "timestamp_column": "t"},
        ],
    }
    nodes, edges = d.extract_lineage(config)
    assert len(nodes) == 1
    assert nodes[0].name == "water"
    assert edges == []


def test_extract_lineage_emits_edge_when_lands_in_set():
    d = CustomSourceDriver()
    config = {
        "platform_label": "MyCiti",
        "base_url": "https://api.example.com/v1",
        "auth": {"kind": "bearer", "secret_ref": "s"},
        "datasets": [{
            "id": "water",
            "endpoint": "/w",
            "timestamp_column": "t",
            "lands_in": "snowflake.raw.water_meters",
        }],
    }
    nodes, edges = d.extract_lineage(config)
    assert len(nodes) == 1
    assert len(edges) == 1
    e = edges[0]
    assert e.target_fqn == "snowflake.raw.water_meters" or "water_meters" in str(e)
```

- [ ] **Step 2: Run, see FAIL**

Run: `pytest scanner/tests/drivers/test_custom_source_driver.py -v`
Expected: FAIL — base class returns `([], [])`.

- [ ] **Step 3: Implement `_extract_lineage_impl`**

In `scanner/drivers/source/custom_source_driver.py`, add the import and method:

```python
# Add at top with other imports:
from scanner.lineage.engine.graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageNode,
    NodeType,
)
from scanner.lineage.engine.ids import generate_asset_id


# Add method to CustomSourceDriver class:
    def _extract_lineage_impl(
        self, config: Dict[str, Any]
    ) -> Tuple[List[Any], List[Any]]:
        platform_label = (config.get("platform_label") or "custom_source").lower()
        datasets = config.get("datasets") or []

        nodes: List[LineageNode] = []
        edges: List[LineageEdge] = []

        for ds in datasets:
            ds_id = ds.get("id", "")
            asset_id = generate_asset_id(
                "source", platform_label, "default", "", ds_id,
            )
            node = LineageNode(
                id=asset_id,
                name=ds_id,
                fqn=f"{platform_label}.{ds_id}",
                node_type=NodeType.SOURCE,
                kind=AssetKind.DATASET,
                platform=platform_label,
            )
            nodes.append(node)

            lands_in = ds.get("lands_in")
            if lands_in:
                edge = LineageEdge(
                    source_id=asset_id,
                    target_fqn=lands_in,
                    edge_type=EdgeType.WRITES,
                    evidence=[Evidence(
                        kind="user_config",
                        confidence=0.9,
                        details={"lands_in": lands_in},
                    )],
                )
                edges.append(edge)

        return nodes, edges
```

- [ ] **Step 4: Run tests, see PASS or fail with attribute mismatch**

Run: `pytest scanner/tests/drivers/test_custom_source_driver.py -v`
Expected: PASS. If FAIL on `LineageEdge` constructor signature — open `scanner/lineage/engine/graph.py`, find the `LineageEdge` dataclass, and adjust the field names in step 3 (e.g. `source` instead of `source_id`, `target` instead of `target_fqn`) to match. Re-run.

- [ ] **Step 5: Commit**

```bash
git add scanner/drivers/source/custom_source_driver.py scanner/tests/drivers/test_custom_source_driver.py
git commit -m "feat(drivers): CustomSourceDriver lineage with lands_in edge creation"
```

---

### Task 13: Register `CustomSourceDriver` in the driver loader

**Files:**
- Modify: `scanner/drivers/loader.py` and/or `scanner/drivers/registry.py`
- Modify: `scanner/tests/drivers/test_custom_source_driver.py`

- [ ] **Step 1: Inspect how existing drivers are registered**

Run: `grep -n "SnowflakeDriver\|CustomWebhook" scanner/drivers/loader.py scanner/drivers/registry.py`
Expected: shows the registration pattern. Locate the lines that register `SnowflakeDriver` (or `BigQueryDriver`).

- [ ] **Step 2: Add registration for `CustomSourceDriver`**

In `scanner/drivers/loader.py` (or `registry.py`, wherever `SnowflakeDriver` is referenced), add the same kind of registration entry. Concretely, add an import and a registration line — for example, if the file has a list called `_ALL_DRIVERS` or a dict registry:

```python
from scanner.drivers.source.custom_source_driver import CustomSourceDriver

# ...add to whatever registration mechanism exists:
# Either appended to a list:
#   _ALL_DRIVERS.append(CustomSourceDriver)
# Or registered in a dict by integration_type:
#   _REGISTRY["CUSTOM_SOURCE"] = CustomSourceDriver
```

If the file has a `_load_drivers()` function (mirroring `AdapterFactory._load_adapters()`), wrap the import in a `try/except ImportError` block and warn-log on failure to follow the existing pattern.

- [ ] **Step 3: Add a registration test**

Append to test file:

```python
def test_driver_registered_in_loader():
    """CustomSourceDriver is discoverable via the integration_type registry."""
    from scanner.drivers.loader import get_driver_for_integration_type
    driver = get_driver_for_integration_type("CUSTOM_SOURCE")
    assert driver is not None
    assert isinstance(driver, CustomSourceDriver)
```

If the loader does not expose `get_driver_for_integration_type`, replace the import with the actual lookup function present in `loader.py`.

- [ ] **Step 4: Run test**

Run: `pytest scanner/tests/drivers/test_custom_source_driver.py::test_driver_registered_in_loader -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/drivers/loader.py scanner/drivers/registry.py scanner/tests/drivers/test_custom_source_driver.py
git commit -m "feat(drivers): register CustomSourceDriver in the driver loader"
```

---

## Phase 4: Probe persistence

### Task 14: `save_probe_run` helper — persist `MetricBundle` to `CustomSourceProbeRun`

**Files:**
- Create: `scanner/drivers/source/probe_persistence.py`
- Create: `scanner/tests/drivers/test_probe_persistence.py`

- [ ] **Step 1: Write failing test (uses an in-memory psycopg2 stub or a test DB fixture)**

```python
# scanner/tests/drivers/test_probe_persistence.py
"""Test for probe persistence. Requires DATABASE_URL set to a test DB."""
import os
import pytest
from datetime import datetime, timezone

from scanner.adapters.http_probe import MetricBundle
from scanner.drivers.source.probe_persistence import save_probe_run, save_probe_failure


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping DB-dependent tests",
)


@pytest.fixture
def integration_id():
    """Create a temporary CUSTOM_SOURCE integration row, yield its id, clean up."""
    import psycopg2
    from urllib.parse import urlparse
    from scanner.scheduler.service import _get_connection
    conn = _get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO "Integration" (id, type, name, "organizationId", config, status)
            VALUES (gen_random_uuid()::text, 'CUSTOM_SOURCE', 'test-source',
                    (SELECT id FROM "Organization" LIMIT 1), '{}'::jsonb, 'CONNECTED')
            RETURNING id
        """)
        iid = cur.fetchone()[0]
    conn.commit()
    yield iid
    with conn.cursor() as cur:
        cur.execute('DELETE FROM "Integration" WHERE id = %s', (iid,))
    conn.commit()
    conn.close()


def test_save_probe_run_writes_metrics(integration_id):
    bundle = MetricBundle(
        probed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        row_count=10,
        latest_timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
        column_schema=[{"name": "id", "data_type": "integer", "is_nullable": False}],
        null_counts={"id": 0},
        distinct_counts={"id": 10},
        value_fingerprints={"id": b"\x00\x01"},
        min_max_numeric={"id": (1.0, 10.0)},
    )
    run_id = save_probe_run(integration_id, "water_meters", bundle, duration_ms=42)
    assert run_id


def test_save_probe_failure_writes_error(integration_id):
    run_id = save_probe_failure(
        integration_id, "water_meters",
        error_code="auth_failed", error_message="HTTP 401",
        duration_ms=10,
    )
    assert run_id
```

- [ ] **Step 2: Run, see ImportError**

Run: `pytest scanner/tests/drivers/test_probe_persistence.py -v`
Expected: FAIL — `probe_persistence` module doesn't exist (or skipped if no DATABASE_URL).

- [ ] **Step 3: Implement persistence helpers**

```python
# scanner/drivers/source/probe_persistence.py
"""
Persist HttpProbeAdapter results to the CustomSourceProbeRun table.

NEVER persists raw rows — only derived metrics from MetricBundle.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Optional

from scanner.adapters.http_probe import MetricBundle

logger = logging.getLogger(__name__)


def _json_safe_fingerprints(fingerprints):
    return {col: base64.b64encode(buf).decode("ascii") for col, buf in fingerprints.items()}


def _json_safe_min_max(min_max_numeric):
    return {col: list(pair) for col, pair in min_max_numeric.items()}


def save_probe_run(
    integration_id: str,
    dataset_id: str,
    bundle: MetricBundle,
    duration_ms: Optional[int] = None,
) -> str:
    """Insert a successful CustomSourceProbeRun. Returns the new row id."""
    from scanner.scheduler.service import _get_connection
    import uuid

    run_id = str(uuid.uuid4()).replace("-", "")[:25]  # mimic cuid()-ish format

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "CustomSourceProbeRun" (
                    id, "integrationId", "datasetId", status,
                    "rowCount", "latestTimestamp",
                    "columnSchema", "nullCounts", "distinctCounts",
                    "valueFingerprints", "minMaxNumeric",
                    "probedAt", "durationMs"
                )
                VALUES (
                    %s, %s, %s, 'SUCCESS',
                    %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s::jsonb,
                    %s, %s
                )
                """,
                (
                    run_id, integration_id, dataset_id,
                    bundle.row_count, bundle.latest_timestamp,
                    json.dumps(bundle.column_schema),
                    json.dumps(bundle.null_counts),
                    json.dumps(bundle.distinct_counts),
                    json.dumps(_json_safe_fingerprints(bundle.value_fingerprints)),
                    json.dumps(_json_safe_min_max(bundle.min_max_numeric)),
                    bundle.probed_at, duration_ms,
                ),
            )
        conn.commit()
        logger.info("[ProbeRun] saved", run_id=run_id, integration_id=integration_id, dataset_id=dataset_id)
        return run_id
    finally:
        conn.close()


def save_probe_failure(
    integration_id: str,
    dataset_id: str,
    error_code: str,
    error_message: str,
    duration_ms: Optional[int] = None,
) -> str:
    """Insert a failed CustomSourceProbeRun. Returns the new row id."""
    from scanner.scheduler.service import _get_connection
    from datetime import datetime, timezone
    import uuid

    run_id = str(uuid.uuid4()).replace("-", "")[:25]

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "CustomSourceProbeRun" (
                    id, "integrationId", "datasetId", status,
                    "errorCode", "errorMessage",
                    "probedAt", "durationMs"
                )
                VALUES (%s, %s, %s, 'FAILED', %s, %s, %s, %s)
                """,
                (
                    run_id, integration_id, dataset_id,
                    error_code, error_message,
                    datetime.now(timezone.utc), duration_ms,
                ),
            )
        conn.commit()
        return run_id
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests against a test DB**

Run: `DATABASE_URL=$DATABASE_URL pytest scanner/tests/drivers/test_probe_persistence.py -v`
Expected: PASS (if `DATABASE_URL` is set and migration from Task 3 is applied), or SKIPPED.

- [ ] **Step 5: Commit**

```bash
git add scanner/drivers/source/probe_persistence.py scanner/tests/drivers/test_probe_persistence.py
git commit -m "feat(drivers): probe-result persistence to CustomSourceProbeRun"
```

---

## Phase 5: Probe scheduling

### Task 15: Probe-due scanner + worker dispatch

**Files:**
- Create: `scanner/scheduler/probe_runner.py`
- Modify: `scanner/scheduler/service.py` (add probe scan into the existing scheduler tick)
- Create: `scanner/tests/scheduler/test_probe_runner.py`

- [ ] **Step 1: Write failing test for `run_due_probes`**

```python
# scanner/tests/scheduler/test_probe_runner.py
import os
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set",
)


def test_run_due_probes_picks_up_integrations_with_due_next_probe(monkeypatch):
    from scanner.scheduler.probe_runner import run_due_probes

    fake_integration = {
        "id": "i1",
        "config": {
            "base_url": "https://api.example.com/v1",
            "auth": {"kind": "bearer", "secret": "t"},
            "datasets": [{
                "id": "d1", "endpoint": "/r", "timestamp_column": "t",
            }],
            "platform_label": "Test",
        },
        "probeSchedule": "hourly",
    }

    fake_bundle = MagicMock()
    fake_bundle.row_count = 0

    with patch("scanner.scheduler.probe_runner._fetch_due_integrations") as fetch, \
         patch("scanner.scheduler.probe_runner._mark_next_probe_at") as mark, \
         patch("scanner.scheduler.probe_runner._resolve_secret", return_value="t"), \
         patch("scanner.scheduler.probe_runner.HttpProbeAdapter") as MockAdapter, \
         patch("scanner.scheduler.probe_runner.save_probe_run") as save:
        fetch.return_value = [fake_integration]
        MockAdapter.return_value.probe.return_value = fake_bundle

        n = run_due_probes()

        assert n == 1
        assert MockAdapter.called
        assert save.called
        assert mark.called
```

- [ ] **Step 2: Run, see ImportError**

Run: `pytest scanner/tests/scheduler/test_probe_runner.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `probe_runner.py`**

```python
# scanner/scheduler/probe_runner.py
"""
Probe runner — finds CUSTOM_SOURCE integrations with due nextProbeAt
and runs HttpProbeAdapter for each configured dataset.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from scanner.adapters.http_probe import HttpProbeAdapter, ProbeError
from scanner.drivers.source.probe_persistence import save_probe_failure, save_probe_run

logger = logging.getLogger(__name__)

_SCHEDULE_TO_TIMEDELTA = {
    "hourly": timedelta(hours=1),
    "every_6h": timedelta(hours=6),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}


def _fetch_due_integrations() -> List[Dict[str, Any]]:
    """Return CUSTOM_SOURCE integrations with nextProbeAt <= now."""
    from scanner.scheduler.service import _get_connection
    now = datetime.now(timezone.utc)
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, config, "probeSchedule"
                FROM "Integration"
                WHERE type = 'CUSTOM_SOURCE'
                  AND status = 'CONNECTED'
                  AND "nextProbeAt" IS NOT NULL
                  AND "nextProbeAt" <= %s
                FOR UPDATE SKIP LOCKED
                """,
                (now,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.commit()
        return rows
    finally:
        conn.close()


def _mark_next_probe_at(integration_id: str, schedule: str) -> None:
    delta = _SCHEDULE_TO_TIMEDELTA.get(schedule, timedelta(days=1))
    next_at = datetime.now(timezone.utc) + delta
    from scanner.scheduler.service import _get_connection
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Integration" SET "nextProbeAt" = %s WHERE id = %s',
                (next_at, integration_id),
            )
        conn.commit()
    finally:
        conn.close()


def _resolve_secret(secret_ref: str) -> str:
    """Decrypt or fetch the secret backing this integration.

    For V1 this looks up the encrypted credential blob on the Integration
    row and decrypts via scanner.scheduler.executor._decrypt.
    """
    from scanner.scheduler.executor import _decrypt
    from scanner.scheduler.service import _get_connection
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT value FROM "IntegrationSecret" WHERE id = %s',
                (secret_ref,),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"secret {secret_ref!r} not found")
            return _decrypt(row[0])
    finally:
        conn.close()


def run_due_probes() -> int:
    """Run all due probes. Returns the number of (integration, dataset) probes attempted."""
    integrations = _fetch_due_integrations()
    attempted = 0

    for integration in integrations:
        config = integration["config"] or {}
        datasets = config.get("datasets") or []
        auth = dict(config.get("auth") or {})

        # Resolve secret (replace secret_ref with actual secret)
        secret_ref = auth.pop("secret_ref", None)
        if secret_ref:
            try:
                auth["secret"] = _resolve_secret(secret_ref)
            except Exception as exc:
                logger.error("[ProbeRunner] secret resolution failed", err=str(exc))
                _mark_next_probe_at(integration["id"], integration.get("probeSchedule") or "daily")
                continue

        adapter = HttpProbeAdapter(
            base_url=config.get("base_url", ""),
            auth=auth,
        )

        for ds in datasets:
            attempted += 1
            start = time.time()
            try:
                bundle = adapter.probe({
                    "endpoint": ds["endpoint"],
                    "timestamp_column": ds.get("timestamp_column"),
                    "json_root": ds.get("json_root"),
                    "cursor_param": ds.get("cursor_param"),
                })
                duration = int((time.time() - start) * 1000)
                save_probe_run(integration["id"], ds["id"], bundle, duration_ms=duration)
            except ProbeError as exc:
                duration = int((time.time() - start) * 1000)
                save_probe_failure(
                    integration["id"], ds["id"],
                    error_code=exc.code, error_message=exc.message,
                    duration_ms=duration,
                )
            except Exception as exc:
                duration = int((time.time() - start) * 1000)
                save_probe_failure(
                    integration["id"], ds["id"],
                    error_code="unknown_error", error_message=str(exc),
                    duration_ms=duration,
                )

        _mark_next_probe_at(integration["id"], integration.get("probeSchedule") or "daily")

    return attempted
```

- [ ] **Step 4: Run unit test**

Run: `pytest scanner/tests/scheduler/test_probe_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Wire `run_due_probes` into the scheduler tick**

In `scanner/scheduler/service.py`, find the loop body that calls `await self._check_due_tasks()` and add a new call alongside it. Locate the line `await self._check_due_tasks()` (around line 177) and add:

```python
                # Custom-source probes run on their own cadence
                try:
                    from scanner.scheduler.probe_runner import run_due_probes
                    n = run_due_probes()
                    if n:
                        logger.info("[Scheduler] Ran custom-source probes", count=n)
                except Exception as exc:
                    logger.warning("[Scheduler] probe runner failed", err=str(exc))
```

Place this immediately after the existing `await self._check_due_tasks()` call.

- [ ] **Step 6: Commit**

```bash
git add scanner/scheduler/probe_runner.py scanner/scheduler/service.py scanner/tests/scheduler/test_probe_runner.py
git commit -m "feat(scheduler): probe runner for CUSTOM_SOURCE integrations"
```

---

## Phase 6: Monitor wiring

The four standard monitors (`freshness`, `volume`, `null_check`, `schema_change`) need a code path that, when the monitor's target is a CUSTOM_SOURCE dataset, reads from the most recent successful `CustomSourceProbeRun` instead of issuing a SQL query. This is one focused change per monitor file plus a helper.

### Task 16: Helper — `latest_probe_run_for(integration_id, dataset_id)`

**Files:**
- Create: `scanner/monitors/custom_source_results.py`

The helper is a thin SQL wrapper. It is exercised end-to-end by the monitor branch tests in Task 17, so this task does not add a dedicated unit test.

- [ ] **Step 1: Implement helper**

```python
# scanner/monitors/custom_source_results.py
"""Read the most recent successful probe run for a CUSTOM_SOURCE dataset."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional


def latest_probe_run_for(integration_id: str, dataset_id: str) -> Optional[Dict[str, Any]]:
    """Return the most recent SUCCESS probe run, or None."""
    from scanner.scheduler.service import _get_connection
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT "rowCount", "latestTimestamp", "columnSchema",
                       "nullCounts", "distinctCounts", "minMaxNumeric",
                       "probedAt"
                FROM "CustomSourceProbeRun"
                WHERE "integrationId" = %s AND "datasetId" = %s AND status = 'SUCCESS'
                ORDER BY "probedAt" DESC
                LIMIT 1
                """,
                (integration_id, dataset_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "row_count": row[0],
                "latest_timestamp": row[1],
                "column_schema": row[2] if isinstance(row[2], (dict, list)) else (json.loads(row[2]) if row[2] else None),
                "null_counts": row[3] if isinstance(row[3], dict) else (json.loads(row[3]) if row[3] else {}),
                "distinct_counts": row[4] if isinstance(row[4], dict) else (json.loads(row[4]) if row[4] else {}),
                "min_max_numeric": row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if row[5] else {}),
                "probed_at": row[6],
            }
    finally:
        conn.close()


def previous_probe_run_for(integration_id: str, dataset_id: str) -> Optional[Dict[str, Any]]:
    """Return the second-most-recent SUCCESS probe run, or None.

    Used by the schema-drift monitor to compare the latest probe's column
    schema against the previous one.
    """
    from scanner.scheduler.service import _get_connection
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT "rowCount", "latestTimestamp", "columnSchema",
                       "nullCounts", "distinctCounts", "minMaxNumeric",
                       "probedAt"
                FROM "CustomSourceProbeRun"
                WHERE "integrationId" = %s AND "datasetId" = %s AND status = 'SUCCESS'
                ORDER BY "probedAt" DESC
                OFFSET 1 LIMIT 1
                """,
                (integration_id, dataset_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "row_count": row[0],
                "latest_timestamp": row[1],
                "column_schema": row[2] if isinstance(row[2], (dict, list)) else (json.loads(row[2]) if row[2] else None),
                "null_counts": row[3] if isinstance(row[3], dict) else (json.loads(row[3]) if row[3] else {}),
                "distinct_counts": row[4] if isinstance(row[4], dict) else (json.loads(row[4]) if row[4] else {}),
                "min_max_numeric": row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if row[5] else {}),
                "probed_at": row[6],
            }
    finally:
        conn.close()
```

- [ ] **Step 2: Commit**

```bash
git add scanner/monitors/custom_source_results.py
git commit -m "feat(monitors): helpers to read latest and previous CustomSourceProbeRun"
```

---

### Task 17: Wire freshness, volume, null_check, schema_change to read probe results

**Files:**
- Modify: `scanner/monitors/freshness.py`, `scanner/monitors/volume.py`, `scanner/monitors/null_check.py`, `scanner/monitors/schema.py`

- [ ] **Step 1: Inspect each monitor file's `run`/`evaluate` entry-point**

Run: `grep -n "def run\|def evaluate\|integrationType\|integration_type" scanner/monitors/freshness.py scanner/monitors/volume.py scanner/monitors/null_check.py scanner/monitors/schema.py | head -40`
Expected: each file has a top-level monitor function that accepts `task: Dict` (carrying integrationType, integrationId, targetFqn / config). Note the function name and signature for each.

- [ ] **Step 2: For each monitor file, add an early branch that handles CUSTOM_SOURCE**

Pattern to apply at the top of each monitor's main entry point. **`freshness.py`** example:

```python
def run_freshness_monitor(task: Dict[str, Any]) -> Dict[str, Any]:
    integration_type = (task.get("integrationType") or "").upper()
    if integration_type == "CUSTOM_SOURCE":
        return _run_freshness_for_custom_source(task)
    # ...existing implementation
```

Add helper `_run_freshness_for_custom_source` at file bottom:

```python
def _run_freshness_for_custom_source(task: Dict[str, Any]) -> Dict[str, Any]:
    from scanner.monitors.custom_source_results import latest_probe_run_for
    from datetime import datetime, timezone

    integration_id = task["integrationId"]
    dataset_id = (task.get("config") or {}).get("dataset_id")
    if not dataset_id:
        return {"status": "ERROR", "message": "config.dataset_id missing for CUSTOM_SOURCE freshness"}

    run = latest_probe_run_for(integration_id, dataset_id)
    if not run:
        return {"status": "ERROR", "message": "no probe run yet"}

    latest_ts = run["latest_timestamp"]
    if latest_ts is None:
        return {"status": "ERROR", "message": "probe captured no timestamp"}

    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    hours = (now - latest_ts).total_seconds() / 3600.0

    threshold = float((task.get("config") or {}).get("max_hours_since_update", 24))
    return {
        "status": "OK" if hours <= threshold else "ALERT",
        "value": hours,
        "threshold": threshold,
        "message": f"{hours:.1f} hours since last record",
    }
```

For `volume.py`, locate the main monitor entry-point (call it `run_volume_monitor` — confirm name from Step 1's grep) and add the same dispatch line near the top:

```python
def run_volume_monitor(task: Dict[str, Any]) -> Dict[str, Any]:
    integration_type = (task.get("integrationType") or "").upper()
    if integration_type == "CUSTOM_SOURCE":
        return _run_volume_for_custom_source(task)
    # ...existing implementation
```

Add helper at file bottom:

```python
def _run_volume_for_custom_source(task: Dict[str, Any]) -> Dict[str, Any]:
    from scanner.monitors.custom_source_results import latest_probe_run_for

    integration_id = task["integrationId"]
    config = task.get("config") or {}
    dataset_id = config.get("dataset_id")
    if not dataset_id:
        return {"status": "ERROR", "message": "config.dataset_id missing for CUSTOM_SOURCE volume"}

    run = latest_probe_run_for(integration_id, dataset_id)
    if not run:
        return {"status": "ERROR", "message": "no probe run yet"}

    row_count = int(run.get("row_count") or 0)
    min_rows = config.get("min_rows")
    max_rows = config.get("max_rows")

    status = "OK"
    msg = f"row_count={row_count}"
    if min_rows is not None and row_count < int(min_rows):
        status, msg = "ALERT", f"row_count {row_count} < min {min_rows}"
    elif max_rows is not None and row_count > int(max_rows):
        status, msg = "ALERT", f"row_count {row_count} > max {max_rows}"

    return {
        "status": status,
        "value": float(row_count),
        "threshold": float(min_rows) if min_rows is not None else None,
        "message": msg,
    }
```

For `null_check.py`, add the same dispatch and helper:

```python
def run_null_check_monitor(task: Dict[str, Any]) -> Dict[str, Any]:
    integration_type = (task.get("integrationType") or "").upper()
    if integration_type == "CUSTOM_SOURCE":
        return _run_null_check_for_custom_source(task)
    # ...existing implementation


def _run_null_check_for_custom_source(task: Dict[str, Any]) -> Dict[str, Any]:
    from scanner.monitors.custom_source_results import latest_probe_run_for

    integration_id = task["integrationId"]
    config = task.get("config") or {}
    dataset_id = config.get("dataset_id")
    column = config.get("column")
    if not dataset_id or not column:
        return {"status": "ERROR", "message": "config.dataset_id and config.column required"}

    run = latest_probe_run_for(integration_id, dataset_id)
    if not run:
        return {"status": "ERROR", "message": "no probe run yet"}

    row_count = int(run.get("row_count") or 0)
    null_counts = run.get("null_counts") or {}
    if row_count == 0:
        return {"status": "OK", "value": 0.0, "threshold": None, "message": "empty dataset"}

    null_count = int(null_counts.get(column) or 0)
    null_rate = null_count / row_count

    threshold = float(config.get("max_null_rate", 0.0))
    status = "ALERT" if null_rate > threshold else "OK"
    return {
        "status": status,
        "value": null_rate,
        "threshold": threshold,
        "message": f"null rate for {column!r}: {null_rate:.3f} (max {threshold:.3f})",
    }
```

For `schema.py`, add the dispatch + helper that compares the latest probe's schema against the previous one (using `previous_probe_run_for` from Task 16):

```python
def run_schema_monitor(task: Dict[str, Any]) -> Dict[str, Any]:
    integration_type = (task.get("integrationType") or "").upper()
    if integration_type == "CUSTOM_SOURCE":
        return _run_schema_for_custom_source(task)
    # ...existing implementation


def _run_schema_for_custom_source(task: Dict[str, Any]) -> Dict[str, Any]:
    from scanner.monitors.custom_source_results import (
        latest_probe_run_for, previous_probe_run_for,
    )

    integration_id = task["integrationId"]
    config = task.get("config") or {}
    dataset_id = config.get("dataset_id")
    if not dataset_id:
        return {"status": "ERROR", "message": "config.dataset_id missing for CUSTOM_SOURCE schema"}

    latest = latest_probe_run_for(integration_id, dataset_id)
    if not latest:
        return {"status": "ERROR", "message": "no probe run yet"}

    previous = previous_probe_run_for(integration_id, dataset_id)
    if not previous:
        # First successful probe — no comparison possible, no drift.
        return {"status": "OK", "value": 0.0, "threshold": None, "message": "baseline established"}

    def _index(schema):
        return {col["name"]: col.get("data_type") for col in (schema or [])}

    cur_idx = _index(latest.get("column_schema"))
    prev_idx = _index(previous.get("column_schema"))

    added = sorted(set(cur_idx) - set(prev_idx))
    removed = sorted(set(prev_idx) - set(cur_idx))
    type_changed = sorted(
        c for c in set(cur_idx) & set(prev_idx) if cur_idx[c] != prev_idx[c]
    )

    drift_count = len(added) + len(removed) + len(type_changed)
    status = "ALERT" if drift_count > 0 else "OK"
    msg_parts = []
    if added: msg_parts.append(f"added: {added}")
    if removed: msg_parts.append(f"removed: {removed}")
    if type_changed: msg_parts.append(f"type-changed: {type_changed}")
    return {
        "status": status,
        "value": float(drift_count),
        "threshold": 0.0,
        "message": "; ".join(msg_parts) if msg_parts else "no schema drift",
        "details": {"added": added, "removed": removed, "type_changed": type_changed},
    }
```

- [ ] **Step 3: Add unit tests — one per monitor branch**

Create: `scanner/tests/monitors/test_custom_source_branches.py`

```python
"""Unit tests for the CUSTOM_SOURCE branches in each monitor type."""
from datetime import datetime, timedelta, timezone


def test_freshness_returns_alert_when_stale(monkeypatch):
    from scanner.monitors.freshness import _run_freshness_for_custom_source

    fake_run = {
        "latest_timestamp": datetime.now(timezone.utc) - timedelta(hours=48),
    }
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: fake_run,
    )
    result = _run_freshness_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "max_hours_since_update": 24},
    })
    assert result["status"] == "ALERT"


def test_freshness_returns_ok_when_fresh(monkeypatch):
    from scanner.monitors.freshness import _run_freshness_for_custom_source

    fake_run = {
        "latest_timestamp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: fake_run,
    )
    result = _run_freshness_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "max_hours_since_update": 24},
    })
    assert result["status"] == "OK"


def test_volume_alerts_when_below_min(monkeypatch):
    from scanner.monitors.volume import _run_volume_for_custom_source

    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: {"row_count": 5},
    )
    result = _run_volume_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "min_rows": 10},
    })
    assert result["status"] == "ALERT"
    assert result["value"] == 5.0


def test_volume_ok_within_range(monkeypatch):
    from scanner.monitors.volume import _run_volume_for_custom_source

    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: {"row_count": 50},
    )
    result = _run_volume_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "min_rows": 10, "max_rows": 100},
    })
    assert result["status"] == "OK"


def test_null_check_alerts_when_rate_exceeds_threshold(monkeypatch):
    from scanner.monitors.null_check import _run_null_check_for_custom_source

    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: {"row_count": 10, "null_counts": {"sensor": 3}},
    )
    result = _run_null_check_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "column": "sensor", "max_null_rate": 0.1},
    })
    assert result["status"] == "ALERT"
    assert result["value"] == 0.3


def test_null_check_ok_when_no_nulls(monkeypatch):
    from scanner.monitors.null_check import _run_null_check_for_custom_source

    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: {"row_count": 10, "null_counts": {"sensor": 0}},
    )
    result = _run_null_check_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1", "column": "sensor", "max_null_rate": 0.05},
    })
    assert result["status"] == "OK"


def test_schema_alerts_on_added_column(monkeypatch):
    from scanner.monitors.schema import _run_schema_for_custom_source

    latest = {"column_schema": [
        {"name": "id", "data_type": "integer"},
        {"name": "new_col", "data_type": "string"},
    ]}
    previous = {"column_schema": [
        {"name": "id", "data_type": "integer"},
    ]}
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: latest,
    )
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.previous_probe_run_for",
        lambda i, d: previous,
    )
    result = _run_schema_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1"},
    })
    assert result["status"] == "ALERT"
    assert "new_col" in result["details"]["added"]


def test_schema_ok_when_baseline_only(monkeypatch):
    from scanner.monitors.schema import _run_schema_for_custom_source

    latest = {"column_schema": [{"name": "id", "data_type": "integer"}]}
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.latest_probe_run_for",
        lambda i, d: latest,
    )
    monkeypatch.setattr(
        "scanner.monitors.custom_source_results.previous_probe_run_for",
        lambda i, d: None,
    )
    result = _run_schema_for_custom_source({
        "integrationId": "i1",
        "config": {"dataset_id": "d1"},
    })
    assert result["status"] == "OK"
```

- [ ] **Step 4: Run all monitor tests**

Run: `pytest scanner/tests/monitors/test_custom_source_branches.py -v`
Expected: all 8 tests PASS.

Run: `pytest scanner/tests/monitors/ -v`
Expected: full monitor suite still PASSes (no regression in existing monitor tests).

- [ ] **Step 5: Commit**

```bash
git add scanner/monitors/freshness.py scanner/monitors/volume.py scanner/monitors/null_check.py scanner/monitors/schema.py scanner/tests/monitors/test_custom_source_branches.py
git commit -m "feat(monitors): wire freshness/volume/null/schema to CUSTOM_SOURCE probe runs"
```

---

## Phase 7: API layer

### Task 18: `/integrations/test-connection` accepts CUSTOM_SOURCE

**Files:**
- Modify: `app/api/integrations/test-connection/route.ts`
- Modify: `scanner/api/routers/` (whichever router handles test-connection — find it)

- [ ] **Step 1: Find the FastAPI test-connection endpoint**

Run: `grep -rn "test-connection\|test_connection" scanner/api/routers/ --include="*.py" | head`
Expected: locate the router file, e.g. `scanner/api/routers/integrations.py`.

- [ ] **Step 2: Add CUSTOM_SOURCE branch in the FastAPI router**

In the relevant router, find the existing `if integration_type == "SNOWFLAKE": ...` cascade and add:

```python
elif integration_type == "CUSTOM_SOURCE":
    from scanner.drivers.source.custom_source_driver import CustomSourceDriver
    driver = CustomSourceDriver()
    result = driver.test_connection(config)
    return {
        "ok": result.ok,
        "message": result.message,
        "latency_ms": result.latency_ms,
    }
```

If the existing pattern uses the driver loader directly, prefer:

```python
from scanner.drivers.loader import get_driver_for_integration_type
driver = get_driver_for_integration_type(integration_type)
if driver is None:
    raise HTTPException(400, f"unsupported integration type: {integration_type}")
result = driver.test_connection(config)
```

(this branch handles all driver types uniformly; verify it works for CUSTOM_SOURCE before removing per-type branches).

- [ ] **Step 3: Add an integration test**

```python
# scanner/tests/api/test_integrations_routes.py — append
import responses
from fastapi.testclient import TestClient


@responses.activate
def test_test_connection_custom_source_ok(client: TestClient, internal_auth_header):
    responses.add(
        responses.GET, "https://api.example.com/v1/x",
        json=[{"id": 1}], status=200,
    )
    resp = client.post(
        "/api/v1/integrations/test-connection",
        json={
            "integrationType": "CUSTOM_SOURCE",
            "config": {
                "base_url": "https://api.example.com/v1",
                "auth": {"kind": "bearer", "secret": "t"},
                "datasets": [{"id": "d", "endpoint": "/x", "timestamp_column": "id"}],
            },
        },
        headers=internal_auth_header,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
```

- [ ] **Step 4: Run**

Run: `pytest scanner/tests/api/test_integrations_routes.py -v -k custom_source`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/api/routers/ scanner/tests/api/
git commit -m "feat(api): test-connection endpoint handles CUSTOM_SOURCE"
```

---

### Task 19: `POST /integrations/{id}/probe-now` — manual probe trigger

**Files:**
- Modify: `scanner/api/routers/integrations.py` (or wherever integrations routes live)

- [ ] **Step 1: Add the endpoint**

```python
from fastapi import HTTPException

@router.post("/integrations/{integration_id}/probe-now")
async def probe_now(integration_id: str, dataset_id: Optional[str] = None):
    """Manually trigger a probe for a CUSTOM_SOURCE integration."""
    from scanner.scheduler.probe_runner import run_due_probes
    # Quick implementation: mark this one due-now and run.
    from scanner.scheduler.service import _get_connection
    from datetime import datetime, timezone
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Integration" SET "nextProbeAt" = %s WHERE id = %s AND type = \'CUSTOM_SOURCE\'',
                (datetime.now(timezone.utc), integration_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(404, "integration not found or not CUSTOM_SOURCE")
        conn.commit()
    finally:
        conn.close()
    n = run_due_probes()
    return {"probes_attempted": n}
```

- [ ] **Step 2: Smoke-test manually (optional)**

Run: `curl -X POST http://localhost:8000/api/v1/integrations/<id>/probe-now -H "X-Internal-Key: <key>"`
Expected: `{"probes_attempted": <n>}`.

- [ ] **Step 3: Commit**

```bash
git add scanner/api/routers/integrations.py
git commit -m "feat(api): manual probe-now endpoint for CUSTOM_SOURCE"
```

---

## Phase 8: Wizard UI

The wizard is a 5-step Next.js flow. Built as a single client component with step state in URL search params (so refreshes preserve state). Mirrors the existing Snowflake/BigQuery wizards in shape and styling.

### Task 20: Wizard scaffold + Step 1 (Identity)

**Files:**
- Create: `app/(dashboard)/dashboard/integrations/connect/custom-source/page.tsx`
- Create: `app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx`

- [ ] **Step 1: Find the existing Snowflake wizard pattern**

Run: `find "app/(dashboard)" -path "*connect*" -o -path "*integrations/new*" 2>/dev/null && grep -rn "Snowflake\|BigQuery" app/\(dashboard\)/ -l | head -5`
Expected: locate the existing wizard component.

- [ ] **Step 2: Create the page entry**

```tsx
// app/(dashboard)/dashboard/integrations/connect/custom-source/page.tsx
import CustomSourceWizard from "./CustomSourceWizard";

export default function CustomSourceConnectPage() {
  return <CustomSourceWizard />;
}
```

- [ ] **Step 3: Create the wizard component with step 1**

```tsx
// app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx
"use client";

import { useState } from "react";

type Step = 1 | 2 | 3 | 4 | 5;

interface WizardState {
  name: string;
  platformLabel: string;
  baseUrl: string;
  auth: { kind: "bearer" | "api_key" | "basic"; secret: string; headerName?: string; username?: string };
  datasets: Array<{
    id: string;
    endpoint: string;
    timestampColumn: string;
    cursorParam?: string;
    jsonRoot?: string;
    landsIn?: string;
  }>;
  schedule: "hourly" | "every_6h" | "daily" | "weekly";
}

const initial: WizardState = {
  name: "",
  platformLabel: "",
  baseUrl: "",
  auth: { kind: "bearer", secret: "" },
  datasets: [],
  schedule: "daily",
};

export default function CustomSourceWizard() {
  const [step, setStep] = useState<Step>(1);
  const [state, setState] = useState<WizardState>(initial);

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Connect a Custom Source</h1>
      <ol className="flex gap-4 text-sm text-muted-foreground">
        {["Identity", "Connection", "Datasets", "Schedule", "Review"].map((label, i) => (
          <li key={label} className={step === i + 1 ? "font-bold" : ""}>
            {i + 1}. {label}
          </li>
        ))}
      </ol>

      {step === 1 && (
        <div className="space-y-4">
          <label className="block">
            <span className="text-sm font-medium">Display name</span>
            <input
              type="text"
              value={state.name}
              onChange={(e) => setState({ ...state, name: e.target.value })}
              placeholder="e.g. MyCiti — water sensors"
              className="mt-1 w-full border rounded px-3 py-2"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Platform label (shown in lineage)</span>
            <input
              type="text"
              value={state.platformLabel}
              onChange={(e) => setState({ ...state, platformLabel: e.target.value })}
              placeholder="e.g. MyCiti"
              className="mt-1 w-full border rounded px-3 py-2"
            />
          </label>
          <button
            disabled={!state.name || !state.platformLabel}
            onClick={() => setStep(2)}
            className="px-4 py-2 bg-primary text-primary-foreground rounded disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify the page renders**

Run dev server, visit `http://localhost:3000/dashboard/integrations/connect/custom-source`, fill in two fields, click Next.
Expected: step indicator advances; no console errors.

- [ ] **Step 5: Commit**

```bash
git add "app/(dashboard)/dashboard/integrations/connect/custom-source/"
git commit -m "feat(ui): custom-source wizard scaffold and step 1 (identity)"
```

---

### Task 21: Wizard step 2 — Connection (URL + auth)

**Files:**
- Modify: `app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx`

- [ ] **Step 1: Add the step 2 panel inside the wizard component**

Below the `{step === 1 && ...}` block, add:

```tsx
{step === 2 && (
  <div className="space-y-4">
    <label className="block">
      <span className="text-sm font-medium">Base URL (must be https://)</span>
      <input
        type="url"
        value={state.baseUrl}
        onChange={(e) => setState({ ...state, baseUrl: e.target.value })}
        placeholder="https://portal.example.com/api/v1"
        className="mt-1 w-full border rounded px-3 py-2"
      />
    </label>

    <fieldset className="border rounded p-4">
      <legend className="px-2 text-sm font-medium">Authentication</legend>
      {(["bearer", "api_key", "basic"] as const).map((kind) => (
        <label key={kind} className="flex items-center gap-2 mt-2">
          <input
            type="radio"
            checked={state.auth.kind === kind}
            onChange={() => setState({ ...state, auth: { ...state.auth, kind } })}
          />
          <span className="text-sm">{kind === "api_key" ? "API key (header)" : kind === "bearer" ? "Bearer token" : "Basic auth"}</span>
        </label>
      ))}

      {state.auth.kind === "api_key" && (
        <input
          type="text"
          value={state.auth.headerName || "X-API-Key"}
          onChange={(e) => setState({ ...state, auth: { ...state.auth, headerName: e.target.value } })}
          placeholder="Header name (defaults to X-API-Key)"
          className="mt-3 w-full border rounded px-3 py-2"
        />
      )}
      {state.auth.kind === "basic" && (
        <input
          type="text"
          value={state.auth.username || ""}
          onChange={(e) => setState({ ...state, auth: { ...state.auth, username: e.target.value } })}
          placeholder="Username"
          className="mt-3 w-full border rounded px-3 py-2"
        />
      )}

      <input
        type="password"
        value={state.auth.secret}
        onChange={(e) => setState({ ...state, auth: { ...state.auth, secret: e.target.value } })}
        placeholder={state.auth.kind === "basic" ? "Password" : "Token / key"}
        className="mt-3 w-full border rounded px-3 py-2"
      />
    </fieldset>

    <div className="flex gap-2">
      <button onClick={() => setStep(1)} className="px-4 py-2 border rounded">Back</button>
      <button
        disabled={!state.baseUrl.startsWith("https://") || !state.auth.secret}
        onClick={() => setStep(3)}
        className="px-4 py-2 bg-primary text-primary-foreground rounded disabled:opacity-50"
      >
        Next
      </button>
    </div>
  </div>
)}
```

- [ ] **Step 2: Visually verify**

Reload page, navigate to step 2, change auth radio buttons.
Expected: header-name field appears for `api_key`, username field appears for `basic`, secret field always present, Next disabled until valid.

- [ ] **Step 3: Commit**

```bash
git add "app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx"
git commit -m "feat(ui): wizard step 2 (connection + auth)"
```

---

### Task 22: Wizard step 3 — Datasets (with test-fetch preview)

**Files:**
- Modify: `app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx`
- Create: `app/api/integrations/custom-source/preview/route.ts` (Next.js proxy to FastAPI test-connection / probe)

- [ ] **Step 1: Create the preview API route**

```typescript
// app/api/integrations/custom-source/preview/route.ts
import { NextRequest, NextResponse } from "next/server";

const FASTAPI = process.env.FASTAPI_BASE_URL || "http://localhost:8000";
const KEY = process.env.INTERNAL_API_KEY || "";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const r = await fetch(`${FASTAPI}/api/v1/integrations/test-connection`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Internal-Key": KEY },
    body: JSON.stringify({
      integrationType: "CUSTOM_SOURCE",
      config: body.config,
    }),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
```

- [ ] **Step 2: Add step 3 panel in the wizard**

```tsx
{step === 3 && (
  <div className="space-y-4">
    <p className="text-sm text-muted-foreground">
      Add one or more datasets. Each dataset becomes a monitored asset.
    </p>
    {state.datasets.map((ds, i) => (
      <fieldset key={i} className="border rounded p-4 space-y-2">
        <legend className="px-2 text-sm font-medium">Dataset {i + 1}</legend>
        <input
          type="text"
          value={ds.id}
          onChange={(e) => {
            const next = [...state.datasets];
            next[i] = { ...next[i], id: e.target.value };
            setState({ ...state, datasets: next });
          }}
          placeholder="Dataset id (e.g. water_meters)"
          className="w-full border rounded px-3 py-2"
        />
        <input
          type="text"
          value={ds.endpoint}
          onChange={(e) => {
            const next = [...state.datasets];
            next[i] = { ...next[i], endpoint: e.target.value };
            setState({ ...state, datasets: next });
          }}
          placeholder="Endpoint path (e.g. /sensors/readings)"
          className="w-full border rounded px-3 py-2"
        />
        <input
          type="text"
          value={ds.timestampColumn}
          onChange={(e) => {
            const next = [...state.datasets];
            next[i] = { ...next[i], timestampColumn: e.target.value };
            setState({ ...state, datasets: next });
          }}
          placeholder="Timestamp column (e.g. reading_at)"
          className="w-full border rounded px-3 py-2"
        />
        <button
          type="button"
          className="text-sm text-blue-600 underline"
          onClick={async () => {
            const r = await fetch("/api/integrations/custom-source/preview", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                config: {
                  base_url: state.baseUrl,
                  auth: state.auth,
                  datasets: [{
                    id: ds.id || "preview",
                    endpoint: ds.endpoint,
                    timestamp_column: ds.timestampColumn,
                  }],
                },
              }),
            });
            const data = await r.json();
            alert(data.ok ? `OK: ${data.message}` : `FAIL: ${data.message}`);
          }}
        >
          Test fetch
        </button>
      </fieldset>
    ))}

    <button
      type="button"
      onClick={() => setState({
        ...state,
        datasets: [...state.datasets, { id: "", endpoint: "", timestampColumn: "" }],
      })}
      className="px-4 py-2 border rounded"
    >
      + Add dataset
    </button>

    <div className="flex gap-2">
      <button onClick={() => setStep(2)} className="px-4 py-2 border rounded">Back</button>
      <button
        disabled={state.datasets.length === 0 || state.datasets.some(d => !d.id || !d.endpoint || !d.timestampColumn)}
        onClick={() => setStep(4)}
        className="px-4 py-2 bg-primary text-primary-foreground rounded disabled:opacity-50"
      >
        Next
      </button>
    </div>
  </div>
)}
```

- [ ] **Step 3: Verify in browser**

Manually click "Test fetch" against a real public JSON endpoint or a stubbed FastAPI test-connection.
Expected: alert with OK or FAIL message.

- [ ] **Step 4: Commit**

```bash
git add "app/(dashboard)/dashboard/integrations/connect/custom-source/" app/api/integrations/custom-source/
git commit -m "feat(ui): wizard step 3 (datasets) with test-fetch preview"
```

---

### Task 23: Wizard step 4 — Schedule + lands_in; Step 5 — Review + save

**Files:**
- Modify: `app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx`
- Modify: `app/api/integrations/route.ts` (or whichever existing route accepts new integration creation; verify path before editing)

- [ ] **Step 1: Add steps 4 and 5 to the wizard**

```tsx
{step === 4 && (
  <div className="space-y-4">
    <label className="block">
      <span className="text-sm font-medium">Probe schedule</span>
      <select
        value={state.schedule}
        onChange={(e) => setState({ ...state, schedule: e.target.value as WizardState["schedule"] })}
        className="mt-1 w-full border rounded px-3 py-2"
      >
        <option value="hourly">Hourly</option>
        <option value="every_6h">Every 6 hours</option>
        <option value="daily">Daily</option>
        <option value="weekly">Weekly</option>
      </select>
    </label>

    {state.datasets.map((ds, i) => (
      <label key={i} className="block">
        <span className="text-sm font-medium">{ds.id}: where does this data land in your warehouse? (optional)</span>
        <input
          type="text"
          value={ds.landsIn || ""}
          onChange={(e) => {
            const next = [...state.datasets];
            next[i] = { ...next[i], landsIn: e.target.value };
            setState({ ...state, datasets: next });
          }}
          placeholder="e.g. snowflake.raw.water_meters"
          className="mt-1 w-full border rounded px-3 py-2"
        />
      </label>
    ))}

    <div className="flex gap-2">
      <button onClick={() => setStep(3)} className="px-4 py-2 border rounded">Back</button>
      <button onClick={() => setStep(5)} className="px-4 py-2 bg-primary text-primary-foreground rounded">Next</button>
    </div>
  </div>
)}

{step === 5 && (
  <div className="space-y-4">
    <h2 className="text-lg font-medium">Review</h2>
    <pre className="bg-muted p-3 rounded text-xs overflow-auto">
      {JSON.stringify({ ...state, auth: { ...state.auth, secret: "•••" } }, null, 2)}
    </pre>
    <div className="flex gap-2">
      <button onClick={() => setStep(4)} className="px-4 py-2 border rounded">Back</button>
      <button
        onClick={async () => {
          const r = await fetch("/api/integrations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              type: "CUSTOM_SOURCE",
              name: state.name,
              config: {
                platform_label: state.platformLabel,
                base_url: state.baseUrl,
                auth: state.auth,
                datasets: state.datasets.map(d => ({
                  id: d.id,
                  endpoint: d.endpoint,
                  timestamp_column: d.timestampColumn,
                  cursor_param: d.cursorParam,
                  json_root: d.jsonRoot,
                  lands_in: d.landsIn,
                })),
                schedule: state.schedule,
              },
            }),
          });
          if (r.ok) {
            window.location.href = "/dashboard/integrations";
          } else {
            const err = await r.json();
            alert(`Failed to save: ${err.message || r.statusText}`);
          }
        }}
        className="px-4 py-2 bg-primary text-primary-foreground rounded"
      >
        Save
      </button>
    </div>
  </div>
)}
```

- [ ] **Step 2: Verify the existing `POST /api/integrations` route stores `config` JSON without modification**

Run: `grep -n "type\|config" "app/api/integrations/route.ts"` — confirm it forwards `config` as-is to the DB. If it strips fields based on a known whitelist of integration types, add a `CUSTOM_SOURCE` branch that accepts the `config` shape and writes the secret credential into `IntegrationSecret` (encrypted via the existing `encrypt()` helper from `lib/crypto.ts`), replacing `config.auth.secret` with `config.auth.secret_ref` before persisting. **Do not store the raw secret in the integration's config JSON.**

- [ ] **Step 3: Commit**

```bash
git add "app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard.tsx" app/api/integrations/
git commit -m "feat(ui): wizard steps 4 (schedule + lands_in) and 5 (review + save)"
```

---

### Task 24: Add the Custom Source card to the integrations connect page

**Files:**
- Modify: the existing integrations connect page (likely `app/(dashboard)/dashboard/integrations/page.tsx` or similar)

- [ ] **Step 1: Find the file**

Run: `grep -rn "Snowflake\|BigQuery\|integration_type\|integrationType" "app/(dashboard)/dashboard/integrations/" 2>/dev/null | head -20`
Expected: locate the file that lists available integration types as cards.

- [ ] **Step 2: Add a Custom Source card**

In the relevant component, add a new card alongside the warehouse cards:

```tsx
{
  id: "custom_source",
  type: "CUSTOM_SOURCE",
  layer: "SOURCE",
  name: "Custom Source",
  description: "Any HTTPS-accessible application with a JSON API. Configure it in 5 steps.",
  icon: "/integration-icons/custom-source.svg",
  href: "/dashboard/integrations/connect/custom-source",
}
```

- [ ] **Step 3: Verify card appears and clicking opens the wizard**

Visit `/dashboard/integrations`; click the new card.
Expected: navigates to the wizard.

- [ ] **Step 4: Commit**

```bash
git add "app/(dashboard)/dashboard/integrations/"
git commit -m "feat(ui): add Custom Source card to integrations connect page"
```

---

## Phase 9: Feature flag + rollout

### Task 25: Feature-flag gate `CUSTOM_SOURCE_INTEGRATION`

**Files:**
- Modify: `scanner/drivers/loader.py` (or `registry.py`)
- Modify: `app/(dashboard)/dashboard/integrations/page.tsx` (or whichever lists cards)
- Modify: `app/(dashboard)/dashboard/integrations/connect/custom-source/page.tsx`

- [ ] **Step 1: Gate driver registration**

In the driver loader, wrap the `CustomSourceDriver` registration:

```python
import os
if os.environ.get("FEATURE_CUSTOM_SOURCE_INTEGRATION", "").lower() in ("1", "true", "yes"):
    try:
        from scanner.drivers.source.custom_source_driver import CustomSourceDriver
        # ...register as before
    except ImportError as exc:
        logger.warning("CustomSourceDriver not available: %s", exc)
```

- [ ] **Step 2: Gate the wizard route — return 404 when flag off**

In `app/(dashboard)/dashboard/integrations/connect/custom-source/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import CustomSourceWizard from "./CustomSourceWizard";

export default function CustomSourceConnectPage() {
  if (process.env.NEXT_PUBLIC_FEATURE_CUSTOM_SOURCE_INTEGRATION !== "true") {
    notFound();
  }
  return <CustomSourceWizard />;
}
```

- [ ] **Step 3: Gate the integrations card**

In whichever file defines the `Custom Source` card from Task 24, add a conditional:

```tsx
...(process.env.NEXT_PUBLIC_FEATURE_CUSTOM_SOURCE_INTEGRATION === "true"
  ? [{ id: "custom_source", /* ...as before */ }]
  : []),
```

- [ ] **Step 4: Verify**

With flag off (`unset FEATURE_CUSTOM_SOURCE_INTEGRATION`), the card should not appear and `/dashboard/integrations/connect/custom-source` should 404.
With flag on (`FEATURE_CUSTOM_SOURCE_INTEGRATION=true`), everything works.

- [ ] **Step 5: Commit**

```bash
git add scanner/drivers/loader.py "app/(dashboard)/dashboard/integrations/"
git commit -m "feat(rollout): feature-flag gate CUSTOM_SOURCE_INTEGRATION"
```

---

### Task 26: Manual end-to-end smoke test against a public open-data API

**Files:** none — this is a verification task.

- [ ] **Step 1: Set the feature flag in dev**

```bash
export FEATURE_CUSTOM_SOURCE_INTEGRATION=true
export NEXT_PUBLIC_FEATURE_CUSTOM_SOURCE_INTEGRATION=true
# Restart Next.js + FastAPI
```

- [ ] **Step 2: Pick a public endpoint with an array-of-objects JSON response**

Example: a small public utility endpoint that returns `[{...}, {...}]` and supports a static API key or no auth (e.g. `https://datausa.io/api/data?...`). For "no auth," temporarily allow auth with empty secret, OR pick an endpoint that accepts a known-public bearer token.

- [ ] **Step 3: Use the wizard to register the source**

Navigate through all 5 steps, hit Save.

- [ ] **Step 4: Trigger a probe**

```bash
curl -X POST http://localhost:8000/api/v1/integrations/<id>/probe-now -H "X-Internal-Key: $INTERNAL_API_KEY"
```

- [ ] **Step 5: Verify `CustomSourceProbeRun` row exists**

```bash
psql $DATABASE_URL -c 'SELECT "integrationId", "datasetId", status, "rowCount", "probedAt" FROM "CustomSourceProbeRun" ORDER BY "probedAt" DESC LIMIT 5;'
```
Expected: at least one SUCCESS row with a non-zero rowCount.

- [ ] **Step 6: Verify the source appears in lineage and (if `lands_in` was set) the edge to the warehouse table is drawn**

Visit the lineage page, confirm the new SOURCE-platform node appears.

- [ ] **Step 7: Document result**

Append to the spec's "Rollout" section: a short note recording the public endpoint used, the probe result, and any issues hit. Commit.

```bash
git add docs/superpowers/specs/2026-04-30-custom-source-integration-design.md
git commit -m "docs(specs): record V1 smoke-test results for custom source"
```

---

## Self-Review Notes

The plan covers every section of the spec:

- **Goal & non-goals** → architecture summary at top of plan
- **New `IntegrationLayer.SOURCE`** → Task 1
- **`IntegrationType.CUSTOM_SOURCE`** → Task 2
- **`CustomSourceDriver`** → Tasks 10–13
- **`HttpProbeAdapter` + `MetricBundle`** → Tasks 4–9
- **Probe scheduler hook** → Task 15
- **Wizard UI (5 steps)** → Tasks 20–23
- **Configuration JSON shape** → enforced by `validate_config` (Task 10) and the wizard save payload (Task 23)
- **What is stored vs not stored** → Prisma model in Task 3 (no rows column); `MetricBundle` dataclass forbids it (Task 4)
- **Lineage integration via `lands_in`** → Task 12
- **Monitor integration** → Tasks 16–17
- **Failure handling** → covered by `ProbeError` codes (Tasks 5–9) + `save_probe_failure` (Task 14) + monitor `ERROR` paths (Task 17)
- **Test plan** → unit tests in Tasks 4–17, API integration in Task 18, manual smoke in Task 26
- **Rollout** → Tasks 25–26

**Type consistency:** The dataset config keys (`endpoint`, `timestamp_column`, `cursor_param`, `cursor_value`, `json_root`, `lands_in`) are used identically across `HttpProbeAdapter.probe`, `CustomSourceDriver.validate_config`, `probe_runner.run_due_probes`, and the wizard's save payload. The `MetricBundle` field names match across `http_probe.py`, `probe_persistence.py`, `custom_source_results.py`, and the four monitor branches.

**Known deviation from spec:** The spec says the probe runner should "Persist the resulting MetricBundle to the existing monitor-results store (same shape as warehouse SLA discovery results)." On reading the schema, `MonitorRun` is keyed to `Monitor` rows (1-to-1 with monitor evaluations), which doesn't fit a probe-per-dataset model. Task 3 introduces a dedicated `CustomSourceProbeRun` table; the four standard monitors then read from it (Tasks 16–17). This is a cleaner fit than overloading `MonitorRun` and was chosen deliberately during planning.
