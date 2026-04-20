# FastAPI Trust Boundary + Mandatory Auth Middleware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the Next.js ↔ FastAPI trust boundary with a shared-secret header + enforced loopback bind, make the Next.js auth middleware always-on, and propagate caller identity (userId + orgId) to FastAPI on every request. Foundation for spec 1b (per-pipeline authz).

**Architecture:** Trusted-subsystem pattern. FastAPI verifies every inbound request carries `X-Internal-Auth` (constant-time compare), then trusts `X-Acting-User`/`X-Acting-Org` headers for identity. Next.js unifies all outbound calls through a typed `scannerClient` that injects headers. Startup checks fail-closed in production (loopback bind, CORS configured, secret set).

**Tech Stack:** FastAPI + Starlette middleware, pytest + FastAPI TestClient, NextAuth v5, Jest + ts-jest.

**Spec:** `docs/superpowers/specs/2026-04-20-fastapi-trust-boundary-design.md`

---

## File Structure

**Python (new):**
- `scanner/api/auth.py` — `ActingPrincipal` dataclass, `InternalAuthMiddleware`, `ActingPrincipalMiddleware`, `require_principal()` dependency.
- `scanner/api/tests/test_auth.py` — unit tests for the middlewares and dependency.
- `scanner/api/tests/test_startup.py` — unit tests for the loopback and CORS startup checks.

**Python (modified):**
- `scanner/api/dependencies.py` — add `shared_secret`, enforce prod-required fields on `Settings`.
- `scanner/api/app.py` — register middlewares, add startup loopback check, tighten CORS.

**TypeScript (new):**
- `lib/scanner-client.ts` — `scannerClient.fetch(session, path, init?)` helper.
- `lib/__tests__/scanner-client.test.ts` — unit tests for the client.

**TypeScript (modified):**
- `middleware.ts` — remove `ENABLE_AUTH_MIDDLEWARE` flag.
- All `app/api/**/route.ts` files using `SCANNER_API_URL` or `SCANNER_URL` — swap to `scannerClient.fetch(...)`.

**Config:**
- `.env` and `scanner/.env` — add `SCANNER_SHARED_SECRET`.
- `README.md` — document the new env var.

---

### Task 1: Python settings — add shared secret + prod validation

**Files:**
- Modify: `scanner/api/dependencies.py:38-52`
- Test: `scanner/api/tests/test_startup.py` (new)

- [ ] **Step 1: Write the failing test**

Create `scanner/api/tests/test_startup.py`:
```python
"""Tests for Settings validation at startup."""

import pytest
from unittest.mock import patch

from scanner.api.dependencies import Settings


class TestSettingsProd:
    def test_prod_missing_shared_secret_raises(self):
        with patch.dict("os.environ", {"ENVIRONMENT": "production"}, clear=True):
            with pytest.raises(RuntimeError, match="SCANNER_SHARED_SECRET"):
                Settings()

    def test_prod_short_shared_secret_raises(self):
        env = {"ENVIRONMENT": "production", "SCANNER_SHARED_SECRET": "tooshort", "ALLOWED_ORIGINS": "https://app.example.com"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="SCANNER_SHARED_SECRET.*32"):
                Settings()

    def test_prod_wildcard_origins_raises(self):
        env = {"ENVIRONMENT": "production", "SCANNER_SHARED_SECRET": "a" * 64, "ALLOWED_ORIGINS": "*"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
                Settings()

    def test_prod_unset_origins_raises(self):
        env = {"ENVIRONMENT": "production", "SCANNER_SHARED_SECRET": "a" * 64}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
                Settings()

    def test_prod_valid_config_succeeds(self):
        env = {
            "ENVIRONMENT": "production",
            "SCANNER_SHARED_SECRET": "a" * 64,
            "ALLOWED_ORIGINS": "https://app.example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            s = Settings()
            assert s.shared_secret == "a" * 64
            assert s.allowed_origins == ["https://app.example.com"]

    def test_dev_missing_shared_secret_uses_default(self):
        with patch.dict("os.environ", {"ENVIRONMENT": "development"}, clear=True):
            s = Settings()
            assert s.shared_secret == "dev-insecure-secret-do-not-use-in-production"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scanner && python -m pytest api/tests/test_startup.py -v`
