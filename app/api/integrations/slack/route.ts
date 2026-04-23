import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { encrypt } from '@/lib/crypto';
import { SlackClient } from '@/lib/integrations/slack';

// POST /api/integrations/slack - Save Slack bot token (manual mode)
export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const { botToken, channel, alertOnCritical, alertOnHigh, alertOnScanComplete, alertOnPrCreated, alertOnTeamInvite } = await request.json();

    if (!botToken) {
      return NextResponse.json({ error: 'Bot token is required' }, { status: 400 });
    }

    if (!botToken.startsWith('xoxb-')) {
      return NextResponse.json({ error: 'Invalid bot token format. Must start with xoxb-' }, { status: 400 });
    }

    // Verify the token via auth.test
    const client = new SlackClient({ bot_token: botToken });
    let authInfo;
    try {
      authInfo = await client.testAuth();
    } catch (e: any) {
      return NextResponse.json({ error: `Invalid token: ${e.message}` }, { status: 400 });
    }

    // Find existing Slack integration
    const existingIntegration = await prisma.integration.findFirst({
      where: {
        organizationId: user.organizationId,
        type: 'SLACK',
      },
    });

    const existingCreds = existingIntegration?.credentials
      ? (typeof existingIntegration.credentials === 'string' ? JSON.parse(existingIntegration.credentials) : existingIntegration.credentials)
      : {};

    const credentialsData = JSON.stringify({
      ...existingCreds,
      channel: channel || existingCreds.channel,
      alertOnCritical: alertOnCritical ?? existingCreds.alertOnCritical ?? true,
      alertOnHigh: alertOnHigh ?? existingCreds.alertOnHigh ?? true,
      alertOnScanComplete: alertOnScanComplete ?? existingCreds.alertOnScanComplete ?? false,
      alertOnPrCreated: alertOnPrCreated ?? existingCreds.alertOnPrCreated ?? true,
      alertOnTeamInvite: alertOnTeamInvite ?? existingCreds.alertOnTeamInvite ?? true,
    });

    const integrationData = {
      name: 'Slack',
      type: 'SLACK' as const,
      status: 'ACTIVE' as const,
      accessToken: encrypt(botToken),
      connectionInfo: `Workspace: ${authInfo.team}`,
      metadata: {
        teamName: authInfo.team,
        teamId: authInfo.teamId,
        botUserId: authInfo.user,
        installedAt: new Date().toISOString(),
      },
      credentials: credentialsData,
      lastTestAt: new Date(),
      organizationId: user.organizationId,
    };

    let integration;
    if (existingIntegration) {
      integration = await prisma.integration.update({
        where: { id: existingIntegration.id },
        data: integrationData,
      });
    } else {
      integration = await prisma.integration.create({
        data: integrationData,
      });
    }

    return NextResponse.json({
      success: true,
      integration: { id: integration.id, name: integration.name },
      workspace: authInfo.team,
    });
  } catch (error: any) {
    console.error('Slack integration error:', error);
    return NextResponse.json({ error: error.message || 'Failed to save Slack integration' }, { status: 500 });
  }
}

// GET /api/integrations/slack - Get Slack integration status
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const integration = await prisma.integration.findFirst({
      where: {
        organizationId: user.organizationId,
        type: 'SLACK',
      },
    });

    if (!integration || !integration.accessToken) {
      return NextResponse.json({
        connected: false,
        hasOAuth: !!process.env.SLACK_CLIENT_ID,
      });
    }

    const config = typeof integration.credentials === 'string'
      ? JSON.parse(integration.credentials)
      : (integration.credentials as Record<string, any>) || {};

    const metadata = (integration.metadata as Record<string, any>) || {};

    return NextResponse.json({
      connected: integration.status === 'ACTIVE',
      channel: config.channel,
      teamName: metadata.teamName || metadata.team,
      hasOAuth: !!process.env.SLACK_CLIENT_ID,
      alertOnCritical: config.alertOnCritical ?? true,
      alertOnHigh: config.alertOnHigh ?? true,
      alertOnScanComplete: config.alertOnScanComplete ?? false,
      alertOnPrCreated: config.alertOnPrCreated ?? true,
      alertOnTeamInvite: config.alertOnTeamInvite ?? true,
    });
  } catch (error: any) {
    console.error('Slack GET error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// PATCH /api/integrations/slack - Update preferences (partial)
export async function PATCH(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const integration = await prisma.integration.findFirst({
      where: {
        organizationId: user.organizationId,
        type: 'SLACK',
      },
    });

    if (!integration) {
      return NextResponse.json({ error: 'Slack not connected' }, { status: 400 });
    }

    const body = await request.json();
    const allowedKeys = ['alertOnCritical', 'alertOnHigh', 'alertOnScanComplete', 'alertOnPrCreated', 'alertOnTeamInvite', 'channel'];

    const existing = typeof integration.credentials === 'string'
      ? JSON.parse(integration.credentials)
      : (integration.credentials as Record<string, any>) || {};

    const updated = { ...existing };
    for (const key of allowedKeys) {
      if (key in body) {
        updated[key] = body[key];
      }
    }

    await prisma.integration.update({
      where: { id: integration.id },
      data: { credentials: JSON.stringify(updated) },
    });

    return NextResponse.json({ success: true });
  } catch (error: any) {
    console.error('Slack PATCH error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
