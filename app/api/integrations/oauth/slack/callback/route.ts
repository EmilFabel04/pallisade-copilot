import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { encrypt } from '@/lib/crypto';

// GET /api/integrations/oauth/slack/callback - Handle Slack OAuth callback
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.redirect(new URL('/login', request.url));
    }

    const searchParams = request.nextUrl.searchParams;
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    const error = searchParams.get('error');

    if (error) {
      console.error('Slack OAuth error:', error);
      return NextResponse.redirect(
        new URL(`/dashboard/pipeline?error=${encodeURIComponent(error)}`, request.url)
      );
    }

    // Verify state token
    const storedState = request.cookies.get('slack_oauth_state')?.value;
    if (!state || state !== storedState) {
      return NextResponse.redirect(
        new URL('/dashboard/pipeline?error=invalid_state', request.url)
      );
    }

    if (!code) {
      return NextResponse.redirect(
        new URL('/dashboard/pipeline?error=no_code', request.url)
      );
    }

    // Exchange code for bot token
    const tokenResponse = await fetch('https://slack.com/api/oauth.v2.access', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: process.env.SLACK_CLIENT_ID!,
        client_secret: process.env.SLACK_CLIENT_SECRET!,
        code,
        redirect_uri: `${process.env.NEXTAUTH_URL}/api/integrations/oauth/slack/callback`,
      }),
    });

    const tokenData = await tokenResponse.json();

    if (!tokenData.ok) {
      console.error('Slack token error:', tokenData);
      return NextResponse.redirect(
        new URL(`/dashboard/pipeline?error=${encodeURIComponent(tokenData.error || 'token_exchange_failed')}`, request.url)
      );
    }

    const botToken = tokenData.access_token;
    const teamName = tokenData.team?.name || '';
    const teamId = tokenData.team?.id || '';

    // Test the token
    const authTestRes = await fetch('https://slack.com/api/auth.test', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${botToken}` },
    });
    const authTest = await authTestRes.json();

    // Get user's organization
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      include: { organization: true },
    });

    let organizationId = user?.organizationId;
    if (!organizationId) {
      const org = await prisma.organization.create({
        data: {
          name: `${user?.name || session.user.email}'s Organization`,
          users: { connect: { id: user?.id } },
        },
      });
      organizationId = org.id;
    }

    // Upsert integration — preserve existing preferences
    const existing = await prisma.integration.findFirst({
      where: { organizationId, type: 'SLACK' },
    });

    const existingCreds = existing?.credentials
      ? (typeof existing.credentials === 'string' ? JSON.parse(existing.credentials) : existing.credentials)
      : {};

    const integrationData = {
      name: 'Slack',
      type: 'SLACK' as const,
      status: 'ACTIVE' as const,
      accessToken: encrypt(botToken),
      connectionInfo: `Workspace: ${teamName || authTest.team || 'Unknown'}`,
      metadata: {
        teamName: teamName || authTest.team,
        teamId: teamId || authTest.team_id,
        botUserId: authTest.user_id,
        installedAt: new Date().toISOString(),
      },
      credentials: JSON.stringify({
        ...existingCreds,
        alertOnCritical: existingCreds.alertOnCritical ?? true,
        alertOnHigh: existingCreds.alertOnHigh ?? true,
        alertOnScanComplete: existingCreds.alertOnScanComplete ?? false,
        alertOnPrCreated: existingCreds.alertOnPrCreated ?? true,
        alertOnTeamInvite: existingCreds.alertOnTeamInvite ?? true,
      }),
      lastTestAt: new Date(),
      organizationId,
    };

    if (existing) {
      await prisma.integration.update({
        where: { id: existing.id },
        data: integrationData,
      });
    } else {
      await prisma.integration.create({ data: integrationData });
    }

    // Clear state cookie and redirect
    const response = NextResponse.redirect(
      new URL('/dashboard/pipeline?success=slack', request.url)
    );
    response.cookies.delete('slack_oauth_state');

    return response;
  } catch (error) {
    console.error('Slack OAuth callback error:', error);
    return NextResponse.redirect(
      new URL('/dashboard/pipeline?error=callback_failed', request.url)
    );
  }
}
