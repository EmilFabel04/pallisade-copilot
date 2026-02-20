import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// POST /api/schedule/discover-logs - Discover log files on a connected server
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const body = await request.json();
    const { integrationId } = body;

    // Find the server pipeline node — try with specific ID first, then any linux_server
    const pipelineStack = await prisma.pipelineStack.findFirst({
      where: { organizationId },
      include: {
        nodes: {
          where: {
            toolType: 'linux_server',
            ...(integrationId ? { id: integrationId } : {}),
          },
          select: { id: true, name: true, toolType: true, config: true, status: true },
          take: 1,
        },
      },
    });

    const serverNode = pipelineStack?.nodes[0];
    if (!serverNode) {
      return NextResponse.json({
        success: false,
        message: 'No Linux server integration found. Connect a server on the Pipeline page first.',
        log_files: [],
      });
    }

    // Decrypt server credentials
    let credentials: Record<string, any> = {};
    try {
      const configJson = serverNode.config as { encrypted?: string; [key: string]: any };
      if (configJson.encrypted) {
        const decrypted = decrypt(configJson.encrypted);
        credentials = JSON.parse(decrypted);
      } else {
        credentials = { ...configJson };
      }
    } catch {
      return NextResponse.json({
        success: false,
        message: 'Failed to decrypt server credentials',
        log_files: [],
      });
    }

    // Call FastAPI to discover logs via SSH
    const response = await fetch(`${SCANNER_API_URL}/api/v1/server/discover-logs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host: credentials.host,
        port: parseInt(credentials.port) || 22,
        username: credentials.username,
        auth_method: credentials.auth_method || 'key',
        private_key: credentials.private_key,
        passphrase: credentials.passphrase,
        password: credentials.password,
      }),
      signal: AbortSignal.timeout(30000),
    });

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error: any) {
    console.error('[Schedule] Discover logs error:', error);
    return NextResponse.json(
      { success: false, message: 'Failed to discover log files', log_files: [] },
      { status: 500 }
    );
  }
}
