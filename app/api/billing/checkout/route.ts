import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

const PAYSTACK_API = 'https://api.paystack.co';
const PAYSTACK_SECRET = () => process.env.PAYSTACK_SECRET_KEY!;

const PLAN_CODE_MAP: Record<string, string | undefined> = {
  GROWTH: process.env.PAYSTACK_GROWTH_PLAN_CODE,
  BUSINESS: process.env.PAYSTACK_BUSINESS_PLAN_CODE,
};

const CREDIT_AMOUNT_MAP: Record<string, number> = {
  '5M': 180000,   // R1,800 in kobo (~$100)
  '20M': 630000,  // R6,300 in kobo (~$350)
};

const PLAN_DEFAULTS: Record<string, { tokenAllowance: number; storageAllowanceGb: number; memberAllowance: number; pipelineAllowance: number }> = {
  GROWTH: { tokenAllowance: 5_000_000, storageAllowanceGb: 100, memberAllowance: 5, pipelineAllowance: 3 },
  BUSINESS: { tokenAllowance: 20_000_000, storageAllowanceGb: 500, memberAllowance: 15, pipelineAllowance: 6 },
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

  // Get user email for PayStack customer
  const user = await prisma.user.findUnique({
    where: { id: session.user.id },
    select: { email: true, name: true },
  });
  if (!user?.email) {
    return NextResponse.json({ error: 'User email required' }, { status: 400 });
  }

  // Get or create PayStack customer
  let customerCode: string;
  const existingSub = await prisma.billingSubscription.findUnique({
    where: { orgId: organizationId },
    select: { paystackCustomerCode: true },
  });

  if (existingSub?.paystackCustomerCode) {
    customerCode = existingSub.paystackCustomerCode;
  } else {
    const customerRes = await fetch(`${PAYSTACK_API}/customer`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${PAYSTACK_SECRET()}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        email: user.email,
        first_name: user.name?.split(' ')[0] || undefined,
        last_name: user.name?.split(' ').slice(1).join(' ') || undefined,
        metadata: { orgId: organizationId },
      }),
    });
    const customerData = await customerRes.json();
    if (!customerData.status) {
      return NextResponse.json({ error: 'Failed to create customer' }, { status: 500 });
    }
    customerCode = customerData.data.customer_code;

    // Pre-create BillingSubscription record so webhook can find it by customer code
    const plan = (body.plan || 'GROWTH') as string;
    const defaults = PLAN_DEFAULTS[plan] ?? PLAN_DEFAULTS.GROWTH;
    const now = new Date();
    const periodEnd = new Date(now);
    periodEnd.setMonth(periodEnd.getMonth() + 1);

    await prisma.billingSubscription.upsert({
      where: { orgId: organizationId },
      create: {
        orgId: organizationId,
        paystackCustomerCode: customerCode,
        plan: plan as any,
        status: 'TRIALING',
        currentPeriodStart: now,
        currentPeriodEnd: periodEnd,
        ...defaults,
      },
      update: { paystackCustomerCode: customerCode },
    });
  }

  if (body.type === 'credit') {
    // Credit top-up — one-time payment
    const block = body.block as string;
    const amount = CREDIT_AMOUNT_MAP[block];
    if (!amount) {
      return NextResponse.json({ error: 'Invalid credit block' }, { status: 400 });
    }

    const txRes = await fetch(`${PAYSTACK_API}/transaction/initialize`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${PAYSTACK_SECRET()}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        email: user.email,
        amount,
        callback_url: `${appUrl}/dashboard/settings?tab=billing&checkout=success`,
        metadata: { orgId: organizationId, type: 'credit', block },
      }),
    });
    const txData = await txRes.json();
    if (!txData.status) {
      return NextResponse.json({ error: 'Failed to initialize transaction' }, { status: 500 });
    }

    return NextResponse.json({ url: txData.data.authorization_url });
  }

  // Subscription checkout — initialize transaction with a plan
  const plan = body.plan as string;
  const planCode = PLAN_CODE_MAP[plan];
  if (!planCode) {
    return NextResponse.json({ error: 'Invalid plan' }, { status: 400 });
  }

  // Update plan defaults if switching plans
  const defaults = PLAN_DEFAULTS[plan] ?? PLAN_DEFAULTS.GROWTH;
  await prisma.billingSubscription.update({
    where: { orgId: organizationId },
    data: { plan: plan as any, ...defaults },
  });

  const txRes = await fetch(`${PAYSTACK_API}/transaction/initialize`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${PAYSTACK_SECRET()}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      email: user.email,
      plan: planCode,
      callback_url: `${appUrl}/dashboard/settings?tab=billing&checkout=success`,
      metadata: { orgId: organizationId, type: 'subscription', plan },
    }),
  });
  const txData = await txRes.json();
  if (!txData.status) {
    return NextResponse.json({ error: 'Failed to initialize checkout' }, { status: 500 });
  }

  return NextResponse.json({ url: txData.data.authorization_url });
}
