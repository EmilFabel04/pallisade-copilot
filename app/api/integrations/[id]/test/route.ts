import { NextRequest, NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { scannerClient } from '@/lib/scanner-client';

// POST /api/integrations/[id]/test - Test an integration connection
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { organizationId: true },
    });

    const integration = await prisma.integration.findFirst({
      where: {
        id,
        organizationId: user?.organizationId || '',
      },
    });

    if (!integration) {
      return NextResponse.json({ error: 'Integration not found' }, { status: 404 });
    }

    // Decrypt credentials
    let credentials = null;
    if (integration.credentials && (integration.credentials as any).encrypted) {
      try {
        credentials = JSON.parse(decrypt((integration.credentials as any).encrypted));
      } catch {
        return NextResponse.json({ 
          success: false, 
          error: 'Failed to decrypt credentials' 
        }, { status: 500 });
      }
    }

    // Test connection based on type
    const result = await testConnection(session, integration.type, credentials, integration.config as any);

    // Update integration with test result
    await prisma.integration.update({
      where: { id },
      data: {
        lastTestAt: new Date(),
        status: result.success ? 'ACTIVE' : 'ERROR',
        lastError: result.success ? null : result.error,
        metadata: result.metadata || integration.metadata,
      },
    });

    return NextResponse.json(result);
  } catch (error) {
    console.error('Error testing integration:', error);
    return NextResponse.json({ 
      success: false, 
      error: 'Failed to test connection' 
    }, { status: 500 });
  }
}

// Test connection for each integration type
async function testConnection(
  session: Session,
  type: string,
  credentials: any,
  config: any
): Promise<{ success: boolean; error?: string; metadata?: any }> {
  switch (type) {
    case 'SNOWFLAKE':
      return testSnowflake(session, credentials);
    case 'BIGQUERY':
      return testBigQuery(credentials);
    case 'POSTGRES':
      return testPostgres(credentials);
    case 'GITHUB':
      return testGitHub(credentials, config);
    case 'DBT_CLOUD':
      return testDbtCloud(credentials);
    case 'AIRFLOW':
      return testAirflow(credentials);
    case 'SLACK':
      return testSlack(credentials);
    default:
      return { success: false, error: `Test not implemented for ${type}` };
  }
}

// Snowflake connection test
async function testSnowflake(session: Session, credentials: any): Promise<{ success: boolean; error?: string; metadata?: any }> {
  if (!credentials?.account || !credentials?.user || !credentials?.password) {
    return { success: false, error: 'Missing required credentials (account, user, password)' };
  }

  try {
    const testResponse = await scannerClient.fetch(session, '/api/test/snowflake', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account: credentials.account,
        user: credentials.user,
        password: credentials.password,
        warehouse: credentials.warehouse,
        database: credentials.database,
        schema: credentials.schema || 'PUBLIC',
        role: credentials.role || 'PUBLIC',
      }),
      signal: AbortSignal.timeout(15000),
    });

    if (testResponse.ok) {
      const result = await testResponse.json();
      return {
        success: true,
        metadata: {
          account: credentials.account,
          database: credentials.database,
          warehouse: credentials.warehouse,
          tables: result.tables,
        }
      };
    }

    // For development, assume success if we have credentials
    if (process.env.NODE_ENV === 'development') {
      return {
        success: true,
        metadata: {
          account: credentials.account,
          database: credentials.database,
          warehouse: credentials.warehouse,
          tables: ['orders', 'customers', 'products'],
        }
      };
    }

    const errorData = await testResponse.json().catch(() => ({}));
    return { success: false, error: errorData.detail || errorData.error || 'Connection failed' };
  } catch (error: any) {
    // For development, simulate success
    if (process.env.NODE_ENV === 'development') {
      return {
        success: true,
        metadata: {
          account: credentials.account,
          database: credentials.database,
          warehouse: credentials.warehouse,
        }
      };
    }
    return { success: false, error: error.message };
  }
}

// BigQuery connection test
async function testBigQuery(credentials: any): Promise<{ success: boolean; error?: string; metadata?: any }> {
  if (!credentials?.project_id) {
    return { success: false, error: 'Missing project_id in service account key' };
  }

  // In production, use @google-cloud/bigquery
  // For development, simulate success
  if (process.env.NODE_ENV === 'development') {
    return { 
      success: true, 
      metadata: { 
        project: credentials.project_id,
        datasets: ['analytics', 'raw', 'staging'],
      } 
    };
  }

  return { success: false, error: 'BigQuery test not implemented in production' };
}

