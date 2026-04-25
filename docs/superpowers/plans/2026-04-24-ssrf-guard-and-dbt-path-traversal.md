# SSRF Guard + dbt Path-Traversal Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 6 SSRF sinks and 1 path-traversal sink on `main` by porting the `assertExternalUrl` guard and the dbt project-root allow-list from `backup/local-security-fixes`, adapted to the current `@/auth` + `scannerClient` + `scanner.api.dependencies` architecture.

**Architecture:**
- TS side: one new file `lib/net/safe-url.ts` exports `assertExternalUrl(raw, policy)`. Every outbound `fetch(userUrl, …)` in the 6 flagged routes becomes `const u = await assertExternalUrl(userUrl, policy); await fetch(u, …)`. If the guard throws, the route returns the same shape it already returns on connect failures (`{ success: false, message|error: … }`) — no new error channels.
- Python side: `scanner/api/routers/dbt.py` gains a `DBT_ALLOWED_PROJECT_ROOTS` env-var allow-list and `_resolve_dbt_core_paths(config) -> (Path | None, err | None)`. Both `dbt/models` and `dbt/test-connection` reject any `manifest_path`/`project_path` outside the allow-list and refuse symlinks that resolve outside it.

**Tech Stack:** TypeScript (Next.js 15), Jest + ts-jest for TS tests (config at `jest.config.ts`), Python 3 + pytest for scanner tests (`scanner/venv`). Node built-ins `node:dns/promises` + `node:net` for IP classification.

---

## File Structure

**New:**
- `lib/net/safe-url.ts` — the guard. Ported verbatim from `backup/local-security-fixes:lib/net/safe-url.ts` (no adaptation needed — zero arch coupling).
- `lib/net/__tests__/safe-url.test.ts` — jest tests. IP-only cases run without network; hostname case mocks `node:dns/promises`.
- `scanner/api/tests/test_dbt_router.py` — pytest tests for `_resolve_dbt_core_paths` using `tmp_path` + `monkeypatch` on `DBT_ALLOWED_PROJECT_ROOTS`.

**Modified:**
- `app/api/integrations/test-connection/route.ts` — wrap Teams `webhookUrl` fetch (line 67) and Jira `siteUrl` fetch (line 154).
- `app/api/pipeline/test-connection/route.ts` — wrap GitLab `host` fetch (line 803) and Airbyte `abHost` fetches (lines 176, 240, 252).
- `app/api/integrations/test/route.ts` — wrap Airflow `baseUrl` fetch in `testAirflow` (line 395).
- `app/api/integrations/[id]/test/route.ts` — wrap both Airflow `baseUrl` fetches in `testAirflow` (lines 323, 329).
- `scanner/api/routers/dbt.py` — replace ad-hoc `find_manifest` + raw `open(manifest_path)` with `_resolve_dbt_core_paths` + `parse_manifest(Path)`. Path-only `Path.open()` instead of `open(str)`. Opaque error messages.

**Files NOT changed (deliberate):**
- `lib/scanner-client.ts` — the `scannerClient` → FastAPI path uses a fixed `SCANNER_API_URL` and shared-secret header. Not user-controlled, not an SSRF vector.
- `app/api/schedule/**` — flagged in initial triage; `request.nextUrl.origin` is self-referential, not user-controlled. Ignore.
- `app/api/integrations/test-connection/route.ts` Databricks case (line 272) — host is user-controlled but out of reported scope. Noted as follow-up in PR description; do not expand scope here.

---

## Task 1: Port the SSRF guard with unit tests

**Files:**
- Create: `lib/net/safe-url.ts`
- Create: `lib/net/__tests__/safe-url.test.ts`

- [ ] **Step 1: Write the failing test file**

Create `lib/net/__tests__/safe-url.test.ts`:

