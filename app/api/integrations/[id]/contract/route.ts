import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/integrations/[id]/contract — fetch source contract
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const contract = await prisma.sourceContract.findUnique({
      where: { integrationId: id },
    });

    return NextResponse.json({ contract: contract || null });
  } catch (error) {
    console.error('Error fetching source contract:', error);
    return NextResponse.json({ error: 'Failed to fetch contract' }, { status: 500 });
  }
}

// PATCH /api/integrations/[id]/contract — create or update source contract
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();

    // Validate allowed fields only
    const allowed = [
      'ownerUser', 'ownerTeam', 'contactChannel', 'slaTier',
      'expectedFreshnessMinutes', 'expectedExtractionFrequencyMinutes', 'notes',
    ];
    const data: Record<string, any> = {};
    for (const key of allowed) {
      if (key in body) data[key] = body[key];
    }

    // Validate slaTier if provided
    if (data.slaTier && !['T0', 'T1', 'T2', 'T3'].includes(data.slaTier)) {
      return NextResponse.json({ error: 'Invalid slaTier. Must be T0, T1, T2, or T3.' }, { status: 400 });
    }

    // Validate numeric fields
    for (const numField of ['expectedFreshnessMinutes', 'expectedExtractionFrequencyMinutes']) {
      if (data[numField] !== undefined && data[numField] !== null) {
        const val = Number(data[numField]);
        if (isNaN(val) || val < 0) {
          return NextResponse.json({ error: `${numField} must be a non-negative number` }, { status: 400 });
        }
        data[numField] = val;
      }
    }

    // Verify integration exists
    const integration = await prisma.integration.findUnique({
      where: { id },
      select: { id: true },
    });
    if (!integration) {
      return NextResponse.json({ error: 'Integration not found' }, { status: 404 });
    }

    const contract = await prisma.sourceContract.upsert({
      where: { integrationId: id },
      create: { integrationId: id, ...data },
      update: data,
    });

    return NextResponse.json({ contract });
  } catch (error) {
    console.error('Error updating source contract:', error);
    return NextResponse.json({ error: 'Failed to update contract' }, { status: 500 });
  }
}
