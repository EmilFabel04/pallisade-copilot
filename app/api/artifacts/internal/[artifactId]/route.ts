// app/api/artifacts/internal/[artifactId]/route.ts
import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ artifactId: string }> },
) {
  if (request.headers.get('x-internal-secret') !== (process.env.INTERNAL_API_SECRET ?? 'pallisade-internal')) {
    return NextResponse.json({ error: 'Unauthorised' }, { status: 401 });
  }
  const { artifactId } = await params;
  const orgId = request.headers.get('x-organization-id');
  if (!orgId) {
    return NextResponse.json({ error: 'Missing org' }, { status: 400 });
  }
  const body = await request.json();
  const { status, externalRefPatch, payloadPatch } = body;

  const existing = await prisma.artifact.findUnique({ where: { id: artifactId } });
  if (!existing || existing.organizationId !== orgId) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  const externalRef = externalRefPatch
    ? { ...(existing.externalRef as Record<string, unknown> ?? {}), ...externalRefPatch }
    : undefined;
  const payload = payloadPatch
    ? { ...(existing.payload as Record<string, unknown>), ...payloadPatch }
    : undefined;

  const updated = await prisma.artifact.update({
    where: { id: artifactId },
    data: {
      status,
      externalRef,
      payload,
      appliedAt: status === 'applied' ? new Date() : undefined,
    },
  });

  return NextResponse.json(updated);
}
