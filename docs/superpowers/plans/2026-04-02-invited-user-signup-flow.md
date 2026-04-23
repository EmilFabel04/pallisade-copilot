# Invited User Signup Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Invited users sign up, complete only the profile step, and land on the dashboard with pipeline access — skipping org/warehouse/monitor onboarding.

**Architecture:** Invite redemption happens in the signup API (for password users) and auth.ts signIn callback (for credentials + OAuth). Pipeline access is granted during redemption. The onboarding page detects users who already have an org and shows only the profile step.

**Tech Stack:** Next.js API routes, NextAuth callbacks, Prisma transactions

**Spec:** `docs/superpowers/specs/2026-03-27-invited-user-signup-flow-design.md`

---

### Task 1: Fix signup page to read `?invite=` param

**Files:**
- Modify: `app/(auth)/signup/page.tsx`

- [ ] **Step 1: Change param from `token` to `invite`**

In `app/(auth)/signup/page.tsx`, find line 23:

```typescript
  const inviteToken = searchParams.get('token');
```

Replace with:

```typescript
  const inviteToken = searchParams.get('invite');
```

- [ ] **Step 2: Commit**

```bash
git add "app/(auth)/signup/page.tsx"
git commit -m "fix: read ?invite= param instead of ?token= on signup page"
```

---

### Task 2: Redeem invite during password signup

**Files:**
- Modify: `app/api/auth/signup/route.ts`

- [ ] **Step 1: Replace the full signup route with invite-aware version**

Replace the entire content of `app/api/auth/signup/route.ts` with:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import prisma from '../../../../lib/db';
import { hashPassword } from '../../../../lib/passwords';

/**
 * Parse pipeline access from a TeamInvite's personalNote field.
 * Returns the array if valid, null otherwise.
 */
