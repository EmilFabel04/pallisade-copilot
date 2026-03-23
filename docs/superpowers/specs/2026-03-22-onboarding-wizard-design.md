# Onboarding Wizard Design Spec

## Problem

New users go straight from signup to an empty dashboard with no guidance. There is no timezone collection, so all timestamps display in UTC — causing a 2-hour offset for users in CET and similar discrepancies globally. No company context or role information is captured, limiting personalization.

## Solution

A 4-step onboarding wizard at `/onboarding` that every new user completes after signup. Steps 1-2 are required (profile + company), steps 3-4 are skippable (warehouse + first monitor). The wizard guides users to first value: seeing a monitor running on their data.

## Approach

**Linear wizard with skip option.** A dedicated route (`/onboarding`) separate from the dashboard. Required steps ensure timezone and company data are always collected. Skippable steps respect users who don't have warehouse credentials at hand. Dashboard shows a resume banner for incomplete setup.

## Schema Changes

### User Model — New Fields

| Field | Type | Default | Required |
|---|---|---|---|
| `timezone` | String | — | Yes (set in onboarding) |
| `role` | String | — | Yes (set in onboarding) |
| `onboardingCompleted` | Boolean | `false` | — |
| `onboardingStep` | Int | `0` | — |

### Organization Model — New Fields

| Field | Type | Default | Required |
|---|---|---|---|
| `companySize` | String? | `null` | Yes (set in onboarding) |
| `industry` | String? | `null` | No |
| `dataTeamSize` | String? | `null` | No |

No new models are introduced. Existing `User` and `Organization` models are extended.

### Migration Strategy

Existing users must not be locked out. The Prisma migration must backfill:
- `onboardingCompleted = true` for all existing users (they already use the platform)
- `timezone = 'UTC'` for all existing users (sensible default; they can update in settings)
- `onboardingStep = 4` for all existing users

## Wizard Steps

### Step 1: Your Profile (Required)

Collects user identity and preferences.

- **Display name** — text input, pre-filled from signup `name` field
- **Timezone** — searchable dropdown of IANA timezones (e.g., `Europe/Stockholm`). Default auto-detected from browser via `Intl.DateTimeFormat().resolvedOptions().timeZone`. User must explicitly confirm.
- **Role** — dropdown: Data Engineer, Analytics Engineer, Data Analyst, Data Scientist, Engineering Manager, Platform Engineer, Other

Profile picture is deferred to a future iteration (requires file upload infrastructure not yet in place).

**API:** `PATCH /api/user/profile` (new endpoint) — updates `name`, `timezone`, `role` on the User record. Authenticated via session.

### Step 2: Your Company (Required)

Collects organization context. Creates Organization if one doesn't exist (user signed up without company name), or updates the existing one.

- **Company name** — text input, pre-filled if Organization already exists from signup
- **Company size** — radio/pill select: 1-10, 11-50, 51-200, 201-1000, 1000+
- **Industry** — optional dropdown: Fintech, Healthcare, E-commerce, SaaS, Media, Other
- **Data team size** — optional pill select: Just me, 2-5, 6-15, 15+

**API:** `PATCH /api/organization` (new endpoint) — upserts Organization with `name`, `companySize`, `industry`, `dataTeamSize`. If no Organization exists, creates one, links it to the User, and creates a `TeamMember` record with role `OWNER` and status `ACTIVE` (matching the existing signup logic in `app/api/auth/signup/route.ts`).

### Step 3: Connect Warehouse (Skippable)

Guides the user through connecting their first data warehouse. This step creates a Pipeline Profile and an Integration.

- **Pipeline name** — text input, default "Production Data Stack"
- **Warehouse type** — card selection: BigQuery, Snowflake, Postgres, Redshift, Databricks
- **Connection details** — dynamic form based on warehouse type (reuse existing integration form components)
- **Test connection** — validates credentials before allowing "Continue". User can retry on failure or change warehouse type.

**Skip behavior:** "I'll do this later" link at bottom. Skipping also skips Step 4.

**APIs:** Reuses existing endpoints:
1. `POST /api/pipeline` — creates the Pipeline Profile
2. `POST /api/integrations` — creates the integration linked to the pipeline
3. `POST /api/integrations/test-connection` — validates credentials

Sequence: create pipeline first, then create integration linked to it, then test connection.

**Error handling:** If connection test fails, show error inline with a "Retry" button. User can also go back to change warehouse type or connection details. The pipeline and integration records are created optimistically; if the user abandons, they remain in DRAFT/unconfigured state.

### Step 4: First Monitor (Skippable, Conditional)

Only shown if Step 3 was completed. Creates a monitor on the newly connected warehouse.

- **Pick a table** — searchable list of tables discovered from the warehouse. If discovery returns zero tables, show a message ("No tables found — check your connection permissions") with a "Skip" option.
- **Monitor type** — simplified choice: Freshness (is data arriving?), Volume (is row count stable?), Schema Change (did columns change?)
- **Run first scan** — runs an immediate baseline scan and shows the result inline

**Skip behavior:** "Skip for now" link. Dashboard will prompt to create a monitor later.

**APIs:** Reuses existing monitor creation and scan trigger endpoints.

## New API Endpoints

