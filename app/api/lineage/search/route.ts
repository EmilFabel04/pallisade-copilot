import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// GET /api/lineage/search?q=stg&stackId=...&limit=10
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { searchParams } = new URL(request.url);
    const q = searchParams.get('q') || '';
    const limit = Math.min(parseInt(searchParams.get('limit') || '10'), 50);

    if (!q.trim()) {
      return NextResponse.json({ results: [] });
    }

    const nodes = await prisma.lineageNode.findMany({
      where: {
        organizationId,
        OR: [
          { name: { contains: q, mode: 'insensitive' } },
          { tableName: { contains: q, mode: 'insensitive' } },
        ],
      },
      select: {
        id: true,
        name: true,
        tableName: true,
        nodeType: true,
        platform: true,
      },
      orderBy: { name: 'asc' },
      take: limit,
    });

    return NextResponse.json({
      results: nodes.map((n) => ({
        id: n.id,
        name: n.tableName || n.name,
        fqn: n.name,
        nodeType: n.nodeType,
        platform: n.platform,
      })),
    });
  } catch (error: any) {
    console.error('[Lineage Search] Error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
