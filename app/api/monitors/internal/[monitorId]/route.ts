import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ monitorId: string }> },
) {
  if (request.headers.get('x-internal-secret') !== (process.env.INTERNAL_API_SECRET ?? 'pallisade-internal')) {
    return NextResponse.json({ error: 'Unauthorised' }, { status: 401 });
  }
  const orgId = request.headers.get('x-organization-id');
  if (!orgId) return NextResponse.json({ error: 'Missing org' }, { status: 400 });

  const { monitorId } = await params;

  const monitor = await prisma.monitor.findFirst({
    where: { id: monitorId, organizationId: orgId },
  });
  if (!monitor) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  await prisma.monitor.delete({ where: { id: monitorId } });

  return NextResponse.json({
    monitorId: monitor.id,
    monitorKind: monitor.monitorType,
    targetFqn: monitor.targetFqn,
    deleted: true,
  });
}
