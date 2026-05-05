import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { PIPELINE_TYPE_TO_FAMILY, TOOL_TYPE_BY_INTEGRATION_TYPE } from '@/lib/monitors/families';
import { aggregate } from './aggregate';

// Each pipeline-tool family can host one of several concrete tools (e.g. orchestration → airflow OR dagster).
// When a monitor lacks an Integration link, we look up the stack's configured PipelineNode for that family
// so pipelineTools count reflects actual tools (Airflow) rather than generic families ("Orchestration").
const FAMILY_TOOL_PREFERENCE: Record<string, string[]> = {
  ingestion: ['fivetran', 'airbyte'],
  orchestration: ['airflow', 'dagster'],
  transform: ['dbt_cloud', 'dbt_core'],
  bi: ['looker', 'tableau', 'power_bi', 'metabase'],
  infra: ['linux_server'],
};

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) return NextResponse.json({ error: 'No organization' }, { status: 400 });

  const stackId = new URL(request.url).searchParams.get('stackId');
  if (!stackId) return NextResponse.json({ error: 'stackId required' }, { status: 400 });

  // Stack-scoped pipeline nodes (configured tools) for family fallback resolution.
  const stack = await prisma.pipelineStack.findFirst({
    where: { id: stackId, organizationId },
    include: {
      nodes: { select: { toolType: true } },
    },
  });
  const stackToolTypes = new Set((stack?.nodes ?? []).map((n) => (n.toolType || '').toLowerCase()));

  // Build a per-family default: pick the first configured tool from the preference list.
  const familyDefault: Record<string, string> = {};
  for (const [family, prefs] of Object.entries(FAMILY_TOOL_PREFERENCE)) {
    const hit = prefs.find((t) => stackToolTypes.has(t));
    if (hit) familyDefault[family] = hit;
  }

  const monitors = await prisma.monitor.findMany({
    where: { organizationId, pipelineStackId: stackId, enabled: true },
    select: {
      monitorType: true,
      targetFqn: true,
      lastStatus: true,
      lastRunAt: true,
      integration: { select: { type: true } },
    },
  });

  const enriched = monitors.map((m) => {
    const integrationKey = m.integration?.type
      ? TOOL_TYPE_BY_INTEGRATION_TYPE[m.integration.type] || m.integration.type.toLowerCase()
      : null;
    if (integrationKey) {
      return { monitorType: m.monitorType, targetFqn: m.targetFqn, lastStatus: m.lastStatus, lastRunAt: m.lastRunAt, toolType: integrationKey };
    }
    const family = PIPELINE_TYPE_TO_FAMILY[(m.monitorType || '').toUpperCase()];
    const resolved = (family && familyDefault[family]) || family || null;
    return { monitorType: m.monitorType, targetFqn: m.targetFqn, lastStatus: m.lastStatus, lastRunAt: m.lastRunAt, toolType: resolved };
  });

  return NextResponse.json(aggregate(enriched));
}
