# Billing & Usage Metering Design

**Date:** 2026-04-19
**Status:** Draft

## Overview

Self-serve billing system for Pallisade using PayStack for payments and an internal Postgres ledger for real-time usage tracking and enforcement. Customers are companies (billed per Organization), onboarded with hands-on support, and metered on three dimensions: AI token usage, storage (GB), and team members.

## Context & Constraints

- **Customer profile:** Companies, not individuals. Integrating production warehouses, Airflow, dbt, etc. requires company-level buy-in. Every customer is effectively an enterprise contract even though billing is self-serve.
- **Cost structure:** LLM API tokens (~$5-10/M tokens) + RunPod serverless GPU for MAAS specialists (~$0.03-0.06 per specialist call on RTX 4500). All-in cost per copilot interaction: ~$0.08-0.17. MAAS specialist calls are metered at a 10k token equivalent per call to reflect their higher compute cost (see Token Enforcement).
- **Existing foundation:** Prisma schema has `plan` enum (STARTER/PROFESSIONAL/ENTERPRISE) on Organization, token tracking fields on PipelineStack and CopilotSession, billing tab stub in Settings.

## Pricing Tiers

| | Growth | Business | Enterprise |
|---|---|---|---|
| **Price** | $1,500/mo | $3,000/mo | Custom |
| **Storage** | 100 GB | 500 GB | Custom |
| **Team members** | 5 | 15 | Unlimited |
| **Tokens/mo** | 5M | 20M | Custom |
| **Target** | Small data team, single stack | Mid-size, multiple pipelines | Large orgs, compliance/SSO |

**Token top-ups** (pre-purchase credits, drawn down until exhausted, never expire):
- 5M tokens — $100
- 20M tokens — $350

## Architecture: Stripe for Payments, Internal Ledger for Usage

Stripe handles payment collection, invoicing, and subscription lifecycle. All usage tracking, limit enforcement, and credit balances live in Postgres for real-time enforcement without Stripe roundtrips.

## Data Model

### BillingSubscription

One per Organization. Source of truth for what the org is entitled to.

| Field | Type | Notes |
|---|---|---|
| id | String (cuid) | Primary key |
| orgId | String (unique) | → Organization |
| stripeCustomerId | String | Stripe Customer ID |
| stripeSubscriptionId | String | Stripe Subscription ID |
| plan | Enum: GROWTH, BUSINESS, ENTERPRISE | Current plan |
| status | Enum: ACTIVE, PAST_DUE, CANCELED, TRIALING | Subscription state |
| currentPeriodStart | DateTime | Current billing period start |
| currentPeriodEnd | DateTime | Current billing period end |
| tokenAllowance | Int | Monthly token limit from plan |
| storageAllowanceGb | Int | Storage limit from plan |
| memberAllowance | Int | Team member limit from plan |
| createdAt | DateTime | |
| updatedAt | DateTime | |

### UsageLedger

One row per Organization per billing period. Tracks actual consumption.

| Field | Type | Notes |
|---|---|---|
| id | String (cuid) | Primary key |
| orgId | String | → Organization |
| periodStart | DateTime | Billing period start |
| periodEnd | DateTime | Billing period end |
| tokensUsed | Int (default 0) | Tokens consumed this period |
| storageUsedGb | Float (default 0) | Last measured storage |
| lastStorageScanAt | DateTime? | When storage was last measured |
| updatedAt | DateTime | |

Unique constraint on (orgId, periodStart).

### CreditBalance

One row per Organization. Running balance of purchased token credits.

| Field | Type | Notes |
|---|---|---|
| id | String (cuid) | Primary key |
| orgId | String (unique) | → Organization |
| tokensRemaining | Int (default 0) | Available credit tokens |
| updatedAt | DateTime | |

### CreditPurchase

Audit trail for all credit top-up purchases.

| Field | Type | Notes |
|---|---|---|
| id | String (cuid) | Primary key |
| orgId | String | → Organization |
| tokensAmount | Int | Tokens purchased |
| pricePaid | Int | Amount in cents |
| stripePaymentIntentId | String | Stripe reference |
| createdAt | DateTime | |

## Stripe Integration

### Stripe Setup (one-time)

- 2 Products: "Growth" and "Business" (Enterprise is manual/custom)
- Each product has a monthly recurring Price
- 1 Product: "Token Top-Up" with Prices for each block (5M, 20M)

### Checkout Flow

