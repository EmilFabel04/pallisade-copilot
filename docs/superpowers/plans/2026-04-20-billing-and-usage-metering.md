# Billing & Usage Metering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add self-serve billing with Stripe payments, an internal Postgres usage ledger, and enforcement gates for tokens, storage, and team members.

**Architecture:** Stripe handles payment collection and subscription lifecycle. Internal Postgres tables (BillingSubscription, UsageLedger, CreditBalance) provide real-time usage tracking. Token enforcement runs pre/post-request in the copilot chat route. The billing UI replaces the existing hardcoded stub in Settings > Billing.

**Tech Stack:** Stripe SDK (`stripe`), Prisma (existing), Next.js API routes (existing pattern), existing notification system (`lib/notifications.ts`)

**Spec:** `docs/superpowers/specs/2026-04-19-billing-and-usage-metering-design.md`

**Deferred to follow-up:** Storage scan cron (`/api/billing/storage-scan/route.ts`) — requires querying customer warehouse adapters for table sizes. Will be a separate task once the core billing loop is verified. Integration-creation storage enforcement gate will be added alongside it.

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `lib/billing.ts` | Billing state loader, caching, enforcement checks, token deduction logic |
| `app/api/billing/checkout/route.ts` | Create Stripe Checkout sessions (subscription + credit top-ups) |
| `app/api/billing/portal/route.ts` | Create Stripe Customer Portal sessions |
| `app/api/billing/subscription/route.ts` | GET current subscription + usage + credits |
| `app/api/billing/usage/route.ts` | GET detailed usage breakdown |
| `app/api/billing/webhooks/route.ts` | Stripe webhook handler (all events) |
| `components/settings/BillingSettings.tsx` | Full billing tab UI (plan, usage bars, credits, invoices) |
| `components/dashboard/BillingBanner.tsx` | Global warning banners (token limit, payment failed) |

### Modified files

| File | Change |
|---|---|
| `prisma/schema.prisma` | Add BillingSubscription, UsageLedger, CreditBalance, CreditPurchase, ProcessedWebhookEvent models; update Plan enum |
| `app/api/copilot/chat/route.ts` | Add pre-request billing check + post-response token deduction |
| `app/api/team/invite/route.ts` | Add member limit enforcement |
| `app/(dashboard)/dashboard/settings/page.tsx` | Replace hardcoded billing tab with BillingSettings component |
| `components/dashboard/Header.tsx` | Add BillingBanner |
| `lib/notifications.ts` | Add billing notification helpers |
| `package.json` | Add `stripe` dependency |

---

### Task 1: Install Stripe SDK and add env vars

**Files:**
- Modify: `package.json`
- Create: `.env.example` (update only — add billing vars)

- [ ] **Step 1: Install stripe**

```bash
npm install stripe
```

- [ ] **Step 2: Add env vars to .env.example**

Add these lines to the existing `.env.example`:

```env
# Billing (Stripe)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_GROWTH_PRICE_ID=price_...
STRIPE_BUSINESS_PRICE_ID=price_...
STRIPE_CREDIT_5M_PRICE_ID=price_...
STRIPE_CREDIT_20M_PRICE_ID=price_...
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

- [ ] **Step 3: Commit**

```bash
git add package.json package-lock.json .env.example
git commit -m "chore: add stripe SDK and billing env vars"
```

---

### Task 2: Prisma schema — billing models and Plan enum migration

**Files:**
- Modify: `prisma/schema.prisma`

- [ ] **Step 1: Update the Plan enum**

In `prisma/schema.prisma`, replace the existing `Plan` enum (around line 949):

```prisma
enum Plan {
  STARTER      // Legacy — maps to GROWTH
  PROFESSIONAL // Legacy — maps to BUSINESS
  GROWTH
  BUSINESS
  ENTERPRISE
}
```

Keep STARTER and PROFESSIONAL so the enum migration doesn't break existing rows. They'll be cleaned up in a data migration step.

- [ ] **Step 2: Add BillingPlan and BillingStatus enums**

Add after the `Plan` enum:

```prisma
enum BillingPlan {
  GROWTH
  BUSINESS
  ENTERPRISE
}

enum BillingStatus {
  ACTIVE
  PAST_DUE
  CANCELED
  TRIALING
}
```

- [ ] **Step 3: Add BillingSubscription model**

Add after the NotificationMute model (end of notifications section):

```prisma
// ============================================
// BILLING & USAGE METERING
// ============================================

model BillingSubscription {
  id                   String        @id @default(cuid())
  orgId                String        @unique
  stripeCustomerId     String
  stripeSubscriptionId String?
  plan                 BillingPlan
  status               BillingStatus @default(ACTIVE)
  currentPeriodStart   DateTime
  currentPeriodEnd     DateTime
  tokenAllowance       Int
  storageAllowanceGb   Int
  memberAllowance      Int
  createdAt            DateTime      @default(now())
  updatedAt            DateTime      @updatedAt

  organization Organization  @relation(fields: [orgId], references: [id], onDelete: Cascade)
  usageLedgers UsageLedger[]

  @@index([stripeCustomerId])
}
```

- [ ] **Step 4: Add UsageLedger model**

```prisma
model UsageLedger {
  id               String    @id @default(cuid())
  orgId            String
  periodStart      DateTime
  periodEnd        DateTime
  tokensUsed       Int       @default(0)
  storageUsedGb    Float     @default(0)
  lastStorageScanAt DateTime?
  notifiedAt80Pct  DateTime?
  notifiedAt100Pct DateTime?
  updatedAt        DateTime  @updatedAt

  organization         Organization        @relation(fields: [orgId], references: [id], onDelete: Cascade)
  billingSubscription  BillingSubscription? @relation(fields: [orgId], references: [orgId])

  @@unique([orgId, periodStart])
  @@index([orgId])
}
```

- [ ] **Step 5: Add CreditBalance model**

```prisma
model CreditBalance {
  id              String   @id @default(cuid())
  orgId           String   @unique
  tokensRemaining Int      @default(0)
  updatedAt       DateTime @updatedAt

  organization Organization @relation(fields: [orgId], references: [id], onDelete: Cascade)
}
```

- [ ] **Step 6: Add CreditPurchase model**

```prisma
model CreditPurchase {
  id                    String   @id @default(cuid())
  orgId                 String
  tokensAmount          Int
  pricePaid             Int      // cents
  stripePaymentIntentId String
  createdAt             DateTime @default(now())

  organization Organization @relation(fields: [orgId], references: [id], onDelete: Cascade)

  @@index([orgId])
}
```

- [ ] **Step 7: Add ProcessedWebhookEvent model**

```prisma
model ProcessedWebhookEvent {
  id            String   @id @default(cuid())
  stripeEventId String   @unique
  eventType     String
  processedAt   DateTime @default(now())

  @@index([stripeEventId])
}
```

- [ ] **Step 8: Add relations to Organization model**

In the Organization model, add these relation fields after the `oidcConfig` line:

```prisma
  // Billing
  billingSubscription BillingSubscription?
  usageLedgers        UsageLedger[]
  creditBalance       CreditBalance?
  creditPurchases     CreditPurchase[]
