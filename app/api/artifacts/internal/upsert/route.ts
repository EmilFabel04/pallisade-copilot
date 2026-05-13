// app/api/artifacts/internal/upsert/route.ts
import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

function unauthorised() {
  return NextResponse.json({ error: 'Unauthorised' }, { status: 401 });
}

export async function POST(request: NextRequest) {
  if (request.headers.get('x-internal-secret') !== (process.env.INTERNAL_API_SECRET ?? 'pallisade-internal')) {
    return unauthorised();
  }
  const orgId = request.headers.get('x-organization-id');
  const userId = request.headers.get('x-user-id');
  if (!orgId || !userId) {
    return NextResponse.json({ error: 'Missing org/user' }, { status: 400 });
  }

  const body = await request.json();
  const {
    idempotencyKey, kind, status, subtype, payload, title, summary,
    sourceSessionId, sourceMessageId, agentSessionId, toolCallId, agentRunId,
    integrationId, externalRef, riskLevel, rollbackHint, isSaved,
  } = body;

  if (!idempotencyKey || !kind || !status || !payload || !title) {
    return NextResponse.json({ error: 'Missing required fields' }, { status: 400 });
  }

  const data = {
    organizationId: orgId,
    userId,
    kind, status, subtype, payload, title, summary,
    sourceSessionId, sourceMessageId, agentSessionId, toolCallId, agentRunId,
    integrationId, externalRef, riskLevel, rollbackHint,
    isSaved: isSaved ?? false,
    appliedAt: status === 'applied' ? new Date() : null,
  };

  const artifact = await prisma.artifact.upsert({
    where: { idempotencyKey_organizationId: { idempotencyKey, organizationId: orgId } },
    create: { ...data, idempotencyKey },
    update: {
      // Provenance fields (subtype, *SessionId, toolCallId, agentRunId, integrationId, riskLevel)
      // are fixed at create-time and intentionally not mutated on retry.
      status, payload, externalRef, summary, title, rollbackHint,
      appliedAt: status === 'applied' ? new Date() : undefined,
      // isSaved: re-emit can set true, never reset to false.
      isSaved: isSaved || undefined,
    },
  });

  return NextResponse.json(artifact, { status: 201 });
}
