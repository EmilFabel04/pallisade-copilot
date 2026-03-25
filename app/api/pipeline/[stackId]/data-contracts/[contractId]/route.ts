import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { Prisma } from '@prisma/client';
import { DataContractInputSchema } from '@/lib/data-contracts/types';

// PATCH /api/pipeline/[stackId]/data-contracts/[contractId]
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; contractId: string }> }
) {
  try {
    const { stackId, contractId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const parsed = DataContractInputSchema.partial().safeParse(body);
    if (!parsed.success) {
      const issues = parsed.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ');
      return NextResponse.json({ error: `Validation failed: ${issues}` }, { status: 400 });
    }

    const contract = await prisma.pipelineDataContract.update({
      where: { id: contractId, pipelineStackId: stackId },
      data: {
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

    return NextResponse.json({ contract });
  } catch (error) {
    console.error('Error updating data contract:', error);
    return NextResponse.json({ error: 'Failed to update data contract' }, { status: 500 });
  }
}

// DELETE /api/pipeline/[stackId]/data-contracts/[contractId]
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string; contractId: string }> }
) {
  try {
    const { stackId, contractId } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    await prisma.pipelineDataContract.delete({
      where: { id: contractId, pipelineStackId: stackId },
    });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error deleting data contract:', error);
    return NextResponse.json({ error: 'Failed to delete data contract' }, { status: 500 });
  }
}
