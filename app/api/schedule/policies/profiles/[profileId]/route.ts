import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

// PATCH /api/schedule/policies/profiles/[profileId] — Update a profile
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ profileId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { profileId } = await params;
    const body = await request.json();

    // Check the profile exists and belongs to this org
    const existing = await prisma.policyProfile.findFirst({
      where: { id: profileId, organizationId },
    });
    if (!existing) {
      return NextResponse.json({ error: 'Profile not found' }, { status: 404 });
    }
    if (existing.isBuiltIn) {
      return NextResponse.json({ error: 'Cannot modify built-in profiles' }, { status: 403 });
    }

    const profile = await prisma.policyProfile.update({
      where: { id: profileId },
      data: {
        ...(body.name !== undefined && { name: body.name }),
        ...(body.description !== undefined && { description: body.description }),
        ...(body.targetDomain !== undefined && { targetDomain: body.targetDomain }),
        ...(body.criticality !== undefined && { criticality: body.criticality }),
        ...(body.freshnessConfig !== undefined && { freshnessConfig: body.freshnessConfig }),
        ...(body.schemaConfig !== undefined && { schemaConfig: body.schemaConfig }),
        ...(body.volumeConfig !== undefined && { volumeConfig: body.volumeConfig }),
        ...(body.anomalyConfig !== undefined && { anomalyConfig: body.anomalyConfig }),
        ...(body.qualityConfig !== undefined && { qualityConfig: body.qualityConfig }),
        ...(body.ingestionConfig !== undefined && { ingestionConfig: body.ingestionConfig }),
        ...(body.biConfig !== undefined && { biConfig: body.biConfig }),
        ...(body.orchestrationConfig !== undefined && { orchestrationConfig: body.orchestrationConfig }),
        ...(body.transformConfig !== undefined && { transformConfig: body.transformConfig }),
      },
    });

    return NextResponse.json({ profile });
  } catch (error: any) {
    console.error('[Policies] Error updating profile:', error);
    return NextResponse.json({ error: error.message || 'Failed to update profile' }, { status: 500 });
  }
}

// DELETE /api/schedule/policies/profiles/[profileId] — Delete a profile
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ profileId: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { profileId } = await params;

    const existing = await prisma.policyProfile.findFirst({
      where: { id: profileId, organizationId },
    });
    if (!existing) {
      return NextResponse.json({ error: 'Profile not found' }, { status: 404 });
    }
    if (existing.isBuiltIn) {
      return NextResponse.json({ error: 'Cannot delete built-in profiles' }, { status: 403 });
    }

    await prisma.policyProfile.delete({ where: { id: profileId } });

    return NextResponse.json({ deleted: profileId });
  } catch (error: any) {
    console.error('[Policies] Error deleting profile:', error);
    return NextResponse.json({ error: error.message || 'Failed to delete profile' }, { status: 500 });
  }
}
