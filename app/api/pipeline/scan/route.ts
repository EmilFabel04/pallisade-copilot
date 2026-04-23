/**
 * Pipeline Scan API
 * 
 * Trigger a full pipeline scan across all configured nodes
 */

import { NextRequest, NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import { auth } from '@/auth';
import { prisma } from '@/lib/db';
import { scannerClient } from '@/lib/scanner-client';

export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = session.user.organizationId;
    const body = await request.json();
    const { stackId } = body;

    // Get the pipeline stack with nodes
    const stack = await prisma.pipelineStack.findUnique({
      where: { id: stackId },
      include: { nodes: true },
    });

    if (!stack || stack.organizationId !== organizationId) {
      return NextResponse.json({ error: 'Pipeline not found' }, { status: 404 });
    }

    // Check that nodes are configured
    const configuredNodes = stack.nodes.filter(n => n.config !== null);
    if (configuredNodes.length === 0) {
      return NextResponse.json(
        { error: 'No configured nodes. Please configure at least one node before scanning.' },
        { status: 400 }
      );
    }

    // Create a pipeline scan record
    const scan = await prisma.pipelineScan.create({
      data: {
        stackId: stack.id,
        status: 'RUNNING',
        layersScanned: [...new Set(configuredNodes.map(n => n.layer))],
        nodesScanned: configuredNodes.length,
      },
    });

    // Update stack status
    await prisma.pipelineStack.update({
      where: { id: stackId },
      data: { status: 'SCANNING' },
    });

    // Start scanning each node asynchronously
    // In production, this would be handled by a job queue
    scanNodesInBackground(stack.id, scan.id, configuredNodes, organizationId, session);

    return NextResponse.json({
      success: true,
      scanId: scan.id,
      message: `Scanning ${configuredNodes.length} nodes across pipeline...`,
    });
  } catch (error) {
    console.error('Pipeline scan failed:', error);
    return NextResponse.json(
      { error: 'Failed to start pipeline scan' },
      { status: 500 }
    );
  }
}