```

- [ ] **Step 9: Run the migration**

```bash
npx prisma migrate dev --name add-billing-models
```

- [ ] **Step 10: Create a data migration to map legacy plans**

```bash
npx prisma db execute --stdin <<'SQL'
UPDATE "Organization" SET plan = 'GROWTH' WHERE plan = 'STARTER';
UPDATE "Organization" SET plan = 'BUSINESS' WHERE plan = 'PROFESSIONAL';
SQL
```

- [ ] **Step 11: Commit**

```bash
git add prisma/
git commit -m "feat: add billing data models and migrate Plan enum"
```

---

### Task 3: Core billing library — state loader, cache, enforcement

**Files:**
- Create: `lib/billing.ts`

- [ ] **Step 1: Create `lib/billing.ts`**

```typescript
/**
 * Billing state loader, caching, and enforcement.
 *
 * Reads BillingSubscription + UsageLedger + CreditBalance per org,
 * caches in-memory with 60s TTL, and provides pre-request / post-request
 * helpers for the copilot chat route.
 */

import prisma from '@/lib/db';

// ── Types ────────────────────────────────────────────────────

export interface BillingState {
  subscription: {
    plan: string;
    status: string;
    currentPeriodEnd: Date;
    tokenAllowance: number;
    storageAllowanceGb: number;
    memberAllowance: number;
  } | null;
  usage: {
    tokensUsed: number;
    storageUsedGb: number;
    notifiedAt80Pct: Date | null;
    notifiedAt100Pct: Date | null;
  };
  credits: {
    tokensRemaining: number;
  };
}

export type EnforcementResult =
  | { allowed: true; usingCredits: boolean }
  | { allowed: false; reason: string };

// ── Cache ────────────────────────────────────────────────────

const cache = new Map<string, { state: BillingState; fetchedAt: number }>();
const CACHE_TTL_MS = 60_000;

export function invalidateBillingCache(orgId: string) {
  cache.delete(orgId);
}

// ── State Loader ─────────────────────────────────────────────

export async function getBillingState(orgId: string): Promise<BillingState> {
  const cached = cache.get(orgId);
  if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
    return cached.state;
  }

  const [sub, ledger, credit] = await Promise.all([
    prisma.billingSubscription.findUnique({ where: { orgId } }),
    prisma.usageLedger.findFirst({
      where: { orgId, periodStart: { lte: new Date() }, periodEnd: { gte: new Date() } },
      orderBy: { periodStart: 'desc' },
    }),
    prisma.creditBalance.findUnique({ where: { orgId } }),
  ]);

  const state: BillingState = {
    subscription: sub
      ? {
          plan: sub.plan,
          status: sub.status,
          currentPeriodEnd: sub.currentPeriodEnd,
          tokenAllowance: sub.tokenAllowance,
          storageAllowanceGb: sub.storageAllowanceGb,
          memberAllowance: sub.memberAllowance,
        }
      : null,
    usage: {
      tokensUsed: ledger?.tokensUsed ?? 0,
      storageUsedGb: ledger?.storageUsedGb ?? 0,
      notifiedAt80Pct: ledger?.notifiedAt80Pct ?? null,
      notifiedAt100Pct: ledger?.notifiedAt100Pct ?? null,
    },
    credits: {
      tokensRemaining: credit?.tokensRemaining ?? 0,
    },
  };

  cache.set(orgId, { state, fetchedAt: Date.now() });
  return state;
}

// ── Pre-Request Enforcement ──────────────────────────────────

export function checkTokenAccess(state: BillingState): EnforcementResult {
  if (!state.subscription) {
    return { allowed: false, reason: 'No active subscription. Activate a plan in Settings > Billing.' };
  }

  if (state.subscription.status === 'CANCELED') {
    return { allowed: false, reason: 'Subscription inactive. Reactivate in Settings > Billing.' };
  }

  if (state.usage.tokensUsed < state.subscription.tokenAllowance) {
    return { allowed: true, usingCredits: false };
  }

  if (state.credits.tokensRemaining > 0) {
    return { allowed: true, usingCredits: true };
  }

  const renewalDate = state.subscription.currentPeriodEnd.toLocaleDateString();
  return {
    allowed: false,
    reason: `Token limit reached — purchase more tokens or wait for renewal on ${renewalDate}.`,
  };
}

// ── Post-Request Token Deduction ─────────────────────────────

const MAAS_TOKEN_EQUIVALENT = 10_000;

