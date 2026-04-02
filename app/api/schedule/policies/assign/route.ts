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
            nodeDomain: nodeDomain || undefined,
            overrides: overrides || undefined,
          },
          update: {
            profileId: resolvedProfileId,
            nodeDomain: nodeDomain || undefined,
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
    } else if (assignmentType === 'auto_discovered') {
      if (!nodeFqns || nodeFqns.length === 0) {
        return NextResponse.json({ error: 'nodeFqns required for auto_discovered assignments' }, { status: 400 });
      }

      for (const fqn of nodeFqns) {
        const assignment = await prisma.policyAssignment.upsert({
          where: {
            organizationId_assignmentType_nodeFqn: {
              organizationId,
              assignmentType: 'auto_discovered',
              nodeFqn: fqn,
            },
          },
          create: {
            organizationId,
            profileId: resolvedProfileId,
            assignmentType: 'auto_discovered',
            nodeFqn: fqn,
          },
          update: {
            profileId: resolvedProfileId,
          },
        });
        created.push(assignment);
      }
    } else {
      return NextResponse.json({ error: `Unknown assignmentType: ${assignmentType}` }, { status: 400 });
    }

    // ── Auto-sync: create/update data SLAs when data SLAs are disabled ──
    // When dataSLAsEnabled=false, SLA changes auto-update data SLA records
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
          // Map SLA profile → data contract fields (full config sections + legacy fields)
          const contractData: Record<string, unknown> = {};
          // SLA tier from criticality
          if (profile.criticality) {
            const tierMap: Record<string, string> = { critical: 'T0', high: 'T1', medium: 'T2', low: 'T3' };
            contractData.slaTier = tierMap[profile.criticality as string] || null;
          }
          // Full domain-specific config sections (same shape as PolicyProfile)
          const configKeys = [
            'freshnessConfig', 'schemaConfig', 'volumeConfig', 'anomalyConfig',
            'qualityConfig', 'ingestionConfig', 'biConfig', 'orchestrationConfig',
            'transformConfig',
          ] as const;
          for (const key of configKeys) {
            if (profile[key]) contractData[key] = profile[key];
          }
          // Also apply per-assignment overrides into configs
          if (overrides && typeof overrides === 'object') {
            for (const [section, fields] of Object.entries(overrides as Record<string, any>)) {
              if (fields && typeof fields === 'object') {
                const configKey = `${section}` as string;
                if (contractData[configKey] && typeof contractData[configKey] === 'object') {
                  contractData[configKey] = { ...(contractData[configKey] as Record<string, unknown>), ...fields };
                } else {
                  contractData[configKey] = fields;
                }
              }
            }
          }
          // Legacy fields for backwards compat
          if (profile.freshnessConfig) {
            const fc = profile.freshnessConfig as Record<string, unknown>;
            if (fc.maxHours != null) contractData.expectedFreshnessMinutes = Math.round(Number(fc.maxHours) * 60);
          }
          if (profile.ingestionConfig) {
            const ic = profile.ingestionConfig as Record<string, unknown>;
            if (ic.syncLagToleranceMinutes != null) contractData.expectedExtractionFrequencyMinutes = Number(ic.syncLagToleranceMinutes);
          }

          // Build a stable scopeRef from sorted FQNs for the unique constraint
          const sortedFqns = [...nodeFqns].sort();
          const scopeRef = sortedFqns.join(',').slice(0, 200) || 'default';
          const scope = 'schema';
          const contractName = `${profile.name} — ${nodeFqns.length} node${nodeFqns.length !== 1 ? 's' : ''}`;

          // When contracts enabled: only create if doesn't exist (don't overwrite user edits)
          // When contracts disabled: always upsert (SLA is source of truth)
          // First check if a contract already covers any of these nodes
          const existingContracts = await prisma.pipelineDataContract.findMany({
            where: { pipelineStackId: stackId },
          });
          const existingForNodes = existingContracts.find(c => {
            const cFqns = (c.nodeFqns as string[] | null) || [];
            return cFqns.length > 0 && nodeFqns.some(fqn => cFqns.includes(fqn));
          });
          // Also check by legacy scopeRef
          const existingByScopeRef = existingContracts.find(c => c.scopeRef === scopeRef);
          const existing = existingForNodes || existingByScopeRef;

          if (contractsEnabled) {
            if (!existing) {
              await prisma.pipelineDataContract.create({
                data: {
                  pipelineStackId: stackId,
                  scope,
                  scopeRef,
                  name: contractName,
                  nodeFqns: sortedFqns,
                  autoSynced: false,
                  ...contractData,
                },
              });
            }
          } else {
            if (existing) {
              await prisma.pipelineDataContract.update({
                where: { id: existing.id },
                data: {
                  autoSynced: true,
                  nodeFqns: sortedFqns,
                  name: existing.name || contractName,
                  ...contractData,
                },
              });
            } else {
              await prisma.pipelineDataContract.create({
                data: {
                  pipelineStackId: stackId,
                  scope,
                  scopeRef,
                  name: contractName,
                  nodeFqns: sortedFqns,
                  autoSynced: true,
                  ...contractData,
                },
              });
            }
          }

          // Update the SourceContract for the integration that owns the assigned nodes.
          // Tool nodes (ingestion/orchestration) get the direct SLA tier.
          // Data asset tools (warehouse/transformation) will aggregate from child assignments
          // when the sources page fetches data — we only update matching integrations here.
          const assignedNodes = await prisma.pipelineNode.findMany({
            where: {
              stackId,
              OR: nodeFqns.map(fqn => {
                const parts = fqn.split('.');
                return { name: parts[parts.length - 1] };
              }),
            },
            select: { integrationId: true, layer: true },
          });
          const integrationIds = [...new Set(assignedNodes.map(n => n.integrationId).filter(Boolean))] as string[];
          for (const integrationId of integrationIds) {
            await prisma.sourceContract.upsert({
              where: { integrationId },
              create: {
                integrationId,
                pipelineStackId: stackId,
                inheritFromPipeline: false,
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
      console.warn('[SLA] Auto-sync to data SLA failed:', syncErr);
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

// PATCH /api/schedule/policies/assign — Update assignment status
export async function PATCH(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const body = await request.json();
    const { id, status } = body;
    if (!id || !['active', 'inactive', 'archived'].includes(status)) {
      return NextResponse.json({ error: 'Invalid id or status' }, { status: 400 });
    }
    const assignment = await prisma.policyAssignment.update({
      where: { id },
      data: {
        status,
        archivedAt: status === 'archived' ? new Date() : null,
      },
    });
    return NextResponse.json({ assignment });
  } catch (error) {
    console.error('Error updating assignment status:', error);
    return NextResponse.json({ error: 'Failed to update' }, { status: 500 });
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

    // Delete by assignment ID
    if (assignmentId) {
      const existing = await prisma.policyAssignment.findFirst({
        where: { id: assignmentId, organizationId },
      });
      if (!existing) {
        return NextResponse.json({ error: 'Assignment not found' }, { status: 404 });
      }
      await prisma.policyAssignment.delete({ where: { id: assignmentId } });
      return NextResponse.json({ deleted: assignmentId });
    }

    // Delete by node FQNs (from request body)
    const body = await request.json().catch(() => null);
    const nodeFqns: string[] = body?.nodeFqns;
    if (nodeFqns?.length) {
      const deleted = await prisma.policyAssignment.deleteMany({
        where: {
          organizationId,
          assignmentType: 'direct',
          nodeFqn: { in: nodeFqns },
        },
      });
      return NextResponse.json({ deleted: deleted.count });
    }

    return NextResponse.json({ error: 'Assignment id or nodeFqns required' }, { status: 400 });
  } catch (error: any) {
    console.error('[Policies] Error deleting assignment:', error);
    return NextResponse.json({ error: error.message || 'Failed to delete assignment' }, { status: 500 });
  }
}
