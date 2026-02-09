/**
 * Pipeline API
 *
 * GET - Fetch user's pipeline stack
 * POST - Save pipeline stack
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { encrypt, decrypt } from '@/lib/crypto';

// Helper to encrypt node config for secure storage
function encryptNodeConfig(config: Record<string, any> | null | undefined): Record<string, any> | undefined {
  if (!config || Object.keys(config).length === 0) {
    return undefined;
  }
  try {
    const encrypted = encrypt(JSON.stringify(config));
    return { encrypted };
  } catch (e) {
    console.error('[PIPELINE] Failed to encrypt config:', e);
    // Fall back to storing unencrypted (not ideal but prevents data loss)
    return config;
  }
}

// Helper to decrypt node config when returning to frontend
function decryptNodeConfig(config: any): Record<string, any> | null {
  if (!config) return null;
  try {
    if (config.encrypted) {
      const decrypted = decrypt(config.encrypted);
      return JSON.parse(decrypted);
    }
    // Config is not encrypted (legacy data), return as-is
    return config as Record<string, any>;
  } catch (e) {
    console.error('[PIPELINE] Failed to decrypt config:', e);
    return null;
  }
}

// GET - Fetch the user's pipeline stack(s)
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Organization not found' }, { status: 404 });
    }

    const organizationId = user.organizationId;
    const searchParams = request.nextUrl.searchParams;
    const stackId = searchParams.get('id') || searchParams.get('stackId');
    const listAll = searchParams.get('all') === 'true';
    const includeStacksList = searchParams.get('includeStacksList') !== 'false'; // default true for backwards compat
    const excludeConfigs = searchParams.get('excludeConfigs') === 'true'; // Skip decrypting configs for faster loads

    // If listAll=true, return all stacks (for dropdown/selection)
    if (listAll) {
      const stacks = await prisma.pipelineStack.findMany({
        where: { organizationId },
        select: {
          id: true,
          name: true,
          status: true,
          healthScore: true,
          lastScanAt: true,
          _count: { select: { nodes: true } },
        },
        orderBy: { updatedAt: 'desc' },
      });

      return NextResponse.json({
        stacks: stacks.map(s => ({
          id: s.id,
          name: s.name,
          status: s.status,
          healthScore: s.healthScore,
          lastScanAt: s.lastScanAt?.toISOString(),
          nodeCount: s._count.nodes,
        })),
      });
    }

    // Get specific stack or first one
    const stack = stackId
      ? await prisma.pipelineStack.findUnique({
          where: { id: stackId },
          include: {
            nodes: { orderBy: { createdAt: 'asc' } },
            edges: true,
          },
        })
      : await prisma.pipelineStack.findFirst({
          where: { organizationId },
          include: {
            nodes: { orderBy: { createdAt: 'asc' } },
            edges: true,
          },
        });

    // Only fetch stacks list if requested (saves a query on dashboard page loads)
    let stacksList: Array<{
      id: string;
      name: string;
      description: string | null;
      status: string;
      healthScore: number | null;
      lastScanAt: string | undefined;
      nodeCount: number;
    }> = [];

    if (includeStacksList) {
      const allStacks = await prisma.pipelineStack.findMany({
        where: { organizationId },
        select: {
          id: true,
          name: true,
          description: true,
          status: true,
          healthScore: true,
          lastScanAt: true,
          _count: { select: { nodes: true } },
        },
        orderBy: { updatedAt: 'desc' },
      });

      stacksList = allStacks.map(s => ({
        id: s.id,
        name: s.name,
        description: s.description,
        status: s.status,
        healthScore: s.healthScore,
        lastScanAt: s.lastScanAt?.toISOString(),
        nodeCount: s._count.nodes,
      }));
    }

    if (!stack) {
      return NextResponse.json({ stack: null, stacks: stacksList });
    }

    // Verify ownership
    if (stack.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
    }

    // Transform to match frontend types
    return NextResponse.json({
      stack: {
        id: stack.id,
        name: stack.name,
        description: stack.description || '',
        status: stack.status,
        healthScore: stack.healthScore,
        lastScanAt: stack.lastScanAt?.toISOString(),
        nodes: stack.nodes.map(node => ({
          id: node.id,
          name: node.name,
          layer: node.layer,
          toolType: node.toolType,
          // Skip config decryption if excludeConfigs=true (faster dashboard loads)
          config: excludeConfigs ? null : decryptNodeConfig(node.config),
          positionX: node.positionX,
          positionY: node.positionY,
          status: node.status,
          lastTestedAt: node.lastTestedAt?.toISOString(),
          lastError: node.lastError,
          healthScore: node.healthScore,
          lastScanAt: node.lastScanAt?.toISOString(),
          findingsCount: node.findingsCount,
          criticalCount: node.criticalCount,
          highCount: node.highCount,
          integrationId: node.integrationId,
        })),
        edges: stack.edges.map(edge => ({
          id: edge.id,
          sourceId: edge.sourceId,
          targetId: edge.targetId,
          label: edge.label,
          dataFlow: edge.dataFlow,
        })),
      },
      stacks: stacksList,
    });
  } catch (error) {
    console.error('Failed to fetch pipeline:', error);
    return NextResponse.json({ error: 'Failed to fetch pipeline' }, { status: 500 });
  }
}

// POST - Save the pipeline stack
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email },
      select: { organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Organization not found' }, { status: 404 });
    }

    const organizationId = user.organizationId;
    const body = await request.json();
    
    const { id, name, description, nodes = [], edges = [] } = body;

    // Check if creating new or updating existing
    // Treat undefined, null, or 'new' as creating a new stack
    const isNew = !id || id === 'new';

    if (isNew) {
      // Create new stack (with optional nodes and edges)
      const stack = await prisma.pipelineStack.create({
        data: {
          name: name || 'My Data Pipeline',
          description: description || null,
          status: nodes.length > 0 ? 'CONFIGURING' : 'DRAFT',
          organizationId,
          ...(nodes.length > 0 ? {
            nodes: {
              create: nodes.map((node: any) => ({
                name: node.name,
                layer: node.layer,
                toolType: node.toolType,
                config: encryptNodeConfig(node.config),
                positionX: node.positionX,
                positionY: node.positionY,
                status: node.status,
              })),
            },
          } : {}),
        },
        include: { nodes: true },
      });

      // Create edges if nodes were provided (need node IDs from DB)
      if (nodes.length > 0 && edges.length > 0) {
        const nodeIdMap = new Map<string, string>();
        nodes.forEach((node: any, index: number) => {
          nodeIdMap.set(node.id, stack.nodes[index].id);
        });

        // Create edges with mapped IDs
        await Promise.all(
          edges.map((edge: any) =>
            prisma.pipelineEdge.create({
              data: {
                sourceId: nodeIdMap.get(edge.sourceId) || edge.sourceId,
                targetId: nodeIdMap.get(edge.targetId) || edge.targetId,
                label: edge.label,
                dataFlow: edge.dataFlow,
                stackId: stack.id,
              },
            })
          )
        );
      }

      return NextResponse.json({ stack: { id: stack.id, name: stack.name }, success: true });
    } else {
      // Update existing stack
      // Get existing nodes for ID mapping
      const existingStack = await prisma.pipelineStack.findUnique({
        where: { id },
        include: { nodes: true, edges: true },
      });

      if (!existingStack || existingStack.organizationId !== organizationId) {
        return NextResponse.json({ error: 'Stack not found' }, { status: 404 });
      }

      // Update stack metadata
      await prisma.pipelineStack.update({
        where: { id },
        data: {
          name,
          description,
          status: nodes.length > 0 ? 'CONFIGURING' : 'DRAFT',
        },
      });

      // Get existing node IDs
      const existingNodeIds = new Set(existingStack.nodes.map(n => n.id));
      const newNodeIds = new Set(nodes.map((n: any) => n.id));

      // Delete removed nodes
      const nodesToDelete = existingStack.nodes.filter(n => !newNodeIds.has(n.id));
      await prisma.pipelineNode.deleteMany({
        where: { id: { in: nodesToDelete.map(n => n.id) } },
      });

      // Upsert nodes
      const nodeIdMap = new Map<string, string>();
      for (const node of nodes) {
        if (existingNodeIds.has(node.id)) {
          // Update existing
          await prisma.pipelineNode.update({
            where: { id: node.id },
            data: {
              name: node.name,
              layer: node.layer,
              toolType: node.toolType,
              config: encryptNodeConfig(node.config),
              positionX: node.positionX,
              positionY: node.positionY,
              status: node.status,
            },
          });
          nodeIdMap.set(node.id, node.id);
        } else {
          // Create new
          const created = await prisma.pipelineNode.create({
            data: {
              name: node.name,
              layer: node.layer,
              toolType: node.toolType,
              config: encryptNodeConfig(node.config),
              positionX: node.positionX,
              positionY: node.positionY,
              status: node.status,
              stackId: id,
            },
          });
          nodeIdMap.set(node.id, created.id);
        }
      }

      // Delete all existing edges and recreate
      await prisma.pipelineEdge.deleteMany({
        where: { stackId: id },
      });

      // Create edges with mapped IDs
      await Promise.all(
        edges.map((edge: any) =>
          prisma.pipelineEdge.create({
            data: {
              sourceId: nodeIdMap.get(edge.sourceId) || edge.sourceId,
              targetId: nodeIdMap.get(edge.targetId) || edge.targetId,
              label: edge.label,
              dataFlow: edge.dataFlow,
              stackId: id,
            },
          })
        )
      );

      return NextResponse.json({ id, success: true });
    }
  } catch (error) {
    console.error('Failed to save pipeline:', error);
    return NextResponse.json({ error: 'Failed to save pipeline' }, { status: 500 });
  }
}
