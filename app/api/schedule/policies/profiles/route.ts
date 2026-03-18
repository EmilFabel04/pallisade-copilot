import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/schedule/policies/profiles — List all profiles (built-in + custom)
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const profiles = await prisma.policyProfile.findMany({
      where: { organizationId },
      orderBy: [{ isBuiltIn: 'desc' }, { name: 'asc' }],
    });

    return NextResponse.json({ profiles });
  } catch (error: any) {
    console.error('[Policies] Error listing profiles:', error);
    return NextResponse.json({ error: error.message || 'Failed to list profiles' }, { status: 500 });
  }
}

// POST /api/schedule/policies/profiles — Create a new profile
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const body = await request.json();

    const profile = await prisma.policyProfile.create({
      data: {
        organizationId,
        name: body.name,
        description: body.description || null,
        isBuiltIn: false,
        targetDomain: body.targetDomain || null,
        criticality: body.criticality || null,
        freshnessConfig: body.freshnessConfig || undefined,
        schemaConfig: body.schemaConfig || undefined,
        volumeConfig: body.volumeConfig || undefined,
        anomalyConfig: body.anomalyConfig || undefined,
        qualityConfig: body.qualityConfig || undefined,
        ingestionConfig: body.ingestionConfig || undefined,
        biConfig: body.biConfig || undefined,
        orchestrationConfig: body.orchestrationConfig || undefined,
        transformConfig: body.transformConfig || undefined,
      },
    });

    return NextResponse.json({ profile }, { status: 201 });
  } catch (error: any) {
    console.error('[Policies] Error creating profile:', error);
    if (error.code === 'P2002') {
      return NextResponse.json({ error: 'A profile with this name already exists' }, { status: 409 });
    }
    return NextResponse.json({ error: error.message || 'Failed to create profile' }, { status: 500 });
  }
}
