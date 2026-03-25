import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// GET /api/pipeline/[stackId]/sla — fetch pipeline SLA + coverage stats
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const { stackId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const contract = await prisma.pipelineContract.findUnique({
      where: { pipelineStackId: stackId },
    });

    // Coverage stats: count source contracts and their inheritance state
    const sourceContracts = await prisma.sourceContract.findMany({
      where: { pipelineStackId: stackId },
      select: { inheritFromPipeline: true, overridesJson: true },
    });

    // Count integrations in this pipeline (via pipeline nodes)
    const totalIntegrations = await prisma.pipelineNode.count({
      where: { stackId, integrationId: { not: null } },
    });

    const inherited = sourceContracts.filter(sc => sc.inheritFromPipeline && !sc.overridesJson).length;
    const overridden = sourceContracts.filter(sc => !sc.inheritFromPipeline || sc.overridesJson).length;
    const noContract = totalIntegrations - sourceContracts.length;

    return NextResponse.json({
      contract: contract || null,
      coverage: { totalIntegrations, inherited, overridden, noContract },
    });
  } catch (error) {
    console.error('Error fetching pipeline contract:', error);
    return NextResponse.json({ error: 'Failed to fetch pipeline contract' }, { status: 500 });
  }
}

// PATCH /api/pipeline/[stackId]/sla — create or update pipeline SLA
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const { stackId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();

    // Validate allowed fields
    const allowed = [
      'ownerUser', 'ownerTeam', 'contactChannel', 'slaTier',
      'expectedFreshnessMinutes', 'expectedExtractionFrequencyMinutes',
      'alertPolicyJson', 'notes',
    ];
    const data: Record<string, any> = {};
    for (const key of allowed) {
      if (key in body) data[key] = body[key];
    }

    // Validate slaTier
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

    // Verify pipeline exists
    const pipeline = await prisma.pipelineStack.findUnique({
      where: { id: stackId },
      select: { id: true },
    });
    if (!pipeline) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    const contract = await prisma.pipelineContract.upsert({
      where: { pipelineStackId: stackId },
      create: { pipelineStackId: stackId, ...data },
      update: data,
    });

    return NextResponse.json({ contract });
  } catch (error) {
    console.error('Error updating pipeline contract:', error);
    return NextResponse.json({ error: 'Failed to update pipeline contract' }, { status: 500 });
  }
}
