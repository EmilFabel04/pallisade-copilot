import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/integrations/saved
// Returns a lightweight list of saved connections so users can pick an existing integration
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
      return NextResponse.json({ connections: [] });
    }

    const searchParams = request.nextUrl.searchParams;
    const typeFilter = searchParams.get('type') || undefined;

    const connections = await prisma.integration.findMany({
      where: {
        organizationId: user.organizationId,
        ...(typeFilter ? { type: typeFilter } : {}),
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


