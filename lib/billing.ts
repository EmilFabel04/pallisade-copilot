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
    pipelineAllowance: number;
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
          pipelineAllowance: sub.pipelineAllowance,
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