Expected: all FAIL — `Settings` does not yet validate prod or expose `shared_secret`.

- [ ] **Step 3: Implement Settings validation**

Replace `scanner/api/dependencies.py:38-52` with:
```python
class Settings:
    """Application settings from environment variables."""

    DEV_SHARED_SECRET = "dev-insecure-secret-do-not-use-in-production"

    def __init__(self):
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.version = "2.0.0"
        self.encryption_key = os.getenv("ENCRYPTION_KEY", "")

        allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "")
        self.allowed_origins = [o.strip() for o in allowed_origins_raw.split(",") if o.strip()]

        shared_secret_env = os.getenv("SCANNER_SHARED_SECRET", "")

        is_prod = self.environment == "production"

        if is_prod:
            if not shared_secret_env:
                raise RuntimeError(
                    "SCANNER_SHARED_SECRET must be set in production (min 32 bytes)"
                )
            if len(shared_secret_env) < 32:
                raise RuntimeError(
                    "SCANNER_SHARED_SECRET must be at least 32 bytes in production"
                )
            if not self.allowed_origins or self.allowed_origins == ["*"]:
                raise RuntimeError(
                    "ALLOWED_ORIGINS must be an explicit comma-separated list in production (not '*' or empty)"
                )
            self.shared_secret = shared_secret_env
        else:
            self.shared_secret = shared_secret_env or self.DEV_SHARED_SECRET
            if not self.allowed_origins:
                self.allowed_origins = ["*"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scanner && python -m pytest api/tests/test_startup.py -v`
Expected: all PASS.

- [ ] **Step 5: Clear settings cache note**

`get_settings()` is `@lru_cache`'d. Tests that construct `Settings()` directly (as above) are unaffected. No code change needed here.

- [ ] **Step 6: Commit**

```bash
git add scanner/api/dependencies.py scanner/api/tests/test_startup.py
git commit -m "feat(api): validate Settings at startup, require shared secret in prod"
```

---

### Task 2: InternalAuthMiddleware (shared-secret check)

**Files:**
- Create: `scanner/api/auth.py`
- Test: `scanner/api/tests/test_auth.py` (new)

- [ ] **Step 1: Write the failing test**

Create `scanner/api/tests/test_auth.py`:
```python
"""Tests for scanner.api.auth middlewares and dependency."""

import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app_with_auth(shared_secret: str = "a" * 64):
    """Build a minimal FastAPI app with InternalAuthMiddleware registered."""
    env = {
        "ENVIRONMENT": "development",
        "SCANNER_SHARED_SECRET": shared_secret,
    }
    with patch.dict("os.environ", env):
        # Import inside the patched env so Settings sees the right values.
        from scanner.api.dependencies import Settings
        from scanner.api.auth import InternalAuthMiddleware

        app = FastAPI()
        app.add_middleware(InternalAuthMiddleware, settings=Settings())

        @app.get("/api/v1/ping")
        async def ping():
            return {"ok": True}

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        return TestClient(app)


class TestInternalAuthMiddleware:
    SECRET = "a" * 64

    def test_missing_header_returns_401(self):
        client = _app_with_auth(self.SECRET)
        r = client.get("/api/v1/ping")
        assert r.status_code == 401
        assert r.json() == {"error": "unauthorized"}

    def test_wrong_header_returns_401(self):
        client = _app_with_auth(self.SECRET)
        r = client.get("/api/v1/ping", headers={"X-Internal-Auth": "b" * 64})
        assert r.status_code == 401

    def test_correct_header_passes(self):
        client = _app_with_auth(self.SECRET)
        r = client.get("/api/v1/ping", headers={"X-Internal-Auth": self.SECRET})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_health_endpoint_exempt(self):
        """Health checks don't need the secret (for k8s/load-balancer probes)."""
        client = _app_with_auth(self.SECRET)
        r = client.get("/health")
        assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scanner && python -m pytest api/tests/test_auth.py::TestInternalAuthMiddleware -v`
Expected: FAIL — `scanner.api.auth` module does not exist.

- [ ] **Step 3: Implement InternalAuthMiddleware**

