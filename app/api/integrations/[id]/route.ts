import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { Prisma } from '@prisma/client';
import { encrypt } from '@/lib/crypto';
import { notifyEvents } from '@/lib/notifications';

// GET /api/integrations/[id] - Get a specific integration
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

    const integration = await prisma.integration.findFirst({
      where: {
        id,
        organizationId: user?.organizationId || '',
      },
      select: {
        id: true,
        name: true,
        type: true,
        status: true,
        connectionInfo: true,
        config: true,
        metadata: true,
        lastSyncAt: true,
        lastTestAt: true,
        lastError: true,
        healthScore: true,
        scanCount: true,
        lastScanAt: true,
        createdAt: true,
        updatedAt: true,
      },
    });

    if (!integration) {
      return NextResponse.json({ error: 'Integration not found' }, { status: 404 });
    }

    return NextResponse.json({ integration });
  } catch (error) {
    console.error('Error fetching integration:', error);
    return NextResponse.json({ error: 'Failed to fetch integration' }, { status: 500 });
  }
}

// PATCH /api/integrations/[id] - Update an integration
export async function PATCH(
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

    // Verify ownership
    const existing = await prisma.integration.findFirst({
      where: {
        id,
        organizationId: user?.organizationId || '',
      },
    });

    if (!existing) {
      return NextResponse.json({ error: 'Integration not found' }, { status: 404 });
    }

    const body = await request.json();
    const { name, credentials, config, status } = body;

    const updateData: any = {};
    if (name) updateData.name = name;
    if (config) updateData.config = config;
    if (status) updateData.status = status;

    // Only update credentials if provided (don't overwrite with empty)
    if (credentials && Object.keys(credentials).length > 0) {
      updateData.credentials = { encrypted: encrypt(JSON.stringify(credentials)) };
    }

    const integration = await prisma.integration.update({
      where: { id },
      data: updateData,
      select: {
        id: true,
        name: true,
        type: true,
        status: true,
        connectionInfo: true,
        config: true,
        updatedAt: true,
      },
    });

    return NextResponse.json({ integration });
  } catch (error) {
    console.error('Error updating integration:', error);
    return NextResponse.json({ error: 'Failed to update integration' }, { status: 500 });
  }
}

// DELETE /api/integrations/[id] - Delete an integration
export async function DELETE(
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

    // Verify ownership
    const existing = await prisma.integration.findFirst({
      where: {
        id,
        organizationId: user?.organizationId || '',
      },
    });

    if (!existing) {
      return NextResponse.json({ error: 'Integration not found' }, { status: 404 });
    }

    // Clear config, integrationId, and reset status on PipelineNodes that reference
    // this integration so they immediately reflect the disconnected state
    await prisma.pipelineNode.updateMany({
      where: { integrationId: id },
      data: {
        integrationId: null,
        config: Prisma.JsonNull,
        status: 'PENDING',
      },
    });

    await prisma.integration.delete({
      where: { id },
    });

    // Fire-and-forget notification
    notifyEvents.integrationDeleted(
      user?.organizationId || '', (session.user as any).id,
      existing.name, id,
    );

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Error deleting integration:', error);
    return NextResponse.json({ error: 'Failed to delete integration' }, { status: 500 });
  }
}

