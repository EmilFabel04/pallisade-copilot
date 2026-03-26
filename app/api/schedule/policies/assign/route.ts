import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import type { SLAAssignmentType } from '@/types/sla';

// POST /api/schedule/policies/assign — Assign a policy to nodes
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
    const {
      profileId,
      assignmentType,
      nodeFqns,
      branchRootFqn,
      nodeDomain,
      nodeCriticality,
      overrides,
      stackId,
    } = body as {
      profileId: string;
      assignmentType: SLAAssignmentType;
      nodeFqns?: string[];
      branchRootFqn?: string;
      nodeDomain?: string;
      nodeCriticality?: string;
      overrides?: Record<string, any>;
      stackId?: string;
    };

    // Validate profile exists — try by ID first, then by name (for backward compat)
    let profile = await prisma.policyProfile.findFirst({
      where: { id: profileId, organizationId },
    });
    if (!profile) {
      // Fallback: match by name in case frontend sent a name-based ID
      profile = await prisma.policyProfile.findFirst({
        where: { name: profileId, organizationId },
      });
    }
    if (!profile) {
      console.error('[Policies] Profile not found:', profileId, 'org:', organizationId);
      return NextResponse.json(
        { error: `Profile not found: ${profileId}. Make sure profiles are seeded.` },
        { status: 404 }
      );
    }
    // Use the real DB profile ID for the assignment
    const resolvedProfileId = profile.id;

    const created: any[] = [];

    if (assignmentType === 'direct') {
      if (!nodeFqns || nodeFqns.length === 0) {
        return NextResponse.json({ error: 'nodeFqns required for direct assignments' }, { status: 400 });
      }

      // Upsert each direct assignment (one per node)
      for (const fqn of nodeFqns) {
        const assignment = await prisma.policyAssignment.upsert({
          where: {
            organizationId_assignmentType_nodeFqn: {
              organizationId,
              assignmentType: 'direct',
              nodeFqn: fqn,
            },
          },
          create: {
            organizationId,
            profileId: resolvedProfileId,
            assignmentType: 'direct',
            nodeFqn: fqn,
            overrides: overrides || undefined,
          },
          update: {
            profileId: resolvedProfileId,
            overrides: overrides || undefined,
          },
        });
        created.push(assignment);
      }
    } else if (assignmentType === 'branch') {
      if (!branchRootFqn) {
        return NextResponse.json({ error: 'branchRootFqn required for branch assignments' }, { status: 400 });
      }

      const assignment = await prisma.policyAssignment.upsert({
        where: {
          organizationId_assignmentType_branchRootFqn: {
            organizationId,
            assignmentType: 'branch',
            branchRootFqn,
          },
        },
        create: {
          organizationId,
          profileId: resolvedProfileId,
          assignmentType: 'branch',
          branchRootFqn,
          overrides: overrides || undefined,
        },
        update: {
          profileId: resolvedProfileId,
          overrides: overrides || undefined,
        },
      });
      created.push(assignment);
    } else if (assignmentType === 'domain_default') {
      if (!nodeDomain) {
        return NextResponse.json({ error: 'nodeDomain required for domain_default' }, { status: 400 });
      }

      const assignment = await prisma.policyAssignment.upsert({
        where: {
          organizationId_assignmentType_nodeDomain_nodeCriticality: {
            organizationId,
            assignmentType: 'domain_default',
            nodeDomain,
            nodeCriticality: null as any,  // domain_default has no criticality
          },
        },
        create: {
          organizationId,
          profileId: resolvedProfileId,
          assignmentType: 'domain_default',
          nodeDomain,
          overrides: overrides || undefined,
        },
        update: {
          profileId: resolvedProfileId,
          overrides: overrides || undefined,
        },
      });
      created.push(assignment);
    } else if (assignmentType === 'criticality_default') {
      if (!nodeDomain || !nodeCriticality) {
        return NextResponse.json(
          { error: 'nodeDomain and nodeCriticality required for criticality_default' },
          { status: 400 }
        );
      }

      const assignment = await prisma.policyAssignment.upsert({
        where: {
          organizationId_assignmentType_nodeDomain_nodeCriticality: {
            organizationId,
            assignmentType: 'criticality_default',
            nodeDomain,
            nodeCriticality,
          },
        },
        create: {
          organizationId,
          profileId: resolvedProfileId,
          assignmentType: 'criticality_default',
          nodeDomain,
          nodeCriticality,
          overrides: overrides || undefined,
        },
        update: {
          profileId: resolvedProfileId,
          overrides: overrides || undefined,
        },
      });
      created.push(assignment);
    } else {
      return NextResponse.json({ error: `Unknown assignmentType: ${assignmentType}` }, { status: 400 });
    }

    // ── Auto-sync: create/update data contracts when contracts are disabled ──
    // When dataContractsEnabled=false, SLA changes auto-update contracts
    console.log('[SLA-Sync] stackId:', stackId, 'assignmentType:', assignmentType, 'nodeFqns:', nodeFqns?.length, 'profile:', profile.name);
    try {
      if (stackId && assignmentType === 'direct' && nodeFqns && nodeFqns.length > 0) {
        const pipeline = await prisma.pipelineStack.findUnique({
          where: { id: stackId },
          select: { dataContractsEnabled: true },
        });
        console.log('[SLA-Sync] pipeline found:', !!pipeline, 'dataContractsEnabled:', pipeline?.dataContractsEnabled);
        // Always sync: create contracts if they don't exist, update only when contracts are disabled
        if (pipeline) {
          const contractsEnabled = pipeline.dataContractsEnabled;
          // Map SLA profile fields → data contract fields
          const contractData: Record<string, unknown> = {};
          if (profile.freshnessConfig) {
            const fc = profile.freshnessConfig as Record<string, unknown>;
            if (fc.maxHours != null) contractData.expectedFreshnessMinutes = Math.round(Number(fc.maxHours) * 60);
          }
          if (profile.ingestionConfig) {
            const ic = profile.ingestionConfig as Record<string, unknown>;
            if (ic.syncLagToleranceMinutes != null) contractData.expectedExtractionFrequencyMinutes = Number(ic.syncLagToleranceMinutes);
          }
          if (profile.criticality) {
            const tierMap: Record<string, string> = { critical: 'T0', high: 'T1', medium: 'T2', low: 'T3' };
            contractData.slaTier = tierMap[profile.criticality as string] || null;
          }

          // Create one contract per unique domain scope from the assigned FQNs
          // Parse domain from first FQN segment (e.g., "bigquery.public.customers" → warehouse)
          // For now, create a single auto-synced contract per assignment
          const fqnParts = nodeFqns[0]?.split('.') || [];
          const scopeRef = fqnParts.length >= 2 ? `${fqnParts[0]}.${fqnParts[1]}` : fqnParts[0] || 'default';
          const scope = 'schema'; // Most lineage nodes are warehouse/data assets

          // When contracts enabled: only create if doesn't exist (don't overwrite user edits)
          // When contracts disabled: always upsert (SLA is source of truth)
          if (contractsEnabled) {
            const existing = await prisma.pipelineDataContract.findUnique({
              where: { pipelineStackId_scope_scopeRef: { pipelineStackId: stackId, scope, scopeRef } },
            });
            if (!existing) {
              await prisma.pipelineDataContract.create({
                data: {
                  pipelineStackId: stackId,
                  scope,
                  scopeRef,
                  autoSynced: false, // User-owned when contracts are enabled
                  ...contractData,
                },
              });
              console.log('[SLA-Sync] Created new data contract (contracts enabled):', scopeRef);
            } else {
              console.log('[SLA-Sync] Skipped update — contract exists and contracts are enabled:', scopeRef);
            }
          } else {
            await prisma.pipelineDataContract.upsert({
              where: {
                pipelineStackId_scope_scopeRef: {
                  pipelineStackId: stackId,
                  scope,
                  scopeRef,
                },
              },
              create: {
                pipelineStackId: stackId,
                scope,
                scopeRef,
                autoSynced: true,
                ...contractData,
              },
              update: {
                autoSynced: true,
                ...contractData,
              },
            });
            console.log('[SLA-Sync] Upserted data contract (contracts disabled):', scopeRef);
          }

          // Also update the SourceContract (per-integration SLA) if an integration exists
          // This keeps the sources page SLA in sync
          const integrations = await prisma.integration.findMany({
            where: {
              pipelineNodes: { some: { stackId } },
            },
            select: { id: true },
          });
          for (const integration of integrations) {
            await prisma.sourceContract.upsert({
              where: { integrationId: integration.id },
              create: {
                integrationId: integration.id,
                pipelineStackId: stackId,
                inheritFromPipeline: true,
                slaTier: contractData.slaTier as string || undefined,
                expectedFreshnessMinutes: contractData.expectedFreshnessMinutes as number || undefined,
                expectedExtractionFrequencyMinutes: contractData.expectedExtractionFrequencyMinutes as number || undefined,
              },
              update: {
                slaTier: contractData.slaTier as string || undefined,
                expectedFreshnessMinutes: contractData.expectedFreshnessMinutes as number || undefined,
                expectedExtractionFrequencyMinutes: contractData.expectedExtractionFrequencyMinutes as number || undefined,
              },
            });
          }
        }
      }
    } catch (syncErr) {
      // Non-critical — log but don't fail the assignment
      console.warn('[SLA] Auto-sync to data contract failed:', syncErr);
    }

    return NextResponse.json({
      created: created.length,
      assignments: created,
      message: `SLA assigned to ${created.length} target(s)`,
    });
  } catch (error: any) {
    console.error('[Policies] Error assigning policy:', error?.message, error?.code, error?.meta);
    return NextResponse.json({
      error: error.message || 'Failed to assign policy',
      code: error.code || null,
      meta: error.meta || null,
    }, { status: 500 });
  }
}

// DELETE /api/schedule/policies/assign — Delete an assignment by ID
export async function DELETE(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    const { searchParams } = new URL(request.url);
    const assignmentId = searchParams.get('id');
    if (!assignmentId) {
      return NextResponse.json({ error: 'Assignment id required' }, { status: 400 });
    }

    const existing = await prisma.policyAssignment.findFirst({
      where: { id: assignmentId, organizationId },
    });
    if (!existing) {
      return NextResponse.json({ error: 'Assignment not found' }, { status: 404 });
    }

    await prisma.policyAssignment.delete({ where: { id: assignmentId } });

    return NextResponse.json({ deleted: assignmentId });
  } catch (error: any) {
    console.error('[Policies] Error deleting assignment:', error);
    return NextResponse.json({ error: error.message || 'Failed to delete assignment' }, { status: 500 });
  }
}
