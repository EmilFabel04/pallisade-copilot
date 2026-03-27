# Invited User Signup Flow — Design Spec

## Problem

When an admin invites a team member, the invited user goes through the full 4-step onboarding (profile, company, warehouse, monitor) — identical to a brand new user creating their own org. Steps 2-4 are redundant because the org and pipeline already exist. Additionally, for password-based signups, the invite is never redeemed — the user ends up creating a separate org instead of joining the inviting org.

## Goal

Invited users should sign up, complete only the profile step (name, timezone, role), and land on the dashboard with access to the existing org's pipelines.

## Design Decisions

- **Profile step kept**: timezone is needed for scheduling, role tailors the UI
- **Pipeline access on join**: if the admin specified pipelines in the invite, grant those; otherwise grant VIEWER on all org pipelines
- **Param standardized**: `?invite=` everywhere (email links already use this)

## Architecture

### 1. Redeem invite during password signup

**File: `app/api/auth/signup/route.ts`**

After creating the User record, check for a pending `TeamInvite` matching the user's email. If found, in the same transaction:

1. Create `TeamMember` with the invite's role and status `ACTIVE`
2. Set `User.organizationId` to the invite's org
3. Mark `TeamInvite.status` = `ACCEPTED`, set `respondedAt`
4. Grant pipeline access (see section below)

This mirrors the existing OAuth redemption in `auth.ts` but happens at the signup API level for credentials users.

### 2. Redeem invite for credentials signIn in auth.ts

The `signIn` callback in `auth.ts` currently only redeems invites for OAuth providers. Add the same check for the `credentials` provider so that existing users who already have an account but sign in after receiving an invite also get redeemed.

The check: if user has no `organizationId`, look for a pending invite matching their email. If found, redeem it (same transaction pattern as OAuth path).

### 3. Shortened onboarding for invited users

**File: `app/(onboarding)/onboarding/page.tsx`**

On load, the onboarding page already fetches the user's state. Add a check:

- If `user.organizationId` is set AND `user.onboardingCompleted` is false → user joined via invite
- Show only Step 1 (ProfileStep: name, timezone, role)
- On completion, set `onboardingCompleted: true` and `onboardingStep: 4`
- Redirect to `/dashboard`

Steps 2 (company), 3 (warehouse), and 4 (monitor) are skipped entirely.

### 4. Pipeline access granting

**During invite redemption (in signup route and auth.ts):**

The invite's `personalNote` field may contain a JSON object with pipeline access:
```json
{
  "note": "Welcome!",
  "pipelineAccess": [
    { "pipelineId": "xxx", "accessLevel": "EDITOR" }
  ]
}
```

Logic:
1. Parse `personalNote` — if it's valid JSON with a `pipelineAccess` array, use those selections
2. If no pipeline access specified (or personalNote is plain text), query all `PipelineStack` records for the org and grant `VIEWER` access to each
3. Create `PipelineAccess` records with `grantedBy` set to the invite sender's userId (`invitedById`)

### 5. Signup page param fix

**File: `app/(auth)/signup/page.tsx`**

Change `searchParams.get('token')` to `searchParams.get('invite')` to match what the invite email sends (`/signup?invite={token}`).

## Files Changed

| File | Change |
|------|--------|
| `app/api/auth/signup/route.ts` | Check for pending invite after user creation; redeem in transaction (TeamMember, org link, pipeline access) |
| `auth.ts` | Extend invite redemption to credentials provider in signIn callback; add pipeline access granting |
| `app/(onboarding)/onboarding/page.tsx` | Detect invited user (has orgId, not onboarded); show profile step only, then complete |
| `app/(auth)/signup/page.tsx` | Change `?token=` to `?invite=` param reading |

## Error Handling

- **Invite expired/revoked**: signup proceeds normally — user goes through full onboarding and creates their own org (same as no invite)
- **Pipeline access grant failure**: non-fatal, logged. User can be granted access manually by admin
- **personalNote parse failure**: treat as no pipeline access specified, fall back to VIEWER on all pipelines

## Out of Scope

- Dedicated pipeline access field on TeamInvite model (continue using personalNote JSON for now)
- Email notification when invited user joins
- Invite-specific welcome page/dashboard
- Bulk invite changes
