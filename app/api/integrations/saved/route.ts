import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { IntegrationType } from '@prisma/client';

// GET /api/integrations/saved
// Returns a lightweight list of saved connections so users can pick an existing integration
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ connections: [] });
    }

    const searchParams = request.nextUrl.searchParams;
    const typeFilter = searchParams.get('type') || undefined;
    // Support comma-separated types: ?types=SLACK,PAGERDUTY,JIRA
    // Validate against the Prisma enum to avoid runtime errors
    const validTypes = new Set(Object.values(IntegrationType));
    const typesFilter = searchParams.get('types')
      ?.split(',')
      .filter((t): t is IntegrationType => validTypes.has(t as IntegrationType)) || undefined;

    const connections = await prisma.integration.findMany({
      where: {
        organizationId: user.organizationId,
        ...(typesFilter?.length ? { type: { in: typesFilter } } : typeFilter ? { type: typeFilter as IntegrationType } : {}),
      },
      select: {
        id: true,
        name: true,
        type: true,
        status: true,
        connectionInfo: true,
        createdAt: true,
        updatedAt: true,
      },
      orderBy: { createdAt: 'desc' },
    });

    return NextResponse.json({ connections });
  } catch (error) {
    console.error('Error fetching saved connections:', error);
    return NextResponse.json({ error: 'Failed to fetch saved connections' }, { status: 500 });
  }
}