export async function deductTokens(
  orgId: string,
  inputTokens: number,
  outputTokens: number,
  maasCallCount: number = 0,
): Promise<void> {
  const actual = inputTokens + outputTokens + maasCallCount * MAAS_TOKEN_EQUIVALENT;
  if (actual <= 0) return;

  // Step 1: Atomic increment on usage ledger, return new total
  const now = new Date();
  const updatedLedger = await prisma.usageLedger.updateMany({
    where: {
      orgId,
      periodStart: { lte: now },
      periodEnd: { gte: now },
    },
    data: {
      tokensUsed: { increment: actual },
    },
  });

  if (updatedLedger.count === 0) return; // No active ledger period

  // Step 2: Check if we need to spill into credits
  const sub = await prisma.billingSubscription.findUnique({
    where: { orgId },
    select: { tokenAllowance: true },
  });

  if (!sub) return;

  const ledger = await prisma.usageLedger.findFirst({
    where: { orgId, periodStart: { lte: now }, periodEnd: { gte: now } },
    select: { tokensUsed: true, notifiedAt80Pct: true, notifiedAt100Pct: true },
  });

  if (!ledger) return;

  const overflow = Math.max(0, ledger.tokensUsed - sub.tokenAllowance);
  if (overflow > 0) {
    await prisma.$executeRaw`
      UPDATE "CreditBalance"
      SET "tokensRemaining" = GREATEST(0, "tokensRemaining" - ${overflow}),
          "updatedAt" = NOW()
      WHERE "orgId" = ${orgId} AND "tokensRemaining" > 0
    `;
  }

  // Step 3: Check notification thresholds
  await checkUsageThresholds(orgId, ledger.tokensUsed, sub.tokenAllowance, ledger);

  // Invalidate cache so next read sees fresh data
  invalidateBillingCache(orgId);
}

// ── Threshold Notifications ──────────────────────────────────