Create `scanner/api/auth.py`:
```python
"""Trust-boundary authentication for Next.js ↔ FastAPI.

Implements the trusted-subsystem pattern:
- InternalAuthMiddleware: verifies X-Internal-Auth shared secret (constant-time).
- ActingPrincipalMiddleware: parses X-Acting-User/X-Acting-Org into request.state.principal.
- require_principal: FastAPI dependency for routers.
"""

import hmac
import uuid
from dataclasses import dataclass
from typing import Optional

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = structlog.get_logger()

HEADER_INTERNAL_AUTH = "x-internal-auth"
HEADER_ACTING_USER = "x-acting-user"
HEADER_ACTING_ORG = "x-acting-org"
HEADER_REQUEST_ID = "x-request-id"

# Paths exempt from internal-auth check (liveness/readiness probes).
EXEMPT_PATHS = {"/health", "/healthz", "/docs", "/redoc", "/openapi.json"}


@dataclass(frozen=True)
class ActingPrincipal:
    """Identity of the end user on whose behalf Next.js is calling FastAPI."""
    user_id: str
    organization_id: str
    request_id: str


class InternalAuthMiddleware(BaseHTTPMiddleware):
    """Rejects requests that don't carry the shared secret."""

    def __init__(self, app, settings):
        super().__init__(app)
        self._expected = settings.shared_secret.encode()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in EXEMPT_PATHS:
            return await call_next(request)

        provided = request.headers.get(HEADER_INTERNAL_AUTH, "")
        if not provided or not hmac.compare_digest(provided.encode(), self._expected):
            logger.warning(
                "auth.internal.rejected",
                path=path,
                request_id=request.headers.get(HEADER_REQUEST_ID, "unknown"),
            )
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        return await call_next(request)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scanner && python -m pytest api/tests/test_auth.py::TestInternalAuthMiddleware -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/api/auth.py scanner/api/tests/test_auth.py
git commit -m "feat(api): add InternalAuthMiddleware for trust-boundary auth"
```

---

### Task 3: ActingPrincipalMiddleware + require_principal dependency

**Files:**
- Modify: `scanner/api/auth.py` (append)
- Modify: `scanner/api/tests/test_auth.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `scanner/api/tests/test_auth.py`:
```python
def _app_with_full_stack(shared_secret: str = "a" * 64):
    env = {"ENVIRONMENT": "development", "SCANNER_SHARED_SECRET": shared_secret}
    with patch.dict("os.environ", env):
        from fastapi import Depends
        from scanner.api.dependencies import Settings
        from scanner.api.auth import (
            InternalAuthMiddleware,
            ActingPrincipalMiddleware,
            ActingPrincipal,
            require_principal,
        )

        app = FastAPI()
        settings = Settings()
        app.add_middleware(ActingPrincipalMiddleware)
        app.add_middleware(InternalAuthMiddleware, settings=settings)

        @app.get("/api/v1/whoami")
        async def whoami(principal: ActingPrincipal = Depends(require_principal)):
            return {
                "user_id": principal.user_id,
                "org_id": principal.organization_id,
                "request_id": principal.request_id,
            }

        return TestClient(app)


