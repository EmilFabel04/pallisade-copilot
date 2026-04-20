# Spec 1a — Next.js ↔ FastAPI Trust Boundary + Mandatory Auth Middleware

**Date:** 2026-04-20
**Status:** Design — awaiting implementation plan
**Scope:** First of five security-hardening specs. Closes the P0 gap that FastAPI is unauthenticated and that the Next.js auth middleware is disabled by default.
**Deployment target:** Single VM / container (shape A). Next.js and FastAPI co-located; FastAPI bound to loopback.
**Tenancy:** Multi-tenant (many orgs share one deployment).

## Why this spec exists

Two observations during the baseline scan drove this work:

1. `middleware.ts:11` short-circuits when `ENABLE_AUTH_MIDDLEWARE !== 'true'`. If the env var is unset, `/dashboard/*` and `/onboarding/*` are reachable without a session. Today this is the default.
2. `scanner/api/app.py` registers routers with no authentication. Any process that can reach `127.0.0.1:8000` can call `/api/v1/copilot/chat`, query warehouses, trigger schedules, read lineage. On a single-VM deployment this includes any other user-space process on the host.

Both are P0 the moment Pallisade leaves localhost.

## Threat model

| # | Threat | Today | After this spec |
|---|---|---|---|
| T1 | Attacker reaches `/dashboard/*` without a session | Possible if `ENABLE_AUTH_MIDDLEWARE` is unset (current default) | Middleware always-on; flag removed |
| T2 | Process on the deployment host calls FastAPI directly, bypassing Next.js auth | Trivial — `curl 127.0.0.1:8000/api/v1/copilot/chat` works | Rejected by shared-secret middleware |
| T3 | FastAPI binds to `0.0.0.0` in prod by mistake and becomes internet-reachable | Possible if the launch command is wrong | FastAPI refuses to boot on non-loopback in prod |
| T4 | Cross-origin site POSTs to FastAPI with credentials | CORS defaults to `*` + `allow_credentials=True` | CORS pinned to Next.js origin; fail-closed if unset in prod |
| T5 | FastAPI-side code cannot attribute a request to a user/org (blocks spec 1b authz work) | No caller identity propagates from Next.js | Every inbound request carries `userId` + `orgId` in trusted headers |

### Out of scope (handled in later specs)

- Per-pipeline authorization checks (`pipelineAccess` enforcement) — **spec 1b**
- CSRF on Next.js API routes, rate limiting — **spec 7**
- LLM data exfiltration controls, audit logging — **spec 5**
- Dependency audit — **spec 6**
- Secrets at rest (warehouse creds, LLM keys) — **spec 2**

### Residual risks accepted

- **Shared-secret compromise**: if the secret leaks, the backend is open to any attacker who can reach the loopback. Mitigation is rotation (env var change + restart). Acceptable given the deployment shape.
- **Identity spoofing if loopback is compromised**: because FastAPI trusts the `X-Acting-User`/`X-Acting-Org` headers, any code running on the host that also has the secret can impersonate any user. This is the "trusted subsystem" tradeoff and is fine for shape A.

## Architecture

```
Browser ──► Next.js (app/)
              ├─ NextAuth session (JWT cookie, SameSite=lax)
              ├─ middleware.ts: always-on route guard
              └─ app/api/**: authed handlers
                    │
                    ▼ loopback only
              FastAPI (scanner/api/app.py)
              ├─ startup check: refuse non-loopback bind in prod
              ├─ InternalAuthMiddleware: verify X-Internal-Auth
              ├─ ActingPrincipalMiddleware: parse X-Acting-* → request.state.principal
              └─ routers/**: read principal via Depends(require_principal)
```

**Contract:** FastAPI never authenticates end users directly. It trusts Next.js to assert identity via headers, and trusts that assertion *only because* the shared secret proves the caller is Next.js. This is the trusted-subsystem pattern.

## Components

### New files

**`scanner/api/auth.py`**
- `SCANNER_SHARED_SECRET` — env var, minimum 32 bytes. Validated at startup. Refuse to boot if missing in production.
- `InternalAuthMiddleware` — ASGI middleware. Constant-time compare on `X-Internal-Auth`. Reject with 401 and structured log `auth.internal.rejected` on mismatch. Health endpoint (`/health`) is exempt.
- `ActingPrincipal` — dataclass: `user_id: str`, `organization_id: str`, `request_id: str`.
- `ActingPrincipalMiddleware` — reads `X-Acting-User`, `X-Acting-Org`, `X-Request-Id` into `request.state.principal`. Missing headers → 400 (fail closed).
- `require_principal()` — FastAPI dependency routers use as: `principal: ActingPrincipal = Depends(require_principal)`.

**`lib/scanner-client.ts`**
- `scannerClient.fetch(session, path, init?)` — takes a `Session` explicitly (no hidden globals), resolves the base URL from a single `SCANNER_API_URL` env var, injects all three headers on every call.
- Throws if `session.user.id` or `session.user.organizationId` missing — routes must authenticate before calling.
- Replaces the ~20 ad-hoc `SCANNER_API_URL` / `SCANNER_URL` constants scattered across `app/api/**`, which also fixes the pre-existing `:8080` typo in `app/api/pipeline/scan/route.ts:11`.

### Modified files

**`middleware.ts`**
- Remove `ENABLE_AUTH_MIDDLEWARE` flag check. Middleware is always on.
- Matcher unchanged.

