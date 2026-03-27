import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { Prisma } from '@prisma/client';
import { DataSLAInputSchema } from '@/lib/data-contracts/types';

const JSON_FIELDS = [
  'freshnessConfig', 'schemaConfig', 'volumeConfig', 'anomalyConfig',
  'qualityConfig', 'ingestionConfig', 'biConfig', 'orchestrationConfig',
  'transformConfig', 'schemaExpectations', 'qualityRules', 'alertPolicyJson',
  'overridesJson', 'nodeFqns',
] as const;

function buildCreateData(stackId: string, data: Record<string, any>): Prisma.PipelineDataContractUncheckedCreateInput {
  const result: Record<string, any> = { pipelineStackId: stackId };
  for (const [key, value] of Object.entries(data)) {
    if (JSON_FIELDS.includes(key as any)) {
      result[key] = value != null ? (value as Prisma.InputJsonValue) : undefined;
    } else {
      result[key] = value;
    }
  }
  return result as Prisma.PipelineDataContractUncheckedCreateInput;
}

// GET /api/pipeline/[stackId]/data-slas — list all data SLAs
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

    const [contracts, pipeline] = await Promise.all([
      prisma.pipelineDataContract.findMany({
        where: { pipelineStackId: stackId },
        include: { exceptions: { select: { id: true, scopeRef: true } } },
        orderBy: { updatedAt: 'desc' },
      }),
      prisma.pipelineStack.findUnique({
        where: { id: stackId },
        select: {
          dataContractsEnabled: true,
          contractAllowOverrides: true,
          contractViolationAlerting: true,
        },
      }),
    ]);

    return NextResponse.json({
      dataSLAs: contracts,
      dataContractsEnabled: pipeline?.dataContractsEnabled ?? false,
      contractAllowOverrides: pipeline?.contractAllowOverrides ?? false,
      contractViolationAlerting: pipeline?.contractViolationAlerting ?? true,
    });
  } catch (error) {
    console.error('Error fetching data SLAs:', error);
    return NextResponse.json({ error: 'Failed to fetch data SLAs' }, { status: 500 });
  }
}

// POST /api/pipeline/[stackId]/data-slas — create a data SLA
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
    const parsed = DataSLAInputSchema.safeParse(body);
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
      data: buildCreateData(stackId, parsed.data),
    });

    return NextResponse.json({ contract }, { status: 201 });
  } catch (error: any) {
    if (error?.code === 'P2002') {
      return NextResponse.json({ error: 'A data SLA already exists for this scope and reference' }, { status: 409 });
    }
    console.error('Error creating data SLA:', error);
    return NextResponse.json({ error: 'Failed to create data SLA' }, { status: 500 });
  }
}
