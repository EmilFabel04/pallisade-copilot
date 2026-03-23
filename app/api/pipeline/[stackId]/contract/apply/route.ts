import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// POST /api/pipeline/[stackId]/contract/apply — apply pipeline defaults to all tools
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

    // Verify pipeline exists and has a contract
    const pipelineContract = await prisma.pipelineContract.findUnique({
      where: { pipelineStackId: stackId },
    });
    if (!pipelineContract) {
      return NextResponse.json(
        { error: 'No pipeline contract found. Create a pipeline contract first.' },
        { status: 400 }
      );
    }

    // Find all integrations in this pipeline that don't have a source contract yet
    const nodesWithIntegrations = await prisma.pipelineNode.findMany({
      where: {
        stackId,
        integrationId: { not: null },
      },
      select: {
        integrationId: true,
        integration: {
          select: {
            id: true,
            sourceContract: { select: { id: true } },
          },
        },
      },
    });

    const toCreate = nodesWithIntegrations
      .filter(n => n.integration && !n.integration.sourceContract)
      .map(n => n.integration!.id);

    if (toCreate.length === 0) {
      return NextResponse.json({
        message: 'All integrations already have contracts.',
        created: 0,
      });
    }

    // Create source contracts with inheritance enabled
    const created = await prisma.$transaction(
      toCreate.map(integrationId =>
        prisma.sourceContract.create({
          data: {
            integrationId,
            pipelineStackId: stackId,
            inheritFromPipeline: true,
          },
        })
      )
    );

    return NextResponse.json({
      message: `Applied pipeline defaults to ${created.length} integration(s).`,
      created: created.length,
    });
  } catch (error) {
    console.error('Error applying pipeline defaults:', error);
    return NextResponse.json({ error: 'Failed to apply defaults' }, { status: 500 });
  }
}
