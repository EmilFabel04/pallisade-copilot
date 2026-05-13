import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const userId = (session.user as any).id;
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) {
    return NextResponse.json({ error: 'No organization' }, { status: 400 });
  }

  const body = await request.json().catch(() => ({}));
  const { title, body: docBody, format = 'md', sourceSessionId, sourceMessageId, tags } = body as {
    title?: string;
    body?: string;
    format?: 'md' | 'html' | 'pdf';
    sourceSessionId?: string;
    sourceMessageId?: string;
    tags?: string[];
  };

  if (!docBody || typeof docBody !== 'string') {
    return NextResponse.json({ error: 'body is required' }, { status: 400 });
  }
  if (!['md', 'html', 'pdf'].includes(format)) {
    return NextResponse.json({ error: `invalid format: ${format}` }, { status: 400 });
  }

  const derivedTitle =
    (title && title.trim()) ||
    docBody.split('\n').find((l) => l.trim())?.slice(0, 80) ||
    'Untitled document';

  const summaryLine =
    docBody
      .split('\n')
      .map((l) => l.trim())
      .find((l) => l && !l.startsWith('#')) ?? null;

  const artefact = await prisma.artifact.create({
    data: {
      userId,
      organizationId,
      kind: 'DOCUMENT',
      status: 'applied',
      title: derivedTitle,
      summary: summaryLine ? summaryLine.slice(0, 240) : null,
      payload: { kind: 'DOCUMENT', format, body: docBody },
      sourceSessionId: sourceSessionId ?? null,
      sourceMessageId: sourceMessageId ?? null,
      tags: tags ?? [],
      isSaved: true,
      appliedAt: new Date(),
    },
  });

  return NextResponse.json({ artefact }, { status: 201 });
}
