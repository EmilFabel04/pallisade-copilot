import { NextRequest, NextResponse } from 'next/server';
import crypto from 'crypto';
import prisma from '@/lib/db';
import { invalidateBillingCache } from '@/lib/billing';

// Plan defaults — keep in sync with pricing table in spec
const PLAN_DEFAULTS: Record<string, { tokenAllowance: number; storageAllowanceGb: number; memberAllowance: number; pipelineAllowance: number }> = {
  GROWTH: { tokenAllowance: 5_000_000, storageAllowanceGb: 100, memberAllowance: 5, pipelineAllowance: 3 },
  BUSINESS: { tokenAllowance: 20_000_000, storageAllowanceGb: 500, memberAllowance: 15, pipelineAllowance: 6 },
  ENTERPRISE: { tokenAllowance: 100_000_000, storageAllowanceGb: 10_000, memberAllowance: 1000, pipelineAllowance: 100 },
};

const CREDIT_BLOCKS: Record<string, number> = {
  '5M': 5_000_000,
  '20M': 20_000_000,
};

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const body = await request.text();
  const signature = request.headers.get('x-paystack-signature');

  if (!signature) {
    return NextResponse.json({ error: 'Missing signature' }, { status: 400 });
  }

  // Verify PayStack webhook signature (HMAC SHA512) using constant-time compare
  const hash = crypto
    .createHmac('sha512', process.env.PAYSTACK_SECRET_KEY!)
    .update(body)
    .digest('hex');

  const hashBuf = Buffer.from(hash, 'hex');
  const sigBuf = Buffer.from(signature, 'hex');

  if (hashBuf.length !== sigBuf.length || !crypto.timingSafeEqual(hashBuf, sigBuf)) {
    console.error('Webhook signature verification failed');
    return NextResponse.json({ error: 'Invalid signature' }, { status: 400 });
  }

  const payload = JSON.parse(body);
  const event = payload.event as string;
  const data = payload.data;

  // Idempotency: skip already-processed events
  // PayStack doesn't send event IDs — use reference as dedup key
  const eventId = data.reference || `${event}-${data.subscription_code || data.id || Date.now()}`;
  const existing = await prisma.processedWebhookEvent.findUnique({
    where: { eventId },
  });
  if (existing) {
    return NextResponse.json({ received: true });
  }

  try {
    switch (event) {
      case 'charge.success':
        await handleChargeSuccess(data);
        break;
      case 'subscription.create':
        await handleSubscriptionCreate(data);
        break;
      case 'subscription.not_renew':
      case 'subscription.disable':
        await handleSubscriptionDisabled(data);
        break;
      case 'invoice.payment_failed':
        await handlePaymentFailed(data);
        break;
    }

    await prisma.processedWebhookEvent.create({
      data: { eventId, eventType: event },
    });
  } catch (err) {
    console.error(`Webhook handler error for ${event}:`, err);
    return NextResponse.json({ error: 'Handler failed' }, { status: 500 });
  }

  return NextResponse.json({ received: true });
}

// ── Handlers ─────────────────────────────────────────────────

async function handleChargeSuccess(data: any) {
  const metadata = data.metadata || {};
  const orgId = metadata.orgId;
  if (!orgId) return;

  const checkoutType = metadata.type; // 'subscription' or 'credit'

  if (checkoutType === 'credit') {
    const block = metadata.block as string;
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
        pricePaid: data.amount ?? 0,
        paystackReference: data.reference ?? '',
      },
    });

    invalidateBillingCache(orgId);
    return;
  }

  // Subscription payment — handled by subscription.create for new subs
  // For renewals, update the period
  if (data.plan && data.subscription_code) {
    const sub = await prisma.billingSubscription.findFirst({
      where: { paystackSubscriptionCode: data.subscription_code },
    });
    if (sub) {
      const now = new Date();
      const periodEnd = new Date(now);
      periodEnd.setMonth(periodEnd.getMonth() + 1);

      await prisma.billingSubscription.update({
        where: { orgId: sub.orgId },
        data: { currentPeriodStart: now, currentPeriodEnd: periodEnd, status: 'ACTIVE' },
      });

      // Create new usage ledger for the new period (idempotent)
      await prisma.usageLedger.upsert({
        where: { orgId_periodStart: { orgId: sub.orgId, periodStart: now } },
        create: { orgId: sub.orgId, periodStart: now, periodEnd, tokensUsed: 0, storageUsedGb: 0 },
        update: {},
      });

      invalidateBillingCache(sub.orgId);
    }
  }
}

async function handleSubscriptionCreate(data: any) {
  const customerCode = data.customer?.customer_code;
  if (!customerCode) return;

  // Look up org by customer code
  const existingSub = await prisma.billingSubscription.findFirst({
    where: { paystackCustomerCode: customerCode },
  });

  if (!existingSub) return;

  const now = new Date();
  const periodEnd = new Date(data.next_payment_date || now);
  if (periodEnd <= now) periodEnd.setMonth(now.getMonth() + 1);

  await prisma.billingSubscription.update({
    where: { orgId: existingSub.orgId },
    data: {
      paystackSubscriptionCode: data.subscription_code,
      paystackEmailToken: data.email_token || null,
      status: 'ACTIVE',
      currentPeriodStart: now,
      currentPeriodEnd: periodEnd,
    },
  });

  // Create initial usage ledger
  await prisma.usageLedger.upsert({
    where: { orgId_periodStart: { orgId: existingSub.orgId, periodStart: now } },
    create: { orgId: existingSub.orgId, periodStart: now, periodEnd, tokensUsed: 0, storageUsedGb: 0 },
    update: {},
  });

  invalidateBillingCache(existingSub.orgId);
}

async function handleSubscriptionDisabled(data: any) {
  const subCode = data.subscription_code;
  if (!subCode) return;

  await prisma.billingSubscription.updateMany({
    where: { paystackSubscriptionCode: subCode },
    data: { status: 'CANCELED' },
  });

  const sub = await prisma.billingSubscription.findFirst({
    where: { paystackSubscriptionCode: subCode },
    select: { orgId: true },
  });
  if (sub) invalidateBillingCache(sub.orgId);
}

async function handlePaymentFailed(data: any) {
  const subCode = data.subscription?.subscription_code;
  if (!subCode) return;

  await prisma.billingSubscription.updateMany({
    where: { paystackSubscriptionCode: subCode },
    data: { status: 'PAST_DUE' },
  });

  const sub = await prisma.billingSubscription.findFirst({
    where: { paystackSubscriptionCode: subCode },
    select: { orgId: true },
  });
  if (sub) invalidateBillingCache(sub.orgId);
}