// Background scan function
async function scanNodesInBackground(
  stackId: string,
  scanId: string,
  nodes: any[],
  organizationId: string,
  session: Session
) {
  const startTime = Date.now();
  let totalFindings = 0;
  let criticalCount = 0;
  let highCount = 0;
  let mediumCount = 0;
  let lowCount = 0;
  let healthScoreSum = 0;
  let scannedCount = 0;

  try {
    for (const node of nodes) {
      try {
        // Scan based on layer
        let findings: any[] = [];
        let nodeHealth = 100;

        switch (node.layer) {
          case 'WAREHOUSE':
            // Use existing warehouse scanners
            findings = await scanWarehouse(node, session);
            break;

          case 'TRANSFORMATION':
            // Scan dbt/transformation layer
            findings = await scanTransformation(node);
            break;

          case 'INGESTION':
            // Scan ingestion layer
            findings = await scanIngestion(node);
            break;

          case 'REPORTING':
            // Scan reporting layer
            findings = await scanReporting(node);
            break;
        }

        // Calculate node health based on findings
        const nodeCritical = findings.filter(f => f.severity === 'critical').length;
        const nodeHigh = findings.filter(f => f.severity === 'high').length;
        const nodeMedium = findings.filter(f => f.severity === 'medium').length;
        const nodeLow = findings.filter(f => f.severity === 'low').length;

        nodeHealth = Math.max(0, 100 - (nodeCritical * 25) - (nodeHigh * 10) - (nodeMedium * 3) - (nodeLow * 1));

        // Update node
        await prisma.pipelineNode.update({
          where: { id: node.id },
          data: {
            status: findings.length === 0 ? 'HEALTHY' : 
                   nodeCritical > 0 ? 'ERROR' :
                   nodeHigh > 0 ? 'WARNING' : 'HEALTHY',
            healthScore: nodeHealth,
            lastScanAt: new Date(),
            findingsCount: findings.length,
            criticalCount: nodeCritical,
            highCount: nodeHigh,
          },
        });

        // Create findings in DB
        for (const finding of findings) {
          await prisma.pipelineNodeFinding.create({
            data: {
              nodeId: node.id,
              scanId: scanId,
              type: finding.type,
              severity: finding.severity.toUpperCase(),
              title: finding.title,
              description: finding.description,
              suggestedFix: finding.suggestedFix,
              rootCauseNodeId: finding.rootCauseNodeId,
              rootCauseType: finding.rootCauseType,
            },
          });
        }

        // Aggregate totals
        totalFindings += findings.length;
        criticalCount += nodeCritical;
        highCount += nodeHigh;
        mediumCount += nodeMedium;
        lowCount += nodeLow;
        healthScoreSum += nodeHealth;
        scannedCount++;

      } catch (nodeError) {
        console.error(`Error scanning node ${node.id}:`, nodeError);
        
        // Mark node as error
        await prisma.pipelineNode.update({
          where: { id: node.id },
          data: {
            status: 'ERROR',
            lastError: nodeError instanceof Error ? nodeError.message : 'Scan failed',
            lastScanAt: new Date(),
          },
        });
      }
    }

    // Calculate overall health
    const avgHealth = scannedCount > 0 ? healthScoreSum / scannedCount : 0;

    // Update scan record
    await prisma.pipelineScan.update({
      where: { id: scanId },
      data: {
        status: 'COMPLETED',
        completedAt: new Date(),
        durationMs: Date.now() - startTime,
        totalFindings,
        criticalCount,
        highCount,
        mediumCount,
        lowCount,
        healthScore: avgHealth,
      },
    });

    // Update stack
    await prisma.pipelineStack.update({
      where: { id: stackId },
      data: {
        status: criticalCount > 0 ? 'ERROR' : 'READY',
        healthScore: avgHealth,
        lastScanAt: new Date(),
      },
    });

  } catch (error) {
    console.error('Pipeline scan background job failed:', error);
    
    await prisma.pipelineScan.update({
      where: { id: scanId },
      data: {
        status: 'FAILED',
        completedAt: new Date(),
        durationMs: Date.now() - startTime,
        errorMessage: error instanceof Error ? error.message : 'Scan failed',
      },
    });

    await prisma.pipelineStack.update({
      where: { id: stackId },
      data: { status: 'ERROR' },
    });
  }
}

// Warehouse scanning
async function scanWarehouse(node: any, session: Session): Promise<any[]> {
  const findings: any[] = [];

  try {
    // Map tool type to scanner connection type
    const connectionTypeMap: Record<string, string> = {
      snowflake: 'snowflake',
      bigquery: 'bigquery',
      postgres: 'postgres',
      redshift: 'redshift',
      sqlserver: 'sqlserver',
      azure_sql: 'sqlserver',
    };

    const connectionType = connectionTypeMap[node.toolType];
    if (!connectionType || !node.config) return findings;

    // Run quality scan
    const scanResponse = await scannerClient.fetch(session, '/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        customer_id: 'pipeline-scan',
        connection_type: connectionType,
        connection_config: node.config,
        scan_types: ['quality', 'freshness', 'volume', 'anomaly'],
      }),
    });

    if (scanResponse.ok) {
      const scanResult = await scanResponse.json();
      if (scanResult.results) {
        for (const [scanType, result] of Object.entries(scanResult.results)) {
          const scanFindings = (result as any).findings || [];
          findings.push(...scanFindings.map((f: any) => ({
            type: f.type || scanType,
            severity: f.severity || 'medium',
            title: f.title || f.message,
            description: f.description || f.message,
            suggestedFix: f.suggested_fix || f.auto_fix,
          })));
        }
      }
    }
  } catch (error) {
    console.error('Warehouse scan error:', error);
  }

  return findings;
}