```
Client signs up (existing auth flow)
    → Organization created (no active subscription)
    → You onboard them, help set up integrations
    → Client clicks "Activate Plan" in Settings > Billing
    → POST /api/billing/checkout (plan = GROWTH or BUSINESS)
    → Server creates Stripe Checkout Session (mode: subscription)
    → Client redirected to Stripe-hosted checkout
    → Stripe redirects back to Pallisade on success
    → Webhook: checkout.session.completed
    → Create BillingSubscription + UsageLedger for current period
    → Org is active
```

### Credit Top-Up Flow

```
Client clicks "Buy more tokens" in billing settings
    → POST /api/billing/checkout (type: credit, block: 5M or 20M)
    → Server creates Stripe Checkout Session (mode: payment)
    → Client completes payment
    → Webhook: checkout.session.completed
    → Upsert CreditBalance, add tokens
    → Create CreditPurchase audit record
```

### Webhook Events

| Event | Action |
|---|---|
| `checkout.session.completed` | Create subscription or add credits (based on metadata) |
| `invoice.paid` | Reset UsageLedger for new billing period |
| `invoice.payment_failed` | Set subscription status to PAST_DUE, show warning banner |
| `customer.subscription.updated` | Sync plan/limits on upgrade/downgrade |
| `customer.subscription.deleted` | Set status to CANCELED, enforce restrictions after grace period |

**Idempotency:** All webhook handlers must be idempotent. Store processed Stripe event IDs in a `ProcessedWebhookEvent` table (unique on `stripeEventId`) and skip duplicates. For UsageLedger creation on `invoice.paid`, the unique constraint on `(orgId, periodStart)` provides a natural guard — use `INSERT ... ON CONFLICT DO NOTHING`.

### Payment Failure Handling

1. First failure: warning banner in dashboard, everything still works
2. After Stripe retry cycle exhausts (~2 weeks): subscription → CANCELED
3. Canceled state: copilot disabled, monitors stop running, data read-only, no new integrations
4. Client can reactivate by updating payment method and paying outstanding invoice

## Enforcement

### Token Enforcement (per copilot request)

**Pre-request check:**

