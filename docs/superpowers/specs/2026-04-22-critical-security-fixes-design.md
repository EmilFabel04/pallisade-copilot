# Spec A — Critical Security Fixes

**Date:** 2026-04-22
**Branch:** `elementary`
**Follows:** `2026-04-20-fastapi-trust-boundary-design.md` (trust boundary + `require_principal`)

## Goal

Close the three critical-severity security issues surfaced by the post-trust-boundary audit:

1. `next@15.5.3` has a known RCE (GHSA-9qr9-h5gf-34mp) in the React flight protocol plus a Source Code Exposure issue. Patched in `next@15.5.15+`.
2. Transitive `handlebars@4.0.0-4.7.8` has multiple JavaScript injection and prototype pollution advisories. Pulled in via `next-mdx-remote@5`.
3. `scanner/api/routers/copilot.py` has 9 endpoints that read `X-Organization-Id` from a client-controlled request header instead of using the `require_principal` dependency introduced by the trust-boundary work. An attacker with a valid `SCANNER_SHARED_SECRET` can set any org id and access that org's copilot sessions, conversation history, and pipeline metadata.

These are the criticals only. Rate limiting, SSRF hardening, NextAuth cookie-flag tightening, and the same org-id pattern in `schedule.py` / `policies.py` are deferred to follow-up specs (B and C).

## Non-goals

- Per-resource authorization beyond org-level scoping. If the principal's org id passes, existing logic stands.
- Rewriting `schedule.py` or `policies.py` (same bug class, lower exposure, separate spec).
- Rate limiting, CSP hardening, audit logging, dependency-audit CI — all out of scope.
- Python dependency audit. Node only here.

## Tech stack

- `npm` for dependency upgrades.
- FastAPI + Starlette (`Depends(require_principal)` already wired).
- pytest + FastAPI TestClient.

## Architecture

Nothing new. Spec A consumes the trust-boundary primitives that already exist:

- `scanner/api/auth.py::require_principal` returns the `ActingPrincipal` (`user_id`, `organization_id`, `request_id`) that `ActingPrincipalMiddleware` populated from the `X-Acting-User` / `X-Acting-Org` headers that `scannerClient.fetch` sets.
- After this spec, `copilot.py` uses `principal.organization_id` everywhere it used `x_organization_id`. The client-supplied `X-Organization-Id` header is no longer read on the FastAPI side.

## Scope and file list

### Workstream 1 — Node dependency upgrades

**Modified:**
- `package.json` — `next` bumped via `npm audit fix`; if needed, `next-mdx-remote` bumped 5 → 6 or `overrides` added to patch `handlebars`.
- `package-lock.json` — regenerated.

**Verification:**
- `npm audit --audit-level=critical` returns zero criticals.
- `npm run build` succeeds.
- `/docs` renders (MDX integrity check).
- `/dashboard/assistant` chat still works (smoke test for Next.js upgrade).

### Workstream 2 — `copilot.py` migration to `require_principal`

**Modified:**
- `scanner/api/routers/copilot.py` — 9 endpoint signatures changed; 6 call-site usages of `x_organization_id` (at lines 198, 319, 452, 478, 502, 683) renamed to `principal.organization_id`; `Header` import scrubbed if no longer used. Note that 4 of the 9 endpoint signatures (lines 546, 698, 714, 728) declare the header but do not use it inside the body — these can drop the parameter entirely instead of adding a principal dep.
- `app/api/copilot/chat/route.ts` — drop the `'X-Organization-Id': user.organizationId` header from both POST calls (non-streaming and streaming). `scannerClient.fetch` already sets `X-Acting-Org`, so the old header is dead weight.

**New tests:**
- `scanner/api/tests/test_copilot_auth.py` — one parametrized test that asserts each of the 9 endpoints:
  - Rejects with 400 when `X-Acting-Org` is missing (via the principal middleware).
  - Uses `principal.organization_id`, not any `X-Organization-Id` header, when building context. Verified by sending `X-Acting-Org: org_A` and `X-Organization-Id: org_B` and asserting the downstream context is built against `org_A`.

### Out of scope for this spec (but tracked)

- `scanner/api/routers/schedule.py` — takes `organization_id` in the request body.
- `scanner/api/routers/policies.py` — takes `organizationId` in query parameters.

Both get a follow-up spec that applies the same pattern. Keeping them here would double the review surface for no critical-severity gain.

## Error handling

- `Depends(require_principal)` raises `RuntimeError` if the middleware isn't registered. The middleware is registered in `scanner/api/app.py::create_app()` already. If that ever regresses, the server fails loudly at first request — acceptable.
- `ActingPrincipalMiddleware` already returns 400 `{"error": "missing_principal"}` when headers are missing. Existing behavior; no change.

## Testing strategy

- Unit tests for each copilot endpoint: header-spoof rejection + principal-wins-when-both-headers-sent.
- Existing `api/tests/test_auth.py::TestFullAppStack` keeps passing (no change needed).
- Manual: start FastAPI, `curl` each of the 9 endpoints with `X-Acting-Org: fake_org` and verify response reflects `fake_org`, not any header the caller passes.
- Frontend smoke: run `npm run build` then `npm run dev`, open copilot, send a message, confirm response.

## Rollback

Each workstream is a small handful of commits. `git revert` any commit cleanly. No DB migrations, no external service coordination. The `X-Organization-Id` header can be restored to `app/api/copilot/chat/route.ts` with a one-line edit if a hot revert of just the FastAPI side is needed.

## Trade-offs / risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `next-mdx-remote@6` breaks docs rendering | Medium — v5→v6 has a compile-time API change | If docs break, keep `next-mdx-remote@5` and use `package.json` `overrides` to force a patched `handlebars` |
| A FastAPI caller outside of `scannerClient` sends `X-Organization-Id` and expects it to be read | Low — all known callers go through `scannerClient` | Grep confirms zero other callers; if one appears, it 400s on missing principal, which is visible not silent |
| `npm audit fix` upgrades peer deps and breaks a build | Low — `15.5.3 → 15.5.15` is a patch bump | CI build + smoke test both gates |

## Threat model delta

| Threat | Before this spec | After |
|---|---|---|
| Attacker exploits Next.js RCE via crafted request | Possible (RCE advisory published) | Patched |
| Attacker with access to `SCANNER_SHARED_SECRET` sends `X-Organization-Id: <victim_org>` and reads copilot sessions | Works | 400 missing_principal; even with acting-org set, it's bound to the calling NextAuth session |
| Attacker uploads crafted MDX/Handlebars template to trigger injection | Possible (Handlebars criticals) | Patched |
| Attacker with a valid NextAuth cookie accesses another org's resources | Still possible if a Next.js route skips the `org === session.org` check | Unchanged — follow-up spec |

The last row is the honest scope boundary: Spec A does not introduce per-resource authz. It removes two paths that don't require session forgery (RCE, header spoof) and patches a template-injection class (Handlebars).