```typescript
import { assertExternalUrl } from '@/lib/net/safe-url';

jest.mock('node:dns/promises', () => ({
  lookup: jest.fn(),
}));

import { lookup } from 'node:dns/promises';
const mockedLookup = lookup as unknown as jest.Mock;

describe('assertExternalUrl', () => {
  beforeEach(() => {
    mockedLookup.mockReset();
    // Default: any hostname resolves to a public IP.
    mockedLookup.mockResolvedValue([{ address: '93.184.216.34', family: 4 }]);
  });

  describe('input validation', () => {
    test.each([
      [null, 'URL is required'],
      [undefined, 'URL is required'],
      ['', 'URL is required'],
      ['not a url', 'Invalid URL'],
    ])('rejects %p', async (raw, msg) => {
      await expect(assertExternalUrl(raw as any)).rejects.toThrow(msg);
    });
  });

  describe('protocol policy', () => {
    test('rejects http:// by default (https-only)', async () => {
      await expect(assertExternalUrl('http://example.com')).rejects.toThrow(
        'Protocol http: not allowed',
      );
    });
    test('rejects file://', async () => {
      await expect(assertExternalUrl('file:///etc/passwd')).rejects.toThrow(
        'Protocol file: not allowed',
      );
    });
    test('allows http:// when policy opts in', async () => {
      await expect(
        assertExternalUrl('http://example.com', {
          allowedProtocols: ['http:', 'https:'],
        }),
      ).resolves.toBeInstanceOf(URL);
    });
  });

  describe('credentials in URL', () => {
    test('rejects userinfo', async () => {
      await expect(
        assertExternalUrl('https://attacker:x@example.com/'),
      ).rejects.toThrow('Credentials in URL are not allowed');
    });
  });

  describe('IPv4 private ranges (no DNS)', () => {
    test.each([
      'https://127.0.0.1/',
      'https://10.0.0.1/',
      'https://172.16.0.1/',
      'https://192.168.1.1/',
      'https://169.254.169.254/', // cloud metadata
      'https://0.0.0.0/',
      'https://100.64.0.1/', // CG-NAT
    ])('rejects %s', async (url) => {
      await expect(assertExternalUrl(url)).rejects.toThrow('Private IP not allowed');
    });
    test('allows public IPv4', async () => {
      await expect(assertExternalUrl('https://8.8.8.8/')).resolves.toBeInstanceOf(URL);
    });
  });

  describe('IPv6 private ranges (no DNS)', () => {
    test.each([
      'https://[::1]/',
      'https://[fe80::1]/',
      'https://[fc00::1]/',
      'https://[::ffff:127.0.0.1]/',
    ])('rejects %s', async (url) => {
      await expect(assertExternalUrl(url)).rejects.toThrow('Private IP not allowed');
    });
  });

  describe('hostname DNS resolution', () => {
    test('rejects when all records are private (DNS rebinding)', async () => {
      mockedLookup.mockResolvedValue([{ address: '169.254.169.254', family: 4 }]);
      await expect(assertExternalUrl('https://rebind.evil.example/')).rejects.toThrow(
        /resolves to private IP/,
      );
    });
    test('rejects when any record is private (dual-stack rebinding)', async () => {
      mockedLookup.mockResolvedValue([
        { address: '93.184.216.34', family: 4 },
        { address: '10.0.0.1', family: 4 },
      ]);
      await expect(assertExternalUrl('https://mixed.evil.example/')).rejects.toThrow(
        /resolves to private IP/,
      );
    });
    test('rejects unresolvable hostname', async () => {
      mockedLookup.mockRejectedValue(new Error('ENOTFOUND'));
      await expect(assertExternalUrl('https://nope.invalid/')).rejects.toThrow(
        'Hostname does not resolve',
      );
    });
    test('accepts public hostname', async () => {
      mockedLookup.mockResolvedValue([{ address: '93.184.216.34', family: 4 }]);
      await expect(assertExternalUrl('https://example.com/')).resolves.toBeInstanceOf(URL);
    });
  });

  describe('host allow-list', () => {
    test('accepts exact match', async () => {
      mockedLookup.mockResolvedValue([{ address: '1.2.3.4', family: 4 }]);
      await expect(
        assertExternalUrl('https://hooks.slack.com/x', {
          allowedHostSuffixes: ['hooks.slack.com'],
        }),
      ).resolves.toBeInstanceOf(URL);
    });
    test('accepts subdomain of suffix', async () => {
      mockedLookup.mockResolvedValue([{ address: '1.2.3.4', family: 4 }]);
      await expect(
        assertExternalUrl('https://api.slack.com/x', {
          allowedHostSuffixes: ['slack.com'],
        }),
      ).resolves.toBeInstanceOf(URL);
    });
    test('rejects off-list host', async () => {
      await expect(
        assertExternalUrl('https://attacker.com/', {
          allowedHostSuffixes: ['slack.com'],
        }),
      ).rejects.toThrow('is not in the allow-list');
    });
    test('rejects host that merely contains the suffix substring', async () => {
      // "evilslack.com" contains "slack.com" as a substring but is not a subdomain.
      await expect(
        assertExternalUrl('https://evilslack.com/', {
          allowedHostSuffixes: ['slack.com'],
        }),
      ).rejects.toThrow('is not in the allow-list');
    });
  });
});
```

