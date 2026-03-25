import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

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

    if ('dataContractsEnabled' in body) {
      data.dataContractsEnabled = Boolean(body.dataContractsEnabled);
    }

    if (Object.keys(data).length === 0) {
      return NextResponse.json({ error: 'No valid fields to update' }, { status: 400 });
    }

    const pipeline = await prisma.pipelineStack.update({
      where: { id: stackId },
      data,
      select: { id: true, dataContractsEnabled: true },
    });

    return NextResponse.json({ pipeline });
  } catch (error) {
    console.error('Error updating pipeline settings:', error);
    return NextResponse.json({ error: 'Failed to update settings' }, { status: 500 });
  }
}
