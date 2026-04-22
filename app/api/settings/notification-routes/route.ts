import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

async function getOrgId(): Promise<string | null> {
  const session = await auth();
  if (!session?.user) return null;
  const user = await prisma.user.findUnique({
    where: { email: session.user.email! },
    select: { organizationId: true },
  });
  return user?.organizationId || null;
}

// GET /api/settings/notification-routes
export async function GET() {
  try {
    const orgId = await getOrgId();
    if (!orgId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

    // Load legacy severity routes
    const routes = await prisma.notificationRoute.findMany({
      where: { organizationId: orgId },
      orderBy: { severity: 'asc' },
    });

    // Load org defaults (stored as a special "ORG_DEFAULTS" severity key)
    const defaultsRow = routes.find((r) => r.severity === 'ORG_DEFAULTS');
    const orgDefaults = defaultsRow
      ? {
          destinations: (defaultsRow.destinations as any) || [],
          notifyOnRecovery: defaultsRow.notifyOnRecovery,
        }
      : null;

    return NextResponse.json({
      routes: routes.filter((r) => r.severity !== 'ORG_DEFAULTS'),
      orgDefaults,
    });
  } catch (error: any) {
    console.error('[NotificationRoutes] GET error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// PUT /api/settings/notification-routes
export async function PUT(request: NextRequest) {
  try {
    const orgId = await getOrgId();
    if (!orgId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

    const body = await request.json();

    // New shape: { orgDefaults: { destinations, notifyOnRecovery } }
    if (body.orgDefaults) {
      const { destinations = [], notifyOnRecovery = false } = body.orgDefaults;

      const result = await prisma.notificationRoute.upsert({
        where: {
          organizationId_severity: {
            organizationId: orgId,
            severity: 'ORG_DEFAULTS',
          },
        },
        create: {
          organizationId: orgId,
          severity: 'ORG_DEFAULTS',
          enabled: true,
          notifyOnRecovery,
          destinations,
        },
        update: {
          enabled: true,
          notifyOnRecovery,
          destinations,
        },
      });

      return NextResponse.json({ orgDefaults: result });
    }

    // Legacy shape: { routes: [...] } (old severity-based routing)
    const { routes } = body;
    if (!Array.isArray(routes)) {
      return NextResponse.json({ error: 'routes or orgDefaults required' }, { status: 400 });
    }

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