- [ ] **Step 2: Run it — should fail (module missing)**

Run: `cd /Users/emilfabel/pallisade-copilot && npx jest lib/net/__tests__/safe-url.test.ts --no-coverage`
Expected: `Cannot find module '@/lib/net/safe-url'` — FAIL for every test.

- [ ] **Step 3: Create the guard**

Write `lib/net/safe-url.ts` **verbatim** from `backup/local-security-fixes`:

```bash
git show backup/local-security-fixes:lib/net/safe-url.ts > /Users/emilfabel/pallisade-copilot/lib/net/safe-url.ts
```

Verify file has the expected exports:

```bash
grep -E "^export" /Users/emilfabel/pallisade-copilot/lib/net/safe-url.ts
```

Expected: `export type UrlPolicy = {` and `export async function assertExternalUrl(`.

- [ ] **Step 4: Run tests — should pass**

Run: `cd /Users/emilfabel/pallisade-copilot && npx jest lib/net/__tests__/safe-url.test.ts --no-coverage`
Expected: all tests green.

- [ ] **Step 5: Type-check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 6: Commit**

```bash
git add lib/net/safe-url.ts lib/net/__tests__/safe-url.test.ts
git commit -m "$(cat <<'EOF'
feat(security): add assertExternalUrl SSRF guard

Ported from backup/local-security-fixes. Blocks private IPv4/IPv6
ranges, cloud-metadata IP, userinfo credentials, non-https protocols
by default, and off-list hosts. DNS-rebind safe: all A/AAAA records
must resolve to public IPs.
EOF
)"
```

---

## Task 2: Wrap Teams webhook fetch

**Files:**
- Modify: `app/api/integrations/test-connection/route.ts` (Teams case, line 67)

- [ ] **Step 1: Read lines 1-10 and 60-90** to confirm current state (imports + Teams case).

Run: `sed -n '1,10p;60,90p' /Users/emilfabel/pallisade-copilot/app/api/integrations/test-connection/route.ts`

Expected first lines:
```
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { decrypt } from '@/lib/crypto';
```

- [ ] **Step 2: Add the import**

Use Edit to change:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { decrypt } from '@/lib/crypto';
```

to:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { decrypt } from '@/lib/crypto';
import { assertExternalUrl } from '@/lib/net/safe-url';
```

- [ ] **Step 3: Wrap the Teams fetch**

Use Edit. Target the block:

```typescript
        try {
          const response = await fetch(webhookUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              '@type': 'MessageCard',
```

Replace with:

