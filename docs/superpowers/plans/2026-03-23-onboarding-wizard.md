# Onboarding Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 4-step onboarding wizard that collects user profile (timezone, role), company info, and optionally guides them through warehouse connection and first monitor setup.

**Architecture:** Multi-step wizard at `/onboarding` using a single client component with step state. New API endpoints for profile and organization updates. Prisma schema extended with timezone, role, onboarding fields. JWT session refresh via NextAuth `trigger === 'update'` pattern. Dashboard layout gets a DB-query guard that redirects incomplete users to onboarding.

**Tech Stack:** Next.js 15, NextAuth, Prisma, Tailwind CSS, TypeScript

**Spec:** `docs/superpowers/specs/2026-03-22-onboarding-wizard-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|---|---|
| `app/(onboarding)/layout.tsx` | Clean layout for onboarding (no sidebar), auth-page style |
| `app/(onboarding)/onboarding/page.tsx` | Wizard container — manages step state, routing, persistence |
| `components/onboarding/ProfileStep.tsx` | Step 1: name, timezone, role form |
| `components/onboarding/CompanyStep.tsx` | Step 2: company name, size, industry, data team size |
| `components/onboarding/WarehouseStep.tsx` | Step 3: pipeline name, warehouse type, connection form |
| `components/onboarding/MonitorStep.tsx` | Step 4: pick table, monitor type, run first scan |
| `components/onboarding/StepProgress.tsx` | Progress bar showing steps 1-4 with active/completed states |
| `components/dashboard/SetupBanner.tsx` | Dashboard resume banner for skipped steps |
| `app/api/user/profile/route.ts` | PATCH: update user name, timezone, role |
| `app/api/user/onboarding/route.ts` | POST: update onboarding step + completed flag |
| `app/api/organization/route.ts` | PATCH: upsert organization with company details |
| `lib/format-date.ts` | Timezone-aware date formatting utility |

### Modified Files
| File | What Changes |
|---|---|
| `prisma/schema.prisma` | Add timezone, role, onboardingCompleted, onboardingStep to User; companySize, industry, dataTeamSize to Organization |
| `lib/auth.ts` | JWT callback handles `trigger === 'update'` to refresh timezone; session callback exposes timezone |
| `app/(auth)/signup/page.tsx` | Change redirect from `/dashboard` to `/onboarding` |
| `app/(dashboard)/layout.tsx` | Add DB query to check onboardingCompleted, redirect to `/onboarding` if false |

---

## Task 1: Schema Changes + Migration

**Files:**
- Modify: `prisma/schema.prisma:17-52` (User model), `prisma/schema.prisma:96-174` (Organization model)

- [ ] **Step 1: Add new fields to User model**

In `prisma/schema.prisma`, add these fields to the User model (after line 25, before the `// Relations` comment):

```prisma
  // Onboarding
  timezone            String?
  role                String?
  onboardingCompleted Boolean   @default(false)
  onboardingStep      Int       @default(0)
```

- [ ] **Step 2: Add new fields to Organization model**

In `prisma/schema.prisma`, add these fields to the Organization model (after line 103, before the `// SLO Configuration` comment):

```prisma
  // Company profile
  companySize  String?
  industry     String?
  dataTeamSize String?
```

- [ ] **Step 3: Create migration (without applying)**

Run:
```bash
npx prisma migrate dev --name add-onboarding-fields --create-only
```

Expected: Creates migration SQL file in `prisma/migrations/` but does NOT apply it yet.

- [ ] **Step 4: Add backfill SQL to the migration**

Open the generated migration file (newest directory in `prisma/migrations/`). Append this at the end of the SQL file:

```sql
-- Backfill existing users so they are not locked out
UPDATE "User" SET "onboardingCompleted" = true, "onboardingStep" = 4, "timezone" = 'UTC' WHERE "onboardingCompleted" = false;
```

- [ ] **Step 5: Apply the migration**

Run:
```bash
npx prisma migrate dev
```

Expected: Migration applies, existing users get `onboardingCompleted = true`, `timezone = 'UTC'`.

- [ ] **Step 6: Verify with Prisma Studio**

Run: `npx prisma studio`
Check: User model has new fields. Existing users show `onboardingCompleted = true`, `timezone = 'UTC'`.

- [ ] **Step 7: Commit**

```bash
git add prisma/schema.prisma prisma/migrations/
git commit -m "feat: add onboarding fields to User and Organization models"
```

---

## Task 2: API Endpoints

**Files:**
- Create: `app/api/user/profile/route.ts`
- Create: `app/api/user/onboarding/route.ts`
- Create: `app/api/organization/route.ts`

- [ ] **Step 1: Create user profile endpoint**

Create `app/api/user/profile/route.ts`:

