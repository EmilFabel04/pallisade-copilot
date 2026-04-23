/**
 * dbt Integration API
 * 
 * POST /api/integrations/dbt - Analyze a dbt project
 * GET /api/integrations/dbt - Get dbt analysis results
 */

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { scannerClient } from '@/lib/scanner-client';

interface DbtAnalysisResult {
  project_name: string;
  dbt_version: string;
  total_models: number;
  total_sources: number;
  total_tests: number;
  test_coverage: {
    model_coverage_pct: number;
    tested_models: number;
    untested_models: string[];
  };
  documentation_coverage: {
    model_doc_coverage_pct: number;
    undocumented_models: string[];
  };
  freshness_config: {
    freshness_coverage_pct: number;
    configured_sources: any[];
    unconfigured_sources: any[];
  };
  test_recommendations: any[];
  findings: any[];
}

export async function POST(req: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.email) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email },
      select: { id: true, organizationId: true },
    });

    if (!user) {
      return NextResponse.json({ error: 'User not found' }, { status: 404 });
    }

    const body = await req.json();
    const { project_path, warehouse_integration_id, action } = body;

    // Action: analyze - Run dbt project analysis
    if (action === 'analyze') {
      // Call the scanner's dbt analysis endpoint
      const response = await scannerClient.fetch(session, '/api/dbt/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_path,
          warehouse_integration_id,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        return NextResponse.json({ error: error.detail || 'Analysis failed' }, { status: 500 });
      }

      const analysis: DbtAnalysisResult = await response.json();
      return NextResponse.json({ success: true, analysis });
    }

    // Action: test_freshness - Run dbt source freshness check
    if (action === 'test_freshness') {
      // Get warehouse credentials
      if (!warehouse_integration_id) {
        return NextResponse.json({ error: 'warehouse_integration_id required' }, { status: 400 });
      }

      const warehouseIntegration = await prisma.integration.findUnique({
        where: { id: warehouse_integration_id },
        select: { type: true, credentials: true },
      });

      if (!warehouseIntegration) {
        return NextResponse.json({ error: 'Warehouse integration not found' }, { status: 404 });
      }

      const response = await scannerClient.fetch(session, '/api/dbt/freshness', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_path,
          warehouse_type: warehouseIntegration.type,
          warehouse_credentials: warehouseIntegration.credentials,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        return NextResponse.json({ error: error.detail || 'Freshness check failed' }, { status: 500 });
      }

      const freshnessResults = await response.json();
      return NextResponse.json({ success: true, freshness: freshnessResults });
    }

    // Action: run_tests - Run dbt tests
    if (action === 'run_tests') {
      if (!warehouse_integration_id) {
        return NextResponse.json({ error: 'warehouse_integration_id required' }, { status: 400 });
      }

      const warehouseIntegration = await prisma.integration.findUnique({
        where: { id: warehouse_integration_id },
        select: { type: true, credentials: true },
      });

      if (!warehouseIntegration) {
        return NextResponse.json({ error: 'Warehouse integration not found' }, { status: 404 });
      }

      const response = await scannerClient.fetch(session, '/api/dbt/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_path,
          warehouse_type: warehouseIntegration.type,
          warehouse_credentials: warehouseIntegration.credentials,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        return NextResponse.json({ error: error.detail || 'Test run failed' }, { status: 500 });
      }

      const testResults = await response.json();
      return NextResponse.json({ success: true, tests: testResults });
    }

    // Default: Save dbt integration
    const integration = await prisma.integration.create({
      data: {
        organizationId: user.organizationId || '',
        type: 'DBT_CORE',
        name: body.name || 'dbt Project',
        status: 'ACTIVE',
        credentials: {
          project_path,
          warehouse_integration_id,
          target: body.target || 'dev',
        },
      },
    });

    return NextResponse.json({ success: true, integration });
  } catch (error: any) {
    console.error('dbt integration error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function GET(req: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.email) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email },
      select: { organizationId: true },
    });

    // Get all dbt integrations
    const dbtIntegrations = await prisma.integration.findMany({
      where: {
        organizationId: user?.organizationId || '',
        type: { in: ['DBT_CORE', 'DBT_CLOUD'] },
        status: 'ACTIVE',
      },
      select: {
        id: true,
        name: true,
        type: true,
        credentials: true,
        createdAt: true,
      },
    });

    return NextResponse.json({ integrations: dbtIntegrations });
  } catch (error: any) {
    console.error('Error fetching dbt integrations:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

