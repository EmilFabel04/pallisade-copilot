import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

/**
 * GET /api/pipeline/health
 * 
 * Get aggregated pipeline health from all layers (Ingestion, Transformation, Warehouse, Reporting)
 * Uses the new PipelineStack/PipelineNode architecture
 */
export async function GET(req: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Organization not found' }, { status: 404 });
    }

    // Get all pipeline stacks for this organization
    const pipelineStacks = await prisma.pipelineStack.findMany({
      where: { organizationId: user.organizationId },
      include: {
        nodes: true,
        edges: true,
        scans: {
          orderBy: { createdAt: 'desc' },
          take: 1,
          include: {
            findings: true,
          },
        },
      },
    });

    // If no pipeline stacks, return empty state
    if (pipelineStacks.length === 0) {
      return NextResponse.json({
        hasStack: false,
        overallScore: 0,
        overallStatus: 'NOT_CONFIGURED',
        layerHealth: {},
        totalNodes: 0,
        totalErrors: 0,
        layers: {},
        stacks: [],
      });
    }

    // Aggregate health across all stacks
    const aggregatedHealth = aggregatePipelineHealth(pipelineStacks);

    return NextResponse.json({
      hasStack: true,
      ...aggregatedHealth,
      stacks: pipelineStacks.map(stack => ({
        id: stack.id,
        name: stack.name,
        healthScore: stack.healthScore || 0,
        status: stack.status,
        nodeCount: stack.nodes.length,
        lastScanAt: stack.lastScanAt,
      })),
    });
  } catch (error) {
    console.error('Pipeline health error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch pipeline health' },
      { status: 500 }
    );
  }
}

/**
 * Aggregate health metrics from all pipeline stacks
 */
function aggregatePipelineHealth(stacks: any[]) {
  const layerHealth: Record<string, { 
    score: number; 
    status: string; 
    nodeCount: number; 
    errorCount: number;
    tools: string[];
  }> = {
    INGESTION: { score: 100, status: 'HEALTHY', nodeCount: 0, errorCount: 0, tools: [] },
    TRANSFORMATION: { score: 100, status: 'HEALTHY', nodeCount: 0, errorCount: 0, tools: [] },
    WAREHOUSE: { score: 100, status: 'HEALTHY', nodeCount: 0, errorCount: 0, tools: [] },
    REPORTING: { score: 100, status: 'HEALTHY', nodeCount: 0, errorCount: 0, tools: [] },
  };

  let totalNodes = 0;
  let totalErrors = 0;
  let totalScore = 0;
  let stacksWithScore = 0;

  for (const stack of stacks) {
    // Aggregate nodes by layer
    for (const node of stack.nodes) {
      const layer = node.layer as string;
      if (layerHealth[layer]) {
        layerHealth[layer].nodeCount++;
        layerHealth[layer].tools.push(node.toolType);
        totalNodes++;

        // Check node status for errors
        if (node.status === 'ERROR') {
          layerHealth[layer].errorCount++;
          totalErrors++;
        } else if (node.status === 'WARNING') {
          layerHealth[layer].errorCount += 0.5; // Partial count for warnings
        }
      }
    }

    // Get findings from most recent scan
    if (stack.scans.length > 0) {
      const latestScan = stack.scans[0];
      for (const finding of latestScan.findings) {
        // Find the node for this finding
        const node = stack.nodes.find((n: any) => n.id === finding.nodeId);
        if (node && layerHealth[node.layer]) {
          if (finding.severity === 'critical' || finding.severity === 'high') {
            layerHealth[node.layer].errorCount++;
            totalErrors++;
          }
        }
      }
    }

    // Aggregate stack score
    if (stack.healthScore !== null) {
      totalScore += stack.healthScore;
      stacksWithScore++;
    }
  }

  // Calculate layer scores based on error counts
  for (const layer of Object.keys(layerHealth)) {
    const lh = layerHealth[layer];
    if (lh.nodeCount > 0) {
      // Score decreases with more errors
      const errorRatio = lh.errorCount / lh.nodeCount;
      lh.score = Math.max(0, Math.round(100 * (1 - errorRatio)));
      
      // Determine status
      if (lh.score >= 80) {
        lh.status = 'HEALTHY';
      } else if (lh.score >= 50) {
        lh.status = 'WARNING';
      } else {
        lh.status = 'ERROR';
      }
    } else {
      lh.status = 'NOT_CONFIGURED';
      lh.score = 0;
    }
    
    // Unique tools
    lh.tools = [...new Set(lh.tools)];
  }

  // Calculate overall score
  const overallScore = stacksWithScore > 0 
    ? Math.round(totalScore / stacksWithScore)
    : calculateOverallFromLayers(layerHealth);

  // Determine overall status
  let overallStatus = 'HEALTHY';
  if (overallScore < 50) {
    overallStatus = 'ERROR';
  } else if (overallScore < 80) {
    overallStatus = 'WARNING';
  }

  return {
    overallScore,
    overallStatus,
    layerHealth,
    totalNodes,
    totalErrors: Math.round(totalErrors),
  };
}

function calculateOverallFromLayers(layerHealth: Record<string, any>): number {
  const layers = Object.values(layerHealth).filter(l => l.nodeCount > 0);
  if (layers.length === 0) return 0;
  
  const totalScore = layers.reduce((sum, l) => sum + l.score, 0);
  return Math.round(totalScore / layers.length);
}
