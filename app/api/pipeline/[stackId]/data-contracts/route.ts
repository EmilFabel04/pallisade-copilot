import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { Prisma } from '@prisma/client';
import { DataContractInputSchema } from '@/lib/data-contracts/types';

// GET /api/pipeline/[stackId]/data-contracts — list all data contracts
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

    const contracts = await prisma.pipelineDataContract.findMany({
      where: { pipelineStackId: stackId },
      include: { exceptions: { select: { id: true, scopeRef: true } } },
      orderBy: { updatedAt: 'desc' },
    });

    return NextResponse.json({ contracts });
  } catch (error) {
    console.error('Error fetching data contracts:', error);
    return NextResponse.json({ error: 'Failed to fetch data contracts' }, { status: 500 });
  }
}

// POST /api/pipeline/[stackId]/data-contracts — create a data contract
export async function POST(
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
    const parsed = DataContractInputSchema.safeParse(body);
    if (!parsed.success) {
      const issues = parsed.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ');
      return NextResponse.json({ error: `Validation failed: ${issues}` }, { status: 400 });
    }

    const pipeline = await prisma.pipelineStack.findUnique({
      where: { id: stackId },
      select: { id: true },
    });
    if (!pipeline) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    const contract = await prisma.pipelineDataContract.create({
      data: {
        pipelineStackId: stackId,
        ...parsed.data,
        schemaExpectations: parsed.data.schemaExpectations != null
          ? parsed.data.schemaExpectations as unknown as Prisma.InputJsonValue
          : undefined,
        qualityRules: parsed.data.qualityRules != null
          ? parsed.data.qualityRules as unknown as Prisma.InputJsonValue
          : undefined,
        alertPolicyJson: parsed.data.alertPolicyJson != null
          ? parsed.data.alertPolicyJson as Prisma.InputJsonValue
          : undefined,
        overridesJson: parsed.data.overridesJson != null
          ? parsed.data.overridesJson as unknown as Prisma.InputJsonValue
          : undefined,
      },
    });

    return NextResponse.json({ contract }, { status: 201 });
  } catch (error: any) {
    if (error?.code === 'P2002') {
      return NextResponse.json({ error: 'A contract already exists for this scope and reference' }, { status: 409 });
    }
    console.error('Error creating data contract:', error);
    return NextResponse.json({ error: 'Failed to create data contract' }, { status: 500 });
  }
}