```typescript
import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../../../lib/auth';
import prisma from '@/lib/db';

export async function PATCH(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const body = await request.json();
  const { name, timezone, role } = body;

  const data: Record<string, any> = {};
  if (name !== undefined) data.name = name;
  if (timezone !== undefined) data.timezone = timezone;
  if (role !== undefined) data.role = role;

  const user = await prisma.user.update({
    where: { id: (session.user as any).id },
    data,
    select: { id: true, name: true, timezone: true, role: true },
  });

  return NextResponse.json({ user });
}
```

- [ ] **Step 2: Create onboarding progress endpoint**

Create `app/api/user/onboarding/route.ts`:

```typescript
import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../../../lib/auth';
import prisma from '@/lib/db';

export async function POST(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const userId = (session.user as any).id;
  const body = await request.json();
  const { step, completed } = body;

  // Validate step is forward-only
  const current = await prisma.user.findUnique({
    where: { id: userId },
    select: { onboardingStep: true },
  });

  if (typeof step !== 'number' || step < (current?.onboardingStep ?? 0)) {
    return NextResponse.json({ error: 'Invalid step' }, { status: 400 });
  }

  const data: Record<string, any> = { onboardingStep: step };
  if (completed) {
    data.onboardingCompleted = true;
  }

  const user = await prisma.user.update({
    where: { id: userId },
    data,
    select: { id: true, onboardingStep: true, onboardingCompleted: true },
  });

  return NextResponse.json({ user });
}

export async function GET(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const user = await prisma.user.findUnique({
    where: { id: (session.user as any).id },
    select: { onboardingStep: true, onboardingCompleted: true },
  });

  return NextResponse.json({ user });
}
```

- [ ] **Step 3: Create organization upsert endpoint**

Create `app/api/organization/route.ts`:

```typescript
import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../../lib/auth';
import prisma from '@/lib/db';

export async function PATCH(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const userId = (session.user as any).id;
  const body = await request.json();
  const { name, companySize, industry, dataTeamSize } = body;

  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { organizationId: true },
  });

  let organization;

  if (user?.organizationId) {
    // Update existing organization
    const data: Record<string, any> = {};
    if (name !== undefined) data.name = name;
    if (companySize !== undefined) data.companySize = companySize;
    if (industry !== undefined) data.industry = industry;
    if (dataTeamSize !== undefined) data.dataTeamSize = dataTeamSize;

    organization = await prisma.organization.update({
      where: { id: user.organizationId },
      data,
    });
  } else {
    // Create new organization + team membership (replicates signup pattern)
    if (!name) {
      return NextResponse.json({ error: 'Company name is required' }, { status: 400 });
    }

    organization = await prisma.$transaction(async (tx) => {
      const org = await tx.organization.create({
        data: { name, companySize, industry, dataTeamSize },
      });

      await tx.teamMember.create({
        data: {
          userId,
          organizationId: org.id,
          role: 'OWNER',
          status: 'ACTIVE',
          joinedAt: new Date(),
        },
      });

      await tx.user.update({
        where: { id: userId },
        data: { organizationId: org.id },
      });

      return org;
    });
  }

  return NextResponse.json({ organization });
}

export async function GET(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const user = await prisma.user.findUnique({
    where: { id: (session.user as any).id },
    select: {
      organization: {
        select: { id: true, name: true, companySize: true, industry: true, dataTeamSize: true },
      },
    },
  });

  return NextResponse.json({ organization: user?.organization || null });
}
```

- [ ] **Step 4: Verify endpoints start without errors**

Run: `npm run dev`
Test with curl:
```bash
# Should return 401 (no session)
curl -X PATCH http://localhost:3000/api/user/profile -H 'Content-Type: application/json' -d '{"name":"test"}'
```
Expected: `{"error":"Unauthorized"}` with status 401.

- [ ] **Step 5: Commit**

```bash
git add app/api/user/profile/route.ts app/api/user/onboarding/route.ts app/api/organization/route.ts
git commit -m "feat: add API endpoints for onboarding (profile, organization, step tracking)"
```

---

## Task 3: JWT/Session + Auth Changes

**Files:**
- Modify: `lib/auth.ts:75-91`
- Modify: `app/(auth)/signup/page.tsx:72`
- Modify: `app/(dashboard)/layout.tsx:17-21`

- [ ] **Step 1: Update JWT callback to handle session refresh and expose timezone**

In `lib/auth.ts`, replace the callbacks section (lines 75-90):

```typescript
  callbacks: {
    async jwt({ token, user, trigger }) {
      if (user) {
        token.id = user.id;
        token.organizationId = (user as any).organizationId;
        token.timezone = (user as any).timezone;
      }
      // Re-fetch from DB when client calls useSession().update()
      if (trigger === 'update' && token.id) {
        const dbUser = await prisma.user.findUnique({
          where: { id: token.id as string },
          select: { timezone: true, organizationId: true },
        });
        if (dbUser) {
          token.timezone = dbUser.timezone;
          token.organizationId = dbUser.organizationId;
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as any).id = token.id;
        (session.user as any).organizationId = token.organizationId;
        (session.user as any).timezone = token.timezone;
      }
      return session;
    },
  },
```

