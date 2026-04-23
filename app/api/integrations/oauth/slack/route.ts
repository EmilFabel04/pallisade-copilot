import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { generateToken } from '@/lib/crypto';

// GET /api/integrations/oauth/slack - Start Slack OAuth flow
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.redirect(new URL('/login', request.url));
    }

    const clientId = process.env.SLACK_CLIENT_ID;
    if (!clientId) {
      return NextResponse.json({
        error: 'Slack OAuth not configured. Use a Bot Token instead.',
      }, { status: 400 });
    }

    // Generate state token for CSRF protection
    const state = generateToken(16);

    // Redirect to Slack OAuth authorize
    const response = NextResponse.redirect(
      `https://slack.com/oauth/v2/authorize?` +
      new URLSearchParams({
        client_id: clientId,
        scope: 'chat:write,channels:read,groups:read',
        redirect_uri: `${process.env.NEXTAUTH_URL}/api/integrations/oauth/slack/callback`,
        state,
      }).toString()
    );

    // Set state cookie (httpOnly, secure in production)
    response.cookies.set('slack_oauth_state', state, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 10, // 10 minutes
    });

    return response;
  } catch (error) {
    console.error('Slack OAuth error:', error);
    return NextResponse.json({ error: 'OAuth initialization failed' }, { status: 500 });
  }
}
