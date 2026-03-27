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

function buildUpdateData(data: Record<string, any>): Prisma.PipelineDataContractUpdateInput {
  const result: Record<string, any> = {};
  for (const [key, value] of Object.entries(data)) {
    if (JSON_FIELDS.includes(key as any)) {
      result[key] = value != null ? (value as Prisma.InputJsonValue) : Prisma.JsonNull;
    } else {
      result[key] = value;
    }
  }
  return result as Prisma.PipelineDataContractUpdateInput;
}

// PATCH /api/pipeline/[stackId]/data-slas/[slaId]
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; slaId: string }> }
) {
  try {
    const { stackId, slaId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const parsed = DataSLAInputSchema.partial().safeParse(body);
    if (!parsed.success) {
      const issues = parsed.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ');
      return NextResponse.json({ error: `Validation failed: ${issues}` }, { status: 400 });
    }

    const contract = await prisma.pipelineDataContract.update({
      where: { id: slaId, pipelineStackId: stackId },
      data: buildUpdateData(parsed.data),
    });

    return NextResponse.json({ contract });
  } catch (error) {
    console.error('Error updating data SLA:', error);
    return NextResponse.json({ error: 'Failed to update data SLA' }, { status: 500 });
  }
}

// DELETE /api/pipeline/[stackId]/data-slas/[slaId]
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; slaId: string }> }
) {
  try {
    const { stackId, slaId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    await prisma.pipelineDataContract.delete({
      where: { id: slaId, pipelineStackId: stackId },
    });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error deleting data SLA:', error);
    return NextResponse.json({ error: 'Failed to delete data SLA' }, { status: 500 });
  }
}
