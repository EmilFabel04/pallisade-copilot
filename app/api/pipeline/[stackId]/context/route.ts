/**
 * Pipeline Context API
 *
 * Manages onboarding state and learned context for pipelines.
 *
 * GET - Get current pipeline context (onboarding status, learned context)
 * PATCH - Update pipeline context (save onboarding answers)
 * POST - Start or complete onboarding
 */

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { OnboardingStatus } from '@prisma/client';

// GET - Get pipeline context
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await auth();
    const _userId = (session?.user as any)?.id;
    const organizationId = (session?.user as any)?.organizationId;

    if (!_userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId } = await params;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Verify pipeline belongs to user's organization
    const pipeline = await prisma.pipelineStack.findFirst({
      where: {
        id: stackId,
        organizationId,
      },
      include: {
        context: true,
        nodes: {
          select: {
            toolType: true,
          },
        },
      },
    });

    if (!pipeline) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    // Get OAuth integrations (GitHub, Slack, Jira) - stored separately from pipeline nodes
    const oauthIntegrations = await prisma.integration.findMany({
      where: {
        organizationId,
        type: { in: ['GITHUB', 'SLACK', 'JIRA'] },
      },
      select: { type: true },
    });

    // Get integration types - merge pipeline nodes with OAuth integrations
    const integrationTypes = [...new Set([
      ...pipeline.nodes.map(n => n.toolType?.toUpperCase()).filter(Boolean),
      ...oauthIntegrations.map(o => o.type.toUpperCase()),
    ] as string[])];

    // If no context exists, return default state
    if (!pipeline.context) {
      return NextResponse.json({
        context: {
          onboardingStatus: 'NOT_STARTED',
          environmentContext: null,
          integrationContexts: null,
          conventionsContext: null,
        },
        integrationTypes,
        needsOnboarding: true,
      });
    }

    return NextResponse.json({
      context: {
        id: pipeline.context.id,
        onboardingStatus: pipeline.context.onboardingStatus,
        onboardingCompletedAt: pipeline.context.onboardingCompletedAt,
        environmentContext: pipeline.context.environmentContext,
        integrationContexts: pipeline.context.integrationContexts,
        conventionsContext: pipeline.context.conventionsContext,
        updatedAt: pipeline.context.updatedAt,
      },
      integrationTypes,
      needsOnboarding: pipeline.context.onboardingStatus !== 'COMPLETED',
    });

  } catch (error) {
    console.error('Failed to fetch pipeline context:', error);
    return NextResponse.json(
      { error: 'Failed to fetch pipeline context' },
      { status: 500 }
    );
  }
}

// PATCH - Update pipeline context (save onboarding answers)
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await auth();
    const _userId = (session?.user as any)?.id;
    const organizationId = (session?.user as any)?.organizationId;

    if (!_userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId } = await params;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Verify pipeline belongs to user's organization
    const pipeline = await prisma.pipelineStack.findFirst({
      where: {
        id: stackId,
        organizationId,
      },
      include: {
        context: true,
      },
    });

    if (!pipeline) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    const body = await request.json();
    const {
      questionKey,
      answer,
      contextField,
      integrationTтype,
    } = body;

    if (!questionKey || !answer || !contextField) {
      return NextResponse.json(
        { error: 'questionKey, answer, and contextField are required' },
        { status: 400 }
      );
    }

    // Build update data
    const existingContext = pipeline.context;
    const updateData: any = {
      onboardingStatus: 'IN_PROGRESS' as OnboardingStatus,
    };

    if (contextField === 'environmentContext') {
      const current = (existingContext?.environmentContext as Record<string, any>) || {};
      updateData.environmentContext = { ...current, [questionKey]: answer };
    } else if (contextField === 'conventionsContext') {
      const current = (existingContext?.conventionsContext as Record<string, any>) || {};
      updateData.conventionsContext = { ...current, [questionKey]: answer };
    } else if (contextField === 'integrationContexts') {
      const current = (existingContext?.integrationContexts as Record<string, any>) || {};
      const intType = integrationTтype || 'GENERAL';
      const intCurrent = current[intType] || {};
      updateData.integrationContexts = {
        ...current,
        [intType]: { ...intCurrent, [questionKey]: answer },
      };
    }

    // Upsert context
    const context = await prisma.pipelineContext.upsert({
      where: { pipelineStackId: stackId },
      create: {
        pipelineStackId: stackId,
        ...updateData,
      },
      update: updateData,
    });

    return NextResponse.json({
      context: {
        id: context.id,
        onboardingStatus: context.onboardingStatus,
        environmentContext: context.environmentContext,
        integrationContexts: context.integrationContexts,
        conventionsContext: context.conventionsContext,
      },
      saved: true,
      questionKey,
    });

  } catch (error) {
    console.error('Failed to update pipeline context:', error);
    return NextResponse.json(
      { error: 'Failed to update pipeline context' },
      { status: 500 }
    );
  }
}

// POST - Start or complete onboarding
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ stackId: string }> }
) {
  try {
    const session = await auth();
    const _userId = (session?.user as any)?.id;
    const organizationId = (session?.user as any)?.organizationId;

    if (!_userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { stackId } = await params;

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Verify pipeline belongs to user's organization
    const pipeline = await prisma.pipelineStack.findFirst({
      where: {
        id: stackId,
        organizationId,
      },
    });

    if (!pipeline) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    const body = await request.json();
    const { action } = body;

    if (action === 'start') {
      // Start onboarding
      const context = await prisma.pipelineContext.upsert({
        where: { pipelineStackId: stackId },
        create: {
          pipelineStackId: stackId,
          onboardingStatus: 'IN_PROGRESS',
        },
        update: {
          onboardingStatus: 'IN_PROGRESS',
        },
      });

      return NextResponse.json({
        context: {
          id: context.id,
          onboardingStatus: context.onboardingStatus,
        },
        message: 'Onboarding started',
      });

    } else if (action === 'complete') {
      // Complete onboarding
      const context = await prisma.pipelineContext.upsert({
        where: { pipelineStackId: stackId },
        create: {
          pipelineStackId: stackId,
          onboardingStatus: 'COMPLETED',
          onboardingCompletedAt: new Date(),
        },
        update: {
          onboardingStatus: 'COMPLETED',
          onboardingCompletedAt: new Date(),
        },
      });

      return NextResponse.json({
        context: {
          id: context.id,
          onboardingStatus: context.onboardingStatus,
          onboardingCompletedAt: context.onboardingCompletedAt,
        },
        message: 'Onboarding completed',
      });

    } else if (action === 'needs_update') {
      // Mark that onboarding needs update (e.g., new integration added)
      const context = await prisma.pipelineContext.upsert({
        where: { pipelineStackId: stackId },
        create: {
          pipelineStackId: stackId,
          onboardingStatus: 'NEEDS_UPDATE',
        },
        update: {
          onboardingStatus: 'NEEDS_UPDATE',
        },
      });

      return NextResponse.json({
        context: {
          id: context.id,
          onboardingStatus: context.onboardingStatus,
        },
        message: 'Onboarding marked as needing update',
      });

    } else {
      return NextResponse.json(
        { error: 'Invalid action. Use: start, complete, or needs_update' },
        { status: 400 }
      );
    }

  } catch (error) {
    console.error('Failed to update onboarding status:', error);
    return NextResponse.json(
      { error: 'Failed to update onboarding status' },
      { status: 500 }
    );
  }
}