```typescript
        try {
          let safeUrl: URL;
          try {
            safeUrl = await assertExternalUrl(webhookUrl);
          } catch (e) {
            return NextResponse.json({
              success: false,
              message: `Invalid Teams webhook URL: ${e instanceof Error ? e.message : 'not allowed'}`,
            });
          }
          const response = await fetch(safeUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              '@type': 'MessageCard',
```

- [ ] **Step 4: Type-check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 5: Commit**

```bash
git add app/api/integrations/test-connection/route.ts
git commit -m "fix(security): guard Teams webhook URL against SSRF"
```

---

## Task 3: Wrap Jira siteUrl fetch

**Files:**
- Modify: `app/api/integrations/test-connection/route.ts` (Jira case, line 154) — same file as Task 2, import already added.

- [ ] **Step 1: Wrap the Jira fetch**

Use Edit. Target:

```typescript
        try {
          const credentials = Buffer.from(`${email}:${apiToken}`).toString('base64');
          const response = await fetch(`${siteUrl}/rest/api/3/myself`, {
            headers: {
              'Authorization': `Basic ${credentials}`,
              'Accept': 'application/json',
            },
          });
```

Replace with:

```typescript
        try {
          let safeUrl: URL;
          try {
            safeUrl = await assertExternalUrl(`${siteUrl}/rest/api/3/myself`);
          } catch (e) {
            return NextResponse.json({
              success: false,
              message: `Invalid Jira site URL: ${e instanceof Error ? e.message : 'not allowed'}`,
            });
          }
          const credentials = Buffer.from(`${email}:${apiToken}`).toString('base64');
          const response = await fetch(safeUrl, {
            headers: {
              'Authorization': `Basic ${credentials}`,
              'Accept': 'application/json',
            },
          });
```

- [ ] **Step 2: Type-check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 3: Commit**

```bash
git add app/api/integrations/test-connection/route.ts
git commit -m "fix(security): guard Jira site URL against SSRF"
```

---

## Task 4: Wrap GitLab host fetch

**Files:**
- Modify: `app/api/pipeline/test-connection/route.ts` (GitLab case, line 803)

- [ ] **Step 1: Add import**

Use Edit. Change:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { scannerClient } from '@/lib/scanner-client';
```

to:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { scannerClient } from '@/lib/scanner-client';
import { assertExternalUrl } from '@/lib/net/safe-url';
```

- [ ] **Step 2: Wrap the GitLab fetch**

Use Edit. Target:

```typescript
          // Test GitLab API with the token
          const glResponse = await fetch(`${host}/api/v4/user`, {
            headers: {
              'PRIVATE-TOKEN': token,
            },
          });
```

Replace with:

```typescript
          // Test GitLab API with the token
          let glUrl: URL;
          try {
            glUrl = await assertExternalUrl(`${host}/api/v4/user`);
          } catch (e) {
            return NextResponse.json({
              success: false,
              message: `Invalid GitLab host: ${e instanceof Error ? e.message : 'not allowed'}`,
            });
          }
          const glResponse = await fetch(glUrl, {
            headers: {
              'PRIVATE-TOKEN': token,
            },
          });
```

- [ ] **Step 3: Type-check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add app/api/pipeline/test-connection/route.ts
git commit -m "fix(security): guard GitLab host URL against SSRF"
```

---

## Task 5: Wrap Airbyte fetches (3 sinks)

**Files:**
- Modify: `app/api/pipeline/test-connection/route.ts` (Airbyte case — lines 176, 240, 252). Import added in Task 4.

The Airbyte case reuses `abHost` across three fetches. Rather than three try/catch blocks, validate once at the top of the case body and reuse the resolved URL base.

- [ ] **Step 1: Validate abHost once, up front**

Use Edit. Target:

```typescript
        let abHost = (config.host || '').replace(/\/+$/, '');
        if (!abHost) {
          return NextResponse.json({ success: false, message: 'Airbyte host URL is required' });
        }

        // Auto-correct common mistake: user enters the dashboard URL instead of the API URL
        if (abHost.includes('cloud.airbyte.com') && !abHost.includes('api.airbyte.com')) {
          abHost = 'https://api.airbyte.com';
        }

        const isCloud = abHost.includes('api.airbyte.com') || abHost.includes('airbyte.com');