async function checkUsageThresholds(
  orgId: string,
  tokensUsed: number,
  tokenAllowance: number,
  ledger: { notifiedAt80Pct: Date | null; notifiedAt100Pct: Date | null },
): Promise<void> {
  const { notify } = await import('@/lib/notifications');
  const now = new Date();

  const pct = tokensUsed / tokenAllowance;

  if (pct >= 1.0 && !ledger.notifiedAt100Pct) {
    await prisma.usageLedger.updateMany({
      where: { orgId, periodStart: { lte: now }, periodEnd: { gte: now } },
      data: { notifiedAt100Pct: now },
    });
    await notify({
      organizationId: orgId,
      eventType: 'billing.token_limit_reached',
      severity: 'WARN',
      title: 'Token limit reached',
      message: 'Your organization has used 100% of its monthly token allowance. Purchase more tokens or wait for renewal.',
      dedupeKey: `billing-100pct-${orgId}`,
      actionUrl: '/dashboard/settings?tab=billing',
    });
  } else if (pct >= 0.8 && !ledger.notifiedAt80Pct) {
    await prisma.usageLedger.updateMany({
      where: { orgId, periodStart: { lte: now }, periodEnd: { gte: now } },
      data: { notifiedAt80Pct: now },
    });
    await notify({
      organizationId: orgId,
      eventType: 'billing.token_usage_80pct',
      severity: 'INFO',
      title: "You've used 80% of your monthly tokens",
      message: `Your organization has used ${(pct * 100).toFixed(0)}% of its monthly token allowance.`,
      dedupeKey: `billing-80pct-${orgId}`,
      actionUrl: '/dashboard/settings?tab=billing',
    });
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add lib/billing.ts
git commit -m "feat: add billing state loader, cache, and enforcement logic"
```

---

### Task 4: Stripe webhook handler

**Files:**
- Create: `app/api/billing/webhooks/route.ts`

- [ ] **Step 1: Create the webhook route**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import Stripe from 'stripe';
import prisma from '@/lib/db';
import { invalidateBillingCache } from '@/lib/billing';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

// Plan defaults — keep in sync with pricing table in spec
const PLAN_DEFAULTS: Record<string, { tokenAllowance: number; storageAllowanceGb: number; memberAllowance: number }> = {
  GROWTH: { tokenAllowance: 5_000_000, storageAllowanceGb: 100, memberAllowance: 5 },
  BUSINESS: { tokenAllowance: 20_000_000, storageAllowanceGb: 500, memberAllowance: 15 },
  ENTERPRISE: { tokenAllowance: 100_000_000, storageAllowanceGb: 10_000, memberAllowance: 1000 },
};

const CREDIT_BLOCKS: Record<string, number> = {
  '5M': 5_000_000,
  '20M': 20_000_000,
};

// Disable body parsing — Stripe needs the raw body for signature verification
export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const body = await request.text();
  const signature = request.headers.get('stripe-signature');

  if (!signature) {
    return NextResponse.json({ error: 'Missing signature' }, { status: 400 });
  }

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(body, signature, process.env.STRIPE_WEBHOOK_SECRET!);
  } catch (err: any) {
    console.error('Webhook signature verification failed:', err.message);
    return NextResponse.json({ error: 'Invalid signature' }, { status: 400 });
  }

  // Idempotency: skip already-processed events
  const existing = await prisma.processedWebhookEvent.findUnique({
    where: { stripeEventId: event.id },
  });
  if (existing) {
    return NextResponse.json({ received: true });
  }

  try {
    switch (event.type) {
      case 'checkout.session.completed':
        await handleCheckoutCompleted(event.data.object as Stripe.Checkout.Session);
        break;
      case 'invoice.paid':
        await handleInvoicePaid(event.data.object as Stripe.Invoice);
        break;
      case 'invoice.payment_failed':
        await handlePaymentFailed(event.data.object as Stripe.Invoice);
        break;
      case 'customer.subscription.updated':
        await handleSubscriptionUpdated(event.data.object as Stripe.Subscription);
        break;
      case 'customer.subscription.deleted':
        await handleSubscriptionDeleted(event.data.object as Stripe.Subscription);
        break;
    }

    // Record event as processed
    await prisma.processedWebhookEvent.create({
      data: { stripeEventId: event.id, eventType: event.type },
    });
  } catch (err) {
    console.error(`Webhook handler error for ${event.type}:`, err);
    return NextResponse.json({ error: 'Handler failed' }, { status: 500 });
  }

  return NextResponse.json({ received: true });
}

// ── Handlers ─────────────────────────────────────────────────

async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const orgId = session.metadata?.orgId;
  if (!orgId) return;

  const checkoutType = session.metadata?.type; // 'subscription' or 'credit'

  if (checkoutType === 'credit') {
    const block = session.metadata?.block as string;
    const tokensAmount = CREDIT_BLOCKS[block];
    if (!tokensAmount) return;

    await prisma.creditBalance.upsert({
      where: { orgId },
      create: { orgId, tokensRemaining: tokensAmount },
      update: { tokensRemaining: { increment: tokensAmount } },
    });

    await prisma.creditPurchase.create({
      data: {
        orgId,
        tokensAmount,
        pricePaid: session.amount_total ?? 0,
        stripePaymentIntentId: (session.payment_intent as string) ?? '',
      },
    });

    invalidateBillingCache(orgId);
    return;
  }

  // Subscription checkout
  const plan = (session.metadata?.plan ?? 'GROWTH') as keyof typeof PLAN_DEFAULTS;
  const defaults = PLAN_DEFAULTS[plan] ?? PLAN_DEFAULTS.GROWTH;
  const stripeSubscriptionId = session.subscription as string;

  const stripeSub = await stripe.subscriptions.retrieve(stripeSubscriptionId);
  const periodStart = new Date(stripeSub.current_period_start * 1000);
  const periodEnd = new Date(stripeSub.current_period_end * 1000);

  await prisma.billingSubscription.upsert({
    where: { orgId },
    create: {
      orgId,
      stripeCustomerId: session.customer as string,
      stripeSubscriptionId,
      plan: plan as any,
      status: 'ACTIVE',
      currentPeriodStart: periodStart,
      currentPeriodEnd: periodEnd,
      ...defaults,
    },
    update: {
      stripeSubscriptionId,
      plan: plan as any,
      status: 'ACTIVE',
      currentPeriodStart: periodStart,
      currentPeriodEnd: periodEnd,
      ...defaults,
    },
  });

  // Create initial usage ledger for this period
  await prisma.usageLedger.upsert({
    where: { orgId_periodStart: { orgId, periodStart } },
    create: { orgId, periodStart, periodEnd, tokensUsed: 0, storageUsedGb: 0 },
    update: {}, // no-op if exists (idempotent)
  });

  invalidateBillingCache(orgId);
}

async function handleInvoicePaid(invoice: Stripe.Invoice) {
  const subId = invoice.subscription as string;
  if (!subId) return;

  const sub = await prisma.billingSubscription.findFirst({
    where: { stripeSubscriptionId: subId },
  });
  if (!sub) return;

  const stripeSub = await stripe.subscriptions.retrieve(subId);
  const periodStart = new Date(stripeSub.current_period_start * 1000);
  const periodEnd = new Date(stripeSub.current_period_end * 1000);

  // Update subscription period
  await prisma.billingSubscription.update({
    where: { orgId: sub.orgId },
    data: { currentPeriodStart: periodStart, currentPeriodEnd: periodEnd, status: 'ACTIVE' },
  });

  // Create new usage ledger for the new period (idempotent via unique constraint)
  await prisma.usageLedger.upsert({
    where: { orgId_periodStart: { orgId: sub.orgId, periodStart } },
    create: { orgId: sub.orgId, periodStart, periodEnd, tokensUsed: 0, storageUsedGb: 0 },
    update: {},
  });

  invalidateBillingCache(sub.orgId);
}

async function handlePaymentFailed(invoice: Stripe.Invoice) {
  const subId = invoice.subscription as string;
  if (!subId) return;

  await prisma.billingSubscription.updateMany({
    where: { stripeSubscriptionId: subId },
    data: { status: 'PAST_DUE' },
  });

  const sub = await prisma.billingSubscription.findFirst({
    where: { stripeSubscriptionId: subId },
    select: { orgId: true },
  });
  if (sub) invalidateBillingCache(sub.orgId);
}

async function handleSubscriptionUpdated(stripeSub: Stripe.Subscription) {
  const sub = await prisma.billingSubscription.findFirst({
    where: { stripeSubscriptionId: stripeSub.id },
  });
  if (!sub) return;

  const planMeta = stripeSub.metadata?.plan as string | undefined;
  const plan = planMeta && PLAN_DEFAULTS[planMeta] ? planMeta : sub.plan;
  const defaults = PLAN_DEFAULTS[plan] ?? PLAN_DEFAULTS.GROWTH;

  await prisma.billingSubscription.update({
    where: { orgId: sub.orgId },
    data: {
      plan: plan as any,
      currentPeriodStart: new Date(stripeSub.current_period_start * 1000),
      currentPeriodEnd: new Date(stripeSub.current_period_end * 1000),
      ...defaults,
    },
  });

  invalidateBillingCache(sub.orgId);
}

async function handleSubscriptionDeleted(stripeSub: Stripe.Subscription) {
  await prisma.billingSubscription.updateMany({
    where: { stripeSubscriptionId: stripeSub.id },
    data: { status: 'CANCELED' },
  });

  const sub = await prisma.billingSubscription.findFirst({
    where: { stripeSubscriptionId: stripeSub.id },
    select: { orgId: true },
  });
  if (sub) invalidateBillingCache(sub.orgId);
}
```

- [ ] **Step 2: Commit**

```bash
git add app/api/billing/webhooks/route.ts
git commit -m "feat: add Stripe webhook handler with idempotency"
```

---

### Task 5: Billing API routes — checkout, portal, subscription, usage

**Files:**
- Create: `app/api/billing/checkout/route.ts`
- Create: `app/api/billing/portal/route.ts`
- Create: `app/api/billing/subscription/route.ts`
- Create: `app/api/billing/usage/route.ts`

- [ ] **Step 1: Create `app/api/billing/checkout/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import Stripe from 'stripe';
import { auth } from '@/auth';
import prisma from '@/lib/db';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

const PLAN_PRICE_MAP: Record<string, string | undefined> = {
  GROWTH: process.env.STRIPE_GROWTH_PRICE_ID,
  BUSINESS: process.env.STRIPE_BUSINESS_PRICE_ID,
};

const CREDIT_PRICE_MAP: Record<string, string | undefined> = {
  '5M': process.env.STRIPE_CREDIT_5M_PRICE_ID,
  '20M': process.env.STRIPE_CREDIT_20M_PRICE_ID,
};

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const organizationId = (session.user as any).organizationId;
  if (!organizationId) {
    return NextResponse.json({ error: 'No organization' }, { status: 400 });
  }

  // Admin check
  const member = await prisma.teamMember.findUnique({
    where: { userId_organizationId: { userId: session.user.id, organizationId } },
  });
  if (!member || (member.role !== 'OWNER' && member.role !== 'ADMIN')) {
    return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
  }

  const body = await request.json();
  const appUrl = process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000';

  // Get or create Stripe customer
  let stripeCustomerId: string;
  const existingSub = await prisma.billingSubscription.findUnique({
    where: { orgId: organizationId },
    select: { stripeCustomerId: true },
  });

  if (existingSub?.stripeCustomerId) {
    stripeCustomerId = existingSub.stripeCustomerId;
  } else {
    const org = await prisma.organization.findUnique({
      where: { id: organizationId },
      select: { name: true },
    });
    const customer = await stripe.customers.create({
      name: org?.name ?? undefined,
      metadata: { orgId: organizationId },
    });
    stripeCustomerId = customer.id;
  }

  if (body.type === 'credit') {
    // Credit top-up checkout
    const block = body.block as string;
    const priceId = CREDIT_PRICE_MAP[block];
    if (!priceId) {
      return NextResponse.json({ error: 'Invalid credit block' }, { status: 400 });
    }

    const checkoutSession = await stripe.checkout.sessions.create({
      customer: stripeCustomerId,
      mode: 'payment',
      line_items: [{ price: priceId, quantity: 1 }],
      metadata: { orgId: organizationId, type: 'credit', block },
      success_url: `${appUrl}/dashboard/settings?tab=billing&checkout=success`,
      cancel_url: `${appUrl}/dashboard/settings?tab=billing&checkout=canceled`,
    });

    return NextResponse.json({ url: checkoutSession.url });
  }

  // Subscription checkout
  const plan = body.plan as string;
  const priceId = PLAN_PRICE_MAP[plan];
  if (!priceId) {
    return NextResponse.json({ error: 'Invalid plan' }, { status: 400 });
  }

  const checkoutSession = await stripe.checkout.sessions.create({
    customer: stripeCustomerId,
    mode: 'subscription',
    line_items: [{ price: priceId, quantity: 1 }],
    metadata: { orgId: organizationId, type: 'subscription', plan },
    success_url: `${appUrl}/dashboard/settings?tab=billing&checkout=success`,
    cancel_url: `${appUrl}/dashboard/settings?tab=billing&checkout=canceled`,
  });

  return NextResponse.json({ url: checkoutSession.url });
}
```

- [ ] **Step 2: Create `app/api/billing/portal/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import Stripe from 'stripe';
import { auth } from '@/auth';
import prisma from '@/lib/db';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const organizationId = (session.user as any).organizationId;
  if (!organizationId) {
    return NextResponse.json({ error: 'No organization' }, { status: 400 });
  }

  const member = await prisma.teamMember.findUnique({
    where: { userId_organizationId: { userId: session.user.id, organizationId } },
  });
  if (!member || (member.role !== 'OWNER' && member.role !== 'ADMIN')) {
    return NextResponse.json({ error: 'Admin access required' }, { status: 403 });
  }

  const sub = await prisma.billingSubscription.findUnique({
    where: { orgId: organizationId },
    select: { stripeCustomerId: true },
  });

  if (!sub) {
    return NextResponse.json({ error: 'No subscription found' }, { status: 404 });
  }

  const appUrl = process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000';
  const portalSession = await stripe.billingPortal.sessions.create({
    customer: sub.stripeCustomerId,
    return_url: `${appUrl}/dashboard/settings?tab=billing`,
  });

  return NextResponse.json({ url: portalSession.url });
}
```

- [ ] **Step 3: Create `app/api/billing/subscription/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { getBillingState } from '@/lib/billing';

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const organizationId = (session.user as any).organizationId;
  if (!organizationId) {
    return NextResponse.json({ error: 'No organization' }, { status: 400 });
  }

  const state = await getBillingState(organizationId);

  // Get member count
  const memberCount = await prisma.teamMember.count({
    where: { organizationId },
  });

  // Get credit purchase history
  const purchases = await prisma.creditPurchase.findMany({
    where: { orgId: organizationId },
    orderBy: { createdAt: 'desc' },
    take: 20,
  });

  return NextResponse.json({
    subscription: state.subscription,
    usage: {
      ...state.usage,
      memberCount,
    },
    credits: {
      ...state.credits,
      purchases: purchases.map((p) => ({
        id: p.id,
        tokensAmount: p.tokensAmount,
        pricePaid: p.pricePaid,
        createdAt: p.createdAt,
      })),
    },
  });
}
```

- [ ] **Step 4: Create `app/api/billing/usage/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { getBillingState } from '@/lib/billing';

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const organizationId = (session.user as any).organizationId;
  if (!organizationId) {
    return NextResponse.json({ error: 'No organization' }, { status: 400 });
  }

  const state = await getBillingState(organizationId);

  const memberCount = await prisma.teamMember.count({
    where: { organizationId },
  });

  return NextResponse.json({
    tokensUsed: state.usage.tokensUsed,
    tokenAllowance: state.subscription?.tokenAllowance ?? 0,
    storageUsedGb: state.usage.storageUsedGb,
    storageAllowanceGb: state.subscription?.storageAllowanceGb ?? 0,
    memberCount,
    memberAllowance: state.subscription?.memberAllowance ?? 0,
    creditsRemaining: state.credits.tokensRemaining,
  });
}
```

- [ ] **Step 5: Commit**

```bash
git add app/api/billing/
git commit -m "feat: add billing API routes (checkout, portal, subscription, usage)"
```

---

### Task 6: Copilot chat route — add billing enforcement

**Files:**
- Modify: `app/api/copilot/chat/route.ts`

- [ ] **Step 1: Add pre-request billing check to the non-streaming path**

At the top of `app/api/copilot/chat/route.ts`, add the import:

```typescript
import { getBillingState, checkTokenAccess, deductTokens } from '@/lib/billing';
```

In the `POST` handler, after the organization check (`if (!user?.organizationId)`) and before the streaming branch (`if (stream)`), add:

```typescript
    // Billing enforcement — pre-request check
    const billingState = await getBillingState(user.organizationId);
    const enforcement = checkTokenAccess(billingState);
    if (!enforcement.allowed) {
      return NextResponse.json({ error: enforcement.reason }, { status: 402 });
    }
```

- [ ] **Step 2: Add post-response deduction to the non-streaming path**

After the token tracking section that increments `totalInputTokens` / `totalOutputTokens` on the CopilotSession (around the existing `prisma.copilotSession.update` call), add:

```typescript
      // Billing: deduct tokens from org ledger
      await deductTokens(user.organizationId, inputTokens, outputTokens);
```

- [ ] **Step 3: Add pre-request billing check to the streaming path**

In the `handleStreamingChat` function, after the user/org lookup, add the same billing check:

```typescript
    // Billing enforcement — pre-request check
    const billingState = await getBillingState(user.organizationId);
    const enforcement = checkTokenAccess(billingState);
    if (!enforcement.allowed) {
      return NextResponse.json({ error: enforcement.reason }, { status: 402 });
    }
```

- [ ] **Step 4: Add post-response deduction to the streaming path**

In the streaming handler, after the `done` event is processed and tokens are tracked (after the `prisma.copilotSession.update` with `totalInputTokens: { increment: inputTokens }`), add:

```typescript
                // Billing: deduct tokens from org ledger
                await deductTokens(user.organizationId, inputTokens, outputTokens);
```

- [ ] **Step 5: Commit**

```bash
git add app/api/copilot/chat/route.ts
git commit -m "feat: add billing enforcement to copilot chat route"
```

---

### Task 7: Team invite route — add member limit enforcement

**Files:**
- Modify: `app/api/team/invite/route.ts`

- [ ] **Step 1: Add member limit check**

In `app/api/team/invite/route.ts`, add the import at the top:

```typescript
import { getBillingState } from '@/lib/billing';
```

After the admin role check and before the email validation, add:

```typescript
    // Member limit enforcement
    const billingState = await getBillingState(organizationId);
    if (billingState.subscription) {
      const currentCount = await prisma.teamMember.count({ where: { organizationId } });
      if (currentCount >= billingState.subscription.memberAllowance) {
        return NextResponse.json(
          { error: `Team member limit reached (${billingState.subscription.memberAllowance}). Upgrade your plan to add more members.` },
          { status: 402 },
        );
      }
    }
```

- [ ] **Step 2: Commit**

```bash
git add app/api/team/invite/route.ts
git commit -m "feat: add member limit enforcement to team invite"
```

---

### Task 8: BillingSettings component

**Files:**
- Create: `components/settings/BillingSettings.tsx`
- Modify: `app/(dashboard)/dashboard/settings/page.tsx`

- [ ] **Step 1: Create `components/settings/BillingSettings.tsx`**

```tsx
'use client';

import { useState, useEffect } from 'react';
import { CreditCard, ExternalLink, Coins, FileText } from 'lucide-react';

interface Subscription {
  plan: string;
  status: string;
  currentPeriodEnd: string;
  tokenAllowance: number;
  storageAllowanceGb: number;
  memberAllowance: number;
}

interface CreditPurchase {
  id: string;
  tokensAmount: number;
  pricePaid: number;
  createdAt: string;
}

interface BillingData {
  subscription: Subscription | null;
  usage: {
    tokensUsed: number;
    storageUsedGb: number;
    memberCount: number;
  };
  credits: {
    tokensRemaining: number;
    purchases: CreditPurchase[];
  };
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toString();
}

function UsageBar({ label, used, total, unit }: { label: string; used: number; total: number; unit?: string }) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const isHigh = pct >= 80;
  const isOver = pct >= 100;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] text-[var(--text-tertiary)]">{label}</span>
        <span className="text-[13px] text-[var(--text)]">
          {unit === 'tokens' ? formatTokens(used) : used.toFixed(1)} / {unit === 'tokens' ? formatTokens(total) : total}{unit === 'GB' ? ' GB' : ''}
        </span>
      </div>
      <div className="h-2 rounded-full bg-[var(--overlay-medium)]">
        <div
          className={`h-full rounded-full transition-all ${isOver ? 'bg-red-500' : isHigh ? 'bg-amber-500' : 'bg-[var(--accent)]'}`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
    </div>
  );
}

export default function BillingSettings() {
  const [data, setData] = useState<BillingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/billing/subscription')
      .then((r) => r.ok ? r.json() : null)
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  const handleCheckout = async (plan: string) => {
    setActionLoading(plan);
    try {
      const res = await fetch('/api/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan }),
      });
      const { url } = await res.json();
      if (url) window.location.href = url;
    } finally {
      setActionLoading(null);
    }
  };

  const handleCreditPurchase = async (block: string) => {
    setActionLoading(`credit-${block}`);
    try {
      const res = await fetch('/api/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'credit', block }),
      });
      const { url } = await res.json();
      if (url) window.location.href = url;
    } finally {
      setActionLoading(null);
    }
  };

  const handlePortal = async () => {
    setActionLoading('portal');
    try {
      const res = await fetch('/api/billing/portal', { method: 'POST' });
      const { url } = await res.json();
      if (url) window.location.href = url;
    } finally {
      setActionLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-6 h-6 red-spinner" />
      </div>
    );
  }

  const sub = data?.subscription;
  const usage = data?.usage;
  const credits = data?.credits;

  // No subscription — show plan selection
  if (!sub) {
    return (
      <div className="space-y-6">
        <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
          <h2 className="text-[15px] font-semibold text-[var(--text)] mb-4 flex items-center gap-2">
            <CreditCard size={16} className="text-[var(--muted)]" /> Choose a Plan
          </h2>
          <p className="text-[13px] text-[var(--muted)] mb-6">Select a plan to activate billing and unlock the full platform.</p>

          <div className="grid grid-cols-2 gap-4">
            {/* Growth */}
            <div className="p-5 rounded-xl border border-[var(--subtle-border)] bg-[var(--overlay-faint)] space-y-3">
              <div>
                <p className="text-[16px] font-semibold text-[var(--text)]">Growth</p>
                <p className="text-[24px] font-bold text-[var(--text)] mt-1">$1,500<span className="text-[14px] font-normal text-[var(--muted)]">/mo</span></p>
              </div>
              <ul className="text-[13px] text-[var(--muted)] space-y-1">
                <li>5M tokens / month</li>
                <li>100 GB storage</li>
                <li>5 team members</li>
              </ul>
              <button
                onClick={() => handleCheckout('GROWTH')}
                disabled={!!actionLoading}
                className="w-full py-2.5 bg-[var(--accent)] hover:bg-[var(--accent)]/90 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
              >
                {actionLoading === 'GROWTH' ? 'Redirecting...' : 'Get Started'}
              </button>
            </div>

            {/* Business */}
            <div className="p-5 rounded-xl border border-[var(--accent)]/30 bg-[var(--accent)]/5 space-y-3">
              <div>
                <p className="text-[16px] font-semibold text-[var(--text)]">Business</p>
                <p className="text-[24px] font-bold text-[var(--text)] mt-1">$3,000<span className="text-[14px] font-normal text-[var(--muted)]">/mo</span></p>
              </div>
              <ul className="text-[13px] text-[var(--muted)] space-y-1">
                <li>20M tokens / month</li>
                <li>500 GB storage</li>
                <li>15 team members</li>
              </ul>
              <button
                onClick={() => handleCheckout('BUSINESS')}
                disabled={!!actionLoading}
                className="w-full py-2.5 bg-[var(--accent)] hover:bg-[var(--accent)]/90 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
              >
                {actionLoading === 'BUSINESS' ? 'Redirecting...' : 'Get Started'}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Active subscription — show current plan + usage
  const statusColor: Record<string, string> = {
    ACTIVE: 'bg-emerald-500/15 text-emerald-400',
    PAST_DUE: 'bg-red-500/15 text-red-400',
    CANCELED: 'bg-zinc-500/15 text-zinc-400',
    TRIALING: 'bg-blue-500/15 text-blue-400',
  };

  return (
    <div className="space-y-6">
      {/* Plan & Usage */}
      <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <h2 className="text-[15px] font-semibold text-[var(--text)] flex items-center gap-2">
              <CreditCard size={16} className="text-[var(--muted)]" /> {sub.plan} Plan
            </h2>
            <span className={`text-xs px-2 py-0.5 rounded-full ${statusColor[sub.status] ?? ''}`}>
              {sub.status}
            </span>
          </div>
          <p className="text-[13px] text-[var(--muted)]">
            Renews {new Date(sub.currentPeriodEnd).toLocaleDateString()}
          </p>
        </div>

        {usage && (
          <div className="space-y-4 mb-6">
            <UsageBar label="Tokens" used={usage.tokensUsed} total={sub.tokenAllowance} unit="tokens" />
            <UsageBar label="Storage" used={usage.storageUsedGb} total={sub.storageAllowanceGb} unit="GB" />
            <UsageBar label="Team Members" used={usage.memberCount} total={sub.memberAllowance} />
          </div>
        )}

        <div className="flex items-center gap-3 pt-4 border-t border-[var(--subtle-border)]">
          <button
            onClick={() => handleCheckout(sub.plan === 'GROWTH' ? 'BUSINESS' : 'GROWTH')}
            disabled={!!actionLoading}
            className="px-4 py-2 text-sm bg-[var(--hover-bg)] hover:bg-[var(--overlay-medium)] text-[var(--text)] rounded-lg transition-colors disabled:opacity-50"
          >
            Change Plan
          </button>
          <button
            onClick={handlePortal}
            disabled={!!actionLoading}
            className="px-4 py-2 text-sm text-[var(--muted)] hover:text-[var(--text)] transition-colors flex items-center gap-1.5 disabled:opacity-50"
          >
            Manage Payment Method <ExternalLink size={12} />
          </button>
        </div>
      </div>

      {/* Token Credits */}
      <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
        <h2 className="text-[15px] font-semibold text-[var(--text)] mb-4 flex items-center gap-2">
          <Coins size={16} className="text-[var(--muted)]" /> Token Credits
        </h2>

        <p className="text-[13px] text-[var(--muted)] mb-4">
          Credit balance: <span className="text-[var(--text)] font-medium">{formatTokens(credits?.tokensRemaining ?? 0)} tokens</span>
        </p>

        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={() => handleCreditPurchase('5M')}
            disabled={!!actionLoading}
            className="px-4 py-2 text-sm bg-[var(--hover-bg)] hover:bg-[var(--overlay-medium)] text-[var(--text)] rounded-lg transition-colors disabled:opacity-50"
          >
            {actionLoading === 'credit-5M' ? 'Redirecting...' : 'Buy 5M tokens — $100'}
          </button>
          <button
            onClick={() => handleCreditPurchase('20M')}
            disabled={!!actionLoading}
            className="px-4 py-2 text-sm bg-[var(--hover-bg)] hover:bg-[var(--overlay-medium)] text-[var(--text)] rounded-lg transition-colors disabled:opacity-50"
          >
            {actionLoading === 'credit-20M' ? 'Redirecting...' : 'Buy 20M tokens — $350'}
          </button>
        </div>

        {credits?.purchases && credits.purchases.length > 0 && (
          <div>
            <h3 className="text-[13px] font-medium text-[var(--text-tertiary)] mb-2">Purchase History</h3>
            <div className="space-y-1">
              {credits.purchases.map((p) => (
                <div key={p.id} className="flex items-center justify-between py-2 px-3 rounded-lg bg-[var(--overlay-faint)] text-[13px]">
                  <span className="text-[var(--text)]">{formatTokens(p.tokensAmount)} tokens</span>
                  <div className="flex items-center gap-4">
                    <span className="text-[var(--muted)]">${(p.pricePaid / 100).toFixed(2)}</span>
                    <span className="text-[var(--text-faint)]">{new Date(p.createdAt).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Invoices */}
      <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
        <h2 className="text-[15px] font-semibold text-[var(--text)] mb-4 flex items-center gap-2">
          <FileText size={16} className="text-[var(--muted)]" /> Invoices
        </h2>
        <p className="text-[13px] text-[var(--muted)]">
          View and download invoices from{' '}
          <button onClick={handlePortal} className="text-[var(--accent)] hover:underline">
            Stripe Customer Portal
          </button>.
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update settings page to use BillingSettings**

In `app/(dashboard)/dashboard/settings/page.tsx`:

Add the import at the top:

```typescript
import BillingSettings from '@/components/settings/BillingSettings';
```

Replace the entire `{activeTab === 'billing' && (...)}` block (the hardcoded billing stub, lines 177-217) with:

```tsx
      {activeTab === 'billing' && <BillingSettings />}
```

- [ ] **Step 3: Commit**

```bash
git add components/settings/BillingSettings.tsx app/\(dashboard\)/dashboard/settings/page.tsx
git commit -m "feat: add billing settings UI with plan, usage, credits, and invoices"
```

---

### Task 9: Global billing warning banner

**Files:**
- Create: `components/dashboard/BillingBanner.tsx`
- Modify: `components/dashboard/Header.tsx`

- [ ] **Step 1: Create `components/dashboard/BillingBanner.tsx`**

```tsx
'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, X } from 'lucide-react';

interface UsageData {
  tokensUsed: number;
  tokenAllowance: number;
  status?: string;
}

export default function BillingBanner() {
  const router = useRouter();
  const [data, setData] = useState<UsageData | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/billing/subscription')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.subscription) {
          setData({
            tokensUsed: d.usage?.tokensUsed ?? 0,
            tokenAllowance: d.subscription.tokenAllowance,
            status: d.subscription.status,
          });
        }
      })
      .catch(() => {});
  }, []);

  if (!data) return null;

  let banner: { message: string; color: string; key: string } | null = null;

  if (data.status === 'PAST_DUE') {
    banner = {
      message: 'Payment failed — update your payment method to avoid service interruption.',
      color: 'bg-red-500/10 border-red-500/20 text-red-400',
      key: 'past_due',
    };
  } else if (data.tokenAllowance > 0 && data.tokensUsed >= data.tokenAllowance) {
    banner = {
      message: 'Token limit reached. Purchase more tokens or wait for your renewal.',
      color: 'bg-amber-500/10 border-amber-500/20 text-amber-400',
      key: 'token_100',
    };
  } else if (data.tokenAllowance > 0 && data.tokensUsed >= data.tokenAllowance * 0.8) {
    banner = {
      message: `You've used ${Math.round((data.tokensUsed / data.tokenAllowance) * 100)}% of your monthly tokens.`,
      color: 'bg-blue-500/10 border-blue-500/20 text-blue-400',
      key: 'token_80',
    };
  }

  if (!banner || dismissed === banner.key) return null;

  return (
    <div className={`flex items-center justify-between px-4 py-2 border-b text-[13px] ${banner.color}`}>
      <div className="flex items-center gap-2">
        <AlertTriangle size={14} />
        <span>{banner.message}</span>
        <button
          onClick={() => router.push('/dashboard/settings?tab=billing')}
          className="ml-1 underline hover:no-underline"
        >
          View billing
        </button>
      </div>
      <button onClick={() => setDismissed(banner!.key)} className="p-1 hover:opacity-70">
        <X size={14} />
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Add BillingBanner to the Header**

In `components/dashboard/Header.tsx`, add the import at the top:

```typescript
import BillingBanner from './BillingBanner';
```

Then render `<BillingBanner />` just before the header's opening wrapper element (so it appears above the header bar). Find the first `<div>` or `<header>` returned by the component and place `<BillingBanner />` before it, wrapping both in a fragment if needed:

```tsx
return (
  <>
    <BillingBanner />
    {/* existing header content */}
  </>
);
```

- [ ] **Step 3: Commit**

```bash
git add components/dashboard/BillingBanner.tsx components/dashboard/Header.tsx
git commit -m "feat: add global billing warning banner to dashboard header"
```

---

### Task 10: Verify and test end-to-end

- [ ] **Step 1: Run Prisma generate to verify schema**

```bash
npx prisma generate
```

Expected: no errors.

- [ ] **Step 2: Run TypeScript type check**

```bash
npx tsc --noEmit
```

Expected: no type errors in new files.

- [ ] **Step 3: Start the dev server and verify the billing UI loads**

```bash
npm run dev
```

Navigate to `http://localhost:3000/dashboard/settings?tab=billing`. Expected: the plan selection UI renders (no subscription yet).

- [ ] **Step 4: Verify the billing banner does not crash the header**

Navigate to any dashboard page. Expected: no banner shown (no subscription), no console errors.

- [ ] **Step 5: Verify copilot still works without a subscription**

Open the copilot and send a message. Expected: 402 response with "No active subscription" message (enforcement is active).

- [ ] **Step 6: Commit any fixes**

```bash
git add -A
git commit -m "fix: address any issues found during billing e2e verification"
```
