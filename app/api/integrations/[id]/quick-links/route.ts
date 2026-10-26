import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

/**
 * GET/PUT /api/integrations/[id]/quick-links
 *
 * Manage user-defined quick links for a source (tool URLs for fast navigation).
 * Links are stored in PipelineNode.config.quickLinks or Integration.metadata.quickLinks.
 */

// A type alias (not an interface) so it's assignable to Prisma's JSON input type.
type QuickLink = {
  label: string;
  url: string;
};

// GET — fetch quick links for a source
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });
    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 404 });
    }

    // Try PipelineNode first (source could be a node ID)
    const node = await prisma.pipelineNode.findFirst({
      where: { id, stack: { organizationId: user.organizationId } },
      select: { config: true },
    });
    if (node) {
      const config = (node.config as Record<string, any>) || {};
      return NextResponse.json({ quickLinks: config.quickLinks || [] });
    }

    // Fall back to Integration
    const integration = await prisma.integration.findFirst({
      where: { id, organizationId: user.organizationId },
      select: { metadata: true },
    });
    if (integration) {
      const meta = (integration.metadata as Record<string, any>) || {};
      return NextResponse.json({ quickLinks: meta.quickLinks || [] });
    }

    return NextResponse.json({ error: 'Source not found' }, { status: 404 });
  } catch (error) {
    console.error('Quick links GET error:', error);
    return NextResponse.json({ error: 'Failed to fetch quick links' }, { status: 500 });
  }
}

// PUT — save quick links for a source
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });
    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 404 });
    }

    const body = await request.json();
    const quickLinks: QuickLink[] = (body.quickLinks || []).filter(
      (l: any) => typeof l.label === 'string' && typeof l.url === 'string' && l.label.trim() && l.url.trim()
    ).map((l: any) => ({ label: l.label.trim(), url: l.url.trim() }));

    // Try PipelineNode first
    const node = await prisma.pipelineNode.findFirst({
      where: { id, stack: { organizationId: user.organizationId } },
      select: { id: true, config: true },
    });
    if (node) {
      const config = (node.config as Record<string, any>) || {};
      await prisma.pipelineNode.update({
        where: { id },
        data: { config: { ...config, quickLinks } },
      });
      return NextResponse.json({ quickLinks });
    }

    // Fall back to Integration
    const integration = await prisma.integration.findFirst({
      where: { id, organizationId: user.organizationId },
      select: { id: true, metadata: true },
    });
    if (integration) {
      const meta = (integration.metadata as Record<string, any>) || {};
      await prisma.integration.update({
        where: { id },
        data: { metadata: { ...meta, quickLinks } },
      });
      return NextResponse.json({ quickLinks });
    }

    return NextResponse.json({ error: 'Source not found' }, { status: 404 });
  } catch (error) {
    console.error('Quick links PUT error:', error);
    return NextResponse.json({ error: 'Failed to save quick links' }, { status: 500 });
  }
}