1. Load org's BillingSubscription + UsageLedger + CreditBalance (cached in memory, ~60s TTL)
2. If subscription status is CANCELED → reject with "subscription inactive" message (PAST_DUE still allowed — payment failure handling shows a banner but doesn't block usage)
3. If `UsageLedger.tokensUsed < BillingSubscription.tokenAllowance` → allow
4. Else if `CreditBalance.tokensRemaining > 0` → allow, flag as "using credits"
5. Else → reject with "token limit reached — purchase more tokens or wait for renewal on [date]"

**Post-request deduction:**

6. Count actual tokens used: `LLM input + output tokens + (MAAS specialist calls × 10,000)`. The 10k multiplier reflects the ~10× higher compute cost of a GPU specialist call vs equivalent LLM tokens.
7. Atomically increment usage and, if needed, spill into credits:
   ```sql
   -- Step 1: atomic increment on usage ledger
   UPDATE usage_ledger
   SET tokens_used = tokens_used + $actual
   WHERE org_id = $orgId AND period_start = $periodStart;

   -- Step 2: if new total exceeds allowance, deduct overflow from credits
   UPDATE credit_balance
   SET tokens_remaining = GREATEST(0, tokens_remaining - $overflow)
   WHERE org_id = $orgId AND tokens_remaining > 0;
   ```
   Where `$overflow = MAX(0, new_tokens_used - token_allowance)`, computed from the returned row in step 1.

Enforcement is permissive on the boundary: the last request that pushes usage over the limit is allowed to complete (we eat the marginal cost rather than cutting off mid-stream). Concurrent requests may overshoot by a few requests during the cache TTL window — this is acceptable; the atomic increments ensure the ledger stays accurate even if the pre-check was stale.

### Storage Enforcement

- **When checked:** Adding a new integration or data source only, not on every request
- **Measurement:** Daily cron queries each connected warehouse adapter for table sizes via INFORMATION_SCHEMA, sums per org, writes to `UsageLedger.storageUsedGb`
- **Over limit:** Block new integrations with "upgrade to add more data" message. Existing integrations continue working.

### Team Member Enforcement

- **When checked:** Team invite action only
- **Measurement:** Count `TeamMember` rows for the org
- **Over limit:** Block invite with "upgrade to add more team members" message

### Caching

Billing state (subscription + usage + credits) is read on every copilot request but written infrequently. Cache per-org in memory with ~60s TTL. Invalidate on webhook events and credit purchases.

## API Routes

### Next.js API Routes

```
/api/billing/
├── checkout/route.ts          POST — Create Stripe Checkout session
│                                     Body: { plan: "GROWTH"|"BUSINESS" }
│                                        or { type: "credit", block: "5M"|"20M" }
│                                     Returns: { url: stripe_checkout_url }
│
├── portal/route.ts            POST — Create Stripe Customer Portal session
│                                     Returns: { url: stripe_portal_url }
│
├── subscription/route.ts      GET  — Current subscription + usage + credits
│                                     Returns: { subscription, usage, credits }
│
├── webhooks/route.ts          POST — Stripe webhook handler
│                                     No auth (verified by Stripe signature)
│
└── usage/route.ts             GET  — Detailed usage breakdown
                                     Returns: { tokensUsed, tokenAllowance,
                                               storageUsedGb, storageAllowanceGb,
                                               memberCount, memberAllowance,
                                               creditsRemaining }
```

### Storage Scan Cron

`/api/billing/storage-scan/route.ts` — Triggered daily (Vercel Cron or equivalent). Iterates all active orgs, queries warehouse adapters for table sizes, updates `UsageLedger.storageUsedGb`.

### FastAPI Changes

No new endpoints. Changes to existing code:

- **Enforcement middleware** wrapping `/api/v1/copilot/chat` — pre-request billing check
- **Post-response hook** — after chat stream completes, write actual token usage (input + output + MAAS) to UsageLedger. Extends existing token tracking in CopilotSession.

### Auth

- All billing routes (except webhooks) require authenticated user with org admin role
- Webhooks verified via `stripe.webhooks.constructEvent()` with signing secret

## Billing Settings UI

Located in existing Settings > Billing tab.

### Plan & Subscription Section

- Plan name (Growth/Business), status badge, renewal date
- Three usage bars with progress indicators:
  - Tokens: "3.2M / 5M used this period"
  - Storage: "45 GB / 100 GB"
  - Team: "4 / 5 members"
- "Change Plan" button → Stripe Checkout for upgrade/downgrade
- "Manage Payment Method" → Stripe Customer Portal

### Token Credits Section

- Current balance: "1.2M tokens remaining"
- Purchase buttons for top-up blocks (5M / 20M) with prices
- Purchase history table (date, tokens, amount paid)

### Invoices Section

- Table fetched from Stripe API: date, amount, status, PDF download link
- No local storage needed — Stripe hosts invoice PDFs

### Warning Banners (global, in dashboard Header)

- **80% token usage:** Info banner — "You've used 80% of your monthly tokens"
- **100% token usage:** Warning banner — "Token limit reached. Purchase more or wait for renewal on [date]"
- **Payment failed:** Red banner — "Payment failed — update your payment method to avoid service interruption"
- **Storage over limit:** Warning on Sources page only — "Storage limit reached — upgrade to add more integrations"

### Email Notifications

Sent to org admins via the existing notification system. Triggered in the post-request deduction hook when usage crosses a threshold for the first time in a billing period (deduplicated by a `notifiedAt80Pct` / `notifiedAt100Pct` flag on UsageLedger):

- **80% token usage:** "You've used 80% of your monthly tokens — [view usage](link)"
- **100% token usage:** "Token limit reached — purchase more tokens or wait for renewal on [date]"

## Migration Notes

- Update existing `plan` enum on Organization from STARTER/PROFESSIONAL/ENTERPRISE to GROWTH/BUSINESS/ENTERPRISE. Migration mapping: STARTER → GROWTH, PROFESSIONAL → BUSINESS, ENTERPRISE stays ENTERPRISE.
- Existing `tokenLimitMonthly` / `tokensUsedThisMonth` on PipelineStack can be deprecated once UsageLedger is live (org-level tracking replaces pipeline-level)
- Existing orgs without a BillingSubscription are treated as unenrolled (no copilot access until plan activated)
- Add `notifiedAt80Pct` (DateTime?) and `notifiedAt100Pct` (DateTime?) columns to UsageLedger for email notification deduplication

## Out of Scope (V1)

- Usage analytics dashboard (detailed charts, historical trends)
- Annual billing / discounts
- Per-pipeline billing breakdowns
- SSO / SAML (Enterprise feature, manual setup for now)
- Automated dunning emails (rely on Stripe's built-in retry + email)
- Prorated mid-cycle upgrades (Stripe handles this automatically)
