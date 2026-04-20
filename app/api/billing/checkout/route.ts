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
