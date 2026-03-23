import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { generateToken } from '@/lib/crypto';

// GET /api/integrations/oauth/github - Start GitHub OAuth flow
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.redirect(new URL('/login', request.url));
    }

    const clientId = process.env.GITHUB_INTEGRATION_CLIENT_ID;
    if (!clientId) {
      return NextResponse.json({ 
        error: 'GitHub OAuth not configured. Use Personal Access Token instead.' 
      }, { status: 400 });
    }

    // Generate state token for CSRF protection
    const state = generateToken(16);
    
    // Store state in cookie for verification
    const response = NextResponse.redirect(
      `https://github.com/login/oauth/authorize?` + 
      new URLSearchParams({
        client_id: clientId,
        redirect_uri: `${process.env.NEXTAUTH_URL}/api/integrations/oauth/github/callback`,
        scope: 'repo read:user user:email',
        state,
      }).toString()
    );

    // Set state cookie (httpOnly, secure in production)
    response.cookies.set('github_oauth_state', state, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 10, // 10 minutes
    });

    return response;
  } catch (error) {
    console.error('GitHub OAuth error:', error);
    return NextResponse.json({ error: 'OAuth initialization failed' }, { status: 500 });
  }
}

