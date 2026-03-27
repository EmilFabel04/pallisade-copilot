import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// GET /api/schedule/policies/assignments?stackId=X&domain=Y&tier=Z
export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const organizationId = (session.user as any).organizationId;
  if (!organizationId) {
    return NextResponse.json({ error: 'No organization found' }, { status: 400 });
  }

  const { searchParams } = request.nextUrl;
  const stackId = searchParams.get('stackId');
  if (!stackId) {
    return NextResponse.json({ error: 'stackId required' }, { status: 400 });
  }

  const domainFilter = searchParams.get('domain');
  const tierFilter = searchParams.get('tier');

  try {
    // Pipeline SLA domains — excludes 'warehouse' and null which are data lineage SLAs
    const PIPELINE_DOMAINS = ['ingestion', 'orchestration', 'transform', 'bi'];

    const where: any = {
      organizationId,
      assignmentType: 'direct',
      nodeDomain: domainFilter ? domainFilter : { in: PIPELINE_DOMAINS },
    };

    const assignments = await prisma.policyAssignment.findMany({
      where,
      include: { profile: true },
      orderBy: { updatedAt: 'desc' },
    });

    const items = assignments.map(a => ({
      assignmentId: a.id,
      nodeFqn: a.nodeFqn || null,
      profileId: a.profileId,
      profileName: a.profile?.name || null,
      nodeDomain: a.nodeDomain || null,
      overrides: a.overrides || null,
      slaTier: a.profile?.criticality || null,
      status: a.status || 'active',
      archivedAt: a.archivedAt?.toISOString() || null,
      updatedAt: a.updatedAt?.toISOString() || null,
    }));

    const filtered = tierFilter
      ? items.filter(i => i.slaTier?.toUpperCase() === tierFilter.toUpperCase())
      : items;

    return NextResponse.json({ assignments: filtered });
  } catch (error) {
    console.error('Error fetching policy assignments:', error);
    return NextResponse.json({ error: 'Failed to fetch assignments' }, { status: 500 });
  }
}
