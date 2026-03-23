# OAuth SSO Design Spec

## Problem

Users can only sign in with email/password. The Google, GitHub, and Microsoft OAuth buttons exist on the login page but are non-functional — the providers are conditionally registered based on environment variables that aren't set, resulting in 302 redirects back to the login page. There is no enterprise SSO support (OIDC), no way to enforce SSO at the org level, and no account linking. The platform is on NextAuth v4, which has limited support for dynamic providers needed for per-org OIDC.

## Solution

Migrate from NextAuth v4 to Auth.js v5 and implement a full OAuth SSO system with four providers (Google, GitHub, Microsoft, per-org OIDC), invite-only onboarding for OAuth users, account linking, enforced SSO, and self-service OIDC configuration for organizations.

## Approach

**Auth.js v5 migration with incremental feature addition.** Migrate the auth infrastructure first (mechanical but wide-reaching), then layer on OAuth providers, invite-only gating, account linking, enforced SSO, and per-org OIDC in that order. Each layer builds on the previous one.

## Auth.js v5 Migration

### New Auth Config (`auth.ts` at project root)

Replaces `lib/auth.ts`. Exports `auth()`, `signIn()`, `signOut()`, and `handlers`.

```typescript
// auth.ts
import NextAuth from 'next-auth'
import { PrismaAdapter } from '@auth/prisma-adapter'
import Credentials from 'next-auth/providers/credentials'
import Google from 'next-auth/providers/google'
import GitHub from 'next-auth/providers/github'
import MicrosoftEntraID from 'next-auth/providers/microsoft-entra-id'
import prisma from '@/lib/db'

export const { auth, handlers, signIn, signOut } = NextAuth({
  adapter: PrismaAdapter(prisma),
  session: { strategy: 'jwt' },
  pages: { signIn: '/login', error: '/login' },
  providers: [
    Credentials({ /* same authorize logic */ }),
    ...(process.env.GOOGLE_CLIENT_ID ? [Google({ ... })] : []),
    ...(process.env.GITHUB_CLIENT_ID ? [GitHub({ ... })] : []),
    ...(process.env.MICROSOFT_CLIENT_ID ? [MicrosoftEntraID({ ... })] : []),
    // Per-org OIDC loaded dynamically — see Per-Org OIDC section
  ],
  callbacks: {
    signIn: /* invite-only + SSO enforcement checks */,
    jwt: /* embed userId, organizationId */,
    session: /* expose id, organizationId */,
  },
})
```

### Route Handler

`app/api/auth/[...nextauth]/route.ts` simplifies to:

```typescript
export { handlers as GET, handlers as POST } from '@/auth'
```

### Middleware (`middleware.ts` — new file)

Protects dashboard routes at the edge. Replaces per-layout `getServerSession` checks.

```typescript
export { auth as middleware } from '@/auth'

export const config = {
  matcher: ['/dashboard/:path*', '/onboarding/:path*'],
}
```

The `auth` middleware redirects unauthenticated users to `/login`. Public routes (`/login`, `/signup`, `/api/auth/*`) are excluded via the matcher.

### API Route Migration (~83 files)

Mechanical find-and-replace across all API routes:

```typescript
// Before (v4)
import { getServerSession } from 'next-auth'
import { authOptions } from '@/lib/auth'
const session = await getServerSession(authOptions)

// After (v5)
import { auth } from '@/auth'
const session = await auth()
```

### Client-Side Changes

Minimal. `useSession`, `signIn`, `signOut` imports remain from `next-auth/react`. `SessionProvider` stays the same. No changes needed to the ~13 client components.

### Old `lib/auth.ts`

Removed after migration. Password helpers (`hashPassword`, `verifyPassword`) move to `lib/passwords.ts` or stay in `lib/auth.ts` as a utility-only file (no more `authOptions` export).

## OAuth Providers

### Platform-Level Providers

Four providers, all conditional on environment variables:

| Provider | Env Vars | Scopes |
|----------|----------|--------|
| Google | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | `openid email profile` |
| GitHub | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | `read:user user:email` |
| Microsoft | `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_TENANT_ID` | `openid email profile User.Read` |
| Per-org OIDC | Stored in DB per org | Configurable, defaults to `openid email profile` |

Note: `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` are for **login**. The existing `GITHUB_INTEGRATION_CLIENT_ID` / `GITHUB_INTEGRATION_CLIENT_SECRET` remain separate (used for repo access integration).

### Login Page UI

- Google, GitHub, Microsoft buttons (shown when respective env vars are set)
- "Sign in with SSO" button → email input → resolves org OIDC provider → redirects to IdP
- Error states: `NoInvite` ("You need an invitation to join an organization"), `SSORequired` ("Your organization requires SSO sign-in")