Two new endpoints are needed (Steps 1 and 2 don't map to existing routes):

### `PATCH /api/user/profile`

**File:** `app/api/user/profile/route.ts` (new)

Accepts: `{ name?, timezone?, role? }`. Updates the authenticated user's record. Returns the updated user fields.

### `PATCH /api/organization`

**File:** `app/api/organization/route.ts` (new)

Accepts: `{ name, companySize?, industry?, dataTeamSize? }`.

- If the user has an `organizationId`: updates the existing Organization.
- If the user has no `organizationId`: creates a new Organization, creates a `TeamMember` with role `OWNER` and status `ACTIVE`, and updates the user's `organizationId`. This replicates the logic in `app/api/auth/signup/route.ts` for users who skipped the company name during signup.

### `POST /api/user/onboarding`

**File:** `app/api/user/onboarding/route.ts` (new)

Accepts: `{ step: number, completed?: boolean }`.

- `step` must be >= the current `onboardingStep` (no going backward in persisted state; the UI can navigate back but only advances the DB marker)
- Updates `onboardingStep` to `step`
- If `completed: true`, sets `onboardingCompleted = true`
- Returns success; the frontend is responsible for calling `useSession().update()` to refresh the JWT (see Session Refresh Strategy below)

## Routing & Redirect Logic

### New Route

`app/(onboarding)/onboarding/page.tsx` — single page component with internal step state. Uses a clean layout (no dashboard sidebar/nav), similar to the auth pages.

### Signup Redirect Change

The signup page (`app/(auth)/signup/page.tsx`) must change its post-signup redirect from `/dashboard` to `/onboarding`. Currently line 72 does `router.push('/dashboard')` — change to `router.push('/onboarding')`.

### Redirect Rules

Applied in the dashboard layout (`app/(dashboard)/layout.tsx`):

```
if (!session) → redirect('/login')
if (!user.onboardingCompleted) → redirect('/onboarding')
else → render dashboard
```

The `onboardingCompleted` check uses a database query in the server component (not the JWT — see Session Refresh Strategy below).

The onboarding page itself checks for a session and redirects to `/login` if none exists. If `onboardingCompleted` is already true, it redirects to `/dashboard`.

### Step Persistence

`user.onboardingStep` tracks the last completed step (0-4). When the user returns to `/onboarding`, the wizard resumes at `onboardingStep + 1`. This handles browser refreshes and session interruptions.

On completing all required steps (or clicking "Skip" on skippable steps past step 2), set `onboardingCompleted = true` and redirect to `/dashboard`.

## Session Refresh Strategy

**Problem:** The JWT is minted at login. When onboarding updates `timezone` and `onboardingCompleted` in the database, the JWT still holds stale values.

**Solution — hybrid approach:**

1. **`onboardingCompleted` check:** The dashboard layout is a server component. Instead of reading from the JWT, query `prisma.user.findUnique({ select: { onboardingCompleted: true } })` using the user ID from the session. This is a single indexed lookup — negligible cost. This avoids JWT staleness for the redirect logic.

2. **`timezone` in session:** After the onboarding wizard completes and calls `POST /api/user/onboarding` with `completed: true`, the frontend calls `await update()` from `useSession()` (NextAuth's client-side session refresh). The NextAuth `jwt` callback re-fetches the user from the database when `trigger === 'update'`, picking up the new `timezone`. The wizard then does `router.push('/dashboard')`.

3. **JWT callback update:** In `lib/auth.ts`, the `jwt` callback must handle the `trigger === 'update'` case by re-fetching user fields from the database:
```typescript
async jwt({ token, user, trigger }) {
  if (user) {
    token.id = user.id;
    token.organizationId = user.organizationId;
    token.timezone = user.timezone;
  }
  if (trigger === 'update') {
    const dbUser = await prisma.user.findUnique({ where: { id: token.id }, select: { timezone: true, organizationId: true } });
    if (dbUser) {
      token.timezone = dbUser.timezone;
      token.organizationId = dbUser.organizationId;
    }
  }
  return token;
}
```

## Timezone Integration

### Collection

Step 1 of the wizard. Browser auto-detection provides the default; user explicitly confirms via searchable dropdown.

### Storage

Stored as `user.timezone` (IANA string, e.g., `Europe/Stockholm`). Added to the JWT token and session object via the callbacks described in Session Refresh Strategy above.

```typescript
// In session callback:
session.user.timezone = token.timezone;
```

### Usage

- **API responses:** Continue returning UTC timestamps. No backend changes needed.
- **Frontend display:** All timestamp formatting uses the timezone from the session. Replace raw `Date` formatting with timezone-aware formatting: `date.toLocaleString([], { timeZone: session.user.timezone })`. Create a shared utility (`lib/format-date.ts`) to centralize this.
- **Affected surfaces:** Lineage "Last Updated", log timestamps, scan history, monitor schedules, any future time displays.

## Dashboard Resume Banner

For users who completed onboarding but skipped steps 3 or 4.

### States

| Condition | Banner Message | Action |
|---|---|---|
| No pipeline/warehouse | "Connect your first warehouse to start monitoring" | Links to pipeline setup |
| Pipeline exists, no monitors | "Set up your first monitor to start watching your data" | Links to monitor creation |
| Both exist | No banner | — |

### Implementation

Create a new `SetupBanner` component (separate from the existing copilot `OnboardingBanner`, which serves a different purpose — teaching the copilot about the user's data stack). The `SetupBanner` is a dashboard-level component that checks for pipeline/integration/monitor existence. It is dismissible (stored in localStorage). Does not block dashboard usage.

## What This Does NOT Cover

- OAuth signup (Google/GitHub) — not currently active. When added, OAuth users enter the same wizard at Step 1.
- Email verification flow — out of scope.
- Team invite onboarding — invited users who join an existing org could have a simplified flow (skip Step 2). Deferred to future work.
- Pipeline-level copilot onboarding — the existing `PipelineContext` onboarding (teaching the copilot about your setup) remains separate and unchanged.
- Profile picture upload — deferred until file upload infrastructure is in place.
