import { NextRequest, NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { createWatchInTransaction } from '@/lib/watch-helpers';
import { scannerClient } from '@/lib/scanner-client';
import { SLA_FIELD_MAP, getSLAValueForField } from '@/lib/sla-utils';

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

    const stackId = new URL(request.url).searchParams.get('stackId');
    if (!stackId) {
      return NextResponse.json(
        { error: 'stackId query parameter is required' },
        { status: 400 }
      );
    }

    const plans = await prisma.monitoringPlan.findMany({
      where: { organizationId, pipelineStackId: stackId },
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
        monitorGroups: groups.map((g) => {
          const mons = g.monitors || [];
          let gPass = 0, gWarn = 0, gFail = 0;
          for (const m of mons) {
            if (m.lastStatus === 'PASS') gPass++;
            else if (m.lastStatus === 'WARN') gWarn++;
            else if (m.lastStatus === 'FAIL' || m.lastStatus === 'ERROR') gFail++;
          }
          return {
            id: g.id,
            name: g.name,
            watchType: g.watchType,
            anchorFqn: g.anchorFqn,
            anchorNodeId: (g as any).anchorNodeId,
            anchorNodeType: (g as any).anchorNodeType,
            anchorPlatform: (g as any).anchorPlatform,
            schedule: g.schedule,
            timezone: (g as any).timezone,
            monitorCount: mons.length,
            passCount: gPass,
            warnCount: gWarn,
            failCount: gFail,
            healthScore: (g as any).healthScore,
            healthStatus: null,
            lastRunAt: mons.reduce<string | null>((latest, m) => {
              if (!m.lastRunAt) return latest;
              const ts = new Date(m.lastRunAt).toISOString();
              return !latest || ts > latest ? ts : latest;
            }, null),
            monitors: mons,
          };
        }),
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
    let session: Session | null = null;

    const internalSecret = request.headers.get('X-Internal-Secret');
    const expectedSecret = process.env.INTERNAL_API_SECRET || 'pallisade-internal';

    if (internalSecret && internalSecret === expectedSecret) {
      organizationId = request.headers.get('X-Organization-Id') || undefined;
      userId = 'copilot-system';
      // Synthesize a session for downstream scannerClient calls
      session = {
        user: { id: userId, organizationId },
        expires: '',
      } as unknown as Session;
    } else {
      session = await auth();
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
      alertDestinations = [], // New per-integration destination routing
      groups, // Array of group specs from the preview
      stackId, // Pipeline stack ID for contract-aware resolution
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
    if (!stackId) {
      return NextResponse.json(
        { error: 'stackId is required' },
        { status: 400 }
      );
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
        const policyRes = await scannerClient.fetch(session!, '/api/v1/policies/resolve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            nodes: Array.from(targetFqns).map((fqn) => ({ fqn, domain: '', criticality: '' })),
            stackId,
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
          const fieldMap = SLA_FIELD_MAP[rec.monitor_key];
          if (!fieldMap) continue;
          const hints = rec.config_hints || {};
          for (const fieldKey of Object.keys(fieldMap)) {
            const policyVal = getSLAValueForField(rec.monitor_key, fieldKey, policy);
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
          pipelineStackId: stackId,
        },
      });

      // Create child groups from the preview groups
      const createdGroups = [];
      let totalMonitors = 0;
      const allTargetFqns = new Set<string>();

      // Per-destination routing: build alertConfig.destinations from the
      // top-level alertDestinations array and also derive per-monitor channel
      // types / triggerOn defaults so legacy consumers keep working.
      const destinations = Array.isArray(alertDestinations) ? alertDestinations : [];
      const derivedChannelTypes = Array.from(
        new Set(destinations.map((d: any) => d.channelType).filter(Boolean)),
      );
      const derivedTriggerOn = Array.from(
        new Set(destinations.flatMap((d: any) => d.triggerOn || [])),
      );
      const effectiveAlertChannels = destinations.length > 0 ? derivedChannelTypes : alertChannels;
      const effectiveAlertOnStatus = destinations.length > 0 && derivedTriggerOn.length > 0
        ? derivedTriggerOn
        : alertOnStatus;

      for (const group of groups || []) {
        const monitors = (group.recommendations || []).map((rec: any) => ({
          name: `${(rec.monitor_key || '').replace(/_/g, ' ')} — ${(rec.target_fqn || 'monitor').split('.').pop()}`,
          monitorType: rec.monitor_key,
          targetFqn: rec.target_fqn,
          config: rec.config_hints || {},
          depth: rec.depth || 0,
          priority: rec.priority || 2,
          alertChannels: effectiveAlertChannels,
          alertOnStatus: effectiveAlertOnStatus,
          alertConfig: destinations.length > 0 ? { destinations } : undefined,
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
          alertChannels: effectiveAlertChannels,
          alertOnStatus: effectiveAlertOnStatus,
          alertConfig: destinations.length > 0 ? { destinations } : undefined,
          monitoringPlanId: plan.id,
          monitors,
          organizationId,
          pipelineStackId: stackId,
          userId,
        });

        createdGroups.push(watchResult.group);
        totalMonitors += watchResult.monitors.length;
        for (const m of watchResult.monitors) {
          if (m.targetFqn) allTargetFqns.add(m.targetFqn);
        }
      }

      // After per-asset dedup (lib/watch-helpers.ts), watchResult.group
      // may be an existing group owned by a different plan (or none) —
      // those groups keep their original monitoringPlanId. If NONE of the
      // watches in this request produced a group attached to this plan,
      // the new plan would appear empty in the plans list. Drop it.
      const ownedGroupCount = createdGroups.filter(
        (g) => g.monitoringPlanId === plan.id,
      ).length;
      if (ownedGroupCount === 0) {
        await tx.monitoringPlan.delete({ where: { id: plan.id } });
        return { plan: null, groups: createdGroups, totalMonitors };
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
      id: result.plan?.id ?? null,
      name: result.plan?.name ?? null,
      groupCount: result.groups.length,
      totalMonitors: result.totalMonitors,
      planSkipped: result.plan === null,
    }, { status: 201 });
  } catch (error: any) {
    console.error('[Plans] Create error:', error?.message || error, error?.stack);
    return NextResponse.json(
      { error: error?.message || String(error) },
      { status: 500 },
    );
  }
}