## Invite-Only OAuth Onboarding

### Sign-In Flow for New OAuth Users

1. User clicks an OAuth provider button on `/login`
2. Auth.js completes the OAuth flow and calls the `signIn` callback
3. **`signIn` callback** checks if the user already exists in the database:
   - **Existing user with org** → allow sign-in (account linking handled by Prisma adapter)
   - **New user** → check for a `TeamInvite` with matching email:
     - **Invite found** → allow sign-in
     - **No invite** → block sign-in, redirect to `/login?error=NoInvite`
4. **`jwt` callback** (on first OAuth login with valid invite):
   - Looks up `TeamInvite` by email
   - Creates `TeamMember` record with the invited role
   - Sets `user.organizationId` to the invite's org
   - Marks invite as accepted (`status: ACCEPTED`, `joinedAt: now`)
   - Embeds `organizationId` in the JWT

### Invite Flow Changes

The existing `POST /api/team/invite` endpoint needs no structural changes. The invite email template should mention OAuth sign-in as an option alongside password setup.

## Account Linking

### Connected Accounts UI (User Settings)

New section in user account/profile settings:

- Lists all linked providers with their email/username
- **Connect** button per unlinked provider → triggers `signIn('provider')` which Auth.js links to the current user
- **Disconnect** button per linked provider → deletes the `Account` record
- **Safety rule**: cannot disconnect the last auth method. If user has no `passwordHash` and only one `Account`, disconnect is blocked with message: "Set a password or connect another provider first."

### No Auto-Linking

