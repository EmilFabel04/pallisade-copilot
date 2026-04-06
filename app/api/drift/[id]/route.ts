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
