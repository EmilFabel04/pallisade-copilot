import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { prisma } from '@/lib/db';

/**
 * GET /api/copilot/sessions
 * List all chat sessions for the current user
 */
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const limit = parseInt(searchParams.get('limit') || '20');
    const pipelineStackId = searchParams.get('pipelineStackId');

    const sessions = await prisma.copilotSession.findMany({
      where: {
        userId: session.user.id,
        ...(pipelineStackId ? { pipelineStackId } : {}),
      },
      orderBy: {
        updatedAt: 'desc',
      },
      take: limit,
      select: {
        id: true,
        title: true,
        contextType: true,
        pipelineStackId: true,
        model: true,
        createdAt: true,
        updatedAt: true,
        messages: {
          take: 1,
          orderBy: { createdAt: 'desc' },
          select: {
            content: true,
            role: true,
          },
        },
      },
    });

    // Format for frontend
    const formatted = sessions.map(s => ({
      id: s.id,
      title: s.title,
      contextType: s.contextType,
      pipelineStackId: s.pipelineStackId,
      model: s.model,
      createdAt: s.createdAt,
      updatedAt: s.updatedAt,
      lastMessage: s.messages[0]?.content?.substring(0, 100) || null,
      lastMessageRole: s.messages[0]?.role || null,
    }));

    return NextResponse.json({ sessions: formatted });
  } catch (error) {
    console.error('Error fetching sessions:', error);
    return NextResponse.json(
      { error: 'Failed to fetch sessions' },
      { status: 500 }
    );
  }
}

/**
 * POST /api/copilot/sessions
 * Create a new chat session
 */
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.id || !session?.user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const { title, contextType, pipelineStackId } = body;

    const newSession = await prisma.copilotSession.create({
      data: {
        title: title || 'New Chat',
        contextType: contextType || 'GENERAL',
        pipelineStackId: pipelineStackId || null,
        userId: session.user.id,
        organizationId: session.user.organizationId,
      },
    });

    return NextResponse.json({ session: newSession });
  } catch (error) {
    console.error('Error creating session:', error);
    return NextResponse.json(
      { error: 'Failed to create session' },
      { status: 500 }
    );
  }
}