Auto-linking by email (where signing in with Google auto-merges with an existing GitHub account sharing the same email) is **disabled**. Linking only happens when:
- An authenticated user explicitly connects a provider from settings
- An existing user initiates an OAuth sign-in themselves (they're the same person)

### Database

No schema changes. The existing `Account` model supports multiple accounts per user via composite unique on `(provider, providerAccountId)`.

## Enforced SSO

### Schema Change

New field on the `Organization` model:

| Field | Type | Default |
|-------|------|---------|
| `authPolicy` | `AuthPolicy` enum | `FLEXIBLE` |

```prisma
enum AuthPolicy {
  FLEXIBLE   // Any auth method allowed
  SSO_ONLY   // OAuth/OIDC only, password login disabled
}

model Organization {
  // ... existing fields
  authPolicy  AuthPolicy @default(FLEXIBLE)
}
```

### Enforcement Points

**`signIn` callback:**
- If user's org has `authPolicy: SSO_ONLY` and the provider is `credentials`, block sign-in
- Redirect to `/login?error=SSORequired`

**Signup page:**
- If arriving from an invite link whose org is `SSO_ONLY`, hide password fields
- Show only OAuth buttons with message: "Your organization uses SSO"

**Account settings:**
- If org is `SSO_ONLY`, hide "set password" option
- Show info: "Your organization requires SSO sign-in"

### Admin UI (Org Settings → Authentication Tab)

- Toggle: "Require SSO for all members"
- **Pre-enable safety checks:**
  1. At least one OAuth provider must be configured (env vars or org OIDC)
  2. The org owner performing the action must have a linked OAuth account
  3. Warning showing how many members don't have linked OAuth accounts
- Optional grace period: "Allow password login for 7 days" — stores `authPolicyGraceUntil: DateTime?` on the org, enforcement skipped until that date
- Only `OWNER` role can change `authPolicy`

## Per-Org OIDC Configuration

### Schema

New model:

```prisma
model OrgOidcConfig {
  id              String       @id @default(cuid())
  organizationId  String       @unique
  organization    Organization @relation(fields: [organizationId], references: [id], onDelete: Cascade)
  issuerUrl       String       // e.g., https://acme.okta.com
  clientId        String
  clientSecret    String       // Encrypted via lib/crypto.ts
  scopes          String       @default("openid email profile")
  displayName     String       @default("SSO") // Button label
  enabled         Boolean      @default(true)
  createdAt       DateTime     @default(now())
  updatedAt       DateTime     @updatedAt
}
```

Add relation to `Organization`:

```prisma
model Organization {
  // ... existing fields
  oidcConfig  OrgOidcConfig?
}
```

### OIDC Admin UI (Org Settings → Authentication Tab)

Form fields:
- **Issuer URL** — text input, validated against `/.well-known/openid-configuration`
- **Client ID** — text input
- **Client Secret** — password input, encrypted before storage
- **Display Name** — text input (default "SSO"), used as button label
- **Scopes** — text input (default `openid email profile`)
- **Test Connection** button — validates the config by hitting the discovery endpoint
- **Enable/Disable** toggle

### API Endpoints

- `GET /api/organization/oidc` — returns config (client secret masked)
- `PUT /api/organization/oidc` — create/update config (OWNER only)
- `DELETE /api/organization/oidc` — remove config (OWNER only)
- `POST /api/organization/oidc/test` — validate issuer URL and client credentials
- `POST /api/auth/sso/lookup` — public endpoint: accepts email, returns whether org has OIDC config (no sensitive data exposed, just `{ hasOidc: true, displayName: "Okta" }`)

### Sign-In Flow

1. User clicks "Sign in with SSO" on `/login`
2. Email input appears — user enters their email
3. Frontend calls `POST /api/auth/sso/lookup` with the email
4. If org has OIDC: frontend sets a cookie `oidc_org_id={orgId}` and calls `signIn('oidc', { callbackUrl })`
5. Auth.js `providers` function reads the cookie, loads `OrgOidcConfig` from DB, constructs a dynamic OIDC provider
6. User is redirected to the IdP, authenticates, and returns via callback
7. Same invite-only checks apply in the `signIn` callback

### Security

- Client secrets encrypted at rest (AES-256-GCM via `lib/crypto.ts`)
- OIDC config only editable by `OWNER` role
- SSO lookup endpoint returns minimal info (boolean + display name, no URLs or credentials)
- State parameter and PKCE handled by Auth.js

## UI Summary

### Login Page (`/login`)

```
┌──────────────────────────────┐
│        Welcome back          │
│  Sign in to your Pallisade   │
│                              │
│  [Email        ]             │
│  [Password     ]             │
│  □ Remember me   Forgot?     │
│  [     Sign in            ]  │
│                              │
│  ──── Or continue with ────  │
│                              │
│  [ Google ]  [ GitHub ]      │
│  [ Microsoft ]               │
│                              │
│  [    Sign in with SSO    ]  │
│                              │
│  Don't have an account?      │
└──────────────────────────────┘
```

### Org Settings → Authentication Tab (new)

Three sections:
1. **Auth Policy** — Flexible / Require SSO toggle with safety warnings
2. **OIDC Provider** — Configuration form with test connection
3. **Member Auth Status** — Table showing each member's linked providers

### User Settings → Connected Accounts (new section)

List of providers with connect/disconnect buttons.

## Migration Strategy

### Database Migration

1. Add `AuthPolicy` enum and `authPolicy` field to `Organization` (default `FLEXIBLE`)
2. Add `authPolicyGraceUntil` nullable DateTime to `Organization`
3. Create `OrgOidcConfig` table
4. No data migration needed — all existing orgs default to `FLEXIBLE`

### Existing Users

- No impact. Existing email/password users continue to work unchanged.
- OAuth becomes available as an additional sign-in option once env vars are configured.

## Testing

- **Unit tests**: `signIn` callback (invite check, SSO enforcement), `jwt` callback (invite redemption, org association)
- **Integration tests**: full OAuth flow with mocked providers, account linking, OIDC dynamic provider loading
- **Edge cases**: last auth method disconnect blocked, SSO enforcement with grace period, OIDC config validation failures, invite-only rejection for new OAuth users
- **Manual testing**: Google, GitHub, Microsoft OAuth flows end-to-end; OIDC with a test Okta/Auth0 instance

## Environment Variables

### New Variables

| Variable | Purpose |
|----------|---------|
| `GOOGLE_CLIENT_ID` | Google OAuth (login) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth (login) |
| `GITHUB_CLIENT_ID` | GitHub OAuth (login) — separate from integration |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth (login) — separate from integration |
| `MICROSOFT_CLIENT_ID` | Microsoft Entra ID OAuth |
| `MICROSOFT_CLIENT_SECRET` | Microsoft Entra ID OAuth |
| `MICROSOFT_TENANT_ID` | Microsoft Entra ID tenant (use `common` for multi-tenant) |

### Existing Variables (unchanged)

| Variable | Purpose |
|----------|---------|
| `GITHUB_INTEGRATION_CLIENT_ID` | GitHub repo integration (not login) |
| `GITHUB_INTEGRATION_CLIENT_SECRET` | GitHub repo integration (not login) |
| `NEXTAUTH_SECRET` | Session encryption (renamed to `AUTH_SECRET` in v5, both supported) |
| `NEXTAUTH_URL` | Base URL (auto-detected in v5, can be removed) |
| `ENCRYPTION_KEY` | AES-256-GCM for OIDC client secrets |
