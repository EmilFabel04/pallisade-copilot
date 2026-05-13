// app/api/artifacts/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { ArtifactKind, ArtifactStatus } from '@prisma/client';

// GET /api/artifacts — list artefacts with filters
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const userId = (session.user as any).id;
    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const { searchParams } = new URL(request.url);
    const kindParam = searchParams.get('kind');
    const statusParam = searchParams.get('status');
    const subtype = searchParams.get('subtype');
    const search = searchParams.get('search');
    const tagsParam = searchParams.get('tags');
    const pinned = searchParams.get('pinned');
    const source = searchParams.get('source'); // 'agent' | 'user' | null
    const includeUnsaved = searchParams.get('includeUnsaved') === 'true';
    const limit = parseInt(searchParams.get('limit') || '50', 10);
    const offset = parseInt(searchParams.get('offset') || '0', 10);

    const kinds = kindParam ? (kindParam.split(',').filter(Boolean) as ArtifactKind[]) : null;
    const statuses = statusParam
      ? (statusParam.split(',').filter(Boolean) as ArtifactStatus[])
      : (['proposed', 'approved', 'applied', 'open', 'resolved'] as ArtifactStatus[]);
    const tags = tagsParam?.split(',').filter(Boolean);

    const where: any = { organizationId, userId };
    if (kinds && kinds.length > 0) where.kind = { in: kinds };
    where.status = { in: statuses };
    if (subtype) where.subtype = subtype;
    if (pinned === 'true') where.isPinned = true;
    if (!includeUnsaved) where.OR = [{ isSaved: true }, { status: { not: 'draft' as ArtifactStatus } }];
    if (search) {
      where.AND = [
        ...(where.AND ?? []),
        {
          OR: [
            { title: { contains: search, mode: 'insensitive' } },
            { summary: { contains: search, mode: 'insensitive' } },
          ],
        },
      ];
    }
    if (tags && tags.length > 0) where.tags = { hasSome: tags };
    if (source === 'agent') where.toolCallId = { not: null };
    if (source === 'user') where.toolCallId = null;

    const [artifacts, total] = await Promise.all([
      prisma.artifact.findMany({
        where,
        orderBy: [{ isPinned: 'desc' }, { createdAt: 'desc' }],
        take: limit,
        skip: offset,
        include: {
          sourceSession: { select: { id: true, title: true } },
          agentSession: { select: { id: true, title: true } },
          integration: { select: { id: true, type: true } },
        },
      }),
      prisma.artifact.count({ where }),
    ]);

    return NextResponse.json({
      artifacts,
      pagination: { total, limit, offset, hasMore: offset + artifacts.length < total },
    });
  } catch (error) {
    console.error('[ARTIFACTS] Error listing:', error);
    return NextResponse.json({ error: 'Failed to list artifacts' }, { status: 500 });
  }
}
