import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { SlackClient } from '@/lib/integrations/slack';

// GET /api/integrations/slack/channels - List Slack channels
export async function GET(request: NextRequest) {
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
        status: 'ACTIVE',
      },
      select: { accessToken: true },
    });

    if (!integration?.accessToken) {
      return NextResponse.json({ error: 'Slack not connected' }, { status: 400 });
    }

    const botToken = decrypt(integration.accessToken);
    const client = new SlackClient({ bot_token: botToken });
    const channels = await client.listChannels();

    return NextResponse.json({ channels });
  } catch (error: any) {
    console.error('Slack channels error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
