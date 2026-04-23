import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// Map from frontend field names to Prisma field names
const BOOLEAN_FIELD_MAP: Record<string, string> = {
  dataSLAsEnabled: 'dataContractsEnabled',         // new frontend name → Prisma column
  dataContractsEnabled: 'dataContractsEnabled',    // legacy compat
  slaAllowOverrides: 'contractAllowOverrides',     // new frontend name → Prisma column
  contractAllowOverrides: 'contractAllowOverrides', // legacy compat
  contractViolationAlerting: 'contractViolationAlerting',
};

// PATCH /api/pipeline/[stackId]/settings — update pipeline settings
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
    const data: Record<string, any> = {};

    for (const [frontendField, prismaField] of Object.entries(BOOLEAN_FIELD_MAP)) {
      if (frontendField in body) {
        data[prismaField] = Boolean(body[frontendField]);
      }
    }

    if (Object.keys(data).length === 0) {
      return NextResponse.json({ error: 'No valid fields to update' }, { status: 400 });
    }

    const pipeline = await prisma.pipelineStack.update({
      where: { id: stackId },
      data,
      select: {
        id: true,
        dataContractsEnabled: true,
        contractAllowOverrides: true,
        contractViolationAlerting: true,
      },
    });

    return NextResponse.json({ pipeline });
  } catch (error) {
    console.error('Error updating pipeline settings:', error);
    return NextResponse.json({ error: 'Failed to update settings' }, { status: 500 });
  }
}
