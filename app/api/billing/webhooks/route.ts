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

// Stripe SDK v22 moved current_period_start/end from Subscription to SubscriptionItem
function getSubscriptionPeriod(sub: Stripe.Subscription): { periodStart: Date; periodEnd: Date } {
  const item = sub.items.data[0];
  return {
    periodStart: new Date(item.current_period_start * 1000),
    periodEnd: new Date(item.current_period_end * 1000),
  };
}

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

  const stripeSubResponse = await stripe.subscriptions.retrieve(stripeSubscriptionId);
  const { periodStart, periodEnd } = getSubscriptionPeriod(stripeSubResponse as unknown as Stripe.Subscription);

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
  // Stripe v22 removed invoice.subscription — extract from parent or raw event data
  const subId = (invoice as any).subscription as string | undefined
    ?? (typeof invoice.parent?.subscription_details === 'object' ? (invoice.parent.subscription_details as any)?.subscription : undefined);
  if (!subId) return;

  const sub = await prisma.billingSubscription.findFirst({
    where: { stripeSubscriptionId: subId },
  });
  if (!sub) return;

  const stripeSubResponse = await stripe.subscriptions.retrieve(subId);
  const { periodStart, periodEnd } = getSubscriptionPeriod(stripeSubResponse as unknown as Stripe.Subscription);

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
  const subId = (invoice as any).subscription as string | undefined
    ?? (typeof invoice.parent?.subscription_details === 'object' ? (invoice.parent.subscription_details as any)?.subscription : undefined);
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
      currentPeriodStart: getSubscriptionPeriod(stripeSub).periodStart,
      currentPeriodEnd: getSubscriptionPeriod(stripeSub).periodEnd,
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
