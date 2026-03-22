import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/settings/notification-routes
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });
    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const routes = await prisma.notificationRoute.findMany({
      where: { organizationId: user.organizationId },
      orderBy: { severity: 'asc' },
    });

    return NextResponse.json({ routes });
  } catch (error: any) {
    console.error('[NotificationRoutes] GET error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// PUT /api/settings/notification-routes
export async function PUT(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });
    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { routes } = await request.json();
    if (!Array.isArray(routes)) {
      return NextResponse.json({ error: 'routes must be an array' }, { status: 400 });
    }

    const orgId = user.organizationId;
    const validSeverities = ['INFO', 'WARN', 'ERROR', 'CRITICAL'];

    const upserted = await prisma.$transaction(
      routes
        .filter((r: any) => validSeverities.includes(r.severity))
        .map((r: any) =>
          prisma.notificationRoute.upsert({
            where: {
              organizationId_severity: {
                organizationId: orgId,
                severity: r.severity,
              },
            },
            create: {
              organizationId: orgId,
              severity: r.severity,
              enabled: r.enabled ?? true,
              notifyOnRecovery: r.notifyOnRecovery ?? false,
              destinations: r.destinations ?? [],
            },
            update: {
              enabled: r.enabled ?? true,
              notifyOnRecovery: r.notifyOnRecovery ?? false,
              destinations: r.destinations ?? [],
            },
          }),
        ),
    );

    return NextResponse.json({ routes: upserted });
  } catch (error: any) {
    console.error('[NotificationRoutes] PUT error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