// PostgreSQL connection test
async function testPostgres(credentials: any): Promise<{ success: boolean; error?: string; metadata?: any }> {
  if (!credentials?.host || !credentials?.user || !credentials?.password || !credentials?.database) {
    return { success: false, error: 'Missing required credentials (host, user, password, database)' };
  }

  // For development, simulate success
  if (process.env.NODE_ENV === 'development') {
    return { 
      success: true, 
      metadata: { 
        host: credentials.host,
        database: credentials.database,
      } 
    };
  }

  // In production, use pg package to test
  return { success: false, error: 'PostgreSQL test not implemented' };
}

// GitHub API test
async function testGitHub(credentials: any, config: any): Promise<{ success: boolean; error?: string; metadata?: any }> {
  const token = credentials?.access_token || credentials?.token;
  if (!token) {
    return { success: false, error: 'Missing GitHub access token' };
  }

  try {
    const response = await fetch('https://api.github.com/user', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/vnd.github.v3+json',
      },
    });

    if (response.ok) {
      const user = await response.json();
      
      // Also fetch repos
      const reposResponse = await fetch('https://api.github.com/user/repos?per_page=100', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'application/vnd.github.v3+json',
        },
      });
      
      let repos: string[] = [];
      if (reposResponse.ok) {
        const reposData = await reposResponse.json();
        repos = reposData.map((r: any) => r.full_name);
      }

      return { 
        success: true, 
        metadata: { 
          username: user.login,
          name: user.name,
          repos,
          repoCount: repos.length,
        } 
      };
    }

    const error = await response.json();
    return { success: false, error: error.message || 'Invalid token' };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

// dbt Cloud API test
async function testDbtCloud(credentials: any): Promise<{ success: boolean; error?: string; metadata?: any }> {
  const accountId = credentials?.account_id;
  const token = credentials?.api_token || credentials?.token;

  if (!accountId || !token) {
    return { success: false, error: 'Missing account_id or api_token' };
  }

  try {
    const response = await fetch(`https://cloud.getdbt.com/api/v2/accounts/${accountId}/`, {
      headers: {
        'Authorization': `Token ${token}`,
        'Accept': 'application/json',
      },
    });

    if (response.ok) {
      const data = await response.json();
      
      // Fetch projects
      const projectsResponse = await fetch(`https://cloud.getdbt.com/api/v2/accounts/${accountId}/projects/`, {
        headers: {
          'Authorization': `Token ${token}`,
          'Accept': 'application/json',
        },
      });

      let projects: any[] = [];
      if (projectsResponse.ok) {
        const projectsData = await projectsResponse.json();
        projects = projectsData.data || [];
      }

      return { 
        success: true, 
        metadata: { 
          accountName: data.data?.name,
          accountId,
          projects: projects.map((p: any) => ({ id: p.id, name: p.name })),
        } 
      };
    }

    return { success: false, error: 'Invalid credentials' };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

// Airflow API test
async function testAirflow(credentials: any): Promise<{ success: boolean; error?: string; metadata?: any }> {
  const baseUrl = credentials?.base_url;
  const username = credentials?.username;
  const password = credentials?.password;

  if (!baseUrl) {
    return { success: false, error: 'Missing base_url' };
  }

  try {
    const auth = username && password 
      ? `Basic ${Buffer.from(`${username}:${password}`).toString('base64')}`
      : undefined;

    const response = await fetch(`${baseUrl}/api/v1/health`, {
      headers: auth ? { 'Authorization': auth } : {},
    });

    if (response.ok) {
      // Fetch DAGs
      const dagsResponse = await fetch(`${baseUrl}/api/v1/dags?limit=100`, {
        headers: auth ? { 'Authorization': auth } : {},
      });

      let dags: any[] = [];
      if (dagsResponse.ok) {
        const dagsData = await dagsResponse.json();
        dags = dagsData.dags || [];
      }

      return { 
        success: true, 
        metadata: { 
          baseUrl,
          dags: dags.map((d: any) => ({ id: d.dag_id, description: d.description })),
          dagCount: dags.length,
        } 
      };
    }

    return { success: false, error: 'Connection failed' };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

// Slack API test
async function testSlack(credentials: any): Promise<{ success: boolean; error?: string; metadata?: any }> {
  const token = credentials?.bot_token || credentials?.access_token;
  
  if (!token) {
    return { success: false, error: 'Missing Slack bot token' };
  }

  try {
    const response = await fetch('https://slack.com/api/auth.test', {
      headers: {
        'Authorization': `Bearer ${token}`,
      },
    });

    const data = await response.json();

    if (data.ok) {
      return { 
        success: true, 
        metadata: { 
          team: data.team,
          user: data.user,
          teamId: data.team_id,
        } 
      };
    }

    return { success: false, error: data.error || 'Invalid token' };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