function parsePipelineAccess(
  personalNote: string | null,
): Array<{ pipelineId: string; accessLevel: string }> | null {
  if (!personalNote) return null;
  try {
    const parsed = JSON.parse(personalNote);
    if (parsed?.pipelineAccess && Array.isArray(parsed.pipelineAccess)) {
      return parsed.pipelineAccess;
    }
  } catch {
    // Plain text note, not JSON
  }
  return null;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password, name, organizationName } = body;

    // Validation
    if (!email || !password) {
      return NextResponse.json(
        { error: 'Email and password are required' },
        { status: 400 }
      );
    }

    if (password.length < 8) {
      return NextResponse.json(
        { error: 'Password must be at least 8 characters' },
        { status: 400 }
      );
    }

    // Check if user already exists
    const existingUser = await prisma.user.findUnique({
      where: { email },
    });

    if (existingUser) {
      return NextResponse.json(
        { error: 'An account with this email already exists' },
        { status: 400 }
      );
    }

    // Hash password
    const passwordHash = await hashPassword(password);

    // Check for a pending invite matching this email
    const invite = await prisma.teamInvite.findFirst({
      where: {
        email: email.toLowerCase(),
        status: 'PENDING',
        expiresAt: { gt: new Date() },
      },
    });

    // Create user and handle org/invite in a transaction
    const result = await prisma.$transaction(async (tx) => {
      // Create user first
      const user = await tx.user.create({
        data: {
          email: email.toLowerCase(),
          name,
          passwordHash,
        },
        select: {
          id: true,
          email: true,
          name: true,
          createdAt: true,
        },
      });

      let organization = null;

      if (invite) {
        // ---- Invite path: join existing org ----
        await tx.teamMember.create({
          data: {
            userId: user.id,
            organizationId: invite.organizationId,
            role: invite.role,
            status: 'ACTIVE',
            joinedAt: new Date(),
          },
        });

        await tx.user.update({
          where: { id: user.id },
          data: { organizationId: invite.organizationId },
        });

        await tx.teamInvite.update({
          where: { id: invite.id },
          data: { status: 'ACCEPTED', respondedAt: new Date() },
        });

        // Grant pipeline access
        const pipelineAccess = parsePipelineAccess(invite.personalNote);
        if (pipelineAccess && pipelineAccess.length > 0) {
          // Use admin-specified pipelines
          for (const pa of pipelineAccess) {
            await tx.pipelineAccess.create({
              data: {
                userId: user.id,
                pipelineId: pa.pipelineId,
                accessLevel: pa.accessLevel === 'EDITOR' ? 'EDITOR' : pa.accessLevel === 'OWNER' ? 'OWNER' : 'VIEWER',
                grantedBy: invite.invitedById || user.id,
              },
            });
          }
        } else {
          // Default: VIEWER access to all org pipelines
          const orgPipelines = await tx.pipelineStack.findMany({
            where: { organizationId: invite.organizationId },
            select: { id: true },
          });
          for (const pipeline of orgPipelines) {
            await tx.pipelineAccess.create({
              data: {
                userId: user.id,
                pipelineId: pipeline.id,
                accessLevel: 'VIEWER',
                grantedBy: invite.invitedById || user.id,
              },
            });
          }
        }

        organization = await tx.organization.findUnique({
          where: { id: invite.organizationId },
          select: { id: true, name: true },
        });
      } else if (organizationName) {
        // ---- Normal path: create new org ----
        organization = await tx.organization.create({
          data: { name: organizationName },
        });

        await tx.teamMember.create({
          data: {
            userId: user.id,
            organizationId: organization.id,
            role: 'OWNER',
            status: 'ACTIVE',
            joinedAt: new Date(),
          },
        });

        await tx.user.update({
          where: { id: user.id },
          data: { organizationId: organization.id },
        });
      }

      return { user, organization };
    });

    return NextResponse.json({
      message: 'Account created successfully',
      user: result.user,
      organization: result.organization
        ? { id: result.organization.id, name: result.organization.name }
        : null,
    });
  } catch (error) {
    console.error('Signup error:', error);
    return NextResponse.json(
      { error: 'An error occurred during signup' },
      { status: 500 }
    );
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/api/auth/signup/route.ts
git commit -m "feat: redeem team invite during password signup with pipeline access"
```

---

### Task 3: Extend auth.ts invite redemption to credentials provider + pipeline access

**Files:**
- Modify: `auth.ts`

- [ ] **Step 1: Add invite check to the credentials provider block**

In `auth.ts`, find the credentials provider signIn block (around lines 85-101):

```typescript
      if (account?.provider === 'credentials') {
        // Check SSO enforcement for the user's org
        const dbUser = await prisma.user.findUnique({
          where: { id: user.id! },
          include: { organization: true },
        });

        if (dbUser?.organization?.authPolicy === 'SSO_ONLY') {
          // Check grace period
          const graceUntil = dbUser.organization.authPolicyGraceUntil;
          if (!graceUntil || new Date() > graceUntil) {
            return '/login?error=SSORequired';
          }
        }

        return true;
      }
```

Replace with:

```typescript
      if (account?.provider === 'credentials') {
        const dbUser = await prisma.user.findUnique({
          where: { id: user.id! },
          include: { organization: true },
        });

        // Check SSO enforcement for the user's org
        if (dbUser?.organization?.authPolicy === 'SSO_ONLY') {
          const graceUntil = dbUser.organization.authPolicyGraceUntil;
          if (!graceUntil || new Date() > graceUntil) {
            return '/login?error=SSORequired';
          }
        }

        // If user has no org, check for a pending invite (covers existing users
        // who were invited after creating their account)
        if (!dbUser?.organizationId && dbUser?.email) {
          const invite = await prisma.teamInvite.findFirst({
            where: {
              email: dbUser.email,
              status: 'PENDING',
              expiresAt: { gt: new Date() },
            },
          });

          if (invite) {
            await prisma.$transaction(async (tx) => {
              await tx.teamMember.create({
                data: {
                  userId: dbUser.id,
                  organizationId: invite.organizationId,
                  role: invite.role,
                  status: 'ACTIVE',
                  joinedAt: new Date(),
                },
              });
              await tx.user.update({
                where: { id: dbUser.id },
                data: { organizationId: invite.organizationId },
              });
              await tx.teamInvite.update({
                where: { id: invite.id },
                data: { status: 'ACCEPTED', respondedAt: new Date() },
              });

              // Grant pipeline access — VIEWER on all org pipelines
              const orgPipelines = await tx.pipelineStack.findMany({
                where: { organizationId: invite.organizationId },
                select: { id: true },
              });
              for (const pipeline of orgPipelines) {
                await tx.pipelineAccess.upsert({
                  where: {
                    userId_pipelineId: {
                      userId: dbUser.id,
                      pipelineId: pipeline.id,
                    },
                  },
                  create: {
                    userId: dbUser.id,
                    pipelineId: pipeline.id,
                    accessLevel: 'VIEWER',
                    grantedBy: invite.invitedById || dbUser.id,
                  },
                  update: {},
                });
              }
            });
          }
        }

        return true;
      }
```

- [ ] **Step 2: Add pipeline access granting to the existing OAuth invite redemption block**

Find the existing OAuth invite redemption transaction (around lines 136-154):

```typescript
        // Redeem invite in a transaction
        const userId = existingUser?.id || user.id;
        await prisma.$transaction([
          prisma.teamMember.create({
            data: {
              userId: userId as string,
              organizationId: invite.organizationId,
              role: invite.role,
              status: 'ACTIVE',
              joinedAt: new Date(),
            },
          }),
          prisma.user.update({
            where: { id: userId as string },
            data: { organizationId: invite.organizationId },
          }),
          prisma.teamInvite.update({
            where: { id: invite.id },
            data: { status: 'ACCEPTED', respondedAt: new Date() },
          }),
        ]);
```

Replace with:

```typescript
        // Redeem invite in a transaction
        const userId = (existingUser?.id || user.id) as string;
        await prisma.$transaction(async (tx) => {
          await tx.teamMember.create({
            data: {
              userId,
              organizationId: invite.organizationId,
              role: invite.role,
              status: 'ACTIVE',
              joinedAt: new Date(),
            },
          });
          await tx.user.update({
            where: { id: userId },
            data: { organizationId: invite.organizationId },
          });
          await tx.teamInvite.update({
            where: { id: invite.id },
            data: { status: 'ACCEPTED', respondedAt: new Date() },
          });

          // Grant pipeline access — VIEWER on all org pipelines
          const orgPipelines = await tx.pipelineStack.findMany({
            where: { organizationId: invite.organizationId },
            select: { id: true },
          });
          for (const pipeline of orgPipelines) {
            await tx.pipelineAccess.upsert({
              where: {
                userId_pipelineId: {
                  userId,
                  pipelineId: pipeline.id,
                },
              },
              create: {
                userId,
                pipelineId: pipeline.id,
                accessLevel: 'VIEWER',
                grantedBy: invite.invitedById || userId,
              },
              update: {},
            });
          }
        });
```

- [ ] **Step 3: Commit**

```bash
git add auth.ts
git commit -m "feat: extend invite redemption to credentials provider + grant pipeline access"
```

---

### Task 4: Shorten onboarding for invited users (profile step only)

**Files:**
- Modify: `app/(onboarding)/onboarding/page.tsx`

- [ ] **Step 1: Add invited-user detection state**

In `app/(onboarding)/onboarding/page.tsx`, find the state declarations (around lines 15-25). After the existing state variables, add:

```typescript
  const [isInvitedUser, setIsInvitedUser] = useState(false);
```

- [ ] **Step 2: Detect invited user in the onboarding state loader**

Find the `loadOnboardingState` function. Inside it, after the onboarding progress check (around line 55, after the first `try/catch`), add a check for the org:

Find:
```typescript
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
```

Replace with:

```typescript
      // Pre-fill name from session
      setUserName((session?.user as any)?.name || '');

      // Load org name if exists — and detect invited users
      try {
        const orgRes = await fetch('/api/organization');
        if (orgRes.ok) {
          const data = await orgRes.json();
          if (data.organization?.name) {
            setOrgName(data.organization.name);
            // User already has an org but hasn't completed onboarding = invited user
            const savedStep = (await fetch('/api/user/onboarding').then(r => r.json()).catch(() => null))?.user?.onboardingStep ?? 0;
            if (savedStep === 0) {
              setIsInvitedUser(true);
            }
          }
        }
      } catch {
        // No org yet
      }
```

Wait — this would double-fetch the onboarding state. Let me restructure more cleanly. Actually, let me just use the org presence as the signal since the onboarding state is already loaded above.

Find the full `loadOnboardingState` function body and replace:

```typescript
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
```

With:

```typescript
      // Pre-fill name from session
      setUserName((session?.user as any)?.name || '');

      // Check if user already has an org (invited user)
      try {
        const orgRes = await fetch('/api/organization');
        if (orgRes.ok) {
          const data = await orgRes.json();
          if (data.organization?.name) {
            setOrgName(data.organization.name);
            // User has org but hasn't completed onboarding → joined via invite
            if (!data.user?.onboardingCompleted) {
              setIsInvitedUser(true);
            }
          }
        }
      } catch {
        // No org yet — normal new user flow
      }
```

- [ ] **Step 3: Create a profile-complete handler for invited users**

Find the `handleProfileComplete` function (around line 87). After it (after the closing `}`), add:

```typescript
  async function handleInvitedProfileComplete(data: { name: string; timezone: string; role: string }) {
    setIsLoading(true);
    try {
      const res = await fetch('/api/user/profile', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error('Failed to save profile');

      // Mark onboarding as fully complete — skip steps 2-4
      await saveStep(4, true);
      await update();
      router.push('/dashboard');
      router.refresh();
    } catch (err) {
      console.error('Profile save error:', err);
    } finally {
      setIsLoading(false);
    }
  }
```

- [ ] **Step 4: Render profile-only flow for invited users**

Find the return JSX block. Replace the step rendering section (around lines 198-230):

Find:
```typescript
  return (
    <div className="w-full max-w-md">
      <div className="text-center mb-6">
        <img src="/pallisade_emblem.svg" alt="Pallisade" className="w-14 h-14 mx-auto mb-3" />
      </div>
      <StepProgress currentStep={currentStep} completedSteps={completedSteps} />

      {currentStep === 1 && (
        <ProfileStep
          initialName={userName}
          onComplete={handleProfileComplete}
          isLoading={isLoading}
        />
      )}
```

Replace with:

```typescript
  return (
    <div className="w-full max-w-md">
      <div className="text-center mb-6">
        <img src="/pallisade_emblem.svg" alt="Pallisade" className="w-14 h-14 mx-auto mb-3" />
      </div>

      {isInvitedUser ? (
        <>
          <div className="text-center mb-6">
            <h2 className="text-lg font-semibold text-[var(--text)]">Welcome to {orgName}!</h2>
            <p className="text-sm text-[var(--muted)] mt-1">Set up your profile to get started</p>
          </div>
          <ProfileStep
            initialName={userName}
            onComplete={handleInvitedProfileComplete}
            isLoading={isLoading}
          />
        </>
      ) : (
        <>
          <StepProgress currentStep={currentStep} completedSteps={completedSteps} />

          {currentStep === 1 && (
            <ProfileStep
              initialName={userName}
              onComplete={handleProfileComplete}
              isLoading={isLoading}
            />
          )}
```

Then find the closing `</div>` at the very end of the return statement and add the closing tags. The full structure should end with:

```typescript
        </>
      )}
    </div>
```

Instead of the current:

```typescript
    </div>
```

- [ ] **Step 5: Commit**

```bash
git add "app/(onboarding)/onboarding/page.tsx"
git commit -m "feat: shorten onboarding to profile-only for invited users"
```

---

### Task 5: (Resolved) PipelineAccess field names verified

The PipelineAccess model uses `pipelineId` and `@@unique([userId, pipelineId])`. All code in Tasks 2 and 3 already uses the correct field names. No action needed.

---

### Task 6: Final verification

- [ ] **Step 1: Verify TypeScript compiles**

Run: `npx tsc --noEmit --pretty 2>&1 | grep -v "vitest" | grep "error" | head -20`
Expected: No errors in changed files.

- [ ] **Step 2: Test the flow manually**

1. Create an invite from the team page for a test email
2. Open the invite link (`/signup?invite=...`)
3. Sign up with password
4. Verify you land on onboarding with only the profile step
5. Complete profile → verify redirect to dashboard
6. Verify you have pipeline access (can see pipelines)

- [ ] **Step 3: Commit any fixes**

```bash
git status
```
