import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { encrypt } from '@/lib/crypto';

// GET /api/integrations/oauth/github/callback - Handle GitHub OAuth callback
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

    // Check for OAuth errors
    if (error) {
      console.error('GitHub OAuth error:', error);
      return NextResponse.redirect(
        new URL(`/dashboard/pipeline?error=${encodeURIComponent(error)}`, request.url)
      );
    }

    // Verify state token
    const storedState = request.cookies.get('github_oauth_state')?.value;
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

    // Exchange code for access token
    const tokenResponse = await fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        client_id: process.env.GITHUB_INTEGRATION_CLIENT_ID,
        client_secret: process.env.GITHUB_INTEGRATION_CLIENT_SECRET,
        code,
      }),
    });

    const tokenData = await tokenResponse.json();

    if (tokenData.error) {
      console.error('GitHub token error:', tokenData);
      return NextResponse.redirect(
        new URL(`/dashboard/pipeline?error=${encodeURIComponent(tokenData.error)}`, request.url)
      );
    }

    const accessToken = tokenData.access_token;

    // Fetch user info
    const userResponse = await fetch('https://api.github.com/user', {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Pallisade',
      },
    });

    const githubUser = await userResponse.json();

    // Fetch repos
    const reposResponse = await fetch('https://api.github.com/user/repos?per_page=100&sort=updated', {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Pallisade',
      },
    });

    const repos = await reposResponse.json();

    // Get or create organization for user
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

    // Create or update integration
    const existingIntegration = await prisma.integration.findFirst({
      where: {
        organizationId,
        type: 'GITHUB',
        name: 'GitHub',
      },
    });

    const integrationData = {
      name: 'GitHub',
      type: 'GITHUB' as const,
      status: 'ACTIVE' as const,
      accessToken: encrypt(accessToken),
      connectionInfo: `@${githubUser.login} • ${repos.length} repositories`,
      metadata: {
        username: githubUser.login,
        name: githubUser.name,
        avatar: githubUser.avatar_url,
        repos: repos.map((r: any) => ({
          name: r.full_name,
          private: r.private,
          url: r.html_url,
        })),
        repoCount: repos.length,
      },
      lastTestAt: new Date(),
      organizationId,
    };

    if (existingIntegration) {
      await prisma.integration.update({
        where: { id: existingIntegration.id },
        data: integrationData,
      });
    } else {
      await prisma.integration.create({
        data: integrationData,
      });
    }

    // Clear state cookie and redirect
    const response = NextResponse.redirect(
      new URL('/dashboard/pipeline?success=github', request.url)
    );
    response.cookies.delete('github_oauth_state');

    return response;
  } catch (error) {
    console.error('GitHub OAuth callback error:', error);
    return NextResponse.redirect(
      new URL('/dashboard/pipeline?error=callback_failed', request.url)
    );
  }
}

