import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ results: [] });
    }

    const { searchParams } = new URL(request.url);
    const query = searchParams.get('q')?.trim();

    if (!query || query.length < 2) {
      return NextResponse.json({ results: [] });
    }

    const orgId = user.organizationId;

    // Run all searches in parallel — each is independent so one failure doesn't break the rest
    const [nodesResult, artifactsResult, tasksResult] = await Promise.allSettled([
      prisma.pipelineNode.findMany({
        where: {
          stack: { organizationId: orgId },
          OR: [
            { name: { contains: query, mode: 'insensitive' } },
            { toolType: { contains: query, mode: 'insensitive' } },
          ],
        },
        select: {
          id: true,
          name: true,
          toolType: true,
          layer: true,
          status: true,
          stackId: true,
        },
        take: 8,
      }),
      prisma.artifact.findMany({
        where: {
          organizationId: orgId,
          OR: [
            { title: { contains: query, mode: 'insensitive' } },
            { tags: { hasSome: [query.toLowerCase()] } },
          ],
        },
        select: {
          id: true,
          title: true,
          type: true,
          tags: true,
          updatedAt: true,
        },
        take: 6,
      }),
      prisma.scanSchedule.findMany({
        where: {
          organizationId: orgId,
          name: { contains: query, mode: 'insensitive' },
        },
        select: {
          id: true,
          name: true,
          scanTypes: true,
          enabled: true,
          lastRunStatus: true,
        },
        take: 5,
      }),
    ]);

    const nodes = nodesResult.status === 'fulfilled' ? nodesResult.value : [];
    const artifacts = artifactsResult.status === 'fulfilled' ? artifactsResult.value : [];
    const tasks = tasksResult.status === 'fulfilled' ? tasksResult.value : [];

    // Log any individual query failures for debugging
    if (nodesResult.status === 'rejected') console.error('Search nodes error:', nodesResult.reason);
    if (artifactsResult.status === 'rejected') console.error('Search artifacts error:', artifactsResult.reason);
    if (tasksResult.status === 'rejected') console.error('Search tasks error:', tasksResult.reason);

    // Combine into unified result set
    const results = [
      ...nodes.map((n) => ({
        id: n.id,
        title: n.name,
        subtitle: `${n.toolType} · ${n.layer}`,
        category: 'source' as const,
        href: `/dashboard/pipeline?node=${n.id}`,
        status: n.status,
        icon: n.toolType,
      })),
      ...artifacts.map((a) => ({
        id: a.id,
        title: a.title,
        subtitle: a.type + (a.tags.length ? ` · ${a.tags.join(', ')}` : ''),
        category: 'artifact' as const,
        href: `/dashboard/artifacts?id=${a.id}`,
        icon: a.type,
      })),
      ...tasks.map((t) => ({
        id: t.id,
        title: t.name,
        subtitle: `${t.scanTypes.join(', ')}${t.enabled ? '' : ' (disabled)'}`,
        category: 'task' as const,
        href: `/dashboard/schedule?task=${t.id}`,
        status: t.lastRunStatus,
        icon: 'task',
      })),
    ];

    return NextResponse.json({ results });
  } catch (error) {
    console.error('Search error:', error);
    return NextResponse.json({ results: [], error: 'Search failed' }, { status: 500 });
  }
}