`lib/auth.ts` already imports prisma on line 7 (`import prisma from './db'`) — no new import needed.

- [ ] **Step 2: Change signup redirect to /onboarding**

In `app/(auth)/signup/page.tsx`, change line 72 from:

```typescript
        router.push('/dashboard');
```

to:

```typescript
        router.push('/onboarding');
```

- [ ] **Step 3: Add onboarding guard to dashboard layout**

In `app/(dashboard)/layout.tsx`, add the onboarding check after the session check (after line 21):

```typescript
  // Check if user has completed onboarding
  const user = await prisma.user.findUnique({
    where: { id: (session.user as any).id },
    select: { onboardingCompleted: true },
  });

  if (!user?.onboardingCompleted) {
    redirect('/onboarding');
  }
```

Add the prisma import at the top of `app/(dashboard)/layout.tsx`:

```typescript
import prisma from '@/lib/db';
```

- [ ] **Step 4: Verify redirect flow**

Run: `npm run dev`
1. Log in as an existing user → should go to dashboard (backfilled `onboardingCompleted = true`)
2. Create a new test user via signup → should redirect to `/onboarding` (returns 404 for now, that's expected)

- [ ] **Step 5: Commit**

```bash
git add lib/auth.ts app/(auth)/signup/page.tsx app/(dashboard)/layout.tsx
git commit -m "feat: JWT timezone support, signup redirect to onboarding, dashboard guard"
```

---

## Task 4: Onboarding Layout + Progress Component

**Files:**
- Create: `app/(onboarding)/layout.tsx`
- Create: `components/onboarding/StepProgress.tsx`

- [ ] **Step 1: Create onboarding layout**

Create `app/(onboarding)/layout.tsx` (mirrors the auth layout style):

```typescript
import '../globals.css';

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen relative overflow-hidden flex flex-col bg-[var(--bg)]">
      {/* Background effects — same as auth layout */}
      <div className="orb orb-1" />
      <div className="orb orb-2" />
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div
          className="absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 w-[1400px] h-[700px] opacity-[0.03]"
          style={{
            background:
              'repeating-linear-gradient(0deg, currentColor 0 1px, transparent 1px 80px), repeating-linear-gradient(90deg, currentColor 0 1px, transparent 1px 80px)',
            color: 'rgb(139,11,16)',
            transform: 'perspective(1200px) rotateX(65deg) translateZ(-150px)',
          }}
        />
      </div>
      <div className="flex-1 flex items-center justify-center px-4 py-8">
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create step progress component**

Create `components/onboarding/StepProgress.tsx`:

```typescript
'use client';

const STEPS = [
  { label: 'Profile', number: 1 },
  { label: 'Company', number: 2 },
  { label: 'Warehouse', number: 3 },
  { label: 'Monitor', number: 4 },
];

interface StepProgressProps {
  currentStep: number; // 1-4
  completedSteps: number; // 0-4
}

export function StepProgress({ currentStep, completedSteps }: StepProgressProps) {
  return (
    <div className="flex items-center justify-center gap-2 mb-8">
      {STEPS.map((step, i) => {
        const isCompleted = step.number <= completedSteps;
        const isCurrent = step.number === currentStep;
        return (
          <div key={step.number} className="flex items-center gap-2">
            {i > 0 && (
              <div
                className={`w-8 h-px ${
                  step.number <= completedSteps + 1
                    ? 'bg-[var(--accent)]'
                    : 'bg-[var(--subtle-border)]'
                }`}
              />
            )}
            <div className="flex items-center gap-2">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-colors ${
                  isCompleted
                    ? 'bg-[var(--accent)] text-white'
                    : isCurrent
                    ? 'bg-[var(--accent)] text-white'
                    : 'bg-[var(--overlay-medium)] text-[var(--muted)]'
                }`}
              >
                {isCompleted && step.number < currentStep ? '✓' : step.number}
              </div>
              <span
                className={`text-xs font-medium hidden sm:inline ${
                  isCurrent ? 'text-[var(--text)]' : 'text-[var(--muted)]'
                }`}
              >
                {step.label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add app/\(onboarding\)/layout.tsx components/onboarding/StepProgress.tsx
git commit -m "feat: onboarding layout and step progress component"
```

---

## Task 5: Profile Step (Step 1)

**Files:**
- Create: `components/onboarding/ProfileStep.tsx`

- [ ] **Step 1: Create profile step component**

Create `components/onboarding/ProfileStep.tsx`:

```typescript
'use client';

import { useState, useEffect } from 'react';
import { Button } from '../ui/button';

// Common IANA timezones — comprehensive enough for global coverage
const TIMEZONES = Intl.supportedValuesOf('timeZone');

interface ProfileStepProps {
  initialName: string;
  onComplete: (data: { name: string; timezone: string; role: string }) => void;
  isLoading: boolean;
}

const ROLES = [
  'Data Engineer',
  'Analytics Engineer',
  'Data Analyst',
  'Data Scientist',
  'Engineering Manager',
  'Platform Engineer',
  'Other',
];

export function ProfileStep({ initialName, onComplete, isLoading }: ProfileStepProps) {
  const [name, setName] = useState(initialName);
  const [timezone, setTimezone] = useState('');
  const [tzSearch, setTzSearch] = useState('');
  const [role, setRole] = useState('');

  useEffect(() => {
    // Auto-detect timezone from browser
    const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
    setTimezone(detected);
    setTzSearch(detected);
  }, []);

  const filteredTimezones = TIMEZONES.filter((tz) =>
    tz.toLowerCase().includes(tzSearch.toLowerCase())
  );

  const isValid = name.trim() && timezone && role;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[var(--text)]">Your Profile</h2>
        <p className="text-[var(--muted)] mt-1">Tell us a bit about yourself</p>
      </div>

      <div className="space-y-4">
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Display Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            placeholder="Your name"
          />
        </div>

        {/* Timezone */}
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Timezone
          </label>
          <input
            type="text"
            value={tzSearch}
            onChange={(e) => {
              setTzSearch(e.target.value);
              // If exact match, select it
              if (TIMEZONES.includes(e.target.value)) {
                setTimezone(e.target.value);
              }
            }}
            onFocus={() => setTzSearch('')}
            onBlur={() => {
              // Restore selected timezone if search is empty
              if (!tzSearch && timezone) setTzSearch(timezone);
            }}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            placeholder="Search timezone..."
          />
          {tzSearch && tzSearch !== timezone && filteredTimezones.length > 0 && (
            <div className="mt-1 max-h-40 overflow-y-auto rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)]">
              {filteredTimezones.slice(0, 10).map((tz) => (
                <button
                  key={tz}
                  type="button"
                  onClick={() => {
                    setTimezone(tz);
                    setTzSearch(tz);
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-[var(--text)] hover:bg-[var(--hover-bg)]"
                >
                  {tz}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Role */}
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Role
          </label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
          >
            <option value="">Select your role</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
      </div>

      <Button
        onClick={() => onComplete({ name: name.trim(), timezone, role })}
        disabled={!isValid || isLoading}
        className="w-full"
        size="lg"
      >
        {isLoading ? 'Saving...' : 'Continue'}
      </Button>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/onboarding/ProfileStep.tsx
git commit -m "feat: profile step component with timezone picker and role selector"
```

---

## Task 6: Company Step (Step 2)

**Files:**
- Create: `components/onboarding/CompanyStep.tsx`

- [ ] **Step 1: Create company step component**

Create `components/onboarding/CompanyStep.tsx`:

```typescript
'use client';

import { useState } from 'react';
import { Button } from '../ui/button';

interface CompanyStepProps {
  initialName: string;
  onComplete: (data: {
    name: string;
    companySize: string;
    industry?: string;
    dataTeamSize?: string;
  }) => void;
  onBack: () => void;
  isLoading: boolean;
}

const COMPANY_SIZES = ['1-10', '11-50', '51-200', '201-1000', '1000+'];
const INDUSTRIES = ['Fintech', 'Healthcare', 'E-commerce', 'SaaS', 'Media', 'Other'];
const DATA_TEAM_SIZES = ['Just me', '2-5', '6-15', '15+'];

export function CompanyStep({ initialName, onComplete, onBack, isLoading }: CompanyStepProps) {
  const [name, setName] = useState(initialName);
  const [companySize, setCompanySize] = useState('');
  const [industry, setIndustry] = useState('');
  const [dataTeamSize, setDataTeamSize] = useState('');

  const isValid = name.trim() && companySize;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[var(--text)]">Your Company</h2>
        <p className="text-[var(--muted)] mt-1">Help us understand your organization</p>
      </div>

      <div className="space-y-4">
        {/* Company Name */}
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Company Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            placeholder="Company name"
          />
        </div>

        {/* Company Size */}
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Company Size
          </label>
          <div className="flex flex-wrap gap-2">
            {COMPANY_SIZES.map((size) => (
              <button
                key={size}
                type="button"
                onClick={() => setCompanySize(size)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
                  companySize === size
                    ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
                    : 'bg-[var(--surface-sunken)] text-[var(--text)] border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                }`}
              >
                {size}
              </button>
            ))}
          </div>
        </div>

        {/* Industry (optional) */}
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Industry <span className="text-[var(--muted)]">(optional)</span>
          </label>
          <select
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
          >
            <option value="">Select industry</option>
            {INDUSTRIES.map((i) => (
              <option key={i} value={i}>{i}</option>
            ))}
          </select>
        </div>

        {/* Data Team Size (optional) */}
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Data Team Size <span className="text-[var(--muted)]">(optional)</span>
          </label>
          <div className="flex flex-wrap gap-2">
            {DATA_TEAM_SIZES.map((size) => (
              <button
                key={size}
                type="button"
                onClick={() => setDataTeamSize(size)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
                  dataTeamSize === size
                    ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
                    : 'bg-[var(--surface-sunken)] text-[var(--text)] border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                }`}
              >
                {size}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex gap-3">
        <Button onClick={onBack} variant="secondary" size="lg" className="flex-1">
          Back
        </Button>
        <Button
          onClick={() =>
            onComplete({
              name: name.trim(),
              companySize,
              industry: industry || undefined,
              dataTeamSize: dataTeamSize || undefined,
            })
          }
          disabled={!isValid || isLoading}
          size="lg"
          className="flex-1"
        >
          {isLoading ? 'Saving...' : 'Continue'}
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/onboarding/CompanyStep.tsx
git commit -m "feat: company step component with size/industry/team pickers"
```

---

## Task 7: Warehouse Step (Step 3)

**Files:**
- Create: `components/onboarding/WarehouseStep.tsx`

- [ ] **Step 1: Create warehouse step component**

Create `components/onboarding/WarehouseStep.tsx`:

```typescript
'use client';

import { useState } from 'react';
import { Button } from '../ui/button';

interface WarehouseStepProps {
  onComplete: (data: { pipelineName: string; warehouseType: string }) => void;
  onSkip: () => void;
  onBack: () => void;
  isLoading: boolean;
}

const WAREHOUSES = [
  { id: 'BIGQUERY', name: 'BigQuery', icon: 'BQ' },
  { id: 'SNOWFLAKE', name: 'Snowflake', icon: 'SF' },
  { id: 'POSTGRES', name: 'PostgreSQL', icon: 'PG' },
  { id: 'REDSHIFT', name: 'Redshift', icon: 'RS' },
  { id: 'DATABRICKS', name: 'Databricks', icon: 'DB' },
];

export function WarehouseStep({ onComplete, onSkip, onBack, isLoading }: WarehouseStepProps) {
  const [pipelineName, setPipelineName] = useState('Production Data Stack');
  const [warehouseType, setWarehouseType] = useState('');

  const isValid = pipelineName.trim() && warehouseType;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[var(--text)]">Connect Your Warehouse</h2>
        <p className="text-[var(--muted)] mt-1">
          Set up your first data connection to start monitoring
        </p>
      </div>

      <div className="space-y-4">
        {/* Pipeline Name */}
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Pipeline Name
          </label>
          <input
            type="text"
            value={pipelineName}
            onChange={(e) => setPipelineName(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            placeholder="e.g., Production Data Stack"
          />
        </div>

        {/* Warehouse Type */}
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Warehouse Type
          </label>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {WAREHOUSES.map((wh) => (
              <button
                key={wh.id}
                type="button"
                onClick={() => setWarehouseType(wh.id)}
                className={`p-4 rounded-xl text-center transition-colors border ${
                  warehouseType === wh.id
                    ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
                    : 'bg-[var(--surface-sunken)] text-[var(--text)] border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                }`}
              >
                <div className="text-lg font-bold mb-1">{wh.icon}</div>
                <div className="text-sm font-medium">{wh.name}</div>
              </button>
            ))}
          </div>
        </div>
      </div>

      <p className="text-xs text-[var(--muted)] text-center">
        You'll configure connection details in the pipeline settings after setup.
      </p>

      <div className="flex gap-3">
        <Button onClick={onBack} variant="secondary" size="lg" className="flex-1">
          Back
        </Button>
        <Button
          onClick={() => onComplete({ pipelineName: pipelineName.trim(), warehouseType })}
          disabled={!isValid || isLoading}
          size="lg"
          className="flex-1"
        >
          {isLoading ? 'Creating...' : 'Continue'}
        </Button>
      </div>

      <button
        onClick={onSkip}
        className="w-full text-sm text-[var(--muted)] hover:text-[var(--text)] transition-colors py-2"
      >
        I'll do this later
      </button>
    </div>
  );
}
```

**Scope note:** This step creates the pipeline profile and selects the warehouse type. Full connection configuration (credentials, test connection) and Step 4's table discovery + monitor creation are deferred to a fast-follow iteration. This keeps the initial onboarding light while still capturing the user's intent and creating the pipeline scaffold. The spec's full Step 3/4 (with live warehouse connection and first scan) can be added once the base wizard is working.

- [ ] **Step 2: Commit**

```bash
git add components/onboarding/WarehouseStep.tsx
git commit -m "feat: warehouse step component with pipeline name and warehouse type selector"
```

---

## Task 8: Monitor Step (Step 4) — Placeholder

**Files:**
- Create: `components/onboarding/MonitorStep.tsx`

- [ ] **Step 1: Create monitor step component**

This step is conditional (only shown if Step 3 was completed) and depends on warehouse being configured with credentials. Since Step 3 now creates a pipeline in DRAFT status, Step 4 shows a preview of what monitoring will look like and links to the configuration.

Create `components/onboarding/MonitorStep.tsx`:

```typescript
'use client';

import { Button } from '../ui/button';

interface MonitorStepProps {
  pipelineName: string;
  warehouseType: string;
  onComplete: () => void;
  onSkip: () => void;
  onBack: () => void;
}

export function MonitorStep({
  pipelineName,
  warehouseType,
  onComplete,
  onSkip,
  onBack,
}: MonitorStepProps) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[var(--text)]">Set Up Monitoring</h2>
        <p className="text-[var(--muted)] mt-1">
          Your pipeline "{pipelineName}" ({warehouseType}) is ready to configure
        </p>
      </div>

      <div className="rounded-xl border border-[var(--subtle-border)] bg-[var(--surface-sunken)] p-6 space-y-4">
        <h3 className="text-sm font-semibold text-[var(--text)]">Next steps after setup:</h3>
        <div className="space-y-3">
          {[
            { step: '1', text: 'Add your warehouse credentials in pipeline settings' },
            { step: '2', text: 'Pick tables to monitor for freshness, volume, or schema changes' },
            { step: '3', text: 'Run your first scan and see results in real-time' },
          ].map((item) => (
            <div key={item.step} className="flex items-start gap-3">
              <div className="w-6 h-6 rounded-full bg-[var(--accent)] text-white flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
                {item.step}
              </div>
              <p className="text-sm text-[var(--text)]">{item.text}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-3">
        <Button onClick={onBack} variant="secondary" size="lg" className="flex-1">
          Back
        </Button>
        <Button onClick={onComplete} size="lg" className="flex-1">
          Go to Dashboard
        </Button>
      </div>

      <button
        onClick={onSkip}
        className="w-full text-sm text-[var(--muted)] hover:text-[var(--text)] transition-colors py-2"
      >
        Skip for now
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/onboarding/MonitorStep.tsx
git commit -m "feat: monitor step component showing next steps after pipeline creation"
```

---

## Task 9: Wizard Container Page

**Files:**
- Create: `app/(onboarding)/onboarding/page.tsx`

- [ ] **Step 1: Create the wizard page**

Create `app/(onboarding)/onboarding/page.tsx`:

```typescript
'use client';

import { useState, useEffect } from 'react';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { StepProgress } from '../../../components/onboarding/StepProgress';
import { ProfileStep } from '../../../components/onboarding/ProfileStep';
import { CompanyStep } from '../../../components/onboarding/CompanyStep';
import { WarehouseStep } from '../../../components/onboarding/WarehouseStep';
import { MonitorStep } from '../../../components/onboarding/MonitorStep';

export default function OnboardingPage() {
  const { data: session, status, update } = useSession();
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(1);
  const [completedSteps, setCompletedSteps] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [initialDataLoaded, setInitialDataLoaded] = useState(false);

  // Data from previous steps (for passing to later steps)
  const [userName, setUserName] = useState('');
  const [orgName, setOrgName] = useState('');
  const [pipelineName, setPipelineName] = useState('');
  const [warehouseType, setWarehouseType] = useState('');
  const [warehouseConnected, setWarehouseConnected] = useState(false);

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/login');
    }
  }, [status, router]);

  // Load initial data — resume from last step, redirect if already completed
  useEffect(() => {
    if (status !== 'authenticated' || initialDataLoaded) return;

    async function loadOnboardingState() {
      // Check onboarding progress from DB
      try {
        const res = await fetch('/api/user/onboarding');
        if (res.ok) {
          const data = await res.json();
          if (data.user?.onboardingCompleted) {
            router.push('/dashboard');
            return;
          }
          const savedStep = data.user?.onboardingStep ?? 0;
          if (savedStep > 0) {
            setCompletedSteps(savedStep);
            setCurrentStep(savedStep + 1);
          }
        }
      } catch {
        // Fresh start
      }

      // Pre-fill name from session
      setUserName((session?.user as any)?.name || '');

      // Load org name if exists
      try {
        const orgRes = await fetch('/api/organization');
        if (orgRes.ok) {
          const data = await orgRes.json();
          if (data.organization?.name) {
            setOrgName(data.organization.name);
          }
        }
      } catch {
        // No org yet
      }

      setInitialDataLoaded(true);
    }

    loadOnboardingState();
  }, [status, session, initialDataLoaded]);

  async function saveStep(step: number, completed = false) {
    await fetch('/api/user/onboarding', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step, completed }),
    });
  }

  async function handleProfileComplete(data: { name: string; timezone: string; role: string }) {
    setIsLoading(true);
    try {
      const res = await fetch('/api/user/profile', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error('Failed to save profile');

      setUserName(data.name);
      await saveStep(1);
      setCompletedSteps(1);
      setCurrentStep(2);
    } catch (err) {
      console.error('Profile save error:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCompanyComplete(data: {
    name: string;
    companySize: string;
    industry?: string;
    dataTeamSize?: string;
  }) {
    setIsLoading(true);
    try {
      const res = await fetch('/api/organization', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error('Failed to save company');

      setOrgName(data.name);
      await saveStep(2);
      setCompletedSteps(2);
      setCurrentStep(3);
    } catch (err) {
      console.error('Company save error:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleWarehouseComplete(data: {
    pipelineName: string;
    warehouseType: string;
  }) {
    setIsLoading(true);
    try {
      // Create pipeline
      const pipelineRes = await fetch('/api/pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: data.pipelineName }),
      });
      if (!pipelineRes.ok) throw new Error('Failed to create pipeline');

      setPipelineName(data.pipelineName);
      setWarehouseType(data.warehouseType);
      setWarehouseConnected(true);
      await saveStep(3);
      setCompletedSteps(3);
      setCurrentStep(4);
    } catch (err) {
      console.error('Warehouse setup error:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleFinish() {
    setIsLoading(true);
    try {
      await saveStep(4, true);
      // Refresh session to pick up timezone
      await update();
      router.push('/dashboard');
      router.refresh();
    } catch (err) {
      console.error('Finish error:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSkipWarehouse() {
    await saveStep(4, true);
    await update();
    router.push('/dashboard');
    router.refresh();
  }

  async function handleSkipMonitor() {
    await saveStep(4, true);
    await update();
    router.push('/dashboard');
    router.refresh();
  }

  if (status === 'loading' || !initialDataLoaded) {
    return (
      <div className="w-full max-w-lg text-center">
        <p className="text-[var(--muted)]">Loading...</p>
      </div>
    );
  }

  return (
    <div className="w-full max-w-lg">
      <StepProgress currentStep={currentStep} completedSteps={completedSteps} />

      {currentStep === 1 && (
        <ProfileStep
          initialName={userName}
          onComplete={handleProfileComplete}
          isLoading={isLoading}
        />
      )}

      {currentStep === 2 && (
        <CompanyStep
          initialName={orgName}
          onComplete={handleCompanyComplete}
          onBack={() => setCurrentStep(1)}
          isLoading={isLoading}
        />
      )}

      {currentStep === 3 && (
        <WarehouseStep
          onComplete={handleWarehouseComplete}
          onSkip={handleSkipWarehouse}
          onBack={() => setCurrentStep(2)}
          isLoading={isLoading}
        />
      )}

      {currentStep === 4 && (
        <MonitorStep
          pipelineName={pipelineName}
          warehouseType={warehouseType}
          onComplete={handleFinish}
          onSkip={handleSkipMonitor}
          onBack={() => setCurrentStep(3)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: The onboarding page needs SessionProvider — add it to the layout**

Update `app/(onboarding)/layout.tsx` to wrap children in SessionProvider:

```typescript
import '../globals.css';
import { SessionProvider } from '../../components/providers/SessionProvider';

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen relative overflow-hidden flex flex-col bg-[var(--bg)]">
      <div className="orb orb-1" />
      <div className="orb orb-2" />
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div
          className="absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 w-[1400px] h-[700px] opacity-[0.03]"
          style={{
            background:
              'repeating-linear-gradient(0deg, currentColor 0 1px, transparent 1px 80px), repeating-linear-gradient(90deg, currentColor 0 1px, transparent 1px 80px)',
            color: 'rgb(139,11,16)',
            transform: 'perspective(1200px) rotateX(65deg) translateZ(-150px)',
          }}
        />
      </div>
      <div className="flex-1 flex items-center justify-center px-4 py-8">
        <SessionProvider>{children}</SessionProvider>
      </div>
    </div>
  );
}
```

Reuses the existing `components/providers/SessionProvider.tsx` — no new wrapper file needed.

- [ ] **Step 3: Verify the full flow**

Run: `npm run dev`
1. Sign up as a new user
2. Should redirect to `/onboarding`
3. Complete Step 1 (profile) → Step 2 (company) → Skip warehouse → lands on dashboard
4. Check DB: `onboardingCompleted = true`, `timezone` set, org created with OWNER TeamMember

- [ ] **Step 4: Commit**

```bash
git add app/\(onboarding\)/
git commit -m "feat: onboarding wizard container with full 4-step flow"
```

---

## Task 10: Timezone Formatting Utility

**Files:**
- Create: `lib/format-date.ts`

- [ ] **Step 1: Create the date formatting utility**

Create `lib/format-date.ts`:

```typescript
/**
 * Format a date/timestamp with the user's timezone.
 * All API responses return UTC; this converts for display.
 */
export function formatDate(
  date: string | Date | null | undefined,
  timezone: string | null | undefined,
  options?: Intl.DateTimeFormatOptions
): string {
  if (!date) return 'Unknown';

  const d = typeof date === 'string' ? new Date(date) : date;
  if (isNaN(d.getTime())) return 'Unknown';

  const tz = timezone || 'UTC';
  const defaultOptions: Intl.DateTimeFormatOptions = {
    timeZone: tz,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  };

  return d.toLocaleString([], { ...defaultOptions, ...options });
}

/**
 * Format a date as a relative time string (e.g., "2h ago", "3d ago").
 * Uses timezone to determine "now" correctly.
 */
export function formatRelativeTime(
  date: string | Date | null | undefined,
  timezone: string | null | undefined
): string {
  if (!date) return 'Unknown';

  const d = typeof date === 'string' ? new Date(date) : date;
  if (isNaN(d.getTime())) return 'Unknown';

  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);

  if (diffHours < 0) return 'Just now';
  if (diffHours < 1) return 'Just now';
  if (diffHours < 24) return `${Math.round(diffHours)}h ago`;
  if (diffHours < 24 * 30) return `${Math.round(diffHours / 24)}d ago`;

  // Fall back to absolute date for older timestamps
  return formatDate(d, timezone, { hour: undefined, minute: undefined });
}

/**
 * Format a date for display in short form (date only, no time).
 */
export function formatDateShort(
  date: string | Date | null | undefined,
  timezone: string | null | undefined
): string {
  return formatDate(date, timezone, {
    hour: undefined,
    minute: undefined,
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add lib/format-date.ts
git commit -m "feat: timezone-aware date formatting utilities"
```

---

## Task 11: Dashboard Setup Banner

**Files:**
- Create: `components/dashboard/SetupBanner.tsx`

- [ ] **Step 1: Create setup banner component**

Create `components/dashboard/SetupBanner.tsx`:

```typescript
'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '../ui/button';

const DISMISSED_KEY = 'pallisade-setup-banner-dismissed';

type BannerState = 'no-warehouse' | 'no-monitors' | 'complete' | 'loading';

export function SetupBanner() {
  const router = useRouter();
  const [state, setState] = useState<BannerState>('loading');
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined' && localStorage.getItem(DISMISSED_KEY)) {
      setDismissed(true);
      return;
    }

    async function checkSetup() {
      try {
        const res = await fetch('/api/pipeline');
        if (!res.ok) {
          setState('no-warehouse');
          return;
        }
        const data = await res.json();
        const pipelines = data.stacks || data.pipelines || [];

        if (pipelines.length === 0) {
          setState('no-warehouse');
          return;
        }

        // Check if any pipeline has integrations/monitors
        // For now, check if any pipeline is past DRAFT status
        const hasConfigured = pipelines.some(
          (p: any) => p.status !== 'DRAFT'
        );

        setState(hasConfigured ? 'complete' : 'no-monitors');
      } catch {
        setState('complete'); // Don't show banner on error
      }
    }

    checkSetup();
  }, []);

  function handleDismiss() {
    localStorage.setItem(DISMISSED_KEY, 'true');
    setDismissed(true);
  }

  if (dismissed || state === 'loading' || state === 'complete') return null;

  const config = {
    'no-warehouse': {
      title: 'Connect your first warehouse to start monitoring',
      action: 'Set Up Pipeline',
      href: '/dashboard/pipeline',
    },
    'no-monitors': {
      title: 'Set up your first monitor to start watching your data',
      action: 'Configure Pipeline',
      href: '/dashboard/pipeline',
    },
  };

  const { title, action, href } = config[state];

  return (
    <div className="mb-6 rounded-xl border border-[var(--accent)]/20 bg-[var(--accent)]/5 p-4 flex items-center justify-between gap-4">
      <p className="text-sm text-[var(--text)]">{title}</p>
      <div className="flex items-center gap-2 shrink-0">
        <Button size="sm" onClick={() => router.push(href)}>
          {action}
        </Button>
        <button
          onClick={handleDismiss}
          className="text-xs text-[var(--muted)] hover:text-[var(--text)] px-2 py-1"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add SetupBanner to the dashboard page**

In `app/(dashboard)/dashboard/page.tsx`, import and render `SetupBanner` at the top of the page content:

```typescript
import { SetupBanner } from '../../../components/dashboard/SetupBanner';
```

Add `<SetupBanner />` as the first element inside the page's return.

- [ ] **Step 3: Commit**

```bash
git add components/dashboard/SetupBanner.tsx app/\(dashboard\)/dashboard/page.tsx
git commit -m "feat: dashboard setup banner for incomplete onboarding"
```

---

## Task 12: End-to-End Verification

- [ ] **Step 1: Run the build to check for TypeScript errors**

Run: `npm run type-check`
Expected: No errors related to onboarding files.

- [ ] **Step 2: Run full build**

Run: `npm run build`
Expected: Build succeeds.

- [ ] **Step 3: Test the full new-user flow**

1. Start dev server: `npm run dev`
2. Go to `/signup`, create a new user
3. Verify redirect to `/onboarding`
4. Complete Step 1 (profile with timezone)
5. Complete Step 2 (company info)
6. Skip Step 3 (warehouse)
7. Verify redirect to `/dashboard`
8. Verify SetupBanner shows "Connect your first warehouse"
9. Check DB: user has timezone, role, onboardingCompleted=true; org has companySize

- [ ] **Step 4: Test existing user flow**

1. Log in as a previously existing user
2. Verify goes directly to dashboard (not onboarding)
3. Verify timezone in session (check via browser dev tools → Application → Cookies)

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address any issues from end-to-end testing"
```
