import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { createWatchInTransaction } from '@/lib/watch-helpers';
import { POLICY_FIELD_MAP, getPolicyValueForField } from '@/lib/policy-utils';

// GET /api/schedule/plans - List all monitoring plans
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const plans = await prisma.monitoringPlan.findMany({
      where: { organizationId },
      orderBy: { createdAt: 'desc' },
      include: {
        monitorGroups: {
          include: {
            monitors: {
              select: {
                id: true,
                name: true,
                monitorType: true,
                targetFqn: true,
                enabled: true,
                lastStatus: true,
                lastRunAt: true,
                schedule: true,
                config: true,
              },
            },
          },
        },
      },
    });

    const summaries = plans.map((plan) => {
      const groups = plan.monitorGroups || [];

      // Compute fresh aggregates from child monitors (mirrors detail route)
      let computedTotal = 0;
      let weightedHealth = 0;
      let passCount = 0;
      let warnCount = 0;
      let failCount = 0;
      let errorCount = 0;

      for (const group of groups) {
        const monCount = group.monitors?.length || 0;
        computedTotal += monCount;
        const groupHealth = (group as any).healthScore ?? 100;
        weightedHealth += groupHealth * monCount;

        for (const m of group.monitors || []) {
          if (m.lastStatus === 'PASS') passCount++;
          else if (m.lastStatus === 'WARN') warnCount++;
          else if (m.lastStatus === 'FAIL') failCount++;
          else if (m.lastStatus === 'ERROR') errorCount++;
        }
      }

      const computedHealthScore = computedTotal > 0
        ? Math.round(weightedHealth / computedTotal * 10) / 10
        : null;

      return {
        id: plan.id,
        name: plan.name,
        description: plan.description,
        scopeType: plan.scopeType,
        scopeConfig: plan.scopeConfig,
        anchorFqn: plan.anchorFqn,
        anchorNodeId: plan.anchorNodeId,
        mode: plan.mode,
        families: plan.families,
        totalAssets: plan.totalAssets,
        totalMonitors: computedTotal || plan.totalMonitors,
        coveragePct: plan.coveragePct,
        healthScore: computedHealthScore,
        healthStatus: plan.healthStatus,
        passCount,
        warnCount,
        failCount,
        errorCount,
        lastAggregatedAt: plan.lastAggregatedAt?.toISOString() || null,
        schedule: plan.schedule,
        timezone: plan.timezone,
        enabled: plan.enabled,
        alertChannels: plan.alertChannels,
        alertOnStatus: plan.alertOnStatus,
        createdBy: plan.createdBy,
        createdAt: plan.createdAt.toISOString(),
        updatedAt: plan.updatedAt.toISOString(),
        monitorGroups: groups.map((g) => ({
          id: g.id,
          name: g.name,
          watchType: g.watchType,
          anchorFqn: g.anchorFqn,
          monitorCount: g.monitors?.length || 0,
          healthScore: (g as any).healthScore,
          healthStatus: null,
          monitors: g.monitors,
        })),
      };
    });

    return NextResponse.json({ plans: summaries });
  } catch (error: any) {
    console.error('[Plans] List error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// POST /api/schedule/plans - Create a monitoring plan with child groups
export async function POST(request: NextRequest) {
  try {
    // Support both session auth (browser) and internal auth (copilot executor)
    let organizationId: string | undefined;
    let userId: string = '';

    const internalSecret = request.headers.get('X-Internal-Secret');
    const expectedSecret = process.env.INTERNAL_API_SECRET || 'pallisade-internal';

    if (internalSecret && internalSecret === expectedSecret) {
      organizationId = request.headers.get('X-Organization-Id') || undefined;
      userId = 'copilot-system';
    } else {
      const session = await auth();
      if (!session?.user) {
        return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
      }
      organizationId = (session.user as any).organizationId;
      userId = (session.user as any).id;
    }

    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    const body = await request.json();
    const {
      name,
      description,
      scopeType,
      scopeConfig,
      anchorFqn,
      anchorNodeId,
      mode,
      families,
      schedule,
      timezone = 'UTC',
      alertChannels = [],
      alertOnStatus = ['FAIL', 'WARN', 'ERROR'],
      groups, // Array of group specs from the preview
    } = body;

    console.log('[Plans] POST body:', JSON.stringify({
      name, scopeType, mode, familyCount: families?.length,
      groupCount: groups?.length,
      groupSummary: (groups || []).map((g: any) => ({
        anchor: g.anchor_name, recCount: g.recommendations?.length,
      })),
    }));

    if (!name) {
      return NextResponse.json({ error: 'name is required' }, { status: 400 });
    }
    if (!scopeType) {
      return NextResponse.json({ error: 'scopeType is required' }, { status: 400 });
    }
    if (!mode) {
      return NextResponse.json({ error: 'mode is required' }, { status: 400 });
    }

    // ---- Server-side policy merge ----
    // Resolve policies for all target FQNs and merge into config_hints
    // so monitors are created with policy-correct defaults regardless of caller.
    const targetFqns = new Set<string>();
    for (const group of groups || []) {
      for (const rec of group.recommendations || []) {
        if (rec.target_fqn) targetFqns.add(rec.target_fqn);
      }
    }

    let resolvedPolicies: Record<string, any> = {};
    if (targetFqns.size > 0) {
      try {
        const scannerUrl = process.env.SCANNER_API_URL || 'http://localhost:8000';
        const policyRes = await fetch(`${scannerUrl}/api/v1/policies/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            nodes: Array.from(targetFqns).map((fqn) => ({ fqn, domain: '', criticality: '' })),
            _assignments: (await prisma.policyAssignment.findMany({
              where: { organizationId },
              include: { profile: true },
            })).map((a) => ({
              id: a.id, profileId: a.profileId, assignmentType: a.assignmentType,
              nodeFqn: a.nodeFqn, nodeDomain: a.nodeDomain, nodeCriticality: a.nodeCriticality,
              branchRootFqn: a.branchRootFqn, overrides: a.overrides,
            })),
            _profiles: Object.fromEntries(
              (await prisma.policyProfile.findMany({ where: { organizationId } }))
                .map((p) => [p.id, p])
            ),
          }),
          signal: AbortSignal.timeout(5000),
        });
        if (policyRes.ok) {
          const policyData = await policyRes.json();
          resolvedPolicies = policyData.policies || {};
        }
      } catch (err) {
        console.warn('[Plans] Policy resolve failed (non-fatal), proceeding without policy merge:', err);
      }
    }

    // Merge policy values into each recommendation's config_hints (policy wins)
    if (Object.keys(resolvedPolicies).length > 0) {
      for (const group of groups || []) {
        for (const rec of group.recommendations || []) {
          const policy = resolvedPolicies[rec.target_fqn];
          if (!policy) continue;
          const fieldMap = POLICY_FIELD_MAP[rec.monitor_key];
          if (!fieldMap) continue;
          const hints = rec.config_hints || {};
          for (const fieldKey of Object.keys(fieldMap)) {
            const policyVal = getPolicyValueForField(rec.monitor_key, fieldKey, policy);
            if (policyVal != null) {
              hints[fieldKey] = policyVal;
            }
          }
          rec.config_hints = hints;
        }
      }
    }

    const result = await prisma.$transaction(async (tx) => {
      // Create the plan
      const plan = await tx.monitoringPlan.create({
        data: {
          name,
          description: description || null,
          scopeType,
          scopeConfig: scopeConfig || null,
          anchorFqn: anchorFqn || null,
          anchorNodeId: anchorNodeId || null,
          mode,
          families: families || [],
          schedule: schedule || null,
          timezone,
          alertChannels,
          alertOnStatus,
          createdBy: userId,
          organizationId,
        },
      });

      // Create child groups from the preview groups
      const createdGroups = [];
      let totalMonitors = 0;
      const allTargetFqns = new Set<string>();

      for (const group of groups || []) {
        const monitors = (group.recommendations || []).map((rec: any) => ({
          name: `${(rec.monitor_key || '').replace(/_/g, ' ')} — ${(rec.target_fqn || 'monitor').split('.').pop()}`,
          monitorType: rec.monitor_key,
          targetFqn: rec.target_fqn,
          config: rec.config_hints || {},
          depth: rec.depth || 0,
          priority: rec.priority || 2,
        }));

        const watchResult = await createWatchInTransaction(tx, {
          name: group.anchor_name || 'Monitor Group',
          description: description || null,
          watchType: group.watch_type || 'custom_watch',
          anchorFqn: group.anchor_fqn,
          anchorNodeId: group.anchor_id,
          anchorNodeType: group.anchor_node_type,
          anchorPlatform: group.anchor_platform,
          schedule,
          timezone,
          alertChannels,
          alertOnStatus,
          monitoringPlanId: plan.id,
          monitors,
          organizationId,
          userId,
        });

        createdGroups.push(watchResult.group);
        totalMonitors += watchResult.monitors.length;
        for (const m of watchResult.monitors) {
          if (m.targetFqn) allTargetFqns.add(m.targetFqn);
        }
      }

      // Update plan aggregate counts
      await tx.monitoringPlan.update({
        where: { id: plan.id },
        data: {
          totalAssets: allTargetFqns.size,
          totalMonitors,
        },
      });

      return { plan, groups: createdGroups, totalMonitors };
    }, { maxWait: 15000, timeout: 60000 });

    return NextResponse.json({
      id: result.plan.id,
      name: result.plan.name,
      groupCount: result.groups.length,
      totalMonitors: result.totalMonitors,
    }, { status: 201 });
  } catch (error: any) {
    console.error('[Plans] Create error:', error?.message || error, error?.stack);
    return NextResponse.json(
      { error: error?.message || String(error) },
      { status: 500 },
    );
  }
}
