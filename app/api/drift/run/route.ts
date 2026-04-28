import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { scannerClient } from '@/lib/scanner-client';

export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const body = await request.json().catch(() => ({}));
    const stackId = body.stackId || new URL(request.url).searchParams.get('stackId');
    if (!stackId) {
      return NextResponse.json(
        { error: 'stackId is required (in body or query)' },
        { status: 400 }
      );
    }

    // Fetch all monitors + runs for this org
    const monitors = await prisma.monitor.findMany({
      where: { organizationId, pipelineStackId: stackId, enabled: true },
    });

    const monitorIds = monitors.map(m => m.id);
    const runs = await prisma.monitorRun.findMany({
      where: { monitorId: { in: monitorIds } },
      orderBy: { completedAt: 'asc' },
    });

    const runsByMonitor: Record<string, any[]> = {};
    for (const run of runs) {
      if (!runsByMonitor[run.monitorId]) runsByMonitor[run.monitorId] = [];
      runsByMonitor[run.monitorId].push(run);
    }

    // Resolve policies
    const fqns = [...new Set(monitors.map(m => m.targetFqn).filter(Boolean))] as string[];
    let policies: Record<string, any> = {};
    try {
      const nodes = fqns.map(fqn => ({ fqn, domain: 'warehouse', criticality: 'medium' }));
      const assignments = await prisma.policyAssignment.findMany({
        where: { organizationId },
        include: { profile: true },
      });
      const profiles = await prisma.policyProfile.findMany({ where: { organizationId } });
      const profileMap: Record<string, any> = {};
      for (const p of profiles) profileMap[p.id] = p;

      const res = await scannerClient.fetch(session, '/api/v1/policies/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nodes,
          _assignments: assignments.map(a => ({
            id: a.id, profileId: a.profileId, assignmentType: a.assignmentType,
            nodeFqn: a.nodeFqn, nodeDomain: a.nodeDomain, nodeCriticality: a.nodeCriticality,
            branchRootFqn: a.branchRootFqn, overrides: a.overrides,
          })),
          _profiles: profileMap,
        }),
        signal: AbortSignal.timeout(10000),
      });
      if (res.ok) {
        const data = await res.json();
        policies = data.policies || {};
      }
    } catch {
      // Proceed without policies
    }

    // Call FastAPI drift analyzer
    const analyzeRes = await scannerClient.fetch(session, '/api/v1/drift/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        org_id: organizationId,
        monitors: monitors.map(m => ({ ...m, config: m.config || {} })),
        runs_by_monitor: runsByMonitor,
        policies,
      }),
      signal: AbortSignal.timeout(120000),
    });

    if (!analyzeRes.ok) {
      const err = await analyzeRes.json().catch(() => ({}));
      throw new Error(err.detail || 'Drift analysis failed');
    }

    const result = await analyzeRes.json();

    // Auto-dismiss old pending recs for same monitor+field
    if (result.recommendations?.length > 0) {
      const supersedePairs = result.recommendations.map((r: any) => ({
        monitorId: r.monitorId,
        currentField: r.currentField,
      }));
      for (const pair of supersedePairs) {
        await prisma.driftRecommendation.updateMany({
          where: {
            organizationId,
            pipelineStackId: stackId,
            monitorId: pair.monitorId,
            currentField: pair.currentField,
            status: 'pending',
          },
          data: { status: 'dismissed', reviewedAt: new Date() },
        });
      }

      await prisma.driftRecommendation.createMany({
        data: result.recommendations.map((r: any) => ({
          ...r,
          pipelineStackId: stackId,
        })),
      });
    }

    return NextResponse.json({
      runId: result.runId,
      recommendationCount: result.recommendationCount,
    });
  } catch (error: any) {
    console.error('[Drift] Run error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
