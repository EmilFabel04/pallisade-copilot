import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { id } = await params;
    const body = await request.json();
    const { action, value } = body as { action: string; value?: string };

    const rec = await prisma.driftRecommendation.findFirst({
      where: { id, organizationId },
      include: { monitor: true },
    });

    if (!rec) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }

    if (action === 'dismiss') {
      await prisma.driftRecommendation.update({
        where: { id },
        data: { status: 'dismissed', reviewedAt: new Date() },
      });
      return NextResponse.json({ ok: true });
    }

    if (action === 'accept' || action === 'accept_with_value') {
      const applyValue = action === 'accept_with_value' && value ? value : rec.recommendedValue;

      const [section, field] = rec.currentField.split('.');
      if (section && field && rec.monitor) {
        const config = (rec.monitor.config as Record<string, any>) || {};
        config[rec.currentField.replace('.', '_')] = isNaN(Number(applyValue))
          ? applyValue
          : Number(applyValue);

        await prisma.monitor.update({
          where: { id: rec.monitorId },
          data: { config },
        });

        // Write to SLA PolicyAssignment overrides
        try {
          const targetFqn = rec.targetFqn;
          if (targetFqn && section) {
            const parsedValue = isNaN(Number(applyValue)) ? applyValue : Number(applyValue);

            const existingAssignment = await prisma.policyAssignment.findFirst({
              where: {
                nodeFqn: targetFqn,
                assignmentType: 'direct',
                status: 'active',
                organizationId,
              },
            });

            if (existingAssignment) {
              const overrides = (existingAssignment.overrides as Record<string, any>) || {};
              if (!overrides[section]) overrides[section] = {};
              overrides[section][field] = parsedValue;
              await prisma.policyAssignment.update({
                where: { id: existingAssignment.id },
                data: { overrides },
              });
            } else {
              const defaultProfile = await prisma.policyProfile.findFirst({
                where: { organizationId, isBuiltIn: true },
              }) || await prisma.policyProfile.findFirst({
                where: { organizationId },
                orderBy: { createdAt: 'asc' },
              });

              if (defaultProfile) {
                await prisma.policyAssignment.create({
                  data: {
                    profileId: defaultProfile.id,
                    nodeFqn: targetFqn,
                    assignmentType: 'direct',
                    organizationId,
                    overrides: { [section]: { [field]: parsedValue } },
                  },
                });
              }
            }
          }
        } catch (slaErr) {
          console.warn('[Drift] SLA writeback failed (non-fatal):', slaErr);
        }
      }

      await prisma.driftRecommendation.update({
        where: { id },
        data: { status: 'accepted', reviewedAt: new Date() },
      });

      return NextResponse.json({ ok: true, applied: applyValue });
    }

    return NextResponse.json({ error: 'Invalid action' }, { status: 400 });
  } catch (error: any) {
    console.error('[Drift] Action error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
