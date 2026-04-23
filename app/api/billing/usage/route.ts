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
