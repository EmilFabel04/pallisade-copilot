import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { invalidateBillingCache } from '@/lib/billing';

const PAYSTACK_API = 'https://api.paystack.co';
const PAYSTACK_SECRET = () => process.env.PAYSTACK_SECRET_KEY!;

// POST — Cancel subscription
// PayStack has no customer portal, so we handle cancellation directly
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
    select: { paystackSubscriptionCode: true, paystackEmailToken: true },
  });

  if (!sub?.paystackSubscriptionCode) {
    return NextResponse.json({ error: 'No active subscription' }, { status: 404 });
  }

  const body = await request.json().catch(() => ({}));

  if (body.action === 'cancel') {
    const res = await fetch(`${PAYSTACK_API}/subscription/disable`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${PAYSTACK_SECRET()}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        code: sub.paystackSubscriptionCode,
        token: sub.paystackEmailToken,
      }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return NextResponse.json({ error: data.message || 'Failed to cancel' }, { status: 500 });
    }

    await prisma.billingSubscription.update({
      where: { orgId: organizationId },
      data: { status: 'CANCELED' },
    });

    invalidateBillingCache(organizationId);
    return NextResponse.json({ success: true, message: 'Subscription canceled' });
  }

  return NextResponse.json({ error: 'Invalid action. Use { action: "cancel" }' }, { status: 400 });
}