class TestActingPrincipalMiddleware:
    SECRET = "a" * 64

    def _headers(self, **overrides):
        base = {
            "X-Internal-Auth": self.SECRET,
            "X-Acting-User": "user_123",
            "X-Acting-Org": "org_456",
            "X-Request-Id": "req_789",
        }
        base.update(overrides)
        return base

    def test_all_headers_present_populates_principal(self):
        client = _app_with_full_stack(self.SECRET)
        r = client.get("/api/v1/whoami", headers=self._headers())
        assert r.status_code == 200
        assert r.json() == {"user_id": "user_123", "org_id": "org_456", "request_id": "req_789"}

    def test_missing_acting_user_returns_400(self):
        client = _app_with_full_stack(self.SECRET)
        headers = self._headers()
        del headers["X-Acting-User"]
        r = client.get("/api/v1/whoami", headers=headers)
        assert r.status_code == 400
        assert r.json() == {"error": "missing_principal"}

    def test_missing_acting_org_returns_400(self):
        client = _app_with_full_stack(self.SECRET)
        headers = self._headers()
        del headers["X-Acting-Org"]
        r = client.get("/api/v1/whoami", headers=headers)
        assert r.status_code == 400

    def test_missing_request_id_generates_one(self):
        client = _app_with_full_stack(self.SECRET)
        headers = self._headers()
        del headers["X-Request-Id"]
        r = client.get("/api/v1/whoami", headers=headers)
        assert r.status_code == 200
        assert r.json()["request_id"]  # server-generated
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scanner && python -m pytest api/tests/test_auth.py::TestActingPrincipalMiddleware -v`
Expected: FAIL — `ActingPrincipalMiddleware` and `require_principal` don't exist.

- [ ] **Step 3: Implement ActingPrincipalMiddleware + dependency**

Append to `scanner/api/auth.py`:
```python
class ActingPrincipalMiddleware(BaseHTTPMiddleware):
    """Parses caller identity headers into request.state.principal.

    Runs AFTER InternalAuthMiddleware (added first, Starlette wraps in reverse).
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        user_id = request.headers.get(HEADER_ACTING_USER, "").strip()
        org_id = request.headers.get(HEADER_ACTING_ORG, "").strip()

        if not user_id or not org_id:
            logger.warning(
                "auth.principal.missing",
                path=request.url.path,
                has_user=bool(user_id),
                has_org=bool(org_id),
            )
            return JSONResponse(status_code=400, content={"error": "missing_principal"})

        request_id = request.headers.get(HEADER_REQUEST_ID, "").strip() or f"srv_{uuid.uuid4().hex}"
        request.state.principal = ActingPrincipal(
            user_id=user_id,
            organization_id=org_id,
            request_id=request_id,
        )
        return await call_next(request)


def require_principal(request: Request) -> ActingPrincipal:
    """FastAPI dependency: pull the principal set by ActingPrincipalMiddleware."""
    principal: Optional[ActingPrincipal] = getattr(request.state, "principal", None)
    if principal is None:
        # Should not happen if middleware is registered — fail loudly.
        raise RuntimeError("ActingPrincipalMiddleware is not registered")
    return principal
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scanner && python -m pytest api/tests/test_auth.py -v`
Expected: all PASS (both TestInternalAuthMiddleware and TestActingPrincipalMiddleware).

- [ ] **Step 5: Commit**

```bash
git add scanner/api/auth.py scanner/api/tests/test_auth.py
git commit -m "feat(api): add ActingPrincipalMiddleware + require_principal dependency"
```

---

### Task 4: Loopback-bind startup check

**Files:**
- Modify: `scanner/api/app.py`
- Test: `scanner/api/tests/test_startup.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `scanner/api/tests/test_startup.py`:
```python
class TestLoopbackCheck:
    def test_prod_non_loopback_raises(self):
        from scanner.api.app import enforce_loopback_in_production
        with pytest.raises(RuntimeError, match="loopback"):
            enforce_loopback_in_production(environment="production", host="0.0.0.0")

    def test_prod_loopback_v4_passes(self):
        from scanner.api.app import enforce_loopback_in_production
        enforce_loopback_in_production(environment="production", host="127.0.0.1")  # no raise

    def test_prod_loopback_v6_passes(self):
        from scanner.api.app import enforce_loopback_in_production
        enforce_loopback_in_production(environment="production", host="::1")

    def test_dev_non_loopback_allowed(self):
        from scanner.api.app import enforce_loopback_in_production
        enforce_loopback_in_production(environment="development", host="0.0.0.0")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scanner && python -m pytest api/tests/test_startup.py::TestLoopbackCheck -v`
Expected: FAIL — `enforce_loopback_in_production` does not exist.

- [ ] **Step 3: Implement the check**

Add to `scanner/api/app.py` (before `create_app`, after the imports):
```python
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def enforce_loopback_in_production(environment: str, host: str) -> None:
    """Exit loudly if FastAPI is bound to a non-loopback interface in production.

    Called from create_app() when ENVIRONMENT=production. Host is read from
    the HOST env var, which is what uvicorn/gunicorn conventionally set.
    """
    if environment != "production":
        return
    if host not in _LOOPBACK_HOSTS:
        raise RuntimeError(
            f"startup.loopback_violation: FastAPI must bind to loopback in production, got host={host!r}"
        )
```

Then in `create_app()`, right after `settings = get_settings()`:
```python
    # Refuse to boot on non-loopback in production.
    enforce_loopback_in_production(
        environment=settings.environment,
        host=os.getenv("HOST", "127.0.0.1"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scanner && python -m pytest api/tests/test_startup.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/api/app.py scanner/api/tests/test_startup.py
git commit -m "feat(api): refuse non-loopback bind in production"
```

---

### Task 5: Wire middlewares and tighten CORS in app.py

**Files:**
- Modify: `scanner/api/app.py:42-49`

- [ ] **Step 1: Modify app.py to register middlewares**

Replace the CORS block in `scanner/api/app.py:42-49` with:
```python
    # Register auth middlewares FIRST — ordering note:
    # Starlette applies middlewares in reverse registration order, so the
    # add_middleware call made LAST runs FIRST on inbound requests.
    # We want: InternalAuth (outer) → ActingPrincipal (inner) → CORS → app.
    from .auth import InternalAuthMiddleware, ActingPrincipalMiddleware

    # CORS Middleware — explicit origins only in prod (enforced by Settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Internal-Auth",
            "X-Acting-User",
            "X-Acting-Org",
            "X-Request-Id",
        ],
    )
    app.add_middleware(ActingPrincipalMiddleware)
    app.add_middleware(InternalAuthMiddleware, settings=settings)
```

- [ ] **Step 2: Add integration test for the full app stack**

Append to `scanner/api/tests/test_auth.py`:
```python
class TestFullAppStack:
    SECRET = "a" * 64

    def test_health_endpoint_accessible_without_headers(self):
        env = {"ENVIRONMENT": "development", "SCANNER_SHARED_SECRET": self.SECRET}
        with patch.dict("os.environ", env):
            # Force re-import so get_settings cache picks up env
            from scanner.api.dependencies import get_settings
            get_settings.cache_clear()
            from scanner.api.app import create_app
            app = create_app()
            client = TestClient(app)
            r = client.get("/health")
            assert r.status_code == 200

    def test_api_endpoint_rejected_without_secret(self):
        env = {"ENVIRONMENT": "development", "SCANNER_SHARED_SECRET": self.SECRET}
        with patch.dict("os.environ", env):
            from scanner.api.dependencies import get_settings
            get_settings.cache_clear()
            from scanner.api.app import create_app
            app = create_app()
            client = TestClient(app)
            r = client.get("/api/v1/drivers")
            assert r.status_code == 401
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd scanner && python -m pytest api/tests/test_auth.py::TestFullAppStack -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scanner/api/app.py scanner/api/tests/test_auth.py
git commit -m "feat(api): wire auth middlewares and tighten CORS headers"
```

---

### Task 6: Next.js scannerClient helper

**Files:**
- Create: `lib/scanner-client.ts`
- Test: `lib/__tests__/scanner-client.test.ts` (new)

- [ ] **Step 1: Write the failing test**

Create `lib/__tests__/scanner-client.test.ts`:
```typescript
import { scannerClient } from '@/lib/scanner-client';

describe('scannerClient.fetch', () => {
  const realFetch = global.fetch;

  beforeEach(() => {
    process.env.SCANNER_API_URL = 'http://127.0.0.1:8000';
    process.env.SCANNER_SHARED_SECRET = 'test-secret-64-bytes-' + 'x'.repeat(44);
    global.fetch = jest.fn(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    ) as jest.Mock;
  });

  afterEach(() => {
    global.fetch = realFetch;
  });

  const session = {
    user: { id: 'user_123', organizationId: 'org_456', email: 'x@y.z', name: 'X', image: null },
    expires: '2099-01-01',
  } as any;

  it('injects all three headers on every call', async () => {
    await scannerClient.fetch(session, '/api/v1/ping');
    const call = (global.fetch as jest.Mock).mock.calls[0];
    const [url, init] = call;
    expect(url).toBe('http://127.0.0.1:8000/api/v1/ping');
    expect(init.headers['X-Internal-Auth']).toBe(process.env.SCANNER_SHARED_SECRET);
    expect(init.headers['X-Acting-User']).toBe('user_123');
    expect(init.headers['X-Acting-Org']).toBe('org_456');
    expect(init.headers['X-Request-Id']).toMatch(/^[0-9a-f-]+$/);
  });

  it('preserves caller-provided headers', async () => {
    await scannerClient.fetch(session, '/api/v1/ping', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ foo: 1 }),
    });
    const [, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(init.method).toBe('POST');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.headers['X-Internal-Auth']).toBeDefined();
  });

  it('throws if session has no user id', async () => {
    const badSession = { user: { organizationId: 'org_456' }, expires: '2099-01-01' } as any;
    await expect(scannerClient.fetch(badSession, '/api/v1/ping')).rejects.toThrow(/user id/i);
  });

  it('throws if session has no organizationId', async () => {
    const badSession = { user: { id: 'user_123' }, expires: '2099-01-01' } as any;
    await expect(scannerClient.fetch(badSession, '/api/v1/ping')).rejects.toThrow(/organization/i);
  });

  it('throws if SCANNER_SHARED_SECRET is not set', async () => {
    delete process.env.SCANNER_SHARED_SECRET;
    await expect(scannerClient.fetch(session, '/api/v1/ping')).rejects.toThrow(/SCANNER_SHARED_SECRET/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx jest lib/__tests__/scanner-client.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement scannerClient**

Create `lib/scanner-client.ts`:
```typescript
import type { Session } from 'next-auth';
import { randomUUID } from 'crypto';

function getBaseUrl(): string {
  return process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';
}

function getSharedSecret(): string {
  const secret = process.env.SCANNER_SHARED_SECRET;
  if (!secret) {
    throw new Error(
      'SCANNER_SHARED_SECRET is not set. Add it to .env — generate with: openssl rand -hex 32'
    );
  }
  return secret;
}

function extractPrincipal(session: Session): { userId: string; orgId: string } {
  const userId = (session.user as any)?.id as string | undefined;
  const orgId = (session.user as any)?.organizationId as string | undefined;
  if (!userId) {
    throw new Error('scannerClient.fetch: session is missing user id');
  }
  if (!orgId) {
    throw new Error('scannerClient.fetch: session is missing organization id');
  }
  return { userId, orgId };
}

export const scannerClient = {
  async fetch(session: Session, path: string, init: RequestInit = {}): Promise<Response> {
    const { userId, orgId } = extractPrincipal(session);
    const secret = getSharedSecret();

    const url = `${getBaseUrl()}${path}`;

    const headers: Record<string, string> = {
      ...(init.headers as Record<string, string> | undefined),
      'X-Internal-Auth': secret,
      'X-Acting-User': userId,
      'X-Acting-Org': orgId,
      'X-Request-Id': randomUUID(),
    };

    return fetch(url, { ...init, headers });
  },
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx jest lib/__tests__/scanner-client.test.ts`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/scanner-client.ts lib/__tests__/scanner-client.test.ts
git commit -m "feat(lib): add scannerClient helper for Next.js → FastAPI calls"
```

---

### Task 7: Migrate Next.js API routes to scannerClient

This is a mechanical refactor across ~20 files. Do it in batches; each batch is one commit.

**Enumerate the targets:**

- [ ] **Step 1: List all files to change**

Run:
```bash
grep -rEl 'SCANNER_API_URL|SCANNER_URL' app/api --include='*.ts'
```
Expected output: a list of ~20 files. Paste into a scratch pad and work through them in batches of 5.

- [ ] **Step 2: Migrate one file as a template — `app/api/copilot/chat/route.ts`**

In `app/api/copilot/chat/route.ts`:

Delete line 7: `const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';`

Add at top: `import { scannerClient } from '@/lib/scanner-client';`

Find every `fetch(\`${SCANNER_API_URL}/...\`, { ... })` call and replace with:
```typescript
scannerClient.fetch(session, '/...', { ... })
```

Remove `headers: { 'Content-Type': 'application/json' }` duplication if present — `scannerClient` doesn't force it, but POST bodies still need it. Keep content-type, strip any hand-rolled auth or internal-header attempts.

- [ ] **Step 3: Run type-check**

Run: `npx tsc --noEmit`
Expected: zero errors from the modified file.

- [ ] **Step 4: Commit the template migration**

```bash
git add app/api/copilot/chat/route.ts
git commit -m "refactor(api): migrate copilot chat route to scannerClient"
```

- [ ] **Step 5: Migrate remaining routes in batches**

For each remaining file from Step 1:

1. Add `import { scannerClient } from '@/lib/scanner-client';` if not present.
2. Remove the `SCANNER_API_URL` / `SCANNER_URL` constant.
3. Ensure the route handler has `const session = await auth(); if (!session?.user) return 401;` at the top — if it doesn't already, add it. **This is defense in depth; some routes may not currently authenticate.** Flag any route where authenticating changes behavior (e.g., public-looking endpoints).
4. Replace every `fetch(\`${SCANNER_...}/...\`, init)` with `scannerClient.fetch(session, '/...', init)`.
5. Fix the `:8080` typo in `app/api/pipeline/scan/route.ts:11` — it becomes 8000 via `SCANNER_API_URL`.

Commit in batches of 5:
```bash
git add app/api/<batch>
git commit -m "refactor(api): migrate <area> routes to scannerClient (N/M)"
```

- [ ] **Step 6: Final grep check**

Run:
```bash
grep -rE 'SCANNER_API_URL|SCANNER_URL' app/api --include='*.ts'
```
Expected: zero matches. If any remain, finish them.

- [ ] **Step 7: Run type-check on whole project**

Run: `npx tsc --noEmit`
Expected: zero errors.

---

### Task 8: Remove ENABLE_AUTH_MIDDLEWARE flag

**Files:**
- Modify: `middleware.ts:11-13`

- [ ] **Step 1: Remove the bypass**

In `middleware.ts`, delete lines 11-13:
```typescript
  if (process.env.ENABLE_AUTH_MIDDLEWARE !== 'true') {
    return NextResponse.next();
  }
```

The final `middleware.ts` should be:
```typescript
import { auth } from '@/auth';
import { NextResponse } from 'next/server';

export default auth((req) => {
  const isLoggedIn = !!req.auth;
  const isAuthPage = req.nextUrl.pathname.startsWith('/login') ||
                     req.nextUrl.pathname.startsWith('/signup');
  const isDashboard = req.nextUrl.pathname.startsWith('/dashboard');
  const isOnboarding = req.nextUrl.pathname.startsWith('/onboarding');

  if (isLoggedIn && isAuthPage) {
    return NextResponse.redirect(new URL('/dashboard', req.nextUrl));
  }

  if (!isLoggedIn && (isDashboard || isOnboarding)) {
    return NextResponse.redirect(new URL('/login', req.nextUrl));
  }

  return NextResponse.next();
});

export const config = {
  matcher: ['/dashboard/:path*', '/onboarding/:path*', '/login', '/signup'],
};
```

- [ ] **Step 2: Grep for stale references**

Run:
```bash
grep -rE 'ENABLE_AUTH_MIDDLEWARE' . --include='*.ts' --include='*.tsx' --include='*.md' --include='.env*'
```
Expected: zero matches outside `.env` files (scrub `.env`/`scanner/.env`/`.env.example` if they mention it).

- [ ] **Step 3: Commit**

```bash
git add middleware.ts
git commit -m "feat(auth): make middleware always-on (remove ENABLE_AUTH_MIDDLEWARE flag)"
```

---

### Task 9: Update .env files and README

**Files:**
- Modify: `.env`, `scanner/.env`, `README.md`

- [ ] **Step 1: Generate a dev shared secret**

Run: `openssl rand -hex 32`
Copy the output — it's a 64-char hex string.

- [ ] **Step 2: Add to `.env` and `scanner/.env`**

Append to both `.env` and `scanner/.env`:
```
# Shared secret between Next.js and FastAPI (min 32 bytes in prod).
# Generate with: openssl rand -hex 32
SCANNER_SHARED_SECRET=<paste value from Step 1>
```

If `.env.example` exists, add the same line (without a real value) for documentation.

- [ ] **Step 3: Document in README**

Locate the env var documentation section in `README.md` (near line 39 based on earlier grep).

Add entry:
```markdown
| `SCANNER_SHARED_SECRET` | Shared secret for the Next.js ↔ FastAPI trust boundary. Generate with `openssl rand -hex 32`. Required (min 32 bytes) in production; a dev default is used otherwise. |
```

Also add a "Security" subsection:
```markdown
### Security

FastAPI (`scanner/`) accepts requests only from Next.js, authenticated via the
`X-Internal-Auth: $SCANNER_SHARED_SECRET` header. FastAPI also binds to
loopback (`127.0.0.1`) in production and refuses to start on a non-loopback
interface. To call FastAPI directly during development (e.g., with curl):

    curl -H "X-Internal-Auth: $SCANNER_SHARED_SECRET" \
         -H "X-Acting-User: $YOUR_USER_ID" \
         -H "X-Acting-Org: $YOUR_ORG_ID" \
         http://127.0.0.1:8000/api/v1/drivers
```

- [ ] **Step 4: Commit**

```bash
git add .env scanner/.env README.md
# Include .env.example if you modified it; do NOT git add real secrets if these files are gitignored.
git commit -m "docs: document SCANNER_SHARED_SECRET and trust-boundary setup"
```

**Note:** Check `.gitignore` first — if `.env` is gitignored (likely), only stage `README.md` and `.env.example`. Do not commit real secrets.

---

### Task 10: Manual end-to-end verification

**No code changes. Run through this checklist before claiming done.**

- [ ] **Step 1: Start FastAPI**

Run: `cd scanner && source venv/bin/activate && uvicorn api.app:app --host 127.0.0.1 --port 8000`
Expected: Starts cleanly. No "loopback_violation" error.

- [ ] **Step 2: Confirm loopback-only binding**

Run: `lsof -iTCP:8000 -sTCP:LISTEN`
Expected: address shows `127.0.0.1:8000` (not `*:8000` or `0.0.0.0:8000`).

- [ ] **Step 3: Call FastAPI without secret → expect 401**

Run: `curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/drivers`
Expected: `401`.

- [ ] **Step 4: Call with correct secret → expect 400 (missing principal)**

Run: `curl -sS -o /dev/null -w "%{http_code}\n" -H "X-Internal-Auth: $SCANNER_SHARED_SECRET" http://127.0.0.1:8000/api/v1/drivers`
Expected: `400` — auth passed, but the acting-user/org headers are missing. This proves layered enforcement.

- [ ] **Step 5: Call with all headers → expect 200**

Run:
```bash
curl -sS -o /dev/null -w "%{http_code}\n" \
  -H "X-Internal-Auth: $SCANNER_SHARED_SECRET" \
  -H "X-Acting-User: test_user" \
  -H "X-Acting-Org: test_org" \
  http://127.0.0.1:8000/api/v1/drivers
```
Expected: `200`.

- [ ] **Step 6: Health endpoint open**

Run: `curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health`
Expected: `200` without any headers.

- [ ] **Step 7: Start Next.js, test middleware**

Run: `npm run dev` (in another terminal).
Open incognito browser → `http://localhost:3000/dashboard`.
Expected: redirected to `/login`.

- [ ] **Step 8: Log in, use the copilot end-to-end**

Sign in. Open copilot. Send a message. Confirm a response comes back.
Expected: works. If broken, check the browser devtools network tab for 401s from Next.js API routes — likely means a route didn't migrate correctly in Task 7.

- [ ] **Step 9: Run full test suites**

```bash
cd scanner && python -m pytest -q
```
```bash
npx jest
```
Expected: all green.

- [ ] **Step 10: Final commit (if anything changed during verification)**

If no code changes, skip. Otherwise:
```bash
git add <files>
git commit -m "fix: resolve issues found in trust-boundary verification"
```

---

## Rollback

Single `git revert` on each feature commit, or `git revert` the merge commit if this becomes a branch. No data migrations, no schema changes, no external service coordination.

## Done criteria

- [ ] All tasks above checked off.
- [ ] Python and Jest test suites pass.
- [ ] Manual verification (Task 10) passes.
- [ ] `grep -rE 'SCANNER_API_URL|SCANNER_URL' app/api --include='*.ts'` returns zero.
- [ ] `grep -rE 'ENABLE_AUTH_MIDDLEWARE' .` returns zero outside `.env` files.
- [ ] FastAPI binds only to loopback in production.
