// app/api/copilot/sessions/fork/route.ts
import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

export async function POST(request: NextRequest) {
  if (request.headers.get('x-internal-secret') !== (process.env.INTERNAL_API_SECRET ?? 'pallisade-internal')) {
    return NextResponse.json({ error: 'Unauthorised' }, { status: 401 });
  }
  const orgId = request.headers.get('x-organization-id');
  const userId = request.headers.get('x-user-id');
  if (!orgId || !userId) {
    return NextResponse.json({ error: 'Missing org/user' }, { status: 400 });
  }

  const { parentSessionId, title } = await request.json();
  if (!parentSessionId || !title) {
    return NextResponse.json({ error: 'parentSessionId and title required' }, { status: 400 });
  }

  const parent = await prisma.copilotSession.findUnique({ where: { id: parentSessionId } });
  if (!parent || parent.organizationId !== orgId) {
    return NextResponse.json({ error: 'Parent session not found' }, { status: 404 });
  }

  const child = await prisma.copilotSession.create({
    data: {
      title,
      organizationId: orgId,
      userId,
      contextType: parent.contextType,
      pipelineStackId: parent.pipelineStackId,
      nodeIds: parent.nodeIds,
      model: parent.model,
    },
  });

  return NextResponse.json({ sessionId: child.id }, { status: 201 });
}
