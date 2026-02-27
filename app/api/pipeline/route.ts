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

// Helper to encrypt node config for secure storage (legacy — kept for _cached data)
function encryptNodeConfig(config: Record<string, any> | null | undefined): Record<string, any> | undefined {
  if (!config || Object.keys(config).length === 0) {
    return undefined;
  }
  try {
    const encrypted = encrypt(JSON.stringify(config));
    return { encrypted };
  } catch (e) {
    console.error('[PIPELINE] Failed to encrypt config:', e);
    return config;
  }
}

// Keys that are NOT real credentials — skip when deciding whether to create an Integration
const NON_CREDENTIAL_KEYS = new Set(['_cached', '_autoDiscovered']);

function hasRealCredentials(config: Record<string, any> | null | undefined): boolean {
  if (!config) return false;
  return Object.keys(config).some(k => !NON_CREDENTIAL_KEYS.has(k));
}

/**
 * Upsert an Integration record for a pipeline node's credentials.
 * Returns the Integration ID.
 */
async function upsertNodeIntegration(
  organizationId: string,
  node: { name: string; toolType: string; config: Record<string, any>; status?: string },
  existingIntegrationId?: string | null,
): Promise<string | null> {
  // Strip internal keys to get only real credentials
  const { _cached, _autoDiscovered, ...credentials } = node.config;
  if (Object.keys(credentials).length === 0) return existingIntegrationId || null;

  const integrationType = node.toolType.toUpperCase();
  const encryptedCreds = { encrypted: encrypt(JSON.stringify(credentials)) };
  const isActive = ['CONNECTED', 'HEALTHY', 'WARNING'].includes(node.status || '');

  // If node already has an integrationId, update that record
  if (existingIntegrationId) {
    try {
      await prisma.integration.update({
        where: { id: existingIntegrationId },
        data: {
          credentials: encryptedCreds,
          status: isActive ? 'ACTIVE' : 'INACTIVE',
          name: node.name,
        },
      });
      console.log(`[PIPELINE] Updated Integration ${existingIntegrationId} for ${integrationType}`);
      return existingIntegrationId;
    } catch (e) {
      console.error(`[PIPELINE] Failed to update Integration ${existingIntegrationId}:`, e);
    }
  }

  // Upsert Integration record (unique constraint: organizationId + type + name)
  try {
    const integration = await prisma.integration.upsert({
      where: {
        organizationId_type_name: {
          organizationId,
          type: integrationType as any,
          name: node.name,
        },
      },
      update: {
        credentials: encryptedCreds,
        status: isActive ? 'ACTIVE' : 'INACTIVE',
      },
      create: {
        name: node.name,
        type: integrationType as any,
        status: isActive ? 'ACTIVE' : 'INACTIVE',
        credentials: encryptedCreds,
        organizationId,
      },
    });
    console.log(`[PIPELINE] Upserted Integration ${integration.id} for ${integrationType}`);
    return integration.id;
  } catch (e) {
    console.error(`[PIPELINE] Failed to upsert Integration for ${integrationType}:`, e);
    return null;
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

    // Get specific stack or first one (include integration for credential resolution)
    const nodeInclude = {
      orderBy: { createdAt: 'asc' as const },
      include: { integration: true },
    };
    const stack = stackId
      ? await prisma.pipelineStack.findUnique({
          where: { id: stackId },
          include: { nodes: nodeInclude, edges: true },
        })
      : await prisma.pipelineStack.findFirst({
          where: { organizationId },
          include: { nodes: nodeInclude, edges: true },
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
        nodes: stack.nodes.map((node: any) => {
          let config = null;
          if (!excludeConfigs) {
            // Prefer Integration credentials, fall back to legacy PipelineNode.config
            if (node.integrationId && node.integration?.credentials) {
              const intCreds = node.integration.credentials as any;
              try {
                if (intCreds.encrypted) {
                  config = JSON.parse(decrypt(intCreds.encrypted));
                } else {
                  config = intCreds;
                }
              } catch (e) {
                console.error(`[PIPELINE] Failed to decrypt integration creds for ${node.name}:`, e);
                config = decryptNodeConfig(node.config);
              }
            } else {
              config = decryptNodeConfig(node.config);
            }
          }
          return {
            id: node.id,
            name: node.name,
            layer: node.layer,
            toolType: node.toolType,
            config,
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
          };
        }),
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
      // Create new stack
      const stack = await prisma.pipelineStack.create({
        data: {
          name: name || 'My Data Pipeline',
          description: description || null,
          status: nodes.length > 0 ? 'CONFIGURING' : 'DRAFT',
          organizationId,
        },
      });

      // Create nodes, upsert Integration records for credentials
      const nodeIdMap = new Map<string, string>();
      for (const node of nodes) {
        let integrationId: string | null = null;
        const cachedData = node.config?._cached || null;

        if (hasRealCredentials(node.config)) {
          integrationId = await upsertNodeIntegration(organizationId, node);
        }

        const created = await prisma.pipelineNode.create({
          data: {
            name: node.name,
            layer: node.layer,
            toolType: node.toolType,
            config: cachedData ? { _cached: cachedData } : undefined,
            positionX: node.positionX,
            positionY: node.positionY,
            status: node.status,
            stackId: stack.id,
            ...(integrationId ? { integrationId } : {}),
          },
        });
        nodeIdMap.set(node.id, created.id);
      }

      // Create edges if nodes were provided
      if (nodes.length > 0 && edges.length > 0) {

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

      // Build lookup for existing nodes' integrationIds
      const existingIntegrationIds = new Map<string, string | null>();
      for (const n of existingStack.nodes) {
        existingIntegrationIds.set(n.id, (n as any).integrationId || null);
      }

      // Upsert nodes — credentials go to Integration table, not PipelineNode.config
      const nodeIdMap = new Map<string, string>();
      for (const node of nodes) {
        const cachedData = node.config?._cached || null;

        if (existingNodeIds.has(node.id)) {
          // Update existing node
          let integrationId = existingIntegrationIds.get(node.id) || null;

          if (hasRealCredentials(node.config)) {
            integrationId = await upsertNodeIntegration(
              organizationId, node, integrationId,
            );
          }

          await prisma.pipelineNode.update({
            where: { id: node.id },
            data: {
              name: node.name,
              layer: node.layer,
              toolType: node.toolType,
              config: cachedData ? { _cached: cachedData } : undefined,
              positionX: node.positionX,
              positionY: node.positionY,
              status: node.status,
              ...(integrationId ? { integrationId } : {}),
            },
          });
          nodeIdMap.set(node.id, node.id);
        } else {
          // Create new node
          let integrationId: string | null = null;
          if (hasRealCredentials(node.config)) {
            integrationId = await upsertNodeIntegration(organizationId, node);
          }

          const created = await prisma.pipelineNode.create({
            data: {
              name: node.name,
              layer: node.layer,
              toolType: node.toolType,
              config: cachedData ? { _cached: cachedData } : undefined,
              positionX: node.positionX,
              positionY: node.positionY,
              status: node.status,
              stackId: id,
              ...(integrationId ? { integrationId } : {}),
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
