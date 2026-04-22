import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { scannerClient } from '@/lib/scanner-client';

// POST /api/schedule/policies/resolve — Resolve effective policies for nodes
// This loads assignments + profiles from DB, then sends to FastAPI for graph-aware resolution.
// If FastAPI is unavailable, falls back to local resolution using criticality defaults.
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

    const body = await request.json();
    const { nodes, stackId } = body as {
      nodes: Array<{ fqn: string; domain: string; criticality: string }>;
      stackId?: string;
    };

    if (!nodes || nodes.length === 0) {
      return NextResponse.json({ policies: {} });
    }

    // Load all assignments and profiles for this org
    const [assignments, profiles] = await Promise.all([
      prisma.policyAssignment.findMany({
        where: { organizationId },
        include: { profile: true },
      }),
      prisma.policyProfile.findMany({
        where: { organizationId },
      }),
    ]);

    // Build profile lookup
    const profileMap: Record<string, any> = {};
    for (const p of profiles) {
      profileMap[p.id] = p;
    }

    // Try to proxy to FastAPI for graph-aware resolution (branch distance, etc.)
    try {
      const res = await scannerClient.fetch(session, '/api/v1/policies/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nodes,
          stackId,
          // Pass DB data to FastAPI so it can resolve
          _assignments: assignments.map((a) => ({
            id: a.id,
            profileId: a.profileId,
            assignmentType: a.assignmentType,
            nodeFqn: a.nodeFqn,
            nodeDomain: a.nodeDomain,
            nodeCriticality: a.nodeCriticality,
            branchRootFqn: a.branchRootFqn,
            overrides: a.overrides,
          })),
          _profiles: profileMap,
        }),
        signal: AbortSignal.timeout(5000),
      });

      if (res.ok) {
        const data = await res.json();
        return NextResponse.json(data);
      }
    } catch {
      // FastAPI unavailable — fall back to simple resolution
    }

    // Fallback: local resolution without graph (no branch distance calc)
    // Handles direct, domain_default, criticality_default assignments.
    // Branch assignments require graph distance — skipped in fallback.
    const policies: Record<string, any> = {};

    // Index assignments by type
    const directByFqn = new Map<string, typeof assignments[0]>();
    const critDefaults = new Map<string, typeof assignments[0]>(); // key: domain:criticality
    const domainDefaults = new Map<string, typeof assignments[0]>(); // key: domain
    const autoDiscoveredByFqn = new Map<string, typeof assignments[0]>();

    for (const a of assignments) {
      if (a.assignmentType === 'direct' && a.nodeFqn) {
        directByFqn.set(a.nodeFqn, a);
      } else if (a.assignmentType === 'auto_discovered' && a.nodeFqn) {
        autoDiscoveredByFqn.set(a.nodeFqn, a);
      } else if (a.assignmentType === 'criticality_default' && a.nodeDomain && a.nodeCriticality) {
        critDefaults.set(`${a.nodeDomain}:${a.nodeCriticality}`, a);
      } else if (a.assignmentType === 'domain_default' && a.nodeDomain && !a.nodeCriticality) {
        domainDefaults.set(a.nodeDomain, a);
      }
    }

    const configFromProfile = (profile: any) => ({
      freshness: profile?.freshnessConfig || {},
      schema: profile?.schemaConfig || {},
      volume: profile?.volumeConfig || {},
      anomaly: profile?.anomalyConfig || {},
      quality: profile?.qualityConfig || {},
      ingestion: profile?.ingestionConfig || {},
      bi: profile?.biConfig || {},
      orchestration: profile?.orchestrationConfig || {},
      transform: profile?.transformConfig || {},
    });

    for (const node of nodes) {
      // Resolution chain: direct → auto_discovered → criticality_default → domain_default → builtin
      const direct = directByFqn.get(node.fqn);
      if (direct) {
        const profile = profileMap[direct.profileId];
        // Node-level status is always "assigned" — customized values within
        // the profile are the user's SLA/SLO configuration, not an override.
        // "Override" only applies at the monitor level when a running monitor's
        // config diverges from the policy rules.
        const effectiveConfig = configFromProfile(profile);
        // Merge any per-assignment overrides into the effective config
        if (direct.overrides && typeof direct.overrides === 'object') {
          for (const [section, fields] of Object.entries(direct.overrides as Record<string, any>)) {
            if (fields && typeof fields === 'object' && effectiveConfig[section as keyof typeof effectiveConfig]) {
              Object.assign(effectiveConfig[section as keyof typeof effectiveConfig], fields);
            }
          }
        }
        policies[node.fqn] = {
          source: 'direct_profile',
          profileId: direct.profileId,
          profileName: profile?.name || null,
          status: 'assigned',
          ...effectiveConfig,
        };
        continue;
      }

      const autoDiscovered = autoDiscoveredByFqn.get(node.fqn);
      if (autoDiscovered) {
        const profile = profileMap[autoDiscovered.profileId];
        policies[node.fqn] = {
          source: 'auto_discovered',
          profileId: autoDiscovered.profileId,
          profileName: profile?.name || null,
          status: 'assigned',
          ...configFromProfile(profile),
        };
        continue;
      }

      const critDefault = critDefaults.get(`${node.domain}:${node.criticality}`);
      if (critDefault) {
        const profile = profileMap[critDefault.profileId];
        policies[node.fqn] = {
          source: 'criticality_default',
          profileId: critDefault.profileId,
          profileName: profile?.name || null,
          status: 'assigned',
          ...configFromProfile(profile),
        };
        continue;
      }

      const domDefault = domainDefaults.get(node.domain);
      if (domDefault) {
        const profile = profileMap[domDefault.profileId];
        policies[node.fqn] = {
          source: 'domain_default',
          profileId: domDefault.profileId,
          profileName: profile?.name || null,
          status: 'assigned',
          ...configFromProfile(profile),
        };
        continue;
      }

      // No SLA assigned — return empty policy with status 'none'
      policies[node.fqn] = {
        source: 'none',
        profileId: null,
        profileName: null,
        status: 'none' as const,
        ...configFromProfile({}),
      };
    }

    return NextResponse.json({ policies });
  } catch (error: any) {
    console.error('[Policies] Error resolving policies:', error);
    return NextResponse.json({ error: error.message || 'Failed to resolve policies' }, { status: 500 });
  }
}
