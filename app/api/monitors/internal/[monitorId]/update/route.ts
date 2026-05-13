import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ monitorId: string }> },
) {
  if (request.headers.get('x-internal-secret') !== (process.env.INTERNAL_API_SECRET ?? 'pallisade-internal')) {
    return NextResponse.json({ error: 'Unauthorised' }, { status: 401 });
  }
  const orgId = request.headers.get('x-organization-id');
  if (!orgId) return NextResponse.json({ error: 'Missing org' }, { status: 400 });

  const { monitorId } = await params;
  const body = await request.json();
  const { config, policyOverrides } = body as {
    config?: Record<string, unknown>;
    policyOverrides?: string[];
  };

  const monitor = await prisma.monitor.findFirst({
    where: { id: monitorId, organizationId: orgId },
  });
  if (!monitor) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  const updated = await prisma.monitor.update({
    where: { id: monitorId },
    data: {
      ...(config !== undefined ? { config: config as object } : {}),
      ...(policyOverrides !== undefined ? { policyOverrides } : {}),
    },
  });

  return NextResponse.json({
    monitorId: updated.id,
    monitorKind: updated.monitorType,
    targetFqn: updated.targetFqn,
    config: updated.config,
    monitorGroupId: updated.monitorGroupId,
    configDiff: {
      before: monitor.config,
      after: updated.config,
    },
  });
}
