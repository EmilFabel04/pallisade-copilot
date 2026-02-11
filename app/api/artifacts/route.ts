import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { ArtifactType } from '@prisma/client';

// GET /api/artifacts - List artifacts with filters
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const userId = (session.user as any).id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const { searchParams } = new URL(request.url);
    const type = searchParams.get('type') as ArtifactType | null;
    const search = searchParams.get('search');
    const tags = searchParams.get('tags')?.split(',').filter(Boolean);
    const pinned = searchParams.get('pinned');
    const limit = parseInt(searchParams.get('limit') || '50', 10);
    const offset = parseInt(searchParams.get('offset') || '0', 10);

    // Build where clause
    const where: any = {
      organizationId,
      userId,
    };

    if (type) {
      where.type = type;
    }

    if (pinned === 'true') {
      where.isPinned = true;
    }

    if (search) {
      where.OR = [
        { title: { contains: search, mode: 'insensitive' } },
        { content: { contains: search, mode: 'insensitive' } },
      ];
    }

    if (tags && tags.length > 0) {
      where.tags = { hasSome: tags };
    }

    const [artifacts, total] = await Promise.all([
      prisma.artifact.findMany({
        where,
        orderBy: [
          { isPinned: 'desc' },
          { createdAt: 'desc' },
        ],
        take: limit,
        skip: offset,
        include: {
          sourceSession: {
            select: {
              id: true,
              title: true,
            },
          },
        },
      }),
      prisma.artifact.count({ where }),
    ]);

    return NextResponse.json({
      artifacts,
      pagination: {
        total,
        limit,
        offset,
        hasMore: offset + artifacts.length < total,
      },
    });
  } catch (error) {
    console.error('[ARTIFACTS] Error listing artifacts:', error);
    return NextResponse.json(
      { error: 'Failed to list artifacts' },
      { status: 500 }
    );
  }
}

// POST /api/artifacts - Create new artifact
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const userId = (session.user as any).id;
    const organizationId = (session.user as any).organizationId;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const body = await request.json();
    const { title, content, type, tags, sourceSessionId, sourceMessageId, metadata } = body;

    if (!title || !content || !type) {
      return NextResponse.json(
        { error: 'Missing required fields: title, content, type' },
        { status: 400 }
      );
    }

    // Validate type
    const validTypes: ArtifactType[] = ['QUERY', 'FIX', 'INSIGHT', 'CODE', 'PLAN'];
    if (!validTypes.includes(type)) {
      return NextResponse.json(
        { error: `Invalid type. Must be one of: ${validTypes.join(', ')}` },
        { status: 400 }
      );
    }

    const artifact = await prisma.artifact.create({
      data: {
        title,
        content,
        type,
        tags: tags || [],
        sourceSessionId,
        sourceMessageId,
        metadata,
        userId,
        organizationId,
      },
      include: {
        sourceSession: {
          select: {
            id: true,
            title: true,
          },
        },
      },
    });

    return NextResponse.json({ artifact }, { status: 201 });
  } catch (error) {
    console.error('[ARTIFACTS] Error creating artifact:', error);
    return NextResponse.json(
      { error: 'Failed to create artifact' },
      { status: 500 }
    );
  }
}
