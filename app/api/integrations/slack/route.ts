import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// POST /api/integrations/slack - Save Slack webhook URL
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
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

    const { webhookUrl, channel, alertOnCritical, alertOnHigh, alertOnScanComplete } = await request.json();

    if (!webhookUrl) {
      return NextResponse.json({ error: 'Webhook URL required' }, { status: 400 });
    }

    // Validate webhook URL format
    if (!webhookUrl.startsWith('https://hooks.slack.com/')) {
      return NextResponse.json({ error: 'Invalid Slack webhook URL' }, { status: 400 });
    }

    // Find existing Slack integration
    const existingIntegration = await prisma.integration.findFirst({
      where: {
        organizationId: user.organizationId,
        type: 'SLACK',
      },
    });

    const credentialsData = JSON.stringify({
      webhookUrl,
      channel,
      alertOnCritical: alertOnCritical ?? true,
      alertOnHigh: alertOnHigh ?? true,
      alertOnScanComplete: alertOnScanComplete ?? false,
    });

    let integration;
    if (existingIntegration) {
      integration = await prisma.integration.update({
        where: { id: existingIntegration.id },
        data: {
          credentials: credentialsData,
          status: 'ACTIVE',
        },
      });
    } else {
      integration = await prisma.integration.create({
        data: {
          name: channel || 'Slack Alerts',
          type: 'SLACK',
          status: 'ACTIVE',
          organizationId: user.organizationId,
          credentials: credentialsData,
        },
      });
    }

    // Test the webhook
    try {
      await sendSlackMessage(webhookUrl, {
        text: '✅ Pallisade connected successfully!',
        blocks: [
          {
            type: 'section',
            text: {
              type: 'mrkdwn',
              text: '*✅ Pallisade Connected*\nYou will now receive data reliability alerts in this channel.',
            },
          },
        ],
      });
    } catch (e) {
      // Don't fail if test message fails
      console.error('Failed to send test message:', e);
    }

    return NextResponse.json({ 
      success: true, 
      integration: { id: integration.id, name: integration.name },
    });
  } catch (error: any) {
    console.error('Slack integration error:', error);
    return NextResponse.json({ error: error.message || 'Failed to save Slack integration' }, { status: 500 });
  }
}

// GET /api/integrations/slack - Get Slack integration status
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
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

    if (!integration) {
      return NextResponse.json({ connected: false });
    }

    const config = typeof integration.credentials === 'string' 
      ? JSON.parse(integration.credentials) 
      : (integration.credentials as Record<string, any>) || {};

    return NextResponse.json({
      connected: integration.status === 'ACTIVE',
      channel: config.channel,
      alertOnCritical: config.alertOnCritical ?? true,
      alertOnHigh: config.alertOnHigh ?? true,
      alertOnScanComplete: config.alertOnScanComplete ?? false,
    });
  } catch (error: any) {
    console.error('Slack GET error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// Helper function to send Slack messages (private to this route)
async function sendSlackMessage(webhookUrl: string, payload: any) {
  const response = await fetch(webhookUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Slack API error: ${response.status}`);
  }
}

