import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import type { PolicyAssignmentType } from '@/types/policy';

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
    } = body as {
      profileId: string;
      assignmentType: PolicyAssignmentType;
      nodeFqns?: string[];
      branchRootFqn?: string;
      nodeDomain?: string;
      nodeCriticality?: string;
      overrides?: Record<string, any>;
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

    return NextResponse.json({
      created: created.length,
      assignments: created,
      message: `Policy assigned to ${created.length} target(s)`,
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
