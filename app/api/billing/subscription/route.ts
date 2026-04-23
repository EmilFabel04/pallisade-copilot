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