// Transformation layer scanning
async function scanTransformation(node: any): Promise<any[]> {
  const findings: any[] = [];

  try {
    if (node.toolType === 'dbt_core' && node.config?.manifest) {
      // Parse dbt manifest and analyze
      const manifest = JSON.parse(node.config.manifest);
      
      // Check test coverage
      const models = Object.keys(manifest.nodes).filter(k => k.startsWith('model.'));
      const tests = Object.keys(manifest.nodes).filter(k => k.startsWith('test.'));
      
      const testCoverage = models.length > 0 ? (tests.length / models.length) * 100 : 0;
      
      if (testCoverage < 50) {
        findings.push({
          type: 'test_coverage',
          severity: testCoverage < 25 ? 'high' : 'medium',
          title: 'Low dbt Test Coverage',
          description: `Only ${testCoverage.toFixed(0)}% of models have tests. Consider adding more data tests.`,
          suggestedFix: {
            type: 'dbt',
            action: 'Add schema tests',
            code: `# Add to schema.yml\nmodels:\n  - name: your_model\n    columns:\n      - name: id\n        tests:\n          - unique\n          - not_null`,
          },
        });
      }

      // Check for models without descriptions
      const modelsWithoutDesc = models.filter(m => 
        !manifest.nodes[m].description || manifest.nodes[m].description.trim() === ''
      );
      
      if (modelsWithoutDesc.length > models.length * 0.5) {
        findings.push({
          type: 'documentation',
          severity: 'low',
          title: 'Missing Model Documentation',
          description: `${modelsWithoutDesc.length} of ${models.length} models lack descriptions.`,
          suggestedFix: {
            type: 'dbt',
            action: 'Add descriptions to schema.yml',
          },
        });
      }
    }

    if (node.toolType === 'dbt_cloud') {
      // Check dbt Cloud job status
      // In production, call dbt Cloud API
      // For now, return empty
    }
  } catch (error) {
    console.error('Transformation scan error:', error);
  }

  return findings;
}

// Ingestion layer scanning
async function scanIngestion(node: any): Promise<any[]> {
  const findings: any[] = [];

  try {
    if (node.toolType === 'fivetran' && node.config) {
      // Call Fivetran API to check connector status
      const auth = Buffer.from(`${node.config.api_key}:${node.config.api_secret}`).toString('base64');
      
      const res = await fetch('https://api.fivetran.com/v1/groups', {
        headers: { Authorization: `Basic ${auth}` },
      });

      if (res.ok) {
        const data = await res.json();
        
        // Check each group's connectors
        for (const group of data.data?.items || []) {
          const connectorsRes = await fetch(`https://api.fivetran.com/v1/groups/${group.id}/connectors`, {
            headers: { Authorization: `Basic ${auth}` },
          });

          if (connectorsRes.ok) {
            const connectors = await connectorsRes.json();
            
            for (const connector of connectors.data?.items || []) {
              // Check sync status
              if (connector.status?.sync_state === 'sync_failed') {
                findings.push({
                  type: 'sync_failed',
                  severity: 'critical',
                  title: `Fivetran Sync Failed: ${connector.schema}`,
                  description: `Connector "${connector.schema}" has failed syncs.`,
                  suggestedFix: {
                    type: 'manual',
                    action: 'Check Fivetran dashboard for error details',
                  },
                });
              }

              // Check if paused
              if (connector.paused) {
                findings.push({
                  type: 'connector_paused',
                  severity: 'medium',
                  title: `Fivetran Connector Paused: ${connector.schema}`,
                  description: `Connector "${connector.schema}" is paused. Data is not being synced.`,
                  suggestedFix: {
                    type: 'api',
                    action: 'Resume connector via Fivetran API or dashboard',
                  },
                });
              }
            }
          }
        }
      }
    }
  } catch (error) {
    console.error('Ingestion scan error:', error);
  }

  return findings;
}

// Reporting layer scanning
async function scanReporting(node: any): Promise<any[]> {
  const findings: any[] = [];

  // Reporting layer scans would check:
  // - Dashboard query errors
  // - Stale dashboards
  // - Broken data sources
  // For now, return placeholder findings for demo

  try {
    if (node.toolType === 'tableau' || node.toolType === 'looker' || node.toolType === 'powerbi') {
      // In production, call respective APIs to check dashboard health
      // For demo, return empty
    }
  } catch (error) {
    console.error('Reporting scan error:', error);
  }

  return findings;
}