**`scanner/api/app.py`**
- Register `InternalAuthMiddleware` and `ActingPrincipalMiddleware` in order, before the existing request-logging middleware.
- Add startup check: if `ENVIRONMENT=production` and bind host is not `127.0.0.1`/`::1`, log `startup.loopback_violation` and `sys.exit(1)`.
- Tighten CORS: `ALLOWED_ORIGINS` must be explicit (no default `*`) in production. Startup fails if unset.

**`scanner/api/dependencies.py`**
- `Settings.__init__`: if `environment == "production"` and `allowed_origins == ["*"]` (or unset), raise at startup.
- Add `shared_secret` field, same prod-required behavior.

**All `app/api/**/route.ts` callers** (mechanical refactor)
- Swap hand-rolled `fetch(\`${SCANNER_API_URL}/...\`)` calls to `scannerClient.fetch(session, '/...')`. Typed session requirement forces callers to `await auth()` first.

## Data flow

### Typical request (copilot chat)

1. Browser → `POST /api/copilot/chat` with session cookie.
2. Next.js middleware verifies session.
3. Route handler calls `const session = await auth()`; rejects 401 if null.
4. Handler calls `scannerClient.fetch(session, '/api/v1/copilot/chat', { method: 'POST', body })`.
5. Client injects `X-Internal-Auth: <secret>`, `X-Acting-User: <userId>`, `X-Acting-Org: <orgId>`, `X-Request-Id: <uuid>`.
6. FastAPI `InternalAuthMiddleware` verifies secret (fail → 401, log, return).
7. FastAPI `ActingPrincipalMiddleware` populates `request.state.principal`.
8. Router reads principal via `Depends(require_principal)`. All downstream code has identity.

### Failure modes

| Condition | Response | Log |
|---|---|---|
| Missing or wrong `X-Internal-Auth` | 401 `{"error":"unauthorized"}` | `auth.internal.rejected` with `X-Request-Id` |
| Missing `X-Acting-User` or `X-Acting-Org` | 400 `{"error":"missing_principal"}` | `auth.principal.missing` |
| `ENVIRONMENT=production` + non-loopback bind | `sys.exit(1)` at startup | `startup.loopback_violation` |
| `ENVIRONMENT=production` + `ALLOWED_ORIGINS` unset | Startup raises | `startup.cors_unconfigured` |
| `ENVIRONMENT=production` + `SCANNER_SHARED_SECRET` unset or <32 bytes | Startup raises | `startup.shared_secret_invalid` |

## Testing

### Unit

- `InternalAuthMiddleware`:
  - correct secret → passes
  - wrong secret → 401
  - missing header → 401
  - implementation uses `hmac.compare_digest` for constant-time comparison (asserted by code review, not a runtime test)
- `ActingPrincipalMiddleware`:
  - all headers present → `request.state.principal` populated
  - missing `X-Acting-User` → 400
  - missing `X-Acting-Org` → 400
  - missing `X-Request-Id` → generated server-side (not fatal)
- Startup checks:
  - `ENVIRONMENT=production` + `HOST=0.0.0.0` → exits
  - `ENVIRONMENT=development` + `HOST=0.0.0.0` → allowed
  - `ENVIRONMENT=production` + `ALLOWED_ORIGINS` unset → raises
  - `ENVIRONMENT=production` + secret <32 bytes → raises
- `scannerClient.fetch`:
  - injects all three headers
  - throws if session missing `user.id` or `user.organizationId`
  - uses single `SCANNER_API_URL` env var

### Integration

- Spin up FastAPI in-process. Call `/api/v1/health` without secret → 401.
- Same call with correct secret → 200.
- Next.js route calls `scannerClient.fetch` → FastAPI router sees populated `principal`.
- Hit Next.js `/dashboard` without session cookie → 302 to `/login`.
- Hit Next.js `/dashboard` with session cookie → 200.

### Manual verification (at end of implementation, before merge)

1. Start both services: `npm run dev` + `cd scanner && uvicorn api.app:app`.
2. `lsof -i :8000` — confirm FastAPI bound to `127.0.0.1` only.
3. `curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/health` → `401`.
4. `curl -sS -o /dev/null -w "%{http_code}\n" -H "X-Internal-Auth: $SCANNER_SHARED_SECRET" http://127.0.0.1:8000/api/v1/health` → `200`.
5. Browse `http://localhost:3000/dashboard` in incognito without logging in → redirected to `/login`.
6. Log in, hit copilot → end-to-end works.

## Migration / rollout

- Generate a shared secret: `openssl rand -hex 32`. Add to `.env` and `scanner/.env` under `SCANNER_SHARED_SECRET`.
- One-commit change — no feature flag. The `ENABLE_AUTH_MIDDLEWARE` escape hatch goes away; no one should have relied on it anyway since it was a dev oversight.
- Rollback plan: revert the commit; auth reverts to previous state.

## Open questions

None. All design decisions are resolved above.

## Follow-on specs (not this spec)

- **1b** — Per-pipeline authorization: routers use `principal` to check `pipelineAccess` for every `stackId`-scoped endpoint.
- **5** — Copilot data-exfiltration controls and audit logging (builds on principal being available).
- **6** — Dependency audit and lockfile hygiene.
- **7** — Transport headers (CSP/HSTS), rate limiting, CSRF on Next.js API routes.
- **2** — Secrets at rest (warehouse credentials, LLM keys) — encryption and key rotation.