```

Replace with:

```typescript
        let abHost = (config.host || '').replace(/\/+$/, '');
        if (!abHost) {
          return NextResponse.json({ success: false, message: 'Airbyte host URL is required' });
        }

        // Auto-correct common mistake: user enters the dashboard URL instead of the API URL
        if (abHost.includes('cloud.airbyte.com') && !abHost.includes('api.airbyte.com')) {
          abHost = 'https://api.airbyte.com';
        }

        const isCloud = abHost.includes('api.airbyte.com') || abHost.includes('airbyte.com');

        // Validate the host once; reuse the normalised origin for every subsequent fetch.
        let abHostSafe: URL;
        try {
          abHostSafe = await assertExternalUrl(abHost);
        } catch (e) {
          return NextResponse.json({
            success: false,
            message: `Invalid Airbyte host: ${e instanceof Error ? e.message : 'not allowed'}`,
          });
        }
        const abHostOrigin = abHostSafe.origin;
```

- [ ] **Step 2: Swap the 3 fetch call-targets to use the validated origin**

Three fetches must move from `${abHost}` to `${abHostOrigin}`:

Use Edit with `replace_all: false` on each:

Change 1 (line ~176):
```typescript
            const tokenRes = await fetch(`${abHost}/v1/applications/token`, {
```
to:
```typescript
            const tokenRes = await fetch(`${abHostOrigin}/v1/applications/token`, {
```

Change 2 (line ~208):
```typescript
            const abUrl = config.workspace_id
              ? `${abHost}/v1/workspaces/${config.workspace_id}`
              : `${abHost}/v1/workspaces`;
```
to:
```typescript
            const abUrl = config.workspace_id
              ? `${abHostOrigin}/v1/workspaces/${config.workspace_id}`
              : `${abHostOrigin}/v1/workspaces`;
```

Change 3 (line ~240):
```typescript
            const healthRes = await fetch(`${abHost}/api/v1/health`, {
```
to:
```typescript
            const healthRes = await fetch(`${abHostOrigin}/api/v1/health`, {
```

Change 4 (line ~252):
```typescript
              const wsRes = await fetch(`${abHost}/api/v1/workspaces/get`, {
```
to:
```typescript
              const wsRes = await fetch(`${abHostOrigin}/api/v1/workspaces/get`, {
```

And the error message on line ~247 referencing `abHost`:
```typescript
              return NextResponse.json({ success: false, message: `Cannot reach Airbyte API at ${abHost}. Make sure this is the Airbyte API URL, not the web UI.` });
```
→ leave `abHost` — it's user-facing display, not a URL target.

- [ ] **Step 3: Type-check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 4: Verify no remaining raw `${abHost}/` fetch targets**

Run: `grep -n "fetch(\`\${abHost}" /Users/emilfabel/pallisade-copilot/app/api/pipeline/test-connection/route.ts`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add app/api/pipeline/test-connection/route.ts
git commit -m "fix(security): guard Airbyte host URL against SSRF"
```

---

## Task 6: Wrap Airflow fetch in `integrations/test/route.ts`

**Files:**
- Modify: `app/api/integrations/test/route.ts` (Airflow case, line 395)

- [ ] **Step 1: Add import**

Use Edit. Change:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';
```

to:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import { auth } from '@/auth';
import { scannerClient } from '@/lib/scanner-client';
import { assertExternalUrl } from '@/lib/net/safe-url';
```

- [ ] **Step 2: Wrap `testAirflow` fetch**

Use Edit. Target:

```typescript
  try {
    const auth = credentials?.username && credentials?.password 
      ? `Basic ${Buffer.from(`${credentials.username}:${credentials.password}`).toString('base64')}`
      : undefined;

    const response = await fetch(`${baseUrl}/api/v1/health`, {
      headers: auth ? { 'Authorization': auth } : {},
    });
```

Replace with:

```typescript
  try {
    let safeUrl: URL;
    try {
      safeUrl = await assertExternalUrl(`${baseUrl}/api/v1/health`);
    } catch (e) {
      return { success: false, error: `Invalid Airflow base URL: ${e instanceof Error ? e.message : 'not allowed'}` };
    }
    const auth = credentials?.username && credentials?.password 
      ? `Basic ${Buffer.from(`${credentials.username}:${credentials.password}`).toString('base64')}`
      : undefined;

    const response = await fetch(safeUrl, {
      headers: auth ? { 'Authorization': auth } : {},
    });
```

- [ ] **Step 3: Type-check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add app/api/integrations/test/route.ts
git commit -m "fix(security): guard Airflow base URL against SSRF (test/route.ts)"
```

---

## Task 7: Wrap Airflow fetches in `integrations/[id]/test/route.ts`

**Files:**
- Modify: `app/api/integrations/[id]/test/route.ts` (Airflow case, lines 323 and 329)

- [ ] **Step 1: Add import**

Use Edit. Change:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { scannerClient } from '@/lib/scanner-client';
```

to:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { scannerClient } from '@/lib/scanner-client';
import { assertExternalUrl } from '@/lib/net/safe-url';
```

- [ ] **Step 2: Validate baseUrl once, wrap both fetches**

Use Edit. Target:

```typescript
  try {
    const auth = username && password 
      ? `Basic ${Buffer.from(`${username}:${password}`).toString('base64')}`
      : undefined;

    const response = await fetch(`${baseUrl}/api/v1/health`, {
      headers: auth ? { 'Authorization': auth } : {},
    });

    if (response.ok) {
      // Fetch DAGs
      const dagsResponse = await fetch(`${baseUrl}/api/v1/dags?limit=100`, {
        headers: auth ? { 'Authorization': auth } : {},
      });
```

Replace with:

```typescript
  try {
    let baseUrlSafe: URL;
    try {
      baseUrlSafe = await assertExternalUrl(baseUrl);
    } catch (e) {
      return { success: false, error: `Invalid Airflow base URL: ${e instanceof Error ? e.message : 'not allowed'}` };
    }
    const baseOrigin = baseUrlSafe.origin;
    const auth = username && password 
      ? `Basic ${Buffer.from(`${username}:${password}`).toString('base64')}`
      : undefined;

    const response = await fetch(`${baseOrigin}/api/v1/health`, {
      headers: auth ? { 'Authorization': auth } : {},
    });

    if (response.ok) {
      // Fetch DAGs
      const dagsResponse = await fetch(`${baseOrigin}/api/v1/dags?limit=100`, {
        headers: auth ? { 'Authorization': auth } : {},
      });
```

Note: the `metadata: { baseUrl }` further down must keep the original `baseUrl` string (user-facing display) — don't change it.

- [ ] **Step 3: Type-check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add app/api/integrations/[id]/test/route.ts
git commit -m "fix(security): guard Airflow base URL against SSRF ([id]/test/route.ts)"
```

---

## Task 8: dbt path-traversal fix

**Files:**
- Modify: `scanner/api/routers/dbt.py`
- Create: `scanner/api/tests/test_dbt_router.py`

- [ ] **Step 1: Write the failing pytest**

Create `scanner/api/tests/test_dbt_router.py`:

```python
"""Path-traversal hardening tests for dbt Core config resolution."""
import json
from pathlib import Path

import pytest

from scanner.api.routers.dbt import _resolve_dbt_core_paths


@pytest.fixture
def allowed_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a dbt project under a tmp allow-listed root with a valid manifest."""
    root = tmp_path / "projects"
    project = root / "warehouse-analytics"
    (project / "target").mkdir(parents=True)
    (project / "target" / "manifest.json").write_text(json.dumps({"nodes": {}, "sources": {}}))
    monkeypatch.setenv("DBT_ALLOWED_PROJECT_ROOTS", str(root))
    return project


def test_rejects_when_allowlist_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DBT_ALLOWED_PROJECT_ROOTS", raising=False)
    manifest, err = _resolve_dbt_core_paths({"project_path": str(tmp_path)})
    assert manifest is None
    assert err is not None
    assert "not enabled" in err.lower()


def test_rejects_path_outside_allowlist(
    allowed_project: Path, tmp_path: Path
) -> None:
    # An attacker-supplied path that sits *next to* the allow-listed root,
    # not under it.
    evil = tmp_path / "not-allowed"
    evil.mkdir()
    manifest, err = _resolve_dbt_core_paths({"project_path": str(evil)})
    assert manifest is None
    assert err is not None


def test_rejects_dotdot_traversal(
    allowed_project: Path, tmp_path: Path
) -> None:
    # Try to escape via ../
    traversal = f"{allowed_project}/../../etc"
    manifest, err = _resolve_dbt_core_paths({"project_path": traversal})
    assert manifest is None
    assert err is not None


def test_rejects_symlink_to_outside(
    allowed_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Replace the valid manifest with a symlink pointing outside the allow-list.
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps({"nodes": {}}))
    manifest_file = allowed_project / "target" / "manifest.json"
    manifest_file.unlink()
    manifest_file.symlink_to(outside)

    manifest, err = _resolve_dbt_core_paths({"project_path": str(allowed_project)})
    assert manifest is None
    assert err is not None


def test_accepts_valid_project(allowed_project: Path) -> None:
    manifest, err = _resolve_dbt_core_paths({"project_path": str(allowed_project)})
    assert err is None
    assert manifest is not None
    assert manifest.name == "manifest.json"
    assert manifest.is_file()


def test_rejects_missing_project_path(allowed_project: Path) -> None:
    manifest, err = _resolve_dbt_core_paths({})
    assert manifest is None
    assert err is not None
```

- [ ] **Step 2: Run tests — should fail (`_resolve_dbt_core_paths` missing)**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && source venv/bin/activate && pytest api/tests/test_dbt_router.py -v`
Expected: `ImportError: cannot import name '_resolve_dbt_core_paths'` → all 6 tests error.

- [ ] **Step 3: Port the hardened dbt router**

Write `scanner/api/routers/dbt.py` **verbatim** from `backup/local-security-fixes`:

```bash
git show backup/local-security-fixes:scanner/api/routers/dbt.py > /Users/emilfabel/pallisade-copilot/scanner/api/routers/dbt.py
```

Verify the new helpers exist:

```bash
grep -nE "_allowed_project_roots|_resolve_dbt_core_paths|DBT_ALLOWED_PROJECT_ROOTS" /Users/emilfabel/pallisade-copilot/scanner/api/routers/dbt.py
```

Expected: hits in `_allowed_project_roots`, `_resolve_dbt_core_paths`, and the env-var read.

- [ ] **Step 4: Run tests — should pass**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && source venv/bin/activate && pytest api/tests/test_dbt_router.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run full scanner test suite (no regressions)**

Run: `cd /Users/emilfabel/pallisade-copilot && npm run test:python -- api/tests/`
Expected: all green (or pre-existing-failures-only; note any un-related failures in the commit body).

- [ ] **Step 6: Commit**

```bash
git add scanner/api/routers/dbt.py scanner/api/tests/test_dbt_router.py
git commit -m "$(cat <<'EOF'
fix(security): harden dbt Core manifest path against traversal

Port _resolve_dbt_core_paths + DBT_ALLOWED_PROJECT_ROOTS allow-list
from backup/local-security-fixes. Rejects paths outside the allow-list,
resolves symlinks before containment checks, and returns opaque error
messages so filesystem structure isn't leaked. dbt Core is now opt-in
via the env var; dbt Cloud path is unchanged.
EOF
)"
```

---

## Task 9: Final verification

- [ ] **Step 1: Full type-check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 2: Full jest run**

Run: `cd /Users/emilfabel/pallisade-copilot && npx jest --no-coverage`
Expected: all tests green. Note: `package.json` `test` script is a placeholder; we're calling jest directly.

- [ ] **Step 3: Verify no remaining user-controlled `fetch(userVar, …)` regressions for the 6 integrations**

Run:

```bash
grep -nE "fetch\(\`\$\{(webhookUrl|siteUrl|host|abHost|baseUrl)\}" \
  app/api/integrations/test-connection/route.ts \
  app/api/integrations/test/route.ts \
  app/api/integrations/\[id\]/test/route.ts \
  app/api/pipeline/test-connection/route.ts
```

Expected: no output. (`abHostOrigin` and `baseOrigin` and the wrapped `safeUrl` / `glUrl` / `baseUrlSafe` forms are the new usage.)

- [ ] **Step 4: Grep for remaining raw-URL fetches touching user input (manual review)**

Run:

```bash
grep -nE "await fetch\(\`\\$\{" app/api/integrations/test-connection/route.ts \
  app/api/integrations/test/route.ts \
  app/api/integrations/\[id\]/test/route.ts \
  app/api/pipeline/test-connection/route.ts | head -50
```

For each remaining hit, confirm the variable before the backtick is a hard-coded origin (`api.slack.com`, `api.pagerduty.com`, etc.), not user input. Document follow-ups in the PR body if any survive.

- [ ] **Step 5: Push branch, open PR**

```bash
git push -u origin ssrf-guard-dbt-hardening
gh pr create --title "Security: SSRF guard + dbt path-traversal" --body "$(cat <<'EOF'
## Summary
- Ports `assertExternalUrl` SSRF guard from `backup/local-security-fixes` into `lib/net/safe-url.ts` with jest coverage for IPv4/IPv6 private ranges, cloud-metadata, userinfo creds, protocol policy, host allow-list, and DNS rebinding.
- Wraps 6 user-controlled URL fetches: Teams, Jira, GitLab, Airbyte (3 sinks), Airflow (3 sinks across 2 routes).
- Ports dbt Core path-traversal fix: manifest resolution now requires `DBT_ALLOWED_PROJECT_ROOTS`, rejects symlinks pointing outside it, and returns opaque errors.

## Out of scope (follow-ups)
- Databricks `host` in `app/api/integrations/test-connection/route.ts` (same class of bug, not in the reported set).
- Any scanner-side FastAPI outbound-fetch audits.

## Test plan
- [ ] `npx tsc --noEmit`
- [ ] `npx jest lib/net/__tests__/safe-url.test.ts`
- [ ] `npm run test:python -- api/tests/test_dbt_router.py`
- [ ] Manual: configure Teams integration with `webhook_url = http://169.254.169.254/` → expect refusal, not a fetch to the metadata IP.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Remember

- Exact file paths always. Line numbers drift — use grep before each Edit.
- Commit per task. Do NOT `git add -A`; stage only the files named in the task.
- If `tsc` fails after a given task, do not proceed — fix the task first.
- The guard's default protocol is `https:` only. Every callsite above currently passes an https URL in practice; if a customer somewhere is configured with `http://` against an internal Airflow (most common), the guard will block it. That's the right default, and the fix is an explicit `{ allowedProtocols: ['http:', 'https:'] }` opt-in — **do not** ship that opt-in without the user's say-so.
- Opaque error messages: we report the guard's reason (`Private IP not allowed`, `is not in the allow-list`) to the user because this is a config-test endpoint, not a public endpoint. That's fine here. In different contexts a flat "Invalid URL" would be preferable.
